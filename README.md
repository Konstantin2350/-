# ИИ‑Оркестр

Multi-agent платформа автоматизации бизнеса: единая точка входа маршрутизирует
запрос к агентам CRM, звонков, чата, базы знаний, задач и контента. Интеграция с
Bitrix24 выполняет разрешённые REST-методы и массовые операции, MCP подключает
Оркестр к внешним AI-системам.

## Что уже работает

- CRM: извлечение имени, телефона, email, суммы и продукта; безопасные предложения
  изменений полей; оценка вероятности сделки; RFM-поиск повторных продаж.
- Звонки: резюме, тональность, проверка скрипта, рекомендации, следующие действия,
  фильтрация нерелевантных обращений и подготовка CRM-полей.
- Чат: Redis-память с локальным резервом, роли sales/support/onboarding,
  поиск по базе знаний и передача оператору с историей; HTTP и WebSocket.
- RAG: PDF/DOCX/TXT/MD, версионность, chunking, локальные embeddings,
  гибридный semantic/lexical reranking и обязательные ссылки на источники.
- Задачи: разбор естественного языка, дедлайн, приоритет, чек-лист,
  рекомендация исполнителя по компетенциям/нагрузке и флаги риска.
- Автоматизация: проверяемый BPMN-like JSON DSL, Bitrix webhooks, event log,
  Celery worker, batch Bitrix API и MCP tools.
- Безопасность: API key, отдельный webhook secret, allowlist методов Bitrix24,
  ручное подтверждение опасных изменений и request ID.

Внешний LLM необязателен. Без ключа API работает локальный предсказуемый режим,
полезный для разработки и аварийного продолжения работы.

## Быстрый запуск

### Docker (рекомендуется)

```bash
cp .env.example .env
docker compose up --build
curl http://localhost:8787/health
```

Compose запускает API, Celery worker, PostgreSQL и Redis. Документация OpenAPI:
`http://localhost:8787/docs`.

### Локально без Docker

```bash
python3 -m venv .venv
.venv/bin/pip install -e '.[dev]'
cp .env.example .env
.venv/bin/uvicorn orchestra.main:app --host 0.0.0.0 --port 8787
```

По умолчанию используется SQLite и память процесса, поэтому PostgreSQL и Redis
не нужны для первого запуска.

## Основные запросы

```bash
# Автоматическая маршрутизация
curl -X POST http://localhost:8787/v1/orchestrate \
  -H 'Content-Type: application/json' \
  -d '{"message":"Создай срочную задачу позвонить клиенту завтра"}'

# Анализ разговора
curl -X POST http://localhost:8787/v1/calls/analyze \
  -H 'Content-Type: application/json' \
  -d '{"transcript":"Здравствуйте! Меня зовут Анна. Нужен тариф Бизнес. Отправьте счет завтра.","sales_script":["поздороваться","уточнить потребность","договориться о следующем шаге"]}'

# Загрузка базы знаний
curl -X POST http://localhost:8787/v1/knowledge/documents \
  -F 'file=@regulations.pdf' -F 'title=Регламент продаж'

curl -X POST http://localhost:8787/v1/knowledge/query \
  -H 'Content-Type: application/json' \
  -d '{"question":"Как согласовать скидку?"}'
```

Если задан `API_KEY`, добавляйте заголовок `x-api-key`. Для Bitrix webhook
используется отдельный `x-webhook-secret`.

## Производственная конфигурация

Обязательные настройки:

- `DATABASE_URL=postgresql+asyncpg://...`
- `REDIS_URL=redis://.../0`
- `CELERY_BROKER_URL` и `CELERY_RESULT_BACKEND`
- `API_KEY` и `WEBHOOK_SECRET`
- `BITRIX_WEBHOOK_URL` для действий в Bitrix24
- `LLM_API_KEY`, `LLM_BASE_URL`, `LLM_MODEL` для генеративных ответов

Для Railway/Render используйте `Dockerfile`, health check `/health` и readiness
check `/ready`. API масштабируется горизонтально; состояние диалогов хранится в
Redis, документы и журнал действий — в PostgreSQL, тяжёлые задания — в Celery.

## Проверка

```bash
.venv/bin/pytest
```

Исходный Node.js сервис скриншотов сохранён в `legacy/auto-screen-perplexity`.
