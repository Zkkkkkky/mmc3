$ErrorActionPreference = "Stop"
$repoRoot = Split-Path -Parent $PSScriptRoot
$python = Join-Path $repoRoot ".venv\Scripts\python.exe"
$collector = Join-Path $repoRoot "tools\research\collect_m14_all_reference_fields.py"
$outDir = Join-Path $repoRoot "output\verification\legacy-m14-all-fields-20260920"
$statePath = Join-Path $outDir "state.json"
$progressPath = Join-Path $outDir "progress.log"
$watchdogPath = Join-Path $outDir "watchdog.json"
$restartCount = 0

function Read-Completed {
    if (-not (Test-Path -LiteralPath $statePath)) { return 0 }
    try { return [int]((Get-Content -Raw -LiteralPath $statePath | ConvertFrom-Json).completed) }
    catch { return 0 }
}

function Latest-Activity {
    $times = @()
    foreach ($path in @($statePath, $progressPath)) {
        $item = Get-Item -LiteralPath $path -ErrorAction SilentlyContinue
        if ($null -ne $item) { $times += $item.LastWriteTimeUtc }
    }
    if ($times.Count -eq 0) { return [DateTime]::UtcNow }
    return ($times | Sort-Object -Descending | Select-Object -First 1)
}

function Write-WatchdogState {
    param([Parameter(Mandatory = $true)][hashtable]$Payload)
    $temporary = $watchdogPath + ".tmp"
    $Payload | ConvertTo-Json | Set-Content -LiteralPath $temporary -Encoding UTF8
    Move-Item -LiteralPath $temporary -Destination $watchdogPath -Force
}

while ($true) {
    $before = Read-Completed
    $child = Start-Process -FilePath $python -ArgumentList @($collector) -WorkingDirectory $repoRoot -PassThru -WindowStyle Hidden
    $lastActivity = Latest-Activity
    $restartRequested = $false
    Write-WatchdogState @{
        status = "running"
        collector_pid = $child.Id
        completed = $before
        restarts = $restartCount
        updated_at = (Get-Date -Format o)
    }

    while (-not $child.HasExited) {
        Start-Sleep -Seconds 10
        $child.Refresh()
        $activity = Latest-Activity
        if ($activity -gt $lastActivity) { $lastActivity = $activity }
        if (([DateTime]::UtcNow - $lastActivity).TotalSeconds -ge 45) {
            & (Join-Path $repoRoot "tools\stop_m09_collector.ps1") -RootPid $child.Id
            $restartCount += 1
            Write-WatchdogState @{
                status = "restarting_after_stall"
                collector_pid = $child.Id
                completed = (Read-Completed)
                restarts = $restartCount
                updated_at = (Get-Date -Format o)
            }
            $restartRequested = $true
            Start-Sleep -Seconds 8
            break
        }
    }

    if ($restartRequested) { continue }
    $child.Refresh()
    if (-not $child.HasExited) { continue }
    $completed = Read-Completed
    if ($child.ExitCode -eq 0 -and $completed -eq 3217) {
        Write-WatchdogState @{
            status = "complete"
            exit_code = $child.ExitCode
            completed = $completed
            restarts = $restartCount
            updated_at = (Get-Date -Format o)
        }
        exit 0
    }
    $restartCount += 1
    Write-WatchdogState @{
        status = "restarting_after_exit"
        exit_code = $child.ExitCode
        completed = $completed
        restarts = $restartCount
        updated_at = (Get-Date -Format o)
    }
    Start-Sleep -Seconds 8
}
