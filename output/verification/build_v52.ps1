$source='C:\Users\hu\Desktop\测试.nes'
$target='C:\Users\hu\Desktop\测试_敌方武器OAM生成点修复V52.nes'
$reference='D:\GIT\mmc3\output\verification\v52-rebuilt-from-test.nes'
$rom=[IO.File]::ReadAllBytes($source); $chrBase=0x80010
function Copy-ChrTile([int]$s,[int]$st,[int]$d,[int]$dt){[Array]::Copy($rom,$chrBase+$s*0x400+$st*16,$rom,$chrBase+$d*0x400+$dt*16,16)}

# 顶部与 UI 的原 R1 页都在未使用的 $D0-$F3 放置同一份敌方武器图案。
for($t=0x86;$t -le 0xA9;$t++){
    $u=$t+0x4A
    Copy-ChrTile 0xFC ($t-0x80) 0xFD ($u-0xC0)
    Copy-ChrTile 0xFC ($t-0x80) 0x13 ($u-0xC0)
}

# 原 $D0E5 的 JSR $F467 改回等价的 LDA #$04 / STA $15，释放 $F467 作为新帮助例程。
[Array]::Copy([byte[]](0xA9,0x04,0x85,0x15),0,$rom,0x7D0F5,4)

# 在统一 OAM tile 写入点 $D235 调用帮助例程，替代原 LDA $0E / STA $0201,X。
[Array]::Copy([byte[]](0x20,0x67,0xF4,0xEA,0xEA),0,$rom,0x7D245,5)

# X<$40 是 UI 保留槽，不处理；其余仅在 Y=$78-$EF 且 tile=$86-$A9 时加 $4A。
# 最后由本例程完成原来的 STA $0201,X。
$helper=[byte[]](
    0x8A,0xC9,0x40,0x90,0x1B,
    0xA5,0x12,0xC9,0x78,0x90,0x15,0xC9,0xF0,0xB0,0x11,
    0xA5,0x0E,0xC9,0x86,0x90,0x07,0xC9,0xAA,0xB0,0x03,
    0x18,0x69,0x4A,
    0x9D,0x01,0x02,0x60,
    0xA5,0x0E,0x4C,0x83,0xF4
)
[Array]::Copy($helper,0,$rom,0x7F477,$helper.Length)

[IO.File]::WriteAllBytes($target,$rom); [IO.File]::WriteAllBytes($reference,$rom)
Get-FileHash -Algorithm SHA256 -LiteralPath $target
