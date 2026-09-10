# 新DC篇完整修改器

面向 FC《第二次机器人大战》新 DC 篇扩容 ROM 的 Windows 桌面编辑器。项目提供可视化数据编辑、扩展 Bank 管理、可重放工程、ROM/IPS 构建以及结构校验。

![新DC篇完整修改器主界面](docs/images/dc_modifier/01-map-editor.png)

> `references/legacy_modifier/SRW2_patched.exe` 仅用于研究旧修改器的操作动线和已知数据，不是当前产品。当前修改器源码位于 `tools/dc_modifier/` 与 `tools/fc_editor/`。

## 快速开始

仓库已经包含 Windows 交付版：

1. 双击 `启动DC修改器.bat`，或直接运行 `FC模拟器/新DC篇完整修改器.exe`。
2. 在精简启动页点击“进入修改器”。
3. 按 `Ctrl+O` 打开 `FC模拟器/DC_kuorong_464K.nes`。
4. 完成编辑后按 `F7` 运行完整检查。
5. 保存 `.dcmod` 工程，或输出新的 `.nes`/`.ips`。不要覆盖基线 ROM。

完整操作步骤、快捷键和截图见 [《DC修改器使用说明》](DC修改器使用说明.md)。

## 当前能力

- 编辑机体、人物、武器、地图、部署、地图触发点和剧情文本。
- 结构化编辑已验证的章节事件与 4 条劝降规则。
- 修改双方战斗音乐，并向 `$9D`、`$9E`、`$9F` 三个 8 KiB 扩展槽导入音乐 Bank。
- 编辑活动 CHR 图块，导入或导出 `.dcunit` 机体包。
- 为地图、机体和剧情分配 464 KiB 托管扩展空间，并保护运行时和音乐 Bank。
- 保存 `.dcmod` 可重放工程，支持撤销/重做、派生 ROM、IPS 和 JSON 构建报告。
- 对未完成地址或语义验证的字体写入、地图动画、存档写入及部分全局参数保持只读。

## ROM 基线与构建源

| 用途 | 路径 | 大小 | SHA-256 | 托管空间 |
|---|---|---:|---|---:|
| 推荐基线 | `FC模拟器/DC_kuorong_464K.nes` | 1,310,736 字节 | `82C218275459D53C0F306F6BC036C4797316976E0FA7AD1D5A8247E338995B8E` | 464 KiB |
| 兼容旧布局 | `FC模拟器/DC_kuorong.nes` | 1,310,736 字节 | `1DDD4F74B2D3ACEAA8A0BC4A6846BE8E6148C858C2D8EA5A1F6E0A04F0AD4A75` | 200 KiB |
| 只读构建源 | `build/nsf/新DC.nes` | 786,448 字节 | `267CFA5E6273E0FE3557D5339B0E50172BCF25475283944C7E8372276FB3493C` | - |

推荐基线使用 Mapper 194，包含 1 MiB PRG 与 256 KiB CHR。修改器会验证 iNES 头、Mapper、基线身份和受保护 Bank，拒绝未知布局、无效身份或损坏的受保护签名；由修改器生成且带有有效自动容量表的派生 ROM 可以继续载入编辑。`build/nsf/新DC.nes` 只供构建器读取，不能由 GUI 打开或作为输出目标。

## 技术架构

项目是离线桌面应用，不依赖数据库或 Web 后端：

| 层级 | 实现 |
|---|---|
| 桌面界面 | Python、PySide6 / Qt 6 |
| 编辑会话 | `tools/fc_rom_editor_core.py`，负责事务、撤销/重做、验证和构建编排 |
| ROM 模型 | `tools/fc_editor/`，负责 Profile、Bank/指针、编解码、资源分配和格式校验 |
| 界面模块 | `tools/dc_modifier/`，负责地图、数据、事件、CHR、音乐和工程窗口 |
| 音乐导入 | FamiStudio ASM6 导出 + 随项目打包的 `asm6_fixed.exe` |
| Windows 发布 | PyInstaller 单文件无控制台 EXE |
| 自动测试 | 标准库 `unittest` + Qt offscreen GUI 测试 + `py65` 6502 执行验证 |

工程文件 `.dcmod` 使用 JSON；机体包 `.dcunit` 使用 ZIP；最终可生成 `.nes`、`.ips` 和 `.build-report.json`。

## 目录结构

```text
扩容MMC3/
├─ README.md                       项目入口
├─ DC修改器使用说明.md             用户操作手册
├─ 交接文档.md                     ROM、音频与验证边界
├─ tools/
│  ├─ dc_modifier/                 当前修改器 GUI
│  ├─ fc_editor/                   ROM 模型、编解码与资源系统
│  ├─ fc_rom_editor_core.py        编辑会话与构建编排
│  ├─ build_*.py                   ROM/文档构建工具
│  └─ test_*.py                    unittest 与离屏 GUI 测试
├─ analysis/                       6502/ASM6、反汇编、Lua 和验证证据
├─ build/                          ROM、报告、NSF 输入与生成映射表
├─ patches/                        可分发 IPS
├─ docs/
│  ├─ README.md                    文档索引
│  ├─ DC修改器设计与实现方案.md   架构设计
│  ├─ 提交记录.md                  开发与验证记录
│  ├─ images/dc_modifier/          使用说明截图
│  └─ archive/                     被淘汰方案，仅供参考
├─ output/pdf/                     生成的 PDF 使用说明
├─ references/
│  ├─ README.md                    参考资料边界
│  └─ legacy_modifier/             旧修改器和配置快照，只读参考
├─ 默认配置文件/                  映射表的生成输入
├─ FC模拟器/                       当前 EXE、兼容基线和本地运行包
└─ 验证工具/                       Mesen 等已验证工具
```

`tools/` 目前也是 Python 的导入根和 `unittest` 的发现根，因此应用包、脚本和测试暂时保持在同一目录。若后续迁移到标准 `src/`/`tests/` 布局，应同时引入正式打包配置，并一次性调整启动器、测试发现和 PyInstaller 路径。

## 源码运行

当前开发流程在 Windows PowerShell 和 Python 3.14 上验证：

```powershell
py -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements-modifier.txt
.\.venv\Scripts\python.exe tools\run_dc_modifier.py
```

如需运行完整测试、6502 验证或生成 PDF，安装开发依赖：

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements-dev.txt
```

## 构建与验证

从仓库根目录执行：

```powershell
# 重建扩容 ROM、IPS 与报告
python tools\build_dc_expanded_dual_audio.py

# ROM 构建专项测试
python tools\test_dc_expanded_dual_audio.py

# 核心与 GUI 完整测试
.\.venv\Scripts\python.exe -m unittest discover -s tools -p "test_*.py"

# 构建 Windows 单文件修改器
.\build_modifier_exe.ps1

# 更新并验证交接包哈希
.\更新文件清单.ps1
.\验证交接包.ps1
```

当前完整测试套件包含 182 项。ROM 布局或音频行为发生变化时，还必须执行 [交接文档](交接文档.md) 中对应的 Mesen/Lua 冒烟检查。

## 文档索引

- [使用说明](DC修改器使用说明.md)：面向修改器使用者的完整操作手册。
- [设计与实现方案](docs/DC修改器设计与实现方案.md)：分层架构、已实现能力和扩展边界。
- [交接文档](交接文档.md)：ROM Bank、音频实现、基线哈希和运行时验证。
- [提交记录](docs/提交记录.md)：历史改动及验证命令。
- [资料集阅读笔记](analysis/FC第二次机器人大战资料集V1.16_阅读笔记.md)：历史逆向线索；使用前仍需对当前 ROM 复核。
- [仓库协作约束](AGENTS.md)：代码风格、测试和交付要求。

## 已知限制

- FCEUX 2.6.6 会使 Mapper 194 的高位 PRG Bank 回绕，不适合验证本项目；当前使用 Mesen 0.9.9。
- 尚未完成真实卡带或烧录卡验证。
- 章节事件仅允许等长兼容替换，不能任意插入、删除或重排。
- 劝降编辑仅开放 4 条已验证规则。
- `$9D`、`$9E`、`$9F` 每槽固定占用一个 8 KiB Bank；输出后仍需在模拟器中试听。
- `build/nsf/新DC.nes` 是只读源素材，禁止原地修改。

对外发布时优先提供源码、报告和 IPS 补丁，不要公开分发可能受版权保护的 ROM。
