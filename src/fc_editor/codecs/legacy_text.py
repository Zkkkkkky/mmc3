from __future__ import annotations

from dataclasses import dataclass

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

    The text pool is never repacked. Each edit stays within its original
    terminated record, and system control/parameter bytes remain unchanged.
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
