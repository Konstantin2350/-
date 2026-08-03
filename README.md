# Авто скрин для perplexity

Node.js-сервис, который делает скриншоты страниц через Playwright и анализирует их через Perplexity API.  
Также содержит **операционный NLP для коллектива** (WFO/TOTE) — это про рабочие цели и циклы проверки, **не терапия**.

## Стек

- Node.js >= 18
- Express (HTTP API)
- Playwright (chromium, скриншоты)
- Perplexity API (модель `sonar`, опционально)

## Настройка

1. Скопируйте файл окружения и впишите свои значения:

```bash
cp .env.example .env
```

| Переменная | Описание | По умолчанию |
| --- | --- | --- |
| `PERPLEXITY_API_KEY` | Ключ Perplexity API | — |
| `PERPLEXITY_URL` | URL endpoint | `https://api.perplexity.ai/chat/completions` |
| `PERPLEXITY_MODEL` | Модель | `sonar` |
| `MIN_CONFIDENCE` | Порог уверенности | `0.78` |
| `PLAYWRIGHT_PROFILE_DIR` | Каталог профиля Playwright | `./pw-profile` |
| `ARTIFACT_DIR` | Каталог для скриншотов и NLP-циклов | `./artifacts` |
| `PORT` | Порт сервиса | `8787` |
| `NLP_STAFF_CYCLE` | Включить операционный NLP (`1`/`0`) | `1` |

## Запуск локально

```bash
npm install
npx playwright install chromium
npm start
```

Сервис будет доступен на `http://localhost:8787`.

## Запуск в Docker

```bash
docker build -t auto-screen .
docker run -p 8787:8787 --env-file .env auto-screen
```

## API

### `GET /health`

Проверка состояния сервиса (включая статус NLP).

### `POST /capture`

Делает скриншот страницы и (опционально) анализирует её через Perplexity.

```bash
curl -X POST http://localhost:8787/capture \
  -H "Content-Type: application/json" \
  -d '{"url": "https://example.com", "prompt": "Опиши что на странице"}'
```

### Операционный NLP (не терапия)

Граница: только цели, критерии, тесты и коррекции процесса. Без психологии/лечения.

#### `GET /nlp/meta`

Метаданные модуля и список эндпоинтов.

#### `POST /nlp/wfo`

Оформить Well-Formed Outcome (локально; с `"ai": true` — через Perplexity, если есть ключ).

```bash
curl -X POST http://localhost:8787/nlp/wfo \
  -H "Content-Type: application/json" \
  -d '{"goal":"Сдать 3 пустующих лота на Северной 100","owner":"Альбина","deadline":"2026-08-17"}'
```

#### `POST /nlp/staff-cycle`

Быстрый операционный цикл для сотрудника/роли. `"startCycle": true` сразу создаёт TOTE-цикл.

```bash
curl -X POST http://localhost:8787/nlp/staff-cycle \
  -H "Content-Type: application/json" \
  -d '{"staff":"Альбина","focus":"сдать пустующие на Северной 100","startCycle":true}'
```

#### `POST /nlp/cycle` / `POST /nlp/cycle/:id/advance`

Создать TOTE-цикл и шагать по нему: `test` → `operate` → `test` → `exit`.

```bash
# создать
curl -X POST http://localhost:8787/nlp/cycle \
  -H "Content-Type: application/json" \
  -d '{"goal":"Закрыть 3 договора аренды","owner":"команда","successMetric":"3 подписанных договора"}'

# тест не пройден
curl -X POST http://localhost:8787/nlp/cycle/<id>/advance \
  -H "Content-Type: application/json" \
  -d '{"eventType":"test","passed":false,"note":"0 показов за день"}'

# коррекция
curl -X POST http://localhost:8787/nlp/cycle/<id>/advance \
  -H "Content-Type: application/json" \
  -d '{"eventType":"operate","action":"10 целевых касаний + 2 показа"}'

# тест пройден → exit
curl -X POST http://localhost:8787/nlp/cycle/<id>/advance \
  -H "Content-Type: application/json" \
  -d '{"eventType":"test","passed":true,"note":"3 договора"}'
```

Циклы сохраняются в `ARTIFACT_DIR/nlp-cycles/` (файлы JSON, без БД).

## Структура проекта

```
.
├── src/
│   ├── index.js          # Express + Playwright + Perplexity
│   └── nlp/              # Операционный NLP (WFO/TOTE)
│       ├── router.js
│       ├── wfo.js
│       ├── tote.js
│       ├── prompts.js
│       └── store.js
├── Dockerfile
├── package.json
├── .env.example
└── .gitignore
```
