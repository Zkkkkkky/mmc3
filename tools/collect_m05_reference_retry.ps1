$ErrorActionPreference = "Continue"

$repoRoot = Split-Path -Parent $PSScriptRoot
$python = Join-Path $repoRoot ".venv\Scripts\python.exe"
$reporter = Join-Path $repoRoot "tools\report_golden_coverage.py"
$baseline = Join-Path $repoRoot "output\build\legacy-diff-audit\m05-reference-baseline.nes"
$logPath = Join-Path $repoRoot "output\verification\m05-reference-retry-20260920.log"
$cases = @(
    "M05-movement-cold-start-01.json",
    "M05-speed-cold-start-01.json",
    "M05-hp-cold-start-01.json"
)

Set-Location -LiteralPath $repoRoot
"M05 reference retry started: $(Get-Date -Format o)" |
    Set-Content -LiteralPath $logPath -Encoding utf8
$failed = 0
foreach ($caseName in $cases) {
    $config = Join-Path $repoRoot "tools\golden_pipeline\cases\$caseName"
    "`n=== $caseName ===" | Add-Content -LiteralPath $logPath -Encoding utf8
    # Do not pass --budget-seconds: the collector's immutable 30-second gate applies.
    & $python $reporter collect --case-config $config --baseline $baseline 2>&1 |
        Add-Content -LiteralPath $logPath -Encoding utf8
    if ($LASTEXITCODE -ne 0) {
        $failed += 1
        "exit_code=$LASTEXITCODE" | Add-Content -LiteralPath $logPath -Encoding utf8
    }
}
"`nM05 reference retry finished: $(Get-Date -Format o); failed=$failed" |
    Add-Content -LiteralPath $logPath -Encoding utf8
exit $failed
