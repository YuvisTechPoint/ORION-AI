# Cross-stack production preflight wrapper (exit code 0 = ready).
$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $MyInvocation.MyCommand.Path
if ((Split-Path -Leaf $root) -eq "scripts") { $root = Split-Path -Parent $root }
$python = Join-Path $root ".venv\Scripts\python.exe"
if (!(Test-Path $python)) { throw "Missing venv at $python" }
& $python (Join-Path $root "scripts\production_preflight.py")
exit $LASTEXITCODE
