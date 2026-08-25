from typing import Any

import httpx

from orchestra.config import Settings


class Bitrix24Client:
    """Restricted Bitrix24 REST client with native batch support."""

    allowed_methods = {
        "batch",
        "crm.lead.add",
        "crm.lead.update",
        "crm.lead.get",
        "crm.lead.list",
        "crm.deal.add",
        "crm.deal.update",
        "crm.deal.get",
        "crm.deal.list",
        "crm.contact.add",
        "crm.contact.update",
        "crm.contact.get",
        "crm.contact.list",
        "crm.company.add",
        "crm.company.update",
        "crm.company.get",
        "crm.company.list",
        "crm.item.add",
        "crm.item.update",
        "crm.item.get",
        "crm.item.list",
        "crm.timeline.comment.add",
        "tasks.task.add",
        "tasks.task.update",
        "tasks.task.get",
        "tasks.task.list",
        "task.checklistitem.add",
        "im.message.add",
        "user.get",
        "calendar.event.add",
        "calendar.event.update",
        "calendar.event.get",
        "bizproc.workflow.start",
    }

    def __init__(self, settings: Settings) -> None:
        self.webhook_url = (
            settings.bitrix_webhook_url.rstrip("/") if settings.bitrix_webhook_url else None
        )

    def validate_method(self, method: str) -> None:
        if method not in self.allowed_methods:
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

    async def batch(self, calls: list[tuple[str, dict[str, Any]]]) -> dict[str, Any]:
        if len(calls) > 50:
            raise ValueError("Bitrix24 supports at most 50 commands per batch")
        command: dict[str, str] = {}
        for index, (method, params) in enumerate(calls):
            self.validate_method(method)
            query = httpx.QueryParams(params)
            command[f"cmd_{index}"] = f"{method}?{query}"
        return await self.call("batch", {"halt": 0, "cmd": command})


class WazzupClient:
    """Minimal Wazzup transport for Telegram/WhatsApp replies and webhook setup."""

    def __init__(self, settings: Settings) -> None:
        self.base_url = settings.wazzup_api_base_url.rstrip("/")
        self.api_key = settings.wazzup_api_key

    @property
    def enabled(self) -> bool:
        return bool(self.api_key)

    async def send_message(
        self,
        *,
        channel_id: str,
        chat_type: str,
        chat_id: str,
        text: str,
        crm_message_id: str,
    ) -> dict[str, Any]:
        if not self.api_key:
            raise RuntimeError("WAZZUP_API_KEY is not configured")
        async with httpx.AsyncClient(timeout=30) as client:
            response = await client.post(
                f"{self.base_url}/v3/message",
                headers={"Authorization": f"Bearer {self.api_key}"},
                json={
                    "channelId": channel_id,
                    "chatType": chat_type,
                    "chatId": chat_id,
                    "text": text,
                    "crmMessageId": crm_message_id,
                    "clearUnanswered": False,
                },
            )
            response.raise_for_status()
            return response.json()

    async def subscribe(self, webhook_url: str) -> dict[str, Any]:
        if not self.api_key:
            raise RuntimeError("WAZZUP_API_KEY is not configured")
        async with httpx.AsyncClient(timeout=30) as client:
            response = await client.patch(
                f"{self.base_url}/v3/webhooks",
                headers={"Authorization": f"Bearer {self.api_key}"},
                json={
                    "webhooksUri": webhook_url,
                    "subscriptions": {
                        "messagesAndStatuses": True,
                        "contactsAndDealsCreation": False,
                        "channelsUpdates": True,
                    },
                },
            )
            response.raise_for_status()
            return response.json() if response.content else {"status": "configured"}


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
                    "enum": [
                        "crm",
                        "calls",
                        "chat",
                        "knowledge",
                        "tasks",
                        "content",
                        "finance",
                    ],
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
    {
        "name": "crm_extract",
        "description": "Extract safe CRM field updates and conflicting suggestions",
        "inputSchema": {
            "type": "object",
            "properties": {
                "text": {"type": "string"},
                "current_fields": {"type": "object"},
            },
            "required": ["text"],
        },
    },
    {
        "name": "call_analyze",
        "description": "Analyze a call transcript against a sales script",
        "inputSchema": {
            "type": "object",
            "properties": {
                "transcript": {"type": "string"},
                "sales_script": {"type": "array", "items": {"type": "string"}},
            },
            "required": ["transcript"],
        },
    },
    {
        "name": "process_from_text",
        "description": "Compile a natural-language workflow into validated Orchestra DSL",
        "inputSchema": {
            "type": "object",
            "properties": {"description": {"type": "string"}},
            "required": ["description"],
        },
    },
]
