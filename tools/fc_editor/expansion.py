from __future__ import annotations

import struct
import zlib
from dataclasses import dataclass
from typing import Iterable, Sequence

from .constants import INES_HEADER_SIZE, PRG_BANK_SIZE, UNIT_RECORD_SIZE


# Mapper 194 exposes 8 KiB PRG banks.  Banks $61-$64 are audio-owned and
# $7E-$7F are fixed code, so they must never enter an editor-managed pool.
AVAILABLE_EXPANSION_BANKS = tuple(range(0x40, 0x61)) + tuple(range(0x65, 0x7E))
MAX_STORY_BANKS = 14  # Seven currently verified text groups, two banks each.
SUPPORTED_UNIT_BANK_COUNTS = (6, 8, 10)  # 48/64/80 KiB, all runtime-linked.
AUTO_ALLOCATION_PREFIX = "auto."
PARTITION_ALLOCATION_PREFIX = "auto.partition."
REOPEN_GUARD_PREFIX = "auto.reopen_guard."

MAP_DISPATCH_OFFSET = 0x005B97
MAP_DISPATCH_SIZE = 67
MAP_BANK_TABLE_OFFSET = 0x005E58
MAP_BANK_TABLE_SIZE = 0x64
EXPANSION_METADATA_OFFSET = MAP_BANK_TABLE_OFFSET + MAP_BANK_TABLE_SIZE
EXPANSION_METADATA_SIZE = 24

# This is the active copy in expanded PRG Bank $7F, not the dormant Bank $3F
# copy retained from the source ROM.
RESOURCE_DESCRIPTOR_TABLE_OFFSET = (
    INES_HEADER_SIZE + 0x7F * PRG_BANK_SIZE + (0xF3E2 - 0xE000)
)
UNIT_RESOURCE_SELECTOR = 0x71
SCENARIO_RESOURCE_SELECTOR = 0x6E
STORY_SELECTORS = (0x32, 0x33, 0x36, 0x38, 0x39, 0x3A, 0x3B)

FLAG_MAPS = 0x01
FLAG_UNITS = 0x02
FLAG_SCENARIOS = 0x04
FLAG_MAP_TRIGGERS = 0x08

_METADATA_MAGIC = b"DCAP"
_METADATA_VERSION = 2
_UNASSIGNED_STORY_BANK = 0xFF


# Drop-in replacement for Bank $02:$9B87.  It preserves the original
# observable register/flag result while replacing the three hard-coded map
# bank ranges with one byte per map at $9E48.
MAP_DISPATCH_CODE = bytes.fromhex(
    "20 0B C1 8A 48 98 48 AD 32 75 D0 03 AD 11 74 AA "
    "BD 48 9E A0 87 84 7E 8C 00 80 8D DF 04 8D 01 80 "
    "E0 2A 68 A8 68 AA AD DF 04 60"
)
MAP_DISPATCH_PATCH = MAP_DISPATCH_CODE + bytes((0xEA,)) * (
    MAP_DISPATCH_SIZE - len(MAP_DISPATCH_CODE)
)


def bank_file_offset(bank: int) -> int:
    if not 0 <= bank <= 0x7F:
        raise ValueError(f"PRG Bank ${bank:02X} 越界。")
    return INES_HEADER_SIZE + bank * PRG_BANK_SIZE


def resource_descriptor_offset(selector: int) -> int:
    if not 0 <= selector <= 0xFF:
        raise ValueError("资源选择器必须是一个字节。")
    return RESOURCE_DESCRIPTOR_TABLE_OFFSET + selector * 2


def consecutive_bank_segments(banks: Iterable[int]) -> tuple[tuple[int, ...], ...]:
    ordered = tuple(sorted(set(banks)))
    if not ordered:
        return ()
    segments: list[list[int]] = [[ordered[0]]]
    for bank in ordered[1:]:
        if bank == segments[-1][-1] + 1:
            segments[-1].append(bank)
        else:
            segments.append([bank])
    return tuple(tuple(segment) for segment in segments)


@dataclass(frozen=True)
class ExpansionPlan:
    """A deterministic, non-overlapping split of the 464 KiB managed pool."""

    map_bank_count: int
    unit_bank_count: int
    story_bank_count: int
    story_group_mask: int = 0
    flags: int = 0
    story_bank_starts: tuple[int, ...] = (_UNASSIGNED_STORY_BANK,) * len(
        STORY_SELECTORS
    )

    def __post_init__(self) -> None:
        counts = (self.map_bank_count, self.unit_bank_count, self.story_bank_count)
        if any(not 0 <= value <= len(AVAILABLE_EXPANSION_BANKS) for value in counts):
            raise ValueError("Bank 配额越界。")
        if sum(counts) > len(AVAILABLE_EXPANSION_BANKS):
            raise ValueError("地图、机体和剧情配额超过 464 KiB。")
        if self.unit_bank_count not in SUPPORTED_UNIT_BANK_COUNTS:
            raise ValueError("机体配额只支持 48、64 或 80 KiB。")
        if self.story_bank_count % 2:
            raise ValueError("剧情配额必须是 16 KiB 的整数倍。")
        if self.story_bank_count > MAX_STORY_BANKS:
            raise ValueError("当前 7 个已验证文本组最多需要 112 KiB。")
        if self.story_group_mask & ~((1 << len(STORY_SELECTORS)) - 1):
            raise ValueError("剧情组位图含未知位。")
        if self.story_group_mask.bit_count() * 2 > self.story_bank_count:
            raise ValueError("已搬移的剧情组超过剧情配额。")
        if not 0 <= self.flags <= 0xFF:
            raise ValueError("扩展状态标志越界。")
        if len(self.story_bank_starts) != len(STORY_SELECTORS):
            raise ValueError("剧情 Bank 绑定表长度无效。")
        used_starts: list[int] = []
        valid_starts = {first for first, _second in self.story_pairs}
        for index, first_bank in enumerate(self.story_bank_starts):
            assigned = first_bank != _UNASSIGNED_STORY_BANK
            if assigned != bool(self.story_group_mask & (1 << index)):
                raise ValueError("剧情组位图与 Bank 绑定表不一致。")
            if assigned:
                if first_bank not in valid_starts:
                    raise ValueError("剧情组绑定到了剧情配额以外的 Bank pair。")
                used_starts.append(first_bank)
        if len(used_starts) != len(set(used_starts)):
            raise ValueError("多个剧情组绑定到了同一个 Bank pair。")

    @classmethod
    def from_kib(
        cls,
        map_kib: int,
        unit_kib: int,
        story_kib: int,
        *,
        story_group_mask: int = 0,
        flags: int = 0,
        story_bank_starts: tuple[int, ...] | None = None,
    ) -> "ExpansionPlan":
        for label, value in (("地图", map_kib), ("机体", unit_kib)):
            if value < 0 or value % 8:
                raise ValueError(f"{label}配额必须是 8 KiB 的整数倍。")
        if story_kib < 0 or story_kib % 16:
            raise ValueError("剧情配额必须是 16 KiB 的整数倍。")
        story_bank_count = story_kib // 8
        if story_bank_starts is None:
            starts = [_UNASSIGNED_STORY_BANK] * len(STORY_SELECTORS)
            story_banks = (
                AVAILABLE_EXPANSION_BANKS[-story_bank_count:]
                if story_bank_count
                else ()
            )
            pairs = tuple(
                story_banks[index]
                for index in range(0, len(story_banks), 2)
            )
            selected = [
                index
                for index in range(len(STORY_SELECTORS))
                if story_group_mask & (1 << index)
            ]
            if len(selected) > len(pairs):
                raise ValueError("已搬移的剧情组超过剧情配额。")
            for index, first_bank in zip(selected, pairs):
                starts[index] = first_bank
            story_bank_starts = tuple(starts)
        return cls(
            map_kib // 8,
            unit_kib // 8,
            story_bank_count,
            story_group_mask,
            flags,
            tuple(story_bank_starts),
        )

    @property
    def total_bank_count(self) -> int:
        return self.map_bank_count + self.unit_bank_count + self.story_bank_count

    @property
    def total_kib(self) -> int:
        return self.total_bank_count * 8

    @property
    def unassigned_kib(self) -> int:
        return (len(AVAILABLE_EXPANSION_BANKS) - self.total_bank_count) * 8

    @property
    def story_banks(self) -> tuple[int, ...]:
        if not self.story_bank_count:
            return ()
        return AVAILABLE_EXPANSION_BANKS[-self.story_bank_count :]

    @property
    def _low_banks(self) -> tuple[int, ...]:
        end = len(AVAILABLE_EXPANSION_BANKS) - self.story_bank_count
        return AVAILABLE_EXPANSION_BANKS[:end]

    @property
    def map_banks(self) -> tuple[int, ...]:
        start = self.unit_bank_count
        return self._low_banks[start : start + self.map_bank_count]

    @property
    def unit_banks(self) -> tuple[int, ...]:
        return self._low_banks[: self.unit_bank_count]

    @property
    def unassigned_banks(self) -> tuple[int, ...]:
        start = self.map_bank_count + self.unit_bank_count
        return self._low_banks[start:]

    @property
    def story_pairs(self) -> tuple[tuple[int, int], ...]:
        return tuple(
            (self.story_banks[index], self.story_banks[index + 1])
            for index in range(0, len(self.story_banks), 2)
        )

    @property
    def expanded_story_selectors(self) -> tuple[int, ...]:
        return tuple(
            selector
            for index, selector in enumerate(STORY_SELECTORS)
            if self.story_group_mask & (1 << index)
        )

    def with_flags(self, flags: int) -> "ExpansionPlan":
        return ExpansionPlan(
            self.map_bank_count,
            self.unit_bank_count,
            self.story_bank_count,
            self.story_group_mask,
            flags,
            self.story_bank_starts,
        )

    def with_story_selector(self, selector: int) -> "ExpansionPlan":
        try:
            index = STORY_SELECTORS.index(selector)
        except ValueError as error:
            raise ValueError(f"剧情组 ${selector:02X} 未经验证。") from error
        if self.story_group_mask & (1 << index):
            return self
        used = {
            bank
            for bank in self.story_bank_starts
            if bank != _UNASSIGNED_STORY_BANK
        }
        pair = next((pair for pair in self.story_pairs if pair[0] not in used), None)
        if pair is None:
            raise ValueError(
                "剧情配额已用完；每个被修改的文本组需要 16 KiB。"
            )
        starts = list(self.story_bank_starts)
        starts[index] = pair[0]
        return ExpansionPlan(
            self.map_bank_count,
            self.unit_bank_count,
            self.story_bank_count,
            self.story_group_mask | (1 << index),
            self.flags,
            tuple(starts),
        )

    def story_pair_for(self, selector: int) -> tuple[int, int] | None:
        try:
            index = STORY_SELECTORS.index(selector)
        except ValueError:
            return None
        first_bank = self.story_bank_starts[index]
        if first_bank == _UNASSIGNED_STORY_BANK:
            return None
        return first_bank, first_bank + 1

    def to_bytes(self) -> bytes:
        header = struct.pack(
            "<4sBBBBBBH7BB",
            _METADATA_MAGIC,
            _METADATA_VERSION,
            self.map_bank_count,
            self.unit_bank_count,
            self.story_bank_count,
            self.story_group_mask,
            self.flags,
            0,
            *self.story_bank_starts,
            0,
        )
        checksum = zlib.crc32(header) & 0xFFFFFFFF
        return header + struct.pack("<I", checksum)

    @classmethod
    def from_bytes(cls, data: bytes | bytearray) -> "ExpansionPlan | None":
        raw = bytes(
            data[
                EXPANSION_METADATA_OFFSET : EXPANSION_METADATA_OFFSET
                + EXPANSION_METADATA_SIZE
            ]
        )
        if len(raw) != EXPANSION_METADATA_SIZE or raw[:4] != _METADATA_MAGIC:
            return None
        header, stored_checksum = raw[:20], struct.unpack("<I", raw[20:])[0]
        if zlib.crc32(header) & 0xFFFFFFFF != stored_checksum:
            raise ValueError("扩展容量表校验失败。")
        unpacked = struct.unpack("<4sBBBBBBH7BB", header)
        magic, version, maps, units, story, mask, flags, reserved = unpacked[:8]
        story_starts = tuple(unpacked[8:15])
        trailing_reserved = unpacked[15]
        if (
            magic != _METADATA_MAGIC
            or version != _METADATA_VERSION
            or reserved
            or trailing_reserved
        ):
            raise ValueError("扩展容量表版本或保留字段无效。")
        return cls(maps, units, story, mask, flags, story_starts)


@dataclass(frozen=True)
class PackedMaps:
    bank_images: tuple[tuple[int, bytes], ...]
    pointers: tuple[int, ...]
    banks: tuple[int, ...]
    used_bytes: int


def pack_maps(records: Sequence[bytes], banks: Sequence[int]) -> PackedMaps:
    if not records:
        raise ValueError("地图记录不能为空。")
    available = tuple(banks)
    if not available:
        raise ValueError("地图配额为空。")
    images: dict[int, bytearray] = {}
    pointers: list[int] = []
    directory: list[int] = []
    bank_index = 0
    cursor = 0
    used = 0
    for map_id, value in enumerate(records):
        payload = bytes(value)
        if not payload:
            raise ValueError(f"地图 ${map_id:02X} 编码为空。")
        if len(payload) > PRG_BANK_SIZE:
            raise ValueError(f"地图 ${map_id:02X} 编码超过单个 8 KiB Bank。")
        if cursor + len(payload) > PRG_BANK_SIZE:
            bank_index += 1
            cursor = 0
        if bank_index >= len(available):
            needed = bank_index + 1
            raise ValueError(
                f"地图池至少需要 {needed * 8} KiB，当前只分配 "
                f"{len(available) * 8} KiB。"
            )
        bank = available[bank_index]
        image = images.setdefault(bank, bytearray(PRG_BANK_SIZE))
        image[cursor : cursor + len(payload)] = payload
        pointers.append(0xA000 + cursor)
        directory.append(bank)
        cursor += len(payload)
        used += len(payload)
    return PackedMaps(
        tuple((bank, bytes(images[bank])) for bank in available if bank in images),
        tuple(pointers),
        tuple(directory),
        used,
    )


def pack_units(records: Sequence[bytes], bank: int) -> bytes:
    if len(records) != 0xFF:
        raise ValueError("机体数据必须包含 ID $01—$FF 的 255 条记录。")
    if any(len(record) != UNIT_RECORD_SIZE for record in records):
        raise ValueError("每条机体记录必须是 16 字节。")
    image = bytearray(PRG_BANK_SIZE)
    table_address = 0x8010
    data_address = table_address + 0x200
    image[0:2] = table_address.to_bytes(2, "little")
    pointers = [0]
    for index in range(len(records)):
        pointers.append(data_address + index * UNIT_RECORD_SIZE)
    table = struct.pack("<256H", *pointers)
    image[0x10 : 0x10 + len(table)] = table
    cursor = data_address - 0x8000
    payload = b"".join(bytes(record) for record in records)
    if cursor + len(payload) > len(image):
        raise AssertionError("机体表超过单 Bank 容量。")
    image[cursor : cursor + len(payload)] = payload
    return bytes(image)


def pack_pointer_records(
    records: Sequence[bytes],
    *,
    pointer_count: int,
    pair: bool,
    deduplicate: bool = True,
) -> tuple[bytes, tuple[int, ...]]:
    """Build a standard $8000 directory plus pointer table and packed records."""

    if len(records) != pointer_count:
        raise ValueError("指针数量与记录数量不一致。")
    image_size = PRG_BANK_SIZE * (2 if pair else 1)
    table_address = 0x8010
    data_address = table_address + pointer_count * 2
    image = bytearray(image_size)
    image[0:2] = table_address.to_bytes(2, "little")
    cursor = data_address - 0x8000
    address_by_payload: dict[bytes, int] = {}
    pointers: list[int] = []
    for index, value in enumerate(records):
        payload = bytes(value)
        if not payload:
            raise ValueError(f"记录 ${index:02X} 为空。")
        address = address_by_payload.get(payload) if deduplicate else None
        if address is None:
            if cursor + len(payload) > image_size:
                raise ValueError(
                    f"打包后需要 {cursor + len(payload)} 字节，"
                    f"当前容器只有 {image_size} 字节。"
                )
            address = 0x8000 + cursor
            image[cursor : cursor + len(payload)] = payload
            if deduplicate:
                address_by_payload[payload] = address
            cursor += len(payload)
        pointers.append(address)
    table = struct.pack(f"<{pointer_count}H", *pointers)
    image[0x10 : 0x10 + len(table)] = table
    return bytes(image), tuple(pointers)
