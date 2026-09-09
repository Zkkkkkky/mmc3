$ErrorActionPreference = "Stop"
$packageRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$manifestPath = Join-Path $packageRoot "文件清单_SHA256.csv"

if (-not (Test-Path -LiteralPath $manifestPath)) {
    throw "找不到哈希清单：$manifestPath"
}

$failures = [System.Collections.Generic.List[string]]::new()
$records = Import-Csv -LiteralPath $manifestPath
foreach ($record in $records) {
    $path = Join-Path $packageRoot $record.RelativePath
    if (-not (Test-Path -LiteralPath $path -PathType Leaf)) {
        $failures.Add("缺少文件：$($record.RelativePath)")
        continue
    }

    $item = Get-Item -LiteralPath $path
    if ($item.Length -ne [long]$record.Bytes) {
        $failures.Add(
            "大小不符：$($record.RelativePath)；预期 $($record.Bytes)，实际 $($item.Length)"
        )
        continue
    }

    $actualHash = (Get-FileHash -LiteralPath $path -Algorithm SHA256).Hash
    if ($actualHash -ne $record.SHA256) {
        $failures.Add("SHA-256 不符：$($record.RelativePath)")
    }
}

if ($failures.Count -gt 0) {
    $failures | ForEach-Object { Write-Error $_ }
    exit 1
}

Write-Output "交接包验证通过：$($records.Count) 个文件。"
exit 0
