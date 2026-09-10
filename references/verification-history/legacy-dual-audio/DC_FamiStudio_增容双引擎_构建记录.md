# DC.nes 增容双引擎构建记录

- 源 ROM SHA-256：`267CFA5E6273E0FE3557D5339B0E50172BCF25475283944C7E8372276FB3493C`
- 输出 ROM SHA-256：`223FDD6433C95B84D4566513FFC94C2B4121C3E4027A73FE841D13DB29BFF2E1`
- IPS SHA-256：`895A301DF94F7D59298EC7A97DAC78E0E32D6BC77CF6D5AF0DB091BB6B7D035B`
- Mapper：保持 194；仅将 PRG 从 512 KiB 扩展到 1 MiB。
- PRG：512 KiB → 1 MiB；CHR：保持 256 KiB。
- 除文件头偏移 `$04` 外，原文件 `$000010-$0C000F` 全部逐字节保持。
- 新增内容从原 EOF `$0C0010` 开始。
- 原20首音乐与56个音效仍由旧驱动播放。
- `$9D/$9E/$9F` 分别测试 Ash to Ash、Dark Knight、Dark Prison，未绑定游戏用途。
- 新曲播放期间的56个音效由第二套 FamiStudio SFX 播放。
- 保持 Mapper 194 后，原混合 CHR-ROM/CHR-RAM 和分屏 IRQ 映射无需转换。
- 目标模拟器：Mesen 0.9.9（已验证真实 1 MiB PRG 偏移）；FCEUX 2.6.6 会把 Mapper 194 固定回绕到 512 KiB，不兼容本增容版。
- FamiStudio 仅复用旧音频驱动专用的165字节 RAM；`$004C-$0056` 在每次更新前后入栈保护。
- 两套引擎不并发更新 APU；切回旧驱动时在同一 NMI 内完成复位和命令重放。
- IPS 扩容回放：通过。

运行时结果见 `build/DC_FamiStudio_增容双引擎_验证记录.md`。
