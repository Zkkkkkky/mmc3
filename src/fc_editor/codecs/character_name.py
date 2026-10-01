from __future__ import annotations

import struct

from .bank24_composite import file_offset as bank24_file_offset
from .bank24_composite import parse as parse_bank24
from .bank24_composite import replacement_patches as bank24_replacement_patches
from .bank24_composite import roots as bank24_roots
from .bank24_composite import with_character_names
from ..dc_text import default_dc_text_table
from ..errors import RomFormatError
from ..rom_image import RomImage
from ..text_table import TextTable


class CharacterNameCodec:
    """Read and safely repoint the verified in-battle character-name table."""

    def __init__(self, rom: RomImage, data: bytes | bytearray | None = None) -> None:
        self.rom = rom
        source = rom.data if data is None else data
        profile = rom.profile
        if (
            profile.character_name_pointer_table_offset is None
            or profile.character_name_data_prg_bank is None
            or profile.character_name_first_pointer is None
            or profile.character_name_data_end_pointer is None
            or profile.character_name_count <= 0
        ):
            raise RomFormatError("当前 ROM 没有已验证的人物名称表。")
        resource_roots = bank24_roots(source)
        battle_table_offset = bank24_file_offset(resource_roots[4])
        normal_table_offset = bank24_file_offset(resource_roots[3]) + 2
        data_end_pointer = resource_roots[5]
        raw = bytes(source[battle_table_offset:battle_table_offset + profile.character_name_count * 2])
        self.original_pointers = tuple(
            struct.unpack(f"<{profile.character_name_count}H", raw)
        )
        self.pointers = self.original_pointers
        if (
            self.original_pointers[0] != 0
            or not self.original_pointers[1]
        ):
            raise RomFormatError("人物名称指针表起始标记不正确。")
        if any(
            pointer
            and not resource_roots[3] <= pointer < data_end_pointer
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
                else data_end_pointer
            )
            - pointer
            for index, pointer in enumerate(unique_pointers)
        }
        if any(capacity <= 0 for capacity in self.capacities.values()):
            raise RomFormatError("人物名称记录容量无效。")
        self.normal_pointers: tuple[int, ...] = ()
        self._capacity_cache: dict[bytes, dict[int, int]] = {}
        if profile.character_normal_name_pointer_table_offset is not None:
            if profile.character_normal_name_count <= 0:
                raise RomFormatError("人物显示名称数量无效。")
            raw = bytes(source[normal_table_offset:normal_table_offset + profile.character_normal_name_count * 2])
            self.normal_pointers = tuple(
                struct.unpack(f"<{profile.character_normal_name_count}H", raw)
            )
            if any(
                not resource_roots[3] <= pointer < data_end_pointer
                for pointer in self.normal_pointers
            ):
                raise RomFormatError("人物显示名称指针超出已验证数据区。")

    def _table_offset(self, source: bytes | bytearray, *, normal: bool) -> int:
        offset = bank24_file_offset(bank24_roots(source)[3 if normal else 4])
        # Directory 4 physically starts with the reserved ID $00 pointer, while
        # the public normal-name API exposes IDs $01—$C8 only.
        return offset + (2 if normal else 0)

    def _data_end_pointer(self, source: bytes | bytearray) -> int:
        return bank24_roots(source)[5]

    def pointer_offset(
        self,
        character_id: int,
        data: bytes | bytearray | None = None,
    ) -> int:
        if not 0 <= character_id < len(self.original_pointers):
            raise IndexError(
                f"人物 ID 必须在 00—{len(self.original_pointers) - 1:02X} 之间。"
            )
        source = self.rom.data if data is None else data
        offset = self._table_offset(source, normal=False)
        return offset + character_id * 2

    def pointer(self, character_id: int, data: bytes | bytearray | None = None) -> int:
        source = self.rom.data if data is None else data
        offset = self.pointer_offset(character_id, source)
        return int.from_bytes(source[offset : offset + 2], "little")

    def normal_pointer_offset(
        self,
        character_id: int,
        data: bytes | bytearray | None = None,
    ) -> int:
        profile = self.rom.profile
        if (
            profile.character_normal_name_pointer_table_offset is None
            or not 1 <= character_id <= profile.character_normal_name_count
        ):
            raise IndexError(
                f"人物显示名称 ID 必须在 01—{profile.character_normal_name_count:02X} 之间。"
            )
        source = self.rom.data if data is None else data
        return self._table_offset(source, normal=True) + (character_id - 1) * 2

    def normal_pointer(
        self, character_id: int, data: bytes | bytearray | None = None
    ) -> int:
        source = self.rom.data if data is None else data
        offset = self.normal_pointer_offset(character_id, source)
        return int.from_bytes(source[offset : offset + 2], "little")

    def _current_pointers(self, data: bytes | bytearray) -> tuple[int, ...]:
        profile = self.rom.profile
        pointers = [self.pointer(index, data) for index in range(profile.character_name_count)]
        if profile.character_normal_name_pointer_table_offset is not None:
            pointers.extend(
                self.normal_pointer(index, data)
                for index in range(1, profile.character_normal_name_count + 1)
            )
        return tuple(pointer for pointer in pointers if pointer)

    def _pointer_table_signature(self, data: bytes | bytearray) -> bytes:
        """Return the small mutable region that determines name capacities."""

        profile = self.rom.profile
        battle_offset = self._table_offset(data, normal=False)
        parts = [
            bytes(
                data[
                    battle_offset : battle_offset + profile.character_name_count * 2
                ]
            )
        ]
        if profile.character_normal_name_pointer_table_offset is not None:
            normal_offset = self._table_offset(data, normal=True)
            parts.append(
                bytes(
                    data[
                        normal_offset : normal_offset
                        + profile.character_normal_name_count * 2
                    ]
                )
            )
        return b"".join(parts)

    def _current_capacities(self, data: bytes | bytearray) -> dict[int, int]:
        signature = self._pointer_table_signature(data)
        cached = self._capacity_cache.get(signature)
        if cached is not None:
            return cached
        data_end_pointer = self._data_end_pointer(data)
        pointers = sorted(set(self._current_pointers(data)))
        capacities = {
            pointer: (
                pointers[index + 1]
                if index + 1 < len(pointers)
                else data_end_pointer
            )
            - pointer
            for index, pointer in enumerate(pointers)
        }
        # Project undo/redo and name repacks only create a few signatures. Keep
        # the cache bounded so temporary validation buffers cannot grow it forever.
        if len(self._capacity_cache) >= 8:
            self._capacity_cache.pop(next(iter(self._capacity_cache)))
        self._capacity_cache[signature] = capacities
        return capacities

    def _capacity(self, pointer: int, data: bytes | bytearray) -> int:
        capacities = self._current_capacities(data)
        if pointer not in capacities:
            raise ValueError(f"人物名称 CPU 指针 ${pointer:04X} 未被当前名称表引用。")
        return capacities[pointer]

    def _terminated_record(self, pointer: int, data: bytes | bytearray) -> bytes:
        offset = self.pointer_to_file_offset(pointer)
        capacity = self._capacity(pointer, data)
        raw = bytes(data[offset : offset + capacity])
        end = raw.find(b"\xFF")
        if end < 0:
            raise RomFormatError(f"人物名称 ${pointer:04X} 缺少结束码。")
        return raw[: end + 1]

    def pointer_to_file_offset(self, pointer: int) -> int:
        if not 0x8000 <= pointer < 0xBF40:
            raise ValueError(f"人物名称 CPU 指针 ${pointer:04X} 无效。")
        return bank24_file_offset(pointer)

    def record_bytes(
        self,
        character_id: int,
        data: bytes | bytearray | None = None,
    ) -> bytes:
        source = self.rom.data if data is None else data
        pointer = self.pointer(character_id, source)
        if not pointer:
            return b""
        return self._terminated_record(pointer, source)

    def normal_record_bytes(
        self,
        character_id: int,
        data: bytes | bytearray | None = None,
    ) -> bytes:
        source = self.rom.data if data is None else data
        pointer = self.normal_pointer(character_id, source)
        return self._terminated_record(pointer, source)

    def source_ids(
        self, pointer: int, data: bytes | bytearray | None = None
    ) -> tuple[int, ...]:
        source = self.rom.data if data is None else data
        return tuple(
            character_id
            for character_id in range(1, self.rom.profile.character_name_count)
            if self.pointer(character_id, source) == pointer
        )

    def normal_source_ids(
        self, pointer: int, data: bytes | bytearray | None = None
    ) -> tuple[int, ...]:
        source = self.rom.data if data is None else data
        return tuple(
            character_id
            for character_id in range(
                1, self.rom.profile.character_normal_name_count + 1
            )
            if self.normal_pointer(character_id, source) == pointer
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
        offset = self.pointer_offset(character_id, data)
        before = bytes(data[offset : offset + 2])
        pointer = self.pointer(source_name_id, data)
        if not pointer:
            raise ValueError("不能把人物名称指向空指针。")
        return offset, before, pointer.to_bytes(2, "little")

    def repack_names(
        self,
        data: bytes | bytearray,
        character_id: int,
        *,
        normal_text: str | None = None,
        battle_text: str | None = None,
        text_table: TextTable | None = None,
    ) -> tuple[tuple[int, bytes, bytes], ...]:
        """Repack both verified name tables inside their shared fixed pool."""

        profile = self.rom.profile
        if (
            profile.character_normal_name_pointer_table_offset is None
            or profile.character_normal_name_count <= 0
        ):
            raise ValueError("当前 ROM 没有可重排的双人物名称表。")
        if not 1 <= character_id <= profile.character_normal_name_count:
            raise ValueError(
                f"人物 ID 必须在 01—{profile.character_normal_name_count:02X} 之间。"
            )
        source = bytes(data)
        logical = parse_bank24(source)
        table = text_table or default_dc_text_table()

        def encode_name(old: bytes, text: str) -> bytes:
            encoded = table.encode_preserving_tokens(old, text)
            return encoded if encoded.endswith(b"\xFF") else encoded + b"\xFF"

        if normal_text is not None:
            old = logical.normal_names[character_id - 1]
            normal_replacement = encode_name(old, normal_text)
        else:
            normal_replacement = None
        if battle_text is not None:
            if character_id >= profile.character_name_count:
                raise ValueError(f"人物 ${character_id:02X} 没有战斗名称槽。")
            old = logical.battle_names[character_id - 1]
            battle_replacement = encode_name(old, battle_text)
        else:
            battle_replacement = None
        updated = with_character_names(
            logical,
            character_id,
            normal=normal_replacement,
            battle=battle_replacement,
        )
        return bank24_replacement_patches(source, updated)

    def round_trip(
        self,
        character_id: int,
        data: bytes | bytearray | None = None,
    ) -> bool:
        source = self.rom.data if data is None else data
        pointer = self.pointer(character_id, source)
        if not pointer:
            return True
        try:
            return self._terminated_record(pointer, source).endswith(b"\xFF")
        except (RomFormatError, ValueError):
            return False
