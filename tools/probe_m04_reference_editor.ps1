$ErrorActionPreference = "Stop"
$repoRoot = Split-Path -Parent $PSScriptRoot
Set-Location $repoRoot
& ".\.venv\Scripts\python.exe" "tools\research\probe_m04_reference_editor.py"
exit $LASTEXITCODE
