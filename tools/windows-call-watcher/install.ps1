param(
    [string]$ConfigPath = (Join-Path $PSScriptRoot "config.json")
)

$ErrorActionPreference = "Stop"
$Launcher = (Get-Command py.exe -ErrorAction Stop).Source
$RepoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path
$VenvPython = Join-Path $RepoRoot ".venv\Scripts\python.exe"
$Script = Join-Path $PSScriptRoot "watch_calls.py"
$Example = Join-Path $PSScriptRoot "config.example.json"

if (-not (Test-Path $ConfigPath)) {
    Copy-Item $Example $ConfigPath
    Write-Host "Создан config.json с папкой Documents\SamsungCalls."
}

if (-not (Test-Path $VenvPython)) {
    & $Launcher -m venv (Join-Path $RepoRoot ".venv")
}
& $VenvPython -m pip install --upgrade pip
& $VenvPython -m pip install -e $RepoRoot
& $VenvPython -m pip install --upgrade faster-whisper
if ($LASTEXITCODE -ne 0) {
    throw "Не удалось установить зависимости Оркестра"
}

$Config = Get-Content $ConfigPath -Raw | ConvertFrom-Json
$WatchDir = [Environment]::ExpandEnvironmentVariables($Config.watch_dir)
New-Item -ItemType Directory -Path $WatchDir -Force | Out-Null

$ApiAction = New-ScheduledTaskAction `
    -Execute $VenvPython `
    -Argument "-m uvicorn orchestra.main:app --host 127.0.0.1 --port 8787" `
    -WorkingDirectory $RepoRoot
$WatcherAction = New-ScheduledTaskAction `
    -Execute $VenvPython `
    -Argument "`"$Script`" --config `"$ConfigPath`""
$Trigger = New-ScheduledTaskTrigger -AtLogOn
$Settings = New-ScheduledTaskSettingsSet `
    -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries `
    -RestartCount 3 `
    -RestartInterval (New-TimeSpan -Minutes 1)

Register-ScheduledTask `
    -TaskName "AI Orchestra API" `
    -Description "Запускает локальный API ИИ-Оркестра" `
    -Action $ApiAction `
    -Trigger $Trigger `
    -Settings $Settings `
    -Force | Out-Null

Register-ScheduledTask `
    -TaskName "AI Orchestra Call Watcher" `
    -Description "Переводит записи Samsung в текст и передаёт их ИИ-Оркестру" `
    -Action $WatcherAction `
    -Trigger $Trigger `
    -Settings $Settings `
    -Force | Out-Null

Start-ScheduledTask -TaskName "AI Orchestra API"
Start-Sleep -Seconds 3
Start-ScheduledTask -TaskName "AI Orchestra Call Watcher"
Write-Host "Готово: Оркестр и обработчик звонков установлены и запущены."
Write-Host "Папка для синхронизации Samsung: $WatchDir"
