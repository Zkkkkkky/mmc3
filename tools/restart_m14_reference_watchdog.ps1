param(
    [Parameter(Mandatory = $true)]
    [int]$PreviousWatchdogPid
)

$ErrorActionPreference = "Stop"
$repoRoot = Split-Path -Parent $PSScriptRoot
& (Join-Path $repoRoot "tools\stop_m09_collector.ps1") -RootPid $PreviousWatchdogPid
Start-Sleep -Seconds 8
& (Join-Path $repoRoot "tools\run_m14_reference_watchdog.ps1")
