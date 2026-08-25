param(
    [string]$ConfigPath = (Join-Path $PSScriptRoot "config.json")
)

$ErrorActionPreference = "Stop"
$Python = (Get-Command py.exe -ErrorAction Stop).Source
$Script = Join-Path $PSScriptRoot "watch_calls.py"
$Example = Join-Path $PSScriptRoot "config.example.json"

if (-not (Test-Path $ConfigPath)) {
    Copy-Item $Example $ConfigPath
    Write-Host "Создан config.json. Укажите в нём папку записей и запустите install.ps1 ещё раз."
    exit 2
}

& $Python -m pip install --upgrade faster-whisper
if ($LASTEXITCODE -ne 0) {
    throw "Не удалось установить faster-whisper"
}

$Action = New-ScheduledTaskAction `
    -Execute $Python `
    -Argument "`"$Script`" --config `"$ConfigPath`""
$Trigger = New-ScheduledTaskTrigger -AtLogOn
$Settings = New-ScheduledTaskSettingsSet `
    -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries `
    -RestartCount 3 `
    -RestartInterval (New-TimeSpan -Minutes 1)

Register-ScheduledTask `
    -TaskName "AI Orchestra Call Watcher" `
    -Description "Переводит записи Samsung в текст и передаёт их ИИ-Оркестру" `
    -Action $Action `
    -Trigger $Trigger `
    -Settings $Settings `
    -Force | Out-Null

Start-ScheduledTask -TaskName "AI Orchestra Call Watcher"
Write-Host "Готово: обработчик звонков установлен и запущен."
