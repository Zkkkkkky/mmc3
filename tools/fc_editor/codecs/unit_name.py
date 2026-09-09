from __future__ import annotations

import struct
from ..errors import RomFormatError
from ..rom_image import RomImage


class UnitNameReferenceCodec:
    """Stable unit-name editing by repointing to an existing localized name."""

    def __init__(self, rom: RomImage) -> None:
        self.rom = rom
        profile = rom.profile
        raw = rom.read(profile.unit_name_pointer_table_offset, profile.unit_name_count * 2)
        self.original_pointers = tuple(struct.unpack(f"<{profile.unit_name_count}H", raw))
        if self.original_pointers[0] != profile.unit_name_first_pointer:
            raise RomFormatError("机体名称指针表起始标记不正确。")
        if any(
            False if unit_id == 0 else not 0x8000 <= pointer <= 0xBFFF
            for unit_id, pointer in enumerate(self.original_pointers)
        ):
            raise RomFormatError("机体名称指针超出 Bank 12/13 的 16 KiB 窗口。")
        ids_by_pointer: dict[int, list[int]] = {}
        for unit_id, pointer in enumerate(self.original_pointers):
            ids_by_pointer.setdefault(pointer, []).append(unit_id)
        self.ids_by_pointer = {
            pointer: tuple(ids) for pointer, ids in ids_by_pointer.items()
        }

    def pointer_offset(self, unit_id: int) -> int:
        if not 0 <= unit_id < self.rom.profile.unit_name_count:
            raise IndexError("名称 ID 必须在 00—FF 之间。")
        return self.rom.profile.unit_name_pointer_table_offset + unit_id * 2

    def pointer(self, unit_id: int, data: bytes | None = None) -> int:
        source = self.rom.data if data is None else data
        offset = self.pointer_offset(unit_id)
        return int.from_bytes(source[offset : offset + 2], "little")

    def reference_patch(
        self,
        data: bytes,
        unit_id: int,
        source_name_id: int,
    ) -> tuple[int, bytes, bytes]:
        if (
            not 1 <= unit_id < self.rom.profile.unit_count
            or not 1 <= source_name_id < self.rom.profile.unit_count
        ):
            raise ValueError("机体 ID 或名称来源 ID 超出当前 ROM 范围。")
        offset = self.pointer_offset(unit_id)
        before = bytes(data[offset : offset + 2])
        pointer = self.original_pointers[source_name_id]
        return offset, before, pointer.to_bytes(2, "little")

    def source_ids(self, pointer: int) -> tuple[int, ...]:
        return tuple(
            unit_id
            for unit_id in self.ids_by_pointer.get(pointer, ())
            if 1 <= unit_id < self.rom.profile.unit_count
        )
