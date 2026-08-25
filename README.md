# ИИ‑Оркестр

Multi-agent платформа автоматизации бизнеса: единая точка входа маршрутизирует
запрос к агентам CRM, звонков, чата, базы знаний, задач и контента. Интеграция с
Bitrix24 выполняет разрешённые REST-методы и массовые операции, MCP подключает
Оркестр к внешним AI-системам.

Полное соответствие требованиям и честные эксплуатационные границы описаны в
`docs/CAPABILITIES.md`.

## ИИ‑сотрудники

Навыки назначаются декларативно в `config/ai_employees.json`. В комплект входят
координатор, продажи, тренер звонков, поддержка, база знаний, проекты, контент и
роль **Елена — Финансы**. Елена анализирует суммы, оплаты, бюджет и риски, но
никогда не проводит платёж без подтверждения человека.

```bash
# Каталог сотрудников и навыков
curl http://localhost:8787/v1/employees -H 'x-api-key: ...'

# Поручение конкретному сотруднику
curl -X POST http://localhost:8787/v1/employees/elena_finance/invoke \
  -H 'x-api-key: ...' -H 'Content-Type: application/json' \
  -d '{"message":"Нужно оплатить счёт поставщика на 120 000 руб."}'
```

Через `POST /v1/employees/director/invoke` можно обратиться к директору:
Оркестр сам выберет профильного сотрудника по смыслу задачи.

## Что уже работает

- CRM: извлечение имени, телефона, email, суммы и продукта; безопасные предложения
  изменений полей; оценка вероятности сделки; RFM-поиск повторных продаж.
- Звонки: Whisper/OpenAI-compatible STT, базовые WAV-сигналы темпа/энергии,
  резюме, тональность, проверка скрипта, рекомендации, следующие действия,
  фильтрация нерелевантных обращений и подготовка CRM-полей.
- Чат: Redis-память с локальным резервом, роли sales/support/onboarding,
  поиск по базе знаний и передача оператору с историей; HTTP и WebSocket.
- RAG: PDF/DOCX/TXT/MD, защита форматов, дедупликация, версионность, chunking,
  OpenAI или локальные embeddings, pgvector HNSW, гибридный reranking и ссылки.
- Задачи: разбор естественного языка, дедлайн, приоритет, чек-лист,
  рекомендация исполнителя по компетенциям/нагрузке, хранимые проекты/задачи,
  статусы, риски и подтверждаемая синхронизация с Bitrix24.
- Автоматизация: проверяемый BPMN-like JSON DSL, Bitrix webhooks, event log,
  конструктор процессов из русского текста, runtime экземпляров/approvals/waits,
  подтверждаемые и идемпотентные Bitrix actions, Celery, batch API и MCP tools.
- Контент и развитие: письма/META/описания, резюме встреч, PPTX-презентации,
  генерация тестов, семантическая проверка ответов и адаптивная сложность.
- Аналитика: дайджест проектов, process mining, узкие места и прогноз KPI.
- Безопасность и эксплуатация: API keys/JWT, роли viewer/operator/manager/admin,
  tenant/session isolation, rate limit, идемпотентные webhooks, Prometheus,
  миграции Alembic, точный allowlist Bitrix24, security headers и request ID.
- Операторы: сохраняемая очередь handoff, claim, история диалога, ответы и
  закрытие обращения.
- Рекламные лиды без Bitrix24: отслеживаемые ссылки, код источника, квалификация,
  самостоятельный реестр, передача человеку и метрики кампании.
- Wazzup: входящие WhatsApp/Telegram-сообщения, защита и дедупликация webhook,
  автоответ в исходный чат и регистрация callback через API.

Внешний LLM необязателен для текста, RAG и аналитики: без ключа работает локальный
предсказуемый режим. Расшифровка реального аудио и синтез речи требуют
`STT_API_KEY`/`LLM_API_KEY`, потому что модель не поставляется внутрь контейнера.

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

Остальные готовые API видны в `/docs`:

- `/v1/calls/transcribe`, `/v1/calls/process-audio`, `/v1/voice/synthesize`
- `/v1/processes/from-text`, `/v1/content/generate`,
  `/v1/content/presentation`
- `/v1/actions`, `/v1/actions/{id}/confirm`, `/execute`, `/enqueue`
- `/v1/processes/instances`, `/approve`, `/resume`
- `/v1/operator/handoffs`, `/claim`, `/reply`
- `/v1/campaigns`, `/v1/webhooks/leads/{campaign_code}`, `/v1/leads`
- `/v1/training/tests`, `/v1/training/evaluate`
- `/v1/analytics/process-mining`, `/v1/analytics/kpi-forecast`,
  `/v1/projects/digest`
- `/v1/channels/{channel}/messages`, `/metrics`, `/mcp`

## Права доступа

`API_KEYS` принимает строку вида
`read-key:viewer:company-a,bot-key:operator:company-a`. Третья часть — организация;
данные, память диалогов, модели, actions и процессы изолируются по ней.

- `viewer` читает статусы, результаты и метрики.
- `operator` общается с агентами и обрабатывает клиентские запросы.
- `manager` запускает процессы, аналитику, очередь и действия Bitrix24.
- `admin` предназначен для административных операций.

Вместо ключей поддерживается JWT HS256 с `sub`, `role`, `tenant_id`, `iat`,
`exp`, `iss`. Для webhook нескольких организаций задайте
`WEBHOOK_SECRETS=company-a=secret-a,company-b=secret-b` и передавайте
`x-tenant-id`.

## Производственная конфигурация

Обязательные настройки:

- `DATABASE_URL=postgresql+asyncpg://...`
- `REDIS_URL=redis://.../0`
- `CELERY_BROKER_URL` и `CELERY_RESULT_BACKEND`
- `API_KEY` и `WEBHOOK_SECRET`
- `BITRIX_WEBHOOK_URL` для действий в Bitrix24
- `LLM_API_KEY`, `LLM_BASE_URL`, `LLM_MODEL` для генеративных ответов

Для кампании блогера по квартире в Геленджике задайте
`PUBLIC_BASE_URL`, `BLOGGER_CONTACT_PHONE` и `BLOGGER_TELEGRAM_USERNAME`.
Для двустороннего обмена через Wazzup также нужны `WAZZUP_API_KEY`,
`WAZZUP_WEBHOOK_TOKEN` и `WAZZUP_AUTO_REPLY=true`.
Пошаговый регламент запуска находится в `docs/BLOGGER_GELENDZHIK_RUNBOOK.md`.
Контактные данные храните только в `.env`.

Для Railway/Render используйте `Dockerfile` и readiness check `/ready`, который
проверяет PostgreSQL, Redis и Celery worker. API масштабируется горизонтально; состояние диалогов хранится в
Redis, документы и журнал действий — в PostgreSQL, тяжёлые задания — в Celery.

- Render: создайте Blueprint из `render.yaml`.
- Railway: добавьте PostgreSQL и Redis, затем разверните `railway.json`. Для
  worker создайте второй сервис из того же репозитория с командой
  `celery -A orchestra.worker.celery_app worker --loglevel=INFO`.
- При старте контейнера автоматически выполняется `alembic upgrade head`.

## Проверка

```bash
.venv/bin/pytest
.venv/bin/alembic upgrade head
```

Нагрузочный сценарий находится в `load/k6-chat.js`. Сначала проверяйте 100
пользователей, затем постепенно увеличивайте:

```bash
k6 run -e BASE_URL=http://localhost:8787 -e VUS=100 load/k6-chat.js
# Только на подготовленном стенде:
k6 run -e BASE_URL=https://your-host -e VUS=10000 -e HOLD=5m load/k6-chat.js
```

Исходный Node.js сервис скриншотов сохранён в `legacy/auto-screen-perplexity`.
