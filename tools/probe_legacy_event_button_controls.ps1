$ErrorActionPreference = "Stop"
$Repo = Split-Path -Parent $PSScriptRoot
$Python = Join-Path $Repo ".venv\Scripts\python.exe"
$Probe = Join-Path $Repo "tools\research\legacy_ui_probe.py"
$SourceRom = Join-Path $Repo "output\rom\DC_kuorong_464K.nes"
$ProbeDir = Join-Path $Repo "output\build\legacy-ui-probe"
$ProbeRom = Join-Path $ProbeDir "event-button-controls.nes"
$VerificationRoot = Join-Path $Repo "output\verification"
New-Item -ItemType Directory -Force -Path $ProbeDir | Out-Null
Set-Location -LiteralPath $Repo
$Cases = @(
    "page",
    "global-690-right_click", "global-690-keyboard_activate", "global-690-left_click",
    "global-100-right_click", "global-100-keyboard_activate", "global-100-left_click",
    "global-110-right_click", "global-110-keyboard_activate", "global-110-left_click"
)
$Ordinal = 0
foreach ($Case in $Cases) {
    $Ordinal += 1
    $SafeCase = $Case.Replace("global-", "g").Replace("keyboard_activate", "key").Replace("right_click", "right").Replace("left_click", "left")
    $Tag = "recursive-eventbutton-$SafeCase-$('{0:D2}' -f $Ordinal)"
    $EvidenceDir = Join-Path $VerificationRoot "legacy-ui-probe-$Tag"
    $LogPath = Join-Path $VerificationRoot "legacy-ui-probe-$Tag.log"
    $CaseRom = [IO.Path]::ChangeExtension($ProbeRom, ".$Ordinal.nes")
    Copy-Item -LiteralPath $SourceRom -Destination $CaseRom -Force
    if (Test-Path -LiteralPath $EvidenceDir) {
        $ResolvedEvidence = (Resolve-Path -LiteralPath $EvidenceDir).Path
        $ResolvedVerification = (Resolve-Path -LiteralPath $VerificationRoot).Path
        if (-not $ResolvedEvidence.StartsWith($ResolvedVerification + [IO.Path]::DirectorySeparatorChar)) { throw "Unsafe evidence path" }
        Remove-Item -LiteralPath $ResolvedEvidence -Recurse -Force
    }
    & $Python $Probe --stage "A,LOAD,EVENTBUTTONCONTROLS" --rom $CaseRom --fast-launch --event-button-case $Case --evidence-tag $Tag 2>&1 | Tee-Object -FilePath $LogPath
    if ($LASTEXITCODE -ne 0) { throw "Event button probe failed: $Case" }
}
