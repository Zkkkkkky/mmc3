$ErrorActionPreference = "Stop"

$repoRoot = Split-Path -Parent $PSScriptRoot
$python = Join-Path $repoRoot ".venv\Scripts\python.exe"
$probe = Join-Path $repoRoot "tools\research\legacy_ui_probe.py"
$sourceRom = Join-Path $repoRoot "output\rom\DC_kuorong_464K.nes"
$probeDir = Join-Path $repoRoot "output\build\legacy-ui-probe"
$probeRom = Join-Path $probeDir "weapon-rule-puzzle-controls.nes"
$verificationRoot = Join-Path $repoRoot "output\verification"
$tag = "recursive-dbwrulepuzzlecontrols-01"
$evidenceDir = Join-Path $verificationRoot "legacy-ui-probe-$tag"
$logPath = Join-Path $verificationRoot "legacy-ui-probe-$tag.log"

New-Item -ItemType Directory -Force -Path $probeDir | Out-Null
Copy-Item -LiteralPath $sourceRom -Destination $probeRom -Force
if (Test-Path -LiteralPath $evidenceDir) {
    $resolvedEvidence = (Resolve-Path -LiteralPath $evidenceDir).Path
    $resolvedVerification = (Resolve-Path -LiteralPath $verificationRoot).Path
    if (-not $resolvedEvidence.StartsWith($resolvedVerification + [IO.Path]::DirectorySeparatorChar)) {
        throw "Refusing to clean evidence outside output verification: $resolvedEvidence"
    }
    Remove-Item -LiteralPath $resolvedEvidence -Recurse -Force
}
Set-Location -LiteralPath $repoRoot
& $python $probe `
    --stage A,LOAD,DBWRULEPUZZLECONTROLS `
    --rom $probeRom `
    --fast-launch `
    --evidence-tag $tag 2>&1 |
    Tee-Object -FilePath $logPath
if ($LASTEXITCODE -ne 0) {
    throw "Weapon-rule puzzle control matrix probe failed"
}
