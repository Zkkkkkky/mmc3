from __future__ import annotations

import struct

from ..dc_text import default_dc_text_table
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
        self.normal_pointers: tuple[int, ...] = ()
        if profile.character_normal_name_pointer_table_offset is not None:
            if profile.character_normal_name_count <= 0:
                raise RomFormatError("人物显示名称数量无效。")
            raw = rom.read(
                profile.character_normal_name_pointer_table_offset,
                profile.character_normal_name_count * 2,
            )
            self.normal_pointers = tuple(
                struct.unpack(f"<{profile.character_normal_name_count}H", raw)
            )
            if any(
                not profile.character_name_first_pointer
                <= pointer
                < profile.character_name_data_end_pointer
                for pointer in self.normal_pointers
            ):
                raise RomFormatError("人物显示名称指针超出已验证数据区。")

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

    def normal_pointer_offset(self, character_id: int) -> int:
        profile = self.rom.profile
        offset = profile.character_normal_name_pointer_table_offset
        if offset is None or not 1 <= character_id <= profile.character_normal_name_count:
            raise IndexError(
                f"人物显示名称 ID 必须在 01—{profile.character_normal_name_count:02X} 之间。"
            )
        return offset + (character_id - 1) * 2

    def normal_pointer(
        self, character_id: int, data: bytes | bytearray | None = None
    ) -> int:
        source = self.rom.data if data is None else data
        offset = self.normal_pointer_offset(character_id)
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

    def _capacity(self, pointer: int, data: bytes | bytearray) -> int:
        profile = self.rom.profile
        assert profile.character_name_data_end_pointer is not None
        pointers = sorted(set(self._current_pointers(data)))
        if pointer not in pointers:
            raise ValueError(f"人物名称 CPU 指针 ${pointer:04X} 未被当前名称表引用。")
        following = next(
            (candidate for candidate in pointers if candidate > pointer),
            profile.character_name_data_end_pointer,
        )
        return following - pointer

    def _terminated_record(self, pointer: int, data: bytes | bytearray) -> bytes:
        offset = self.pointer_to_file_offset(pointer)
        capacity = self._capacity(pointer, data)
        raw = bytes(data[offset : offset + capacity])
        end = raw.find(b"\xFF")
        if end < 0:
            raise RomFormatError(f"人物名称 ${pointer:04X} 缺少结束码。")
        return raw[: end + 1]

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
        capacity = self._capacity(pointer, source)
        return bytes(source[offset : offset + capacity])

    def normal_record_bytes(
        self,
        character_id: int,
        data: bytes | bytearray | None = None,
    ) -> bytes:
        source = self.rom.data if data is None else data
        pointer = self.normal_pointer(character_id, source)
        offset = self.pointer_to_file_offset(pointer)
        capacity = self._capacity(pointer, source)
        return bytes(source[offset : offset + capacity])

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
        offset = self.pointer_offset(character_id)
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
        normal_records = [
            self._terminated_record(self.normal_pointer(index, source), source)
            for index in range(1, profile.character_normal_name_count + 1)
        ]
        battle_records: list[bytes] = [b""]
        battle_records.extend(
            self._terminated_record(self.pointer(index, source), source)
            for index in range(1, profile.character_name_count)
        )
        table = default_dc_text_table()

        def encode_name(old: bytes, text: str) -> bytes:
            encoded = table.encode_preserving_tokens(old, text)
            return encoded if encoded.endswith(b"\xFF") else encoded + b"\xFF"

        if normal_text is not None:
            old = normal_records[character_id - 1]
            normal_records[character_id - 1] = encode_name(old, normal_text)
        if battle_text is not None:
            if character_id >= profile.character_name_count:
                raise ValueError(f"人物 ${character_id:02X} 没有战斗名称槽。")
            old = battle_records[character_id]
            battle_records[character_id] = encode_name(old, battle_text)
        for raw in (*normal_records, *battle_records[1:]):
            if not raw or raw[-1] != 0xFF:
                raise ValueError("人物名称必须保留结束码。")

        assert profile.character_name_first_pointer is not None
        assert profile.character_name_data_end_pointer is not None
        cursor = profile.character_name_first_pointer
        packed = bytearray()
        assigned: dict[bytes, int] = {}

        def allocate(raw: bytes) -> int:
            nonlocal cursor
            if raw in assigned:
                return assigned[raw]
            pointer = cursor
            cursor += len(raw)
            if cursor > profile.character_name_data_end_pointer:
                capacity = (
                    profile.character_name_data_end_pointer
                    - profile.character_name_first_pointer
                )
                raise ValueError(
                    f"人物名称共享池容量不足：需要 {cursor - profile.character_name_first_pointer} "
                    f"字节，固定容量为 {capacity} 字节。"
                )
            assigned[raw] = pointer
            packed.extend(raw)
            return pointer

        normal_pointers = tuple(allocate(raw) for raw in normal_records)
        battle_pointers = (0, *(allocate(raw) for raw in battle_records[1:]))
        pool_offset = self.pointer_to_file_offset(profile.character_name_first_pointer)
        pool_size = (
            profile.character_name_data_end_pointer
            - profile.character_name_first_pointer
        )
        after_pool = bytes(packed) + source[
            pool_offset + len(packed) : pool_offset + pool_size
        ]
        assert profile.character_normal_name_pointer_table_offset is not None
        normal_offset = profile.character_normal_name_pointer_table_offset
        battle_offset = profile.character_name_pointer_table_offset
        assert battle_offset is not None
        patches = (
            (
                normal_offset,
                source[normal_offset : normal_offset + len(normal_pointers) * 2],
                struct.pack(f"<{len(normal_pointers)}H", *normal_pointers),
            ),
            (
                pool_offset,
                source[pool_offset : pool_offset + pool_size],
                after_pool,
            ),
            (
                battle_offset,
                source[battle_offset : battle_offset + len(battle_pointers) * 2],
                struct.pack(f"<{len(battle_pointers)}H", *battle_pointers),
            ),
        )
        return tuple(patch for patch in patches if patch[1] != patch[2])

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
