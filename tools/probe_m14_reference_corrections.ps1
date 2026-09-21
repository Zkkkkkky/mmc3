$ErrorActionPreference = "Stop"
$repoRoot = Split-Path -Parent $PSScriptRoot
$python = Join-Path $repoRoot ".venv\Scripts\python.exe"
& $python (Join-Path $repoRoot "tools\research\probe_m14_reference_victory_texts.py")
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
& $python (Join-Path $repoRoot "tools\research\probe_m14_reference_field_families.py") --family surrender_enemy
exit $LASTEXITCODE
