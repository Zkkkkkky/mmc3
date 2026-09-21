$ErrorActionPreference = "Continue"
$repoRoot = Split-Path -Parent $PSScriptRoot
$python = Join-Path $repoRoot ".venv\Scripts\python.exe"
$reporter = Join-Path $repoRoot "tools\report_golden_coverage.py"
$baseline = Join-Path $repoRoot "output\build\legacy-diff-audit\m05-reference-baseline.nes"
$logPath = Join-Path $repoRoot "output\verification\m08-representative-discovery-20260920.log"
$cases = @(
  "M08-battle-00-row000-variant000-cold-start-01.json",
  "M08-battle-01-row000-variant000-discovery-cold-start-01.json",
  "M08-battle-01-row000-variant000-discovery-cold-start-02.json",
  "M08-battle-04-row000-variant001-discovery-cold-start-01.json",
  "M08-battle-04-row000-variant001-discovery-cold-start-02.json",
  "M08-battle-05-row001-variant000-discovery-cold-start-01.json",
  "M08-battle-05-row001-variant000-discovery-cold-start-02.json",
  "M08-battle-07-alias-row000-variant000-discovery-cold-start-01.json",
  "M08-battle-07-alias-row000-variant000-discovery-cold-start-02.json"
)
Set-Location -LiteralPath $repoRoot
"M08 representative collection started: $(Get-Date -Format o)" | Set-Content $logPath
$failed = 0
foreach($caseName in $cases) {
  $folder = if($caseName -like "*-discovery-*") { "discovery_history" } else { "cases" }
  $config = Join-Path $repoRoot "tools\golden_pipeline\$folder\$caseName"
  "`n=== $caseName ===" | Add-Content $logPath
  $safe = [IO.Path]::GetFileNameWithoutExtension($caseName)
  $stdout = Join-Path $repoRoot "output\verification\$safe-stdout.log"
  $stderr = Join-Path $repoRoot "output\verification\$safe-stderr.log"
  $p=Start-Process $python -ArgumentList @($reporter,"collect","--case-config",$config,"--baseline",$baseline,"--defer-archive") -WorkingDirectory $repoRoot -WindowStyle Hidden -RedirectStandardOutput $stdout -RedirectStandardError $stderr -PassThru
  $finished=$p.WaitForExit(60000)
  if(-not $finished){taskkill /PID $p.Id /T /F | Out-Null; $failed+=1; continue}
  Get-Content $stdout -ErrorAction SilentlyContinue | Add-Content $logPath
  Get-Content $stderr -ErrorAction SilentlyContinue | Add-Content $logPath
  if($p.ExitCode -ne 0){$failed+=1}
  Start-Sleep -Seconds 1
}
& $python $reporter archive | Add-Content $logPath
& $python $reporter stats | Add-Content $logPath
"M08 representative collection finished: $(Get-Date -Format o); failed=$failed" | Add-Content $logPath
exit $failed
