from __future__ import annotations

import struct

from ..constants import (
    WEAPON_RECORD_SIZE,
)
from ..errors import RomFormatError
from ..models import WEAPON_FIELD_BY_KEY, WeaponRecord
from ..rom_image import BankAddress, RomImage


class WeaponCodec:
    """Lossless, read-only decoder for the 192-entry weapon pointer table."""

    def __init__(self, rom: RomImage) -> None:
        self.rom = rom
        self.pointers = self._read_pointers()

    def _read_pointers(self) -> tuple[int, ...]:
        profile = self.rom.profile
        table_size = profile.weapon_pointer_count * 2
        pointers = struct.unpack(
            f"<{profile.weapon_pointer_count}H",
            self.rom.read(profile.weapon_pointer_table_offset, table_size),
        )
        if pointers[0] != 0:
            raise RomFormatError("武器指针表起始标记不正确。")
        table_end = profile.weapon_pointer_table_offset + table_size
        for weapon_id, pointer in enumerate(pointers[1:], 1):
            try:
                offset = self.record_offset_from_pointer(pointer)
            except ValueError as error:
                raise RomFormatError(
                    f"武器 {weapon_id:02X} 的记录指针 ${pointer:04X} 无效。"
                ) from error
            if offset < table_end or offset + WEAPON_RECORD_SIZE > self.rom.size:
                raise RomFormatError(f"武器 {weapon_id:02X} 的记录超出支持区域。")
        return tuple(pointers)

    def record_offset_from_pointer(self, pointer: int) -> int:
        return BankAddress(
            self.rom.profile.weapon_data_prg_bank,
            pointer,
            window_base=self.rom.profile.weapon_data_window_base,
        ).to_file_offset()

    def record_offset(self, weapon_id: int) -> int:
        if not 1 <= weapon_id < self.rom.profile.weapon_count:
            raise IndexError(
                f"Weapon ID must be between 01 and {self.rom.profile.weapon_count - 1:02X}"
            )
        return self.record_offset_from_pointer(self.pointers[weapon_id])

    def decode_record(
        self,
        weapon_id: int,
        data: bytes | None = None,
    ) -> WeaponRecord:
        source = self.rom.data if data is None else data
        pointer = self.pointers[weapon_id]
        offset = self.record_offset(weapon_id)
        raw = bytes(source[offset : offset + WEAPON_RECORD_SIZE])
        if len(raw) != WEAPON_RECORD_SIZE:
            raise RomFormatError(f"武器 {weapon_id:02X} 的记录不完整。")
        return WeaponRecord(weapon_id, pointer, raw)

    @staticmethod
    def encode_record(record: WeaponRecord) -> bytes:
        return bytes(record.raw)

    def field_patch(
        self,
        data: bytes,
        weapon_id: int,
        field_key: str,
        value: int,
    ) -> tuple[int, bytes, bytes]:
        field = WEAPON_FIELD_BY_KEY[field_key]
        record = self.decode_record(weapon_id, data)
        changed = record.with_field(field_key, value)
        offset = self.record_offset(weapon_id) + field.record_offset
        return offset, record.raw[field.record_offset : field.record_offset + 1], changed.raw[
            field.record_offset : field.record_offset + 1
        ]

    def round_trip_record(self, weapon_id: int) -> bool:
        record = self.decode_record(weapon_id)
        return self.encode_record(record) == record.raw
