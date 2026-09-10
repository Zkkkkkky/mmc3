# DC.nes 增容双引擎验证记录

## 构建对象

- 源 ROM：`build/nsf/新DC.nes`
- 源 SHA-256：`267CFA5E6273E0FE3557D5339B0E50172BCF25475283944C7E8372276FB3493C`
- 测试 ROM：`build/DC_FamiStudio_增容双引擎_测试.nes`
- 测试 ROM SHA-256：`223FDD6433C95B84D4566513FFC94C2B4121C3E4027A73FE841D13DB29BFF2E1`
- IPS SHA-256：`895A301DF94F7D59298EC7A97DAC78E0E32D6BC77CF6D5AF0DB091BB6B7D035B`
- 文件大小：786448 → 1310736 字节；增加 524288 字节。

## 原数据保护

- iNES 文件头只有偏移 `$04` 从 `$20` 改为 `$40`，表示 PRG 从 512 KiB 扩展为 1 MiB。
- 源文件正文 `$000010-$0C000F` 在输出 ROM 的相同文件偏移逐字节完全一致。
- 原 PRG Bank `$00-$3F` 无修改。
- 原 CHR 在旧文件偏移处保留，同时在新的有效 CHR 区 `$100010-$14000F` 追加一份逐字节相同的副本。
- 所有新增代码和数据都从源 ROM 的 EOF `$0C0010` 开始；没有利用原 ROM 内的空字节。
- IPS 从源 ROM 回放后与测试 ROM 完全一致。

## 音频布局和 RAM

- 原 20 首曲目和原 56 个音效仍由旧驱动播放。
- Ash to Ash、Dark Knight、Dark Prison 与迁移后的 56 个 FamiStudio SFX 使用第二套引擎，测试命令为 `$9D/$9E/$9F`，未绑定游戏用途。
- 第二套引擎只复用旧音频驱动拥有的 165 字节 RAM：`$0028-$005D`（不含 `$002C`）和 `$0400-$046F`。
- `$004C-$0056` 是游戏音频接口兼 FamiStudio 临时输出区；每次更新前后均完整入栈、出栈保护。
- 桥接状态位于 `$0468-$046B`。两套引擎不在同一帧共同更新 APU；切回旧曲时同帧完成旧驱动复位和待处理命令重放。
- 构建器逐符号核对 RAM 地址、跨度和重叠，并确认占用集合恰好等于上述 165 字节。

## Mesen 0.9.9 运行时验证

- 自动检查：17/17 通过，共 11309 帧，退出码 0。
- 三首新曲分别连续保持约 3600 帧；FamiStudio 共更新 10993 次。
- APU `$4000-$4013` 写入 101960 次。
- 56/56 个迁移音效入口均被调用。
- 新曲切回原曲命令 `$89` 后，旧驱动在同一 NMI 内复位并开始处理原曲；原驱动调用增量为 9。
- 所有高扩展银行均命中真实 1 MiB PRG 偏移：固定 Bank、复制的旧音频 Bank、新引擎 Bank 和三首新曲 Bank 均无错误回绕。
- 为单独验证每首曲子的持续运行，三个 3600 帧窗口只屏蔽游戏标题流程自行发出的旧曲切换命令；新曲切换、56 个正值音效命令以及最后显式切回旧驱动均未被屏蔽。
- 原始运行日志：`analysis/dc_mesen_dual_audio_final.log`。

## 画面和自动测试

- 源 ROM 与测试 ROM 的第 675 帧 PNG 均为 4736 字节，SHA-256 同为 `B315051DA2C1CF8CD0AF743879F52CB5D95E54AF07EA5921600312A423D936A3`，文件逐字节相同。
- `python tools/test_dc_expanded_dual_audio.py`：10/10 通过。
- `python -m unittest discover -s tools -p 'test_*.py'`：108 项通过，10 项按环境条件跳过。
- `python -m py_compile tools/build_dc_expanded_dual_audio.py tools/test_dc_expanded_dual_audio.py`：通过。

## 兼容性

- 已验证模拟器：Mesen 0.9.9。
- FCEUX 2.6.6 的 Mapper 194 实现把 PRG 固定为 512 KiB，高扩展 Bank 会回绕，因此不能运行这个 1 MiB PRG 测试版。
- 保持 Mapper 194 是为了保留源 ROM 的混合 CHR-ROM/CHR-RAM 行为；最终测试应使用能按 iNES PRG 容量处理 Mapper 194 的模拟器或烧录环境。
