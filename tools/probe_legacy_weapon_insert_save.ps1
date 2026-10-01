$ErrorActionPreference = "Stop"

$repoRoot = Split-Path -Parent $PSScriptRoot
$python = Join-Path $repoRoot ".venv\Scripts\python.exe"
$probe = Join-Path $repoRoot "tools\research\legacy_ui_probe.py"
$sourceRom = Join-Path $repoRoot "output\rom\DC_kuorong_464K.nes"
$probeDir = Join-Path $repoRoot "output\build\legacy-ui-probe"
$probeRom = Join-Path $probeDir "rule-c2-v2-01-02-03.nes"
$logPath = Join-Path $repoRoot "output\verification\legacy-ui-probe-recursive-dbsavec2-v2-01.log"

New-Item -ItemType Directory -Force -Path $probeDir | Out-Null
Copy-Item -LiteralPath $sourceRom -Destination $probeRom -Force

Set-Location -LiteralPath $repoRoot
& $python $probe `
    --stage A,LOAD,DBSAVEF3 `
    --rom $probeRom `
    --dbins-option 1 `
    --dbins-button 170 `
    --dbins-value 2 `
    --dbins-value2 3 `
    --dbins-rule-family c2 `
    --dbins-rule-variant 1 `
    --dbins-confirm no `
    --evidence-tag recursive-dbsavec2-v2-01 2>&1 |
    Set-Content -LiteralPath $logPath -Encoding utf8
exit $LASTEXITCODE
