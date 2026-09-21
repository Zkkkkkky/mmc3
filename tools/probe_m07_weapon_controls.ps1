$ErrorActionPreference = "Continue"
$repoRoot = Split-Path -Parent $PSScriptRoot
$python = Join-Path $repoRoot ".venv\Scripts\python.exe"
$probe = Join-Path $repoRoot "tools\research\probe_m07_weapon_controls.py"
$logPath = Join-Path $repoRoot "output\verification\m07-weapon-controls-probe-20260920.log"
Set-Location -LiteralPath $repoRoot
& $python $probe *> $logPath
exit $LASTEXITCODE
