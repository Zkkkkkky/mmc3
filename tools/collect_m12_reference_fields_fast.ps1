param([int]$Limit = 0, [switch]$Restart)
$ErrorActionPreference = "Stop"
$repoRoot = Split-Path -Parent $PSScriptRoot
$arguments = @((Join-Path $repoRoot "tools\research\collect_m12_reference_fields_fast.py"))
if ($Limit -gt 0) { $arguments += @("--limit", "$Limit") }
if ($Restart) { $arguments += "--restart" }
& (Join-Path $repoRoot ".venv\Scripts\python.exe") @arguments
exit $LASTEXITCODE
