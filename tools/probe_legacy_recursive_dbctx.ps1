$ErrorActionPreference = "Stop"

$repoRoot = Split-Path -Parent $PSScriptRoot
$python = Join-Path $repoRoot ".venv\Scripts\python.exe"
$probe = Join-Path $repoRoot "tools\research\legacy_ui_probe.py"
$logPath = Join-Path $repoRoot "output\verification\legacy-ui-probe-recursive-dbctx-03.log"

Set-Location -LiteralPath $repoRoot
& $python $probe --stage A,LOAD,DBCTX --evidence-tag recursive-dbctx-03 2>&1 |
    Set-Content -LiteralPath $logPath -Encoding utf8
exit $LASTEXITCODE
