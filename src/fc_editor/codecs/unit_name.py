from __future__ import annotations

import struct
from typing import Sequence
from ..dc_text import default_dc_text_table
from ..errors import RomFormatError
from ..rom_image import RomImage


class UnitNameReferenceCodec:
    """Stable unit-name editing by repointing to an existing localized name."""

    def __init__(
        self,
        rom: RomImage,
        data: bytes | bytearray | None = None,
        *,
        pointer_table_offset: int | None = None,
        pair_first_bank: int | None = None,
        original_pointers: Sequence[int] | None = None,
        pool_spans: Sequence[tuple[int, int]] | None = None,
    ) -> None:
        self.rom = rom
        profile = rom.profile
        self._source = rom.data if data is None else bytes(data)
        self.pointer_table_offset = (
            profile.unit_name_pointer_table_offset
            if pointer_table_offset is None
            else pointer_table_offset
        )
        self.pair_first_bank = pair_first_bank
        self.pool_spans = tuple(pool_spans or ())
        raw = self._source[
            self.pointer_table_offset : self.pointer_table_offset
            + profile.unit_name_count * 2
        ]
        if len(raw) != profile.unit_name_count * 2:
            raise RomFormatError("机体名称指针表不完整。")
        current_pointers = tuple(struct.unpack(f"<{profile.unit_name_count}H", raw))
        self.original_pointers = (
            current_pointers
            if original_pointers is None
            else tuple(int(pointer) for pointer in original_pointers)
        )
        if len(self.original_pointers) != profile.unit_name_count:
            raise RomFormatError("机体名称基准指针表长度无效。")
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
        if any(
            not 0x8000 <= start < end <= 0xC000
            for start, end in self.pool_spans
        ):
            raise RomFormatError("机体名称池边界必须位于一个 16 KiB Bank 对窗口内。")

    def pointer_offset(self, unit_id: int) -> int:
        if not 0 <= unit_id < self.rom.profile.unit_name_count:
            raise IndexError("名称 ID 必须在 00—FF 之间。")
        return self.pointer_table_offset + unit_id * 2

    def pointer(self, unit_id: int, data: bytes | bytearray | None = None) -> int:
        source = self._source if data is None else data
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
        pointer = self.canonical_pointer(source_name_id, data)
        if not pointer:
            raise ValueError("不能把机体名称指向空指针。")
        return offset, before, pointer.to_bytes(2, "little")

    def canonical_pointer(
        self,
        source_name_id: int,
        data: bytes | bytearray | None = None,
    ) -> int:
        """Resolve an immutable source identity after deterministic pool repacks."""

        source = self._source if data is None else data
        baseline = self.original_pointers[source_name_id]
        baseline_unique = sorted(pointer for pointer in self.ids_by_pointer if pointer)
        current_unique = sorted(
            {
                self.pointer(unit_id, source)
                for unit_id in range(1, self.rom.profile.unit_count)
                if self.pointer(unit_id, source)
            }
        )
        if len(current_unique) == len(baseline_unique):
            return current_unique[baseline_unique.index(baseline)]
        return baseline

    def source_ids(
        self,
        pointer: int,
        data: bytes | bytearray | None = None,
    ) -> tuple[int, ...]:
        source = self._source if data is None else data
        current_unique = sorted(
            {
                self.pointer(unit_id, source)
                for unit_id in range(1, self.rom.profile.unit_count)
                if self.pointer(unit_id, source)
            }
        )
        baseline_unique = sorted(
            pointer for pointer in self.ids_by_pointer if pointer
        )
        if len(current_unique) == len(baseline_unique) and pointer in current_unique:
            baseline = baseline_unique[current_unique.index(pointer)]
            return self.baseline_source_ids(baseline)
        return self.baseline_source_ids(pointer)

    def baseline_source_ids(self, pointer: int) -> tuple[int, ...]:
        return tuple(
            unit_id
            for unit_id in self.ids_by_pointer.get(pointer, ())
            if 1 <= unit_id < self.rom.profile.unit_count
        )

    def pointer_to_file_offset(self, pointer: int) -> int:
        if not any(start <= pointer < end for start, end in self.pool_spans):
            raise ValueError(f"机体名称 CPU 指针 ${pointer:04X} 超出已验证名称池。")
        bank = (
            self.pair_first_bank
            if self.pair_first_bank is not None
            else (self.pointer_table_offset - 16) // 0x2000
        )
        return 16 + bank * 0x2000 + pointer - 0x8000

    @staticmethod
    def _terminated_record(raw: bytes) -> bytes:
        """Return a name through its standalone FF terminator."""

        glyph_leads = frozenset(
            (*range(0xB8, 0xBC), *range(0xC8, 0xCC), *range(0xD8, 0xDC))
        )
        cursor = 0
        while cursor < len(raw):
            lead = raw[cursor]
            if lead in glyph_leads:
                if cursor + 1 >= len(raw):
                    raise RomFormatError("机体名称以不完整的双字节字形码结尾。")
                cursor += 2
                continue
            cursor += 1
            if lead == 0xFF:
                return raw[:cursor]
        raise RomFormatError("机体名称没有独立的 $FF 结束码。")

    def _record_for_pointer(self, source: bytes, pointer: int) -> bytes:
        for start, end in self.pool_spans:
            if start <= pointer < end:
                offset = self.pointer_to_file_offset(pointer)
                return self._terminated_record(source[offset : offset + end - pointer])
        raise ValueError(f"机体名称 CPU 指针 ${pointer:04X} 超出已验证名称池。")

    def record_bytes(
        self,
        unit_id: int,
        data: bytes | bytearray | None = None,
    ) -> bytes:
        source = bytes(self._source if data is None else data)
        pointer = self.pointer(unit_id, source)
        if not pointer:
            return b""
        return self._record_for_pointer(source, pointer)

    def repack_name(
        self,
        data: bytes | bytearray,
        unit_id: int,
        text: str,
    ) -> tuple[tuple[int, bytes, bytes], ...]:
        """Repack the aliased unit-name graph inside verified fixed spans."""

        if not self.pool_spans:
            raise ValueError("当前 ROM 尚未登记可重排的机体名称池。")
        if not 1 <= unit_id < self.rom.profile.unit_count:
            raise ValueError("机体 ID 超出当前 ROM 范围。")
        value = text.strip()
        if not value:
            raise ValueError("名称不能为空。")
        source = bytes(data)
        pointers = tuple(
            self.pointer(index, source)
            for index in range(self.rom.profile.unit_name_count)
        )
        unique = sorted({pointer for pointer in pointers if pointer})
        records = {
            pointer: self._record_for_pointer(source, pointer) for pointer in unique
        }
        target_pointer = pointers[unit_id]
        if not target_pointer:
            raise ValueError("当前机体名称为空指针，不能直接编辑。")
        old = records[target_pointer]
        encoded = default_dc_text_table().encode_preserving_tokens(old, value)
        records[target_pointer] = (
            encoded if encoded.endswith(b"\xFF") else encoded + b"\xFF"
        )
        baseline_unique = {pointer for pointer in self.ids_by_pointer if pointer}
        if len(unique) != len(baseline_unique):
            replacement = records[target_pointer]
            if len(replacement) != len(old):
                raise ValueError(
                    "机体名称存在已重定向、当前未被引用的规范记录；"
                    "请先恢复名称引用，或保持本次名称编码长度不变。"
                )
            offset = self.pointer_to_file_offset(target_pointer)
            return ((offset, source[offset : offset + len(old)], replacement),)

        assigned: dict[int, int] = {}
        span_payloads = [
            bytearray(b"\xFF" * (end - start)) for start, end in self.pool_spans
        ]
        span_index = 0
        cursor = self.pool_spans[0][0]
        for old_pointer in unique:
            raw = records[old_pointer]
            while (
                span_index < len(self.pool_spans)
                and cursor + len(raw) > self.pool_spans[span_index][1]
            ):
                span_index += 1
                if span_index < len(self.pool_spans):
                    cursor = self.pool_spans[span_index][0]
            if span_index >= len(self.pool_spans):
                required = sum(len(record) for record in records.values())
                capacity = sum(end - start for start, end in self.pool_spans)
                raise ValueError(
                    f"机体名称共享池容量不足：记录共需 {required} 字节，"
                    f"固定容量为 {capacity} 字节；请先缩短其他机体名称。"
                )
            start, _end = self.pool_spans[span_index]
            assigned[old_pointer] = cursor
            relative = cursor - start
            span_payloads[span_index][relative : relative + len(raw)] = raw
            cursor += len(raw)

        new_pointers = tuple(
            0 if pointer == 0 else assigned[pointer] for pointer in pointers
        )
        table_size = len(new_pointers) * 2
        patches: list[tuple[int, bytes, bytes]] = [
            (
                self.pointer_table_offset,
                source[self.pointer_table_offset : self.pointer_table_offset + table_size],
                struct.pack(f"<{len(new_pointers)}H", *new_pointers),
            )
        ]
        for (start, end), payload in zip(self.pool_spans, span_payloads):
            offset = self.pointer_to_file_offset(start)
            patches.append((offset, source[offset : offset + end - start], bytes(payload)))
        return tuple(patch for patch in patches if patch[1] != patch[2])
