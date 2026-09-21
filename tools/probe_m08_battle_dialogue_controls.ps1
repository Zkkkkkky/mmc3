$ErrorActionPreference = "Continue"
$repoRoot = Split-Path -Parent $PSScriptRoot
$python = Join-Path $repoRoot ".venv\Scripts\python.exe"
$probe = Join-Path $repoRoot "tools\research\probe_m08_battle_dialogue_controls.py"
$log = Join-Path $repoRoot "output\verification\m08-battle-controls-probe-20260920.log"
Set-Location -LiteralPath $repoRoot
& $python $probe *> $log
exit $LASTEXITCODE
