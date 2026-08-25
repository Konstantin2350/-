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
    assert ready.json()["status"] == "ready"
    assert ready.json()["components"]["database"] == "ready"
    assert ready.json()["components"]["celery"] == "not-checked"
    assert health.headers["x-content-type-options"] == "nosniff"


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
    assert payload["actions"][0]["action_id"]


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


def test_action_engine_confirmation_execution_and_tenant_isolation(tmp_path):
    headers_a = {"x-api-key": "manager-a"}
    headers_b = {"x-api-key": "manager-b"}
    with make_client(
        tmp_path,
        api_keys="manager-a:manager:tenant-a,manager-b:manager:tenant-b",
    ) as client:
        forbidden_method = client.post(
            "/v1/bitrix/call",
            headers=headers_a,
            json={"method": "crm.deal.delete", "params": {"id": 42}},
        )

        async def fake_bitrix_call(method, params):
            return {"result": {"method": method, "id": params["id"]}}

        client.app.state.bitrix.call = fake_bitrix_call
        body = {
            "tool": "bitrix.call",
            "payload": {},
            "requires_confirmation": True,
            "idempotency_key": "deal-update-42",
        }
        created = client.post("/v1/actions", headers=headers_a, json=body)
        duplicate = client.post("/v1/actions", headers=headers_a, json=body)
        action_id = created.json()["id"]
        confirmed = client.post(
            f"/v1/actions/{action_id}/confirm",
            headers=headers_a,
            json={
                "payload_updates": {
                    "method": "crm.deal.update",
                    "params": {"id": 42, "fields": {"TITLE": "Новая сделка"}},
                }
            },
        )
        executed = client.post(f"/v1/actions/{action_id}/execute", headers=headers_a)
        tenant_b_actions = client.get("/v1/actions", headers=headers_b)

    assert created.status_code == 201
    assert duplicate.json()["id"] == action_id
    assert confirmed.json()["status"] == "confirmed"
    assert executed.json()["status"] == "executed"
    assert executed.json()["result"]["result"]["id"] == 42
    assert tenant_b_actions.json()["actions"] == []
    assert forbidden_method.status_code == 422


def test_process_runtime_approval_and_webhook_trigger(tmp_path):
    headers = {"x-api-key": "manager-key"}
    with make_client(
        tmp_path,
        api_keys="manager-key:manager:acme",
        webhook_secrets="acme=hook-acme",
    ) as client:
        saved = client.post(
            "/v1/processes",
            headers=headers,
            json={
                "name": "Согласование скидки",
                "trigger": "manual",
                "steps": [
                    {"type": "notify", "instruction": "Проверка началась"},
                    {"type": "human_approval", "instruction": "Согласовать"},
                    {"type": "notify", "instruction": "Скидка согласована"},
                ],
            },
        )
        started = client.post(
            "/v1/processes/instances",
            headers=headers,
            json={"process_id": saved.json()["id"], "context": {"deal_id": 42}},
        )
        approved = client.post(
            f"/v1/processes/instances/{started.json()['id']}/approve",
            headers=headers,
            json={"approved": True, "comment": "Одобрено"},
        )
        event_process = client.post(
            "/v1/processes",
            headers=headers,
            json={
                "name": "Новый лид",
                "trigger": "ONCRMLEADADD",
                "steps": [{"type": "notify", "instruction": "Назначить менеджера"}],
            },
        )
        webhook = client.post(
            "/v1/webhooks/bitrix24",
            headers={
                "x-webhook-secret": "hook-acme",
                "x-tenant-id": "acme",
            },
            json={
                "event": "ONCRMLEADADD",
                "event_id": "lead-event-1",
                "data": {"id": 100},
            },
        )

    assert saved.status_code == 201
    assert started.json()["status"] == "waiting_approval"
    assert started.json()["current_step"] == 1
    assert approved.json()["status"] == "completed"
    assert len(approved.json()["history"]) == 3
    assert event_process.status_code == 201
    assert len(webhook.json()["process_instances"]) == 1


def test_operator_handoff_queue_and_session_tenant_isolation(tmp_path):
    operator_a = {"x-api-key": "operator-a"}
    operator_b = {"x-api-key": "operator-b"}
    manager_a = {"x-api-key": "manager-a"}
    with make_client(
        tmp_path,
        api_keys=(
            "operator-a:operator:tenant-a,operator-b:operator:tenant-b,manager-a:manager:tenant-a"
        ),
    ) as client:
        handoff = client.post(
            "/v1/chat/messages",
            headers=operator_a,
            json={"session_id": "same-session", "message": "Позовите оператора"},
        )
        isolated = client.post(
            "/v1/chat/messages",
            headers=operator_b,
            json={"session_id": "same-session", "message": "Нужна помощь"},
        )
        client.post(
            "/v1/knowledge/documents",
            headers=operator_a,
            files={
                "file": (
                    "private.md",
                    "Секретный регламент компании tenant-a.",
                    "text/markdown",
                )
            },
            data={"title": "Закрытый регламент"},
        )
        tenant_b_search = client.post(
            "/v1/knowledge/query",
            headers=operator_b,
            json={"question": "Секретный регламент компании"},
        )
        queued = client.get("/v1/operator/handoffs", headers=manager_a)
        handoff_id = handoff.json()["handoff_id"]
        claimed = client.post(
            f"/v1/operator/handoffs/{handoff_id}/claim",
            headers=manager_a,
            json={},
        )
        replied = client.post(
            f"/v1/operator/handoffs/{handoff_id}/reply",
            headers=manager_a,
            json={"message": "Подключился менеджер", "close": True},
        )

    assert handoff.json()["handoff"] is True
    assert len(queued.json()["handoffs"]) == 1
    assert claimed.json()["status"] == "claimed"
    assert replied.json()["status"] == "closed"
    assert replied.json()["delivery"] == "recorded"
    assert len(isolated.json()["history"]) == 2
    assert tenant_b_search.json()["citations"] == []


def test_blogger_campaign_redirect_and_lead_flow_without_bitrix(tmp_path):
    campaign_code = "gelendzhik-blogger-2708"
    with make_client(
        tmp_path,
        blogger_contact_phone="+7 (999) 111-22-33",
        public_base_url="https://orchestra.example",
    ) as client:
        campaign = client.get(f"/v1/campaigns/{campaign_code}")
        redirect = client.get(f"/r/{campaign_code}", follow_redirects=False)
        first = client.post(
            f"/v1/webhooks/leads/{campaign_code}",
            json={
                "external_id": "wa-dialog-1",
                "channel": "whatsapp",
                "message": "Подскажите цену квартиры",
            },
        )
        second = client.post(
            f"/v1/webhooks/leads/{campaign_code}",
            json={
                "external_id": "wa-dialog-1",
                "channel": "whatsapp",
                "message": "Я Анна, хочу посмотреть квартиру",
                "phone": "8 (999) 123-45-67",
                "answers": {
                    "goal": "для себя",
                    "budget": "15 млн",
                    "timeline": "в течение месяца",
                    "payment": "наличные",
                    "viewing_time": "завтра в 15:00",
                },
            },
        )
        leads = client.get(f"/v1/leads?campaign_code={campaign_code}")
        handoffs = client.get("/v1/operator/handoffs")
        metrics = client.get(f"/v1/campaigns/{campaign_code}/metrics")

    assert campaign.status_code == 200
    assert campaign.json()["public_link"] == (
        "https://orchestra.example/r/gelendzhik-blogger-2708"
    )
    assert campaign.json()["contact_configured"] is True
    assert redirect.status_code == 307
    assert redirect.headers["location"].startswith("https://wa.me/79991112233?text=")
    assert first.status_code == 200
    assert first.json()["created"] is True
    assert first.json()["lead"]["handoff_id"] is None
    assert first.json()["lead"]["next_question"]
    assert second.status_code == 200
    assert second.json()["created"] is False
    assert second.json()["lead"]["phone"] == "+79991234567"
    assert second.json()["lead"]["status"] == "qualified"
    assert second.json()["lead"]["priority"] == "hot"
    assert second.json()["lead"]["handoff_id"]
    assert len(leads.json()["leads"]) == 1
    assert len(handoffs.json()["handoffs"]) == 1
    assert metrics.json() == {
        "campaign_code": campaign_code,
        "clicks": 1,
        "leads": 1,
        "with_phone": 1,
        "handoffs": 1,
        "statuses": {"qualified": 1},
        "priorities": {"hot": 1},
    }


def test_campaign_lead_webhook_secret_and_status_update(tmp_path):
    campaign_code = "gelendzhik-blogger-2708"
    with make_client(tmp_path, webhook_secret="campaign-secret") as client:
        rejected = client.post(
            f"/v1/webhooks/leads/{campaign_code}",
            json={"external_id": "wa-2", "message": "Хочу посмотреть"},
        )
        accepted = client.post(
            f"/v1/webhooks/leads/{campaign_code}",
            headers={"x-webhook-secret": "campaign-secret"},
            json={
                "external_id": "wa-2",
                "message": "Хочу посмотреть",
                "phone": "+79990000000",
            },
        )
        lead_id = accepted.json()["lead"]["id"]
        updated = client.patch(
            f"/v1/leads/{lead_id}",
            json={"status": "viewing_scheduled", "answers": {"viewing_time": "27 августа"}},
        )

    assert rejected.status_code == 401
    assert accepted.status_code == 200
    assert updated.status_code == 200
    assert updated.json()["status"] == "viewing_scheduled"


def test_persistent_projects_tasks_and_bitrix_sync_proposal(tmp_path):
    headers = {"x-api-key": "operator-key"}
    with make_client(tmp_path, api_keys="operator-key:operator:projects-tenant") as client:
        project = client.post(
            "/v1/projects",
            headers=headers,
            json={"name": "Запуск продукта", "description": "План запуска"},
        )
        task = client.post(
            "/v1/tasks",
            headers=headers,
            json={
                "project_id": project.json()["id"],
                "title": "Подготовить презентацию",
                "description": "Собрать итоговый PPTX",
                "priority": "high",
                "checklist": ["Структура", "Дизайн", "Проверка"],
            },
        )
        updated = client.patch(
            f"/v1/tasks/{task.json()['id']}",
            headers=headers,
            json={"status": "in_progress", "progress": 30},
        )
        listed = client.get(
            f"/v1/projects/{project.json()['id']}/tasks",
            headers=headers,
        )
        sync = client.post(
            f"/v1/tasks/{task.json()['id']}/sync-bitrix",
            headers=headers,
        )

    assert project.status_code == 201
    assert task.status_code == 201
    assert updated.json()["progress"] == 30
    assert listed.json()["tasks"][0]["title"] == "Подготовить презентацию"
    assert sync.json()["status"] == "proposed"
    assert sync.json()["payload"]["method"] == "tasks.task.add"


def test_ai_employees_receive_bitrix_like_skills_and_elena_handles_finance(
    tmp_path,
):
    headers = {"x-api-key": "operator-key"}
    with make_client(tmp_path, api_keys="operator-key:operator:employees-tenant") as client:
        catalog = client.get("/v1/employees", headers=headers)
        elena = client.get("/v1/employees/elena_finance", headers=headers)
        invoked = client.post(
            "/v1/employees/elena_finance/invoke",
            headers=headers,
            json={"message": ("Нужно оплатить счёт поставщика на сумму 120 000 руб.")},
        )
        director = client.post(
            "/v1/employees/director/invoke",
            headers=headers,
            json={"message": "Проанализируй бюджет и расходы за месяц"},
        )

    ids = {item["id"] for item in catalog.json()["employees"]}
    assert {
        "director",
        "sales",
        "call_coach",
        "support",
        "knowledge",
        "projects",
        "content",
        "elena_finance",
    } <= ids
    assert elena.json()["name"] == "Елена"
    assert elena.json()["role"] == "Финансы"
    assert "mandatory_payment_approval" in elena.json()["skills"]
    assert invoked.json()["result"]["agent"] == "finance"
    assert invoked.json()["result"]["data"]["amount"] == 120000
    assert invoked.json()["result"]["requires_human"] is True
    assert invoked.json()["result"]["actions"][0]["action_id"]
    assert director.json()["result"]["agent"] == "finance"
