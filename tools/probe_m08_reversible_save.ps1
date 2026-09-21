$ErrorActionPreference = "Stop"
$repoRoot = Split-Path -Parent $PSScriptRoot
$python = Join-Path $repoRoot ".venv\Scripts\python.exe"
$script = Join-Path $repoRoot "tools\research\probe_m08_reversible_save.py"
& $python $script
exit $LASTEXITCODE
