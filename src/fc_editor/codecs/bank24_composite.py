from __future__ import annotations

import struct
from dataclasses import dataclass, replace

from ..errors import RomFormatError


INES_HEADER = 16
BANK = 0x24
PAIR_FILE_BASE = INES_HEADER + BANK * 0x2000
WINDOW_BASE = 0x8000
DIRECTORY_OFFSET = PAIR_FILE_BASE
ROOT_COUNT = 8
ROOT_START = 0x83F0
FIXED_CODE_START = 0xBF40


@dataclass(frozen=True)
class Bank24LogicalData:
    character_attributes: tuple[bytes, ...]
    unit_attributes: tuple[bytes, ...]
    weapon_attributes: tuple[bytes, ...]
    normal_names: tuple[bytes, ...]
    battle_names: tuple[bytes, ...]
    unit_names: tuple[bytes, ...]
    weapon_names: tuple[bytes, ...]
    scenarios: tuple[bytes, ...]


def file_offset(pointer: int) -> int:
    if not WINDOW_BASE <= pointer < 0xC000:
        raise ValueError(f"CPU 指针 ${pointer:04X} 不在 $8000—$BFFF。")
    return PAIR_FILE_BASE + pointer - WINDOW_BASE


def roots(data: bytes | bytearray) -> tuple[int, ...]:
    try:
        values = tuple(struct.unpack_from("<8H", data, DIRECTORY_OFFSET + 2))
    except struct.error as error:
        raise RomFormatError("Bank $24 的八资源目录不完整。") from error
    if values[0] != ROOT_START or values != tuple(sorted(values)):
        raise RomFormatError("Bank $24 的八资源目录无效。")
    if values[-1] >= FIXED_CODE_START:
        raise RomFormatError("Bank $24 的资源目录越过固定代码。")
    return values


def _pointers(data: bytes | bytearray, pointer: int, count: int) -> tuple[int, ...]:
    try:
        return tuple(struct.unpack_from(f"<{count}H", data, file_offset(pointer)))
    except struct.error as error:
        raise RomFormatError(f"Bank $24 指针表 ${pointer:04X} 不完整。") from error


def character_count(data: bytes | bytearray) -> int:
    """Infer the logical roster size from the first variable pointer table.

    The table is ``00`` followed by one pointer per character and then the
    packed records.  This is also how a ROM saved by the reference editor can
    be reopened after its roster has grown; the count is not stored elsewhere.
    """

    root = roots(data)[0]
    minimum = 0x10000
    index = 0
    while root + index * 2 < minimum:
        value = _pointers(data, root + index * 2, 1)[0]
        if index == 0 and value:
            raise RomFormatError("Bank $24 人物属性表缺少 ID $00 空指针。")
        if value:
            minimum = min(minimum, value)
        index += 1
        if index > 0x100:
            raise RomFormatError("Bank $24 人物属性表项数超过 8 位 ID 容量。")
    if minimum != root + index * 2 or index < 2:
        raise RomFormatError("Bank $24 人物属性表边界无效。")
    return index - 1


def _raw_fixed(data: bytes | bytearray, pointer: int, size: int) -> bytes:
    offset = file_offset(pointer)
    raw = bytes(data[offset : offset + size])
    if len(raw) != size:
        raise RomFormatError(f"Bank $24 定长记录 ${pointer:04X} 不完整。")
    return raw


def _raw_character_attribute(data: bytes | bytearray, pointer: int) -> bytes:
    offset = file_offset(pointer)
    if offset + 6 > len(data):
        raise RomFormatError(f"人物属性记录 ${pointer:04X} 不完整。")
    size = 6 + (data[offset + 5] & 0xF8).bit_count()
    return _raw_fixed(data, pointer, size)


def _raw_text(data: bytes | bytearray, pointer: int) -> bytes:
    offset = file_offset(pointer)
    limit = file_offset(FIXED_CODE_START)
    glyph_leads = frozenset(
        (*range(0xB8, 0xBC), *range(0xC8, 0xCC), *range(0xD8, 0xDC))
    )
    cursor = offset
    while cursor < limit:
        lead = data[cursor]
        if lead in glyph_leads:
            if cursor + 1 >= limit:
                break
            cursor += 2
            continue
        cursor += 1
        if lead == 0xFF:
            return bytes(data[offset:cursor])
    raise RomFormatError(f"文本记录 ${pointer:04X} 缺少独立 FF 结束码。")


def _raw_scenario(data: bytes | bytearray, pointer: int) -> bytes:
    offset = file_offset(pointer)
    cursor = offset
    limit = file_offset(FIXED_CODE_START)
    for step in (1, 6, 6, 4):
        while cursor < limit and data[cursor] != 0xFF:
            cursor += step
        if cursor >= limit:
            raise RomFormatError(f"初始配置 ${pointer:04X} 缺少 FF 结束码。")
        cursor += 1
    return bytes(data[offset:cursor])


def parse(data: bytes | bytearray) -> Bank24LogicalData:
    resource_roots = roots(data)
    roster_count = character_count(data)
    character_pointers = _pointers(data, resource_roots[0], roster_count + 1)
    unit_pointers = _pointers(data, resource_roots[1], 256)
    weapon_pointers = _pointers(data, resource_roots[2], 256)
    normal_pointers = _pointers(data, resource_roots[3], roster_count + 1)[1:]
    battle_pointers = _pointers(data, resource_roots[4], roster_count + 1)
    unit_name_pointers = _pointers(data, resource_roots[5], 256)
    weapon_name_pointers = _pointers(data, resource_roots[6], 256)
    scenario_pointers = _pointers(data, resource_roots[7], 32)
    if (
        character_pointers[0]
        or unit_pointers[0]
        or weapon_pointers[0]
        or battle_pointers[0]
        or unit_name_pointers[0]
    ):
        raise RomFormatError("Bank $24 保留 ID $00 的空指针已变化。")
    return Bank24LogicalData(
        tuple(_raw_character_attribute(data, item) for item in character_pointers[1:]),
        tuple(_raw_fixed(data, item, 16) for item in unit_pointers[1:]),
        tuple(_raw_fixed(data, item, 6) for item in weapon_pointers[1:]),
        tuple(_raw_text(data, item) for item in normal_pointers),
        tuple(_raw_text(data, item) for item in battle_pointers[1:]),
        tuple(_raw_text(data, item) for item in unit_name_pointers[1:]),
        tuple(_raw_text(data, item) for item in weapon_name_pointers),
        tuple(_raw_scenario(data, item) for item in scenario_pointers),
    )


def pack(logical: Bank24LogicalData) -> tuple[bytes, tuple[int, ...], int]:
    roster_count = len(logical.character_attributes)
    expected = (roster_count, 255, 255, roster_count, roster_count, 255, 256, 32)
    actual = tuple(
        len(items)
        for items in (
            logical.character_attributes,
            logical.unit_attributes,
            logical.weapon_attributes,
            logical.normal_names,
            logical.battle_names,
            logical.unit_names,
            logical.weapon_names,
            logical.scenarios,
        )
    )
    if actual != expected:
        raise ValueError(f"Bank $24 逻辑记录数量错误：{actual}，预期 {expected}。")

    image = bytearray(0x4000)
    cursor = ROOT_START
    packed_roots: list[int] = []

    def write(pointer: int, raw: bytes) -> None:
        start = pointer - WINDOW_BASE
        image[start : start + len(raw)] = raw

    def pack_resource(records: tuple[bytes, ...], *, leading_zero: bool) -> None:
        nonlocal cursor
        packed_roots.append(cursor)
        table = cursor
        cursor += (len(records) + int(leading_zero)) * 2
        assigned: dict[bytes, int] = {}
        values = [0] if leading_zero else []
        for raw in records:
            pointer = assigned.get(raw)
            if pointer is None:
                pointer = cursor
                assigned[raw] = pointer
                write(pointer, raw)
                cursor += len(raw)
            values.append(pointer)
        write(table, struct.pack(f"<{len(values)}H", *values))

    pack_resource(logical.character_attributes, leading_zero=True)
    pack_resource(logical.unit_attributes, leading_zero=True)
    pack_resource(logical.weapon_attributes, leading_zero=True)

    packed_roots.append(cursor)
    normal_table = cursor
    cursor += (roster_count + 1) * 2
    name_addresses: dict[bytes, int] = {}
    normal_values = [0]
    for raw in logical.normal_names:
        pointer = name_addresses.get(raw)
        if pointer is None:
            pointer = cursor
            name_addresses[raw] = pointer
            write(pointer, raw)
            cursor += len(raw)
        normal_values.append(pointer)
    write(normal_table, struct.pack(f"<{roster_count + 1}H", *normal_values))

    packed_roots.append(cursor)
    battle_table = cursor
    cursor += (roster_count + 1) * 2
    battle_values = [0]
    for raw in logical.battle_names:
        pointer = name_addresses.get(raw)
        if pointer is None:
            pointer = cursor
            name_addresses[raw] = pointer
            write(pointer, raw)
            cursor += len(raw)
        battle_values.append(pointer)
    write(battle_table, struct.pack(f"<{roster_count + 1}H", *battle_values))

    pack_resource(logical.unit_names, leading_zero=True)
    pack_resource(logical.weapon_names, leading_zero=False)
    pack_resource(logical.scenarios, leading_zero=False)
    if cursor > FIXED_CODE_START:
        raise ValueError(
            f"Bank $24 八资源重排后需要 {cursor - ROOT_START} 字节，"
            f"原生总容量只有 {FIXED_CODE_START - ROOT_START} 字节。"
        )
    struct.pack_into("<H8H", image, 0, 0, *packed_roots)
    return bytes(image), tuple(packed_roots), cursor


def replacement_patches(
    data: bytes | bytearray,
    logical: Bank24LogicalData,
) -> tuple[tuple[int, bytes, bytes], ...]:
    source = bytes(data)
    packed, _packed_roots, used_end = pack(logical)
    directory_after = packed[:18]
    directory_before = source[DIRECTORY_OFFSET : DIRECTORY_OFFSET + 18]
    block_offset = file_offset(ROOT_START)
    block_size = used_end - ROOT_START
    block_after = packed[ROOT_START - WINDOW_BASE : used_end - WINDOW_BASE]
    block_before = source[block_offset : block_offset + block_size]
    patches = (
        (DIRECTORY_OFFSET, directory_before, directory_after),
        (block_offset, block_before, block_after),
    )
    return tuple(item for item in patches if item[1] != item[2])


def with_character_names(
    logical: Bank24LogicalData,
    character_id: int,
    *,
    normal: bytes | None = None,
    battle: bytes | None = None,
) -> Bank24LogicalData:
    normal_names = list(logical.normal_names)
    battle_names = list(logical.battle_names)
    if normal is not None:
        normal_names[character_id - 1] = bytes(normal)
    if battle is not None:
        battle_names[character_id - 1] = bytes(battle)
    return replace(
        logical,
        normal_names=tuple(normal_names),
        battle_names=tuple(battle_names),
    )


def with_character_attribute(
    logical: Bank24LogicalData,
    character_id: int,
    raw: bytes,
    *,
    shared_ids: tuple[int, ...] = (),
) -> Bank24LogicalData:
    records = list(logical.character_attributes)
    targets = shared_ids or (character_id,)
    for target in targets:
        if not 1 <= target <= len(records):
            raise ValueError("人物 ID 必须在 01—C8 之间。")
        records[target - 1] = bytes(raw)
    return replace(logical, character_attributes=tuple(records))


def with_unit_attribute(
    logical: Bank24LogicalData,
    unit_id: int,
    raw: bytes,
) -> Bank24LogicalData:
    """Replace one logical unit record without changing aliased neighbours."""

    records = list(logical.unit_attributes)
    if not 1 <= unit_id <= len(records):
        raise ValueError("机体 ID 必须在 01—FF 之间。")
    value = bytes(raw)
    if len(value) != 16:
        raise ValueError("机体属性记录必须正好为 16 字节。")
    records[unit_id - 1] = value
    return replace(logical, unit_attributes=tuple(records))


def with_appended_character(logical: Bank24LogicalData) -> Bank24LogicalData:
    """Append the same empty logical record used by the reference editor."""

    if len(logical.character_attributes) >= 0xFF:
        raise ValueError("人物 ID 已到 FF，不能继续添加。")
    blank_name = b"\xFF"
    return replace(
        logical,
        character_attributes=logical.character_attributes + (b"\x00" * 6,),
        normal_names=logical.normal_names + (blank_name,),
        battle_names=logical.battle_names + (blank_name,),
    )
