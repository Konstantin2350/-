# AGENTS.md

## Cursor Cloud specific instructions

This repo is a single Node.js service (`auto-screen-perplexity`): an Express API that
captures full-page screenshots of URLs via Playwright (headless Chromium) and optionally
analyzes them with the Perplexity API. It also exposes **operational NLP for collectives**
(WFO/TOTE staff cycles) under `/nlp/*` — explicitly not therapy. There is no database
and no frontend; NLP cycles are stored as JSON files under `ARTIFACT_DIR/nlp-cycles/`.

### Running the service
- Dev (hot reload): `npm run dev` (uses `node --watch`). Prod-style: `npm start`.
- Listens on `http://localhost:8787` (`PORT` env var).
- A `.env` is required at runtime only for behavior tuning; the app starts fine without
  real values. Copy it with `cp .env.example .env`. `PERPLEXITY_API_KEY` is OPTIONAL —
  it is only used by `POST /capture` when a `prompt` is included in the request body,
  and by `/nlp/*` when the body has `"ai": true`. Without it, screenshot capture and
  local NLP cycles still work; AI enrichment is skipped.
- `NLP_STAFF_CYCLE` defaults to on (`1`). Set `0`/`false`/`off` to disable `/nlp/*`
  (returns 503).

### Testing the core flow (no GUI)
This is a headless API service; test it with curl, not a browser:
- `curl http://localhost:8787/health` → includes `nlp.enabled` / `therapy: false`
- `curl -X POST http://localhost:8787/capture -H "Content-Type: application/json" -d '{"url":"https://example.com"}'`
  → returns the saved screenshot path (under `ARTIFACT_DIR`, default `./artifacts`).
- `curl http://localhost:8787/nlp/meta` → operational NLP module metadata
- `curl -X POST http://localhost:8787/nlp/morning -H "Content-Type: application/json" -d '{"roster":[{"staff":"Альбина","focus":"сдать лоты"}]}'`
- With the server running: `npm run nlp:smoke` exercises morning → fail → operate → pass.

### Non-obvious caveats
- Playwright browser deps: this VM runs Ubuntu Noble, where `npx playwright install --with-deps chromium`
  FAILS because Playwright 1.44 requests the old `libasound2` package name (now `libasound2t64`).
  The browser binary and the required OS libs are already installed in the VM snapshot, so you do
  NOT need to reinstall them. If you ever must, install the browser with `npx playwright install chromium`
  (no `--with-deps`) and apt-install the `*t64` library variants separately.
- There are no lint or test scripts (`package.json` has only `start` and `dev`); no ESLint
  config and no test framework are present.
- Runtime dirs `./artifacts` and `./pw-profile` are auto-created on startup and are gitignored.
