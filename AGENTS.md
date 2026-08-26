# AGENTS.md

## Cursor Cloud specific instructions

This repo is a Python 3.12/FastAPI service (`ai-orchestra`) for multi-agent business
automation. It uses PostgreSQL for persistent knowledge/event data, Redis for session
memory, and Celery for background tasks. The former Node.js screenshot service is kept
under `legacy/auto-screen-perplexity`.

### Running the service
- Install: `python3 -m venv .venv && .venv/bin/pip install -e '.[dev]'`.
- Dev: `.venv/bin/uvicorn orchestra.main:app --reload --port 8787`.
- Full stack: `cp .env.example .env && docker compose up --build`.
- Production schema: `.venv/bin/alembic upgrade head`.
- Listens on `http://localhost:8787` (`PORT` env var).
- The app starts without `.env`, external services, or an LLM key using SQLite,
  in-process memory, deterministic embeddings, and rule-based fallbacks.

### Testing the core flow (no GUI)
This is a headless API service; run `.venv/bin/pytest` and test it with curl:
- `curl http://localhost:8787/health`
- `curl -X POST http://localhost:8787/v1/orchestrate -H "Content-Type: application/json" -d '{"message":"Создай задачу позвонить клиенту завтра"}'`

### Non-obvious caveats
- Production should configure PostgreSQL and Redis. Local tests intentionally use SQLite
  and in-process memory.
- Production startup rejects missing auth, webhook secret, PostgreSQL, or Redis settings.
- Audio transcription/TTS tests must mock the provider unless real credentials were
  explicitly supplied; text functionality has deterministic local fallbacks.
- Never log or commit API keys or Bitrix24 webhook URLs.
- Bitrix write actions proposed by agents require explicit confirmation by the caller.
