from typing import Any

import httpx

from orchestra.config import Settings


class Bitrix24Client:
    """Restricted Bitrix24 REST client with native batch support."""

    allowed_prefixes = (
        "crm.",
        "tasks.",
        "task.",
        "im.",
        "user.",
        "calendar.",
        "bizproc.",
    )

    def __init__(self, settings: Settings) -> None:
        self.webhook_url = (
            settings.bitrix_webhook_url.rstrip("/")
            if settings.bitrix_webhook_url
            else None
        )

    def validate_method(self, method: str) -> None:
        if method != "batch" and not method.startswith(self.allowed_prefixes):
            raise ValueError("Bitrix24 method is not allowed")

    async def call(self, method: str, params: dict[str, Any]) -> dict[str, Any]:
        self.validate_method(method)
        if not self.webhook_url:
            raise RuntimeError("BITRIX_WEBHOOK_URL is not configured")
        async with httpx.AsyncClient(timeout=30) as client:
            response = await client.post(f"{self.webhook_url}/{method}.json", json=params)
            response.raise_for_status()
            payload = response.json()
        if "error" in payload:
            raise RuntimeError(
                f"Bitrix24 error {payload['error']}: {payload.get('error_description', '')}"
            )
        return payload

    async def batch(
        self, calls: list[tuple[str, dict[str, Any]]]
    ) -> dict[str, Any]:
        if len(calls) > 50:
            raise ValueError("Bitrix24 supports at most 50 commands per batch")
        command: dict[str, str] = {}
        for index, (method, params) in enumerate(calls):
            self.validate_method(method)
            query = httpx.QueryParams(params)
            command[f"cmd_{index}"] = f"{method}?{query}"
        return await self.call("batch", {"halt": 0, "cmd": command})


MCP_TOOLS = [
    {
        "name": "orchestra_agent",
        "description": "Route a business request to an ИИ-Оркестр specialist agent",
        "inputSchema": {
            "type": "object",
            "properties": {
                "message": {"type": "string"},
                "agent": {
                    "type": "string",
                    "enum": ["crm", "calls", "chat", "knowledge", "tasks", "content"],
                },
                "session_id": {"type": "string"},
            },
            "required": ["message"],
        },
    },
    {
        "name": "knowledge_search",
        "description": "Search the versioned company knowledge base with citations",
        "inputSchema": {
            "type": "object",
            "properties": {
                "question": {"type": "string"},
                "limit": {"type": "integer", "minimum": 1, "maximum": 20},
            },
            "required": ["question"],
        },
    },
]
