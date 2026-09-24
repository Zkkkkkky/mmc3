from __future__ import annotations

import struct

from ..dc_text import default_dc_text_table
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

    def pointer(self, weapon_id: int, data: bytes | bytearray | None = None) -> int:
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

    def record_bytes(
        self, weapon_id: int, data: bytes | bytearray | None = None
    ) -> bytes:
        source = self.rom.data if data is None else data
        pointer = self.pointer(weapon_id, source)
        offset = self.pointer_to_file_offset(pointer)
        pointers = sorted(
            set(
                self.pointer(index, source)
                for index in range(self.rom.profile.weapon_name_pointer_count)
            )
        )
        position = pointers.index(pointer)
        end = (
            pointers[position + 1]
            if position + 1 < len(pointers)
            else self.rom.profile.weapon_name_data_end_pointer
        )
        assert end is not None
        return bytes(source[offset : offset + end - pointer])

    def source_ids(
        self, pointer: int, data: bytes | bytearray | None = None
    ) -> tuple[int, ...]:
        source = self.rom.data if data is None else data
        return tuple(
            weapon_id
            for weapon_id in range(self.rom.profile.weapon_name_pointer_count)
            if self.pointer(weapon_id, source) == pointer
            if 1 <= weapon_id < self.rom.profile.weapon_count
        )

    @staticmethod
    def _terminated_record(raw: bytes) -> bytes:
        """Return one name through its standalone FF terminator.

        FF can be the low byte of a two-byte Chinese glyph, so byte.find()
        cannot be used here.
        """

        glyph_leads = frozenset(
            (*range(0xB8, 0xBC), *range(0xC8, 0xCC), *range(0xD8, 0xDC))
        )
        cursor = 0
        while cursor < len(raw):
            lead = raw[cursor]
            if lead in glyph_leads:
                if cursor + 1 >= len(raw):
                    raise RomFormatError("武器名称以不完整的双字节字形码结尾。")
                cursor += 2
                continue
            cursor += 1
            if lead == 0xFF:
                return raw[:cursor]
        raise RomFormatError("武器名称没有独立的 $FF 结束码。")

    def repack_name(
        self,
        data: bytes | bytearray,
        weapon_id: int,
        text: str,
    ) -> tuple[tuple[int, bytes, bytes], ...]:
        """Repack all weapon names and pointers inside the verified pool."""

        profile = self.rom.profile
        if not 1 <= weapon_id < profile.weapon_count:
            raise ValueError(
                f"武器 ID 必须在 01—{profile.weapon_count - 1:02X} 之间。"
            )
        value = text.strip()
        if not value:
            raise ValueError("名称不能为空。")
        source = bytes(data)
        current = self._current_records(source)
        old = current[1][current[0][weapon_id]]
        encoded = default_dc_text_table().encode_preserving_tokens(old, value)
        replacement = encoded if encoded.endswith(b"\xFF") else encoded + b"\xFF"
        return self._repack_raw(source, weapon_id, replacement, current=current)

    def _current_records(
        self, source: bytes
    ) -> tuple[tuple[int, ...], dict[int, bytes]]:
        profile = self.rom.profile
        pointers = tuple(
            self.pointer(index, source)
            for index in range(profile.weapon_name_pointer_count)
        )
        unique_pointers = sorted(set(pointers))
        pool_offset = self.pointer_to_file_offset(profile.weapon_name_first_pointer)
        pool_file_end = pool_offset + (
            profile.weapon_name_data_end_pointer
            - profile.weapon_name_first_pointer
        )
        records: dict[int, bytes] = {}
        for position, pointer in enumerate(unique_pointers):
            start = self.pointer_to_file_offset(pointer)
            end = (
                self.pointer_to_file_offset(unique_pointers[position + 1])
                if position + 1 < len(unique_pointers)
                else pool_file_end
            )
            records[pointer] = self._terminated_record(bytes(source[start:end]))
        return pointers, records

    def repack_raw(
        self,
        data: bytes | bytearray,
        weapon_id: int,
        replacement: bytes,
    ) -> tuple[tuple[int, bytes, bytes], ...]:
        if not 1 <= weapon_id < self.rom.profile.weapon_count:
            raise ValueError("武器 ID 超出当前 ROM 范围。")
        raw = self._terminated_record(bytes(replacement))
        if len(raw) != len(replacement):
            raise ValueError("武器名称结束码后不能包含额外字节。")
        source = bytes(data)
        return self._repack_raw(source, weapon_id, raw)

    def _repack_raw(
        self,
        source: bytes,
        weapon_id: int,
        replacement: bytes,
        *,
        current: tuple[tuple[int, ...], dict[int, bytes]] | None = None,
    ) -> tuple[tuple[int, bytes, bytes], ...]:
        profile = self.rom.profile
        pointers, records = self._current_records(source) if current is None else current
        unique_pointers = sorted(records)
        records[pointers[weapon_id]] = bytes(replacement)

        assert profile.weapon_name_first_pointer is not None
        assert profile.weapon_name_data_end_pointer is not None
        cursor = profile.weapon_name_first_pointer
        assigned_by_source: dict[int, int] = {}
        packed = bytearray()
        for pointer in unique_pointers:
            raw = records[pointer]
            assigned_by_source[pointer] = cursor
            cursor += len(raw)
            if cursor > profile.weapon_name_data_end_pointer:
                capacity = (
                    profile.weapon_name_data_end_pointer
                    - profile.weapon_name_first_pointer
                )
                raise ValueError(
                    f"武器名称共享池容量不足：需要 "
                    f"{cursor - profile.weapon_name_first_pointer} 字节，"
                    f"固定容量为 {capacity} 字节。请缩短其他武器名称。"
                )
            packed.extend(raw)

        new_pointers = tuple(assigned_by_source[pointer] for pointer in pointers)
        table_offset = profile.weapon_name_pointer_table_offset
        assert table_offset is not None
        table_size = profile.weapon_name_pointer_count * 2
        pool_size = (
            profile.weapon_name_data_end_pointer
            - profile.weapon_name_first_pointer
        )
        pool_offset = self.pointer_to_file_offset(profile.weapon_name_first_pointer)
        after_pool = bytes(packed) + b"\xFF" * (pool_size - len(packed))
        patches = (
            (
                table_offset,
                source[table_offset : table_offset + table_size],
                struct.pack(f"<{len(new_pointers)}H", *new_pointers),
            ),
            (
                pool_offset,
                source[pool_offset : pool_offset + pool_size],
                after_pool,
            ),
        )
        return tuple(patch for patch in patches if patch[1] != patch[2])

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
        pointer = self.pointer(source_name_id, data)
        return offset, before, pointer.to_bytes(2, "little")

    def round_trip(self, weapon_id: int) -> bool:
        pointer = self.pointer(weapon_id)
        return (
            pointer == self.original_pointers[weapon_id]
            and len(self.record_bytes(weapon_id)) == self.capacities.get(pointer)
        )
