from __future__ import annotations

from collections.abc import Iterable, Sequence

from ..errors import RomFormatError
from ..profiles import LegacyGlobalDataSpec
from ..rom_image import RomImage


BytePatch = tuple[int, bytes, bytes]
InitialRoster = tuple[tuple[int, int], ...]
DistanceHitCorrections = tuple[tuple[int, ...], ...]
ItemNameRecords = tuple[bytes, ...]
OperandContext = tuple[int, bytes, bytes]


class LegacyGlobalDataCodec:
    """Decode and patch global tables whose operands were verified in SRW2 V1.5."""

    DISTANCE_ROW_COUNT = 4
    DISTANCE_COLUMN_COUNT = 16
    EXPERIENCE_TOTAL_COUNT = 99
    INITIAL_ROSTER_COUNT = 6
    INITIAL_ROSTER_SENTINEL = 0xFF
    ITEM_NAME_TERMINATOR = 0xFF
    DAMAGE_NONZERO_INDICES = (2, 4)

    # Each signature is (editable operand offset, fixed prefix, fixed suffix).
    # The operand byte itself is deliberately absent: projects saved after a
    # legitimate edit must still reopen, while a changed opcode, destination,
    # call target, or surrounding instruction makes the codec fail closed.
    # These fixed bytes are identical in 新DC.nes, DC_kuorong.nes, and the
    # recommended 464K output.
    DOUBLE_HIT_CONTEXTS: tuple[OperandContext, ...] = (
        (0x78109, bytes.fromhex("A5 B1 85 01 A9"), bytes.fromhex("85 08 20 0C C0")),
        (0x7815A, bytes.fromhex("A5 B3 85 01 A9"), bytes.fromhex("85 08 20 0C C0")),
        (0x78127, bytes.fromhex("A5 B3 85 01 A9"), bytes.fromhex("85 08 20 0C C0")),
        (0x78178, bytes.fromhex("A5 B1 85 01 A9"), bytes.fromhex("85 08 20 0C C0")),
        (
            0x78138,
            bytes.fromhex("A5 10 18 69"),
            bytes.fromhex("85 00 A5 11 69 00 85 01"),
        ),
        (
            0x78189,
            bytes.fromhex("A5 10 18 69"),
            bytes.fromhex("85 00 A5 11 69 00 85 01"),
        ),
    )
    DAMAGE_FORMULA_CONTEXTS: tuple[OperandContext, ...] = (
        (
            0x780E4,
            bytes.fromhex("A5 B0 85 01 A9"),
            bytes.fromhex("85 08 20 0C C0"),
        ),
        (
            0x780C5,
            bytes.fromhex("4C A5 80 EA A9"),
            bytes.fromhex("85 08 20 0C C0"),
        ),
        (
            0x780EB,
            bytes.fromhex("20 0C C0 A9"),
            bytes.fromhex("85 08 20 12 C0"),
        ),
        (
            0x9999,
            bytes.fromhex("20 00 A5 EA A9"),
            bytes.fromhex("85 08 20 0C C0"),
        ),
        (
            0x99A0,
            bytes.fromhex("20 0C C0 A9"),
            bytes.fromhex("85 08 20 12 C0"),
        ),
    )
    HIT_THRESHOLD_CONTEXTS: tuple[OperandContext, ...] = (
        (
            0xA44E,
            bytes.fromhex("A5 00 C9"),
            bytes.fromhex("B0 07 A9 00 85 15"),
        ),
    )
    ITEM_EFFECT_CONTEXTS: tuple[OperandContext, ...] = (
        (0x140CF, bytes.fromhex("A9"), bytes.fromhex("85 EF 4C EC 83")),
        (0x140D6, bytes.fromhex("A9"), bytes.fromhex("85 EF 4C 58 84")),
        (0x140DD, bytes.fromhex("A9"), bytes.fromhex("85 EF 4C 80 83")),
        (0x140E4, bytes.fromhex("A9"), bytes.fromhex("85 EF 4C C4 84")),
        (0x140EB, bytes.fromhex("A9"), bytes.fromhex("85 EF 4C EC 83")),
        (0x140F2, bytes.fromhex("A9"), bytes.fromhex("85 EF 4C FE 82")),
        (0x140F9, bytes.fromhex("A9"), bytes.fromhex("85 EF 4C 80 83")),
        (0x14100, bytes.fromhex("A9"), bytes.fromhex("85 EF 4C 58 84")),
        (0x14107, bytes.fromhex("A9"), bytes.fromhex("85 EF 4C C4 84")),
        (0x1410E, bytes.fromhex("A9"), bytes.fromhex("85 EF 4C 5F 86")),
        (0x14115, bytes.fromhex("A9"), bytes.fromhex("85 EF 4C 5F 86")),
    )

    def __init__(
        self,
        rom: RomImage,
        data: bytes | bytearray | None = None,
    ) -> None:
        spec = rom.profile.legacy_global_data
        if spec is None:
            raise RomFormatError(f"“{rom.profile.label}”没有已验证的全局数据表。")
        self.rom = rom
        self.spec: LegacyGlobalDataSpec = spec
        source = rom.data if data is None else data
        self._validate_boundaries(source)
        self._validate_all_code_contexts(source)
        self.double_hit_values(source)
        self.damage_formula_values(source)
        self.initial_roster(source)
        self.item_name_records(source)
        self.item_prices(source)

    @staticmethod
    def _require_range(
        data: bytes | bytearray,
        offset: int,
        size: int,
        label: str,
    ) -> None:
        if offset < 0 or size < 0 or offset + size > len(data):
            raise RomFormatError(
                f"{label}范围 0x{offset:X}—0x{offset + size:X} 超出 ROM。"
            )

    def _validate_boundaries(self, data: bytes | bytearray) -> None:
        self._require_range(
            data,
            self.spec.distance_hit_table_offset,
            self.DISTANCE_ROW_COUNT * self.DISTANCE_COLUMN_COUNT,
            "距离命中修正表",
        )
        self._require_range(
            data,
            self.spec.experience_totals_offset,
            self.EXPERIENCE_TOTAL_COUNT * 2,
            "累计经验表",
        )
        self._require_range(
            data,
            self.spec.item_name_pointer_table_offset,
            self.spec.item_count * 2,
            "道具名称指针表",
        )
        self._require_range(
            data,
            self.spec.item_name_pool_start_offset,
            self.spec.item_name_pool_end_offset
            - self.spec.item_name_pool_start_offset,
            "道具名称文本池",
        )
        self._require_range(
            data,
            self.spec.item_price_table_offset,
            self.spec.item_count * 2,
            "道具价格表",
        )
        self._require_range(
            data,
            self.spec.initial_roster_offset,
            self.INITIAL_ROSTER_COUNT * 2 + 1,
            "初始人物/机体表",
        )
        for label, offsets in (
            ("双击公式操作数", tuple(
                offset
                for pair in self.spec.double_hit_operand_pairs
                for offset in pair
            )),
            ("伤害公式操作数", self.spec.damage_formula_operand_offsets),
            ("道具效果操作数", self.spec.item_effect_operand_offsets),
            ("命中阈值操作数", (self.spec.hit_threshold_operand_offset,)),
        ):
            for offset in offsets:
                self._require_range(data, offset, 1, label)

    def _validate_operand_contexts(
        self,
        data: bytes | bytearray,
        label: str,
        configured_offsets: Sequence[int],
        contexts: Sequence[OperandContext],
    ) -> None:
        signature_offsets = tuple(context[0] for context in contexts)
        if tuple(configured_offsets) != signature_offsets:
            raise RomFormatError(f"{label}操作数配置与代码上下文签名不一致。")

        for operand_offset, prefix, suffix in contexts:
            start = operand_offset - len(prefix)
            size = len(prefix) + 1 + len(suffix)
            self._require_range(data, start, size, f"{label}代码上下文")
            actual_prefix = bytes(data[start:operand_offset])
            actual_suffix = bytes(
                data[operand_offset + 1 : operand_offset + 1 + len(suffix)]
            )
            if actual_prefix == prefix and actual_suffix == suffix:
                continue

            mismatch_offset = next(
                (
                    start + index
                    for index, (actual, expected) in enumerate(
                        zip(actual_prefix, prefix)
                    )
                    if actual != expected
                ),
                None,
            )
            if mismatch_offset is None:
                mismatch_offset = next(
                    operand_offset + 1 + index
                    for index, (actual, expected) in enumerate(
                        zip(actual_suffix, suffix)
                    )
                    if actual != expected
                )
            raise RomFormatError(
                f"{label}操作数 0x{operand_offset:X} 的代码上下文签名不匹配"
                f"（固定字节 0x{mismatch_offset:X}）。"
            )

    def _validate_double_hit_contexts(self, data: bytes | bytearray) -> None:
        offsets = tuple(
            offset
            for pair in self.spec.double_hit_operand_pairs
            for offset in pair
        )
        self._validate_operand_contexts(
            data,
            "双击公式",
            offsets,
            self.DOUBLE_HIT_CONTEXTS,
        )

    def _validate_damage_formula_contexts(self, data: bytes | bytearray) -> None:
        self._validate_operand_contexts(
            data,
            "伤害公式",
            self.spec.damage_formula_operand_offsets,
            self.DAMAGE_FORMULA_CONTEXTS,
        )

    def _validate_hit_threshold_contexts(self, data: bytes | bytearray) -> None:
        self._validate_operand_contexts(
            data,
            "命中阈值",
            (self.spec.hit_threshold_operand_offset,),
            self.HIT_THRESHOLD_CONTEXTS,
        )

    def _validate_item_effect_contexts(self, data: bytes | bytearray) -> None:
        self._validate_operand_contexts(
            data,
            "道具效果",
            self.spec.item_effect_operand_offsets,
            self.ITEM_EFFECT_CONTEXTS,
        )

    def _validate_all_code_contexts(self, data: bytes | bytearray) -> None:
        self._validate_double_hit_contexts(data)
        self._validate_damage_formula_contexts(data)
        self._validate_hit_threshold_contexts(data)
        self._validate_item_effect_contexts(data)

    @staticmethod
    def _u8_values(
        values: Iterable[int],
        count: int,
        label: str,
        *,
        nonzero_indices: Sequence[int] = (),
    ) -> tuple[int, ...]:
        result = tuple(values)
        if len(result) != count:
            raise ValueError(f"{label}必须包含 {count} 个数值。")
        if any(not isinstance(value, int) or not 0 <= value <= 0xFF for value in result):
            raise ValueError(f"{label}每项必须在 0—255 之间。")
        for index in nonzero_indices:
            if result[index] == 0:
                raise ValueError(f"{label}第 {index + 1} 项不能为 0。")
        return result

    @staticmethod
    def _u16_values(values: Iterable[int], count: int, label: str) -> tuple[int, ...]:
        result = tuple(values)
        if len(result) != count:
            raise ValueError(f"{label}必须包含 {count} 个数值。")
        if any(not isinstance(value, int) or not 0 <= value <= 0xFFFF for value in result):
            raise ValueError(f"{label}每项必须在 0—65535 之间。")
        return result

    @staticmethod
    def _operand_patches(
        data: bytes | bytearray,
        offsets: Sequence[int],
        values: Sequence[int],
    ) -> tuple[BytePatch, ...]:
        return tuple(
            (offset, bytes((data[offset],)), bytes((value,)))
            for offset, value in zip(offsets, values)
        )

    def double_hit_values(
        self, data: bytes | bytearray | None = None
    ) -> tuple[int, int, int]:
        source = self.rom.data if data is None else data
        values: list[int] = []
        for index, (first, mirror) in enumerate(self.spec.double_hit_operand_pairs):
            self._require_range(source, first, 1, "双击公式操作数")
            self._require_range(source, mirror, 1, "双击公式镜像操作数")
            if source[first] != source[mirror]:
                raise RomFormatError(
                    f"双击公式第 {index + 1} 项的两个镜像操作数不一致。"
                )
            values.append(source[first])
        return values[0], values[1], values[2]

    def double_hit_patches(
        self, data: bytes | bytearray, values: Iterable[int]
    ) -> tuple[BytePatch, ...]:
        normalized = self._u8_values(values, 3, "双击公式")
        offsets = tuple(
            offset
            for pair in self.spec.double_hit_operand_pairs
            for offset in pair
        )
        mirrored_values = tuple(value for value in normalized for _ in range(2))
        self._validate_boundaries(data)
        self._validate_double_hit_contexts(data)
        return self._operand_patches(data, offsets, mirrored_values)

    def damage_formula_values(
        self, data: bytes | bytearray | None = None
    ) -> tuple[int, int, int, int, int]:
        source = self.rom.data if data is None else data
        self._validate_boundaries(source)
        result = tuple(source[offset] for offset in self.spec.damage_formula_operand_offsets)
        self._u8_values(
            result,
            5,
            "伤害公式",
            nonzero_indices=self.DAMAGE_NONZERO_INDICES,
        )
        return result  # type: ignore[return-value]

    def damage_formula_patches(
        self, data: bytes | bytearray, values: Iterable[int]
    ) -> tuple[BytePatch, ...]:
        normalized = self._u8_values(
            values,
            5,
            "伤害公式",
            nonzero_indices=self.DAMAGE_NONZERO_INDICES,
        )
        self._validate_boundaries(data)
        self._validate_damage_formula_contexts(data)
        return self._operand_patches(
            data, self.spec.damage_formula_operand_offsets, normalized
        )

    def hit_threshold(self, data: bytes | bytearray | None = None) -> int:
        source = self.rom.data if data is None else data
        offset = self.spec.hit_threshold_operand_offset
        self._require_range(source, offset, 1, "命中阈值操作数")
        return source[offset]

    def hit_threshold_patches(
        self, data: bytes | bytearray, value: int
    ) -> tuple[BytePatch, ...]:
        normalized = self._u8_values((value,), 1, "命中阈值")
        self._validate_boundaries(data)
        self._validate_hit_threshold_contexts(data)
        return self._operand_patches(
            data, (self.spec.hit_threshold_operand_offset,), normalized
        )

    def item_effect_values(
        self, data: bytes | bytearray | None = None
    ) -> tuple[int, ...]:
        source = self.rom.data if data is None else data
        self._validate_boundaries(source)
        return tuple(source[offset] for offset in self.spec.item_effect_operand_offsets)

    def item_effect_patches(
        self, data: bytes | bytearray, values: Iterable[int]
    ) -> tuple[BytePatch, ...]:
        normalized = self._u8_values(values, 11, "道具效果")
        self._validate_boundaries(data)
        self._validate_item_effect_contexts(data)
        return self._operand_patches(data, self.spec.item_effect_operand_offsets, normalized)

    def _item_name_file_offset(self, cpu_pointer: int) -> int:
        return self.spec.item_name_bank_file_base + (
            cpu_pointer - self.spec.item_name_bank_window_base
        )

    def _item_name_cpu_pointer(self, file_offset: int) -> int:
        cpu_pointer = self.spec.item_name_bank_window_base + (
            file_offset - self.spec.item_name_bank_file_base
        )
        if not 0 <= cpu_pointer <= 0xFFFF:
            raise RomFormatError("道具名称文本池无法用 16 位 CPU 指针表示。")
        return cpu_pointer

    def item_name_records(
        self, data: bytes | bytearray | None = None
    ) -> ItemNameRecords:
        source = self.rom.data if data is None else data
        self._validate_boundaries(source)
        table_offset = self.spec.item_name_pointer_table_offset
        pointers = tuple(
            int.from_bytes(source[offset : offset + 2], "little")
            for offset in range(
                table_offset,
                table_offset + self.spec.item_count * 2,
                2,
            )
        )
        file_offsets = tuple(
            self._item_name_file_offset(pointer) for pointer in pointers
        )
        pool_start = self.spec.item_name_pool_start_offset
        pool_end = self.spec.item_name_pool_end_offset
        for index, offset in enumerate(file_offsets):
            if not pool_start <= offset < pool_end:
                raise RomFormatError(
                    f"道具名称第 {index + 1} 项指针超出文本池。"
                )
            if index and offset == file_offsets[index - 1]:
                raise RomFormatError("道具名称指针表含有重复指针。")
            if index and offset < file_offsets[index - 1]:
                raise RomFormatError("道具名称指针表不是严格递增顺序。")

        records: list[bytes] = []
        for index, offset in enumerate(file_offsets):
            limit = file_offsets[index + 1] if index + 1 < len(file_offsets) else pool_end
            terminator = source.find(bytes((self.ITEM_NAME_TERMINATOR,)), offset, limit)
            if terminator < 0:
                raise RomFormatError(
                    f"道具名称第 {index + 1} 项在下一指针前缺少 $FF 终止符。"
                )
            records.append(bytes(source[offset:terminator]))
        return tuple(records)

    def _normalize_item_name_records(
        self, records: Iterable[bytes]
    ) -> ItemNameRecords:
        result = tuple(records)
        if len(result) != self.spec.item_count:
            raise ValueError(f"道具名称必须包含 {self.spec.item_count} 条记录。")
        normalized: list[bytes] = []
        for index, record in enumerate(result):
            if not isinstance(record, (bytes, bytearray)):
                raise ValueError(f"道具名称第 {index + 1} 项必须是原始字节。")
            value = bytes(record)
            if self.ITEM_NAME_TERMINATOR in value:
                raise ValueError(
                    f"道具名称第 {index + 1} 项不得包含 $FF 终止符。"
                )
            normalized.append(value)

        capacity = (
            self.spec.item_name_pool_end_offset
            - self.spec.item_name_pool_start_offset
        )
        required = sum(len(record) + 1 for record in normalized)
        if required > capacity:
            raise ValueError(
                f"道具名称需要 {required} 字节，超过文本池 {capacity} 字节容量。"
            )
        return tuple(normalized)

    def item_name_record_patches(
        self,
        data: bytes | bytearray,
        records: Iterable[bytes],
    ) -> tuple[BytePatch, ...]:
        self.item_name_records(data)
        normalized = self._normalize_item_name_records(records)
        pool_start = self.spec.item_name_pool_start_offset
        pool_end = self.spec.item_name_pool_end_offset
        cursor = pool_start
        pointers: list[int] = []
        payload_parts: list[bytes] = []
        for record in normalized:
            pointers.append(self._item_name_cpu_pointer(cursor))
            terminated = record + bytes((self.ITEM_NAME_TERMINATOR,))
            payload_parts.append(terminated)
            cursor += len(terminated)

        pointer_payload = b"".join(
            pointer.to_bytes(2, "little") for pointer in pointers
        )
        pool_payload = b"".join(payload_parts) + bytes((self.ITEM_NAME_TERMINATOR,)) * (
            pool_end - cursor
        )
        table_offset = self.spec.item_name_pointer_table_offset
        return (
            (
                table_offset,
                bytes(data[table_offset : table_offset + len(pointer_payload)]),
                pointer_payload,
            ),
            (
                pool_start,
                bytes(data[pool_start:pool_end]),
                pool_payload,
            ),
        )

    def item_name_storage_copy_patches(
        self,
        data: bytes | bytearray,
        source: bytes | bytearray,
    ) -> tuple[BytePatch, ...]:
        """Copy the complete verified name storage without normalizing its layout.

        Legal ROMs may leave gaps in the fixed pool or choose non-canonical glyph
        byte aliases.  A reset must restore those bytes and pointers exactly,
        rather than decoding the names and tightly repacking equivalent text.
        """

        self._validate_boundaries(data)
        self.item_name_records(source)
        table_start = self.spec.item_name_pointer_table_offset
        table_end = table_start + self.spec.item_count * 2
        pool_start = self.spec.item_name_pool_start_offset
        pool_end = self.spec.item_name_pool_end_offset
        return (
            (
                table_start,
                bytes(data[table_start:table_end]),
                bytes(source[table_start:table_end]),
            ),
            (
                pool_start,
                bytes(data[pool_start:pool_end]),
                bytes(source[pool_start:pool_end]),
            ),
        )

    def item_prices(
        self, data: bytes | bytearray | None = None
    ) -> tuple[int, ...]:
        source = self.rom.data if data is None else data
        offset = self.spec.item_price_table_offset
        size = self.spec.item_count * 2
        self._require_range(source, offset, size, "道具价格表")
        return tuple(
            int.from_bytes(source[position : position + 2], "little")
            for position in range(offset, offset + size, 2)
        )

    def item_price_patches(
        self,
        data: bytes | bytearray,
        values: Iterable[int],
    ) -> tuple[BytePatch, ...]:
        normalized = self._u16_values(values, self.spec.item_count, "道具价格表")
        offset = self.spec.item_price_table_offset
        payload = b"".join(value.to_bytes(2, "little") for value in normalized)
        self._require_range(data, offset, len(payload), "道具价格表")
        return ((offset, bytes(data[offset : offset + len(payload)]), payload),)

    def initial_roster(
        self, data: bytes | bytearray | None = None
    ) -> InitialRoster:
        source = self.rom.data if data is None else data
        offset = self.spec.initial_roster_offset
        size = self.INITIAL_ROSTER_COUNT * 2
        self._require_range(source, offset, size + 1, "初始人物/机体表")
        if source[offset + size] != self.INITIAL_ROSTER_SENTINEL:
            raise RomFormatError("初始人物/机体表缺少 $FF 结束哨兵。")
        result = tuple(
            (source[offset + index * 2], source[offset + index * 2 + 1])
            for index in range(self.INITIAL_ROSTER_COUNT)
        )
        self.validate_initial_roster(result)
        return result

    def validate_initial_roster(
        self, roster: Iterable[tuple[int, int]]
    ) -> InitialRoster:
        result = tuple(roster)
        if len(result) != self.INITIAL_ROSTER_COUNT:
            raise ValueError(
                f"初始阵容必须包含 {self.INITIAL_ROSTER_COUNT} 组人物/机体。"
            )
        normalized: list[tuple[int, int]] = []
        for index, pair in enumerate(result):
            if not isinstance(pair, (tuple, list)) or len(pair) != 2:
                raise ValueError(f"初始阵容第 {index + 1} 组必须是人物/机体 ID 对。")
            character_id, unit_id = pair
            if not isinstance(character_id, int) or not (
                0 <= character_id < self.rom.profile.character_name_count
            ):
                raise ValueError(
                    f"人物 ID 必须在 00—{self.rom.profile.character_name_count - 1:02X} 之间。"
                )
            if not isinstance(unit_id, int) or not (
                0 <= unit_id < self.rom.profile.unit_count
            ):
                raise ValueError(
                    f"机体 ID 必须在 00—{self.rom.profile.unit_count - 1:02X} 之间。"
                )
            normalized.append((character_id, unit_id))
        return tuple(normalized)

    def initial_roster_patches(
        self,
        data: bytes | bytearray,
        roster: Iterable[tuple[int, int]],
    ) -> tuple[BytePatch, ...]:
        normalized = self.validate_initial_roster(roster)
        offset = self.spec.initial_roster_offset
        size = self.INITIAL_ROSTER_COUNT * 2
        self._require_range(data, offset, size + 1, "初始人物/机体表")
        if data[offset + size] != self.INITIAL_ROSTER_SENTINEL:
            raise RomFormatError("初始人物/机体表缺少 $FF 结束哨兵。")
        payload = bytes(value for pair in normalized for value in pair)
        return ((offset, bytes(data[offset : offset + size]), payload),)

    def distance_hit_corrections(
        self, data: bytes | bytearray | None = None
    ) -> DistanceHitCorrections:
        source = self.rom.data if data is None else data
        offset = self.spec.distance_hit_table_offset
        size = self.DISTANCE_ROW_COUNT * self.DISTANCE_COLUMN_COUNT
        self._require_range(source, offset, size, "距离命中修正表")
        return tuple(
            tuple(
                source[
                    offset
                    + row * self.DISTANCE_COLUMN_COUNT
                    + column
                ]
                for column in range(self.DISTANCE_COLUMN_COUNT)
            )
            for row in range(self.DISTANCE_ROW_COUNT)
        )

    def distance_hit_correction_patches(
        self,
        data: bytes | bytearray,
        rows: Iterable[Iterable[int]],
    ) -> tuple[BytePatch, ...]:
        normalized_rows = tuple(tuple(row) for row in rows)
        if len(normalized_rows) != self.DISTANCE_ROW_COUNT:
            raise ValueError(
                f"距离命中修正表必须包含 {self.DISTANCE_ROW_COUNT} 行。"
            )
        normalized = tuple(
            self._u8_values(
                row,
                self.DISTANCE_COLUMN_COUNT,
                f"距离命中修正表第 {index + 1} 行",
            )
            for index, row in enumerate(normalized_rows)
        )
        offset = self.spec.distance_hit_table_offset
        payload = bytes(value for row in normalized for value in row)
        self._require_range(data, offset, len(payload), "距离命中修正表")
        return ((offset, bytes(data[offset : offset + len(payload)]), payload),)

    def experience_totals(
        self, data: bytes | bytearray | None = None
    ) -> tuple[int, ...]:
        source = self.rom.data if data is None else data
        offset = self.spec.experience_totals_offset
        size = self.EXPERIENCE_TOTAL_COUNT * 2
        self._require_range(source, offset, size, "累计经验表")
        return tuple(
            int.from_bytes(source[position : position + 2], "little")
            for position in range(offset, offset + size, 2)
        )

    def experience_total_patches(
        self,
        data: bytes | bytearray,
        values: Iterable[int],
    ) -> tuple[BytePatch, ...]:
        normalized = self._u16_values(
            values, self.EXPERIENCE_TOTAL_COUNT, "累计经验表"
        )
        offset = self.spec.experience_totals_offset
        payload = b"".join(value.to_bytes(2, "little") for value in normalized)
        self._require_range(data, offset, len(payload), "累计经验表")
        return ((offset, bytes(data[offset : offset + len(payload)]), payload),)
