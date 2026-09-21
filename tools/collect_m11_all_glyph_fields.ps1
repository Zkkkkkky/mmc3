$ErrorActionPreference = "Stop"
$repoRoot = Split-Path -Parent $PSScriptRoot
& (Join-Path $repoRoot ".venv\Scripts\python.exe") (Join-Path $repoRoot "tools\research\collect_m11_all_glyph_fields.py")
exit $LASTEXITCODE
