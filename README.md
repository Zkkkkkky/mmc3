# 新DC篇完整修改器

面向 FC《第二次机器人大战》新 DC 篇扩容 ROM 的 Windows 桌面编辑器。项目提供可视化数据编辑、扩展 Bank 管理、可重放工程、ROM/IPS 构建以及结构校验。

![新DC篇完整修改器主界面](docs/images/dc_modifier/01-map-editor.png)

> `references/legacy_modifier/SRW2_patched.exe` 仅用于研究旧修改器的操作动线和已知数据，不是当前产品。当前修改器源码位于 `src/dc_modifier/`、`src/fc_editor/` 与 `src/fc_rom_editor_core.py`。

## 快速开始

仓库包含 Windows 交付版：

1. 双击 `启动DC修改器.bat`，或直接运行 `output/app/新DC篇完整修改器.exe`。
2. 在精简启动页点击“进入修改器”。
3. 按 `Ctrl+O` 打开推荐 ROM：`output/rom/DC_kuorong_464K.nes`。
4. 完成编辑后按 `F7` 运行完整检查。
5. 保存 `.dcmod` 工程，或输出新的 `.nes`/`.ips`。不要覆盖 `references/` 中的任何 ROM。

完整操作步骤、快捷键和截图见 [《DC修改器使用说明》](docs/DC修改器使用说明.md)。

## 当前能力

- 编辑机体、人物、武器、地图、部署、地图触发点和剧情文本。
- 结构化编辑已验证的章节事件与 4 条劝降规则。
- 修改双方战斗音乐，并向 `$9D`、`$9E`、`$9F` 三个 8 KiB 扩展槽导入音乐 Bank。
- 编辑活动 CHR 图块，导入或导出 `.dcunit` 机体包。
- 为地图、机体和剧情分配 464 KiB 托管扩展空间，并保护运行时和音乐 Bank。
- 保存 `.dcmod` 可重放工程，支持撤销/重做、派生 ROM、IPS 和 JSON 构建报告。
- 对未完成地址或语义验证的字体写入、地图动画、存档写入及部分全局参数保持只读。

## ROM 输入与推荐输出

| 用途 | 路径 | 大小 | SHA-256 | 托管空间 |
|---|---|---:|---|---:|
| 推荐运行与编辑 ROM | `output/rom/DC_kuorong_464K.nes` | 1,310,736 字节 | `82C218275459D53C0F306F6BC036C4797316976E0FA7AD1D5A8247E338995B8E` | 464 KiB |
| 旧布局基线（只读） | `references/rom/baselines/DC_kuorong.nes` | 1,310,736 字节 | `1DDD4F74B2D3ACEAA8A0BC4A6846BE8E6148C858C2D8EA5A1F6E0A04F0AD4A75` | 200 KiB |
| 构建源（只读） | `references/rom/source/新DC.nes` | 786,448 字节 | `267CFA5E6273E0FE3557D5339B0E50172BCF25475283944C7E8372276FB3493C` | - |

推荐 ROM 使用 Mapper 194，包含 1 MiB PRG 与 256 KiB CHR。修改器会验证 iNES 头、Mapper、基线身份和受保护 Bank，拒绝未知布局、无效身份或损坏的受保护签名；由修改器生成且带有有效自动容量表的派生 ROM 可以继续载入编辑。

`references/rom/source/新DC.nes` 只供构建器读取，不能由 GUI 打开或作为输出目标。`references/` 中的基线、旧修改器、研究资料和音频素材均视为只读；所有派生文件写入 `output/`。

## 技术架构

项目是离线桌面应用，不依赖数据库或 Web 后端：

| 层级 | 实现 |
|---|---|
| 桌面界面 | Python、PySide6 / Qt 6；源码位于 `src/dc_modifier/` |
| 编辑会话 | `src/fc_rom_editor_core.py`，负责事务、撤销/重做、验证和构建编排 |
| ROM 模型 | `src/fc_editor/`，负责 Profile、Bank/指针、编解码、资源分配和格式校验 |
| 汇编与资源 | `src/asm/` 保存 6502/ASM6 源码，`src/resources/default_config/` 保存映射导出配置 |
| 音乐导入 | FamiStudio ASM6 导出 + `tools/vendor/famistudio-4.5.3/Tools/asm6_fixed.exe` |
| Windows 发布 | PyInstaller 单文件无控制台 EXE |
| 自动测试 | `tests/` 下的标准库 `unittest`、Qt offscreen GUI 测试与 `py65` 6502 验证 |

工程文件 `.dcmod` 使用 JSON；机体包 `.dcunit` 使用 ZIP；最终可生成 `.nes`、`.ips` 和 `.build-report.json`。

## 目录结构

仓库采用“核心五目录 + 独立参考输入”的布局：

```text
扩容MMC3/
├─ src/                            产品源码与运行资源
│  ├─ dc_modifier/                 当前修改器 GUI
│  ├─ fc_editor/                   ROM 模型、编解码与资源系统
│  ├─ fc_rom_editor_core.py        编辑会话与构建编排
│  ├─ asm/                         6502/ASM6 源码
│  └─ resources/default_config/    当前修改器默认配置
├─ tools/                          启动、构建、打包、清单与研究脚本
│  ├─ run_dc_modifier.py           源码启动入口
│  ├─ build_dc_expanded_dual_audio.py
│  ├─ build_modifier_exe.ps1
│  ├─ 更新文件清单.ps1
│  ├─ 验证交接包.ps1
│  └─ vendor/
│     ├─ famistudio-4.5.3/
│     ├─ fceux-2.6.6/
│     └─ mesen-0.9.9/
├─ tests/                          单元、集成、GUI 与模拟器检查
│  └─ emulator/                    Mesen/Lua 冒烟脚本
├─ output/                         所有可再生成或交付的产物
│  ├─ app/                         Windows 修改器与随附映射表
│  ├─ rom/                         构建出的 ROM
│  ├─ patches/                     IPS 补丁
│  ├─ reports/                     构建及验证报告
│  ├─ mappings/                    导出的映射表
│  ├─ pdf/                         生成的 PDF 手册
│  ├─ exports/                     GUI“另存为”与资源导出的默认目录
│  ├─ build/                       汇编与 PyInstaller 中间产物
│  ├─ verification/                自动计划与模拟器验证产物
│  └─ manifest/                    SHA-256 交接清单
├─ docs/                           使用、设计、交接、研究和历史文档
│  ├─ DC修改器使用说明.md
│  ├─ DC修改器设计与实现方案.md
│  ├─ 交接文档.md
│  ├─ 提交记录.md
│  ├─ research/
│  ├─ images/dc_modifier/
│  └─ archive/
└─ references/                     只读原始输入与历史参考
   ├─ rom/source/新DC.nes
   ├─ rom/baselines/DC_kuorong.nes
   ├─ legacy_modifier/
   ├─ audio/
   ├─ emulator-state/
   ├─ verification-history/
   └─ research/
```

`src/` 是正式 Python 源码布局，`pyproject.toml` 定义包发现和 `fc_rom_editor_core` 模块；入口、构建器及维护脚本保留在 `tools/`，测试统一由 `tests/` 发现。

## 源码运行

当前开发流程在 Windows PowerShell 上运行。先准备环境：

```powershell
py -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements-modifier.txt
```

然后从仓库根目录启动：

```powershell
.\.venv\Scripts\python.exe tools\run_dc_modifier.py
```

如需运行完整测试、6502 验证、生成 PDF 或打包 EXE，再安装开发依赖：

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements-dev.txt
```

也可通过 `pyproject.toml` 以可编辑方式安装：

```powershell
.\.venv\Scripts\python.exe -m pip install -e .
```

## 构建与验证

从仓库根目录执行：

```powershell
# 重建扩容 ROM、IPS 与报告
python tools\build_dc_expanded_dual_audio.py

# 核心、集成与 GUI 完整测试
.\.venv\Scripts\python.exe -m unittest discover -s tests -t . -p "test_*.py"

# 构建 Windows 单文件修改器
.\tools\build_modifier_exe.ps1

# 更新并验证 output/manifest 下的交接包哈希
.\tools\更新文件清单.ps1
.\tools\验证交接包.ps1
```

当前迁移后的完整套件为 184 项测试，包含核心、集成、离屏 GUI、6502 运行片段及只读输出边界检查。

ROM 布局或音频行为发生变化时，还必须执行 [《交接文档》](docs/交接文档.md) 中对应的 Mesen/Lua 冒烟检查。Mesen 0.9.9 位于 `tools/vendor/mesen-0.9.9/`，脚本位于 `tests/emulator/`，验证产物写入 `output/verification/`。

## 文档索引

- [使用说明](docs/DC修改器使用说明.md)：面向修改器使用者的完整操作手册。
- [设计与实现方案](docs/DC修改器设计与实现方案.md)：分层架构、已实现能力和扩展边界。
- [交接文档](docs/交接文档.md)：ROM Bank、音频实现、基线哈希和运行时验证。
- [提交记录](docs/提交记录.md)：历史改动及验证命令。
- [资料集阅读笔记](docs/research/FC第二次机器人大战资料集V1.16_阅读笔记.md)：历史逆向线索；使用前仍需对当前 ROM 复核。
- [参考输入边界](references/README.md)：只读素材的分类和使用规则。
- [仓库协作约束](AGENTS.md)：代码风格、测试和交付要求。

## 已知限制

- FCEUX 2.6.6 会使 Mapper 194 的高位 PRG Bank 回绕，不适合验证本项目；当前使用 Mesen 0.9.9。
- 尚未完成真实卡带或烧录卡验证。
- 章节事件仅允许等长兼容替换，不能任意插入、删除或重排。
- 劝降编辑仅开放 4 条已验证规则。
- `$9D`、`$9E`、`$9F` 每槽固定占用一个 8 KiB Bank；输出后仍需在模拟器中试听。
- `references/rom/source/新DC.nes` 是只读源素材，禁止原地修改。

对外发布时优先提供源码、报告和 IPS 补丁，不要公开分发可能受版权保护的 ROM。
