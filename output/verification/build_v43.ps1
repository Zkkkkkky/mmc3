$source = 'C:\Users\hu\Downloads\测试.nes'
$target = 'C:\Users\hu\Downloads\测试_武器跨UI图块复制修复V43.nes'
$reference = 'D:\GIT\mmc3\output\verification\v43-rebuilt-from-test.nes'
$rom = [IO.File]::ReadAllBytes($source)
$chrBase = 0x80010

function Copy-ChrTile([int]$sourceBank, [int]$sourceLocalTile, [int]$targetBank, [int]$targetLocalTile) {
    $sourceOffset = $chrBase + $sourceBank * 0x400 + $sourceLocalTile * 16
    $targetOffset = $chrBase + $targetBank * 0x400 + $targetLocalTile * 16
    [Array]::Copy($rom, $sourceOffset, $rom, $targetOffset, 16)
}

# 紫色环形武器：顶层 R2=$A2，tile $06-$29。
# 复制为 tile $B9-$DC；分别落入 R4 的 $39-$3F 和 R5 的 $00-$1C。
for ($tile = 0x06; $tile -le 0x29; $tile++) {
    $targetTile = $tile + 0xB3
    if ($targetTile -lt 0xC0) {
        foreach ($bank in @(0xB7, 0x02)) {
            Copy-ChrTile 0xA2 $tile $bank ($targetTile - 0x80)
        }
    } else {
        foreach ($bank in @(0xBD, 0x14, 0x53)) {
            Copy-ChrTile 0xA2 $tile $bank ($targetTile - 0xC0)
        }
    }
}

# 冰刃：顶层 R3=$35，tile $61-$6A（R3 内局部 tile $21-$2A）。
# 复制为 tile $DD-$E6，落入 R5 的 $1D-$26。
for ($tile = 0x61; $tile -le 0x6A; $tile++) {
    $targetTile = $tile + 0x7C
    foreach ($bank in @(0x06, 0xBD, 0x14, 0x53)) {
        Copy-ChrTile 0x35 ($tile - 0x40) $bank ($targetTile - 0xC0)
    }
}

# 恢复原入口；跨界处理放到最终 OAM 生成之后。
[Array]::Copy([byte[]](0xA9,0x04,0x85,0x15), 0, $rom, 0x7D0F5, 4)

# 扫描战斗 OAM $0240-$02FF，只重编号 Y=$78-$EF 的两类武器 tile。
$routine = [byte[]](
    0xA2,0x40,
    0xBD,0x00,0x02,0xC9,0x78,0x90,0x25,0xC9,0xF0,0xB0,0x21,
    0xBD,0x01,0x02,0xC9,0x06,0x90,0x0C,0xC9,0x2A,0xB0,0x08,
    0x18,0x69,0xB3,0x9D,0x01,0x02,0xD0,0x0E,
    0xC9,0x61,0x90,0x0A,0xC9,0x6B,0xB0,0x06,
    0x18,0x69,0x7C,0x9D,0x01,0x02,
    0xE8,0xE8,0xE8,0xE8,0xD0,0xCE,0x60
)
[Array]::Copy($routine, 0, $rom, 0x7F477, $routine.Length)

# 只保存/恢复 X；例程不使用 Y。保持原调用点的 LDA $73 / SEC 约定。
$wrapper = [byte[]](0x8A,0x48,0x20,0x67,0xF4,0x68,0xAA,0xA5,0x73,0x38,0x60)
[Array]::Copy($wrapper, 0, $rom, 0x7F521, $wrapper.Length)
[Array]::Copy([byte[]](0x20,0x11,0xF5), 0, $rom, 0x7FB2C, 3)

[IO.File]::WriteAllBytes($target, $rom)
[IO.File]::WriteAllBytes($reference, $rom)
Get-FileHash -Algorithm SHA256 -LiteralPath $target
