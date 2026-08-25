# Звонки Samsung → Windows → ИИ‑Оркестр

Поток не использует Bitrix24 и платные API:

1. Samsung Phone сохраняет SIM-звонок в `Recordings/Call`.
2. Syncthing-Fork (Android) синхронизирует эту папку с Windows.
3. `watch_calls.py` бесплатно распознаёт аудио локальной моделью Whisper.
4. Оркестр сохраняет текст, находит проект и предлагает задачи.
5. Задачи появляются только после ручного подтверждения и выполнения action.

Запись разговоров должна выполняться с согласия участников и с учётом местного
законодательства. Не синхронизируйте звонки с паролями и другими секретами.

## 1. Samsung Fold

В Samsung Phone откройте `⋮ → Настройки → Запись вызовов` и включите
автоматическую запись. Типичная папка — `Внутренняя память/Recordings/Call`.

Если пункта записи нет, он отключён прошивкой, регионом или оператором. Обычное
Android-приложение не может надёжно получить обе стороны SIM-звонка. Не
рекомендуется получать root-доступ или менять CSC: это влияет на безопасность,
банковские приложения и гарантию.

Для автоматической передачи установите свободный Syncthing-Fork из F-Droid или
GitHub проекта, добавьте Windows-компьютер и настройте отправку папки
`Recordings/Call` в `%USERPROFILE%\Documents\SamsungCalls`.

## 2. Оркестр на Windows

Запустите Оркестр локально по инструкции в основном `README.md`. В `.env`
создайте отдельный ключ для моста:

```dotenv
API_KEYS=call-watcher-key:operator:personal
```

Скопируйте каталог `tools/windows-call-watcher` на Windows, затем:

```powershell
Copy-Item config.example.json config.json
notepad config.json
PowerShell -ExecutionPolicy Bypass -File .\install.ps1
```

В `config.json` укажите:

- `watch_dir` — папку, куда Syncthing складывает записи;
- `api_url` — адрес Оркестра, обычно `http://localhost:8787`;
- `api_key` — значение `call-watcher-key`, не весь текст `API_KEYS`;
- `process_existing: false` — при первом запуске не отправлять старые записи.

Установщик загружает `faster-whisper`, создаёт задачу Windows «AI Orchestra Call
Watcher» и запускает её при входе пользователя. Модель `small` работает на CPU;
первый запуск дольше обычного, потому что модель загружается один раз.

Ручная проверка:

```powershell
py .\watch_calls.py --config .\config.json --once
```

Watcher также принимает `.txt`: это удобно, если Samsung уже экспортировал
готовую расшифровку.

## 3. API и подтверждение

`POST /v1/calls/intake` принимает форму:

- `metadata` — JSON с `source_id`, датой и устройством;
- `transcript` — готовый текст; либо `file` — аудиозапись для настроенного STT;
- `Idempotency-Key` — SHA-256 файла, предотвращает повторную обработку.

Ответ содержит найденный проект, анализ, черновики и `proposed_actions`.
Повторная отправка возвращает тот же звонок с `duplicate: true`.

Посмотреть историю:

```powershell
Invoke-RestMethod http://localhost:8787/v1/calls `
  -Headers @{"x-api-key"="call-watcher-key"}
```

Для каждой задачи действует безопасный цикл:

```text
proposed → POST /v1/actions/{id}/confirm → POST /v1/actions/{id}/execute
```

До подтверждения задача не создаётся. При выполнении
`orchestra.task.create` задача сохраняется в локальной базе Оркестра, без
Bitrix24.
