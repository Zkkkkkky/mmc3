param(
    [ValidateSet(
        "beam-xy",
        "beam-code",
        "movement1-code",
        "movement1-increment",
        "movement2-code",
        "movement2-increment",
        "picture-xy",
        "picture-code",
        "beam-puzzle-replace",
        "beam-puzzle-noop",
        "beam-puzzle-delete",
        "picture-puzzle-move",
        "picture-puzzle-flip",
        "picture-puzzle-hflip",
        "picture-puzzle-vflip"
    )]
    [string]$Case = "beam-xy",
    [int]$Value = 18,
    [int]$Value2 = 7,
    [int]$Record = 0,
    [ValidateSet("same", "longer", "shorter")]
    [string]$CodeVariant = "same",
    [ValidateSet(40, 80)]
    [int]$PuzzleStart = 80,
    [ValidateRange(1, 99)]
    [int]$LibraryX = 50,
    [ValidateRange(1, 99)]
    [int]$LibraryY = 50,
    [ValidateRange(1, 99)]
    [int]$EffectX = 50,
    [ValidateRange(1, 99)]
    [int]$EffectY = 50,
    [ValidatePattern('^$|^[a-z0-9][a-z0-9-]{0,40}$')]
    [string]$EvidenceTag = "",
    [switch]$ExpectNoop
)

$ErrorActionPreference = "Stop"

$repoRoot = Split-Path -Parent $PSScriptRoot
$python = Join-Path $repoRoot ".venv\Scripts\python.exe"
$probe = Join-Path $repoRoot "tools\research\legacy_ui_probe.py"
$sourceRom = Join-Path $repoRoot "output\rom\DC_kuorong_464K.nes"
$probeDir = Join-Path $repoRoot "output\build\legacy-ui-probe"
$tagSuffix = @{
    "beam-xy" = "beamxy"
    "beam-code" = "beamcode"
    "movement1-code" = "m1code"
    "movement1-increment" = "m1inc"
    "movement2-code" = "m2code"
    "movement2-increment" = "m2inc"
    "picture-xy" = "picxy"
    "picture-code" = "piccode"
    "beam-puzzle-replace" = "beampuzzle-replace"
    "beam-puzzle-noop" = "beampuzzle-noop"
    "beam-puzzle-delete" = "beampuzzle-delete"
    "picture-puzzle-move" = "picpuzzle-move"
    "picture-puzzle-flip" = "picpuzzle-flip"
    "picture-puzzle-hflip" = "picpuzzle-hflip"
    "picture-puzzle-vflip" = "picpuzzle-vflip"
}[$Case]
$recordTag = if ($Record -gt 0) { "-r$Record" } else { "" }
$variantTag = if ($Case.EndsWith("-code")) { "-$CodeVariant" } else { "" }
$tag = if ($Record -gt 0) {
    $shortCase = @{
        "beam-puzzle-replace" = "beamrep"
        "beam-puzzle-noop" = "beamnoop"
        "beam-puzzle-delete" = "beamdel"
        "picture-puzzle-move" = "picmove"
        "picture-puzzle-flip" = "picflip"
        "picture-puzzle-hflip" = "pichflip"
        "picture-puzzle-vflip" = "picvflip"
    }[$Case]
    if (-not $shortCase) { $shortCase = $tagSuffix }
    "wrulesave-$shortCase$recordTag$variantTag-01"
} else {
    "recursive-wrulesave-$tagSuffix$variantTag-01"
}
$tag = if ($EvidenceTag) { $EvidenceTag } else { $tag }
$probeRom = Join-Path $probeDir "weapon-rule-save-$tag.nes"
$Code = if ($Case -eq "beam-code") {
    switch ($CodeVariant) {
        "longer" { "FD 20 20 F8 FF 00 00 FF" }
        "shorter" { "FD 20 20 F8 FF FF" }
        default { "FD 20 20 F8 FF 01 FF" }
    }
} elseif ($Case -eq "picture-code") {
    switch ($CodeVariant) {
        "longer" { "01 00 00 08 F0 00 00 00 28 04 E8 80 80 80 A8 01 E8 80 80 80 00 FF" }
        "shorter" { "01 00 00 08 F0 00 00 00 28 04 E8 80 80 80 A8 01 E8 80 80 FF" }
        default { "01 00 00 08 F0 00 00 00 28 04 E8 80 80 80 A8 01 E8 80 80 81 FF" }
    }
} else {
    switch ($CodeVariant) {
        "longer" { "01 83 F0 FC 00 83 F0 FC 00" }
        "shorter" { "01 83 F0 FC 00 83 F0" }
        default { "01 83 F0 FC 00 83 F0 FC" }
    }
}
$logPath = Join-Path $repoRoot "output\verification\legacy-ui-probe-$tag.log"
$evidenceDir = Join-Path $repoRoot "output\verification\legacy-ui-probe-$tag"

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

$probeArgs = @(
    $probe,
    "--stage", "A,LOAD,DBWRULESAVE",
    "--rom", $probeRom,
    "--wrule-case", $Case,
    "--wrule-value", "$Value",
    "--wrule-value2", "$Value2",
    "--wrule-record", "$Record",
    "--wrule-code", $Code,
    "--wrule-puzzle-start", "$PuzzleStart",
    "--wrule-library-x", "$LibraryX",
    "--wrule-library-y", "$LibraryY",
    "--wrule-effect-x", "$EffectX",
    "--wrule-effect-y", "$EffectY",
    "--evidence-tag", $tag
)
if ($ExpectNoop) {
    $probeArgs += "--wrule-expect-noop"
}

Set-Location -LiteralPath $repoRoot
& $python @probeArgs 2>&1 |
    Set-Content -LiteralPath $logPath -Encoding utf8
exit $LASTEXITCODE
