param(
    [int]$PreviousWatchdogPid = 0
)

$ErrorActionPreference = 'Stop'
$Repo = Split-Path -Parent $PSScriptRoot
$Python = Join-Path $Repo '.venv\Scripts\python.exe'
$Status = Join-Path $Repo 'output\verification\legacy-m03-m04-existing-probe-status.json'

try {
    if ($PreviousWatchdogPid -gt 0) {
        & (Join-Path $PSScriptRoot 'stop_m09_collector.ps1') -RootPid $PreviousWatchdogPid
    }
    & $Python (Join-Path $PSScriptRoot 'research\probe_m03_m04_existing_records.py')
    $ProbeExit = $LASTEXITCODE
    @{ completed_at = (Get-Date).ToString('o'); exit_code = $ProbeExit } |
        ConvertTo-Json | Set-Content -LiteralPath $Status -Encoding UTF8
}
finally {
    & (Join-Path $PSScriptRoot 'run_m14_reference_watchdog.ps1')
}

exit $ProbeExit
