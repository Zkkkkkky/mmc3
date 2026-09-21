$ErrorActionPreference = "Continue"
$repoRoot = Split-Path -Parent $PSScriptRoot
$python = Join-Path $repoRoot ".venv\Scripts\python.exe"
$probe = Join-Path $repoRoot "tools\research\probe_m06_portrait_blank_upload.py"
$logPath = Join-Path $repoRoot "output\verification\m06-portrait-blank-upload-probe-20260920.log"
Set-Location -LiteralPath $repoRoot
& $python $probe *> $logPath
exit $LASTEXITCODE
