$ErrorActionPreference = "Continue"
$repoRoot = Split-Path -Parent $PSScriptRoot
$python = Join-Path $repoRoot ".venv\Scripts\python.exe"
$probe = Join-Path $repoRoot "tools\research\probe_m06_dialogue_button.py"
$stdout = Join-Path $repoRoot "output\verification\m06-dialogue-probe-stdout-20260920.log"
$stderr = Join-Path $repoRoot "output\verification\m06-dialogue-probe-stderr-20260920.log"
Set-Location -LiteralPath $repoRoot
$process = Start-Process -FilePath $python -ArgumentList @($probe) -WorkingDirectory $repoRoot -WindowStyle Hidden -RedirectStandardOutput $stdout -RedirectStandardError $stderr -PassThru
$finished = $process.WaitForExit(60000)
if (-not $finished) { taskkill /PID $process.Id /T /F | Out-Null; exit 1 }
