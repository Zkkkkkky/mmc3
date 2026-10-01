$ErrorActionPreference = "Stop"

$repoRoot = Split-Path -Parent $PSScriptRoot
$python = Join-Path $repoRoot ".venv\Scripts\python.exe"
$probe = Join-Path $repoRoot "tools\research\legacy_ui_probe.py"
$sourceRom = Join-Path $repoRoot "output\rom\DC_kuorong_464K.nes"
$probeDir = Join-Path $repoRoot "output\build\legacy-ui-probe"
$probeRom = Join-Path $probeDir "weapon-command-cancel-all.nes"
$logPath = Join-Path $repoRoot "output\verification\legacy-ui-probe-recursive-dbcancelall-01.log"

New-Item -ItemType Directory -Force -Path $probeDir | Out-Null
Copy-Item -LiteralPath $sourceRom -Destination $probeRom -Force

Set-Location -LiteralPath $repoRoot
& $python $probe `
    --stage A,LOAD,DBCANCELALL `
    --rom $probeRom `
    --evidence-tag recursive-dbcancelall-01 2>&1 |
    Set-Content -LiteralPath $logPath -Encoding utf8
exit $LASTEXITCODE
