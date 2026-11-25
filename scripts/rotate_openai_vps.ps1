# Run: .\scripts\rotate_openai_vps.ps1 -SshHost <your-SSH-alias>
param([Parameter(Mandatory=$true)][string]$SshHost)

$ErrorActionPreference = 'Stop'
$buffer = [System.Text.StringBuilder]::new()
$previousOutputEncoding = $OutputEncoding
try {
    Write-Host 'New Watcher OpenAI key (*): ' -NoNewline
    while ($true) {
        $key = [Console]::ReadKey($true)
        if ($key.Key -eq [ConsoleKey]::Enter) { Write-Host ''; break }
        if (($key.Modifiers -band [ConsoleModifiers]::Control) -and $key.Key -eq [ConsoleKey]::C) {
            throw 'Cancelled.'
        }
        if ($key.Key -eq [ConsoleKey]::Backspace) {
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
    if ($buffer.Length -eq 0 -or $buffer.ToString() -match '\s') { throw 'Key is empty or contains whitespace.' }
    $OutputEncoding = [System.Text.UTF8Encoding]::new($false)
    $buffer.ToString() | & ssh -o BatchMode=yes $SshHost 'cd /opt/des-job-watcher && .venv/bin/python -B -m examples.rotate_openai_key'
    if ($LASTEXITCODE -ne 0) { throw 'Rotation did not complete successfully. See message above.' }
}
finally {
    $OutputEncoding = $previousOutputEncoding
    [void]$buffer.Clear()
    $key = $null
}
