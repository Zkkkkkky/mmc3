$ErrorActionPreference = 'Stop'
$Repo = Split-Path -Parent $PSScriptRoot
$Python = Join-Path $Repo '.venv\Scripts\python.exe'

function Invoke-Watchdog {
    param(
        [Parameter(Mandatory = $true)][string]$Script,
        [string[]]$Arguments = @()
    )
    $processArgs = @(
        '-NoProfile',
        '-ExecutionPolicy', 'Bypass',
        '-File', ('"' + $Script + '"')
    ) + $Arguments
    $process = Start-Process `
        -FilePath 'powershell.exe' `
        -ArgumentList $processArgs `
        -WorkingDirectory $Repo `
        -WindowStyle Hidden `
        -Wait `
        -PassThru
    if ($process.ExitCode -ne 0) { exit $process.ExitCode }
}

$m14State = Join-Path $Repo 'output\verification\legacy-m14-all-fields-20260920\state.json'
$m14Complete = (Test-Path -LiteralPath $m14State) -and `
    ([int]((Get-Content -Raw -LiteralPath $m14State | ConvertFrom-Json).completed) -eq 3217)
if (-not $m14Complete) {
    Invoke-Watchdog -Script (Join-Path $PSScriptRoot 'run_m14_reference_watchdog.ps1')
}

Invoke-Watchdog `
    -Script (Join-Path $PSScriptRoot 'run_reference_collector_watchdog.ps1') `
    -Arguments @(
        '-CollectorName', 'collect_m03_all_reference_fields.py',
        '-OutputName', 'legacy-m03-all-fields-20260920',
        '-ExpectedTotal', '1380'
    )

Invoke-Watchdog `
    -Script (Join-Path $PSScriptRoot 'run_reference_collector_watchdog.ps1') `
    -Arguments @(
        '-CollectorName', 'collect_m04_all_reference_fields.py',
        '-OutputName', 'legacy-m04-all-fields-20260920',
        '-ExpectedTotal', '103'
    )

& $Python (Join-Path $PSScriptRoot 'report_m14_reference_save_coverage.py')
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
& $Python (Join-Path $PSScriptRoot 'report_m03_reference_save_coverage.py')
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
& $Python (Join-Path $PSScriptRoot 'report_m04_reference_save_coverage.py')
exit $LASTEXITCODE
