# DC.nes 增容双引擎构建记录

- 源 ROM SHA-256：`267CFA5E6273E0FE3557D5339B0E50172BCF25475283944C7E8372276FB3493C`
- 输出 ROM SHA-256：`82C218275459D53C0F306F6BC036C4797316976E0FA7AD1D5A8247E338995B8E`
- IPS SHA-256：`EFAEDAF6E474CDE676ECEC2AC119F5C5EB1C4B01C851A5C997FFBD01218DF823`
- Mapper：保持 194；仅将 PRG 从 512 KiB 扩展到 1 MiB。
- PRG：512 KiB → 1 MiB；CHR：保持 256 KiB。
- 源 ROM 不覆盖；派生输出释放 `$40-$60` 与 `$65-$7D` 共 464 KiB。
- 原 CHR 旧位置副本清零；有效 CHR 仍位于 `$100010-$14000F`。
- 旧音频调度代码写入原 Bank `$18` 的已验证空白区，不再复制 Bank `$60`。
- 原20首音乐与56个音效仍由旧驱动播放。
- `$9D/$9E/$9F` 分别对应 Ash to Ash、Dark Knight、Dark Prison；保留当前基准中的人物战斗曲绑定。
- 新曲播放期间的56个音效由第二套 FamiStudio SFX 播放。
- 保持 Mapper 194 后，原混合 CHR-ROM/CHR-RAM 和分屏 IRQ 映射无需转换。
- 目标模拟器：Mesen 0.9.9（已验证真实 1 MiB PRG 偏移）；FCEUX 2.6.6 会把 Mapper 194 固定回绕到 512 KiB，不兼容本增容版。
- FamiStudio 仅复用旧音频驱动专用的165字节 RAM；`$004C-$0056` 在每次更新前后入栈保护。
- 两套引擎不并发更新 APU；切回旧驱动时在同一 NMI 内完成复位和命令重放。
- IPS 扩容回放：通过。

运行时结果见 `output/reports/rom-build/DC_FamiStudio_增容双引擎_464K_验证记录.md`。
