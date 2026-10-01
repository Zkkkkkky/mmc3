param(
    [Parameter(Mandatory = $true)]
    [ValidateRange(1, 255)]
    [int]$WeaponRecord,

    [Parameter(Mandatory = $true)]
    [ValidateRange(0, 199)]
    [int]$InstructionRow,

    [ValidateSet('ally', 'enemy')]
    [string]$AnimationKind = 'ally',

    [switch]$ExpectNoop,

    [ValidateSet('left', 'keyboard', 'right')]
    [string]$Action = 'left',

    [Parameter(Mandatory = $true)]
    [ValidatePattern('^[a-z0-9][a-z0-9-]{0,40}$')]
    [string]$Tag
)

$ErrorActionPreference = "Stop"
$repoRoot = Split-Path -Parent $PSScriptRoot
$python = Join-Path $repoRoot ".venv\Scripts\python.exe"
$probe = Join-Path $repoRoot "tools\research\legacy_ui_probe.py"
$sourceRom = Join-Path $repoRoot "output\rom\DC_kuorong_464K.nes"
$probeDir = Join-Path $repoRoot "output\build\legacy-ui-probe"
$probeRom = Join-Path $probeDir ("weapon-command-ff-{0}-w{1}-r{2}.nes" -f $AnimationKind, $WeaponRecord, $InstructionRow)
$logPath = Join-Path $repoRoot ("output\verification\legacy-ui-probe-{0}.log" -f $Tag)
$evidenceDir = Join-Path $repoRoot ("output\verification\legacy-ui-probe-{0}" -f $Tag)

New-Item -ItemType Directory -Force -Path $probeDir | Out-Null
Copy-Item -LiteralPath $sourceRom -Destination $probeRom -Force
if (Test-Path -LiteralPath $evidenceDir) {
    $resolvedEvidence = (Resolve-Path -LiteralPath $evidenceDir).Path
    $resolvedVerification = (
        Resolve-Path -LiteralPath (Join-Path $repoRoot "output\verification")
    ).Path
    if (-not $resolvedEvidence.StartsWith(
        $resolvedVerification + [IO.Path]::DirectorySeparatorChar
    )) {
        throw "Refusing to clean evidence outside output verification: $resolvedEvidence"
    }
    Remove-Item -LiteralPath $resolvedEvidence -Recurse -Force
}

Set-Location -LiteralPath $repoRoot
$probeArgs = @(
    '--stage', 'A,LOAD,DBSAVEFF',
    '--rom', $probeRom,
    '--db-weapon-record', $WeaponRecord,
    '--db-instruction-row', $InstructionRow,
    '--db-animation-kind', $AnimationKind,
    '--db-ff-action', $Action,
    '--evidence-tag', $Tag
)
if ($ExpectNoop) {
    $probeArgs += '--db-ff-expect-noop'
}
& $python $probe @probeArgs 2>&1 |
    Set-Content -LiteralPath $logPath -Encoding utf8
exit $LASTEXITCODE
