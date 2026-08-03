# Авто скрин для perplexity + операционный NLP

Node.js-сервис:
1. скриншоты страниц через Playwright (+ опциональный разбор через Perplexity);
2. **операционный NLP для коллектива** (WFO/TOTE) — цели, тесты, коррекции. **Не терапия.**

## Стек

- Node.js >= 18
- Express
- Playwright (chromium)
- Perplexity API (опционально, модель `sonar`)

## Настройка

```bash
cp .env.example .env
npm install
npx playwright install chromium   # без --with-deps на Ubuntu Noble
npm start
```

| Переменная | Описание | По умолчанию |
| --- | --- | --- |
| `PERPLEXITY_API_KEY` | Ключ Perplexity (опционально) | — |
| `PERPLEXITY_URL` | URL endpoint | `https://api.perplexity.ai/chat/completions` |
| `PERPLEXITY_MODEL` | Модель | `sonar` |
| `MIN_CONFIDENCE` | Порог уверенности | `0.78` |
| `PLAYWRIGHT_PROFILE_DIR` | Профиль Playwright | `./pw-profile` |
| `ARTIFACT_DIR` | Скриншоты + NLP JSON | `./artifacts` |
| `PORT` | Порт | `8787` |
| `NLP_STAFF_CYCLE` | Операционный NLP `1`/`0` | `1` |

## Под ключ: день команды

```bash
# 1) Утренний запуск циклов по ростеру (reuseActive не плодит дубли)
curl -X POST http://localhost:8787/nlp/morning \
  -H "Content-Type: application/json" \
  -d '{
    "roster": [
      {"staff":"Альбина","focus":"сдать пустующие на Северной 100","deadline":"2026-08-17"},
      {"staff":"Олег","focus":"закрыть 5 тёплых лидов"}
    ]
  }'

# 2) Доска стендапа
curl http://localhost:8787/nlp/board

# 3) Вечер: тест не пройден → коррекция → тест пройден
curl -X POST http://localhost:8787/nlp/cycle/<id>/advance \
  -H "Content-Type: application/json" \
  -d '{"eventType":"test","passed":false,"note":"0 показов за день"}'

curl -X POST http://localhost:8787/nlp/cycle/<id>/advance \
  -H "Content-Type: application/json" \
  -d '{"eventType":"operate","action":"10 целевых касаний + 2 показа"}'

curl -X POST http://localhost:8787/nlp/cycle/<id>/advance \
  -H "Content-Type: application/json" \
  -d '{"eventType":"test","passed":true,"note":"3 договора"}'
```

Smoke без браузера (сервер должен быть запущен):

```bash
npm run nlp:smoke
```

## API

### Базовое
- `GET /` — карта сервиса
- `GET /health` — статус + счётчики NLP-циклов
- `POST /capture` — скриншот (`url` обязателен, только http/https)

### Операционный NLP (`therapy: false`)
- `GET /nlp/meta`
- `GET /nlp/board` — стендап-доска (STALL/OVERDUE)
- `POST /nlp/morning` — создать/обновить циклы по ростеру
- `POST /nlp/wfo` — Well-Formed Outcome + чеклист
- `POST /nlp/staff-cycle` — план сотрудника (`startCycle`, `reuseActive`)
- `POST /nlp/cycle` / `GET /nlp/cycle` / `GET /nlp/cycle/:id`
- `POST /nlp/cycle/:id/advance` — `test` \| `operate` \| `exit` (для `test` нужен `passed`)
- `POST /nlp/cycle/:id/note` — хвост заметок без смены фазы
- `POST /nlp/cycle/:id/archive` / `POST /nlp/cycle/:id/reopen`

### Модели достижения целей
- `GET /nlp/models` — каталог
- `POST /nlp/models/wfo` — хорошо сформулированный результат + чеклист
- `POST /nlp/models/goal-path` — модель достижения цели (сейчас → вехи → результат)
- `POST /nlp/models/score` — SCORE (симптом/причина/результат/ресурсы/эффект)
- `POST /nlp/models/ecology` — экологическая проверка
- `POST /nlp/models/clarify` — уточняющие вопросы к размытой цели
- `POST /nlp/models/disney` — Мечтатель / Реалист / Критик
- `POST /nlp/models/chunking` — крупнее смысл / конкретнее шаги
- `POST /nlp/models/pack` — все модели сразу; `"startCycle": true` запускает TOTE

```bash
curl -X POST http://localhost:8787/nlp/models/pack \
  -H "Content-Type: application/json" \
  -d '{
    "goal":"Сдать 3 пустующих лота на Северной 100",
    "owner":"Альбина",
    "deadline":"2026-08-17",
    "present":"2 лота пустуют дольше месяца",
    "startCycle":true,
    "staff":"Альбина"
  }'
```

Опция `"ai": true` на wfo/staff-cycle/advance — обогащение через Perplexity, если ключ задан.

Циклы: `ARTIFACT_DIR/nlp-cycles/*.json`.

### Что скопировано из похожих приложений

| Приложение | Взяли |
| --- | --- |
| **Tability** | Weekly check-in, confidence 1–10, статусы on_track/at_risk/off_track |
| **Weekdone** | OKR + Key Results, PPP (plans/progress/problems) |
| **GROW** | Goal→Reality→Options→Will, commitment ≥8 |
| **Range** | Async standup cadence, check-in привязан к цели |
| **Coachful-подход** | Исполнение между ритуалами, retro/learnings |

### Навыки NLP-мастера для ИИ-сотрудников (только работа)
- `GET /nlp/skills` — каталог навыков
- `POST /nlp/skills/pack` — systemPrompt + набор навыков под роль (`sales|ops|manager|analyst|closer|general`)
- `POST /nlp/skills/playbook` — дневной ритуал + правила эскалации
- `POST /nlp/skills/apply` — применить навык к рабочей ситуации

```bash
curl -X POST http://localhost:8787/nlp/skills/pack \
  -H "Content-Type: application/json" \
  -d '{"role":"sales","staff":"Альбина","focus":"сдать лоты Северная 100"}'

curl -X POST http://localhost:8787/nlp/skills/apply \
  -H "Content-Type: application/json" \
  -d '{"skillId":"objection-handle","situation":"Дорого","staff":"Альбина"}'
```

### Бизнес-слой из лучших практик (Tability / Weekdone / GROW)
- `POST /nlp/okr` / `POST /nlp/okr/suggest` — Objective + Key Results + прогресс
- Статусы KR/OKR: `on_track` | `at_risk` | `off_track`
- `POST /nlp/checkin` и `POST /nlp/cycle/:id/checkin` — weekly check-in:
  confidence 1–10 + PPP (plans/progress/problems)
- `GET /nlp/digest` — дайджест: что движется / что буксует / кому check-in
- `POST /nlp/cycle/:id/retro` — ретро по истории цикла
- `POST /nlp/models/grow` — Goal → Reality → Options → Will (commitment)

```bash
# OKR + weekly check-in
curl -X POST http://localhost:8787/nlp/okr \
  -H "Content-Type: application/json" \
  -d '{"goal":"Сдать 3 лота","owner":"Альбина"}'

curl -X POST http://localhost:8787/nlp/okr/<id>/checkin \
  -H "Content-Type: application/json" \
  -d '{"confidence":7,"plans":"2 показа","progress":"1 договор","problems":"цена"}'

curl http://localhost:8787/nlp/digest
```

### Логика «под ключ» (что улучшено)
- Подсказки Operate по тексту блокера (показы, лиды, договоры, цена…)
- Антидубль: активный цикл сотрудника переиспользуется
- Stall (нет движения 24ч) и overdue по `deadline`
- Лимит итераций → статус `review`
- Утренняя доска и notes tail

## Docker

```bash
docker build -t auto-screen .
docker run -p 8787:8787 --env-file .env auto-screen
```

## Структура

```
src/
  index.js
  nlp/
    router.js
    wfo.js
    tote.js
    models.js
    okr.js
    checkin.js
    prompts.js
    store.js
scripts/
  nlp-smoke.js
```
