from fastapi.testclient import TestClient

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
            files={"file": ("sales.md", "Скидку свыше 10% согласует руководитель.", "text/markdown")},
            data={"title": "Регламент продаж"},
        )
        second = client.post(
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
    assert names == {"orchestra_agent", "knowledge_search"}
