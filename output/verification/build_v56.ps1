$source = 'C:\Users\hu\Desktop\测试.nes'
$target = 'C:\Users\hu\Desktop\测试_敌方武器直接使用稳定图块组修复V56.nes'
$reference = 'D:\GIT\mmc3\output\verification\v56-rebuilt-from-test.nes'
$rom = [IO.File]::ReadAllBytes($source)

# 这五个对象定义的第 5 字节是动画指针低字节兼图块组标志。
# $C2 与 $42 的低 7 位相同，动画数据指针不变；只移除会把图块号 XOR $80 的敌方高组标志。
# 因而敌方武器仍执行完全相同的动画和坐标逻辑，但直接使用已经能跨 UI 正常显示的 $06-$29 图块组。
$markerOffsets = @(0x41536, 0x4153F, 0x41550, 0x4155A, 0x41564)
foreach ($offset in $markerOffsets) {
    if ($rom[$offset] -ne 0xC2) {
        throw ('Unexpected source byte at 0x{0:X}: expected C2, got {1:X2}' -f $offset, $rom[$offset])
    }
    $rom[$offset] = 0x42
}

[IO.File]::WriteAllBytes($target, $rom)
[IO.File]::WriteAllBytes($reference, $rom)
Get-FileHash -Algorithm SHA256 -LiteralPath $target
