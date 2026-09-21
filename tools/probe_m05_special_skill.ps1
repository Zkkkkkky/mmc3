$ErrorActionPreference = "Continue"

$repoRoot = Split-Path -Parent $PSScriptRoot
$python = Join-Path $repoRoot ".venv\Scripts\python.exe"
$probe = Join-Path $repoRoot "tools\research\legacy_ui_probe.py"
$rom = Join-Path $repoRoot "output\build\legacy-diff-audit\probe-m05-special\after.nes"
$logPath = Join-Path $repoRoot "output\verification\m05-special-skill-probe-20260920.log"

Set-Location -LiteralPath $repoRoot
& $python $probe --stage A,M05 --rom $rom --evidence-tag m05-icon-parent-click-20260920n 2>&1 |
    Set-Content -LiteralPath $logPath -Encoding utf8
exit $LASTEXITCODE
