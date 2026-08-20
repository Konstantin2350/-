import asyncio

import httpx
from celery import Celery

from orchestra.config import get_settings


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
    autoretry_for=(httpx.HTTPError,),
    retry_backoff=True,
    retry_kwargs={"max_retries": 5},
)
def run_agent(payload: dict) -> dict:
    async def execute() -> dict:
        headers = {"x-api-key": settings.api_key} if settings.api_key else {}
        async with httpx.AsyncClient(timeout=120) as client:
            response = await client.post(
                f"{settings.internal_api_url.rstrip('/')}/v1/orchestrate",
                json=payload,
                headers=headers,
            )
            response.raise_for_status()
            return response.json()

    return asyncio.run(execute())
