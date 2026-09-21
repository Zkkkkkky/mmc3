$ErrorActionPreference = "Continue"
$repoRoot = Split-Path -Parent $PSScriptRoot
$python = Join-Path $repoRoot ".venv\Scripts\python.exe"
$probe = Join-Path $repoRoot "tools\research\probe_m07_pointer_values.py"
$logPath = Join-Path $repoRoot "output\verification\m07-pointer-values-probe-20260920.log"
Set-Location -LiteralPath $repoRoot
& $python $probe *> $logPath
exit $LASTEXITCODE
