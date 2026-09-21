from __future__ import annotations

import sys
from pathlib import Path


def workspace_root() -> Path:
    if getattr(sys, "frozen", False):
        executable_dir = Path(sys.executable).resolve().parent
        for candidate in (
            executable_dir,
            executable_dir.parent,
            executable_dir.parent.parent,
            Path.cwd(),
        ):
            rom_directory = candidate / "output" / "rom"
            if (rom_directory / "DC_kuorong_464K.nes").is_file():
                return candidate
        return executable_dir
    return Path(__file__).resolve().parents[2]


ROOT = workspace_root()
EXPANDED_ROM = ROOT / "output" / "rom" / "DC_kuorong_464K.nes"
LEGACY_ROM = ROOT / "references" / "rom" / "baselines" / "DC_kuorong.nes"
DEFAULT_ROM = EXPANDED_ROM if EXPANDED_ROM.is_file() else LEGACY_ROM


def default_export_path(filename: str) -> Path:
    if Path(filename).name != filename:
        raise ValueError("默认输出文件名不能包含路径。")
    directory = ROOT / "output" / "exports"
    directory.mkdir(parents=True, exist_ok=True)
    return directory / filename


def writable_output_path(path: str | Path) -> Path:
    destination = Path(path).expanduser().resolve()
    reference_root = (ROOT / "references").resolve()
    if destination == reference_root or reference_root in destination.parents:
        raise ValueError("references/ 是只读参考目录，不能作为输出目标。")
    return destination
