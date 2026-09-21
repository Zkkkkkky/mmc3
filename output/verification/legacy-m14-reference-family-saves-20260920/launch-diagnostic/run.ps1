$ErrorActionPreference='Stop'
$exe='D:\GIT\mmc3\output\verification\legacy-m14-reference-family-saves-20260920\launch-diagnostic\SRW2_patched.exe'
$p=Start-Process -FilePath $exe -WorkingDirectory (Split-Path $exe) -PassThru
Start-Sleep -Seconds 3
$p.Refresh()
$windows = Get-CimInstance Win32_Process | Where-Object { $_.ProcessId -eq $p.Id } | Select-Object ProcessId,ParentProcessId,Name,CreationDate
@{pid=$p.Id; exited=$p.HasExited; windows=$windows} | ConvertTo-Json -Depth 4 | Set-Content -LiteralPath 'D:\GIT\mmc3\output\verification\legacy-m14-reference-family-saves-20260920\launch-diagnostic.json' -Encoding UTF8
if (-not $p.HasExited) { Stop-Process -Id $p.Id -Force }
