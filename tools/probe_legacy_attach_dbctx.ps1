$ErrorActionPreference = "Stop"

$repoRoot = Split-Path -Parent $PSScriptRoot
$python = Join-Path $repoRoot ".venv\Scripts\python.exe"
$probe = Join-Path $repoRoot "tools\research\legacy_ui_probe.py"
$logPath = Join-Path $repoRoot "output\verification\legacy-ui-probe-recursive-dbctx-06.log"

Set-Location -LiteralPath $repoRoot
& $python $probe --stage DBCTX --pid 17156 --evidence-tag recursive-dbctx-06 --keep-open-attach 2>&1 |
    Set-Content -LiteralPath $logPath -Encoding utf8
exit $LASTEXITCODE
