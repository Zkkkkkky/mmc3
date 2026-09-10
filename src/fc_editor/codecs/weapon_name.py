from __future__ import annotations

import struct

from ..errors import RomFormatError
from ..rom_image import RomImage


class WeaponNameReferenceCodec:
    """Safe weapon-name editing by reusing an existing localized record."""

    def __init__(self, rom: RomImage) -> None:
        self.rom = rom
        profile = rom.profile
        if (
            profile.weapon_name_pointer_table_offset is None
            or profile.weapon_name_data_prg_bank is None
            or profile.weapon_name_first_pointer is None
            or profile.weapon_name_data_end_pointer is None
            or profile.weapon_name_pointer_count <= 0
        ):
            raise RomFormatError("当前 ROM 没有已验证的武器名称表。")
        raw = rom.read(
            profile.weapon_name_pointer_table_offset,
            profile.weapon_name_pointer_count * 2,
        )
        self.original_pointers = tuple(
            struct.unpack(f"<{profile.weapon_name_pointer_count}H", raw)
        )
        if self.original_pointers[0] != profile.weapon_name_first_pointer:
            raise RomFormatError("武器名称指针表起始标记不正确。")
        if any(
            not profile.weapon_name_first_pointer
            <= pointer
            < profile.weapon_name_data_end_pointer
            for pointer in self.original_pointers
        ):
            raise RomFormatError("武器名称指针超出已验证数据区。")

        ids_by_pointer: dict[int, list[int]] = {}
        for weapon_id, pointer in enumerate(self.original_pointers):
            ids_by_pointer.setdefault(pointer, []).append(weapon_id)
        self.ids_by_pointer = {
            pointer: tuple(ids) for pointer, ids in ids_by_pointer.items()
        }
        unique_pointers = sorted(ids_by_pointer)
        self.capacities = {
            pointer: (
                unique_pointers[index + 1]
                if index + 1 < len(unique_pointers)
                else profile.weapon_name_data_end_pointer
            )
            - pointer
            for index, pointer in enumerate(unique_pointers)
        }
        if any(capacity <= 0 for capacity in self.capacities.values()):
            raise RomFormatError("武器名称记录容量无效。")

    def pointer_offset(self, weapon_id: int) -> int:
        profile = self.rom.profile
        if not 0 <= weapon_id < profile.weapon_name_pointer_count:
            raise IndexError("武器名称 ID 必须在 00—FF 之间。")
        assert profile.weapon_name_pointer_table_offset is not None
        return profile.weapon_name_pointer_table_offset + weapon_id * 2

    def pointer(self, weapon_id: int, data: bytes | None = None) -> int:
        source = self.rom.data if data is None else data
        offset = self.pointer_offset(weapon_id)
        return int.from_bytes(source[offset : offset + 2], "little")

    def pointer_to_file_offset(self, pointer: int) -> int:
        profile = self.rom.profile
        assert profile.weapon_name_data_prg_bank is not None
        assert profile.weapon_name_first_pointer is not None
        assert profile.weapon_name_data_end_pointer is not None
        if not profile.weapon_name_first_pointer <= pointer < profile.weapon_name_data_end_pointer:
            raise ValueError(f"武器名称 CPU 指针 ${pointer:04X} 无效。")
        return (
            16
            + profile.weapon_name_data_prg_bank * 0x2000
            + pointer
            - profile.weapon_name_data_window_base
        )

    def record_bytes(self, weapon_id: int, data: bytes | None = None) -> bytes:
        source = self.rom.data if data is None else data
        pointer = self.pointer(weapon_id, source)
        offset = self.pointer_to_file_offset(pointer)
        return bytes(source[offset : offset + self.capacities[pointer]])

    def source_ids(self, pointer: int) -> tuple[int, ...]:
        return tuple(
            weapon_id
            for weapon_id in self.ids_by_pointer.get(pointer, ())
            if 1 <= weapon_id < self.rom.profile.weapon_count
        )

    def reference_patch(
        self,
        data: bytes,
        weapon_id: int,
        source_name_id: int,
    ) -> tuple[int, bytes, bytes]:
        if (
            not 1 <= weapon_id < self.rom.profile.weapon_count
            or not 1 <= source_name_id < self.rom.profile.weapon_count
        ):
            raise ValueError("武器 ID 或名称来源 ID 超出当前 ROM 范围。")
        offset = self.pointer_offset(weapon_id)
        before = bytes(data[offset : offset + 2])
        pointer = self.original_pointers[source_name_id]
        return offset, before, pointer.to_bytes(2, "little")

    def round_trip(self, weapon_id: int) -> bool:
        pointer = self.pointer(weapon_id)
        return (
            pointer == self.original_pointers[weapon_id]
            and len(self.record_bytes(weapon_id)) == self.capacities[pointer]
        )
