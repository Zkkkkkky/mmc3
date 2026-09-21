$ErrorActionPreference = "Continue"
$repoRoot = Split-Path -Parent $PSScriptRoot
$python = Join-Path $repoRoot ".venv\Scripts\python.exe"
$reporter = Join-Path $repoRoot "tools\report_golden_coverage.py"
$config = Join-Path $repoRoot "tools\golden_pipeline\cases\M08-battle-01-row000-variant000-cold-start-01.json"
$baseline = Join-Path $repoRoot "output\build\legacy-diff-audit\m05-reference-baseline.nes"
$stdout = Join-Path $repoRoot "output\verification\m08-battle01-retry-stdout.log"
$stderr = Join-Path $repoRoot "output\verification\m08-battle01-retry-stderr.log"
Set-Location -LiteralPath $repoRoot
& $python $reporter collect --case-config $config --baseline $baseline --defer-archive 1> $stdout 2> $stderr
exit $LASTEXITCODE
