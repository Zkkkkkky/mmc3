$ErrorActionPreference = "Stop"

$packageRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$manifestPath = Join-Path $packageRoot "文件清单_SHA256.csv"
$excludedPrefixes = @(
    ".venv\",
    ".git\",
    "build\pyinstaller-work\",
    # User-supplied reverse-engineering references are inputs, not handoff files.
    "默认配置文件\",
    "修改器\"
)

$records = Get-ChildItem -LiteralPath $packageRoot -Recurse -File | ForEach-Object {
    $relativePath = [IO.Path]::GetRelativePath($packageRoot, $_.FullName)
    if ($relativePath -eq "文件清单_SHA256.csv") {
        return
    }
    if ($relativePath -match "(^|\\)__pycache__\\") {
        return
    }
    if ($relativePath -eq "FC模拟器\fceux.cfg") {
        return
    }
    if ($relativePath -like "*.spec") {
        return
    }
    foreach ($prefix in $excludedPrefixes) {
        if ($relativePath.StartsWith($prefix, [StringComparison]::OrdinalIgnoreCase)) {
            return
        }
    }
    [PSCustomObject]@{
        RelativePath = $relativePath
        Bytes = $_.Length
        SHA256 = (Get-FileHash -LiteralPath $_.FullName -Algorithm SHA256).Hash
    }
} | Sort-Object RelativePath

$records | Export-Csv -LiteralPath $manifestPath -NoTypeInformation -Encoding utf8
Write-Output "已更新哈希清单：$($records.Count) 个文件。"
