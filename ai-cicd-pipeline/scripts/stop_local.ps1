# Stop background ORION + staging started by run_local.ps1 -Background

$Root = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
$pidFile = Join-Path $Root ".local\run.pids"

function Stop-PortListener([int]$listenPort) {
    Get-NetTCPConnection -LocalPort $listenPort -State Listen -ErrorAction SilentlyContinue |
        ForEach-Object { Stop-Process -Id $_.OwningProcess -Force -ErrorAction SilentlyContinue }
}

if (Test-Path $pidFile) {
    foreach ($line in Get-Content $pidFile) {
        if ($line -match '^(staging|api)=(\d+)$') {
            Stop-Process -Id ([int]$Matches[2]) -Force -ErrorAction SilentlyContinue
        }
        if ($line -match '^port=(\d+)$') { Stop-PortListener ([int]$Matches[1]) }
        if ($line -match '^staging_port=(\d+)$') { Stop-PortListener ([int]$Matches[1]) }
    }
    Remove-Item $pidFile -Force
}

# Fallback for processes started outside the pid file.
Stop-PortListener 8001
Stop-PortListener 8080
Write-Host "Stopped local ORION processes." -ForegroundColor Green
