$ErrorActionPreference = "Continue"
$repoRoot = Split-Path -Parent $PSScriptRoot
$python = Join-Path $repoRoot ".venv\Scripts\python.exe"
$reporter = Join-Path $repoRoot "tools\report_golden_coverage.py"
$baseline = Join-Path $repoRoot "output\build\legacy-diff-audit\m05-reference-baseline.nes"
$configRoot = Join-Path $repoRoot "tools\golden_pipeline\cases"
$logPath = Join-Path $repoRoot "output\verification\m06-portrait-upload-formal-20260920.log"
Set-Location -LiteralPath $repoRoot
Start-Sleep -Seconds 5
foreach ($name in @("M06-portrait-front-upload-cold-start-01.json","M06-portrait-back-upload-cold-start-01.json")) {
    & $python $reporter collect --case-config (Join-Path $configRoot $name) --baseline $baseline --defer-archive *>> $logPath
    Start-Sleep -Seconds 5
}
& $python $reporter archive *>> $logPath
& $python $reporter stats *>> $logPath
exit 0
