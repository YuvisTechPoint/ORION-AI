# Copy GITHUB_CLIENT_ID and GITHUB_CLIENT_SECRET from backend/.env into ai-cicd-pipeline/.env
# when both stacks share the same GitHub OAuth application.
$ErrorActionPreference = "Stop"
$root = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
$backendEnv = Join-Path $root "..\backend\.env"
$orionEnv = Join-Path $root ".env"
if (-not (Test-Path $backendEnv)) {
    throw "backend/.env not found at $backendEnv"
}
function Get-EnvValue([string]$path, [string]$key) {
    $line = Select-String -Path $path -Pattern "^$key=" | Select-Object -First 1
    if (-not $line) { return $null }
    return ($line.Line -split '=', 2)[1]
}
$cid = Get-EnvValue $backendEnv "GITHUB_CLIENT_ID"
$csec = Get-EnvValue $backendEnv "GITHUB_CLIENT_SECRET"
if (-not $cid -or -not $csec) { throw "GITHUB_CLIENT_ID/SECRET missing in backend/.env" }
$lines = Get-Content $orionEnv
$out = foreach ($l in $lines) {
    if ($l -match '^GITHUB_CLIENT_ID=') { "GITHUB_CLIENT_ID=$cid" }
    elseif ($l -match '^GITHUB_CLIENT_SECRET=') { "GITHUB_CLIENT_SECRET=$csec" }
    else { $l }
}
Set-Content -Path $orionEnv -Value $out -Encoding utf8
Write-Host "Synced GitHub OAuth credentials from backend/.env to ai-cicd-pipeline/.env (restart ORION)."
