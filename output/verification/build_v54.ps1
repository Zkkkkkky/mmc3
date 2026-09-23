$source='C:\Users\hu\Desktop\测试.nes'
$target='C:\Users\hu\Desktop\测试_敌方武器对象重映射修复V54.nes'
$reference='D:\GIT\mmc3\output\verification\v54-rebuilt-from-test.nes'
$rom=[IO.File]::ReadAllBytes($source); $chrBase=0x80010
function Copy-ChrTile([int]$s,[int]$st,[int]$d,[int]$dt){[Array]::Copy($rom,$chrBase+$s*0x400+$st*16,$rom,$chrBase+$d*0x400+$dt*16,16)}

for($tile=0x86;$tile -le 0xA9;$tile++){
    $targetTile=$tile -bxor 0x70
    Copy-ChrTile 0xFC ($tile-0x80) 0xFD ($targetTile-0xC0)
    Copy-ChrTile 0xFC ($tile-0x80) 0x13 ($targetTile-0xC0)
}

[Array]::Copy([byte[]](0xA9,0x04,0x85,0x15),0,$rom,0x7D0F5,4)
[Array]::Copy([byte[]](0x20,0x67,0xF4,0xEA,0xEA),0,$rom,0x7D1E7,5)

# 仅动画指针低字节标记为 $C2 的武器对象使用 $F0；机体 $C1、头像/UI 等保持原掩码。
$helper=[byte[]](
    0x85,0x1E,0xF0,0x0B,
    0xBD,0x40,0x07,0xC9,0xC2,0xD0,0x04,
    0xA9,0xF0,0x85,0x1E,
    0xBD,0x30,0x07,0x60
)
[Array]::Copy($helper,0,$rom,0x7F477,$helper.Length)

[IO.File]::WriteAllBytes($target,$rom); [IO.File]::WriteAllBytes($reference,$rom)
Get-FileHash -Algorithm SHA256 -LiteralPath $target
