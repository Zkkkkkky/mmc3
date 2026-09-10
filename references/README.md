# 只读参考输入

`references/` 独立于 `src/`、`tools/`、`tests/`、`output/` 和 `docs/`，保存构建输入、历史基线与逆向证据。这里的内容原则上只读：不要原地修改、覆盖或把生成结果写回本目录。

## ROM

- `rom/source/新DC.nes`：构建器使用的唯一只读源 ROM，大小 786,448 字节，SHA-256 为 `267CFA5E6273E0FE3557D5339B0E50172BCF25475283944C7E8372276FB3493C`。
- `rom/baselines/DC_kuorong.nes`：兼容旧布局的只读基线，大小 1,310,736 字节，SHA-256 为 `1DDD4F74B2D3ACEAA8A0BC4A6846BE8E6148C858C2D8EA5A1F6E0A04F0AD4A75`。

推荐运行和编辑的派生 ROM 不在这里，而是 `../output/rom/DC_kuorong_464K.nes`。ROM 构建器必须读取 `rom/source/新DC.nes`，并把 ROM、IPS、报告及中间文件分别写到 `output/rom/`、`output/patches/`、`output/reports/` 和 `output/build/`。

## 其他参考资料

- `legacy_modifier/`：旧版 `SRW2_patched.exe`、配套配置、历史编辑样本和截图，用于核对界面、操作动线及逆向线索。它不是“新DC篇完整修改器”的源码或运行依赖。
- `audio/`：NSF、FamiStudio 工程、替代实验和原音效导入记录等历史音频输入。
- `emulator-state/`：历史 FCEUX 存档及状态，用于复核既有实验，不作为当前输出目录。
- `research/`：资料集 CHM 的提取内容和旧修改器界面证据。先阅读 `../docs/research/FC第二次机器人大战资料集V1.16_阅读笔记.md`，再按需查阅。
- `verification-history/`：迁移前的构建、容量与运行验证记录；保留原始路径和当时的测试口径，仅作为历史证据。

从参考资料得到的地址、字段和行为结论，必须重新对当前 ROM、构建器断言及模拟器结果验证。当前第三方可执行工具不放在本目录；FamiStudio 4.5.3、FCEUX 2.6.6 与 Mesen 0.9.9 分别位于 `../tools/vendor/famistudio-4.5.3/`、`../tools/vendor/fceux-2.6.6/` 和 `../tools/vendor/mesen-0.9.9/`。
