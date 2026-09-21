$ErrorActionPreference = "Continue"
$repoRoot = Split-Path -Parent $PSScriptRoot
$python = Join-Path $repoRoot ".venv\Scripts\python.exe"
$reporter = Join-Path $repoRoot "tools\report_golden_coverage.py"
$baseline = Join-Path $repoRoot "output\build\legacy-diff-audit\m05-reference-baseline.nes"
$logPath = Join-Path $repoRoot "output\verification\m05-icon-captain-discovery-20260920.log"
$cases = @(
    @{Name="M05-icon-index-discovery-cold-start-01.json";Field="icon_index"},
    @{Name="M05-icon-bank-discovery-cold-start-01.json";Field="icon_bank"},
    @{Name="M05-captain-discovery-cold-start-01.json";Field="captain"}
)
Set-Location -LiteralPath $repoRoot
"M05 icon/captain discovery started: $(Get-Date -Format o)" | Set-Content -LiteralPath $logPath -Encoding utf8
foreach ($case in $cases) {
    $config = Join-Path $repoRoot "tools\golden_pipeline\cases\$($case.Name)"
    "`n=== $($case.Name) ===" | Add-Content -LiteralPath $logPath -Encoding utf8
    $stdout = Join-Path $repoRoot "output\verification\$($case.Field)-discovery-stdout-20260920.log"
    $stderr = Join-Path $repoRoot "output\verification\$($case.Field)-discovery-stderr-20260920.log"
    $process = Start-Process -FilePath $python -ArgumentList @($reporter,"collect","--case-config",$config,"--baseline",$baseline) -WorkingDirectory $repoRoot -WindowStyle Hidden -RedirectStandardOutput $stdout -RedirectStandardError $stderr -PassThru
    if (-not $process.WaitForExit(60000)) { taskkill /PID $process.Id /T /F | Out-Null; "timeout" | Add-Content -LiteralPath $logPath -Encoding utf8; continue }
    Get-Content -LiteralPath $stdout -ErrorAction SilentlyContinue | Add-Content -LiteralPath $logPath -Encoding utf8
    Get-Content -LiteralPath $stderr -ErrorAction SilentlyContinue | Add-Content -LiteralPath $logPath -Encoding utf8
}
"`nM05 icon/captain discovery finished: $(Get-Date -Format o)" | Add-Content -LiteralPath $logPath -Encoding utf8
