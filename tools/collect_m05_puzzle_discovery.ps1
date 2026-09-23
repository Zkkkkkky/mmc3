param(
    [switch]$PreflightOnly
)

$ErrorActionPreference = "Continue"

$repoRoot = Split-Path -Parent $PSScriptRoot
$python = Join-Path $repoRoot ".venv\Scripts\python.exe"
$reporter = Join-Path $repoRoot "tools\report_golden_coverage.py"
$samplePreparer = Join-Path $repoRoot "tools\prepare_m05_legacy_upload_samples.py"
$baseline = Join-Path $repoRoot "output\build\legacy-diff-audit\m05-reference-baseline.nes"
$legacyExe = Join-Path $repoRoot "output\build\legacy-diff-audit\SRW2_patched.exe"
$logPath = Join-Path $repoRoot "output\verification\m05-puzzle-discovery.log"
$caseRoot = Join-Path $repoRoot "tools\golden_pipeline\discovery_history"
$cases = @(
    "M05-body-upload-bmp-discovery-cold-start-01.json",
    "M05-body-compressed-upload-bmp-discovery-cold-start-01.json",
    "M05-fragment-upload-bmp-discovery-cold-start-01.json",
    "M05-fragment-compressed-upload-bmp-discovery-cold-start-01.json",
    "M05-icon-upload-bmp-discovery-cold-start-01.json",
    "M05-main-clear-body-discovery-cold-start-01.json",
    "M05-main-clear-fragment-discovery-cold-start-01.json",
    "M05-icon-binding-double-click-discovery-cold-start-01.json",
    "M05-body-puzzle-clear-discovery-cold-start-01.json",
    "M05-body-puzzle-move-up-discovery-cold-start-01.json",
    "M05-body-puzzle-move-down-discovery-cold-start-01.json",
    "M05-body-puzzle-move-left-discovery-cold-start-01.json",
    "M05-body-puzzle-move-right-discovery-cold-start-01.json",
    "M05-body-puzzle-template-8x8-discovery-cold-start-01.json",
    "M05-body-puzzle-template-7x9-discovery-cold-start-01.json",
    "M05-body-puzzle-template-9x7-discovery-cold-start-01.json",
    "M05-body-puzzle-template-10x6-discovery-cold-start-01.json",
    "M05-body-puzzle-swap-banks-discovery-cold-start-01.json",
    "M05-fragment-puzzle-move-up-discovery-cold-start-01.json",
    "M05-fragment-puzzle-move-down-discovery-cold-start-01.json",
    "M05-fragment-puzzle-move-left-discovery-cold-start-01.json",
    "M05-fragment-puzzle-move-right-discovery-cold-start-01.json",
    "M05-fragment-puzzle-clear-discovery-cold-start-01.json",
    "M05-fragment-puzzle-flip-horizontal-discovery-cold-start-01.json",
    "M05-fragment-puzzle-flip-vertical-discovery-cold-start-01.json"
)

Set-Location -LiteralPath $repoRoot
$requiredFiles = @($python, $reporter, $samplePreparer, $baseline, $legacyExe)
foreach ($requiredFile in $requiredFiles) {
    if (-not (Test-Path -LiteralPath $requiredFile -PathType Leaf)) {
        throw "M05 discovery preflight missing required file: $requiredFile"
    }
}
foreach ($caseName in $cases) {
    $config = Join-Path $caseRoot $caseName
    if (-not (Test-Path -LiteralPath $config -PathType Leaf)) {
        throw "M05 discovery preflight missing case config: $config"
    }
}
& $python $samplePreparer
if ($LASTEXITCODE -ne 0) {
    throw "M05 legacy upload sample preparation failed with exit code $LASTEXITCODE"
}
if ($PreflightOnly) {
    foreach ($caseName in $cases) {
        $config = Join-Path $caseRoot $caseName
        $payload = Get-Content -Raw -LiteralPath $config | ConvertFrom-Json
        if (
            $payload.module -ne "M05" -or
            $payload.case_kind -ne "discovery" -or
            @($payload.expected_offsets).Count -ne 0 -or
            @($payload.required_offsets).Count -ne 0
        ) {
            throw "M05 discovery preflight rejected unguarded config: $caseName"
        }
    }
    $baselineHash = (Get-FileHash -Algorithm SHA256 -LiteralPath $baseline).Hash
    $legacyExeHash = (Get-FileHash -Algorithm SHA256 -LiteralPath $legacyExe).Hash
    Write-Output "M05 discovery preflight passed: cases=$($cases.Count)"
    Write-Output "baseline_sha256=$baselineHash"
    Write-Output "legacy_exe_sha256=$legacyExeHash"
    exit 0
}
"M05 action discovery started: $(Get-Date -Format o)" |
    Set-Content -LiteralPath $logPath -Encoding utf8
$failed = 0
foreach ($caseName in $cases) {
    $config = Join-Path $caseRoot $caseName
    "`n=== $caseName ===" | Add-Content -LiteralPath $logPath -Encoding utf8
    & $python $reporter collect --case-config $config --baseline $baseline 2>&1 |
        Add-Content -LiteralPath $logPath -Encoding utf8
    if ($LASTEXITCODE -ne 0) {
        $failed += 1
        "exit_code=$LASTEXITCODE" | Add-Content -LiteralPath $logPath -Encoding utf8
    }
}
"`nM05 action discovery finished: $(Get-Date -Format o); failed=$failed" |
    Add-Content -LiteralPath $logPath -Encoding utf8
exit $failed
