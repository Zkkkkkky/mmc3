$ErrorActionPreference = "Stop"

$root = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot "..")).Path
$python = Join-Path $root ".venv\Scripts\python.exe"
$asm6 = Join-Path $root "tools\vendor\famistudio-4.5.3\Tools\asm6_fixed.exe"
$specFile = Join-Path $PSScriptRoot "dc_modifier.spec"
$dist = Join-Path $root "output\app"
$work = Join-Path $root "output\build\pyinstaller-work"

if (-not (Test-Path -LiteralPath $python -PathType Leaf)) {
    throw "未找到虚拟环境 Python：$python"
}
if (-not (Test-Path -LiteralPath $asm6 -PathType Leaf)) {
    throw "未找到音乐导入所需 ASM6：$asm6"
}
if (-not (Test-Path -LiteralPath $specFile -PathType Leaf)) {
    throw "未找到 PyInstaller 配置：$specFile"
}

& $python (Join-Path $root "tools\export_dc_modifier_mappings.py")
if ($LASTEXITCODE -ne 0) {
    throw "修改器映射表生成失败，退出码：$LASTEXITCODE"
}

& $python -m PyInstaller `
    --noconfirm `
    --clean `
    --distpath $dist `
    --workpath $work `
    $specFile
if ($LASTEXITCODE -ne 0) {
    throw "PyInstaller 构建失败，退出码：$LASTEXITCODE"
}

$output = Join-Path $dist "新DC篇完整修改器.exe"
if (-not (Test-Path -LiteralPath $output -PathType Leaf)) {
    throw "PyInstaller 未生成预期文件：$output"
}
$archiveListing = & $python -m PyInstaller.utils.cliutils.archive_viewer -l $output
if ($LASTEXITCODE -ne 0) {
    throw "无法读取生成的 EXE 归档。"
}
if ($archiveListing -match "(?im)'(?:icuuc\.dll|icudt78\.dll)'") {
    throw "EXE 意外包含与 Qt6Core 不兼容的 Poppler ICU DLL。"
}
$selfTest = Start-Process -FilePath $output -ArgumentList "--self-test" -WorkingDirectory $root -WindowStyle Hidden -Wait -PassThru
if ($selfTest.ExitCode -ne 0) {
    throw "EXE 主窗口自检失败，退出码：$($selfTest.ExitCode)"
}
$hash = (Get-FileHash -LiteralPath $output -Algorithm SHA256).Hash
$hashFile = "$output.sha256.txt"
Set-Content -LiteralPath $hashFile -Value "$hash  新DC篇完整修改器.exe" -Encoding utf8
$mappingSource = Join-Path $root "output\mappings"
$mappingDestination = Join-Path $dist "修改器映射表"
New-Item -ItemType Directory -Path $mappingDestination -Force | Out-Null
Copy-Item -Path (Join-Path $mappingSource "*") -Destination $mappingDestination -Force
Write-Host "EXE: $output"
Write-Host "SHA-256: $hash"
Write-Host "Checksum: $hashFile"
Write-Host "Mappings: $mappingDestination"
