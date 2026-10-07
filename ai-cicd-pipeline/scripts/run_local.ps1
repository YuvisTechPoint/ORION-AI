# Start ORION locally on Windows (SQLite, inline executor, no Redis/Docker required).
# Usage:
#   .\scripts\run_local.ps1              # foreground API (Ctrl+C stops API; staging keeps running)
#   .\scripts\run_local.ps1 -Background # both services in background; PIDs in .local\

param(
    [switch]$Background,
    [int]$Port = 0,
    [int]$StagingPort = 8080
)

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
$RepoRoot = Split-Path -Parent $Root
Set-Location $Root

$syncCatalog = Join-Path $RepoRoot "scripts\sync_stack_catalog.ps1"
if (Test-Path $syncCatalog) {
    & powershell -ExecutionPolicy Bypass -File $syncCatalog | Out-Null
}

$repoVenvPython = Join-Path $RepoRoot ".venv\Scripts\python.exe"
$venvPython = Join-Path $Root ".venv\Scripts\python.exe"
if (Test-Path $repoVenvPython) {
    $venvPython = $repoVenvPython
} elseif (-not (Test-Path $venvPython)) {
    Write-Host "Creating virtualenv..." -ForegroundColor Yellow
    python -m venv .venv
    & $venvPython -m pip install -q -r requirements.txt
}

# Read APP_PORT from .env when not passed explicitly.
if ($Port -le 0) {
    $Port = 8001
    $envFile = Join-Path $Root ".env"
    if (Test-Path $envFile) {
        foreach ($line in Get-Content $envFile) {
            if ($line -match '^\s*APP_PORT\s*=\s*(\d+)') {
                $Port = [int]$Matches[1]
                break
            }
        }
    }
}

$localDir = Join-Path $Root ".local"
New-Item -ItemType Directory -Force -Path $localDir | Out-Null
$pidFile = Join-Path $localDir "run.pids"
$logDir = Join-Path $localDir "logs"
New-Item -ItemType Directory -Force -Path $logDir | Out-Null

function Stop-PortListener([int]$listenPort) {
    Get-NetTCPConnection -LocalPort $listenPort -State Listen -ErrorAction SilentlyContinue |
        ForEach-Object { Stop-Process -Id $_.OwningProcess -Force -ErrorAction SilentlyContinue }
}

function Wait-Http([string]$url, [int]$seconds = 30) {
    $deadline = (Get-Date).AddSeconds($seconds)
    while ((Get-Date) -lt $deadline) {
        try {
            $r = Invoke-WebRequest -UseBasicParsing -Uri $url -TimeoutSec 3
            if ($r.StatusCode -ge 200 -and $r.StatusCode -lt 500) { return $true }
        } catch { Start-Sleep -Milliseconds 400 }
    }
    return $false
}

function Import-DotEnvFile {
    param([string]$Path)
    if (!(Test-Path $Path)) { return }
    Get-Content $Path | ForEach-Object {
        $line = $_.Trim()
        if (-not $line -or $line.StartsWith("#") -or -not $line.Contains("=")) { return }
        $parts = $line.Split("=", 2)
        Set-Item -Path ("env:" + $parts[0].Trim()) -Value $parts[1].Trim()
    }
}

$isProduction = ($env:APP_ENV -eq "production")
$localSim = ($env:PRODUCTION_LOCAL_SIM -eq "true")
if ($isProduction) {
    Import-DotEnvFile (Join-Path $Root ".env.production")
} else {
    Import-DotEnvFile (Join-Path $Root ".env")
}
if (-not $isProduction -or $localSim) {
    $dbPath = Join-Path $localDir "orion.db"
    $env:DATABASE_URL = "sqlite+aiosqlite:///$($dbPath.Replace('\', '/'))"
    $env:SYNC_DATABASE_URL = "sqlite:///$($dbPath.Replace('\', '/'))"
}

Write-Host "==> Migrating database" -ForegroundColor Cyan
& $venvPython -m alembic upgrade head
if ($LASTEXITCODE -ne 0) { throw "alembic upgrade failed" }

Write-Host "==> Starting staging target on port $StagingPort" -ForegroundColor Cyan
Stop-PortListener $StagingPort
$stagingOut = Join-Path $logDir "staging.out.log"
$stagingErr = Join-Path $logDir "staging.err.log"
$stagingProc = Start-Process -FilePath $venvPython `
    -ArgumentList "scripts\staging_server.py", "--port", $StagingPort `
    -WorkingDirectory $Root -PassThru -WindowStyle Hidden `
    -RedirectStandardOutput $stagingOut -RedirectStandardError $stagingErr
if (-not (Wait-Http "http://127.0.0.1:$StagingPort/health")) {
    throw "staging server did not become healthy on port $StagingPort"
}

Write-Host "==> Starting ORION API on port $Port" -ForegroundColor Cyan
Stop-PortListener $Port

$env:STAGING_URL = "http://127.0.0.1:$StagingPort"
if (-not $isProduction) {
    $env:APP_ENV = "development"
    $env:JOURNALD_ENABLED = "false"
    $env:PIPELINE_EXECUTOR = "inline"
    $env:DEPLOY_MODE = "auto"
    $env:STRESS_TEST_USERS = "25"
    $env:STRESS_TEST_SPAWN_RATE = "10"
    $env:STRESS_TEST_DURATION = "15"
}
if (-not $env:FRONTEND_URL) { $env:FRONTEND_URL = "http://localhost:$Port/ui/" }
if (-not $env:GITHUB_REDIRECT_URI) { $env:GITHUB_REDIRECT_URI = "http://localhost:$Port/api/v1/auth/github/callback" }
if (-not $env:CORS_ORIGINS) {
    $env:CORS_ORIGINS = "http://127.0.0.1:$Port,http://127.0.0.1:5173,http://127.0.0.1:3000,http://127.0.0.1:5180,http://localhost:$Port,http://localhost:5173,http://localhost:3000,http://localhost:5180"
}

$apiOut = Join-Path $logDir "orion.out.log"
$apiErr = Join-Path $logDir "orion.err.log"
$ui = "http://127.0.0.1:$Port/ui/"
$docs = "http://127.0.0.1:$Port/docs"
$health = "http://127.0.0.1:$Port/health"

if ($Background) {
    $apiProc = Start-Process -FilePath $venvPython `
        -ArgumentList "-m", "uvicorn", "app.main:app", "--host", "127.0.0.1", "--port", $Port `
        -WorkingDirectory $Root -PassThru -WindowStyle Hidden `
        -RedirectStandardOutput $apiOut -RedirectStandardError $apiErr
    if (-not (Wait-Http $health)) { throw "ORION API did not start on port $Port" }
    @(
        "staging=$($stagingProc.Id)",
        "api=$($apiProc.Id)",
        "port=$Port",
        "staging_port=$StagingPort"
    ) | Set-Content -Path $pidFile -Encoding utf8
    Write-Host ""
    Write-Host "ORION is running in the background." -ForegroundColor Green
    Write-Host "  Dashboard : $ui"
    Write-Host "  API docs  : $docs"
    Write-Host "  Staging   : http://127.0.0.1:$StagingPort/health"
    Write-Host "  Logs      : $logDir"
    Write-Host "  Stop      : .\scripts\stop_local.ps1"
    exit 0
}

Write-Host ""
Write-Host "ORION local stack is up." -ForegroundColor Green
Write-Host "  Dashboard : $ui"
Write-Host "  API docs  : $docs"
Write-Host "  Staging   : http://127.0.0.1:$StagingPort/health"
Write-Host "  Press Ctrl+C to stop the API (run .\scripts\stop_local.ps1 to stop staging too)"
Write-Host ""

try {
    & $venvPython -m uvicorn app.main:app --host 127.0.0.1 --port $Port
} finally {
    if ($stagingProc -and -not $stagingProc.HasExited) {
        Stop-Process -Id $stagingProc.Id -Force -ErrorAction SilentlyContinue
    }
}
