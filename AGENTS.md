# Repository Guidelines

## Project Purpose & Modifier Conventions

The project's core goal is to develop a ROM editor for the FC game *第二次机器人大战*. `srw2_patched.exe` is a completed editor product used as a reference source for behavior, workflows, and supported data; it is not the editor currently being developed. “新DC修改器” is the active editor product in this repository.

Every change to the active editor must update `DC修改器使用说明.md` in the same change. Keep the instructions synchronized with changes to features, UI, supported data, operating steps, validation, and user-visible limitations.

## Project Structure & Module Organization

This repository is a self-contained NES ROM expansion handoff. `tools/` contains the Python builder, IPS helpers, reusable `fc_editor/` modules, and the `unittest` suite. `analysis/` holds 6502/ASM6 sources, generated listings, Lua emulator checks, and bundled FamiStudio assembler dependencies. Final ROMs, reports, and NSF inputs live under `build/`; distributable patches belong in `patches/`. Treat `历史方案报告/` as reference material and `验证工具/` as vendored tooling. Read `交接文档.md` before changing ROM layout or audio behavior.

For historical reverse-engineering experience, consult `analysis/FC第二次机器人大战资料集V1.16_阅读笔记.md` first and use the extracted CHM content under `analysis/reference_chm_v1_16/` when more detail is needed. Treat this material as leads rather than authoritative project facts: verify addresses, free-space claims, mapper behavior, and uncertain annotations against the current ROM, disassembly, builder assertions, and emulator checks.

## Build, Test, and Development Commands

Run commands from the repository root on Windows:

```powershell
python tools\build_dc_expanded_dual_audio.py
python tools\test_dc_expanded_dual_audio.py
.\.venv\Scripts\python.exe -m unittest discover -s tools -p "test_*.py"
.\build_modifier_exe.ps1
.\验证交接包.ps1
```

The ROM builder validates source identity and regenerates ROM, IPS, and reports. The discovery command runs core and offscreen GUI tests. `build_modifier_exe.ps1` creates the standalone Windows editor. The verification script checks every file recorded in `文件清单_SHA256.csv`.

## Coding Style & Naming Conventions

Use four-space indentation, type hints, `pathlib.Path`, and `snake_case` for Python functions and modules; constants remain `UPPER_SNAKE_CASE`. Keep tests named `test_<behavior>`. In assembly, preserve existing lower-snake-case labels and hexadecimal address comments. Prefer repository-relative paths derived from the root; do not embed machine-specific paths. There is no configured formatter or linter, so match nearby code and keep changes focused.

## Testing Guidelines

Tests use Python's standard `unittest` framework and require the exact source ROM hash documented in `交接文档.md`. Add assertions for every changed bank, pointer, size, or hash invariant. After ROM changes, run the builder and full test suite, then perform the relevant Mesen/Lua smoke checks described in the handoff. Do not edit `build/nsf/新DC.nes`; create derived outputs instead.

## Commit & Pull Request Guidelines

This package contains no Git metadata, so no historical commit convention can be inferred. Use concise imperative subjects, for example `Fix expanded-bank dispatch`. Pull requests should explain affected banks and behavior, list verification commands and emulator results, and identify regenerated ROM/IPS/report artifacts. Include before/after hashes when binary outputs change. Avoid distributing copyrighted ROMs publicly; prefer source, reports, and IPS patches.
