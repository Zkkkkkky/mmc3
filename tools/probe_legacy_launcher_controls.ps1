$ErrorActionPreference = "Stop"
$Repo = Split-Path -Parent $PSScriptRoot
$Python = Join-Path $Repo ".venv\Scripts\python.exe"
$Probe = Join-Path $Repo "tools\research\legacy_ui_probe.py"
$VerificationRoot = Join-Path $Repo "output\verification"
$Tag = "recursive-launchercontrols-01"
$EvidenceDir = Join-Path $VerificationRoot "legacy-ui-probe-$Tag"
$LogPath = Join-Path $VerificationRoot "legacy-ui-probe-$Tag.log"
if (Test-Path -LiteralPath $EvidenceDir) {
    $ResolvedEvidence = (Resolve-Path -LiteralPath $EvidenceDir).Path
    $ResolvedVerification = (Resolve-Path -LiteralPath $VerificationRoot).Path
    if (-not $ResolvedEvidence.StartsWith($ResolvedVerification + [IO.Path]::DirectorySeparatorChar)) { throw "Unsafe evidence path" }
    Remove-Item -LiteralPath $ResolvedEvidence -Recurse -Force
}
Set-Location -LiteralPath $Repo
& $Python $Probe --stage "LAUNCHERCONTROLS" --fast-launch --evidence-tag $Tag 2>&1 | Tee-Object -FilePath $LogPath
if ($LASTEXITCODE -ne 0) { throw "Launcher-control probe failed" }
