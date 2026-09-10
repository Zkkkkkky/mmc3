from __future__ import annotations

import struct
from dataclasses import dataclass
from typing import Sequence

from .constants import INES_HEADER_SIZE, PRG_BANK_SIZE
from .errors import RomFormatError


# The map quota may use either reclaimed range, but never the audio or fixed
# banks between them.  The category allocator owns whole 8 KiB banks.
MAP_ELIGIBLE_BANKS = tuple(range(0x40, 0x61)) + tuple(range(0x65, 0x7E))

TERRAIN_COUNT = 0x64
SCENARIO_COUNT = 0x20
TRIGGER_COUNT = 0x20

TERRAIN_POINTER_TABLE_OFFSET = 0x005D90
TERRAIN_BANK_DIRECTORY_OFFSET = 0x005E58
SCENARIO_POINTER_TABLE_OFFSET = 0x04A425
SCENARIO_BANK_DIRECTORY_OFFSET = 0x04A990
TRIGGER_POINTER_TABLE_OFFSET = 0x01588E
TRIGGER_BANK_DIRECTORY_OFFSET = 0x015F10

# Bank $02:$9B87.  The replacement preserves the old routine's observable
# register/flag result while selecting one $A000 data bank per map.
TERRAIN_DISPATCH_OFFSET = 0x005B97
TERRAIN_DISPATCH_SIZE = 67
TERRAIN_DISPATCH_ORIGINAL = bytes.fromhex(
    "20 0B C1 AD 32 75 D0 03 AD 11 74 C9 22 B0 10 A9 87 85 7E "
    "8D 00 80 A9 03 8D DF 04 8D 01 80 60 C9 2A B0 10 A9 87 "
    "85 7E 8D 00 80 A9 34 8D DF 04 8D 01 80 60 A9 87 85 7E "
    "8D 00 80 A9 35 8D DF 04 8D 01 80 60"
)
TERRAIN_DISPATCH_CODE = bytes.fromhex(
    "20 0B C1 8A 48 98 48 AD 32 75 D0 03 AD 11 74 AA BD 48 9E "
    "A0 87 84 7E 8C 00 80 8D DF 04 8D 01 80 E0 2A 68 A8 68 "
    "AA AD DF 04 60"
)
TERRAIN_DISPATCH_PATCH = TERRAIN_DISPATCH_CODE + bytes((0xEA,)) * (
    TERRAIN_DISPATCH_SIZE - len(TERRAIN_DISPATCH_CODE)
)

# Deployment loader Bank $25:$BF49.  Its code remains mapped at $A000; the
# hook maps the selected payload into $8000 so it never switches out itself.
SCENARIO_RESOLVE_CALL_OFFSET = 0x04BF59
SCENARIO_RESOLVE_CALL_ORIGINAL = bytes.fromhex("20 0B C1")
SCENARIO_RESOLVE_CALL_PATCH = bytes.fromhex("20 40 A9")
SCENARIO_HOOK_OFFSET = 0x04A950
SCENARIO_HOOK_ADDRESS = 0xA940
SCENARIO_HOOK_CODE = bytes.fromhex(
    "A5 19 48 20 0B C1 8A 48 98 48 BA BD 03 01 AA BD 80 A9 "
    "A0 86 84 7E 8C 00 80 8D DE 04 8D 01 80 68 A8 68 AA 68 60"
)

# Coordinate event/shop scanner Bank $0A:$95BD.  Code stays at $8000 and the
# selected list is mapped into $A000.  The caller's far-call wrapper restores
# both PRG windows after the scanner returns.
TRIGGER_DISPATCH_CALL_OFFSET = 0x0155CD
TRIGGER_DISPATCH_CALL_ORIGINAL = bytes.fromhex("AD 11 74")
TRIGGER_DISPATCH_CALL_PATCH = bytes.fromhex("20 D4 9E")
TRIGGER_HOOK_OFFSET = 0x015EE4
TRIGGER_HOOK_ADDRESS = 0x9ED4
TRIGGER_HOOK_CODE = bytes.fromhex(
    "8A 48 98 48 AD 11 74 AA BD 00 9F A0 87 84 7E 8C 00 80 "
    "8D DF 04 8D 01 80 68 A8 68 AA AD 11 74 60"
)


@dataclass(frozen=True)
class LocatedMapResource:
    bank: int
    pointer: int
    window_base: int
    file_offset: int
    capacity: int

    @property
    def bank_offset(self) -> int:
        return self.pointer - self.window_base


@dataclass(frozen=True)
class ExpandedMapLayout:
    terrain: tuple[LocatedMapResource, ...]
    scenarios: tuple[LocatedMapResource, ...]
    triggers: tuple[LocatedMapResource, ...]

    @property
    def used_banks(self) -> tuple[int, ...]:
        return tuple(
            sorted(
                {
                    item.bank
                    for group in (self.terrain, self.scenarios, self.triggers)
                    for item in group
                }
            )
        )


@dataclass(frozen=True)
class MapResourcePayloads:
    terrain: tuple[bytes, ...]
    scenarios: tuple[bytes, ...]
    triggers: tuple[bytes, ...]


@dataclass(frozen=True)
class MapResourcePatch:
    offset: int
    before: bytes
    after: bytes
    label: str

    def __post_init__(self) -> None:
        if self.offset < 0 or not self.before or len(self.before) != len(self.after):
            raise ValueError("地图扩展补丁范围无效。")

    @property
    def end(self) -> int:
        return self.offset + len(self.after)


@dataclass(frozen=True)
class PackedMapResources:
    map_banks: tuple[int, ...]
    bank_images: tuple[tuple[int, bytes], ...]
    terrain_pointers: tuple[int, ...]
    terrain_banks: tuple[int, ...]
    scenario_pointers: tuple[int, ...]
    scenario_banks: tuple[int, ...]
    trigger_pointers: tuple[int, ...]
    trigger_banks: tuple[int, ...]
    used_bytes: int

    @property
    def capacity(self) -> int:
        return len(self.map_banks) * PRG_BANK_SIZE

    @property
    def used_bank_count(self) -> int:
        return sum(any(image) for _bank, image in self.bank_images)


def _validate_banks(banks: Sequence[int]) -> tuple[int, ...]:
    result = tuple(int(bank) for bank in banks)
    if not result:
        raise ValueError("地图配额至少需要一个 8 KiB Bank。")
    if len(result) != len(set(result)):
        raise ValueError("地图配额中包含重复 Bank。")
    invalid = tuple(bank for bank in result if bank not in MAP_ELIGIBLE_BANKS)
    if invalid:
        labels = "、".join(f"${bank:02X}" for bank in invalid)
        raise ValueError(f"地图配额包含不可用 Bank：{labels}。")
    return result


def _validate_records(
    records: Sequence[bytes], expected_count: int, label: str
) -> tuple[bytes, ...]:
    if len(records) != expected_count:
        raise ValueError(f"{label}必须包含 {expected_count} 条记录。")
    result = tuple(bytes(record) for record in records)
    for index, record in enumerate(result):
        if not record:
            raise ValueError(f"{label} ${index:02X} 编码为空。")
        if len(record) > PRG_BANK_SIZE:
            raise ValueError(f"{label} ${index:02X} 超过单个 8 KiB Bank。")
    return result


def pack_map_resources(
    terrain_records: Sequence[bytes],
    scenario_records: Sequence[bytes],
    trigger_records: Sequence[bytes],
    map_banks: Sequence[int],
) -> PackedMapResources:
    """Pack all map-owned data into one deterministic, non-overlapping pool.

    Terrain records remain distinct.  Equal deployment records and equal
    trigger lists share storage within their own type, matching the stock ROM's
    alias semantics.  No individual record is allowed to cross an 8 KiB bank.
    """

    banks = _validate_banks(map_banks)
    terrain = _validate_records(terrain_records, TERRAIN_COUNT, "地形")
    scenarios = _validate_records(scenario_records, SCENARIO_COUNT, "部署")
    triggers = _validate_records(trigger_records, TRIGGER_COUNT, "地图事件/商店")
    for index, payload in enumerate(terrain):
        if _terrain_payload(payload, index) != payload:
            raise ValueError(f"地形 ${index:02X} 编码末尾含多余字节。")
    for index, payload in enumerate(scenarios):
        if _scenario_payload(payload, index) != payload:
            raise ValueError(f"部署 ${index:02X} 编码末尾含多余字节。")
    for index, payload in enumerate(triggers):
        if _trigger_payload(payload, index) != payload:
            raise ValueError(f"地图事件 ${index:02X} 编码末尾含多余字节。")

    images = {bank: bytearray(PRG_BANK_SIZE) for bank in banks}
    bank_index = 0
    cursor = 0
    used = 0

    def place(payload: bytes, window_base: int) -> tuple[int, int]:
        nonlocal bank_index, cursor, used
        if cursor + len(payload) > PRG_BANK_SIZE:
            bank_index += 1
            cursor = 0
        if bank_index >= len(banks):
            required = bank_index + 1
            raise ValueError(
                f"地图池至少需要 {required * 8} KiB，"
                f"当前只分配 {len(banks) * 8} KiB。"
            )
        bank = banks[bank_index]
        pointer = window_base + cursor
        images[bank][cursor : cursor + len(payload)] = payload
        cursor += len(payload)
        used += len(payload)
        return bank, pointer

    terrain_locations = tuple(place(payload, 0xA000) for payload in terrain)

    def place_deduplicated(
        records: tuple[bytes, ...], window_base: int
    ) -> tuple[tuple[int, int], ...]:
        locations: dict[bytes, tuple[int, int]] = {}
        result: list[tuple[int, int]] = []
        for payload in records:
            location = locations.get(payload)
            if location is None:
                location = place(payload, window_base)
                locations[payload] = location
            result.append(location)
        return tuple(result)

    scenario_locations = place_deduplicated(scenarios, 0x8000)
    trigger_locations = place_deduplicated(triggers, 0xA000)

    return PackedMapResources(
        banks,
        tuple((bank, bytes(images[bank])) for bank in banks),
        tuple(pointer for _bank, pointer in terrain_locations),
        tuple(bank for bank, _pointer in terrain_locations),
        tuple(pointer for _bank, pointer in scenario_locations),
        tuple(bank for bank, _pointer in scenario_locations),
        tuple(pointer for _bank, pointer in trigger_locations),
        tuple(bank for bank, _pointer in trigger_locations),
        used,
    )


def _slice(data: bytes, offset: int, size: int, label: str) -> bytes:
    block = data[offset : offset + size]
    if len(block) != size:
        raise RomFormatError(f"{label}范围超出 ROM。")
    return block


def _accept_original_or_linked(
    source: bytes, offset: int, original: bytes, linked: bytes, label: str
) -> None:
    current = _slice(source, offset, len(original), label)
    if current not in (original, linked):
        raise RomFormatError(
            f"{label}字节与已验证的原版/扩展版都不匹配。"
        )


def build_map_resource_patches(
    data: bytes | bytearray,
    packed: PackedMapResources,
    *,
    clear_banks: Sequence[int] = (),
) -> tuple[MapResourcePatch, ...]:
    """Build every byte patch only after all source invariants pass."""

    source = bytes(data)
    _accept_original_or_linked(
        source,
        TERRAIN_DISPATCH_OFFSET,
        TERRAIN_DISPATCH_ORIGINAL,
        TERRAIN_DISPATCH_PATCH,
        "地形 Bank 调度器",
    )
    _accept_original_or_linked(
        source,
        SCENARIO_RESOLVE_CALL_OFFSET,
        SCENARIO_RESOLVE_CALL_ORIGINAL,
        SCENARIO_RESOLVE_CALL_PATCH,
        "部署解析 Hook",
    )
    _accept_original_or_linked(
        source,
        TRIGGER_DISPATCH_CALL_OFFSET,
        TRIGGER_DISPATCH_CALL_ORIGINAL,
        TRIGGER_DISPATCH_CALL_PATCH,
        "地图事件 Hook",
    )
    if _slice(source, SCENARIO_HOOK_OFFSET, len(SCENARIO_HOOK_CODE), "部署 Hook 空洞") not in (
        bytes(len(SCENARIO_HOOK_CODE)),
        SCENARIO_HOOK_CODE,
    ):
        raise RomFormatError("部署 Hook 空洞已被其他数据占用。")
    if _slice(source, TRIGGER_HOOK_OFFSET, len(TRIGGER_HOOK_CODE), "事件 Hook 空洞") not in (
        bytes(len(TRIGGER_HOOK_CODE)),
        TRIGGER_HOOK_CODE,
    ):
        raise RomFormatError("地图事件 Hook 空洞已被其他数据占用。")

    banks_to_clear = _validate_banks(tuple(clear_banks) or packed.map_banks)
    all_clear = tuple(dict.fromkeys((*banks_to_clear, *packed.map_banks)))
    image_by_bank = dict(packed.bank_images)
    writes: list[tuple[int, bytes, str]] = []
    for bank in all_clear:
        writes.append(
            (
                INES_HEADER_SIZE + bank * PRG_BANK_SIZE,
                image_by_bank.get(bank, bytes(PRG_BANK_SIZE)),
                f"地图共享池 Bank ${bank:02X}",
            )
        )
    writes.extend(
        (
            (TERRAIN_DISPATCH_OFFSET, TERRAIN_DISPATCH_PATCH, "地形 Bank 调度器"),
            (
                TERRAIN_POINTER_TABLE_OFFSET,
                struct.pack(f"<{TERRAIN_COUNT}H", *packed.terrain_pointers),
                "地形指针表",
            ),
            (
                TERRAIN_BANK_DIRECTORY_OFFSET,
                bytes(packed.terrain_banks),
                "地形 Bank 目录",
            ),
            (SCENARIO_HOOK_OFFSET, SCENARIO_HOOK_CODE, "部署 Bank Hook"),
            (
                SCENARIO_RESOLVE_CALL_OFFSET,
                SCENARIO_RESOLVE_CALL_PATCH,
                "部署解析 Hook",
            ),
            (
                SCENARIO_POINTER_TABLE_OFFSET,
                struct.pack(f"<{SCENARIO_COUNT}H", *packed.scenario_pointers),
                "部署指针表",
            ),
            (
                SCENARIO_BANK_DIRECTORY_OFFSET,
                bytes(packed.scenario_banks),
                "部署 Bank 目录",
            ),
            (TRIGGER_HOOK_OFFSET, TRIGGER_HOOK_CODE, "地图事件 Bank Hook"),
            (
                TRIGGER_DISPATCH_CALL_OFFSET,
                TRIGGER_DISPATCH_CALL_PATCH,
                "地图事件 Hook",
            ),
            (
                TRIGGER_POINTER_TABLE_OFFSET,
                struct.pack(f"<{TRIGGER_COUNT}H", *packed.trigger_pointers),
                "地图事件指针表",
            ),
            (
                TRIGGER_BANK_DIRECTORY_OFFSET,
                bytes(packed.trigger_banks),
                "地图事件 Bank 目录",
            ),
        )
    )

    patches = tuple(
        MapResourcePatch(
            offset,
            _slice(source, offset, len(after), label),
            after,
            label,
        )
        for offset, after, label in writes
    )
    ordered = sorted(patches, key=lambda patch: patch.offset)
    for left, right in zip(ordered, ordered[1:]):
        if left.end > right.offset:
            raise AssertionError(f"地图扩展补丁重叠：{left.label} / {right.label}。")
    return patches


def apply_map_resource_patches(
    data: bytes | bytearray, patches: Sequence[MapResourcePatch]
) -> bytes:
    """Apply a prevalidated patch set to a copy; the caller's buffer is untouched."""

    source = bytes(data)
    result = bytearray(source)
    for patch in patches:
        if result[patch.offset : patch.end] != patch.before:
            raise RomFormatError(f"{patch.label}在应用前已变化。")
        result[patch.offset : patch.end] = patch.after
    return bytes(result)


def link_map_resources(
    data: bytes | bytearray,
    terrain_records: Sequence[bytes],
    scenario_records: Sequence[bytes],
    trigger_records: Sequence[bytes],
    map_banks: Sequence[int],
    *,
    clear_banks: Sequence[int] = (),
) -> tuple[bytes, PackedMapResources, tuple[MapResourcePatch, ...]]:
    """Atomically pack and link all resources covered by the map quota."""

    packed = pack_map_resources(
        terrain_records, scenario_records, trigger_records, map_banks
    )
    patches = build_map_resource_patches(data, packed, clear_banks=clear_banks)
    return apply_map_resource_patches(data, patches), packed, patches


def _read_table(data: bytes, offset: int, count: int) -> tuple[int, ...]:
    return tuple(struct.unpack(f"<{count}H", _slice(data, offset, count * 2, "指针表")))


def read_expanded_map_layout(data: bytes | bytearray) -> ExpandedMapLayout:
    """Read the three pointer/bank directories and derive shared capacities."""

    source = bytes(data)
    if _slice(source, TERRAIN_DISPATCH_OFFSET, TERRAIN_DISPATCH_SIZE, "地形调度器") != TERRAIN_DISPATCH_PATCH:
        raise RomFormatError("地形扩展调度器未安装。")
    if _slice(source, SCENARIO_RESOLVE_CALL_OFFSET, 3, "部署 Hook") != SCENARIO_RESOLVE_CALL_PATCH:
        raise RomFormatError("部署扩展 Hook 未安装。")
    if _slice(source, SCENARIO_HOOK_OFFSET, len(SCENARIO_HOOK_CODE), "部署 Hook 代码") != SCENARIO_HOOK_CODE:
        raise RomFormatError("部署扩展 Hook 代码不匹配。")
    if _slice(source, TRIGGER_DISPATCH_CALL_OFFSET, 3, "事件 Hook") != TRIGGER_DISPATCH_CALL_PATCH:
        raise RomFormatError("地图事件扩展 Hook 未安装。")
    if _slice(source, TRIGGER_HOOK_OFFSET, len(TRIGGER_HOOK_CODE), "事件 Hook 代码") != TRIGGER_HOOK_CODE:
        raise RomFormatError("地图事件扩展 Hook 代码不匹配。")

    definitions = (
        (
            "terrain",
            _read_table(source, TERRAIN_POINTER_TABLE_OFFSET, TERRAIN_COUNT),
            tuple(
                _slice(
                    source,
                    TERRAIN_BANK_DIRECTORY_OFFSET,
                    TERRAIN_COUNT,
                    "地形 Bank 目录",
                )
            ),
            0xA000,
        ),
        (
            "scenarios",
            _read_table(source, SCENARIO_POINTER_TABLE_OFFSET, SCENARIO_COUNT),
            tuple(
                _slice(
                    source,
                    SCENARIO_BANK_DIRECTORY_OFFSET,
                    SCENARIO_COUNT,
                    "部署 Bank 目录",
                )
            ),
            0x8000,
        ),
        (
            "triggers",
            _read_table(source, TRIGGER_POINTER_TABLE_OFFSET, TRIGGER_COUNT),
            tuple(
                _slice(
                    source,
                    TRIGGER_BANK_DIRECTORY_OFFSET,
                    TRIGGER_COUNT,
                    "事件 Bank 目录",
                )
            ),
            0xA000,
        ),
    )

    raw_locations: dict[str, list[tuple[int, int, int]]] = {}
    offsets_by_bank: dict[int, set[int]] = {}
    for name, pointers, banks, window_base in definitions:
        locations: list[tuple[int, int, int]] = []
        for index, (pointer, bank) in enumerate(zip(pointers, banks)):
            if bank not in MAP_ELIGIBLE_BANKS:
                raise RomFormatError(f"{name} ${index:02X} 的 Bank ${bank:02X} 不在可用池。")
            if not window_base <= pointer < window_base + PRG_BANK_SIZE:
                raise RomFormatError(f"{name} ${index:02X} 的指针 ${pointer:04X} 越界。")
            bank_offset = pointer - window_base
            locations.append((bank, pointer, bank_offset))
            offsets_by_bank.setdefault(bank, set()).add(bank_offset)
        raw_locations[name] = locations

    next_offset: dict[tuple[int, int], int] = {}
    for bank, offsets in offsets_by_bank.items():
        ordered = sorted(offsets)
        for index, offset in enumerate(ordered):
            next_offset[(bank, offset)] = (
                ordered[index + 1] if index + 1 < len(ordered) else PRG_BANK_SIZE
            )

    def locate(name: str, window_base: int) -> tuple[LocatedMapResource, ...]:
        result: list[LocatedMapResource] = []
        for bank, pointer, bank_offset in raw_locations[name]:
            capacity = next_offset[(bank, bank_offset)] - bank_offset
            if capacity <= 0:
                raise RomFormatError(f"{name} 记录容量无效。")
            result.append(
                LocatedMapResource(
                    bank,
                    pointer,
                    window_base,
                    INES_HEADER_SIZE + bank * PRG_BANK_SIZE + bank_offset,
                    capacity,
                )
            )
        return tuple(result)

    return ExpandedMapLayout(
        locate("terrain", 0xA000),
        locate("scenarios", 0x8000),
        locate("triggers", 0xA000),
    )


def _terrain_payload(block: bytes, index: int) -> bytes:
    if len(block) < 3:
        raise RomFormatError(f"地形 ${index:02X} 记录太短。")
    width, height = block[:2]
    if not 1 <= width <= 32 or not 1 <= height <= 32:
        raise RomFormatError(f"地形 ${index:02X} 尺寸 {width}×{height} 越界。")
    needed = width * height
    produced = 0
    cursor = 2
    while produced < needed:
        if cursor >= len(block):
            raise RomFormatError(f"地形 ${index:02X} RLE 数据提前结束。")
        produced += (block[cursor] >> 4) + 1
        cursor += 1
        if produced > needed:
            raise RomFormatError(f"地形 ${index:02X} RLE 游程越过末尾。")
    return block[:cursor]


def _scenario_payload(block: bytes, index: int) -> bytes:
    cursor = 0
    while cursor < len(block) and block[cursor] != 0xFF:
        cursor += 1
    if cursor >= len(block):
        raise RomFormatError(f"部署 ${index:02X} 前导列表缺少 FF。")
    if cursor > 0xFE:
        raise RomFormatError(f"部署 ${index:02X} 前导列表超过 254 字节。")
    cursor += 1
    for size, maximum, label in (
        (6, 18, "敌军"),
        (6, 3, "客军"),
        (4, 11, "我方出击位"),
    ):
        count = 0
        while cursor < len(block) and block[cursor] != 0xFF:
            if cursor + size > len(block):
                raise RomFormatError(f"部署 ${index:02X} {label}记录不完整。")
            cursor += size
            count += 1
            if count > maximum:
                raise RomFormatError(
                    f"部署 ${index:02X} {label}超过 {maximum} 条。"
                )
        if cursor >= len(block):
            raise RomFormatError(f"部署 ${index:02X} {label}缺少 FF。")
        cursor += 1
    return block[:cursor]


def _trigger_payload(block: bytes, index: int) -> bytes:
    cursor = 0
    while cursor < len(block) and block[cursor] != 0xFF:
        if cursor + 4 > len(block):
            raise RomFormatError(f"地图事件 ${index:02X} 记录不完整。")
        cursor += 4
    if cursor >= len(block):
        raise RomFormatError(f"地图事件 ${index:02X} 缺少 FF。")
    return block[: cursor + 1]


def read_expanded_map_payloads(data: bytes | bytearray) -> MapResourcePayloads:
    source = bytes(data)
    layout = read_expanded_map_layout(source)

    def blocks(locations: tuple[LocatedMapResource, ...]) -> tuple[bytes, ...]:
        return tuple(
            _slice(source, item.file_offset, item.capacity, "地图扩展记录")
            for item in locations
        )

    terrain_blocks = blocks(layout.terrain)
    scenario_blocks = blocks(layout.scenarios)
    trigger_blocks = blocks(layout.triggers)
    return MapResourcePayloads(
        tuple(_terrain_payload(block, index) for index, block in enumerate(terrain_blocks)),
        tuple(
            _scenario_payload(block, index)
            for index, block in enumerate(scenario_blocks)
        ),
        tuple(_trigger_payload(block, index) for index, block in enumerate(trigger_blocks)),
    )
