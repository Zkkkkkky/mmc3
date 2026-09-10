$ErrorActionPreference = "Stop"

$packageRoot = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot "..")).Path
$manifestPath = Join-Path $packageRoot "output\manifest\文件清单_SHA256.csv"
$excludedPrefixes = @(
    ".venv\",
    ".git\",
    ".codex-remote-attachments\",
    ".skill-staging\",
    "tmp\",
    "output\build\pyinstaller-work\",
    # User-supplied reverse-engineering snapshots are not handoff files.
    "references\legacy_modifier\"
)

$records = Get-ChildItem -LiteralPath $packageRoot -Recurse -File | ForEach-Object {
    $relativePath = [IO.Path]::GetRelativePath($packageRoot, $_.FullName)
    if ($relativePath -eq "output\manifest\文件清单_SHA256.csv") {
        return
    }
    if ($relativePath -match "(^|\\)__pycache__\\") {
        return
    }
    if ($relativePath -eq "tools\vendor\fceux-2.6.6\fceux.cfg") {
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

$manifestDirectory = Split-Path -Parent $manifestPath
New-Item -ItemType Directory -Path $manifestDirectory -Force | Out-Null
$records | Export-Csv -LiteralPath $manifestPath -NoTypeInformation -Encoding utf8
Write-Output "已更新哈希清单：$($records.Count) 个文件。"
