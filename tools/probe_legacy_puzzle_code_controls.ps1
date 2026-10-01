$ErrorActionPreference = "Stop"
$Repo = Split-Path -Parent $PSScriptRoot
$Python = Join-Path $Repo ".venv\Scripts\python.exe"
$Probe = Join-Path $Repo "tools\research\legacy_ui_probe.py"
$SourceRom = Join-Path $Repo "output\rom\DC_kuorong_464K.nes"
$ProbeDir = Join-Path $Repo "output\build\legacy-ui-probe"
$VerificationRoot = Join-Path $Repo "output\verification"
$Cases = @("ok-keyboard","ok-left","ok-right","cancel-keyboard","cancel-left","cancel-right")
New-Item -ItemType Directory -Force -Path $ProbeDir | Out-Null
Set-Location -LiteralPath $Repo
$Ordinal = 0
foreach ($Case in $Cases) {
    $Ordinal += 1
    $SafeCase = $Case.Replace("keyboard","key")
    $Tag = "recursive-puzzlecode-$SafeCase-$('{0:D2}' -f $Ordinal)"
    $EvidenceDir = Join-Path $VerificationRoot "legacy-ui-probe-$Tag"
    $LogPath = Join-Path $VerificationRoot "legacy-ui-probe-$Tag.log"
    $ProbeRom = Join-Path $ProbeDir "puzzle-code-$Ordinal.nes"
    Copy-Item -LiteralPath $SourceRom -Destination $ProbeRom -Force
    if (Test-Path -LiteralPath $EvidenceDir) {
        $ResolvedEvidence = (Resolve-Path -LiteralPath $EvidenceDir).Path
        $ResolvedVerification = (Resolve-Path -LiteralPath $VerificationRoot).Path
        if (-not $ResolvedEvidence.StartsWith($ResolvedVerification + [IO.Path]::DirectorySeparatorChar)) { throw "Unsafe evidence path" }
        Remove-Item -LiteralPath $ResolvedEvidence -Recurse -Force
    }
    & $Python $Probe --stage "A,LOAD,PUZZLECODECONTROLS" --rom $ProbeRom --fast-launch --puzzle-code-case $Case --evidence-tag $Tag 2>&1 | Tee-Object -FilePath $LogPath
    if ($LASTEXITCODE -ne 0) { throw "Puzzle-code probe failed: $Case" }
}
