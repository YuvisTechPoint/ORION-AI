param(
    [switch]$SkipCanonical,
    [switch]$SkipAiCicd,
    [switch]$SkipDevops,
    [switch]$SkipPlaywright,
    [switch]$Offline
)

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $MyInvocation.MyCommand.Path
$python = Join-Path $root ".venv/Scripts/python.exe"

if (!(Test-Path $python)) {
    throw "Virtual environment not found at $python"
}

function Invoke-StepCommand {
    param(
        [Parameter(Mandatory)]
        [scriptblock]$Command
    )
    # Native tools (pytest, npm, npx) may write notices to stderr; do not treat that as failure.
    $prev = $ErrorActionPreference
    $ErrorActionPreference = "Continue"
    & $Command
    $exitCode = $LASTEXITCODE
    $ErrorActionPreference = $prev
    if ($exitCode -ne 0) {
        exit $exitCode
    }
}

Write-Host "=== Binary-v2 full E2E verification ===" -ForegroundColor Cyan

$step = 0
Write-Host "`n[0] Architecture wiring verification..." -ForegroundColor Yellow
Invoke-StepCommand { & $python (Join-Path $root "scripts/verify_architecture_wiring.py") }
Invoke-StepCommand { & $python -m pytest (Join-Path $root "tests/test_architecture_wiring.py") -q --tb=line }

$steps = [System.Collections.Generic.List[string]]::new()
if (-not $SkipCanonical) { [void]$steps.Add("canonical") }
if (-not $SkipAiCicd) {
    [void]$steps.Add("ai-cicd-tests")
    [void]$steps.Add("ai-cicd-e2e")
}
if (-not $SkipDevops) { [void]$steps.Add("devops") }
if (-not $SkipPlaywright) {
    [void]$steps.Add("hub")
    [void]$steps.Add("playwright")
}
$total = $steps.Count
$step = 0

if (-not $SkipCanonical) {
    $step++
    Write-Host "`n[$step/$total] Canonical backend tests..." -ForegroundColor Yellow
    Push-Location (Join-Path $root "backend")
    $savedDatabaseUrl = $env:DATABASE_URL
    $savedSyncDatabaseUrl = $env:SYNC_DATABASE_URL
    $env:DATABASE_URL = "sqlite:///./test_devops_platform.db"
    $env:SYNC_DATABASE_URL = "sqlite:///./test_devops_platform.db"
    Invoke-StepCommand { & $python -m pytest tests/ -q --tb=line }
    if ($null -ne $savedDatabaseUrl) { $env:DATABASE_URL = $savedDatabaseUrl } else { Remove-Item Env:DATABASE_URL -ErrorAction SilentlyContinue }
    if ($null -ne $savedSyncDatabaseUrl) { $env:SYNC_DATABASE_URL = $savedSyncDatabaseUrl } else { Remove-Item Env:SYNC_DATABASE_URL -ErrorAction SilentlyContinue }
    Pop-Location
}

if (-not $SkipAiCicd) {
    $step++
    Write-Host "`n[$step/$total] ai-cicd-pipeline tests..." -ForegroundColor Yellow
    Push-Location (Join-Path $root "ai-cicd-pipeline")
    Invoke-StepCommand { & $python -m pytest tests/ -q --tb=line }
    Pop-Location

    $step++
    Write-Host "`n[$step/$total] ai-cicd offline E2E scenario..." -ForegroundColor Yellow
    Push-Location (Join-Path $root "ai-cicd-pipeline")
    $e2eArgs = @("scripts/e2e_run.py", "--scenario", "pass")
    if ($Offline) { $e2eArgs += "--offline" }
    Invoke-StepCommand { & $python @e2eArgs }
    Pop-Location
}

if (-not $SkipDevops) {
    $step++
    Write-Host "`n[$step/$total] devops-platform tests..." -ForegroundColor Yellow
    Push-Location (Join-Path $root "devops-platform")
    $savedAppEnv = $env:APP_ENV
    $savedApiAuth = $env:API_REQUIRE_AUTH
    $savedDatabaseUrl = $env:DATABASE_URL
    $savedSyncDatabaseUrl = $env:SYNC_DATABASE_URL
    $env:APP_ENV = "development"
    $env:API_REQUIRE_AUTH = "false"
    $dbPath = Join-Path (Get-Location) ".pytest_devops.db"
    $env:DATABASE_URL = "sqlite+aiosqlite:///$($dbPath.Replace('\', '/'))"
    $env:SYNC_DATABASE_URL = "sqlite:///$($dbPath.Replace('\', '/'))"
    Invoke-StepCommand { & $python -m pytest tests/ -q --tb=line }
    if ($null -ne $savedAppEnv) { $env:APP_ENV = $savedAppEnv } else { Remove-Item Env:APP_ENV -ErrorAction SilentlyContinue }
    if ($null -ne $savedApiAuth) { $env:API_REQUIRE_AUTH = $savedApiAuth } else { Remove-Item Env:API_REQUIRE_AUTH -ErrorAction SilentlyContinue }
    if ($null -ne $savedDatabaseUrl) { $env:DATABASE_URL = $savedDatabaseUrl } else { Remove-Item Env:DATABASE_URL -ErrorAction SilentlyContinue }
    if ($null -ne $savedSyncDatabaseUrl) { $env:SYNC_DATABASE_URL = $savedSyncDatabaseUrl } else { Remove-Item Env:SYNC_DATABASE_URL -ErrorAction SilentlyContinue }
    Pop-Location
}

if (-not $SkipPlaywright) {
    $step++
    Write-Host "`n[$step/$total] Hub federation tests..." -ForegroundColor Yellow
    Invoke-StepCommand { & $python -m pytest tests/hub/ -q --tb=line }

    $step++
    Write-Host "`n[$step/$total] Playwright hub smoke..." -ForegroundColor Yellow
    Push-Location (Join-Path $root "e2e")
    if (-not (Test-Path "node_modules")) {
        Invoke-StepCommand { npm install --silent }
    }
    Invoke-StepCommand { npx playwright install chromium }
    Invoke-StepCommand { npx playwright test tests/hub.spec.ts tests/stacks.spec.ts tests/navigation.spec.ts tests/operations.spec.ts }
    Pop-Location
}

Write-Host "`nAll E2E checks passed." -ForegroundColor Green
Write-Host "Start stacks:"
Write-Host "  All stacks: .\run_all_stacks.ps1"
Write-Host "  Canonical:  .\run_local_all.ps1"
Write-Host "  ai-cicd:    cd ai-cicd-pipeline; .\scripts\run_local.ps1 -Background"
Write-Host "  devops:     cd devops-platform\backend; ..\.venv\Scripts\uvicorn.exe app.main:app --port 8002"
