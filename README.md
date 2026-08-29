# Авто скрин для perplexity

Node.js-сервис, который делает скриншоты страниц через Playwright, анализирует их через
Perplexity API и отправляет файлы в WhatsApp через Wazzup.

## Стек

- Node.js >= 18
- Express (HTTP API)
- Playwright (chromium, скриншоты)
- Perplexity API (модель `sonar`)
- Wazzup API (отправка файлов в WhatsApp)

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
| `WAZZUP_API_KEY` | Секретный ключ Wazzup | — |
| `WAZZUP_API_BASE_URL` | Адрес Wazzup API | `https://api.wazzup24.com` |
| `WAZZUP_CHANNEL_ID` | UUID подключённого канала WhatsApp в Wazzup | — |
| `WAZZUP_SEND_API_KEY` | Собственный секрет для защиты endpoint отправки | — |
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

### `POST /whatsapp/send-file`

Отправляет файл в индивидуальный чат WhatsApp через Wazzup. Endpoint работает только
после настройки всех переменных `WAZZUP_*`.

Wazzup принимает не локальный файл, а прямую публичную HTTPS-ссылку. По этой ссылке
файл должен скачиваться без авторизации и перенаправлений.

```bash
curl -X POST http://localhost:8787/whatsapp/send-file \
  -H "Authorization: Bearer $WAZZUP_SEND_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{
    "phone": "+7 (918) 555-12-34",
    "contentUri": "https://files.example.com/dogovor.docx",
    "crmMessageId": "dogovor-albina-2026-001"
  }'
```

Поля:

- `phone` — номер получателя с кодом страны;
- `contentUri` — публичная HTTPS-ссылка на документ;
- `crmMessageId` — необязательный уникальный идентификатор, защищающий от повторной отправки.

Успешный ответ имеет HTTP-статус `201`:

```json
{
  "status": "sent",
  "messageId": "идентификатор-сообщения-wazzup",
  "chatId": "79185551234"
}
```

Сначала отправьте поясняющий текст отдельным сообщением через Wazzup, если он нужен:
API Wazzup не разрешает передавать `text` и `contentUri` одновременно.

## Структура проекта

```
.
├── src/index.js     # Express + Playwright + Perplexity
├── src/wazzup.js    # безопасная отправка файлов через Wazzup
├── test/            # автоматические тесты
├── Dockerfile       # образ на базе Playwright
├── package.json     # зависимости и скрипты
├── .env.example     # пример конфигурации
└── .gitignore
```
