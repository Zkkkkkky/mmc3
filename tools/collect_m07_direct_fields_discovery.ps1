$ErrorActionPreference = "Continue"
$repoRoot = Split-Path -Parent $PSScriptRoot
$python = Join-Path $repoRoot ".venv\Scripts\python.exe"
$reporter = Join-Path $repoRoot "tools\report_golden_coverage.py"
$baseline = Join-Path $repoRoot "output\build\legacy-diff-audit\m05-reference-baseline.nes"
$logPath = Join-Path $repoRoot "output\verification\m07-direct-fields-discovery-20260920.log"
$fields = @("max-range", "hit", "distance-correction", "power-air", "power-land", "power-sea", "weapon-skill")
Set-Location -LiteralPath $repoRoot
"M07 direct-field discovery started: $(Get-Date -Format o)" | Set-Content -LiteralPath $logPath -Encoding utf8
$failed = 0
foreach ($field in $fields) {
    foreach ($round in 1, 2) {
        $caseName = "M07-$field-discovery-cold-start-0$round.json"
        $config = Join-Path $repoRoot "tools\golden_pipeline\discovery_history\$caseName"
        "`n=== $caseName ===" | Add-Content -LiteralPath $logPath -Encoding utf8
        $stdout = Join-Path $repoRoot "output\verification\m07-$field-discovery-0$round-stdout.log"
        $stderr = Join-Path $repoRoot "output\verification\m07-$field-discovery-0$round-stderr.log"
        $process = Start-Process -FilePath $python -ArgumentList @(
            $reporter, "collect", "--case-config", $config, "--baseline", $baseline
        ) -WorkingDirectory $repoRoot -WindowStyle Hidden -RedirectStandardOutput $stdout `
            -RedirectStandardError $stderr -PassThru
        $finished = $process.WaitForExit(60000)
        if (-not $finished) {
            taskkill /PID $process.Id /T /F | Out-Null
            "timeout: process tree terminated after 60 seconds" | Add-Content -LiteralPath $logPath -Encoding utf8
            $failed += 1
            continue
        }
        Get-Content -LiteralPath $stdout -ErrorAction SilentlyContinue | Add-Content -LiteralPath $logPath -Encoding utf8
        Get-Content -LiteralPath $stderr -ErrorAction SilentlyContinue | Add-Content -LiteralPath $logPath -Encoding utf8
        if ($process.ExitCode -ne 0) { $failed += 1 }
        Start-Sleep -Seconds 1
    }
}
"`nM07 direct-field discovery finished: $(Get-Date -Format o); failed=$failed" | Add-Content -LiteralPath $logPath -Encoding utf8
exit $failed
