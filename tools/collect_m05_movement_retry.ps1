$ErrorActionPreference = "Continue"

$repoRoot = Split-Path -Parent $PSScriptRoot
$python = Join-Path $repoRoot ".venv\Scripts\python.exe"
$reporter = Join-Path $repoRoot "tools\report_golden_coverage.py"
$baseline = Join-Path $repoRoot "output\build\legacy-diff-audit\m05-reference-baseline.nes"
$config = Join-Path $repoRoot "tools\golden_pipeline\cases\M05-movement-cold-start-01.json"
$logPath = Join-Path $repoRoot "output\verification\m05-movement-retry-20260920.log"

Set-Location -LiteralPath $repoRoot
"M05 movement retry started: $(Get-Date -Format o)" |
    Set-Content -LiteralPath $logPath -Encoding utf8
& $python $reporter collect --case-config $config --baseline $baseline 2>&1 |
    Add-Content -LiteralPath $logPath -Encoding utf8
$exitCode = $LASTEXITCODE
"`nM05 movement retry finished: $(Get-Date -Format o); exit_code=$exitCode" |
    Add-Content -LiteralPath $logPath -Encoding utf8
exit $exitCode
