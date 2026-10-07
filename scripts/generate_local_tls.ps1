# Generate self-signed TLS certs for local nginx production testing.
# Output: observability/tls/local/fullchain.pem + privkey.pem

param(
    [string]$HostName = "orion.local",
    [int]$Days = 365
)

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
$outDir = Join-Path $root "observability\tls\local"
New-Item -ItemType Directory -Force -Path $outDir | Out-Null

$openssl = Get-Command openssl -ErrorAction SilentlyContinue
if (-not $openssl) {
    throw "openssl not found on PATH. Install OpenSSL or use mkcert for trusted local certs."
}

$key = Join-Path $outDir "privkey.pem"
$cert = Join-Path $outDir "fullchain.pem"
$csr = Join-Path $outDir "server.csr"

& openssl req -x509 -newkey rsa:4096 -sha256 -days $Days -nodes `
    -keyout $key -out $cert `
    -subj "/CN=$HostName" `
    -addext "subjectAltName=DNS:$HostName,DNS:localhost,IP:127.0.0.1"

Write-Host "TLS material written to $outDir" -ForegroundColor Green
Write-Host "Mount into nginx: /etc/nginx/ssl/fullchain.pem and privkey.pem"
Write-Host "Add to hosts file: 127.0.0.1 $HostName"
