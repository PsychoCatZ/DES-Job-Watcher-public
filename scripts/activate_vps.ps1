# Запуск из текущего окна с ключами: .\scripts\activate_vps.ps1
param([Parameter(Mandatory=$true)][string]$SshHost)

$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $PSScriptRoot

$running = Get-CimInstance Win32_Process -Filter "Name='python.exe'" |
    Where-Object { $_.CommandLine -match 'examples\.(control_telegram|run_queue|run_once)' }
if ($running) { throw 'Сначала останови локальные раскопки и дождись завершения прохода.' }

foreach ($name in @('HH_ACCESS_TOKEN', 'OPENAI_API_KEY', 'TELEGRAM_BOT_TOKEN', 'HH_USER_AGENT')) {
    if (-not [Environment]::GetEnvironmentVariable($name, 'Process')) {
        & (Join-Path $PSScriptRoot 'start_session.ps1')
        break
    }
}
$values = @{}
foreach ($name in @('HH_USER_AGENT', 'HH_ACCESS_TOKEN', 'OPENAI_API_KEY', 'TELEGRAM_BOT_TOKEN')) {
    $value = [Environment]::GetEnvironmentVariable($name, 'Process')
    if ([string]::IsNullOrWhiteSpace($value)) { throw "Не задано значение $name" }
    $values[$name] = $value
}
# Секреты передаются в stdin SSH, не в аргументах команд или файлах на ПК.
$previousOutputEncoding = $OutputEncoding
try {
    $OutputEncoding = [System.Text.UTF8Encoding]::new($false)
    $values | ConvertTo-Json -Compress | & ssh -o BatchMode=yes $SshHost 'cd /opt/des-job-watcher && .venv/bin/python -m examples.service_runtime --install-credentials'
    if ($LASTEXITCODE -ne 0) { throw 'Передача настроек не завершилась.' }
}
finally {
    $OutputEncoding = $previousOutputEncoding
    $values.Clear()
    $value = $null
}
& ssh -o BatchMode=yes $SshHost 'cd /opt/des-job-watcher && .venv/bin/python -m examples.service_runtime --preflight && systemctl enable --now des-job-watcher.service && systemctl is-active des-job-watcher.service'
if ($LASTEXITCODE -ne 0) { throw 'Контрольная проверка или запуск службы не завершились.' }
Write-Host 'Watcher запущен на VPS. Проверь приветствие и кнопки в Telegram.'
