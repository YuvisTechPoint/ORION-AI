$ErrorActionPreference = "Stop"

$root = Split-Path -Parent $MyInvocation.MyCommand.Path
$python = Join-Path $root ".venv/Scripts/python.exe"
$backend = Join-Path $root "backend"

if (!(Test-Path $python)) {
    throw "Python virtual environment not found at $python"
}

Push-Location $backend
& $python scripts/preflight_check.py
$exitCode = $LASTEXITCODE
Pop-Location

if ($exitCode -eq 0) {
    Write-Host "Preflight passed."
} else {
    Write-Host "Preflight failed. See report above."
}

exit $exitCode
