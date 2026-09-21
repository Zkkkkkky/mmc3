$ErrorActionPreference = "Continue"
$repoRoot = Split-Path -Parent $PSScriptRoot
$python = Join-Path $repoRoot ".venv\Scripts\python.exe"
$reporter = Join-Path $repoRoot "tools\report_golden_coverage.py"
$baseline = Join-Path $repoRoot "output\build\legacy-diff-audit\m05-reference-baseline.nes"
$logPath = Join-Path $repoRoot "output\verification\m05-weapon-batch-20260920.log"
$cases = @(
    @{ Name = "M05-weapon-1-cold-start-01.json"; Field = "weapon_1" },
    @{ Name = "M05-weapon-2-cold-start-01.json"; Field = "weapon_2" }
)
Set-Location -LiteralPath $repoRoot
"M05 weapon batch started: $(Get-Date -Format o)" | Set-Content -LiteralPath $logPath -Encoding utf8
$failed = 0
foreach ($case in $cases) {
    $config = Join-Path $repoRoot "tools\golden_pipeline\cases\$($case.Name)"
    $caseJson = Join-Path $repoRoot "output\build\legacy-diff-audit\cases\legacy_live\M05\$($case.Field)\cold_start_01\case.json"
    "`n=== $($case.Name) ===" | Add-Content -LiteralPath $logPath -Encoding utf8
    if (Test-Path -LiteralPath $caseJson) { "skip: completed live case already exists" | Add-Content -LiteralPath $logPath -Encoding utf8; continue }
    $stdout = Join-Path $repoRoot "output\verification\$($case.Field)-stdout-20260920.log"
    $stderr = Join-Path $repoRoot "output\verification\$($case.Field)-stderr-20260920.log"
    $process = Start-Process -FilePath $python -ArgumentList @($reporter, "collect", "--case-config", $config, "--baseline", $baseline) -WorkingDirectory $repoRoot -WindowStyle Hidden -RedirectStandardOutput $stdout -RedirectStandardError $stderr -PassThru
    $finished = $process.WaitForExit(60000)
    if (-not $finished) { taskkill /PID $process.Id /T /F | Out-Null; "timeout: process tree terminated after 60 seconds" | Add-Content -LiteralPath $logPath -Encoding utf8; $failed += 1; continue }
    Get-Content -LiteralPath $stdout -ErrorAction SilentlyContinue | Add-Content -LiteralPath $logPath -Encoding utf8
    Get-Content -LiteralPath $stderr -ErrorAction SilentlyContinue | Add-Content -LiteralPath $logPath -Encoding utf8
    if ($process.ExitCode -and $process.ExitCode -ne 0) { $failed += 1; "exit_code=$($process.ExitCode)" | Add-Content -LiteralPath $logPath -Encoding utf8 }
}
"`nM05 weapon batch finished: $(Get-Date -Format o); failed=$failed" | Add-Content -LiteralPath $logPath -Encoding utf8
exit $failed
