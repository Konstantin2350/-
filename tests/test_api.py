import io
import math
import struct
import wave
from datetime import UTC, datetime, timedelta

from fastapi.testclient import TestClient

from orchestra.capabilities import AudioService
from orchestra.config import Settings
from orchestra.main import create_app


def make_client(tmp_path, **overrides) -> TestClient:
    settings = Settings(
        database_url=f"sqlite+aiosqlite:///{tmp_path / 'test.db'}",
        redis_url=None,
        llm_api_key=None,
        **overrides,
    )
    return TestClient(create_app(settings))


def test_health_and_readiness(tmp_path):
    with make_client(tmp_path) as client:
        health = client.get("/health")
        ready = client.get("/ready")

    assert health.status_code == 200
    assert health.json()["status"] == "ok"
    assert health.json()["llm"] == "local-fallback"
    assert ready.json() == {"status": "ready"}


def test_crm_extraction_does_not_overwrite_existing_fields(tmp_path):
    with make_client(tmp_path) as client:
        response = client.post(
            "/v1/crm/extract",
            json={
                "text": (
                    "Меня зовут Анна. Телефон +7 (999) 123-45-67, "
                    "email Anna@Example.com. Интересует тариф Бизнес, сумма 150 000 руб."
                ),
                "current_fields": {"email": "old@example.com"},
            },
        )

    assert response.status_code == 200
    payload = response.json()
    assert payload["entities"]["name"] == "Анна"
    assert payload["entities"]["amount"] == 150000
    assert payload["field_updates"]["phone"] == "+79991234567"
    assert "email" not in payload["field_updates"]
    assert payload["suggestions"]["email"] == "anna@example.com"


def test_call_intelligence_returns_script_gaps_and_actions(tmp_path):
    with make_client(tmp_path) as client:
        response = client.post(
            "/v1/calls/analyze",
            json={
                "transcript": (
                    "Здравствуйте, меня зовут Иван. Клиенту нужен тариф Бизнес. "
                    "Спасибо, подходит. Отправьте договор завтра."
                ),
                "sales_script": [
                    "поздороваться и представиться",
                    "уточнить потребность клиента",
                    "обсудить бюджет",
                ],
            },
        )

    assert response.status_code == 200
    payload = response.json()
    assert payload["sentiment"] == "positive"
    assert payload["action_items"] == ["Отправьте договор завтра."]
    assert "обсудить бюджет" in payload["missing_steps"]
    assert payload["crm"]["entities"]["name"] == "Иван"


def test_orchestrator_routes_task_and_builds_checklist(tmp_path):
    with make_client(tmp_path) as client:
        response = client.post(
            "/v1/orchestrate",
            json={
                "message": "Срочно создай задачу подготовить коммерческое предложение завтра",
                "context": {
                    "available_assignees": [
                        {"name": "Елена", "skills": ["финансы"], "load": 30},
                        {"name": "Анна", "skills": ["коммерческое предложение"], "load": 20},
                    ]
                },
            },
        )

    assert response.status_code == 200
    payload = response.json()
    assert payload["agent"] == "tasks"
    assert payload["data"]["priority"] == "high"
    assert payload["data"]["recommended_assignee"] == "Анна"
    assert payload["actions"][0]["requires_confirmation"] is True


def test_versioned_knowledge_rag_returns_citation(tmp_path):
    with make_client(tmp_path) as client:
        first = client.post(
            "/v1/knowledge/documents",
            files={
                "file": ("sales.md", "Скидку свыше 10% согласует руководитель.", "text/markdown")
            },
            data={"title": "Регламент продаж"},
        )
        second = client.post(
            "/v1/knowledge/documents",
            files={"file": ("sales.md", "Скидку свыше 8% согласует директор.", "text/markdown")},
            data={"title": "Регламент продаж"},
        )
        duplicate = client.post(
            "/v1/knowledge/documents",
            files={"file": ("sales.md", "Скидку свыше 8% согласует директор.", "text/markdown")},
            data={"title": "Регламент продаж"},
        )
        answer = client.post(
            "/v1/knowledge/query",
            json={"question": "Кто согласует скидку?", "limit": 5},
        )

    assert first.status_code == 200
    assert first.json()["version"] == 1
    assert second.json()["version"] == 2
    assert duplicate.json()["id"] == second.json()["id"]
    assert answer.status_code == 200
    assert answer.json()["citations"]
    assert answer.json()["citations"][0]["title"] == "Регламент продаж"
    assert {item["version"] for item in answer.json()["citations"]} == {2}
    assert "[1]" in answer.json()["answer"]


def test_local_rag_ranks_lexically_relevant_chunk_first(tmp_path):
    document = (
        ("Архитектура и возможности агентов. " * 80)
        + "Для запуска через Docker выполните docker compose up --build. "
        + ("Настройки CRM и роли сотрудников. " * 80)
    )
    with make_client(tmp_path) as client:
        client.post(
            "/v1/knowledge/documents",
            files={"file": ("manual.md", document, "text/markdown")},
            data={"title": "Эксплуатация"},
        )
        response = client.post(
            "/v1/knowledge/query",
            json={"question": "Как запустить через Docker?"},
        )

    top_excerpt = response.json()["citations"][0]["excerpt"].lower()
    assert "docker compose up" in top_excerpt
    assert not top_excerpt.startswith(("ость", "тура"))


def test_chat_handoff_keeps_full_history(tmp_path):
    with make_client(tmp_path) as client:
        client.post(
            "/v1/chat/messages",
            json={"session_id": "dialog-1", "message": "Какие есть тарифы?"},
        )
        response = client.post(
            "/v1/chat/messages",
            json={"session_id": "dialog-1", "message": "Позовите оператора"},
        )

    payload = response.json()
    assert payload["handoff"] is True
    assert len(payload["history"]) == 4
    assert payload["history"][-1]["role"] == "assistant"


def test_mcp_lists_tools_and_api_key_is_enforced(tmp_path):
    with make_client(tmp_path, api_key="secret") as client:
        denied = client.post("/mcp", json={"jsonrpc": "2.0", "id": 1, "method": "tools/list"})
        allowed = client.post(
            "/mcp",
            headers={"x-api-key": "secret"},
            json={"jsonrpc": "2.0", "id": 1, "method": "tools/list"},
        )

    assert denied.status_code == 401
    assert allowed.status_code == 200
    names = {tool["name"] for tool in allowed.json()["result"]["tools"]}
    assert names == {
        "orchestra_agent",
        "knowledge_search",
        "crm_extract",
        "call_analyze",
        "process_from_text",
    }


def test_role_access_and_rate_headers(tmp_path):
    with make_client(
        tmp_path,
        api_keys="viewer-key:viewer,operator-key:operator,manager-key:manager",
    ) as client:
        metrics = client.get("/metrics", headers={"x-api-key": "viewer-key"})
        viewer_write = client.post(
            "/v1/chat/messages",
            headers={"x-api-key": "viewer-key"},
            json={"session_id": "rbac", "message": "Помогите"},
        )
        operator_admin = client.post(
            "/v1/processes/from-text",
            headers={"x-api-key": "operator-key"},
            json={"description": "Когда создан лид, затем уведомить менеджера"},
        )
        manager_allowed = client.post(
            "/v1/processes/from-text",
            headers={"x-api-key": "manager-key"},
            json={"description": "Когда создан лид, затем уведомить менеджера"},
        )

    assert metrics.status_code == 200
    assert "orchestra_http_requests_total" in metrics.text
    assert viewer_write.status_code == 403
    assert operator_admin.status_code == 403
    assert manager_allowed.status_code == 200
    assert "x-ratelimit-remaining" in manager_allowed.headers


def test_webhook_is_idempotent(tmp_path):
    body = {"event": "ONCRMLEADADD", "event_id": "event-42", "data": {"id": 42}}
    with make_client(tmp_path, webhook_secret="hook-secret") as client:
        first = client.post(
            "/v1/webhooks/bitrix24",
            headers={"x-webhook-secret": "hook-secret"},
            json=body,
        )
        duplicate = client.post(
            "/v1/webhooks/bitrix24",
            headers={"x-webhook-secret": "hook-secret"},
            json=body,
        )

    assert first.json()["accepted"] is True
    assert first.json()["duplicate"] is False
    assert duplicate.json()["accepted"] is False
    assert duplicate.json()["duplicate"] is True


def test_extended_business_capabilities(tmp_path):
    now = datetime.now(UTC)
    with make_client(tmp_path) as client:
        process = client.post(
            "/v1/processes/from-text",
            json={
                "description": (
                    "Когда создана новая сделка, затем проверить данные CRM; "
                    "затем согласовать скидку; затем уведомить менеджера"
                )
            },
        )
        training = client.post(
            "/v1/training/evaluate",
            json={
                "expected": "Скидку согласует директор отдела продаж",
                "answer": "Скидку согласует директор отдела продаж",
                "previous_scores": [0.8, 0.9],
            },
        )
        mining = client.post(
            "/v1/analytics/process-mining",
            json={
                "events": [
                    {
                        "case_id": "deal-1",
                        "activity": "qualification",
                        "occurred_at": now.isoformat(),
                    },
                    {
                        "case_id": "deal-1",
                        "activity": "proposal",
                        "occurred_at": (now + timedelta(hours=5)).isoformat(),
                    },
                    {
                        "case_id": "deal-1",
                        "activity": "payment",
                        "occurred_at": (now + timedelta(hours=6)).isoformat(),
                    },
                ]
            },
        )
        forecast = client.post(
            "/v1/analytics/kpi-forecast",
            json={"values": [10, 12, 14, 16], "horizon": 2},
        )
        presentation = client.post(
            "/v1/content/presentation",
            json={
                "title": "План продаж",
                "content": "Цель — рост продаж. Настроить CRM. Обучить менеджеров.",
                "slides": 4,
            },
        )

    assert process.status_code == 200
    assert [step["type"] for step in process.json()["process"]["steps"]] == [
        "bitrix_call",
        "human_approval",
        "notify",
    ]
    assert training.json()["score"] == 1
    assert training.json()["next_difficulty"] == "hard"
    assert mining.json()["bottlenecks"][0]["activity"] == "qualification"
    assert forecast.json()["forecast"] == [18.0, 20.0]
    assert presentation.status_code == 200
    assert presentation.content.startswith(b"PK")


def test_trainable_deal_outcome_model_is_versioned(tmp_path):
    won = [
        {
            "text": "готов купить договор оплата бюджет",
            "amount": 200_000 + index * 10_000,
            "days_open": 5,
            "activities": 12,
            "won": True,
        }
        for index in range(5)
    ]
    lost = [
        {
            "text": "дорого подумаю позже отказ",
            "amount": 10_000,
            "days_open": 120,
            "activities": 1,
            "won": False,
        }
        for _ in range(5)
    ]
    with make_client(tmp_path) as client:
        trained = client.post("/v1/crm/deal-model/train", json={"examples": won + lost})
        positive = client.post(
            "/v1/crm/deal-model/predict",
            json={
                "text": "готов купить и оплатить договор",
                "amount": 250_000,
                "days_open": 3,
                "activities": 10,
            },
        )
        negative = client.post(
            "/v1/crm/deal-model/predict",
            json={
                "text": "дорого, подумаю позже",
                "amount": 5_000,
                "days_open": 150,
                "activities": 1,
            },
        )

    assert trained.status_code == 200
    assert trained.json()["version"] == 1
    assert trained.json()["metrics"]["training_examples"] == 10
    assert positive.json()["probability"] > negative.json()["probability"]


def test_audio_provider_guard_and_local_wav_signals(tmp_path):
    settings = Settings(
        database_url=f"sqlite+aiosqlite:///{tmp_path / 'audio.db'}",
        llm_api_key=None,
        stt_api_key=None,
    )
    with make_client(tmp_path) as client:
        unavailable = client.post(
            "/v1/calls/transcribe",
            files={"file": ("call.mp3", b"fake-audio", "audio/mpeg")},
        )

    buffer = io.BytesIO()
    rate = 8_000
    with wave.open(buffer, "wb") as output:
        output.setnchannels(1)
        output.setsampwidth(2)
        output.setframerate(rate)
        samples = [
            int(10_000 * math.sin(2 * math.pi * 440 * index / rate)) for index in range(rate)
        ]
        output.writeframes(struct.pack(f"<{len(samples)}h", *samples))
    signals = AudioService(settings).wav_signals(
        buffer.getvalue(), "Это короткая проверка темпа речи"
    )

    assert unavailable.status_code == 503
    assert signals["available"] is True
    assert signals["duration_seconds"] == 1
    assert signals["energy"] > 0
