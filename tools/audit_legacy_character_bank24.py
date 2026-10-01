from __future__ import annotations

import argparse
import hashlib
import json
import struct
from dataclasses import dataclass
from pathlib import Path


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


def _file_offset(pointer: int) -> int:
    if not WINDOW_BASE <= pointer < 0xC000:
        raise ValueError(f"CPU 指针 ${pointer:04X} 不在 $8000—$BFFF。")
    return PAIR_FILE_BASE + pointer - WINDOW_BASE


def _roots(data: bytes) -> tuple[int, ...]:
    roots = struct.unpack_from("<8H", data, DIRECTORY_OFFSET + 2)
    if roots[0] != ROOT_START or tuple(roots) != tuple(sorted(roots)):
        raise ValueError("Bank $24 的八项资源目录无效。")
    if roots[-1] >= FIXED_CODE_START:
        raise ValueError("Bank $24 的资源目录越过固定代码。")
    return tuple(roots)


def _pointers(data: bytes, pointer: int, count: int) -> tuple[int, ...]:
    return tuple(struct.unpack_from(f"<{count}H", data, _file_offset(pointer)))


def _raw_fixed(data: bytes, pointer: int, size: int) -> bytes:
    offset = _file_offset(pointer)
    return data[offset : offset + size]


def _raw_character_attribute(data: bytes, pointer: int) -> bytes:
    offset = _file_offset(pointer)
    size = 6 + (data[offset + 5] & 0xF8).bit_count()
    return data[offset : offset + size]


def _raw_text(data: bytes, pointer: int) -> bytes:
    offset = _file_offset(pointer)
    end = data.find(b"\xFF", offset, _file_offset(FIXED_CODE_START))
    if end < 0:
        raise ValueError(f"文本记录 ${pointer:04X} 缺少 FF 结束码。")
    return data[offset : end + 1]


def _raw_scenario(data: bytes, pointer: int) -> bytes:
    offset = _file_offset(pointer)
    cursor = offset
    limit = _file_offset(FIXED_CODE_START)

    def scan(step: int) -> None:
        nonlocal cursor
        while cursor < limit and data[cursor] != 0xFF:
            cursor += step
        if cursor >= limit:
            raise ValueError(f"初始配置 ${pointer:04X} 缺少 FF 结束码。")
        cursor += 1

    scan(1)
    scan(6)
    scan(6)
    scan(4)
    return data[offset:cursor]


def parse_bank24(data: bytes) -> Bank24LogicalData:
    roots = _roots(data)
    character_pointers = _pointers(data, roots[0], 201)
    unit_pointers = _pointers(data, roots[1], 256)
    weapon_pointers = _pointers(data, roots[2], 256)
    # Directory 4 begins with the reserved $00 pointer followed by IDs $01—$C8.
    normal_pointers = _pointers(data, roots[3], 201)[1:]
    # Directory 5 physically contains IDs $00—$C8.  The old UI does not offer
    # a normal battle-name field for reserved ID $C8, but its final pointer is
    # still serialized and must move with the table.
    battle_pointers = _pointers(data, roots[4], 201)
    unit_name_pointers = _pointers(data, roots[5], 256)
    weapon_name_pointers = _pointers(data, roots[6], 256)
    scenario_pointers = _pointers(data, roots[7], 32)
    if (
        character_pointers[0]
        or unit_pointers[0]
        or weapon_pointers[0]
        or battle_pointers[0]
        or unit_name_pointers[0]
    ):
        raise ValueError("保留 ID $00 的空指针已变化。")
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


def pack_bank24(logical: Bank24LogicalData) -> tuple[bytes, tuple[int, ...], int]:
    expected = (200, 255, 255, 200, 200, 255, 256, 32)
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
    roots: list[int] = []

    def write(pointer: int, raw: bytes) -> None:
        start = pointer - WINDOW_BASE
        image[start : start + len(raw)] = raw

    def pack_resource(records: tuple[bytes, ...], *, leading_zero: bool) -> None:
        nonlocal cursor
        roots.append(cursor)
        count = len(records) + int(leading_zero)
        table = cursor
        cursor += count * 2
        assigned: dict[bytes, int] = {}
        values = [0] if leading_zero else []
        for raw in records:
            pointer = assigned.get(raw)
            if pointer is None:
                pointer = cursor
                assigned[raw] = pointer
                write(cursor, raw)
                cursor += len(raw)
            values.append(pointer)
        write(table, struct.pack(f"<{len(values)}H", *values))

    pack_resource(logical.character_attributes, leading_zero=True)
    pack_resource(logical.unit_attributes, leading_zero=True)
    pack_resource(logical.weapon_attributes, leading_zero=True)

    # The two character-name tables share textual records.  The old modifier
    # writes normal-name records after directory 4, then directory 5, followed
    # only by battle-name records that were not already emitted.
    roots.append(cursor)
    normal_table = cursor
    cursor += 201 * 2
    name_addresses: dict[bytes, int] = {}
    normal_values = [0]
    for raw in logical.normal_names:
        pointer = name_addresses.get(raw)
        if pointer is None:
            pointer = cursor
            name_addresses[raw] = pointer
            write(cursor, raw)
            cursor += len(raw)
        normal_values.append(pointer)
    write(normal_table, struct.pack("<201H", *normal_values))

    roots.append(cursor)
    battle_table = cursor
    cursor += 201 * 2
    battle_values = [0]
    for raw in logical.battle_names:
        pointer = name_addresses.get(raw)
        if pointer is None:
            pointer = cursor
            name_addresses[raw] = pointer
            write(cursor, raw)
            cursor += len(raw)
        battle_values.append(pointer)
    write(battle_table, struct.pack("<201H", *battle_values))

    pack_resource(logical.unit_names, leading_zero=True)
    pack_resource(logical.weapon_names, leading_zero=False)
    pack_resource(logical.scenarios, leading_zero=False)
    if cursor > FIXED_CODE_START:
        raise ValueError(
            f"Bank $24 复合数据需要 {cursor - ROOT_START} 字节，"
            f"原生容量只有 {FIXED_CODE_START - ROOT_START} 字节。"
        )
    struct.pack_into("<H8H", image, 0, 0, *roots)
    return bytes(image), tuple(roots), cursor


def audit(path: Path) -> dict[str, object]:
    data = path.read_bytes()
    logical = parse_bank24(data)
    packed, roots, used_end = pack_bank24(logical)
    start = ROOT_START - WINDOW_BASE
    end = used_end - WINDOW_BASE
    original = data[PAIR_FILE_BASE + start : PAIR_FILE_BASE + end]
    rebuilt = packed[start:end]
    mismatches = [
        ROOT_START + index
        for index, (before, after) in enumerate(zip(original, rebuilt))
        if before != after
    ]
    counts = {
        "人物属性": len(set(logical.character_attributes)),
        "机体属性": len(set(logical.unit_attributes)),
        "武器属性": len(set(logical.weapon_attributes)),
        "人物目录名": len(set(logical.normal_names)),
        "人物战斗名": len(set(logical.battle_names)),
        "机体名": len(set(logical.unit_names)),
        "武器名": len(set(logical.weapon_names)),
        "初始配置": len(set(logical.scenarios)),
    }
    return {
        "path": str(path),
        "sha256": hashlib.sha256(data).hexdigest().upper(),
        "roots": [f"${item:04X}" for item in roots],
        "used_end": f"${used_end:04X}",
        "capacity": FIXED_CODE_START - ROOT_START,
        "used": used_end - ROOT_START,
        "remaining": FIXED_CODE_START - used_end,
        "unique_records": counts,
        "exact_rebuild": not mismatches and _roots(data) == roots,
        "mismatch_count": len(mismatches),
        "first_mismatches": [f"${item:04X}" for item in mismatches[:16]],
    }


def main() -> None:
    parser = argparse.ArgumentParser(
        description="复核旧修改器 Bank $24 八资源目录及确定性重排。"
    )
    parser.add_argument("rom", nargs="+", type=Path)
    parser.add_argument("--json", type=Path)
    args = parser.parse_args()
    reports = [audit(path) for path in args.rom]
    text = json.dumps(reports, ensure_ascii=False, indent=2)
    if args.json is not None:
        args.json.parent.mkdir(parents=True, exist_ok=True)
        args.json.write_text(text + "\n", encoding="utf-8")
    print(text)


if __name__ == "__main__":
    main()
