$ErrorActionPreference = "Continue"
$repoRoot = Split-Path -Parent $PSScriptRoot
$python = Join-Path $repoRoot ".venv\Scripts\python.exe"
$reporter = Join-Path $repoRoot "tools\report_golden_coverage.py"
$baseline = Join-Path $repoRoot "output\build\legacy-diff-audit\m05-reference-baseline.nes"
$logPath = Join-Path $repoRoot "output\verification\m06-name-formal-20260920.log"
$cases = @(
    @{ Name = "M06-name-cold-start-01.json"; Field = "name" },
    @{ Name = "M06-battle-name-cold-start-01.json"; Field = "battle_name" }
)
Set-Location -LiteralPath $repoRoot
"M06 name formal batch started: $(Get-Date -Format o)" | Set-Content -LiteralPath $logPath -Encoding utf8
foreach ($case in $cases) {
    $config = Join-Path $repoRoot "tools\golden_pipeline\cases\$($case.Name)"
    "`n=== $($case.Name) ===" | Add-Content -LiteralPath $logPath -Encoding utf8
    $stdout = Join-Path $repoRoot "output\verification\m06-$($case.Field)-stdout-20260920.log"
    $stderr = Join-Path $repoRoot "output\verification\m06-$($case.Field)-stderr-20260920.log"
    $process = Start-Process -FilePath $python -ArgumentList @($reporter, "collect", "--case-config", $config, "--baseline", $baseline) -WorkingDirectory $repoRoot -WindowStyle Hidden -RedirectStandardOutput $stdout -RedirectStandardError $stderr -PassThru
    $finished = $process.WaitForExit(60000)
    if (-not $finished) { taskkill /PID $process.Id /T /F | Out-Null; "timeout" | Add-Content -LiteralPath $logPath -Encoding utf8; continue }
    Get-Content -LiteralPath $stdout -ErrorAction SilentlyContinue | Add-Content -LiteralPath $logPath -Encoding utf8
    Get-Content -LiteralPath $stderr -ErrorAction SilentlyContinue | Add-Content -LiteralPath $logPath -Encoding utf8
    Start-Sleep -Seconds 2
}
"`nM06 name formal batch finished: $(Get-Date -Format o)" | Add-Content -LiteralPath $logPath -Encoding utf8
