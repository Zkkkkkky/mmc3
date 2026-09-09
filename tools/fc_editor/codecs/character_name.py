from __future__ import annotations

import struct

from ..errors import RomFormatError
from ..rom_image import RomImage


class CharacterNameCodec:
    """Read and safely repoint the verified in-battle character-name table."""

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
        self.original_pointers = tuple(
            struct.unpack(f"<{profile.character_name_count}H", raw)
        )
        self.pointers = self.original_pointers
        if (
            self.original_pointers[0] != 0
            or self.original_pointers[1] != profile.character_name_first_pointer
        ):
            raise RomFormatError("人物名称指针表起始标记不正确。")
        if any(
            pointer
            and not profile.character_name_first_pointer
            <= pointer
            < profile.character_name_data_end_pointer
            for pointer in self.original_pointers
        ):
            raise RomFormatError("人物名称指针超出已验证数据区。")

        ids_by_pointer: dict[int, list[int]] = {}
        for character_id, pointer in enumerate(self.original_pointers):
            if pointer:
                ids_by_pointer.setdefault(pointer, []).append(character_id)
        self.ids_by_pointer = {
            pointer: tuple(ids) for pointer, ids in ids_by_pointer.items()
        }
        unique_pointers = sorted(ids_by_pointer)
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

    def pointer_offset(self, character_id: int) -> int:
        if not 0 <= character_id < len(self.original_pointers):
            raise IndexError(
                f"人物 ID 必须在 00—{len(self.original_pointers) - 1:02X} 之间。"
            )
        offset = self.rom.profile.character_name_pointer_table_offset
        assert offset is not None
        return offset + character_id * 2

    def pointer(self, character_id: int, data: bytes | bytearray | None = None) -> int:
        source = self.rom.data if data is None else data
        offset = self.pointer_offset(character_id)
        return int.from_bytes(source[offset : offset + 2], "little")

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

    def record_bytes(
        self,
        character_id: int,
        data: bytes | bytearray | None = None,
    ) -> bytes:
        source = self.rom.data if data is None else data
        pointer = self.pointer(character_id, source)
        if not pointer:
            return b""
        offset = self.pointer_to_file_offset(pointer)
        return bytes(source[offset : offset + self.capacities[pointer]])

    def source_ids(self, pointer: int) -> tuple[int, ...]:
        return tuple(
            character_id
            for character_id in self.ids_by_pointer.get(pointer, ())
            if 1 <= character_id < self.rom.profile.character_name_count
        )

    def reference_patch(
        self,
        data: bytes | bytearray,
        character_id: int,
        source_name_id: int,
    ) -> tuple[int, bytes, bytes]:
        count = self.rom.profile.character_name_count
        if not 1 <= character_id < count or not 1 <= source_name_id < count:
            raise ValueError(
                f"人物 ID 或名称来源 ID 必须在 01—{count - 1:02X} 之间。"
            )
        offset = self.pointer_offset(character_id)
        before = bytes(data[offset : offset + 2])
        pointer = self.original_pointers[source_name_id]
        if not pointer:
            raise ValueError("不能把人物名称指向空指针。")
        return offset, before, pointer.to_bytes(2, "little")

    def round_trip(
        self,
        character_id: int,
        data: bytes | bytearray | None = None,
    ) -> bool:
        pointer = self.pointer(character_id, data)
        return (
            not pointer
            or pointer in self.capacities
            and len(self.record_bytes(character_id, data)) == self.capacities[pointer]
        )
