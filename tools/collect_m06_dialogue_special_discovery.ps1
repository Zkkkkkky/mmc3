$ErrorActionPreference = "Continue"
$repoRoot = Split-Path -Parent $PSScriptRoot
$python = Join-Path $repoRoot ".venv\Scripts\python.exe"
$reporter = Join-Path $repoRoot "tools\report_golden_coverage.py"
$baseline = Join-Path $repoRoot "output\build\legacy-diff-audit\m05-reference-baseline.nes"
$config = Join-Path $repoRoot "tools\golden_pipeline\discovery_history\M06-dialogue-special-attack-1-number-discovery-cold-start-01.json"
$logPath = Join-Path $repoRoot "output\verification\m06-dialogue-special-discovery-20260920.log"
Set-Location -LiteralPath $repoRoot
& $python $reporter collect --case-config $config --baseline $baseline *> $logPath
exit $LASTEXITCODE
