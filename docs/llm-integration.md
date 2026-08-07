# Интеграция LLM (фаза 0)

Документ описывает **текущую** архитектуру вызова модели в этом репозитории
(`auto-screen-perplexity`). Логика провайдеров пока не меняется — только
фиксация as-is и подготовка feature-flag переменных для локальной LLM (Ollama).

## Где выбирается провайдер

**Отдельного слоя выбора LLM-провайдера нет.**

Единственная точка вызова модели — функция `askPerplexity` в `src/index.js`.
Сервис всегда ходит в Perplexity (если передан `prompt` и задан API-ключ).
Клиента OpenAI в коде нет.

| Компонент | Файл / символ | Роль |
| --- | --- | --- |
| Конфиг | `process.env` в `src/index.js` (строки ~12–20) | Читает `PERPLEXITY_*`, порт, каталоги |
| HTTP API | `POST /capture` | Принимает `url` и опциональный `prompt` |
| Скриншот | `captureScreenshot(url)` | Playwright (Chromium), сохраняет PNG в `ARTIFACT_DIR` |
| LLM-вызов | `askPerplexity(prompt)` | `fetch` → Perplexity Chat Completions |
| Health | `GET /health` | Возвращает `model: PERPLEXITY_MODEL` |

## Текущий поток вызова

```
Клиент
  │  POST /capture { url, prompt? }
  ▼
Express (src/index.js)
  │
  ├─ captureScreenshot(url)  →  Playwright → artifacts/shot-*.png
  │
  └─ если prompt есть И задан PERPLEXITY_API_KEY:
       askPerplexity(prompt)
         │  POST ${PERPLEXITY_URL}
         │  Authorization: Bearer ${PERPLEXITY_API_KEY}
         │  body: { model: PERPLEXITY_MODEL, messages: [{ role, content }] }
         ▼
       Perplexity API (по умолчанию sonar)
         │
         ▼
       analysis в JSON-ответе (иначе analysis = null)
```

## Параметры запроса к модели

`askPerplexity` отправляет OpenAI-совместимый JSON:

- **URL:** `PERPLEXITY_URL` (дефолт `https://api.perplexity.ai/chat/completions`)
- **Модель:** `PERPLEXITY_MODEL` (дефолт `sonar`)
- **Сообщения:** один `user`-message с текстом `prompt` из тела запроса
- **Авторизация:** `Bearer ${PERPLEXITY_API_KEY}`

Скриншот **не** передаётся в Perplexity: анализ идёт только по текстовому `prompt`.
Если ключа нет или `prompt` не передан — захват скриншота всё равно работает,
`analysis` будет `null`.

## Переменные окружения (текущие + заготовка фазы 0)

Уже используются:

| Переменная | Назначение |
| --- | --- |
| `PERPLEXITY_API_KEY` | Ключ API (опционально для скриншотов) |
| `PERPLEXITY_URL` | Endpoint chat completions |
| `PERPLEXITY_MODEL` | Имя модели |

Добавлены в `.env` / `.env.example` как **заготовка**, пока **не читаются кодом**:

| Переменная | Значение по умолчанию | Смысл |
| --- | --- | --- |
| `LOCAL_LLM_ENABLED` | `false` | Вкл/выкл локального провайдера (Ollama) |
| `LOCAL_LLM_BASE_URL` | `http://<hetzner-gpu-ip>:11434/v1` | OpenAI-совместимый base URL Ollama |
| `LOCAL_LLM_MODEL` | `qwen3:14b` | Модель на GPU-хосте |
| `LOCAL_LLM_TRAFFIC_PERCENT` | `0` | Доля трафика на локальную LLM (0–100) |

## Что намеренно не сделано в фазе 0

- Нет абстракции `provider` / роутера между Perplexity и Ollama
- Нет чтения `LOCAL_LLM_*` в `src/index.js`
- Нет процентного сплита трафика
- Текущий путь Perplexity не изменён

Следующие фазы смогут подключить Ollama за feature-flag, не ломая существующий
вызов Perplexity.
