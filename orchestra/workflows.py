from typing import Any

from orchestra.agents import Orchestrator
from orchestra.config import Settings
from orchestra.infrastructure import (
    ActionRecord,
    Database,
    ProcessInstanceRecord,
)
from orchestra.integrations import Bitrix24Client
from orchestra.schemas import AgentRequest


class WorkflowConflict(RuntimeError):
    pass


class ActionEngine:
    def __init__(self, db: Database, bitrix: Bitrix24Client) -> None:
        self.db = db
        self.bitrix = bitrix

    async def confirm(
        self,
        action_id: str,
        tenant_id: str,
        payload_updates: dict[str, Any],
    ) -> ActionRecord:
        action = await self.db.get_action(action_id, tenant_id)
        if not action:
            raise KeyError(action_id)
        if action.status not in {"proposed", "confirmed"}:
            raise WorkflowConflict(f"Action cannot be confirmed from {action.status}")
        payload = {**action.payload, **payload_updates}
        updated = await self.db.update_action(
            action_id,
            tenant_id,
            status="confirmed",
            payload=payload,
            error=None,
        )
        assert updated
        return updated

    async def execute(self, action_id: str, tenant_id: str) -> ActionRecord:
        action = await self.db.get_action(action_id, tenant_id)
        if not action:
            raise KeyError(action_id)
        if action.status == "executed":
            return action
        if action.status != "confirmed":
            raise WorkflowConflict("Action requires confirmation before execution")
        if action.tool == "orchestra.task.create":
            return await self._execute_local_task(action, tenant_id)
        method = action.payload.get("method")
        params = action.payload.get("params", {})
        if not method:
            raise WorkflowConflict("Confirmed action must include Bitrix method and params")
        try:
            self.bitrix.validate_method(method)
        except ValueError as error:
            raise WorkflowConflict(str(error)) from error
        await self.db.update_action(action_id, tenant_id, status="executing", error=None)
        try:
            result = await self.bitrix.call(method, params)
        except Exception as error:
            failed = await self.db.update_action(
                action_id,
                tenant_id,
                status="failed",
                error=str(error)[:2_000],
            )
            assert failed
            return failed
        executed = await self.db.update_action(
            action_id,
            tenant_id,
            status="executed",
            result=result,
            error=None,
        )
        assert executed
        await self.db.append_event(
            "action.executed",
            action.actor,
            {"action_id": action.id, "tool": action.tool, "method": method},
            external_id=f"action:{action.id}:executed",
            tenant_id=tenant_id,
        )
        return executed

    async def _execute_local_task(self, action: ActionRecord, tenant_id: str) -> ActionRecord:
        task_data = action.payload.get("task")
        if not isinstance(task_data, dict) or not task_data.get("title"):
            raise WorkflowConflict("Local task action must include task data")
        values = {
            "project_id": task_data.get("project_id"),
            "title": str(task_data["title"])[:500],
            "description": str(task_data.get("description", ""))[:30_000],
            "status": "new",
            "priority": task_data.get("priority", "normal"),
            "deadline": task_data.get("deadline"),
            "assignee": task_data.get("assignee"),
            "progress": 0,
            "checklist": list(task_data.get("checklist", []))[:100],
            "risk_flags": list(task_data.get("risk_flags", []))[:100],
        }
        await self.db.update_action(action.id, tenant_id, status="executing", error=None)
        try:
            task = await self.db.create_task(tenant_id, values)
        except Exception as error:
            failed = await self.db.update_action(
                action.id,
                tenant_id,
                status="failed",
                error=str(error)[:2_000],
            )
            assert failed
            return failed
        executed = await self.db.update_action(
            action.id,
            tenant_id,
            status="executed",
            result={"task_id": task.id, "project_id": task.project_id},
            error=None,
        )
        assert executed
        await self.db.append_event(
            "action.executed",
            action.actor,
            {"action_id": action.id, "tool": action.tool, "task_id": task.id},
            external_id=f"action:{action.id}:executed",
            tenant_id=tenant_id,
        )
        return executed


class ProcessEngine:
    def __init__(
        self,
        db: Database,
        orchestrator: Orchestrator,
        settings: Settings,
    ) -> None:
        self.db = db
        self.orchestrator = orchestrator
        self.settings = settings

    async def start(
        self,
        process_id: str,
        tenant_id: str,
        actor: str,
        context: dict[str, Any],
    ) -> ProcessInstanceRecord:
        process = await self.db.get_process(process_id, tenant_id)
        if not process or not process.active:
            raise KeyError(process_id)
        instance = await self.db.create_process_instance(
            process_id, tenant_id, {**context, "_actor": actor}
        )
        return await self.advance(instance.id, tenant_id)

    async def advance(self, instance_id: str, tenant_id: str) -> ProcessInstanceRecord:
        instance = await self.db.get_process_instance(instance_id, tenant_id)
        if not instance:
            raise KeyError(instance_id)
        process = await self.db.get_process(instance.process_id, tenant_id)
        if not process:
            raise KeyError(instance.process_id)
        steps = process.definition.get("steps", [])
        history = list(instance.history)
        context = dict(instance.context)
        executed_now = 0
        while instance.current_step < len(steps):
            if executed_now >= self.settings.max_agent_steps:
                raise WorkflowConflict("Process exceeded MAX_AGENT_STEPS")
            step = steps[instance.current_step]
            step_type = step.get("type")
            if step_type == "human_approval":
                updated = await self.db.update_process_instance(
                    instance.id,
                    tenant_id,
                    status="waiting_approval",
                    history=history,
                )
                assert updated
                return updated
            if step_type == "wait":
                history.append({"step": instance.current_step, "type": "wait", "status": "waiting"})
                updated = await self.db.update_process_instance(
                    instance.id,
                    tenant_id,
                    status="waiting",
                    history=history,
                )
                assert updated
                return updated
            if step_type == "bitrix_call":
                action = await self.db.create_action(
                    tenant_id=tenant_id,
                    actor=context.get("_actor", "process"),
                    tool="bitrix.call",
                    payload={
                        "method": step.get("method"),
                        "params": step.get("params", {}),
                        "instruction": step.get("instruction"),
                    },
                    requires_confirmation=True,
                    idempotency_key=f"process:{instance.id}:step:{instance.current_step}",
                )
                history.append(
                    {
                        "step": instance.current_step,
                        "type": step_type,
                        "status": "action_proposed",
                        "action_id": action.id,
                    }
                )
                updated = await self.db.update_process_instance(
                    instance.id,
                    tenant_id,
                    status="waiting_action",
                    history=history,
                )
                assert updated
                return updated
            if step_type == "agent":
                response = await self.orchestrator.execute(
                    AgentRequest(
                        message=step.get("instruction", ""),
                        user_id=context.get("_actor", "process"),
                        tenant_id=tenant_id,
                        context=context,
                    )
                )
                history.append(
                    {
                        "step": instance.current_step,
                        "type": step_type,
                        "status": "completed",
                        "agent": response.agent,
                        "request_id": str(response.request_id),
                    }
                )
            elif step_type == "condition":
                condition_key = step.get("condition_key")
                passed = bool(context.get(condition_key)) if condition_key else True
                history.append(
                    {
                        "step": instance.current_step,
                        "type": step_type,
                        "status": "completed",
                        "passed": passed,
                    }
                )
            elif step_type == "notify":
                history.append(
                    {
                        "step": instance.current_step,
                        "type": step_type,
                        "status": "completed",
                        "message": step.get("instruction", ""),
                    }
                )
                await self.db.append_event(
                    "process.notification",
                    context.get("_actor", "process"),
                    {"instance_id": instance.id, "step": step},
                    tenant_id=tenant_id,
                )
            else:
                raise WorkflowConflict(f"Unsupported process step: {step_type}")
            instance.current_step += 1
            executed_now += 1
            updated = await self.db.update_process_instance(
                instance.id,
                tenant_id,
                current_step=instance.current_step,
                history=history,
                context=context,
            )
            assert updated
            instance = updated
        completed = await self.db.update_process_instance(
            instance.id,
            tenant_id,
            status="completed",
            history=history,
        )
        assert completed
        return completed

    async def approve(
        self,
        instance_id: str,
        tenant_id: str,
        approved: bool,
        comment: str | None,
    ) -> ProcessInstanceRecord:
        instance = await self.db.get_process_instance(instance_id, tenant_id)
        if not instance:
            raise KeyError(instance_id)
        if instance.status != "waiting_approval":
            raise WorkflowConflict("Process is not waiting for approval")
        history = list(instance.history)
        history.append(
            {
                "step": instance.current_step,
                "type": "human_approval",
                "status": "approved" if approved else "rejected",
                "comment": comment,
            }
        )
        if not approved:
            rejected = await self.db.update_process_instance(
                instance.id, tenant_id, status="failed", history=history
            )
            assert rejected
            return rejected
        updated = await self.db.update_process_instance(
            instance.id,
            tenant_id,
            status="running",
            current_step=instance.current_step + 1,
            history=history,
        )
        assert updated
        return await self.advance(instance.id, tenant_id)

    async def resume_after_action(self, instance_id: str, tenant_id: str) -> ProcessInstanceRecord:
        instance = await self.db.get_process_instance(instance_id, tenant_id)
        if not instance:
            raise KeyError(instance_id)
        if instance.status != "waiting_action" or not instance.history:
            raise WorkflowConflict("Process is not waiting for an action")
        action_id = instance.history[-1].get("action_id")
        action = await self.db.get_action(action_id, tenant_id) if action_id else None
        if not action or action.status != "executed":
            raise WorkflowConflict("Related action is not executed")
        updated = await self.db.update_process_instance(
            instance.id,
            tenant_id,
            status="running",
            current_step=instance.current_step + 1,
        )
        assert updated
        return await self.advance(instance.id, tenant_id)

    async def resume_wait(self, instance_id: str, tenant_id: str) -> ProcessInstanceRecord:
        instance = await self.db.get_process_instance(instance_id, tenant_id)
        if not instance:
            raise KeyError(instance_id)
        if instance.status != "waiting":
            raise WorkflowConflict("Process is not waiting")
        updated = await self.db.update_process_instance(
            instance.id,
            tenant_id,
            status="running",
            current_step=instance.current_step + 1,
        )
        assert updated
        return await self.advance(instance.id, tenant_id)
