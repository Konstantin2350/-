import json
from pathlib import Path

from orchestra.agents import Orchestrator
from orchestra.config import Settings
from orchestra.schemas import (
    AgentRequest,
    EmployeeInvokeRequest,
    EmployeeProfile,
    EmployeeResponse,
)


class EmployeeRegistry:
    def __init__(self, settings: Settings, orchestrator: Orchestrator) -> None:
        self.orchestrator = orchestrator
        path = Path(settings.employee_config_path)
        if not path.exists():
            raise RuntimeError(f"Employee configuration not found: {path}")
        profiles = [
            EmployeeProfile.model_validate(item)
            for item in json.loads(path.read_text(encoding="utf-8"))
        ]
        if len({profile.id for profile in profiles}) != len(profiles):
            raise RuntimeError("Employee IDs must be unique")
        self.profiles = {profile.id: profile for profile in profiles}

    def list(self) -> list[EmployeeProfile]:
        return list(self.profiles.values())

    def get(self, employee_id: str) -> EmployeeProfile | None:
        return self.profiles.get(employee_id)

    async def invoke(
        self,
        employee_id: str,
        body: EmployeeInvokeRequest,
        user_id: str,
        tenant_id: str,
    ) -> EmployeeResponse:
        profile = self.get(employee_id)
        if not profile:
            raise KeyError(employee_id)
        context = {
            **body.context,
            "employee": {
                "id": profile.id,
                "name": profile.name,
                "role": profile.role,
                "skills": profile.skills,
            },
        }
        result = await self.orchestrator.execute(
            AgentRequest(
                message=body.message,
                session_id=body.session_id,
                user_id=user_id,
                tenant_id=tenant_id,
                agent=profile.primary_agent,
                context=context,
            )
        )
        return EmployeeResponse(employee=profile, result=result)
