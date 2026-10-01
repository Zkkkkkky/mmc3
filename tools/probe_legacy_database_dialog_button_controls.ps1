$ErrorActionPreference = "Stop"
$Repo = Split-Path -Parent $PSScriptRoot
$Python = Join-Path $Repo ".venv\Scripts\python.exe"
$Probe = Join-Path $Repo "tools\research\legacy_ui_probe.py"
$SourceRom = Join-Path $Repo "output\rom\DC_kuorong_464K.nes"
$ProbeDir = Join-Path $Repo "output\build\legacy-ui-probe"
$ProbeRom = Join-Path $ProbeDir "database-dialog-button-controls.nes"
$VerificationRoot = Join-Path $Repo "output\verification"
$Tag = "recursive-dbdialogbuttoncontrols-01"
$EvidenceDir = Join-Path $VerificationRoot "legacy-ui-probe-$Tag"
$LogPath = Join-Path $VerificationRoot "legacy-ui-probe-$Tag.log"
New-Item -ItemType Directory -Force -Path $ProbeDir | Out-Null
Copy-Item -LiteralPath $SourceRom -Destination $ProbeRom -Force
if (Test-Path -LiteralPath $EvidenceDir) {
    $ResolvedEvidence = (Resolve-Path -LiteralPath $EvidenceDir).Path
    $ResolvedVerification = (Resolve-Path -LiteralPath $VerificationRoot).Path
    if (-not $ResolvedEvidence.StartsWith($ResolvedVerification + [IO.Path]::DirectorySeparatorChar)) { throw "Unsafe evidence path" }
    Remove-Item -LiteralPath $ResolvedEvidence -Recurse -Force
}
Set-Location -LiteralPath $Repo
& $Python $Probe --stage "A,LOAD,DBDIALOGBUTTONCONTROLS" --rom $ProbeRom --fast-launch --evidence-tag $Tag 2>&1 | Tee-Object -FilePath $LogPath
if ($LASTEXITCODE -ne 0) { throw "Database dialogue-button probe failed" }
