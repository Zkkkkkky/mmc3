from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from functools import lru_cache
import struct

from ..dc_text import default_dc_text_table
from ..errors import RomFormatError
from .story_text import StoryTextCodec


@dataclass(frozen=True)
class LegacyTextGroup:
    key: str
    label: str
    bank: int
    table: int
    count: int
    pool_start: int
    pool_end: int
    header_offset: int | None = None


TEXT_GROUPS = (
    LegacyTextGroup("battle_00", "00 · 进攻战斗对话", 0x2A, 0x9032, 256, 0x8010, 0x9740, 0),
    LegacyTextGroup("battle_01", "01 · 进攻特殊对话", 0x2A, 0x9740, 16, 0x8010, 0x9768, 2),
    LegacyTextGroup("battle_04", "04 · 防御战斗对话", 0x0E, 0x9396, 256, 0x8010, 0x9AA6, 0),
    LegacyTextGroup("battle_05", "05 · 防御特殊对话", 0x0E, 0x9AA6, 64, 0x8010, 0x9E28, 2),
    LegacyTextGroup("system", "系统文字", 0x2A, 0x9768, 221, 0x9922, 0xA000, 4),
    LegacyTextGroup("item_description", "道具说明", 0x0A, 0xA141, 24, 0xB0DE, 0xB319),
)


# The battle dialogue runtime uses 16-bit pointers inside two fixed 8 KiB
# banks.  These are the exact object-covered spans in the supported ROM; the
# gaps between them are pointer tables or unrelated data and must never be
# treated as spare text capacity.  Keeping the spans explicit also preserves
# their capacity after a repacked ROM is saved and opened as a new baseline.
BATTLE_GROUPS_BY_BANK = {
    0x2A: ("battle_00", "battle_01"),
    0x0E: ("battle_04", "battle_05"),
}
BATTLE_TEXT_ARENAS = {
    0x2A: ((0x8010, 0x9032), (0x9232, 0x9740), (0x9760, 0x9768)),
    0x0E: (
        (0x8010, 0x9396),
        (0x9596, 0x97E4),
        (0x97FB, 0x9AA6),
        (0x9B26, 0x9B3D),
    ),
}


@dataclass(frozen=True)
class LegacyBattleTextUsage:
    bank: int
    capacity: int
    used: int
    text_records: int
    random_directories: int

    @property
    def free(self) -> int:
        return self.capacity - self.used


@dataclass(frozen=True)
class LegacySimpleTextUsage:
    key: str
    capacity: int
    used: int
    text_records: int

    @property
    def free(self) -> int:
        return self.capacity - self.used


@dataclass(frozen=True)
class LegacyTextRecord:
    group_key: str
    index: int
    variant: int
    file_offset: int
    pointer: int
    raw: bytes
    shared_by: tuple[tuple[int, int], ...]

    @property
    def text(self) -> str:
        return decode_legacy_text(self.raw)


def decode_legacy_text(raw: bytes) -> str:
    table = default_dc_text_table()
    parts = []
    cursor = 0
    while cursor < len(raw):
        lead = raw[cursor]
        size = 2 if lead in StoryTextCodec.GLYPH_LEADS else {0xFC: 3, 0xF0: 2, 0xEE: 2}.get(lead, 1)
        token = raw[cursor:cursor + size]
        parts.append(f"<{token.hex().upper()}>" if lead in (0xFC, 0xF0, 0xEE) else table.decode(token))
        cursor += size
    return "".join(parts)


class LegacyTextCodec:
    """Verified DC pointer tables, including F8 random-dialogue indirection.

    All verified text pools can be repacked while preserving aliases and
    control bytes. Battle dialogue additionally preserves F8 directories.
    """

    def __init__(self, data: bytes | bytearray, *, capacity_data: bytes | bytearray | None = None) -> None:
        self.data = bytes(data)
        self.groups = TEXT_GROUPS
        self.group_by_key = {group.key: group for group in self.groups}
        self._variants: dict[str, tuple[tuple[int, ...], ...]] = {}
        self._capacity_codec = LegacyTextCodec(capacity_data) if capacity_data is not None else None
        self._boundaries: dict[int, set[int]] = {}
        for group in self.groups:
            boundaries = self._boundaries.setdefault(group.bank, set())
            boundaries.update((group.table, group.table + group.count * 2, group.pool_end))
            base = self.offset(group.bank, 0x8000)
            if group.header_offset is not None:
                actual = self.word(base + group.header_offset)
                if actual != group.table:
                    raise RomFormatError(f"{group.label}指针表入口不匹配。")
            table = self.offset(group.bank, group.table)
            rows = []
            for index in range(group.count):
                pointer = self.word(table + index * 2)
                self._validate_pointer(group, pointer)
                boundaries.add(pointer)
                start = self.offset(group.bank, pointer)
                if self.data[start] == 0xF8 and group.key.startswith("battle_"):
                    count = self.data[start + 1]
                    if not 1 <= count <= 32:
                        raise RomFormatError(f"{group.label}随机对话数量无效。")
                    pointers = tuple(self.word(start + 2 + variant * 2) for variant in range(count))
                    for child in pointers:
                        self._validate_pointer(group, child)
                        boundaries.add(child)
                    boundaries.add(pointer + 2 + count * 2)
                    rows.append(pointers)
                else:
                    rows.append((pointer,))
            self._variants[group.key] = tuple(rows)
        for group in self.groups:
            for index in range(group.count):
                for variant in range(self.variant_count(group.key, index)):
                    self.record(group.key, index, variant)

    @staticmethod
    def offset(bank: int, pointer: int) -> int:
        return 16 + bank * 0x2000 + pointer - 0x8000

    def word(self, offset: int) -> int:
        if offset < 0 or offset + 2 > len(self.data):
            raise RomFormatError("文字指针超出 ROM。")
        return int.from_bytes(self.data[offset:offset + 2], "little")

    @staticmethod
    def _validate_pointer(group: LegacyTextGroup, pointer: int) -> None:
        if not group.pool_start <= pointer < group.pool_end:
            raise RomFormatError(f"{group.label}含越界指针 ${pointer:04X}。")
        if group.table <= pointer < group.table + group.count * 2:
            raise RomFormatError(f"{group.label}文字指针指向指针表。")

    def variant_count(self, key: str, index: int) -> int:
        return len(self._variants[key][index])

    def _raw_at(self, group: LegacyTextGroup, pointer: int) -> bytes:
        start = self.offset(group.bank, pointer)
        end = min((value for value in self._boundaries[group.bank] if value > pointer), default=group.pool_end)
        limit = self.offset(group.bank, min(end, group.pool_end))
        cursor = start
        while cursor < limit:
            lead = self.data[cursor]
            # FC has two literal operands; F0 and EE have one. This also
            # prevents an FF parameter from being mistaken for termination.
            size = 2 if lead in StoryTextCodec.GLYPH_LEADS else {0xFC: 3, 0xF0: 2, 0xEE: 2}.get(lead, 1)
            cursor += size
            if cursor > limit:
                break
            if lead == 0xFF:
                return self.data[start:cursor]
        raise RomFormatError(f"{group.label}文字记录缺少结束码。")

    def record(self, key: str, index: int, variant: int = 0) -> LegacyTextRecord:
        group = self.group_by_key[key]
        pointer = self._variants[key][index][variant]
        aliases = tuple(
            (row, sub)
            for row, variants in enumerate(self._variants[key])
            for sub, candidate in enumerate(variants)
            if candidate == pointer
        )
        return LegacyTextRecord(key, index, variant, self.offset(group.bank, pointer), pointer, self._raw_at(group, pointer), aliases)

    @staticmethod
    def protected_tokens(raw: bytes) -> tuple[bytes, ...]:
        table = default_dc_text_table()
        result = []
        cursor = 0
        while cursor < len(raw):
            lead = raw[cursor]
            size = 2 if lead in StoryTextCodec.GLYPH_LEADS else {0xFC: 3, 0xF0: 2, 0xEE: 2}.get(lead, 1)
            token = raw[cursor:cursor + size]
            if len(token) != size:
                raise ValueError("文字尾部控制码或字形不完整。")
            if lead >= 0xEE or table.byte_to_text.get(token, "⟦").startswith("⟦"):
                result.append(token)
            cursor += size
        return tuple(result)

    def replacement_patch(self, key: str, index: int, variant: int, text: str) -> tuple[int, bytes, bytes]:
        record = self.record(key, index, variant)
        capacity = len(record.raw)
        if self._capacity_codec is not None:
            baseline = self._capacity_codec.record(key, index, variant)
            if baseline.file_offset != record.file_offset:
                raise ValueError("文字指针与原容量基线不同，不能沿用原记录空间。")
            capacity = len(baseline.raw)
        encoded = default_dc_text_table().encode_preserving_tokens(record.raw, text)
        if self.protected_tokens(encoded) != self.protected_tokens(record.raw):
            raise ValueError("请保留全部控制码、参数和结束码，只修改正文文字。")
        if len(encoded) > capacity:
            raise ValueError(f"当前文字需要 {len(encoded)} 字节，原记录容量为 {capacity} 字节。")
        if not encoded or encoded[-1] != 0xFF:
            raise ValueError("请保留末尾结束码。")
        # The original range is retained. Padding follows termination, so it
        # cannot appear on screen or overwrite the neighbouring text.
        before = self.data[record.file_offset:record.file_offset + capacity]
        after = encoded + before[len(encoded):]
        return record.file_offset, before, after

    def simple_group_usage(
        self,
        key: str,
        replacements: Mapping[tuple[str, int, int], str] | None = None,
    ) -> LegacySimpleTextUsage:
        _pointers, records = self._encode_simple_group(key, replacements or {})
        group = self.group_by_key[key]
        used = sum(len(raw) for raw in records.values())
        return LegacySimpleTextUsage(
            key,
            group.pool_end - group.pool_start,
            used,
            len(records),
        )

    def _encode_simple_group(
        self,
        key: str,
        replacements: Mapping[tuple[str, int, int], str],
    ) -> tuple[tuple[int, ...], dict[int, bytes]]:
        if key.startswith("battle_"):
            raise ValueError("战斗文字必须使用带随机目录的专用重排器。")
        group = self.group_by_key[key]
        table_offset = self.offset(group.bank, group.table)
        pointers = tuple(
            self.word(table_offset + index * 2)
            for index in range(group.count)
        )
        records = {
            pointer: self._raw_at(group, pointer)
            for pointer in sorted(set(pointers))
        }
        drafted: dict[int, bytes] = {}
        for identity, text in replacements.items():
            draft_key, index, variant = identity
            if draft_key != key:
                continue
            if variant != 0:
                raise ValueError(f"{group.label}没有随机分支。")
            record = self.record(key, index, variant)
            encoded = default_dc_text_table().encode_preserving_tokens(
                record.raw, text
            )
            if self.protected_tokens(encoded) != self.protected_tokens(record.raw):
                raise ValueError("请保留全部控制码、参数和结束码，只修改正文文字。")
            if not encoded or encoded[-1] != 0xFF:
                raise ValueError("请保留末尾结束码。")
            previous = drafted.setdefault(record.pointer, encoded)
            if previous != encoded:
                raise ValueError("共用同一文字的两个编号存在不同草稿，请保留一份修改。")
            records[record.pointer] = encoded
        return pointers, records

    def simple_group_repack_patches(
        self,
        key: str,
        replacements: Mapping[tuple[str, int, int], str],
    ) -> tuple[tuple[int, bytes, bytes], ...]:
        pointers, records = self._encode_simple_group(key, replacements)
        group = self.group_by_key[key]
        capacity = group.pool_end - group.pool_start
        used = sum(len(raw) for raw in records.values())
        if used > capacity:
            raise ValueError(
                f"{group.label}共享池容量不足：需要 {used} 字节，"
                f"固定容量为 {capacity} 字节。请缩短同组其他文字。"
            )
        cursor = group.pool_start
        assigned: dict[int, int] = {}
        packed = bytearray()
        for pointer in sorted(records):
            assigned[pointer] = cursor
            raw = records[pointer]
            packed.extend(raw)
            cursor += len(raw)
        filler_source = (
            self._capacity_codec.data
            if self._capacity_codec is not None
            else self.data
        )
        relocated = tuple(assigned[pointer] for pointer in pointers)
        table_offset = self.offset(group.bank, group.table)
        table_size = group.count * 2
        pool_offset = self.offset(group.bank, group.pool_start)
        packed.extend(
            filler_source[
                pool_offset + len(packed):pool_offset + capacity
            ]
        )
        patches = (
            (
                table_offset,
                self.data[table_offset:table_offset + table_size],
                struct.pack(f"<{len(relocated)}H", *relocated),
            ),
            (
                pool_offset,
                self.data[pool_offset:pool_offset + capacity],
                bytes(packed),
            ),
        )
        return tuple(patch for patch in patches if patch[1] != patch[2])

    @staticmethod
    def _battle_bank(key: str) -> int:
        for bank, keys in BATTLE_GROUPS_BY_BANK.items():
            if key in keys:
                return bank
        raise ValueError(f"{key} 不是战斗对话文字组。")

    @staticmethod
    def _arena_for_interval(bank: int, start: int, end: int) -> int | None:
        return next(
            (
                index
                for index, (arena_start, arena_end) in enumerate(
                    BATTLE_TEXT_ARENAS[bank]
                )
                if arena_start <= start and end <= arena_end
            ),
            None,
        )

    def _battle_graph(self, bank: int) -> dict[str, object]:
        if bank not in BATTLE_GROUPS_BY_BANK:
            raise ValueError(f"Bank ${bank:02X} 不是已验证的战斗文字 Bank。")
        texts: dict[int, bytes] = {}
        text_refs: dict[int, list[tuple[str, int, int]]] = {}
        headers: dict[int, tuple[int, ...]] = {}
        header_refs: dict[int, list[tuple[str, int]]] = {}
        roots: dict[tuple[str, int], tuple[str, int]] = {}
        intervals: list[tuple[int, int, str, int]] = []
        for key in BATTLE_GROUPS_BY_BANK[bank]:
            group = self.group_by_key[key]
            table_offset = self.offset(bank, group.table)
            for index in range(group.count):
                pointer = self.word(table_offset + index * 2)
                start_offset = self.offset(bank, pointer)
                if self.data[start_offset] == 0xF8:
                    count = self.data[start_offset + 1]
                    if not 1 <= count <= 32:
                        raise RomFormatError(
                            f"{group.label}随机对话数量无效。"
                        )
                    children = tuple(
                        self.word(start_offset + 2 + variant * 2)
                        for variant in range(count)
                    )
                    existing = headers.setdefault(pointer, children)
                    if existing != children:
                        raise RomFormatError("共用随机对话目录内容不一致。")
                    header_refs.setdefault(pointer, []).append((key, index))
                    roots[(key, index)] = ("header", pointer)
                    for variant, child in enumerate(children):
                        self._validate_pointer(group, child)
                        raw = self._raw_at(group, child)
                        previous = texts.setdefault(child, raw)
                        if previous != raw:
                            raise RomFormatError("共用战斗文字内容边界不一致。")
                        text_refs.setdefault(child, []).append((key, index, variant))
                else:
                    raw = self._raw_at(group, pointer)
                    previous = texts.setdefault(pointer, raw)
                    if previous != raw:
                        raise RomFormatError("共用战斗文字内容边界不一致。")
                    text_refs.setdefault(pointer, []).append((key, index, 0))
                    roots[(key, index)] = ("text", pointer)

        overlap = set(texts) & set(headers)
        if overlap:
            pointer = min(overlap)
            raise RomFormatError(
                f"战斗文字 ${pointer:04X} 同时被解释为正文和随机目录。"
            )
        for pointer, raw in texts.items():
            intervals.append((pointer, pointer + len(raw), "正文", pointer))
        for pointer, children in headers.items():
            intervals.append(
                (pointer, pointer + 2 + len(children) * 2, "随机目录", pointer)
            )
        intervals.sort()
        previous_end = -1
        for start, end, label, pointer in intervals:
            if self._arena_for_interval(bank, start, end) is None:
                raise RomFormatError(
                    f"Bank ${bank:02X} 的{label} ${pointer:04X} 超出已验证文字段。"
                )
            if start < previous_end:
                raise RomFormatError(
                    f"Bank ${bank:02X} 战斗文字对象发生重叠。"
                )
            previous_end = end
        return {
            "texts": texts,
            "text_refs": text_refs,
            "headers": headers,
            "header_refs": header_refs,
            "roots": roots,
        }

    def _encode_battle_replacements(
        self,
        bank: int,
        replacements: Mapping[tuple[str, int, int], str],
    ) -> tuple[dict[str, object], dict[int, bytes]]:
        graph = self._battle_graph(bank)
        encoded_by_pointer: dict[int, bytes] = dict(graph["texts"])
        drafted: dict[int, bytes] = {}
        for identity, text in replacements.items():
            if len(identity) != 3:
                raise ValueError("战斗文字草稿标识无效。")
            key, index, variant = identity
            if self._battle_bank(key) != bank:
                continue
            record = self.record(key, index, variant)
            encoded = default_dc_text_table().encode_preserving_tokens(
                record.raw, text
            )
            if self.protected_tokens(encoded) != self.protected_tokens(record.raw):
                raise ValueError(
                    "请保留全部控制码、参数和结束码，只修改正文文字。"
                )
            if not encoded or encoded[-1] != 0xFF:
                raise ValueError("请保留末尾结束码。")
            previous = drafted.setdefault(record.pointer, encoded)
            if previous != encoded:
                raise ValueError(
                    "共用同一文字的两个编号存在不同草稿，请保留一份修改。"
                )
            encoded_by_pointer[record.pointer] = encoded
        return graph, encoded_by_pointer

    def battle_usage(
        self,
        bank: int,
        replacements: Mapping[tuple[str, int, int], str] | None = None,
    ) -> LegacyBattleTextUsage:
        graph, texts = self._encode_battle_replacements(
            bank, replacements or {}
        )
        headers = graph["headers"]
        used = sum(len(raw) for raw in texts.values()) + sum(
            2 + len(children) * 2 for children in headers.values()
        )
        capacity = sum(end - start for start, end in BATTLE_TEXT_ARENAS[bank])
        return LegacyBattleTextUsage(
            bank,
            capacity,
            used,
            len(texts),
            len(headers),
        )

    def _best_fit_battle_objects(
        self,
        bank: int,
        sizes: Mapping[tuple[str, int], int],
        original_sizes: Mapping[tuple[str, int], int],
        sort_keys: Mapping[tuple[str, int], tuple[object, ...]],
        group_keys: Mapping[tuple[str, int], tuple[str, ...]],
    ) -> dict[tuple[str, int], int]:
        arenas = BATTLE_TEXT_ARENAS[bank]

        def can_place(
            item: tuple[str, int],
            pointer: int,
            arena_index: int,
        ) -> bool:
            size = sizes[item]
            if pointer + size > arenas[arena_index][1]:
                return False
            for key in group_keys[item]:
                group = self.group_by_key[key]
                if not (
                    group.pool_start <= pointer
                    and pointer + size <= group.pool_end
                ):
                    return False
                if group.table <= pointer < group.table + group.count * 2:
                    return False
            return True

        # First keep every object whose size did not change at its current
        # address.  The vacated ranges of resized records and existing filler
        # become holes; place only the resized records into those holes.  A
        # shrink therefore changes just that record, and a later growth can
        # consume the adjacent hole without churning the whole bank.
        pinned = {
            item: item[1]
            for item in sizes
            if sizes[item] == original_sizes[item]
        }
        free_ranges: list[tuple[int, int, int]] = [
            (start, end, index)
            for index, (start, end) in enumerate(arenas)
        ]
        for item, pointer in sorted(pinned.items(), key=lambda pair: pair[1]):
            size = sizes[item]
            updated: list[tuple[int, int, int]] = []
            removed = False
            for start, end, arena_index in free_ranges:
                if start <= pointer and pointer + size <= end:
                    if start < pointer:
                        updated.append((start, pointer, arena_index))
                    if pointer + size < end:
                        updated.append((pointer + size, end, arena_index))
                    removed = True
                else:
                    updated.append((start, end, arena_index))
            if not removed:
                pinned = {}
                break
            free_ranges = updated
        if pinned:
            minimal = dict(pinned)
            resized = sorted(
                (item for item in sizes if item not in pinned),
                key=lambda item: (-sizes[item], item[1], sort_keys[item]),
            )
            for item in resized:
                size = sizes[item]
                candidates: list[tuple[int, int, int, int]] = []
                for range_index, (start, end, arena_index) in enumerate(
                    free_ranges
                ):
                    low = start
                    high = end - size
                    for key in group_keys[item]:
                        group = self.group_by_key[key]
                        low = max(low, group.pool_start)
                        high = min(high, group.pool_end - size)
                    if low > high:
                        continue
                    preferred = min(max(item[1], low), high)
                    if not can_place(item, preferred, arena_index):
                        continue
                    candidates.append(
                        (
                            abs(preferred - item[1]),
                            end - start - size,
                            range_index,
                            preferred,
                        )
                    )
                if not candidates:
                    minimal = {}
                    break
                _distance, _waste, range_index, pointer = min(candidates)
                start, end, arena_index = free_ranges.pop(range_index)
                if start < pointer:
                    free_ranges.append((start, pointer, arena_index))
                if pointer + size < end:
                    free_ranges.append((pointer + size, end, arena_index))
                free_ranges.sort()
                minimal[item] = pointer
            if len(minimal) == len(sizes):
                return minimal

        # Prefer an ordered packing.  The canonical banks store objects in
        # pointer order, so this keeps unchanged records at their old address
        # whenever possible and produces a small, auditable shifted range.
        # The dynamic program selects the segment boundaries with the fewest
        # moved objects and then the shortest total pointer distance.
        ordered_by_pointer = tuple(
            sorted(sizes, key=lambda item: (item[1], item[0]))
        )

        @lru_cache(maxsize=None)
        def ordered_plan(
            arena_index: int,
            item_index: int,
        ) -> tuple[int, tuple[int, ...]] | None:
            if arena_index == len(arenas):
                return (0, ()) if item_index == len(ordered_by_pointer) else None
            best: tuple[int, tuple[int, ...]] | None = None
            cursor = arenas[arena_index][0]
            score = 0
            for end_index in range(item_index, len(ordered_by_pointer) + 1):
                if end_index > item_index:
                    item = ordered_by_pointer[end_index - 1]
                    if not can_place(item, cursor, arena_index):
                        break
                    distance = abs(cursor - item[1])
                    score += (1_000_000 if distance else 0) + distance
                    cursor += sizes[item]
                tail = ordered_plan(arena_index + 1, end_index)
                if tail is None:
                    continue
                candidate = (score + tail[0], (end_index,) + tail[1])
                if best is None or candidate < best:
                    best = candidate
            return best

        stable = ordered_plan(0, 0)
        if stable is not None:
            result: dict[tuple[str, int], int] = {}
            first = 0
            for arena_index, end_index in enumerate(stable[1]):
                cursor = arenas[arena_index][0]
                for item in ordered_by_pointer[first:end_index]:
                    result[item] = cursor
                    cursor += sizes[item]
                first = end_index
            if len(result) == len(sizes):
                return result

        cursors = [start for start, _end in arenas]
        remaining = [end - start for start, end in arenas]
        result: dict[tuple[str, int], int] = {}

        def fits(item: tuple[str, int], arena_index: int) -> bool:
            return can_place(item, cursors[arena_index], arena_index)

        def eligible_count(item: tuple[str, int]) -> int:
            size = sizes[item]
            count = 0
            for arena_start, arena_end in arenas:
                low = arena_start
                high = arena_end - size
                for key in group_keys[item]:
                    group = self.group_by_key[key]
                    low = max(low, group.pool_start)
                    high = min(high, group.pool_end - size)
                if low <= high:
                    count += 1
            return count

        ordered = sorted(
            sizes,
            key=lambda item: (
                eligible_count(item),
                -sizes[item],
                sort_keys[item],
            ),
        )
        for item in ordered:
            size = sizes[item]
            candidates = [
                (free - size, index)
                for index, free in enumerate(remaining)
                if free >= size and fits(item, index)
            ]
            if not candidates:
                raise ValueError(
                    f"Bank ${bank:02X} 的安全文字段无法容纳连续的"
                    f" {size} 字节记录；请继续缩短同 Bank 的其他对话。"
                )
            _after, arena_index = min(candidates)
            result[item] = cursors[arena_index]
            cursors[arena_index] += size
            remaining[arena_index] -= size
        return result

    def battle_repack_patches(
        self,
        replacements: Mapping[tuple[str, int, int], str],
    ) -> tuple[tuple[int, bytes, bytes], ...]:
        """Repack edited battle text inside the verified fixed-bank arenas.

        A shorter record releases bytes for any other record in the same bank.
        Random-directory aliases and both root pointer tables are rebuilt as a
        single transaction; unrelated gaps and the system text table are never
        included in a patch.
        """

        if not replacements:
            return ()
        banks = sorted({self._battle_bank(key) for key, _index, _variant in replacements})
        patches: list[tuple[int, bytes, bytes]] = []
        group_order = {
            key: order
            for order, group in enumerate(TEXT_GROUPS)
            for key in (group.key,)
        }
        for bank in banks:
            graph, texts = self._encode_battle_replacements(bank, replacements)
            original_texts: dict[int, bytes] = graph["texts"]
            changed = {
                pointer: raw
                for pointer, raw in texts.items()
                if raw != original_texts[pointer]
            }
            if not changed:
                continue
            usage = self.battle_usage(bank, replacements)
            if usage.used > usage.capacity:
                excess = usage.used - usage.capacity
                raise ValueError(
                    f"Bank ${bank:02X} 战斗文字需要 {usage.used} 字节，"
                    f"安全池容量为 {usage.capacity} 字节，超出 {excess} 字节。"
                    "请先缩短同 Bank 的其他对话。"
                )
            if all(len(raw) == len(original_texts[pointer]) for pointer, raw in changed.items()):
                for pointer, raw in sorted(changed.items()):
                    offset = self.offset(bank, pointer)
                    patches.append((offset, original_texts[pointer], raw))
                continue

            headers: dict[int, tuple[int, ...]] = graph["headers"]
            text_refs: dict[int, list[tuple[str, int, int]]] = graph["text_refs"]
            header_refs: dict[int, list[tuple[str, int]]] = graph["header_refs"]
            roots: dict[tuple[str, int], tuple[str, int]] = graph["roots"]
            sizes: dict[tuple[str, int], int] = {
                ("text", pointer): len(raw) for pointer, raw in texts.items()
            }
            sizes.update(
                {
                    ("header", pointer): 2 + len(children) * 2
                    for pointer, children in headers.items()
                }
            )
            sort_keys: dict[tuple[str, int], tuple[object, ...]] = {}
            for pointer, refs in text_refs.items():
                first = min(
                    refs,
                    key=lambda item: (group_order[item[0]], item[1], item[2]),
                )
                sort_keys[("text", pointer)] = (
                    0,
                    group_order[first[0]],
                    first[1],
                    first[2],
                )
            for pointer, refs in header_refs.items():
                first = min(
                    refs,
                    key=lambda item: (group_order[item[0]], item[1]),
                )
                sort_keys[("header", pointer)] = (
                    1,
                    group_order[first[0]],
                    first[1],
                )
            groups_by_object = {
                ("text", pointer): tuple(sorted({key for key, _index, _variant in refs}))
                for pointer, refs in text_refs.items()
            }
            groups_by_object.update(
                {
                    ("header", pointer): tuple(sorted({key for key, _index in refs}))
                    for pointer, refs in header_refs.items()
                }
            )
            locations = self._best_fit_battle_objects(
                bank,
                sizes,
                {
                    **{
                        ("text", pointer): len(raw)
                        for pointer, raw in original_texts.items()
                    },
                    **{
                        ("header", pointer): 2 + len(children) * 2
                        for pointer, children in headers.items()
                    },
                },
                sort_keys,
                groups_by_object,
            )
            rebuilt = bytearray(self.data)
            for start, end in BATTLE_TEXT_ARENAS[bank]:
                offset = self.offset(bank, start)
                rebuilt[offset : offset + end - start] = b"\xFF" * (end - start)
            for pointer, raw in texts.items():
                target = locations[("text", pointer)]
                offset = self.offset(bank, target)
                rebuilt[offset : offset + len(raw)] = raw
            for pointer, children in headers.items():
                target = locations[("header", pointer)]
                raw = bytearray((0xF8, len(children)))
                for child in children:
                    raw.extend(
                        locations[("text", child)].to_bytes(2, "little")
                    )
                offset = self.offset(bank, target)
                rebuilt[offset : offset + len(raw)] = raw
            for key in BATTLE_GROUPS_BY_BANK[bank]:
                group = self.group_by_key[key]
                table_offset = self.offset(bank, group.table)
                for index in range(group.count):
                    kind, pointer = roots[(key, index)]
                    target = locations[(kind, pointer)]
                    offset = table_offset + index * 2
                    rebuilt[offset : offset + 2] = target.to_bytes(2, "little")

            verified = LegacyTextCodec(rebuilt)
            for pointer, refs in text_refs.items():
                expected = texts[pointer]
                for identity in refs:
                    if verified.record(*identity).raw != expected:
                        raise RomFormatError(
                            "战斗文字重排后的正文或共用关系验证失败。"
                        )
            for start, end in BATTLE_TEXT_ARENAS[bank]:
                offset = self.offset(bank, start)
                before = self.data[offset : offset + end - start]
                after = bytes(rebuilt[offset : offset + end - start])
                if before != after:
                    patches.append((offset, before, after))
            for key in BATTLE_GROUPS_BY_BANK[bank]:
                group = self.group_by_key[key]
                offset = self.offset(bank, group.table)
                size = group.count * 2
                before = self.data[offset : offset + size]
                after = bytes(rebuilt[offset : offset + size])
                if before != after:
                    patches.append((offset, before, after))
        return tuple(sorted(patches, key=lambda item: item[0]))
