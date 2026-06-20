# Авто скрин для perplexity

Node.js-сервис, который делает скриншоты страниц через Playwright и анализирует их через Perplexity API.

## Стек

- Node.js >= 18
- Express (HTTP API)
- Playwright (chromium, скриншоты)
- Perplexity API (модель `sonar`)

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
| `ARTIFACT_DIR` | Каталог для скриншотов | `./artifacts` |
| `PORT` | Порт сервиса | `8787` |

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

Проверка состояния сервиса.

### `POST /capture`

Делает скриншот страницы и (опционально) анализирует её через Perplexity.

```bash
curl -X POST http://localhost:8787/capture \
  -H "Content-Type: application/json" \
  -d '{"url": "https://example.com", "prompt": "Опиши что на странице"}'
```

Ответ содержит путь к сохранённому скриншоту и результат анализа.

## Структура проекта

```
.
├── src/index.js     # Express + Playwright + Perplexity
├── Dockerfile       # образ на базе Playwright
├── package.json     # зависимости и скрипты
├── .env.example     # пример конфигурации
└── .gitignore
```
