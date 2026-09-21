$ErrorActionPreference = "Continue"
$repoRoot = Split-Path -Parent $PSScriptRoot
$python = Join-Path $repoRoot ".venv\Scripts\python.exe"
$reporter = Join-Path $repoRoot "tools\report_golden_coverage.py"
$config = Join-Path $repoRoot "tools\golden_pipeline\cases\M07-name-token-cold-start-01.json"
$baseline = Join-Path $repoRoot "output\build\legacy-diff-audit\m05-reference-baseline.nes"
$logPath = Join-Path $repoRoot "output\verification\m07-name-formal-20260920.log"
Set-Location -LiteralPath $repoRoot
& $python $reporter collect --case-config $config --baseline $baseline *> $logPath
exit $LASTEXITCODE
