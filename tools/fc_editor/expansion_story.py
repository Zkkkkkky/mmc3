from __future__ import annotations

import struct
from dataclasses import dataclass, replace
from typing import Mapping

from .codecs.story_text import StoryTextCodec
from .constants import INES_HEADER_SIZE, PRG_BANK_SIZE
from .errors import RomFormatError


VERIFIED_STORY_SELECTORS = (0x32, 0x33, 0x36, 0x38, 0x39, 0x3A, 0x3B)
STORY_PAIR_SIZE = PRG_BANK_SIZE * 2
STORY_POINTER_TABLE = 0x8010
STORY_POINTER_COUNT = 0xFF
STORY_DATA_START = STORY_POINTER_TABLE + STORY_POINTER_COUNT * 2
STORY_DATA_END = 0xC000
STORY_DATA_CAPACITY = STORY_DATA_END - STORY_DATA_START
STORY_DIRECT_DESCRIPTOR = 0xF0

# Active fixed PRG Bank $7F.  The same table in dormant Bank $3F is not used
# by the expanded ROM at runtime.
STORY_DESCRIPTOR_TABLE_OFFSET = (
    INES_HEADER_SIZE + 0x7F * PRG_BANK_SIZE + (0xF3E2 - 0xE000)
)


def story_descriptor_offset(selector: int) -> int:
    if selector not in VERIFIED_STORY_SELECTORS:
        raise ValueError(f"剧情文本组 ${selector:02X} 未经验证。")
    return STORY_DESCRIPTOR_TABLE_OFFSET + selector * 2


def story_pair_file_offset(first_bank: int) -> int:
    if not 0 <= first_bank < 0x7F:
        raise ValueError("剧情文本 pair 的首 Bank 越界。")
    if first_bank % 2:
        raise ValueError("剧情文本 pair 必须从偶数 PRG Bank 开始。")
    return INES_HEADER_SIZE + first_bank * PRG_BANK_SIZE


def _cpu_to_file_offset(first_bank: int, cpu_address: int) -> int:
    if not 0x8000 <= cpu_address < STORY_DATA_END:
        raise ValueError(f"剧情文本 CPU 地址 ${cpu_address:04X} 越界。")
    return story_pair_file_offset(first_bank) + cpu_address - 0x8000


def _terminated_length(raw: bytes) -> int:
    """Return one token-safe record length, including its standalone $FF."""

    cursor = 0
    while cursor < len(raw):
        lead = raw[cursor]
        if lead in StoryTextCodec.GLYPH_LEADS:
            if cursor + 1 >= len(raw):
                raise RomFormatError("剧情文本以不完整的双字节字形码结尾。")
            cursor += 2
            continue
        cursor += 1
        if lead == 0xFF:
            return cursor
    raise RomFormatError("剧情文本记录缺少独立 $FF 结束码。")


def _validate_record(raw: bytes) -> None:
    if not raw:
        raise ValueError("剧情文本记录不能为空。")
    try:
        length = _terminated_length(raw)
    except RomFormatError as error:
        raise ValueError(str(error)) from error
    if length != len(raw):
        raise ValueError("剧情文本的独立 $FF 结束码后不能还有数据。")


@dataclass(frozen=True)
class StoryAliasRecord:
    """One physical text record and every index that originally aliases it."""

    source_pointer: int
    indices: tuple[int, ...]
    raw: bytes

    def __post_init__(self) -> None:
        if not 0x8000 <= self.source_pointer < STORY_DATA_END:
            raise ValueError("剧情文本原指针越界。")
        if not self.indices or tuple(sorted(set(self.indices))) != self.indices:
            raise ValueError("剧情文本别名索引必须非空、唯一且有序。")
        _validate_record(bytes(self.raw))


@dataclass(frozen=True)
class StoryGroupRecords:
    """Logical records for one selector, retaining pointer-alias identity."""

    selector: int
    count: int
    records: tuple[StoryAliasRecord, ...]

    def __post_init__(self) -> None:
        if self.selector not in VERIFIED_STORY_SELECTORS:
            raise ValueError(f"剧情文本组 ${self.selector:02X} 未经验证。")
        if self.count <= 0:
            raise ValueError("剧情文本指针数量必须大于零。")
        pointers = tuple(record.source_pointer for record in self.records)
        if tuple(sorted(set(pointers))) != pointers:
            raise ValueError("剧情文本别名类必须按原指针唯一排序。")
        covered = [index for record in self.records for index in record.indices]
        if sorted(covered) != list(range(self.count)):
            raise ValueError("剧情文本别名类没有恰好覆盖所有索引。")

    @property
    def alias_signature(self) -> tuple[int, ...]:
        result = [-1] * self.count
        for alias_id, record in enumerate(self.records):
            for index in record.indices:
                result[index] = alias_id
        return tuple(result)

    @property
    def raw_by_index(self) -> tuple[bytes, ...]:
        result: list[bytes | None] = [None] * self.count
        for record in self.records:
            for index in record.indices:
                result[index] = bytes(record.raw)
        if any(value is None for value in result):
            raise AssertionError("剧情文本别名类缺少索引。")
        return tuple(value for value in result if value is not None)

    def record_for_index(self, index: int) -> StoryAliasRecord:
        if not 0 <= index < self.count:
            raise IndexError("剧情文本索引越界。")
        return next(record for record in self.records if index in record.indices)

    def with_replacement(self, index: int, raw: bytes) -> "StoryGroupRecords":
        replacement = bytes(raw)
        _validate_record(replacement)
        current = self.record_for_index(index)
        return replace(
            self,
            records=tuple(
                replace(record, raw=replacement) if record is current else record
                for record in self.records
            ),
        )


@dataclass(frozen=True)
class PackedStoryGroup:
    selector: int
    first_bank: int
    pair_image: bytes
    pointers: tuple[int, ...]
    used_bytes: int

    def __post_init__(self) -> None:
        story_descriptor_offset(self.selector)
        story_pair_file_offset(self.first_bank)
        if len(self.pair_image) != STORY_PAIR_SIZE:
            raise ValueError("剧情文本 pair 镜像必须恰好为 16 KiB。")

    @property
    def pair_file_offset(self) -> int:
        return story_pair_file_offset(self.first_bank)

    @property
    def descriptor_file_offset(self) -> int:
        return story_descriptor_offset(self.selector)

    @property
    def descriptor(self) -> bytes:
        return bytes((STORY_DIRECT_DESCRIPTOR, self.first_bank))


def extract_story_group(
    codec: StoryTextCodec,
    selector: int,
    data: bytes | bytearray | None = None,
) -> StoryGroupRecords:
    """Read a complete group without dropping its highest-pointer record."""

    if selector not in VERIFIED_STORY_SELECTORS:
        raise ValueError(f"剧情文本组 ${selector:02X} 未经验证。")
    group = codec.group_by_selector[selector]
    # Newer codecs retain the byte image used to build their pointer cache.
    # Fall back to the immutable ROM for compatibility with the baseline
    # codec, while an explicit data argument always wins.
    source = (
        bytes(getattr(codec, "_source", codec.rom.data))
        if data is None
        else bytes(data)
    )
    pointers = codec.pointers(selector)
    if len(pointers) != group.count:
        raise RomFormatError("剧情文本指针数量与配置不符。")
    unique_pointers = sorted(set(pointers))
    if any(not group.data_start <= pointer < group.data_end for pointer in unique_pointers):
        raise RomFormatError(f"剧情文本组 ${selector:02X} 含越界指针。")

    ids_by_pointer: dict[int, list[int]] = {pointer: [] for pointer in unique_pointers}
    for index, pointer in enumerate(pointers):
        ids_by_pointer[pointer].append(index)

    records: list[StoryAliasRecord] = []
    for position, pointer in enumerate(unique_pointers):
        start = _cpu_to_file_offset(group.prg_bank, pointer)
        end_pointer = (
            unique_pointers[position + 1]
            if position + 1 < len(unique_pointers)
            else group.data_end
        )
        end = _cpu_to_file_offset(group.prg_bank, end_pointer - 1) + 1
        bounded = bytes(source[start:end])
        if len(bounded) != end - start:
            raise RomFormatError(f"剧情文本组 ${selector:02X} 数据不完整。")
        length = _terminated_length(bounded)
        if position + 1 < len(unique_pointers) and length != len(bounded):
            raise RomFormatError(
                f"剧情文本组 ${selector:02X} 指针 ${pointer:04X} "
                "在下一指针前含额外数据。"
            )
        records.append(
            StoryAliasRecord(
                pointer,
                tuple(ids_by_pointer[pointer]),
                bounded[:length],
            )
        )
    return StoryGroupRecords(selector, group.count, tuple(records))


def pack_story_group(records: StoryGroupRecords, first_bank: int) -> PackedStoryGroup:
    """Pack one logical group into an independently mapped 16 KiB pair."""

    story_pair_file_offset(first_bank)
    pointer_table_size = records.count * 2
    data_address = STORY_POINTER_TABLE + pointer_table_size
    if data_address >= STORY_DATA_END:
        raise ValueError("剧情文本指针表本身已超过 16 KiB pair。")

    image = bytearray(STORY_PAIR_SIZE)
    image[0:2] = STORY_POINTER_TABLE.to_bytes(2, "little")
    cursor = data_address
    pointers = [0] * records.count
    for record in records.records:
        end = cursor + len(record.raw)
        if end > STORY_DATA_END:
            available = STORY_DATA_END - data_address
            needed = sum(len(item.raw) for item in records.records)
            raise ValueError(
                f"剧情文本组 ${records.selector:02X} 需要 {needed} 字节，"
                f"单个 16 KiB pair 的文本容量只有 {available} 字节。"
            )
        offset = cursor - 0x8000
        image[offset : offset + len(record.raw)] = record.raw
        for index in record.indices:
            pointers[index] = cursor
        cursor = end

    table = struct.pack(f"<{records.count}H", *pointers)
    table_offset = STORY_POINTER_TABLE - 0x8000
    image[table_offset : table_offset + len(table)] = table
    return PackedStoryGroup(
        records.selector,
        first_bank,
        bytes(image),
        tuple(pointers),
        cursor - 0x8000,
    )


def build_story_group(
    codec: StoryTextCodec,
    selector: int,
    first_bank: int,
    *,
    data: bytes | bytearray | None = None,
    replacements: Mapping[int, bytes] | None = None,
) -> PackedStoryGroup:
    """Extract, optionally edit, and pack one verified story selector."""

    records = extract_story_group(codec, selector, data)
    replacement_by_alias: dict[int, bytes] = {}
    for index, payload in (replacements or {}).items():
        record = records.record_for_index(index)
        replacement = bytes(payload)
        previous = replacement_by_alias.get(record.source_pointer)
        if previous is not None and previous != replacement:
            raise ValueError("同一共享剧情记录收到了两个不同的替换值。")
        replacement_by_alias[record.source_pointer] = replacement
    for record in records.records:
        if record.source_pointer in replacement_by_alias:
            records = records.with_replacement(
                record.indices[0], replacement_by_alias[record.source_pointer]
            )
    return pack_story_group(records, first_bank)
