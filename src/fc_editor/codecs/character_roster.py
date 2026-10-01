from __future__ import annotations

import struct

from ..errors import RomFormatError
from .bank24_composite import (
    character_count,
    parse as parse_bank24,
    replacement_patches as bank24_replacement_patches,
    with_appended_character,
)


BytePatch = tuple[int, bytes, bytes]
INES_HEADER = 16
PORTRAIT_PAIR_BASE = INES_HEADER + 0x04 * 0x2000
PORTRAIT_ROOT_DIRECTORY = PORTRAIT_PAIR_BASE + 4
CONFIGURATION_ROOT_DIRECTORY = PORTRAIT_PAIR_BASE + 12
PORTRAIT_TAIL_END = 0xB5E6
PORTRAIT_FOLLOW_SIZE = 0x02FA
PORTRAIT_FOLLOW_POINTER_RELATIVE = (0x0250, 0x0252, 0x0254, 0x0256)
PORTRAIT_CODE_POINTERS = (
    0x82B1, 0x82B7, 0x82C2, 0x82C8, 0x83ED, 0x83F2,
    0x8A86, 0x8C4D, 0x8CFF, 0x8D04, 0x9306, 0x930B, 0x9658,
    0x965D, 0x9EB5, 0x9EB9,
)
BANK06_BASE = INES_HEADER + 0x06 * 0x2000
DIALOGUE_END_CPU = 0xB510
DIALOGUE_CODE_BASE_OPERANDS = (0xC95E, 0xC963)


def _pair_offset(base: int, pointer: int) -> int:
    if not 0x8000 <= pointer < 0xC000:
        raise RomFormatError(f"CPU 指针 ${pointer:04X} 超出双 Bank 窗口。")
    return base + pointer - 0x8000


def _shift_word_patch(data: bytes | bytearray, offset: int, delta: int) -> BytePatch:
    before = bytes(data[offset:offset + 2])
    if len(before) != 2:
        raise RomFormatError("人物扩容代码操作数超出 ROM。")
    value = int.from_bytes(before, "little")
    after_value = value + delta
    if not 0x8000 <= value <= 0xBFFF or not 0x8000 <= after_value <= 0xBFFF:
        raise RomFormatError(f"人物扩容代码操作数 0x{offset:X} 无效。")
    return offset, before, struct.pack("<H", after_value)


def _portrait_patches(data: bytes | bytearray, count: int) -> tuple[BytePatch, ...]:
    source = bytes(data)
    portrait_root = int.from_bytes(
        source[PORTRAIT_ROOT_DIRECTORY:PORTRAIT_ROOT_DIRECTORY + 2], "little"
    )
    configuration_root = int.from_bytes(
        source[CONFIGURATION_ROOT_DIRECTORY:CONFIGURATION_ROOT_DIRECTORY + 2], "little"
    )
    portrait_table = _pair_offset(PORTRAIT_PAIR_BASE, portrait_root)
    portrait_pointers = struct.unpack_from(f"<{count + 1}H", source, portrait_table)
    if portrait_pointers[0] != 0:
        raise RomFormatError("人物头像表的 ID $00 不是空指针。")
    portraits = [
        source[_pair_offset(PORTRAIT_PAIR_BASE, pointer):
               _pair_offset(PORTRAIT_PAIR_BASE, pointer) + 7]
        for pointer in portrait_pointers[1:]
    ]
    portraits.append(b"\x00\x00\x00\x00\x00\xC0\x80")

    configuration_table = _pair_offset(PORTRAIT_PAIR_BASE, configuration_root)
    configuration_pointers = struct.unpack_from("<256H", source, configuration_table)
    if configuration_pointers[0] != 0:
        raise RomFormatError("机体战斗外观表的 ID $00 不是空指针。")
    configurations: list[bytes] = []
    old_used_end = configuration_root + 0x200
    for pointer in configuration_pointers[1:]:
        offset = _pair_offset(PORTRAIT_PAIR_BASE, pointer)
        size = 10 if source[offset] & 0x80 else 9
        configurations.append(source[offset:offset + size])
        old_used_end = max(old_used_end, pointer + size)

    image = bytearray(PORTRAIT_TAIL_END - portrait_root)
    cursor = portrait_root

    def write(pointer: int, raw: bytes) -> None:
        start = pointer - portrait_root
        image[start:start + len(raw)] = raw

    def pack(records: list[bytes], entries: int) -> int:
        nonlocal cursor
        table = cursor
        cursor += entries * 2
        assigned: dict[bytes, int] = {}
        pointers = [0]
        for raw in records:
            pointer = assigned.get(raw)
            if pointer is None:
                pointer = cursor
                assigned[raw] = pointer
                write(pointer, raw)
                cursor += len(raw)
            pointers.append(pointer)
        write(table, struct.pack(f"<{entries}H", *pointers))
        return table

    pack(portraits, count + 2)
    new_configuration_root = pack(configurations, 256)
    if cursor > PORTRAIT_TAIL_END:
        raise ValueError(
            "头像与机体战斗外观共享尾区容量不足："
            f"需要 {cursor - portrait_root} 字节，容量 {PORTRAIT_TAIL_END - portrait_root} 字节。"
        )
    relocation = cursor - old_used_end
    if relocation != 2:
        raise RomFormatError(
            f"新增人物后的头像尾区位移应为 2 字节，实际为 {relocation} 字节。"
        )
    follow_end = old_used_end + PORTRAIT_FOLLOW_SIZE
    if not old_used_end <= follow_end < 0xC000 - relocation:
        raise RomFormatError("头像后的关联资源边界无效。")
    new_follow_end = follow_end + relocation
    span_end = new_follow_end
    tail_offset = _pair_offset(PORTRAIT_PAIR_BASE, portrait_root)
    before_tail = source[tail_offset:tail_offset + span_end - portrait_root]
    after_tail = bytearray(before_tail)
    after_tail[:cursor - portrait_root] = image[:cursor - portrait_root]
    follow_start_offset = _pair_offset(PORTRAIT_PAIR_BASE, old_used_end)
    follow_end_offset = _pair_offset(PORTRAIT_PAIR_BASE, follow_end)
    after_tail[cursor - portrait_root:new_follow_end - portrait_root] = (
        source[follow_start_offset:follow_end_offset]
    )
    for relative_offset in PORTRAIT_FOLLOW_POINTER_RELATIVE:
        source_offset = follow_start_offset + relative_offset
        destination_offset = source_offset + relocation
        relative = destination_offset - tail_offset
        value = int.from_bytes(source[source_offset:source_offset + 2], "little")
        if not old_used_end <= value < follow_end:
            raise RomFormatError(
                f"头像关联资源内部指针 0x{source_offset:X} 无效。"
            )
        after_tail[relative:relative + 2] = struct.pack("<H", value + relocation)

    delta = new_configuration_root - configuration_root
    patches: list[BytePatch] = [
        (
            CONFIGURATION_ROOT_DIRECTORY,
            source[CONFIGURATION_ROOT_DIRECTORY:CONFIGURATION_ROOT_DIRECTORY + 2],
            struct.pack("<H", new_configuration_root),
        ),
        (tail_offset, before_tail, bytes(after_tail)),
    ]
    patches.extend(_shift_word_patch(source, offset, delta) for offset in PORTRAIT_CODE_POINTERS)
    return tuple(patch for patch in patches if patch[1] != patch[2])


def _dialogue_record_end(source: bytes, offset: int, limit: int) -> int:
    cursor = offset + 16
    for _ in range(3):
        while cursor < limit and source[cursor] != 0xFF:
            cursor += 4
        if cursor >= limit:
            raise RomFormatError("人物台词记录缺少 FF 结束码。")
        cursor += 1
    return cursor


def _music_dialogue_patches(project, count: int) -> tuple[BytePatch, ...]:
    source = bytes(project.working)
    base_profile = project._base_character_profile
    spec = base_profile.battle_music
    if spec is None or base_profile.character_dialogue_pointer_table_offset is None:
        raise RomFormatError("当前 ROM 没有完整的人物音乐/台词扩容资料。")
    delta_count = count - base_profile.character_normal_name_count
    attacker_offset = spec.attacker_table_offset
    defender_offset = spec.defender_table_offset + delta_count
    dialogue_offset = base_profile.character_dialogue_pointer_table_offset + delta_count * 2
    if defender_offset != attacker_offset + count:
        raise RomFormatError("人物战斗音乐双表不连续，不能安全扩容。")
    attacker = source[attacker_offset:attacker_offset + count] + b"\x00"
    defender = source[defender_offset:defender_offset + count] + b"\x00"

    pointers = struct.unpack_from(f"<{count}H", source, dialogue_offset)
    pool_start = min(pointers)
    pool_offset = _pair_offset(BANK06_BASE, pool_start)
    code_offset = _pair_offset(BANK06_BASE, DIALOGUE_END_CPU)
    records = []
    for pointer in pointers:
        offset = _pair_offset(BANK06_BASE, pointer)
        records.append(source[offset:_dialogue_record_end(source, offset, code_offset)])
    records.append(records[-1])

    new_count = count + 1
    new_dialogue_offset = dialogue_offset + 2
    prefix_offset = new_dialogue_offset - 2
    gap = source[defender_offset + count:dialogue_offset - 2]
    table_end = new_dialogue_offset + new_count * 2
    cursor = 0x8000 + table_end - BANK06_BASE
    assigned: dict[bytes, int] = {}
    remapped = []
    payload = bytearray()
    for raw in records:
        pointer = assigned.get(raw)
        if pointer is None:
            pointer = cursor
            assigned[raw] = pointer
            payload.extend(raw)
            cursor += len(raw)
        remapped.append(pointer)
    if cursor > DIALOGUE_END_CPU:
        raise ValueError(
            f"人物台词原生区容量不足：需要到 ${cursor:04X}，"
            f"上限为 ${DIALOGUE_END_CPU:04X}。"
        )

    region_offset = attacker_offset
    region_end = code_offset
    after = bytearray()
    after.extend(attacker)
    after.extend(defender)
    after.extend(gap)
    after.extend(b"\x00\x00")
    if region_offset + len(after) != new_dialogue_offset:
        raise RomFormatError("人物音乐与台词表之间的布局无法无损重建。")
    after.extend(struct.pack(f"<{new_count}H", *remapped))
    after.extend(payload)
    after.extend(b"\x00" * (region_end - region_offset - len(after)))
    before = source[region_offset:region_end]
    patches: list[BytePatch] = [(region_offset, before, bytes(after))]
    patches.append(_shift_word_patch(source, 0xC6CC, 1))
    patches.extend(_shift_word_patch(source, offset, 2) for offset in DIALOGUE_CODE_BASE_OPERANDS)
    return tuple(patch for patch in patches if patch[1] != patch[2])


def addition_patches(project) -> tuple[BytePatch, ...]:
    """Build one atomic, reference-compatible character roster expansion."""

    source = project.working
    count = character_count(source)
    if count >= 0xFF:
        raise ValueError("人物 ID 已到 FF，不能继续添加。")
    logical = with_appended_character(parse_bank24(source))
    patches = list(bank24_replacement_patches(source, logical))
    patches.extend(_portrait_patches(source, count))
    patches.extend(_music_dialogue_patches(project, count))
    return tuple(patches)
