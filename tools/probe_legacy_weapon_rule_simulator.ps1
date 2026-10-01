param()

$ErrorActionPreference = "Stop"
$repoRoot = Split-Path -Parent $PSScriptRoot
$python = Join-Path $repoRoot ".venv\Scripts\python.exe"
$probe = Join-Path $repoRoot "tools\research\legacy_ui_probe.py"
$sourceRom = Join-Path $repoRoot "output\rom\DC_kuorong_464K.nes"
$probeDir = Join-Path $repoRoot "output\build\legacy-ui-probe"
$probeRom = Join-Path $probeDir "weapon-rule-simulator.nes"
$tag = "recursive-wrulesim-01"
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

Set-Location -LiteralPath $repoRoot
$oldCompatLayer = $env:__COMPAT_LAYER
$oldPythonIoEncoding = $env:PYTHONIOENCODING
try {
    # The reference executable embeds an elevation request.  Running the
    # isolated probe copy as invoker keeps the probe and reference UI at the
    # same desktop integrity level, so synthetic user input is observable and
    # no UAC-only false negatives enter the evidence set.
    $env:__COMPAT_LAYER = "RunAsInvoker"
    $env:PYTHONIOENCODING = "utf-8"
    & $python $probe `
        --stage A,LOAD,DBWRULESIM `
        --rom $probeRom `
        --evidence-tag $tag 2>&1 |
        Set-Content -LiteralPath $logPath -Encoding utf8
    $exitCode = $LASTEXITCODE
}
finally {
    $env:__COMPAT_LAYER = $oldCompatLayer
    $env:PYTHONIOENCODING = $oldPythonIoEncoding
}
exit $exitCode
