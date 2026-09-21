$ErrorActionPreference = "Continue"
$repoRoot = Split-Path -Parent $PSScriptRoot
$python = Join-Path $repoRoot ".venv\Scripts\python.exe"
$reporter = Join-Path $repoRoot "tools\report_golden_coverage.py"
$baseline = Join-Path $repoRoot "output\build\legacy-diff-audit\m05-reference-baseline.nes"
$config = Join-Path $repoRoot "tools\golden_pipeline\cases\M06-dialogue-attack-hit-number-cold-start-01.json"
$logPath = Join-Path $repoRoot "output\verification\m06-dialogue-attack-hit-formal-20260920.log"
$stdout = Join-Path $repoRoot "output\verification\m06-dialogue-attack-hit-formal-stdout-20260920.log"
$stderr = Join-Path $repoRoot "output\verification\m06-dialogue-attack-hit-formal-stderr-20260920.log"
Set-Location -LiteralPath $repoRoot
Start-Sleep -Seconds 20
$process = Start-Process -FilePath $python -ArgumentList @($reporter, "collect", "--case-config", $config, "--baseline", $baseline) -WorkingDirectory $repoRoot -WindowStyle Hidden -RedirectStandardOutput $stdout -RedirectStandardError $stderr -PassThru
$finished = $process.WaitForExit(60000)
if (-not $finished) { taskkill /PID $process.Id /T /F | Out-Null; "timeout" | Set-Content -LiteralPath $logPath -Encoding utf8; exit 1 }
Get-Content -LiteralPath $stdout -ErrorAction SilentlyContinue | Set-Content -LiteralPath $logPath -Encoding utf8
Get-Content -LiteralPath $stderr -ErrorAction SilentlyContinue | Add-Content -LiteralPath $logPath -Encoding utf8
