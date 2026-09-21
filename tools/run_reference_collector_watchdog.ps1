param(
    [Parameter(Mandatory = $true)]
    [string]$CollectorName,
    [Parameter(Mandatory = $true)]
    [string]$OutputName,
    [Parameter(Mandatory = $true)]
    [int]$ExpectedTotal
)

$ErrorActionPreference = 'Stop'
$Repo = Split-Path -Parent $PSScriptRoot
$Python = Join-Path $Repo '.venv\Scripts\python.exe'
$Collector = Join-Path $PSScriptRoot ("research\" + $CollectorName)
$Out = Join-Path $Repo ("output\verification\" + $OutputName)
$State = Join-Path $Out 'state.json'
$Progress = Join-Path $Out 'progress.log'
$Watchdog = Join-Path $Out 'watchdog.json'
$Summary = Join-Path $Out 'summary.json'
$Restarts = 0

if (-not (Test-Path -LiteralPath $Collector -PathType Leaf)) {
    throw "Collector not found: $Collector"
}

function Read-Completed {
    if (-not (Test-Path -LiteralPath $State)) { return 0 }
    try { return [int]((Get-Content -Raw -LiteralPath $State | ConvertFrom-Json).completed) }
    catch { return 0 }
}

function Latest-Activity {
    $Times = @()
    foreach ($Path in @($State, $Progress)) {
        $Item = Get-Item -LiteralPath $Path -ErrorAction SilentlyContinue
        if ($null -ne $Item) { $Times += $Item.LastWriteTimeUtc }
    }
    if ($Times.Count -eq 0) { return [DateTime]::UtcNow }
    return ($Times | Sort-Object -Descending | Select-Object -First 1)
}

function Read-SummaryPassed {
    if (-not (Test-Path -LiteralPath $Summary)) { return $false }
    try { return [bool]((Get-Content -Raw -LiteralPath $Summary | ConvertFrom-Json).passed) }
    catch { return $false }
}

function Write-WatchdogState {
    param([Parameter(Mandatory = $true)][hashtable]$Payload)
    $Temporary = $Watchdog + '.tmp'
    $Payload | ConvertTo-Json | Set-Content -LiteralPath $Temporary -Encoding UTF8
    Move-Item -LiteralPath $Temporary -Destination $Watchdog -Force
}

while ($true) {
    $Before = Read-Completed
    $AttemptStamp = Get-Date -Format 'yyyyMMddTHHmmssfff'
    $AttemptStdout = Join-Path $Out ("watchdog-attempt-$AttemptStamp.stdout.log")
    $AttemptStderr = Join-Path $Out ("watchdog-attempt-$AttemptStamp.stderr.log")
    $Child = Start-Process -FilePath $Python -ArgumentList @($Collector) `
        -WorkingDirectory $Repo -PassThru -WindowStyle Hidden `
        -RedirectStandardOutput $AttemptStdout -RedirectStandardError $AttemptStderr
    # A restarted collector needs a full startup window even when the last
    # persisted progress timestamp is old.  Otherwise the first ten-second
    # poll can immediately classify the fresh child as stalled.
    $LastActivity = [DateTime]::UtcNow
    # Once every field is recorded, collectors may spend over a minute
    # launching the first clean reference process before the inventory loop
    # can append its first progress line.  Give that bounded finalization
    # phase a wider startup window; normal field collection keeps the tighter
    # one-minute stall detection.
    $StallSeconds = if ($Before -eq $ExpectedTotal) { 240 } else { 60 }
    $RestartRequested = $false
    Write-WatchdogState @{
        status = 'running'; collector_pid = $Child.Id; completed = $Before
        restarts = $Restarts; updated_at = (Get-Date -Format o)
    }

    while (-not $Child.HasExited) {
        Start-Sleep -Seconds 10
        $Child.Refresh()
        $Activity = Latest-Activity
        if ($Activity -gt $LastActivity) { $LastActivity = $Activity }
        if (([DateTime]::UtcNow - $LastActivity).TotalSeconds -ge $StallSeconds) {
            & (Join-Path $PSScriptRoot 'stop_m09_collector.ps1') -RootPid $Child.Id
            $Restarts += 1
            Write-WatchdogState @{
                status = 'restarting_after_stall'; collector_pid = $Child.Id
                completed = (Read-Completed); restarts = $Restarts
                updated_at = (Get-Date -Format o)
            }
            $RestartRequested = $true
            Start-Sleep -Seconds 8
            break
        }
    }

    if ($RestartRequested) { continue }
    # With redirected stdout/stderr, PowerShell can expose HasExited before
    # the managed Process object has populated ExitCode.  WaitForExit is
    # immediate here and also flushes the redirected streams.
    $Child.WaitForExit()
    $Child.Refresh()
    if (-not $Child.HasExited) { continue }
    $Completed = Read-Completed
    $CollectorSucceeded = ($Child.ExitCode -eq 0) -or (Read-SummaryPassed)
    if ($CollectorSucceeded -and $Completed -eq $ExpectedTotal) {
        Write-WatchdogState @{
            status = 'complete'; exit_code = $Child.ExitCode; completed = $Completed
            restarts = $Restarts; updated_at = (Get-Date -Format o)
        }
        exit 0
    }
    $Restarts += 1
    $CollectorError = Join-Path $Out 'error.log'
    if (Test-Path -LiteralPath $CollectorError) {
        Copy-Item -LiteralPath $CollectorError `
            -Destination (Join-Path $Out ("watchdog-attempt-$AttemptStamp.error.log")) `
            -Force
    }
    Write-WatchdogState @{
        status = 'restarting_after_exit'; exit_code = $Child.ExitCode
        completed = $Completed; restarts = $Restarts; updated_at = (Get-Date -Format o)
    }
    Start-Sleep -Seconds 8
}
