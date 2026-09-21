$ErrorActionPreference = "Stop"
$repoRoot = Split-Path -Parent $PSScriptRoot
& (Join-Path $repoRoot ".venv\Scripts\python.exe") (Join-Path $repoRoot "tools\research\probe_m12_reference_pointer_fields.py")
exit $LASTEXITCODE
