$ErrorActionPreference = "Continue"
$repoRoot = Split-Path -Parent $PSScriptRoot
$python = Join-Path $repoRoot ".venv\Scripts\python.exe"
$reporter = Join-Path $repoRoot "tools\report_golden_coverage.py"
$baseline = Join-Path $repoRoot "output\build\legacy-diff-audit\m05-reference-baseline.nes"
$logPath = Join-Path $repoRoot "output\verification\m06-spirit-representative-formal-retry-20260920.log"
$cases = @(
    "M06-spirit-02-cold-start-01.json",
    "M06-spirit-cost-17-cold-start-01.json"
)
Set-Location -LiteralPath $repoRoot
"M06 spirit representative formal retry started: $(Get-Date -Format o)" | Set-Content -LiteralPath $logPath -Encoding utf8
foreach ($name in $cases) {
    $config = Join-Path $repoRoot "tools\golden_pipeline\cases\$name"
    "`n=== $name ===" | Add-Content -LiteralPath $logPath -Encoding utf8
    $tag = [IO.Path]::GetFileNameWithoutExtension($name)
    $stdout = Join-Path $repoRoot "output\verification\$tag-retry-stdout-20260920.log"
    $stderr = Join-Path $repoRoot "output\verification\$tag-retry-stderr-20260920.log"
    $process = Start-Process -FilePath $python -ArgumentList @($reporter, "collect", "--defer-archive", "--case-config", $config, "--baseline", $baseline) -WorkingDirectory $repoRoot -WindowStyle Hidden -RedirectStandardOutput $stdout -RedirectStandardError $stderr -PassThru
    $finished = $process.WaitForExit(60000)
    if (-not $finished) { taskkill /PID $process.Id /T /F | Out-Null; "timeout" | Add-Content -LiteralPath $logPath -Encoding utf8; continue }
    Get-Content -LiteralPath $stdout -ErrorAction SilentlyContinue | Add-Content -LiteralPath $logPath -Encoding utf8
    Get-Content -LiteralPath $stderr -ErrorAction SilentlyContinue | Add-Content -LiteralPath $logPath -Encoding utf8
    Start-Sleep -Seconds 2
}
& $python $reporter archive 2>&1 | Add-Content -LiteralPath $logPath -Encoding utf8
& $python $reporter stats 2>&1 | Add-Content -LiteralPath $logPath -Encoding utf8
"`nM06 spirit representative formal retry finished: $(Get-Date -Format o)" | Add-Content -LiteralPath $logPath -Encoding utf8
