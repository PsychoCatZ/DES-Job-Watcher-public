# Запуск: .\scripts\start_session.ps1
# Переменные окружения сохраняются в текущем PowerShell до закрытия окна.
param([switch]$Replace)

$ErrorActionPreference = 'Stop'

function Read-MaskedSessionValue([string]$Prompt) {
    Write-Host $Prompt -NoNewline
    $buffer = [System.Text.StringBuilder]::new()
    while ($true) {
        $key = [Console]::ReadKey($true)
        if ($key.Key -eq [ConsoleKey]::Enter) {
            Write-Host ''
            return $buffer.ToString()
        }
        if (($key.Modifiers -band [ConsoleModifiers]::Control) -and $key.Key -eq [ConsoleKey]::C) {
            Write-Host ''
            throw 'Input cancelled.'
        }
        if (($key.Modifiers -band [ConsoleModifiers]::Control) -and $key.Key -eq [ConsoleKey]::U) {
            Write-Host ("`b `b" * $buffer.Length) -NoNewline
            [void]$buffer.Clear()
        }
        elseif ($key.Key -eq [ConsoleKey]::Backspace) {
            if ($buffer.Length -gt 0) {
                [void]$buffer.Remove($buffer.Length - 1, 1)
                Write-Host "`b `b" -NoNewline
            }
        }
        elseif (-not [char]::IsControl($key.KeyChar)) {
            [void]$buffer.Append($key.KeyChar)
            Write-Host '*' -NoNewline
        }
    }
}

foreach ($name in @('HH_ACCESS_TOKEN', 'OPENAI_API_KEY', 'TELEGRAM_BOT_TOKEN')) {
    if (-not $Replace -and [Environment]::GetEnvironmentVariable($name, 'Process')) {
        Write-Host "$name is already set for this window."
        continue
    }
    $value = Read-MaskedSessionValue "$name (*; Enter to skip): "
    if ($value.Length -gt 0) {
        if ($value -match '\s') { throw 'Secret contains whitespace. Run again and correct the input.' }
        [Environment]::SetEnvironmentVariable($name, $value, 'Process')
    }
    $value = $null
}
if ($Replace -or -not $env:HH_USER_AGENT) {
    $agent = Read-Host 'HH-User-Agent (Enter to keep current value)'
    if ($agent.Trim()) { $env:HH_USER_AGENT = $agent.Trim() }
}
Write-Host 'Session configured. Values are not saved to disk. Close this PowerShell window to end the session.'
