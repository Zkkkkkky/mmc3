from __future__ import annotations

from ..constants import (
    UNIT_WEAPON_SLOT_COUNT,
)
from ..errors import RomFormatError
from ..models import UnitWeaponConfig
from ..rom_image import RomImage


class UnitWeaponCodec:
    """Decoder for the two direct weapon-ID slots assigned to every unit ID."""

    def __init__(
        self,
        rom: RomImage,
        data: bytes | bytearray | None = None,
        *,
        table_offset: int | None = None,
    ) -> None:
        self.rom = rom
        self._source = rom.data if data is None else bytes(data)
        self.table_offset = (
            rom.profile.unit_weapon_table_offset
            if table_offset is None
            else int(table_offset)
        )
        self._validate_table(self._source)

    def record_offset(self, unit_id: int) -> int:
        if not 1 <= unit_id < self.rom.profile.unit_count:
            raise IndexError(
                f"Unit ID must be between 01 and {self.rom.profile.unit_count - 1:02X}"
            )
        return self.table_offset + unit_id * UNIT_WEAPON_SLOT_COUNT

    def _validate_table(self, data: bytes) -> None:
        profile = self.rom.profile
        end = self.table_offset + profile.unit_count * UNIT_WEAPON_SLOT_COUNT
        if end > len(data):
            raise RomFormatError("机体武器配置表超出 ROM。")
        for unit_id in range(1, profile.unit_count):
            start = self.table_offset + unit_id * UNIT_WEAPON_SLOT_COUNT
            for weapon_id in data[start : start + UNIT_WEAPON_SLOT_COUNT]:
                if weapon_id >= profile.weapon_count:
                    raise RomFormatError(
                        f"机体 {unit_id:02X} 引用了无效武器 {weapon_id:02X}。"
                    )

    def decode(
        self, unit_id: int, data: bytes | bytearray | None = None
    ) -> UnitWeaponConfig:
        source = self._source if data is None else data
        offset = self.record_offset(unit_id)
        raw = source[offset : offset + UNIT_WEAPON_SLOT_COUNT]
        if len(raw) != UNIT_WEAPON_SLOT_COUNT:
            raise RomFormatError(f"机体 {unit_id:02X} 的武器配置不完整。")
        return UnitWeaponConfig(unit_id, (raw[0], raw[1]))

    @staticmethod
    def encode(config: UnitWeaponConfig) -> bytes:
        return bytes(config.weapon_ids)

    def slot_patch(
        self,
        data: bytes,
        unit_id: int,
        slot: int,
        weapon_id: int,
    ) -> tuple[int, bytes, bytes]:
        if not 0 <= weapon_id < self.rom.profile.weapon_count:
            raise ValueError(
                f"武器 ID 必须在 00—{self.rom.profile.weapon_count - 1:02X} 之间。"
            )
        config = self.decode(unit_id, data)
        changed = config.with_slot(slot, weapon_id)
        offset = self.record_offset(unit_id) + slot
        return offset, bytes((config.weapon_ids[slot],)), bytes((changed.weapon_ids[slot],))
