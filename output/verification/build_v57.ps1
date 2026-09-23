$source = 'C:\Users\hu\Desktop\测试.nes'
$target = 'C:\Users\hu\Desktop\测试_敌方武器原拼图跨UI显示修复V57.nes'
$reference = 'D:\GIT\mmc3\output\verification\v57-rebuilt-from-test.nes'
$rom = [IO.File]::ReadAllBytes($source)
$chrBase = 0x80010

# 敌方武器原 tile $86-$A9 位于 sprite R1 的 FC 页。
# 目标 tile $46-$69 位于上下分屏共同使用的 sprite R0 后半页 FD；
# 两组 tile 在各自 1 KiB 页中的局部索引同为 $06-$29。
[Array]::Copy($rom, $chrBase + 0xFC * 0x400 + 0x60,
              $rom, $chrBase + 0xFD * 0x400 + 0x60, 0x240)

# 原 $D0E5: JSR $F467 / NOP，而 $F467 只执行 LDA #$04 / STA $15 / RTS。
# 先等价内联，释放 $F467 给下面的跳板使用，同时还抵消一部分新增周期。
[Array]::Copy([byte[]](0xA9, 0x04, 0x85, 0x15), 0, $rom, 0x7D0F5, 4)

# 原逻辑：AND #$80 / STA $1E / LDA $0730,X。
# 改为无栈跳板；只把对象标记恰为 $C2 的敌方武器掩码改成 $40，
# 其它对象继续使用原来的 $00/$80。返回时 A 仍等于 $0730,X。
$expected = [byte[]](0x29, 0x80, 0x85, 0x1E, 0xBD, 0x30, 0x07)
for ($i = 0; $i -lt $expected.Length; $i++) {
    if ($rom[0x7D1E5 + $i] -ne $expected[$i]) {
        throw ('Unexpected source byte at 0x{0:X}: expected {1:X2}, got {2:X2}' -f
            (0x7D1E5 + $i), $expected[$i], $rom[0x7D1E5 + $i])
    }
}
[Array]::Copy([byte[]](0x4C, 0x67, 0xF4, 0xEA, 0xEA, 0xEA, 0xEA),
              0, $rom, 0x7D1E5, 7)

$helper = [byte[]](
    0xC9, 0xC2,             # CMP #$C2
    0xF0, 0x05,             # BEQ weapon
    0x29, 0x80,             # normal: AND #$80
    0x4C, 0x72, 0xF4,       # JMP store
    0xA9, 0x40,             # weapon: LDA #$40
    0x85, 0x1E,             # store: STA $1E
    0xBD, 0x30, 0x07,       # LDA $0730,X
    0x4C, 0xDC, 0xD1        # JMP $D1DC
)
[Array]::Copy($helper, 0, $rom, 0x7F477, $helper.Length)

[IO.File]::WriteAllBytes($target, $rom)
[IO.File]::WriteAllBytes($reference, $rom)
Get-FileHash -Algorithm SHA256 -LiteralPath $target
