# Repository Guidelines

## Project Purpose & Modifier Conventions

The project's core goal is to develop a ROM editor for the FC game *第二次机器人大战*. `references/legacy_modifier/SRW2_patched.exe` is a completed editor product used as a reference source for behavior, workflows, and supported data; it is not the editor currently being developed. “新DC修改器” is the active editor product in this repository.

Every change to the active editor must update `docs/DC修改器使用说明.md` in the same change. Keep the instructions synchronized with changes to features, UI, supported data, operating steps, validation, and user-visible limitations.

## Project Structure & Module Organization

The repository uses five core directories plus a separate read-only reference area:

- `src/` is the product source root. The GUI is in `src/dc_modifier/`, reusable ROM code is in `src/fc_editor/`, session/build orchestration is in `src/fc_rom_editor_core.py`, 6502/ASM6 sources are in `src/asm/`, and active default configuration is in `src/resources/default_config/`.
- `tools/` contains launch, ROM build, documentation, packaging, manifest, and research scripts. Bundled third-party dependencies live under `tools/vendor/famistudio-4.5.3/`, `tools/vendor/fceux-2.6.6/`, and `tools/vendor/mesen-0.9.9/`.
- `tests/` is the sole automated-test discovery root. Emulator smoke scripts live in `tests/emulator/`.
- `output/` contains generated and distributable artifacts. Use `output/app/`, `output/rom/`, `output/patches/`, `output/reports/`, `output/mappings/`, `output/pdf/`, `output/build/`, `output/verification/`, and `output/manifest/` according to artifact type.
- `docs/` contains user-facing and maintenance documentation, research notes, screenshots, and rejected-design archives.
- `references/` contains immutable source material and historical evidence. Treat `references/rom/source/新DC.nes`, `references/rom/baselines/DC_kuorong.nes`, `references/legacy_modifier/`, `references/audio/`, `references/emulator-state/`, and `references/research/` as read-only.

The recommended generated ROM is `output/rom/DC_kuorong_464K.nes`. Never redirect build output into `references/` and do not use a generated output as a replacement for the canonical source ROM.

Read `docs/交接文档.md` before changing ROM layout or audio behavior. For historical reverse-engineering experience, consult `docs/research/FC第二次机器人大战资料集V1.16_阅读笔记.md` first and use the extracted CHM content under `references/research/fc资料集-v1.16/` when more detail is needed. Treat this material as leads rather than authoritative facts: verify addresses, free-space claims, mapper behavior, and uncertain annotations against the current ROM, disassembly, builder assertions, and emulator checks.

`docs/提交记录.md` is a historical record. Do not rewrite it merely to make old commands or old paths look current.

## Build, Test, and Development Commands

Run commands from the repository root on Windows:

```powershell
.\.venv\Scripts\python.exe tools\run_dc_modifier.py
python tools\build_dc_expanded_dual_audio.py
.\.venv\Scripts\python.exe -m unittest discover -s tests -t . -p "test_*.py"
.\tools\build_modifier_exe.ps1
.\tools\更新文件清单.ps1
.\tools\验证交接包.ps1
```

The launcher adds `src/` to the import path. `pyproject.toml` provides the standard `src` package configuration for editable installs and packaging. The ROM builder reads `references/rom/source/新DC.nes` and writes ROM, IPS, reports, and intermediate assembly products under `output/`. The discovery command runs core, integration, and offscreen GUI tests. `tools/build_modifier_exe.ps1` creates `output/app/新DC篇完整修改器.exe`. The two manifest scripts update and verify `output/manifest/文件清单_SHA256.csv`.

## Coding Style & Naming Conventions

Use four-space indentation, type hints, `pathlib.Path`, and `snake_case` for Python functions and modules; constants remain `UPPER_SNAKE_CASE`. Keep tests named `test_<behavior>`. In assembly, preserve existing lower-snake-case labels and hexadecimal address comments. Prefer repository-relative paths derived from the root; do not embed machine-specific paths. There is no configured formatter or linter, so match nearby code and keep changes focused.

Do not restore application modules or tests beneath `tools/`. New product code belongs in `src/`; new tests belong in `tests/`; generated files belong in `output/`; immutable evidence and upstream inputs belong in `references/`.

## Testing Guidelines

Tests use Python's standard `unittest` framework and require the exact source ROM hash documented in `docs/交接文档.md`. Add assertions for every changed bank, pointer, size, or hash invariant. After ROM changes, run the builder and full test suite, then perform the relevant Mesen/Lua smoke checks described in the handoff. Use `tools/vendor/mesen-0.9.9/` with scripts from `tests/emulator/`, and store resulting evidence under `output/verification/`.

Do not edit `references/rom/source/新DC.nes` or `references/rom/baselines/DC_kuorong.nes`; create derived outputs instead.

## Commit & Pull Request Guidelines

Use concise imperative subjects, for example `Fix expanded-bank dispatch`. Pull requests should explain affected banks and behavior, list verification commands and emulator results, and identify regenerated ROM/IPS/report artifacts. Include before/after hashes when binary outputs change. Avoid distributing copyrighted ROMs publicly; prefer source, reports, and IPS patches.
