$source = 'C:\Users\hu\Desktop\测试.nes'
$target = 'C:\Users\hu\Desktop\测试_敌方武器8x16完整重映射修复V55.nes'
$reference = 'D:\GIT\mmc3\output\verification\v55-rebuilt-from-test.nes'
$rom = [IO.File]::ReadAllBytes($source)
$chrBase = 0x80010

function Copy-ChrBytes([int]$sourceBank, [int]$sourceOffset, [int]$targetBank, [int]$targetOffset, [int]$length) {
    [Array]::Copy(
        $rom,
        $chrBase + $sourceBank * 0x400 + $sourceOffset,
        $rom,
        $chrBase + $targetBank * 0x400 + $targetOffset,
        $length
    )
}

# 8x16 精灵中，偶数图块号从 PPU $0000 表取一对图块，奇数图块号从 $1000 表取一对图块。
# 敌方武器原编号为 $86-$A9；改号后为 original XOR $70。
# 偶数路：顶部 R4/BB -> 目标 R5/BF，并复制到下方 UI 使用的 R5/12。
# 奇数路：顶部 R1/FC -> 目标 R1 后半/FD，并复制到下方 UI 使用的 R1 后半/13。
for ($baseTile = 0x86; $baseTile -le 0xA8; $baseTile += 2) {
    $targetBase = $baseTile -bxor 0x70
    $sourceOffset = ($baseTile - 0x80) * 16
    $targetOffset = ($targetBase - 0xC0) * 16

    Copy-ChrBytes 0xBB $sourceOffset 0xBF $targetOffset 32
    Copy-ChrBytes 0xBB $sourceOffset 0x12 $targetOffset 32
    Copy-ChrBytes 0xFC $sourceOffset 0xFD $targetOffset 32
    Copy-ChrBytes 0xFC $sourceOffset 0x13 $targetOffset 32
}

# 恢复被早期试验占用的原逻辑，再在对象初始化点调用专用掩码选择函数。
[Array]::Copy([byte[]](0xA9, 0x04, 0x85, 0x15), 0, $rom, 0x7D0F5, 4)
[Array]::Copy([byte[]](0x20, 0x67, 0xF4, 0xEA, 0xEA), 0, $rom, 0x7D1E7, 5)

# 只对动画指针低字节为 $C2 的敌方武器对象，把原 XOR $80 改为 XOR $F0。
# 机体对象 $C1、光标、头像及 UI 精灵保持原编号。
$helper = [byte[]](
    0x85, 0x1E, 0xF0, 0x0B,
    0xBD, 0x40, 0x07, 0xC9, 0xC2, 0xD0, 0x04,
    0xA9, 0xF0, 0x85, 0x1E,
    0xBD, 0x30, 0x07, 0x60
)
[Array]::Copy($helper, 0, $rom, 0x7F477, $helper.Length)

[IO.File]::WriteAllBytes($target, $rom)
[IO.File]::WriteAllBytes($reference, $rom)
Get-FileHash -Algorithm SHA256 -LiteralPath $target
