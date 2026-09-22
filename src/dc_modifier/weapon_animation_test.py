from __future__ import annotations

import os
import tempfile
from dataclasses import dataclass
from pathlib import Path

from fc_editor.codecs import LegacySaveCodec


TEST_UNIT_ID = 0x11


@dataclass(frozen=True)
class WeaponAnimationTestArtifacts:
    rom_path: Path
    save_path: Path
    unit_id: int
    weapon_id: int


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


def prepare_weapon_animation_test(
    project,
    weapon_id: int,
    source_save: str | Path,
    output_directory: str | Path,
    emulator_directory: str | Path,
) -> WeaponAnimationTestArtifacts:
    """Export an isolated ROM/SRAM pair that can immediately enter combat."""
    if not project.supports_unit_weapons or project.unit_weapon_codec is None:
        raise ValueError("当前 ROM 没有可写的机体武器表，不能生成动画测试。")
    if not 1 <= weapon_id < project.weapon_count:
        raise ValueError(f"武器 ID 必须在 01—{project.weapon_count - 1:02X} 之间。")
    if not 1 <= TEST_UNIT_ID < project.unit_count:
        raise ValueError("当前 ROM 不包含动画测试所需的机体槽 $11。")

    source = Path(source_save).expanduser().resolve()
    save_data = source.read_bytes()
    fixture = LegacySaveCodec.prepare_weapon_animation_fixture(
        save_data, unit_id=TEST_UNIT_ID
    )

    directory = Path(output_directory).expanduser().resolve()
    rom_path = directory / f"weapon-animation-{weapon_id:02X}.nes"
    project.save_as(rom_path, make_backup=False)
    rom_data = bytearray(rom_path.read_bytes())
    weapon_offset = project.unit_weapon_codec.record_offset(TEST_UNIT_ID)
    if weapon_offset >= len(rom_data):
        raise ValueError("动画测试机体的武器槽超出导出 ROM。")
    rom_data[weapon_offset] = weapon_id
    _atomic_write(rom_path, bytes(rom_data))

    saves = Path(emulator_directory).expanduser().resolve() / "Saves"
    save_path = saves / f"{rom_path.stem}.sav"
    _atomic_write(save_path, fixture)
    return WeaponAnimationTestArtifacts(
        rom_path=rom_path,
        save_path=save_path,
        unit_id=TEST_UNIT_ID,
        weapon_id=weapon_id,
    )
