import asyncio

from celery import Celery
from sqlalchemy.exc import OperationalError

from orchestra.agents import build_orchestrator
from orchestra.config import get_settings
from orchestra.infrastructure import ConversationMemory, Database
from orchestra.schemas import AgentRequest


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
    worker_prefetch_multiplier=1,
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
