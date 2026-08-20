# Матрица возможностей ИИ‑Оркестра

Проверено по официальным материалам Bitrix24 от апреля–мая 2026:

- [CoPilot: call transcription and CRM field updates](https://helpdesk.bitrix24.com/open/25855535/)
- [AI Speech Analytics and Sales Scripts](https://helpdesk.bitrix24.com/open/23763142/)
- [AI Agents for Bitrix24](https://www.bitrix24.com/tools/vibecode/ai-agents.php)

## HIGH

| Направление | Реализация |
| --- | --- |
| CRM Automation | NER, безопасные updates/suggestions, обучаемая logistic-модель сделок, spam-фильтр, RFM |
| Call Intelligence | STT provider, WAV prosody, sentiment, script score, feedback, action items |
| Multi-channel Chat | HTTP/WebSocket, channel adapters, Redis memory, роли, RAG, handoff |
| Knowledge Q&A | PDF/DOCX/TXT/MD, dedup/versioning, remote/local embeddings, reranking, citations |
| Tasks & Projects | NL task draft, checklist, assignee/load scoring, risks, project digest |

## MEDIUM

| Направление | Реализация |
| --- | --- |
| Business Processes | NL → validated DSL, webhooks/event log, Bitrix batch, MCP, Celery |
| Content | Email/product/META/article templates, brainstorming, meeting summary, PPTX |
| Testing & Training | Question generation, semantic scoring, adaptive difficulty |

## LOW

| Направление | Реализация |
| --- | --- |
| Voice & Audio | Audio → transcript/CRM/task flow; provider-backed TTS |
| Analytics & BI | Process variants/bottlenecks, recommendations, linear KPI forecast |

## Эксплуатационные границы

- Текстовые функции работают без внешнего AI через детерминированный fallback.
- Реальная расшифровка и TTS требуют ключ совместимого провайдера. Сам ключ не
  хранится в репозитории.
- 10 000 соединений требуют нескольких API replicas, управляемых PostgreSQL/Redis
  и нагрузочной проверки на инфраструктуре заказчика. Сценарий находится в
  `load/k6-chat.js`; число не заявляется подтверждённым до фактического прогона.
- Точность модели сделок зависит от истории конкретной компании. Endpoint обучения
  сохраняет версию и метрики, но бизнес должен предоставить размеченные won/lost
  сделки.
- Действия Bitrix24 используют allowlist методов. Изменение существующего CRM-поля
  возвращается как suggestion и требует подтверждения.
