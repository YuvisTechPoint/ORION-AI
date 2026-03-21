$ErrorActionPreference = "Stop"

$root = Split-Path -Parent $MyInvocation.MyCommand.Path
$processFile = Join-Path $root ".local_processes.json"

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

$stoppedAny = $false

if (Test-Path $processFile) {
    $saved = Get-Content $processFile -Raw | ConvertFrom-Json
    foreach ($entry in $saved) {
        if (Stop-ByPid -ProcessId ([int]$entry.pid) -Name ([string]$entry.name)) {
            $stoppedAny = $true
        }
    }
    Remove-Item $processFile -Force
    Write-Host "Removed process metadata file."
}

# Fallback: stop known dev ports if process metadata is missing or stale.
$ports = @(8000, 5173, 5174)
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

if (-not $stoppedAny) {
    Write-Host "No local backend/frontend processes were running."
} else {
    Write-Host "Local services stopped."
}
