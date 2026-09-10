# DC 双音频 464 KiB 资源版验证记录

## 验证对象

- ROM：`build/DC_FamiStudio_增容双引擎_464K_测试.nes`
- ROM SHA-256：`82C218275459D53C0F306F6BC036C4797316976E0FA7AD1D5A8247E338995B8E`
- IPS SHA-256：`EFAEDAF6E474CDE676ECEC2AC119F5C5EB1C4B01C851A5C997FFBD01218DF823`
- 修改器 EXE：`FC模拟器/新DC篇完整修改器.exe`，SHA-256 `194003ED1DB185F503DF76E878DBB47C112973C9CCE7CDEB468F06E4C939299B`

## 静态与修改器验证

- 构建器核对源 ROM 的大小、Mapper 和 SHA-256，源 ROM 与旧版 `DC_kuorong.nes` 均未覆盖。
- Bank `$40-$60` 与 `$65-$7D` 全零，共 475136 字节（464 KiB）。
- Bank `$61-$64/$7E-$7F` 受保护；原 CHR 仅保留文件末尾的有效副本。
- Bank `$18` 只在已验证空洞中加入 53 字节跳板，桥接器恢复映射明确为 `$18`。
- Python `unittest` 完整发现 64/64 通过，覆盖双版本识别、资源分配/回收、撤销/重做、工程回放、非法裸写拦截和离屏 GUI。
- PyInstaller 独立 EXE 构建后通过 `--self-test` 主窗口自检。

## Mesen 0.9.9 运行时验证

- 自动断言 17/17 通过，共运行 11309 帧，失败数 0。
- Ash to Ash、Dark Knight、Dark Prison 分别持续约 3600 帧，三曲 Bank 均命中正确的 1 MiB PRG 偏移。
- FamiStudio 更新 10993 次，APU `$4000-$4013` 写入 101960 次。
- 56/56 个迁移音效入口全部调用；最后显式切回旧曲 `$89` 成功。
- 旧音频 Bank `$18` 命中 310 次，双引擎桥接命中 11302 次，错误 Bank 命中均为 0。

原始逐项日志保存在 `analysis/dc_mesen_dual_audio_464K.log`，SHA-256 为 `91B9BA4188F2B4AF1F7EE8D8F4F4BB46D077217D1389B0777B8A4A9224729531`。由于 Mesen 0.9.9 的 Lua 文件 I/O 不兼容中文路径，测试从纯 ASCII 临时目录运行；ROM 和 Lua 在运行前后均按哈希核对，日志随后复制回本目录。

## 边界

自动测试能确认 ROM 布局、Bank 映射、播放生命周期和修改器工程一致性，不能替代人工听感或真实 Mapper 194 烧录卡验证。FCEUX 2.6.6 会把高位 PRG Bank 回绕到 512 KiB，不用于本版验收。
