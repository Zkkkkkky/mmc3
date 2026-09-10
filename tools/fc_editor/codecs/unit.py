from __future__ import annotations

import struct
from dataclasses import replace

from ..constants import (
    UNIT_RECORD_SIZE,
)
from ..errors import RomFormatError
from ..models import UNIT_FIELD_BY_KEY, UnitRecord
from ..rom_image import BankAddress, RomImage


class UnitCodec:
    """Lossless decoder for the 128-entry unit pointer table and records."""

    def __init__(
        self,
        rom: RomImage,
        data: bytes | bytearray | None = None,
        *,
        pointer_table_offset: int | None = None,
        pair_first_bank: int | None = None,
    ) -> None:
        self.rom = rom
        self._source = rom.data if data is None else bytes(data)
        self.pointer_table_offset = (
            rom.profile.unit_pointer_table_offset
            if pointer_table_offset is None
            else pointer_table_offset
        )
        self.pair_first_bank = pair_first_bank
        self.pointers = self._read_pointers()
        groups: dict[int, list[int]] = {}
        for unit_id, pointer in enumerate(self.pointers):
            if unit_id and pointer:
                groups.setdefault(pointer, []).append(unit_id)
        self.ids_by_pointer = {
            pointer: tuple(ids) for pointer, ids in groups.items()
        }

    def _read_pointers(self) -> tuple[int, ...]:
        profile = self.rom.profile
        table_size = profile.unit_count * 2
        raw = self._source[
            self.pointer_table_offset : self.pointer_table_offset + table_size
        ]
        if len(raw) != table_size:
            raise RomFormatError("机体指针表不完整。")
        pointers = struct.unpack(
            f"<{profile.unit_count}H",
            raw,
        )
        if pointers[0] != 0:
            raise RomFormatError("机体指针表起始标记不正确。")
        table_end = self.pointer_table_offset + table_size
        for unit_id, pointer in enumerate(pointers[1:], 1):
            try:
                offset = self.record_offset_from_pointer(pointer)
            except ValueError as error:
                raise RomFormatError(
                    f"机体 {unit_id:02X} 的记录指针 ${pointer:04X} 无效。"
                ) from error
            if offset < table_end or offset + UNIT_RECORD_SIZE > self.rom.size:
                raise RomFormatError(f"机体 {unit_id:02X} 的记录超出支持区域。")
        return tuple(pointers)

    def record_offset_from_pointer(self, pointer: int) -> int:
        if self.pair_first_bank is not None:
            if not 0x8000 <= pointer < 0xC000:
                raise ValueError(f"机体记录指针 ${pointer:04X} 超出扩展 Bank 对。")
            return 16 + self.pair_first_bank * 0x2000 + pointer - 0x8000
        return BankAddress(
            self.rom.profile.unit_data_prg_bank,
            pointer,
            window_base=self.rom.profile.unit_data_window_base,
        ).to_file_offset()

    def record_offset(self, unit_id: int) -> int:
        if not 1 <= unit_id < self.rom.profile.unit_count:
            raise IndexError(
                f"Unit ID must be between 01 and {self.rom.profile.unit_count - 1:02X}"
            )
        return self.record_offset_from_pointer(self.pointers[unit_id])

    def decode_record(self, unit_id: int, data: bytes | None = None) -> UnitRecord:
        source = self._source if data is None else data
        pointer = self.pointers[unit_id]
        offset = self.record_offset(unit_id)
        raw = bytes(source[offset : offset + UNIT_RECORD_SIZE])
        if len(raw) != UNIT_RECORD_SIZE:
            raise RomFormatError(f"机体 {unit_id:02X} 的记录不完整。")
        return UnitRecord(pointer, self.ids_by_pointer[pointer], raw)

    def encode_record(self, record: UnitRecord) -> bytes:
        if record.pointer not in self.ids_by_pointer:
            raise ValueError(f"未知机体记录指针 ${record.pointer:04X}。")
        return bytes(record.raw)

    def field_patch(
        self,
        data: bytes,
        unit_id: int,
        field_key: str,
        value: int,
    ) -> tuple[int, bytes, bytes]:
        field = UNIT_FIELD_BY_KEY[field_key]
        if field_key.endswith("_growth"):
            field = replace(field, maximum=self.rom.profile.growth_curve_max)
        record = self.decode_record(unit_id, data)
        changed_raw = field.encode_into(record.raw, value)
        offset = self.record_offset(unit_id) + field.record_offset
        before = record.raw[field.record_offset : field.record_offset + field.width]
        after = changed_raw[field.record_offset : field.record_offset + field.width]
        return offset, before, after

    def round_trip_record(self, unit_id: int) -> bool:
        record = self.decode_record(unit_id)
        return self.encode_record(record) == record.raw
