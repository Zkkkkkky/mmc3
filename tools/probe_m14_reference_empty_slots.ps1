$ErrorActionPreference = "Stop"
$repoRoot = Split-Path -Parent $PSScriptRoot
$python = Join-Path $repoRoot ".venv\Scripts\python.exe"
& $python (Join-Path $repoRoot "tools\research\probe_m14_reference_field_families.py") --family map_name_empty
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
& $python (Join-Path $repoRoot "tools\research\probe_m14_reference_field_families.py") --family story_text_empty
exit $LASTEXITCODE
