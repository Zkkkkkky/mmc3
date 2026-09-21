$ErrorActionPreference = "Continue"

$repoRoot = Split-Path -Parent $PSScriptRoot
$python = Join-Path $repoRoot ".venv\Scripts\python.exe"
$reporter = Join-Path $repoRoot "tools\report_golden_coverage.py"
$baseline = Join-Path $repoRoot "output\build\legacy-diff-audit\m05-reference-baseline.nes"
$logPath = Join-Path $repoRoot "output\verification\m06-numeric-formal-20260920.log"
$cases = @(
    @{ Name = "M06-growth-fixed-cold-start-01.json"; Field = "growth_fixed" },
    @{ Name = "M06-strength-bonus-cold-start-01.json"; Field = "strength_bonus" },
    @{ Name = "M06-mobility-bonus-cold-start-01.json"; Field = "mobility_bonus" },
    @{ Name = "M06-defense-bonus-cold-start-01.json"; Field = "defense_bonus" },
    @{ Name = "M06-hp-bonus-cold-start-01.json"; Field = "hp_bonus" },
    @{ Name = "M06-speed-bonus-cold-start-01.json"; Field = "speed_bonus" }
)

Set-Location -LiteralPath $repoRoot
"M06 numeric formal batch started: $(Get-Date -Format o)" |
    Set-Content -LiteralPath $logPath -Encoding utf8
$failed = 0
foreach ($case in $cases) {
    $caseName = $case.Name
    $field = $case.Field
    $config = Join-Path $repoRoot "tools\golden_pipeline\cases\$caseName"
    $caseJson = Join-Path $repoRoot "output\build\legacy-diff-audit\cases\legacy_live\M06\$field\cold_start_01\case.json"
    "`n=== $caseName ===" | Add-Content -LiteralPath $logPath -Encoding utf8
    if (Test-Path -LiteralPath $caseJson) {
        "skip: completed live case already exists" |
            Add-Content -LiteralPath $logPath -Encoding utf8
        continue
    }
    $stdout = Join-Path $repoRoot "output\verification\m06-$field-stdout-20260920.log"
    $stderr = Join-Path $repoRoot "output\verification\m06-$field-stderr-20260920.log"
    $process = Start-Process -FilePath $python -ArgumentList @(
        $reporter, "collect", "--case-config", $config, "--baseline", $baseline
    ) -WorkingDirectory $repoRoot -WindowStyle Hidden -RedirectStandardOutput $stdout `
        -RedirectStandardError $stderr -PassThru
    $finished = $process.WaitForExit(60000)
    if (-not $finished) {
        taskkill /PID $process.Id /T /F | Out-Null
        "timeout: process tree terminated after 60 seconds" |
            Add-Content -LiteralPath $logPath -Encoding utf8
        $failed += 1
        continue
    }
    Get-Content -LiteralPath $stdout -ErrorAction SilentlyContinue |
        Add-Content -LiteralPath $logPath -Encoding utf8
    Get-Content -LiteralPath $stderr -ErrorAction SilentlyContinue |
        Add-Content -LiteralPath $logPath -Encoding utf8
    if (-not (Test-Path -LiteralPath $caseJson)) {
        $failed += 1
        "case.json missing after collector exit" |
            Add-Content -LiteralPath $logPath -Encoding utf8
    }
    Start-Sleep -Seconds 2
}
"`nM06 numeric formal batch finished: $(Get-Date -Format o); failed=$failed" |
    Add-Content -LiteralPath $logPath -Encoding utf8
exit $failed
