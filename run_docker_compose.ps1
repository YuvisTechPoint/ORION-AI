param(
    [switch]$Detached = $false,
    [switch]$Down = $false,
    [switch]$Build = $true
)

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $MyInvocation.MyCommand.Path

$dockerCmd = Get-Command docker -ErrorAction SilentlyContinue
if ($null -eq $dockerCmd) {
    Write-Host "Docker CLI is not installed or not on PATH."
    Write-Host "Install Docker Desktop and ensure 'docker' is available in terminal."
    exit 1
}

try {
    docker info | Out-Null
} catch {
    Write-Host "Docker is installed but daemon is not running. Start Docker Desktop and retry."
    exit 1
}

Set-Location $root

if ($Down) {
    Write-Host "Running: docker compose down"
    docker compose down
    exit $LASTEXITCODE
}

$args = @("compose", "up")
if ($Build) {
    $args += "--build"
}
if ($Detached) {
    $args += "-d"
}

Write-Host ("Running: docker " + ($args -join " "))
docker @args
exit $LASTEXITCODE
