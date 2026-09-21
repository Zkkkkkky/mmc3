$ErrorActionPreference = "Continue"
$repoRoot = Split-Path -Parent $PSScriptRoot
$python = Join-Path $repoRoot ".venv\Scripts\python.exe"
$reporter = Join-Path $repoRoot "tools\report_golden_coverage.py"
$baseline = Join-Path $repoRoot "output\build\legacy-diff-audit\m05-reference-baseline.nes"
$logPath = Join-Path $repoRoot "output\verification\m06-spirit-failed-retry-20260920.log"
$cases = @(
    "M06-spirit-03-cold-start-01.json",
    "M06-spirit-06-cold-start-01.json",
    "M06-spirit-07-cold-start-01.json",
    "M06-spirit-10-cold-start-01.json",
    "M06-spirit-13-cold-start-01.json",
    "M06-spirit-14-cold-start-01.json",
    "M06-spirit-22-cold-start-01.json",
    "M06-spirit-23-cold-start-01.json",
    "M06-spirit-24-cold-start-01.json",
    "M06-spirit-cost-04-cold-start-01.json",
    "M06-spirit-cost-08-cold-start-01.json",
    "M06-spirit-cost-10-cold-start-01.json",
    "M06-spirit-cost-11-cold-start-01.json",
    "M06-spirit-cost-12-cold-start-01.json",
    "M06-spirit-cost-15-cold-start-01.json",
    "M06-spirit-cost-19-cold-start-01.json"
)
Set-Location -LiteralPath $repoRoot
"M06 spirit failed retry started: $(Get-Date -Format o)" | Set-Content -LiteralPath $logPath -Encoding utf8
foreach ($name in $cases) {
    $config = Join-Path $repoRoot "tools\golden_pipeline\cases\$name"
    "`n=== $name ===" | Add-Content -LiteralPath $logPath -Encoding utf8
    $tag = [IO.Path]::GetFileNameWithoutExtension($name)
    $stdout = Join-Path $repoRoot "output\verification\$tag-retry2-stdout-20260920.log"
    $stderr = Join-Path $repoRoot "output\verification\$tag-retry2-stderr-20260920.log"
    $process = Start-Process -FilePath $python -ArgumentList @($reporter, "collect", "--defer-archive", "--case-config", $config, "--baseline", $baseline) -WorkingDirectory $repoRoot -WindowStyle Hidden -RedirectStandardOutput $stdout -RedirectStandardError $stderr -PassThru
    $finished = $process.WaitForExit(60000)
    if (-not $finished) { taskkill /PID $process.Id /T /F | Out-Null; "timeout" | Add-Content -LiteralPath $logPath -Encoding utf8; continue }
    Get-Content -LiteralPath $stdout -ErrorAction SilentlyContinue | Add-Content -LiteralPath $logPath -Encoding utf8
    Get-Content -LiteralPath $stderr -ErrorAction SilentlyContinue | Add-Content -LiteralPath $logPath -Encoding utf8
    Start-Sleep -Seconds 2
}
& $python $reporter archive 2>&1 | Add-Content -LiteralPath $logPath -Encoding utf8
& $python $reporter stats 2>&1 | Add-Content -LiteralPath $logPath -Encoding utf8
"`nM06 spirit failed retry finished: $(Get-Date -Format o)" | Add-Content -LiteralPath $logPath -Encoding utf8
