$ErrorActionPreference = "Continue"

$repoRoot = Split-Path -Parent $PSScriptRoot
$python = Join-Path $repoRoot ".venv\Scripts\python.exe"
$reporter = Join-Path $repoRoot "tools\report_golden_coverage.py"
$caseConfig = Join-Path $repoRoot "tools\golden_pipeline\cases\M05-special-skill-dimension-cold-start-01.json"
$baseline = Join-Path $repoRoot "output\build\legacy-diff-audit\m05-reference-baseline.nes"
$logPath = Join-Path $repoRoot "output\verification\m05-special-skill-collect-20260920.log"

Set-Location -LiteralPath $repoRoot
& $python $reporter collect --case-config $caseConfig --baseline $baseline 2>&1 |
    Set-Content -LiteralPath $logPath -Encoding utf8
exit $LASTEXITCODE
