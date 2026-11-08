param(
    [string[]]$CaseIds = @(),
    [string]$Manifest,
    [string]$ProfileDirectory,
    [switch]$Synthetic
)

$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $PSScriptRoot
$pythonPath = Join-Path $projectRoot '.venv\Scripts\python.exe'
$previousKey = $env:OPENAI_API_KEY
$previousEncoding = $env:PYTHONIOENCODING
$secret = $null
$secretPointer = [IntPtr]::Zero
$runExitCode = 1
$caseArguments = @()
foreach ($caseId in $CaseIds) { $caseArguments += @('--case', $caseId) }
if ($Manifest) { $caseArguments += @('--manifest', $Manifest) }
if ($ProfileDirectory) { $caseArguments += @('--profile-directory', $ProfileDirectory) }
if ($Synthetic) { $caseArguments += '--synthetic' }

Push-Location -LiteralPath $projectRoot
try {
    $env:PYTHONIOENCODING = 'utf-8'
    & $pythonPath -m examples.run_evaluation @caseArguments
    if ($LASTEXITCODE -ne 0) { throw 'Preflight failed. No API request was made.' }
    Write-Host ''
    Write-Host '=== NEXT: PAID API RUN. WAITING FOR YOUR KEY ===' -ForegroundColor Yellow
    Write-Host 'One request per listed case, sequentially, no retries.'
    $secret = Read-Host 'PASTE OPENAI KEY HERE (masked), then press ENTER' -AsSecureString
    if ($secret.Length -eq 0) { throw 'The API key is empty.' }
    $secretPointer = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($secret)
    $env:OPENAI_API_KEY = [Runtime.InteropServices.Marshal]::PtrToStringBSTR($secretPointer)
    [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($secretPointer)
    $secretPointer = [IntPtr]::Zero
    & $pythonPath -m examples.run_evaluation @caseArguments --live
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
