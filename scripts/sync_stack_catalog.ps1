# Sync config/stacks.json -> hub/stacks.json for static Command Hub (python http.server).
$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $MyInvocation.MyCommand.Path
if ((Split-Path -Leaf $root) -eq "scripts") { $root = Split-Path -Parent $root }

$src = Join-Path $root "config\stacks.json"
$dst = Join-Path $root "hub\stacks.json"
if (!(Test-Path $src)) {
    Write-Warning "Missing $src"
    exit 1
}

$raw = Get-Content $src -Raw | ConvertFrom-Json
$out = @($raw.stacks | Where-Object { $_.id -ne "hub" } | ForEach-Object {
    @{
        id = $_.id
        title = $_.title
        desc = $_.description
        ui = $_.ui
        health = $_.health
        ready = $_.ready
        intelligence = $_.intelligence
        metaKeys = $_.metaKeys
    }
})
$out | ConvertTo-Json -Depth 6 | Set-Content -Path $dst -Encoding UTF8
Write-Host "Synced stack catalog -> $dst ($($out.Count) stacks)"
