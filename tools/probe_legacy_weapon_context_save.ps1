param(
    [Parameter(Mandatory = $true)]
    [ValidateSet('cut', 'paste', 'paste-all', 'delete', 'clear')]
    [string]$Case,

    [Parameter(Mandatory = $true)]
    [ValidatePattern('^[a-z0-9][a-z0-9-]{0,40}$')]
    [string]$Tag,

    [ValidateSet('ally', 'enemy')]
    [string]$Kind = 'ally',

    [ValidateRange(1, 255)]
    [int]$WeaponRecord = 1,

    [ValidateRange(0, 199)]
    [int]$InstructionRow = 0
)

$ErrorActionPreference = "Stop"
$repoRoot = Split-Path -Parent $PSScriptRoot
$python = Join-Path $repoRoot ".venv\Scripts\python.exe"
$probe = Join-Path $repoRoot "tools\research\legacy_ui_probe.py"
$sourceRom = Join-Path $repoRoot "output\rom\DC_kuorong_464K.nes"
$probeDir = Join-Path $repoRoot "output\build\legacy-ui-probe"
$probeRom = Join-Path $probeDir ("weapon-context-{0}-save.nes" -f $Tag)
$logPath = Join-Path $repoRoot ("output\verification\legacy-ui-probe-{0}.log" -f $Tag)
$evidenceDir = Join-Path $repoRoot ("output\verification\legacy-ui-probe-{0}" -f $Tag)

New-Item -ItemType Directory -Force -Path $probeDir | Out-Null
Copy-Item -LiteralPath $sourceRom -Destination $probeRom -Force
if (Test-Path -LiteralPath $evidenceDir) {
    $resolvedEvidence = (Resolve-Path -LiteralPath $evidenceDir).Path
    $verificationRoot = (Resolve-Path -LiteralPath (
        Join-Path $repoRoot "output\verification"
    )).Path
    if (-not $resolvedEvidence.StartsWith(
        $verificationRoot + [IO.Path]::DirectorySeparatorChar
    )) {
        throw "Refusing to clean evidence outside output verification: $resolvedEvidence"
    }
    Remove-Item -LiteralPath $resolvedEvidence -Recurse -Force
}

Set-Location -LiteralPath $repoRoot
& $python $probe `
    --stage A,LOAD,DBCONTEXTSAVE `
    --rom $probeRom `
    --db-context-case $Case `
    --db-animation-kind $Kind `
    --db-weapon-record $WeaponRecord `
    --db-instruction-row $InstructionRow `
    --evidence-tag $Tag 2>&1 |
    Set-Content -LiteralPath $logPath -Encoding utf8
exit $LASTEXITCODE
