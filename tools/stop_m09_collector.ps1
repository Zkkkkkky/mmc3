param([int]$RootPid)
$ErrorActionPreference = "SilentlyContinue"
$all = Get-CimInstance Win32_Process
$ids = @($RootPid)
do {
  $new = @($all | Where-Object { $_.ParentProcessId -in $ids -and $_.ProcessId -notin $ids } | Select-Object -ExpandProperty ProcessId)
  $before = $ids.Count
  $ids = @($ids + $new | Select-Object -Unique)
} while ($ids.Count -gt $before)
$ids = @($ids | Where-Object { $_ -ne 15748 })
Stop-Process -Id $ids -Force
