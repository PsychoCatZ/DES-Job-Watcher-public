param(
    [Parameter(Mandatory = $true)]
    [string]$InputPath
)

$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $PSScriptRoot
$pythonPath = Join-Path $projectRoot '.venv\Scripts\python.exe'
$previousKey = $env:OPENAI_API_KEY
$previousEncoding = $env:PYTHONIOENCODING
$secret = $null
$secretPointer = [IntPtr]::Zero
$runExitCode = 1

Push-Location -LiteralPath $projectRoot
try {
    if (-not (Test-Path -LiteralPath $InputPath -PathType Leaf)) {
        throw 'Analysis input file not found.'
    }
    # Проверить актуальность входа до запроса ключа; --live здесь отсутствует.
    & $pythonPath -m examples.analyze_openai --input $InputPath
    if ($LASTEXITCODE -ne 0) { throw 'Input preflight failed. No API request was made.' }
    Write-Host 'One API request: gpt-6-luna, medium, max_output_tokens=8192. No retries.'
    $secret = Read-Host 'Paste the Watcher API key (masked)' -AsSecureString
    if ($secret.Length -eq 0) { throw 'The API key is empty.' }
    $secretPointer = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($secret)
    $env:OPENAI_API_KEY = [Runtime.InteropServices.Marshal]::PtrToStringBSTR($secretPointer)
    [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($secretPointer)
    $secretPointer = [IntPtr]::Zero
    $env:PYTHONIOENCODING = 'utf-8'
    & $pythonPath -m examples.analyze_openai --input $InputPath --live
    $runExitCode = $LASTEXITCODE
}
finally {
    if ($secretPointer -ne [IntPtr]::Zero) {
        [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($secretPointer)
    }
    if ($null -ne $secret) { $secret.Dispose() }
    $env:OPENAI_API_KEY = $previousKey
    $env:PYTHONIOENCODING = $previousEncoding
    Pop-Location
}
exit $runExitCode
