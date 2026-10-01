$ErrorActionPreference = "Stop"

$repoRoot = Split-Path -Parent $PSScriptRoot
$python = Join-Path $repoRoot ".venv\Scripts\python.exe"
$probe = Join-Path $repoRoot "tools\research\legacy_ui_probe.py"
$sourceRom = Join-Path $repoRoot "output\rom\DC_kuorong_464K.nes"
$probeDir = Join-Path $repoRoot "output\build\legacy-ui-probe"
$probeRom = Join-Path $probeDir "weapon-rule-button-case.nes"
$verificationRoot = Join-Path $repoRoot "output\verification"
$cases = @(
    @{ Page = 0; Button = 420; Record = 0 },
    @{ Page = 0; Button = 470; Record = 10 },
    @{ Page = 1; Button = 720; Record = 0 },
    @{ Page = 2; Button = 740; Record = 0 },
    @{ Page = 3; Button = 520; Record = 0 },
    @{ Page = 0; Button = 100; Record = 0 },
    @{ Page = 0; Button = 110; Record = 0 }
)
$actions = @("left", "right", "keyboard")

New-Item -ItemType Directory -Force -Path $probeDir | Out-Null
Set-Location -LiteralPath $repoRoot
foreach ($case in $cases) {
    foreach ($action in $actions) {
        $tag = "wrb-p$($case.Page)-b$($case.Button)-$action"
        $evidenceDir = Join-Path $verificationRoot "legacy-ui-probe-$tag"
        $logPath = Join-Path $verificationRoot "legacy-ui-probe-$tag.log"
        $resultPath = Join-Path $evidenceDir "interaction-discovery\weapon-rule-button-case.json"
        if (Test-Path -LiteralPath $resultPath) {
            $prior = Get-Content -LiteralPath $resultPath -Raw | ConvertFrom-Json
            if ($prior.validated -eq $true) {
                Write-Output "[$tag] already validated; skipping"
                continue
            }
        }
        Copy-Item -LiteralPath $sourceRom -Destination $probeRom -Force
        Write-Output "[$tag] starting isolated legacy gesture"
        if (Test-Path -LiteralPath $evidenceDir) {
            $resolvedEvidence = (Resolve-Path -LiteralPath $evidenceDir).Path
            $resolvedVerification = (Resolve-Path -LiteralPath $verificationRoot).Path
            if (-not $resolvedEvidence.StartsWith($resolvedVerification + [IO.Path]::DirectorySeparatorChar)) {
                throw "Refusing to clean evidence outside output verification: $resolvedEvidence"
            }
            Remove-Item -LiteralPath $resolvedEvidence -Recurse -Force
        }
        & $python $probe `
            --stage A,LOAD,DBWRULEBUTTONCASE `
            --rom $probeRom `
            --wrule-page-index $case.Page `
            --wrule-button-id $case.Button `
            --wrule-button-action $action `
            --wrule-record $case.Record `
            --fast-launch `
            --evidence-tag $tag 2>&1 |
            Set-Content -LiteralPath $logPath -Encoding utf8
        if ($LASTEXITCODE -ne 0) {
            throw "Weapon-rule button case failed: page=$($case.Page) button=$($case.Button) action=$action"
        }
        Write-Output "[$tag] passed"
    }
}
