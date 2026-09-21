$ErrorActionPreference = "Stop"
$repoRoot = Split-Path -Parent $PSScriptRoot
$python = Join-Path $repoRoot ".venv\Scripts\python.exe"
$script = Join-Path $repoRoot "tools\research\probe_m14_reference_list_samples.py"
& $python $script
exit $LASTEXITCODE
