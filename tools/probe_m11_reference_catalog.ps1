$ErrorActionPreference = "Stop"
$repoRoot = Split-Path -Parent $PSScriptRoot
& (Join-Path $repoRoot ".venv\Scripts\python.exe") (Join-Path $repoRoot "tools\research\probe_m11_reference_catalog.py")
exit $LASTEXITCODE
