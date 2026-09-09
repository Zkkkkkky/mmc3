from __future__ import annotations

import struct

from ..errors import RomFormatError
from ..rom_image import RomImage


class CharacterNameCodec:
    """Read the verified in-battle character-name pointer table."""

    def __init__(self, rom: RomImage) -> None:
        self.rom = rom
        profile = rom.profile
        if (
            profile.character_name_pointer_table_offset is None
            or profile.character_name_data_prg_bank is None
            or profile.character_name_first_pointer is None
            or profile.character_name_data_end_pointer is None
            or profile.character_name_count <= 0
        ):
            raise RomFormatError("当前 ROM 没有已验证的人物名称表。")
        raw = rom.read(
            profile.character_name_pointer_table_offset,
            profile.character_name_count * 2,
        )
        self.pointers = tuple(
            struct.unpack(f"<{profile.character_name_count}H", raw)
        )
        if self.pointers[0] != 0 or self.pointers[1] != profile.character_name_first_pointer:
            raise RomFormatError("人物名称指针表起始标记不正确。")
        if any(
            pointer
            and not profile.character_name_first_pointer
            <= pointer
            < profile.character_name_data_end_pointer
            for pointer in self.pointers
        ):
            raise RomFormatError("人物名称指针超出已验证数据区。")

        unique_pointers = sorted(set(self.pointers) - {0})
        self.capacities = {
            pointer: (
                unique_pointers[index + 1]
                if index + 1 < len(unique_pointers)
                else profile.character_name_data_end_pointer
            )
            - pointer
            for index, pointer in enumerate(unique_pointers)
        }
        if any(capacity <= 0 for capacity in self.capacities.values()):
            raise RomFormatError("人物名称记录容量无效。")

    def pointer(self, character_id: int) -> int:
        if not 0 <= character_id < len(self.pointers):
            raise IndexError(
                f"人物 ID 必须在 00—{len(self.pointers) - 1:02X} 之间。"
            )
        return self.pointers[character_id]

    def pointer_to_file_offset(self, pointer: int) -> int:
        profile = self.rom.profile
        assert profile.character_name_data_prg_bank is not None
        assert profile.character_name_first_pointer is not None
        assert profile.character_name_data_end_pointer is not None
        if not profile.character_name_first_pointer <= pointer < profile.character_name_data_end_pointer:
            raise ValueError(f"人物名称 CPU 指针 ${pointer:04X} 无效。")
        return (
            16
            + profile.character_name_data_prg_bank * 0x2000
            + pointer
            - profile.character_name_data_window_base
        )

    def record_bytes(self, character_id: int) -> bytes:
        pointer = self.pointer(character_id)
        if not pointer:
            return b""
        offset = self.pointer_to_file_offset(pointer)
        return self.rom.read(offset, self.capacities[pointer])

    def round_trip(self, character_id: int) -> bool:
        pointer = self.pointer(character_id)
        return not pointer or len(self.record_bytes(character_id)) == self.capacities[pointer]
