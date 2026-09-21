param(
    [Parameter(Mandatory = $true)]
    [string]$ScriptName,
    [int]$PreviousWatchdogPid = 0
)

$ErrorActionPreference = 'Stop'
$Repo = Split-Path -Parent $PSScriptRoot
$Python = Join-Path $Repo '.venv\Scripts\python.exe'
$Research = [System.IO.Path]::GetFullPath((Join-Path $PSScriptRoot 'research'))
$Script = [System.IO.Path]::GetFullPath((Join-Path $Research $ScriptName))
if (-not $Script.StartsWith($Research + [System.IO.Path]::DirectorySeparatorChar)) {
    throw 'Script must stay inside tools/research.'
}
if (-not (Test-Path -LiteralPath $Script -PathType Leaf) -or [System.IO.Path]::GetExtension($Script) -ne '.py') {
    throw "Invalid research script: $ScriptName"
}

$ExitCode = 1
try {
    if ($PreviousWatchdogPid -gt 0) {
        & (Join-Path $PSScriptRoot 'stop_m09_collector.ps1') -RootPid $PreviousWatchdogPid
        Start-Sleep -Seconds 5
    }
    & $Python $Script
    $ExitCode = $LASTEXITCODE
}
finally {
    & (Join-Path $PSScriptRoot 'run_m14_reference_watchdog.ps1')
}

exit $ExitCode
