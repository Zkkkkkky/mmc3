param(
    [Parameter(Mandatory = $true)]
    [int]$PreviousWatchdogPid
)

$ErrorActionPreference = "Stop"
$repoRoot = Split-Path -Parent $PSScriptRoot
$statusPath = Join-Path $repoRoot "output\verification\legacy-m03-m04-probe-status.json"
Set-Location $repoRoot

& (Join-Path $repoRoot "tools\stop_m09_collector.ps1") -RootPid $PreviousWatchdogPid
Start-Sleep -Seconds 8

$m03 = -1
$m04 = -1
try {
    & (Join-Path $repoRoot "tools\probe_m03_reference_editor.ps1")
    $m03 = $LASTEXITCODE
    & (Join-Path $repoRoot "tools\probe_m04_reference_editor.ps1")
    $m04 = $LASTEXITCODE
}
finally {
    @{
        m03_exit_code = $m03
        m04_exit_code = $m04
        completed_at = (Get-Date -Format o)
    } | ConvertTo-Json | Set-Content -LiteralPath $statusPath -Encoding UTF8
    & (Join-Path $repoRoot "tools\run_m14_reference_watchdog.ps1")
}
