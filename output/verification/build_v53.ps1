$source='C:\Users\hu\Desktop\测试.nes'
$target='C:\Users\hu\Desktop\测试_敌方武器动画表重映射修复V53.nes'
$reference='D:\GIT\mmc3\output\verification\v53-rebuilt-from-test.nes'
$rom=[IO.File]::ReadAllBytes($source); $chrBase=0x80010
function Copy-ChrTile([int]$s,[int]$st,[int]$d,[int]$dt){[Array]::Copy($rom,$chrBase+$s*0x400+$st*16,$rom,$chrBase+$d*0x400+$dt*16,16)}

# 敌方原 tile = raw XOR $80；改为 raw XOR $F0 后，目标 tile = 原 tile XOR $70。
# 目标集合为 $D0-$D9、$E0-$EF、$F6-$FF，已在完整回合 OAM 中确认未使用。
for($tile=0x86;$tile -le 0xA9;$tile++){
    $targetTile=$tile -bxor 0x70
    Copy-ChrTile 0xFC ($tile-0x80) 0xFD ($targetTile-0xC0)
    Copy-ChrTile 0xFC ($tile-0x80) 0x13 ($targetTile-0xC0)
}

# 释放固定 Bank 的 $F467 区域。
[Array]::Copy([byte[]](0xA9,0x04,0x85,0x15),0,$rom,0x7D0F5,4)

# 对象初始化：原 STA $1E / LDA $0730,X 改为一次 JSR；这是每对象一次，不是每子精灵一次。
[Array]::Copy([byte[]](0x20,0x67,0xF4,0xEA,0xEA),0,$rom,0x7D1E7,5)

# A 入参为原掩码 $00/$80。仅当掩码非零且动画数据高字节为 $83 时改成 $F0；
# 同时返回原流程需要的 $0730,X（动画指针高字节）。
$helper=[byte[]](
    0x85,0x1E,0xF0,0x0E,
    0xBD,0x30,0x07,0xC9,0x83,0xD0,0x06,
    0xA9,0xF0,0x85,0x1E,0xA9,0x83,
    0x60,
    0xBD,0x30,0x07,0x60
)
[Array]::Copy($helper,0,$rom,0x7F477,$helper.Length)

[IO.File]::WriteAllBytes($target,$rom); [IO.File]::WriteAllBytes($reference,$rom)
Get-FileHash -Algorithm SHA256 -LiteralPath $target
