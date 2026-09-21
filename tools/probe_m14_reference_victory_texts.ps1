$ErrorActionPreference = "Stop"
$repoRoot = Split-Path -Parent $PSScriptRoot
& (Join-Path $repoRoot ".venv\Scripts\python.exe") (Join-Path $repoRoot "tools\research\probe_m14_reference_victory_texts.py")
exit $LASTEXITCODE
