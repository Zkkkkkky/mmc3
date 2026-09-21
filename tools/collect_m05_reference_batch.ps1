$ErrorActionPreference = "Continue"

$repoRoot = Split-Path -Parent $PSScriptRoot
$python = Join-Path $repoRoot ".venv\Scripts\python.exe"
$reporter = Join-Path $repoRoot "tools\report_golden_coverage.py"
$baseline = Join-Path $repoRoot "output\build\legacy-diff-audit\cases\legacy_live\M05\movement\cold_start_01\before.nes"
$logPath = Join-Path $repoRoot "output\verification\m05-reference-batch-20260919.log"
$cases = @(
    "M05-speed-cold-start-01.json",
    "M05-strength-cold-start-01.json",
    "M05-defense-cold-start-01.json",
    "M05-money-cold-start-01.json",
    "M05-hp-cold-start-01.json",
    "M05-experience-cold-start-01.json",
    "M05-speed-growth-cold-start-01.json",
    "M05-strength-growth-cold-start-01.json",
    "M05-defense-growth-cold-start-01.json",
    "M05-hp-growth-cold-start-01.json",
    "M05-terrain-cold-start-01.json",
    "M05-transform-cold-start-01.json"
)

Set-Location -LiteralPath $repoRoot
"M05 reference batch started: $(Get-Date -Format o)" | Set-Content -LiteralPath $logPath -Encoding utf8
$failed = 0
foreach ($caseName in $cases) {
    $config = Join-Path $repoRoot "tools\golden_pipeline\cases\$caseName"
    "`n=== $caseName ===" | Add-Content -LiteralPath $logPath -Encoding utf8
    & $python $reporter collect --case-config $config --baseline $baseline --budget-seconds 90 2>&1 |
        Add-Content -LiteralPath $logPath -Encoding utf8
    if ($LASTEXITCODE -ne 0) {
        $failed += 1
        "exit_code=$LASTEXITCODE" | Add-Content -LiteralPath $logPath -Encoding utf8
    }
}
"`nM05 reference batch finished: $(Get-Date -Format o); failed=$failed" |
    Add-Content -LiteralPath $logPath -Encoding utf8
exit $failed
