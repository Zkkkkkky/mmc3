$ErrorActionPreference = "Stop"
$repoRoot = Split-Path -Parent $PSScriptRoot
$python = Join-Path $repoRoot ".venv\Scripts\python.exe"
$script = Join-Path $repoRoot "tools\research\probe_m14_reference_catalog.py"
$statusPath = Join-Path $repoRoot "output\verification\legacy-m14-reference-catalog-20260920\elevation.txt"
$statusDir = Split-Path -Parent $statusPath
New-Item -ItemType Directory -Path $statusDir -Force | Out-Null
$principal = New-Object Security.Principal.WindowsPrincipal([Security.Principal.WindowsIdentity]::GetCurrent())
$isAdmin = $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
"admin=$isAdmin pid=$PID executable=$((Get-Process -Id $PID).Path)" | Set-Content -LiteralPath $statusPath -Encoding UTF8
& $python $script
exit $LASTEXITCODE
