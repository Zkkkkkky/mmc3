$ErrorActionPreference = "Continue"
$repoRoot = Split-Path -Parent $PSScriptRoot
$python = Join-Path $repoRoot ".venv\Scripts\python.exe"
$reporter = Join-Path $repoRoot "tools\report_golden_coverage.py"
$baseline = Join-Path $repoRoot "output\build\legacy-diff-audit\m05-reference-baseline.nes"
$logPath = Join-Path $repoRoot "output\verification\m07-direct-fields-formal-20260920.log"
$cases = @("M07-max-range-cold-start-01.json", "M07-hit-cold-start-01.json", "M07-distance-correction-cold-start-01.json", "M07-power-air-cold-start-01.json", "M07-power-land-cold-start-01.json", "M07-power-sea-cold-start-01.json", "M07-weapon-skill-cold-start-01.json")
Set-Location -LiteralPath $repoRoot
"M07 direct-field formal batch started: $(Get-Date -Format o)" | Set-Content -LiteralPath $logPath -Encoding utf8
$failed = 0
foreach ($caseName in $cases) {
    "`n=== $caseName ===" | Add-Content -LiteralPath $logPath -Encoding utf8
    $config = Join-Path $repoRoot "tools\golden_pipeline\cases\$caseName"
    $stdout = Join-Path $repoRoot "output\verification\$($caseName.Replace('.json',''))-stdout.log"
    $stderr = Join-Path $repoRoot "output\verification\$($caseName.Replace('.json',''))-stderr.log"
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
"`nM07 direct-field formal batch finished: $(Get-Date -Format o); failed=$failed" | Add-Content -LiteralPath $logPath -Encoding utf8
exit $failed
