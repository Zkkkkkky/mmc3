from __future__ import annotations

import os
import tempfile
from dataclasses import dataclass
from pathlib import Path

from fc_editor.codecs import LegacySaveCodec


SPIRIT_PREVIEW_CALL_OFFSET = 0x3891D
TITLE_PREVIEW_CALL_OFFSET = 0x3804A
TEST_UNIT_ID = 0x11


@dataclass(frozen=True)
class MapAnimationRuntimeArtifacts:
    rom_path: Path
    save_path: Path | None
    frame_directory: Path
    script_path: Path
    context: str


def _atomic_write(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{path.name}.", suffix=".tmp", dir=path.parent
    )
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    except Exception:
        temporary.unlink(missing_ok=True)
        raise


def prepare_map_animation_runtime_preview(
    draft: bytes | bytearray,
    animation_id: int,
    source_save: str | Path,
    output_directory: str | Path,
    emulator_directory: str | Path,
    battle_script: str | Path,
    title_script: str | Path,
) -> MapAnimationRuntimeArtifacts:
    """Create an isolated ROM/SRAM pair for a real Mesen-rendered preview."""

    data = bytearray(draft)
    if data[:4] != b"NES\x1a":
        raise ValueError("当前草稿不是可供 Mesen 运行的 NES ROM。")
    if not 0 <= animation_id <= 0x98:
        raise ValueError("地图动画编号超出当前 ROM 的动画表。")

    output = Path(output_directory).expanduser().resolve()
    emulator = Path(emulator_directory).expanduser().resolve()
    if animation_id == 0:
        call_offset = TITLE_PREVIEW_CALL_OFFSET
        context = "标题场景"
        script = Path(title_script).expanduser().resolve()
    else:
        call_offset = SPIRIT_PREVIEW_CALL_OFFSET
        context = "活动战场精神场景"
        script = Path(battle_script).expanduser().resolve()
    if bytes(data[call_offset:call_offset + 2]) != b"\x38\x02":
        raise ValueError("真实预览调用入口与已验证 ROM 不一致，已拒绝生成测试 ROM。")
    if not script.is_file():
        raise FileNotFoundError(f"找不到真实预览脚本：{script}")
    data[call_offset + 2] = animation_id

    rom_path = output / f"map-animation-runtime-{animation_id:02X}.nes"
    _atomic_write(rom_path, bytes(data))
    save_path: Path | None = None
    if animation_id != 0:
        source = Path(source_save).expanduser().resolve()
        fixture = LegacySaveCodec.prepare_weapon_animation_fixture(
            source.read_bytes(), unit_id=TEST_UNIT_ID
        )
        save_path = emulator / "Saves" / f"{rom_path.stem}.sav"
        _atomic_write(save_path, fixture)

    frame_directory = emulator / "LuaScriptData" / script.stem
    frame_directory.mkdir(parents=True, exist_ok=True)
    for frame in frame_directory.glob("runtime-frame-*.png"):
        frame.unlink()
    return MapAnimationRuntimeArtifacts(
        rom_path=rom_path,
        save_path=save_path,
        frame_directory=frame_directory,
        script_path=script,
        context=context,
    )


def runtime_preview_frames(directory: str | Path) -> tuple[Path, ...]:
    return tuple(sorted(Path(directory).glob("runtime-frame-*.png")))
