param(
    [switch]$ReuseBackend,
    [switch]$SkipFrontend,
    [switch]$SkipInstall
)

$ErrorActionPreference = "Stop"

$root = Split-Path -Parent $MyInvocation.MyCommand.Path
$backend = Join-Path $root "backend"
$frontend = Join-Path $root "frontend"
$python = Join-Path $root ".venv/Scripts/python.exe"
$processFile = Join-Path $root ".local_processes.json"

$startBackendEnabled = -not $ReuseBackend
$startFrontendEnabled = -not $SkipFrontend

function Wait-BackendReady {
    param(
        [int]$MaxAttempts = 15,
        [int]$DelaySeconds = 1
    )

    for ($attempt = 1; $attempt -le $MaxAttempts; $attempt++) {
        try {
            $health = Invoke-RestMethod -Method Get -Uri "http://127.0.0.1:8000/health" -TimeoutSec 3
            if ($null -ne $health -and $health.status -eq "ok") {
                return $true
            }
        } catch {
            Start-Sleep -Seconds $DelaySeconds
        }
    }

    return $false
}

Write-Host "[1/6] Validating environment..."
if (!(Test-Path $python)) {
    throw "Python virtual environment not found at $python"
}

if (-not $SkipInstall) {
    Write-Host "[2/6] Installing dependencies..."
    Push-Location $backend
    & $python -m pip install -r requirements.txt
    Pop-Location

    Push-Location $frontend
    npm install
    Pop-Location
}

Write-Host "[3/6] Running backend tests..."
Push-Location $backend
& $python -m pytest
Pop-Location

if ($startBackendEnabled) {
    Write-Host "[4/6] Starting backend API..."
    $backendProc = Start-Process -FilePath $python -ArgumentList "-m uvicorn main:app --host 0.0.0.0 --port 8000" -WorkingDirectory $backend -PassThru
    if (-not (Wait-BackendReady)) {
        throw "Backend did not become healthy on http://127.0.0.1:8000. Check backend logs and port availability."
    }
} else {
    Write-Host "[4/6] Reusing existing backend API..."
    if (-not (Wait-BackendReady -MaxAttempts 3 -DelaySeconds 1)) {
        throw "Backend reuse requested but no healthy backend detected on http://127.0.0.1:8000. Start backend or run script with -StartBackend `$true."
    }
}

if ($startFrontendEnabled) {
    Write-Host "[5/6] Starting frontend dashboard..."
    $frontendProc = Start-Process -FilePath "cmd.exe" -ArgumentList "/c npm run dev -- --host 0.0.0.0 --port 5173" -WorkingDirectory $frontend -PassThru
    Start-Sleep -Seconds 2
} else {
    Write-Host "[5/6] Skipping frontend startup..."
}

$started = @()
if ($startBackendEnabled -and $backendProc) {
    $started += [pscustomobject]@{
        name = "backend"
        pid = $backendProc.Id
        port = 8000
    }
}
if ($startFrontendEnabled -and $frontendProc) {
    $started += [pscustomobject]@{
        name = "frontend"
        pid = $frontendProc.Id
        port = 5173
    }
}
if ($started.Count -gt 0) {
    $started | ConvertTo-Json | Set-Content -Path $processFile -Encoding UTF8
    Write-Host "Saved process metadata to $processFile"
}

Write-Host "[6/6] Running API smoke checks..."
$health = Invoke-RestMethod -Method Get -Uri "http://127.0.0.1:8000/health"
$sample = Get-Content (Join-Path $root "samples/submit_code_request.json") -Raw
$submit = Invoke-RestMethod -Method Post -Uri "http://127.0.0.1:8000/submit-code" -ContentType "application/json" -Body $sample
$status = Invoke-RestMethod -Method Get -Uri ("http://127.0.0.1:8000/pipeline-status/" + $submit.pipeline_id)

$pySmoke = @"
import httpx
payload = {
  "pipeline_id": "${submit.pipeline_id}",
  "logs": "ERROR timeout",
  "multimodal_inputs": [
    {"modality": "log", "content": "ERROR timeout", "name": "runtime_logs", "metadata": {}},
    {"modality": "metrics", "content": "cpu=88", "name": "runtime_metrics", "metadata": {}}
  ]
}
resp = httpx.post("http://127.0.0.1:8000/analyze-logs", json=payload, timeout=30)
print(resp.status_code)
print(resp.text)
"@

$pyFile = Join-Path $root ".tmp_smoke.py"
Set-Content -Path $pyFile -Value $pySmoke -Encoding UTF8
$monitorOutput = & $python $pyFile
Remove-Item $pyFile -Force

Write-Host "HEALTH: $($health | ConvertTo-Json -Compress)"
Write-Host "SUBMIT: $($submit | ConvertTo-Json -Compress)"
Write-Host "STATUS: stage=$($status.current_stage) status=$($status.status)"
Write-Host "MONITOR:"
$monitorOutput | ForEach-Object { Write-Host $_ }

Write-Host "Done."
if ($startBackendEnabled) {
    Write-Host "Backend PID: $($backendProc.Id)"
}
if ($startFrontendEnabled) {
    Write-Host "Frontend PID: $($frontendProc.Id)"
}
Write-Host "Run ./stop_local_all.ps1 to stop started services cleanly."
