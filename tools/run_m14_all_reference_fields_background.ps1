$ErrorActionPreference = "Stop"
$repoRoot = Split-Path -Parent $PSScriptRoot
$outDir = Join-Path $repoRoot "output\verification\legacy-m14-all-fields-20260920"
$stdout = Join-Path $outDir "runner.log"
$stderr = Join-Path $outDir "runner-error.log"
Set-Location -LiteralPath $repoRoot
& (Join-Path $repoRoot ".venv\Scripts\python.exe") `
  (Join-Path $repoRoot "tools\research\collect_m14_all_reference_fields.py") `
  1> $stdout 2> $stderr
$exitCode = $LASTEXITCODE
@{
  exit_code = $exitCode
  finished_at = (Get-Date -Format o)
} | ConvertTo-Json | Set-Content -LiteralPath (Join-Path $outDir "runner-result.json") -Encoding UTF8
exit $exitCode
