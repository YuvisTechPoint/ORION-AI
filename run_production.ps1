param(
    [switch]$SkipPreflight,
    [switch]$SkipDocker,
    [switch]$SkipInstall,
    [switch]$GenerateSecrets,
    [switch]$ForceSecrets,
    [switch]$LocalSim
)

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $MyInvocation.MyCommand.Path
$python = Join-Path $root ".venv\Scripts\python.exe"

if (!(Test-Path $python)) {
    throw "Virtual environment not found at $python - run: python -m venv .venv"
}

function Import-DotEnvFile {
    param([string]$Path)
    if (!(Test-Path $Path)) { return }
    Get-Content $Path | ForEach-Object {
        $line = $_.Trim()
        if (-not $line -or $line.StartsWith("#") -or -not $line.Contains("=")) { return }
        $parts = $line.Split("=", 2)
        $key = $parts[0].Trim()
        $val = $parts[1].Trim()
        if ($val.StartsWith('"') -and $val.EndsWith('"')) { $val = $val.Substring(1, $val.Length - 2) }
        [System.Environment]::SetEnvironmentVariable($key, $val, "Process")
    }
}

Write-Host "=== ORION Binary-v2 production launcher ===" -ForegroundColor Cyan

if ($GenerateSecrets -or $ForceSecrets) {
    $genArgs = @((Join-Path $root "scripts\generate_production_env.py"))
    if ($ForceSecrets) { $genArgs += "--force" }
    if ($LocalSim) { $genArgs += "--local-sim" }
    & $python @genArgs
    if ($LASTEXITCODE -ne 0) { throw "generate_production_env.py failed" }
}

$required = @(
    (Join-Path $root "ai-cicd-pipeline\.env.production"),
    (Join-Path $root "backend\.env.production"),
    (Join-Path $root "devops-platform\.env.production")
)
$missing = $required | Where-Object { -not (Test-Path $_) }
if ($missing.Count -gt 0) {
    Write-Host "`nMissing production env files." -ForegroundColor Yellow
    Write-Host "  Run: .\run_production.ps1 -GenerateSecrets" -ForegroundColor Yellow
    foreach ($m in $missing) {
        $example = $m -replace '\.env\.production$', '.env.production.example'
        Write-Host "  or: copy $example -> $m"
    }
    throw "Create .env.production files before running production mode."
}

# Load only shared ORION automation key here; per-stack env is loaded by run_all_stacks.ps1
$orionProd = Join-Path $root "ai-cicd-pipeline\.env.production"
if (Test-Path $orionProd) {
    foreach ($line in Get-Content $orionProd) {
        if ($line -match '^\s*ORION_API_KEY\s*=\s*(.+)$') {
            $env:ORION_API_KEY = $Matches[1].Trim()
        }
        if ($line -match '^\s*PRODUCTION_LOCAL_SIM\s*=\s*(.+)$') {
            $env:PRODUCTION_LOCAL_SIM = $Matches[1].Trim()
        }
    }
}
$env:APP_ENV = "production"
if ($LocalSim -or $env:PRODUCTION_LOCAL_SIM -eq "true") {
    $env:PRODUCTION_LOCAL_SIM = "true"
    Write-Host "PRODUCTION_LOCAL_SIM enabled (auth + gates on, SQLite backend)" -ForegroundColor Yellow
}
if ($env:ORION_API_KEY) {
    Write-Host "ORION_API_KEY loaded (use for CLI / X-ORION-API-Key)" -ForegroundColor DarkGray
}

$infraEnv = Join-Path $root ".env.prod.infra"
if (-not (Test-Path $infraEnv)) {
    Write-Host "Missing .env.prod.infra - run with -GenerateSecrets" -ForegroundColor Yellow
}

$dockerCmd = Get-Command docker -ErrorAction SilentlyContinue
if (-not $SkipDocker -and -not $dockerCmd) {
    Write-Host "Docker not found - enabling PRODUCTION_LOCAL_SIM (SQLite, no Redis required)" -ForegroundColor Yellow
    $SkipDocker = $true
    $LocalSim = $true
    $env:PRODUCTION_LOCAL_SIM = "true"
    $orionEnvPath = Join-Path $root "ai-cicd-pipeline\.env.production"
    $needsRegen = $true
    if (Test-Path $orionEnvPath) {
        $raw = Get-Content $orionEnvPath -Raw
        if ($raw -match 'PRODUCTION_LOCAL_SIM=true') { $needsRegen = $false }
    }
    if ($needsRegen) {
        & $python (Join-Path $root "scripts\generate_production_env.py") --force --local-sim
        if ($LASTEXITCODE -ne 0) { throw "generate_production_env.py --local-sim failed" }
    }
}

if (-not $SkipDocker) {
    Write-Host "`n[infra] Starting PostgreSQL + Redis (docker-compose.prod.yml)" -ForegroundColor Yellow
    Push-Location $root
    if (Test-Path $infraEnv) {
        docker compose --env-file .env.prod.infra -f docker-compose.prod.yml up -d
    } else {
        docker compose -f docker-compose.prod.yml up -d
    }
    Pop-Location
    Write-Host "Waiting for Postgres health..." -ForegroundColor DarkGray
    $deadline = (Get-Date).AddSeconds(45)
    $pgReady = $false
    while ((Get-Date) -lt $deadline) {
        try {
            docker compose --env-file $infraEnv -f (Join-Path $root "docker-compose.prod.yml") exec -T postgres pg_isready -U orion 2>$null | Out-Null
            if ($LASTEXITCODE -eq 0) { $pgReady = $true; break }
        } catch { }
        Start-Sleep -Seconds 2
    }
    if (-not $pgReady) { Write-Host "Postgres may still be starting - continuing" -ForegroundColor Yellow }
}

if (-not $SkipPreflight) {
    Write-Host "`n[preflight] Validating production configuration" -ForegroundColor Yellow
    & $python (Join-Path $root "scripts\production_preflight.py")
    if ($LASTEXITCODE -ne 0) {
        throw "Production preflight failed - fix .env.production placeholders and re-run."
    }
}

Write-Host "`n[stacks] Starting all stacks in production mode" -ForegroundColor Yellow
$stackArgs = @("-ExecutionPolicy", "Bypass", "-File", (Join-Path $root "run_all_stacks.ps1"))
if ($SkipInstall) { $stackArgs += "-SkipInstall" }
& powershell @stackArgs
if ($LASTEXITCODE -ne 0) { throw "run_all_stacks.ps1 failed with exit code $LASTEXITCODE" }

Write-Host "`nProduction endpoints:" -ForegroundColor Green
Write-Host "  Hub:        http://127.0.0.1:5180"
Write-Host "  ORION:      http://127.0.0.1:8001/ui/"
Write-Host "  Checklist:  http://127.0.0.1:8001/api/v1/production/checklist"
Write-Host "  Prod ready: http://127.0.0.1:8001/api/v1/production/ready"
Write-Host "`nStop: .\stop_local_all.ps1 ; docker compose -f docker-compose.prod.yml down" -ForegroundColor Cyan
