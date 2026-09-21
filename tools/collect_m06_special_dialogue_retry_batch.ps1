$ErrorActionPreference = "Continue"
$repoRoot = Split-Path -Parent $PSScriptRoot
$python = Join-Path $repoRoot ".venv\Scripts\python.exe"
$reporter = Join-Path $repoRoot "tools\report_golden_coverage.py"
$baseline = Join-Path $repoRoot "output\build\legacy-diff-audit\m05-reference-baseline.nes"
$logPath = Join-Path $repoRoot "output\verification\m06-special-dialogue-retry-batch-20260920.log"
$configs = Get-ChildItem -LiteralPath (Join-Path $repoRoot "tools\golden_pipeline\cases") -Filter "M06-dialogue-special-attack-*-cold-start-01.json" |
  Where-Object { $_.Name -match "attack-[23]-" } |
  Sort-Object Name
Set-Location -LiteralPath $repoRoot
"M06 special dialogue retry: $($configs.Count) cases" | Set-Content -LiteralPath $logPath -Encoding utf8
foreach ($config in $configs) {
  Start-Sleep -Seconds 5
  & $python $reporter collect --case-config $config.FullName --baseline $baseline --defer-archive *>> $logPath
  "completed=$($config.Name) exit=$LASTEXITCODE" | Add-Content -LiteralPath $logPath -Encoding utf8
}
& $python $reporter archive *>> $logPath
& $python $reporter stats *>> $logPath
