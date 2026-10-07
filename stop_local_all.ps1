$ErrorActionPreference = "Stop"

$root = Split-Path -Parent $MyInvocation.MyCommand.Path
$processFile = Join-Path $root ".local_processes.json"
$stacksFile = Join-Path $root ".local_stacks.json"

function Stop-ByPid {
    param(
        [int]$ProcessId,
        [string]$Name
    )

    $proc = Get-Process -Id $ProcessId -ErrorAction SilentlyContinue
    if ($null -ne $proc) {
        Stop-Process -Id $ProcessId -Force
        Write-Host "Stopped $Name process (PID $ProcessId)."
        return $true
    }
    return $false
}

function Stop-FromMetadataFile {
    param([string]$Path)

    if (!(Test-Path $Path)) { return $false }
    $stopped = $false
    $saved = Get-Content $Path -Raw | ConvertFrom-Json
    foreach ($entry in $saved) {
        if (Stop-ByPid -ProcessId ([int]$entry.pid) -Name ([string]$entry.name)) {
            $stopped = $true
        }
        elseif ($entry.stack -and (Stop-ByPid -ProcessId ([int]$entry.pid) -Name ([string]$entry.stack))) {
            $stopped = $true
        }
    }
    Remove-Item $Path -Force
    Write-Host "Removed metadata file: $Path"
    return $stopped
}

$stoppedAny = $false

if (Stop-FromMetadataFile $processFile) { $stoppedAny = $true }
if (Stop-FromMetadataFile $stacksFile) { $stoppedAny = $true }

# Fallback: stop known dev ports if process metadata is missing or stale.
# Port 3000 is omitted by default — another app (e.g. Vite e-commerce) may own it.
$ports = @(5180, 8000, 8001, 8002, 5173, 5174, 3001, 3002, 3010)
if (Test-Path $stacksFile) {
    try {
        $stackEntries = Get-Content $stacksFile -Raw | ConvertFrom-Json
        foreach ($entry in $stackEntries) {
            if ($null -ne $entry.port) { $ports += [int]$entry.port }
            elseif ($entry.url -match ':(\d+)$') { $ports += [int]$Matches[1] }
        }
    } catch { }
}
$ports = $ports | Select-Object -Unique
foreach ($port in $ports) {
    $connections = Get-NetTCPConnection -LocalPort $port -State Listen -ErrorAction SilentlyContinue
    foreach ($conn in $connections) {
        $ownerPid = [int]$conn.OwningProcess
        if ($ownerPid -gt 0) {
            if (Stop-ByPid -ProcessId $ownerPid -Name ("port-" + $port)) {
                $stoppedAny = $true
            }
        }
    }
}

$orionStop = Join-Path $root "ai-cicd-pipeline\scripts\stop_local.ps1"
if (Test-Path $orionStop) {
    & powershell -ExecutionPolicy Bypass -File $orionStop
    $stoppedAny = $true
}

if (-not $stoppedAny) {
    Write-Host "No local stack processes were running."
} else {
    Write-Host "Local services stopped."
}
