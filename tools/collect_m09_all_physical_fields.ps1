param(
  [int]$Limit = 0,
  [switch]$Restart,
  [int]$Rewind = -1
)
$ErrorActionPreference = "Stop"
$repoRoot = Split-Path -Parent $PSScriptRoot
$python = Join-Path $repoRoot ".venv\Scripts\python.exe"
$script = Join-Path $repoRoot "tools\research\collect_m09_all_physical_fields.py"
$arguments = @($script)
if ($Limit -gt 0) { $arguments += @("--limit", "$Limit") }
if ($Restart) { $arguments += "--restart" }
if ($Rewind -ge 0) { $arguments += @("--rewind", "$Rewind") }
& $python @arguments
exit $LASTEXITCODE
