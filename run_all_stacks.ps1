param(
    [switch]$SkipCanonical,
    [switch]$SkipAiCicd,
    [switch]$SkipDevops,
    [switch]$SkipInstall
)

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $MyInvocation.MyCommand.Path
$python = Join-Path $root ".venv/Scripts/python.exe"
$processFile = Join-Path $root ".local_stacks.json"
$isProduction = ($env:APP_ENV -eq "production")
$localSim = ($env:PRODUCTION_LOCAL_SIM -eq "true")
$useSqlite = (-not $isProduction) -or $localSim

if (!(Test-Path $python)) {
    throw "Virtual environment not found at $python"
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

function Wait-HttpOk {
    param(
        [string]$Url,
        [int]$MaxAttempts = 20,
        [int]$DelaySeconds = 1
    )
    for ($i = 1; $i -le $MaxAttempts; $i++) {
        try {
            $r = Invoke-RestMethod -Method Get -Uri $Url -TimeoutSec 3
            if ($null -ne $r) { return $true }
        } catch {
            Start-Sleep -Seconds $DelaySeconds
        }
    }
    return $false
}

function Test-OrionDevopsUi {
    param([int]$Port)
    try {
        $html = (Invoke-WebRequest -UseBasicParsing -Uri "http://127.0.0.1:$Port" -TimeoutSec 3).Content
        return ($html -match 'Multi-Agent DevOps Platform|ORION')
    } catch {
        return $false
    }
}

function Ensure-NpmDependencies {
    param(
        [string]$ProjectDir,
        [switch]$SkipInstall
    )
    $nodeModules = Join-Path $ProjectDir "node_modules"
    if ($SkipInstall -and (Test-Path $nodeModules)) { return }
    Push-Location $ProjectDir
    npm install --silent
    Pop-Location
}

function Resolve-DevopsUiPort {
    param([int[]]$Candidates = @(3000, 3001, 3002, 3010))
    if ($env:DEVOPS_UI_PORT) { return [int]$env:DEVOPS_UI_PORT }
    foreach ($port in $Candidates) {
        $busy = Get-NetTCPConnection -LocalPort $port -State Listen -ErrorAction SilentlyContinue
        if (-not $busy) { return $port }
        if (Test-OrionDevopsUi -Port $port) { return $port }
        Write-Host "Port $port in use by non-ORION app - trying next" -ForegroundColor Yellow
    }
    throw "No DevOps UI port available in: $($Candidates -join ', '). Stop conflicting apps or set DEVOPS_UI_PORT."
}

function Wait-DevopsUiReady {
    param(
        [int]$Port,
        [int]$MaxAttempts = 90
    )
    for ($i = 1; $i -le $MaxAttempts; $i++) {
        try {
            $html = (Invoke-WebRequest -UseBasicParsing -Uri "http://127.0.0.1:$Port" -TimeoutSec 3).Content
            if ($html -match 'Multi-Agent DevOps Platform|ORION') {
                return $true
            }
            Write-Host "Port $Port serves a non-ORION app - stop it or set DEVOPS_UI_PORT" -ForegroundColor Yellow
            return $false
        } catch {
            Start-Sleep -Seconds 1
        }
    }
    return $false
}

function Update-DevopsCatalogPort {
    param([int]$Port)
    $catalogPath = Join-Path $root "config\stacks.json"
    if (!(Test-Path $catalogPath)) { return }
    $catalog = Get-Content $catalogPath -Raw | ConvertFrom-Json
    foreach ($stack in $catalog.stacks) {
        if ($stack.id -eq "platform") {
            $stack.ui = "http://127.0.0.1:$Port"
        }
    }
    $json = $catalog | ConvertTo-Json -Depth 8
    [System.IO.File]::WriteAllText($catalogPath, $json, [System.Text.UTF8Encoding]::new($false))
    & powershell -ExecutionPolicy Bypass -File (Join-Path $root "scripts\sync_stack_catalog.ps1")
}

$started = @()
$devopsUiPort = if ($env:DEVOPS_UI_PORT) { [int]$env:DEVOPS_UI_PORT } else { $null }

Write-Host "=== Binary-v2 - starting all stacks ===" -ForegroundColor Cyan

if ($isProduction) {
    $syncOauth = Join-Path $root "scripts\sync_github_oauth.py"
    if (Test-Path $syncOauth) {
        & $python $syncOauth 2>&1 | Out-Host
    }
}

if (-not $SkipDevops -and -not $devopsUiPort) {
    $devopsUiPort = Resolve-DevopsUiPort
}
if ($devopsUiPort) {
    $env:DEVOPS_UI_URL = "http://127.0.0.1:$devopsUiPort"
    Update-DevopsCatalogPort -Port $devopsUiPort
} else {
    & powershell -ExecutionPolicy Bypass -File (Join-Path $root "scripts\sync_stack_catalog.ps1")
}

Write-Host "`n[hub] ORION Command Hub :5180 (control plane API + UI)" -ForegroundColor Yellow
$hubProc = Start-Process -FilePath $python -ArgumentList "-m uvicorn hub.server:app --host 127.0.0.1 --port 5180" -WorkingDirectory $root -PassThru
$started += [pscustomobject]@{ stack = "hub"; pid = $hubProc.Id; url = "http://127.0.0.1:5180" }
if (-not (Wait-HttpOk "http://127.0.0.1:5180/health" -MaxAttempts 45)) {
    throw "Command Hub did not become healthy on port 5180"
}

if (-not $SkipCanonical) {
    Write-Host "`n[canonical] backend :8000 + frontend :5173" -ForegroundColor Yellow
    if ($isProduction) {
        Import-DotEnvFile (Join-Path $root "backend\.env.production")
    }
    if ($localSim) { $env:PRODUCTION_LOCAL_SIM = "true" }
    if (-not $SkipInstall) {
        Push-Location (Join-Path $root "backend")
        & $python -m pip install -r requirements.txt -q
        Pop-Location
        Ensure-NpmDependencies (Join-Path $root "frontend")
    } else {
        Ensure-NpmDependencies (Join-Path $root "frontend") -SkipInstall
    }
    if ($useSqlite) {
        $env:DATABASE_URL = "sqlite:///./devops_platform.db"
        $env:QA_MODE = if ($isProduction) { "simulated" } else { "simulated" }
        if (-not $isProduction) { $env:LLM_MODE = "auto" }
    }
    $canonicalBackend = Start-Process -FilePath $python -ArgumentList "-m uvicorn main:app --host 127.0.0.1 --port 8000" -WorkingDirectory (Join-Path $root "backend") -PassThru
    if (-not (Wait-HttpOk "http://127.0.0.1:8000/health")) {
        throw "Canonical backend did not become healthy on port 8000"
    }
    $canonicalFrontend = Start-Process -FilePath "cmd.exe" -ArgumentList "/c npm run dev -- --host 127.0.0.1 --port 5173" -WorkingDirectory (Join-Path $root "frontend") -PassThru
    $started += [pscustomobject]@{ stack = "canonical-backend"; pid = $canonicalBackend.Id; url = "http://127.0.0.1:8000" }
    $started += [pscustomobject]@{ stack = "canonical-frontend"; pid = $canonicalFrontend.Id; url = "http://127.0.0.1:5173" }
}

if (-not $SkipAiCicd) {
    Write-Host "`n[ai-cicd] API :8001 + dashboard /ui/ (via run_local.ps1)" -ForegroundColor Yellow
    $orionDir = Join-Path $root "ai-cicd-pipeline"
    if ($isProduction) {
        Import-DotEnvFile (Join-Path $orionDir ".env.production")
    }
    if ($localSim) { $env:PRODUCTION_LOCAL_SIM = "true" }
    & powershell -ExecutionPolicy Bypass -File (Join-Path $orionDir "scripts\run_local.ps1") -Background
    if (-not (Wait-HttpOk "http://127.0.0.1:8001/health")) {
        throw "ai-cicd API did not become healthy on port 8001"
    }
    $pidFile = Join-Path $orionDir ".local\run.pids"
    if (Test-Path $pidFile) {
        foreach ($line in Get-Content $pidFile) {
            if ($line -match '^api=(\d+)$') {
                $started += [pscustomobject]@{ stack = "ai-cicd"; pid = [int]$Matches[1]; url = "http://127.0.0.1:8001/ui/" }
            }
        }
    } else {
        $started += [pscustomobject]@{ stack = "ai-cicd"; pid = 0; url = "http://127.0.0.1:8001/ui/" }
    }
}

if (-not $SkipDevops) {
    Write-Host "`n[devops-platform] API :8002 + frontend :3000" -ForegroundColor Yellow
    if ($isProduction) {
        Import-DotEnvFile (Join-Path $root "devops-platform\.env.production")
    }
    if ($localSim) { $env:PRODUCTION_LOCAL_SIM = "true" }
    if (-not $SkipInstall) {
        Ensure-NpmDependencies (Join-Path $root "devops-platform/frontend")
    } else {
        Ensure-NpmDependencies (Join-Path $root "devops-platform/frontend") -SkipInstall
    }
    if ($useSqlite) {
        if (-not $isProduction) { $env:DEPLOY_MODE = "auto" }
        $devopsLocal = Join-Path $root "devops-platform\backend\.local"
        New-Item -ItemType Directory -Force -Path $devopsLocal | Out-Null
        $devopsDb = Join-Path $devopsLocal "devops.db"
        $env:DATABASE_URL = "sqlite+aiosqlite:///$($devopsDb.Replace('\', '/'))"
        $env:SYNC_DATABASE_URL = "sqlite:///$($devopsDb.Replace('\', '/'))"
        if ($localSim) { $env:PIPELINE_EXECUTOR = "inline" }
    }
    $env:ORION_API_URL = "http://127.0.0.1:8001"
    $devopsBackend = Start-Process -FilePath $python -ArgumentList "-m uvicorn app.main:app --host 127.0.0.1 --port 8002" -WorkingDirectory (Join-Path $root "devops-platform/backend") -PassThru
    if (-not (Wait-HttpOk "http://127.0.0.1:8002/health")) {
        throw "devops-platform API did not become healthy on port 8002"
    }
    if (-not $devopsUiPort) { $devopsUiPort = Resolve-DevopsUiPort }
    $env:DEVOPS_UI_URL = "http://127.0.0.1:$devopsUiPort"
    if ($devopsUiPort -ne 3000) {
        Write-Host "DevOps UI using port $devopsUiPort (3000 unavailable - e.g. another Vite app)" -ForegroundColor Yellow
    }
    $devopsFrontendCmd = "/c set VITE_API_URL=http://127.0.0.1:8002&& set VITE_WS_URL=ws://127.0.0.1:8002&& npm run dev -- --host 127.0.0.1 --port $devopsUiPort"
    $devopsFrontend = Start-Process -FilePath "cmd.exe" -ArgumentList $devopsFrontendCmd -WorkingDirectory (Join-Path $root "devops-platform/frontend") -PassThru
    if (-not (Wait-DevopsUiReady -Port $devopsUiPort)) {
        throw "DevOps UI did not serve ORION frontend on port $devopsUiPort"
    }
    $devopsUiUrl = "http://127.0.0.1:$devopsUiPort"
    $started += [pscustomobject]@{ stack = "devops-backend"; pid = $devopsBackend.Id; url = "http://127.0.0.1:8002/health" }
    $started += [pscustomobject]@{ stack = "devops-frontend"; pid = $devopsFrontend.Id; url = $devopsUiUrl; port = $devopsUiPort }
}

if ($started.Count -gt 0) {
    $started | ConvertTo-Json | Set-Content -Path $processFile -Encoding UTF8
}

Write-Host ''
Write-Host 'Stacks running (devops uses inline executor when Redis is unavailable):' -ForegroundColor Green
$started | ForEach-Object { Write-Host ('  ' + $_.stack + ': ' + $_.url + ' (PID ' + $_.pid + ')') }
Write-Host ''
Write-Host ('Process metadata: ' + $processFile)
Write-Host 'Run .\stop_local_all.ps1 or stop PIDs manually when finished.'
Write-Host 'Verify: .\run_e2e_all.ps1 -Offline'
