import asyncio

from celery import Celery
from sqlalchemy.exc import OperationalError

from orchestra.agents import build_orchestrator
from orchestra.config import get_settings
from orchestra.infrastructure import ConversationMemory, Database
from orchestra.integrations import Bitrix24Client
from orchestra.schemas import AgentRequest
from orchestra.workflows import ActionEngine, ProcessEngine

settings = get_settings()
celery_app = Celery(
    "ai-orchestra",
    broker=settings.celery_broker_url,
    backend=settings.celery_result_backend,
)
celery_app.conf.update(
    task_serializer="json",
    result_serializer="json",
    accept_content=["json"],
    task_track_started=True,
    task_acks_late=True,
    task_reject_on_worker_lost=True,
    task_time_limit=600,
    task_soft_time_limit=540,
    result_expires=3_600,
    worker_prefetch_multiplier=1,
    worker_send_task_events=True,
)


@celery_app.task(name="orchestra.ping")
def ping() -> dict[str, str]:
    return {"status": "ok"}


@celery_app.task(
    name="orchestra.run_agent",
    autoretry_for=(OperationalError, OSError),
    retry_backoff=True,
    retry_kwargs={"max_retries": 5},
)
def run_agent(payload: dict) -> dict:
    async def execute() -> dict:
        database = Database(settings)
        memory = ConversationMemory(settings)
        orchestrator, _, _, _, _ = build_orchestrator(settings, database, memory)
        try:
            response = await orchestrator.execute(AgentRequest(**payload))
            return response.model_dump(mode="json")
        finally:
            await memory.close()
            await database.close()

    return asyncio.run(execute())


@celery_app.task(
    name="orchestra.execute_action",
    autoretry_for=(OperationalError, OSError),
    retry_backoff=True,
    retry_kwargs={"max_retries": 5},
)
def execute_action(action_id: str, tenant_id: str) -> dict:
    async def execute() -> dict:
        database = Database(settings)
        engine = ActionEngine(database, Bitrix24Client(settings))
        try:
            result = await engine.execute(action_id, tenant_id)
            return {"id": result.id, "status": result.status, "error": result.error}
        finally:
            await database.close()

    return asyncio.run(execute())


@celery_app.task(
    name="orchestra.resume_process_wait",
    autoretry_for=(OperationalError, OSError),
    retry_backoff=True,
    retry_kwargs={"max_retries": 5},
)
def resume_process_wait(instance_id: str, tenant_id: str) -> dict:
    async def execute() -> dict:
        database = Database(settings)
        memory = ConversationMemory(settings)
        orchestrator, _, _, _, _ = build_orchestrator(settings, database, memory)
        engine = ProcessEngine(database, orchestrator, settings)
        try:
            result = await engine.resume_wait(instance_id, tenant_id)
            return {"id": result.id, "status": result.status}
        finally:
            await memory.close()
            await database.close()

    return asyncio.run(execute())
