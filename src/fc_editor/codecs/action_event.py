from __future__ import annotations

import struct
from dataclasses import dataclass

from ..errors import RomFormatError
from ..rom_image import RomImage
from .chapter_event import ChapterEventCodec, OPCODE_LABELS


ACTION_EVENT_COUNT = 0x100
ACTION_EVENT_POINTER_TABLE_OFFSET = 0x35BD0
ACTION_EVENT_POINTER_TABLE_SIZE = ACTION_EVENT_COUNT * 2
ACTION_EVENT_DATA_BANK = 0x26
ACTION_EVENT_DATA_START = 0xA000
ACTION_EVENT_DATA_END = 0xAABF
ACTION_EVENT_DATA_FILE_OFFSET = 0x4C010
ACTION_EVENT_CAPACITY = ACTION_EVENT_DATA_END - ACTION_EVENT_DATA_START
ACTION_EVENT_EMPTY_SCRIPT = b"\xDF"

# The fixed-bank dispatcher maps Bank $26 at $A000 before entering the
# action VM in Bank $1A.  Checking the loader prevents these hard offsets from
# being applied to a merely similar ROM.
ACTION_EVENT_LOADER_OFFSET = 0x355D0
ACTION_EVENT_LOADER_SIGNATURE = bytes.fromhex(
    "A9 26 85 00 8D 35 75 20 40 96 4C C2 80"
)

# These VM instructions carry a little-endian absolute address in bytes 1-2.
# All such operands in the verified action pool target instruction boundaries
# in the same pool, so a repack can relocate them without guessing.
ACTION_EVENT_JUMP_OPCODES = frozenset((0x55, 0x57, 0x58))


@dataclass(frozen=True)
class ActionEventInstruction:
    index: int
    address: int
    file_offset: int
    raw: bytes

    @property
    def raw_opcode(self) -> int:
        return self.raw[0]

    @property
    def opcode(self) -> int:
        return self.raw_opcode & 0x7F

    @property
    def is_terminal(self) -> bool:
        return bool(self.raw_opcode & 0x80)

    @property
    def label(self) -> str:
        return OPCODE_LABELS.get(self.opcode, f"未知操作码 ${self.opcode:02X}")


@dataclass(frozen=True)
class ActionEventRecord:
    action_id: int
    pointer: int
    file_offset: int
    raw: bytes
    instructions: tuple[ActionEventInstruction, ...]
    aliases: tuple[int, ...]


@dataclass(frozen=True)
class ActionEventUsage:
    used: int
    capacity: int
    free: int
    physical_records: int


@dataclass
class _PlannedInstruction:
    raw: bytes
    source_address: int | None


@dataclass
class _PlannedGroup:
    key: tuple[str, int]
    ids: list[int]
    old_pointer: int
    instructions: list[_PlannedInstruction]
    new_pointer: int = 0


class ActionEventCodec:
    """Independent 256-entry action-script table used by deployed units.

    The table lives in Bank $1A while its scripts live in the fixed-capacity
    Bank $26 pool.  Script size is determined by reachable VM instructions,
    not by the next pointer: many real records contain early terminal branches.
    This also exposes the 208 bytes occupied by duplicate one-byte ``DF``
    placeholders as reusable capacity while keeping every action ID valid.
    """

    count = ACTION_EVENT_COUNT
    pool_capacity = ACTION_EVENT_CAPACITY

    def __init__(self, rom: RomImage, data: bytes | bytearray) -> None:
        self.rom = rom
        source = bytes(data)
        if not self.supports(source):
            raise RomFormatError("行动事件表与已验证的 DC 布局不匹配。")
        self.records(source)

    @staticmethod
    def supports(data: bytes | bytearray) -> bool:
        source = bytes(data)
        if (
            len(source) < ACTION_EVENT_DATA_FILE_OFFSET + ACTION_EVENT_CAPACITY
            or source[
                ACTION_EVENT_LOADER_OFFSET:
                ACTION_EVENT_LOADER_OFFSET + len(ACTION_EVENT_LOADER_SIGNATURE)
            ]
            != ACTION_EVENT_LOADER_SIGNATURE
        ):
            return False
        pointers = struct.unpack(
            f"<{ACTION_EVENT_COUNT}H",
            source[
                ACTION_EVENT_POINTER_TABLE_OFFSET:
                ACTION_EVENT_POINTER_TABLE_OFFSET + ACTION_EVENT_POINTER_TABLE_SIZE
            ],
        )
        return (
            pointers[0] == ACTION_EVENT_DATA_START
            and all(
                ACTION_EVENT_DATA_START <= pointer < ACTION_EVENT_DATA_END
                for pointer in pointers
            )
        )

    @staticmethod
    def address_to_file_offset(address: int) -> int:
        if not ACTION_EVENT_DATA_START <= address < ACTION_EVENT_DATA_END:
            raise ValueError(f"行动事件地址 ${address:04X} 超出已验证数据池。")
        return ACTION_EVENT_DATA_FILE_OFFSET + address - ACTION_EVENT_DATA_START

    @staticmethod
    def _pointers(source: bytes) -> tuple[int, ...]:
        return struct.unpack(
            f"<{ACTION_EVENT_COUNT}H",
            source[
                ACTION_EVENT_POINTER_TABLE_OFFSET:
                ACTION_EVENT_POINTER_TABLE_OFFSET + ACTION_EVENT_POINTER_TABLE_SIZE
            ],
        )

    @staticmethod
    def _single_instruction(raw: bytes) -> bytes:
        value = bytes(raw)
        if not value:
            raise ValueError("事件指令不能为空。")
        length = ChapterEventCodec.instruction_length(value[0], value, 0)
        if length != len(value):
            raise ValueError(
                f"操作码 ${value[0]:02X} 需要 {length} 字节，"
                f"当前输入为 {len(value)} 字节。"
            )
        return value

    def _decode_script(
        self,
        source: bytes,
        pointer: int,
    ) -> tuple[ActionEventInstruction, ...]:
        """Follow both sides of conditional branches and return one script."""

        pending = [pointer]
        decoded: dict[int, ActionEventInstruction] = {}
        while pending:
            address = pending.pop()
            if address in decoded:
                continue
            if not ACTION_EVENT_DATA_START <= address < ACTION_EVENT_DATA_END:
                raise RomFormatError(
                    f"行动事件跳转目标 ${address:04X} 超出 Bank $26 数据池。"
                )
            offset = self.address_to_file_offset(address)
            raw_opcode = source[offset]
            length = ChapterEventCodec.instruction_length(raw_opcode, source, offset)
            if address + length > ACTION_EVENT_DATA_END:
                raise RomFormatError("行动事件指令越过 Bank $26 容量边界。")
            raw = source[offset:offset + length]
            instruction = ActionEventInstruction(
                0,
                address,
                offset,
                raw,
            )
            decoded[address] = instruction
            opcode = instruction.opcode
            next_address = address + length
            if opcode in ACTION_EVENT_JUMP_OPCODES:
                target = raw[1] | raw[2] << 8
                pending.append(target)
                if opcode == 0x55 or instruction.is_terminal:
                    continue
            if instruction.is_terminal:
                continue
            pending.append(next_address)

        ordered = sorted(decoded.values(), key=lambda item: item.address)
        if not ordered:
            raise RomFormatError("行动事件记录为空。")
        end = max(item.address + len(item.raw) for item in ordered)
        cursor = pointer
        normalized = []
        for index, instruction in enumerate(ordered):
            if instruction.address != cursor:
                raise RomFormatError(
                    f"行动事件 ${pointer:04X} 存在无法证明归属的数据空隙。"
                )
            normalized.append(
                ActionEventInstruction(
                    index,
                    instruction.address,
                    instruction.file_offset,
                    instruction.raw,
                )
            )
            cursor += len(instruction.raw)
        if cursor != end:
            raise RomFormatError(f"行动事件 ${pointer:04X} 指令边界不连续。")
        return tuple(normalized)

    def records(
        self,
        data: bytes | bytearray | None = None,
    ) -> tuple[ActionEventRecord, ...]:
        source = self.rom.data if data is None else bytes(data)
        pointers = self._pointers(source)
        by_pointer: dict[int, tuple[ActionEventInstruction, ...]] = {}
        aliases: dict[int, list[int]] = {}
        for action_id, pointer in enumerate(pointers):
            aliases.setdefault(pointer, []).append(action_id)
            if pointer not in by_pointer:
                by_pointer[pointer] = self._decode_script(source, pointer)
        result = []
        for action_id, pointer in enumerate(pointers):
            instructions = by_pointer[pointer]
            raw = b"".join(item.raw for item in instructions)
            result.append(
                ActionEventRecord(
                    action_id,
                    pointer,
                    self.address_to_file_offset(pointer),
                    raw,
                    instructions,
                    tuple(aliases[pointer]),
                )
            )
        return tuple(result)

    def record(
        self,
        action_id: int,
        data: bytes | bytearray | None = None,
    ) -> ActionEventRecord:
        if not 0 <= action_id < ACTION_EVENT_COUNT:
            raise IndexError(f"行动 ID ${action_id:02X} 超出范围。")
        return self.records(data)[action_id]

    def usage(self, data: bytes | bytearray | None = None) -> ActionEventUsage:
        records = self.records(data)
        physical = {record.pointer: record.raw for record in records}
        # Duplicate one-byte placeholders are interchangeable and are packed as
        # one physical script on the first variable-length operation.
        empty_count = sum(raw == ACTION_EVENT_EMPTY_SCRIPT for raw in physical.values())
        used = sum(len(raw) for raw in physical.values())
        if empty_count > 1:
            used -= empty_count - 1
        return ActionEventUsage(
            used,
            ACTION_EVENT_CAPACITY,
            ACTION_EVENT_CAPACITY - used,
            len(physical) - max(0, empty_count - 1),
        )

    @staticmethod
    def _planned_instructions(record: ActionEventRecord) -> list[_PlannedInstruction]:
        return [
            _PlannedInstruction(item.raw, item.address)
            for item in record.instructions
        ]

    def _repack(
        self,
        data: bytes | bytearray,
        action_id: int,
        mutate,
    ) -> tuple[tuple[int, bytes, bytes], ...]:
        source = bytes(data)
        records = self.records(source)
        current = records[action_id]
        selected = self._planned_instructions(current)
        mutate(selected)
        if not selected:
            raise ValueError("每个行动记录至少要保留一条指令。")

        selected_ids = set(current.aliases)
        # $03 and $FF are a verified deliberate alias in the stock table.
        # Duplicate DF placeholders, by contrast, may be split per action ID.
        if current.raw == ACTION_EVENT_EMPTY_SCRIPT and len(selected_ids) > 1:
            selected_ids = {action_id}

        group_by_key: dict[tuple[str, int], _PlannedGroup] = {}
        group_order: list[tuple[str, int]] = []
        selected_key = ("selected", action_id)
        for record in records:
            if record.action_id in selected_ids:
                key = selected_key
                instructions = selected
            elif record.raw == ACTION_EVENT_EMPTY_SCRIPT:
                key = ("empty", 0)
                instructions = self._planned_instructions(record)
            else:
                key = ("pointer", record.pointer)
                instructions = self._planned_instructions(record)
            group = group_by_key.get(key)
            if group is None:
                group = _PlannedGroup(
                    key,
                    [],
                    record.pointer,
                    [
                        _PlannedInstruction(item.raw, item.source_address)
                        for item in instructions
                    ],
                )
                group_by_key[key] = group
                group_order.append(key)
            group.ids.append(record.action_id)

        groups = [group_by_key[key] for key in group_order]
        groups.sort(key=lambda item: (item.old_pointer, min(item.ids)))
        cursor = ACTION_EVENT_DATA_START
        local_maps: dict[tuple[str, int], dict[int, int]] = {}
        for group in groups:
            group.new_pointer = cursor
            local: dict[int, int] = {}
            for item in group.instructions:
                if item.source_address is not None:
                    local[item.source_address] = cursor
                cursor += len(item.raw)
            local_maps[group.key] = local
        if cursor > ACTION_EVENT_DATA_END:
            raise ValueError(
                f"行动事件数据需要 {cursor - ACTION_EVENT_DATA_START} 字节，"
                f"固定容量仅 {ACTION_EVENT_CAPACITY} 字节。"
            )

        # Canonical relocation targets prefer the group that retains the most
        # IDs.  A split record still receives its own local address map.
        canonical: dict[int, tuple[int, int]] = {}
        for group in groups:
            weight = len(group.ids)
            for old, new in local_maps[group.key].items():
                previous = canonical.get(old)
                if previous is None or weight > previous[0]:
                    canonical[old] = (weight, new)

        pool = bytearray()
        pointers = [0] * ACTION_EVENT_COUNT
        expected_by_id: dict[int, bytes] = {}
        for group in groups:
            for item_id in group.ids:
                pointers[item_id] = group.new_pointer
            local = local_maps[group.key]
            group_bytes = bytearray()
            for item in group.instructions:
                raw = bytearray(item.raw)
                opcode = raw[0] & 0x7F
                if opcode in ACTION_EVENT_JUMP_OPCODES:
                    target = raw[1] | raw[2] << 8
                    relocated = local.get(target)
                    if relocated is None:
                        entry = canonical.get(target)
                        relocated = entry[1] if entry is not None else None
                    if relocated is None:
                        raise ValueError(
                            f"指令仍跳转到已删除或未对齐的 ${target:04X}，"
                            "请先修改跳转关系。"
                        )
                    raw[1:3] = relocated.to_bytes(2, "little")
                group_bytes.extend(raw)
            pool.extend(group_bytes)
            for item_id in group.ids:
                expected_by_id[item_id] = bytes(group_bytes)
        pool.extend(bytes((0xDF,)) * (ACTION_EVENT_CAPACITY - len(pool)))
        pointer_bytes = struct.pack(f"<{ACTION_EVENT_COUNT}H", *pointers)
        before_pointers = source[
            ACTION_EVENT_POINTER_TABLE_OFFSET:
            ACTION_EVENT_POINTER_TABLE_OFFSET + ACTION_EVENT_POINTER_TABLE_SIZE
        ]
        before_pool = source[
            ACTION_EVENT_DATA_FILE_OFFSET:
            ACTION_EVENT_DATA_FILE_OFFSET + ACTION_EVENT_CAPACITY
        ]
        candidate = bytearray(source)
        candidate[
            ACTION_EVENT_POINTER_TABLE_OFFSET:
            ACTION_EVENT_POINTER_TABLE_OFFSET + ACTION_EVENT_POINTER_TABLE_SIZE
        ] = pointer_bytes
        candidate[
            ACTION_EVENT_DATA_FILE_OFFSET:
            ACTION_EVENT_DATA_FILE_OFFSET + ACTION_EVENT_CAPACITY
        ] = pool
        decoded = self.records(candidate)
        for record in decoded:
            if record.raw != expected_by_id[record.action_id]:
                raise ValueError(
                    f"行动 ${record.action_id:02X} 修改后会越过自身记录边界，"
                    "请保留可到达的结束/跳转指令。"
                )
        return (
            (ACTION_EVENT_POINTER_TABLE_OFFSET, before_pointers, pointer_bytes),
            (ACTION_EVENT_DATA_FILE_OFFSET, before_pool, bytes(pool)),
        )

    def replacement_patches(
        self,
        data: bytes | bytearray,
        action_id: int,
        instruction_index: int,
        replacement: bytes,
    ) -> tuple[tuple[int, bytes, bytes], ...]:
        new_raw = self._single_instruction(replacement)
        record = self.record(action_id, data)
        if not 0 <= instruction_index < len(record.instructions):
            raise IndexError("行动事件指令索引超出范围。")
        current = record.instructions[instruction_index]
        direct_aliases = set(record.aliases)
        if len(new_raw) == len(current.raw) and (
            len(direct_aliases) == 1 or direct_aliases == {0x03, 0xFF}
        ):
            return ((current.file_offset, current.raw, new_raw),)

        def mutate(items: list[_PlannedInstruction]) -> None:
            items[instruction_index] = _PlannedInstruction(
                new_raw,
                items[instruction_index].source_address,
            )

        return self._repack(data, action_id, mutate)

    def insertion_patches(
        self,
        data: bytes | bytearray,
        action_id: int,
        instruction_index: int,
        raw: bytes,
        *,
        after: bool,
    ) -> tuple[tuple[int, bytes, bytes], ...]:
        new_raw = self._single_instruction(raw)
        record = self.record(action_id, data)
        if not 0 <= instruction_index < len(record.instructions):
            raise IndexError("行动事件指令索引超出范围。")

        def mutate(items: list[_PlannedInstruction]) -> None:
            target = instruction_index + (1 if after else 0)
            items.insert(target, _PlannedInstruction(new_raw, None))

        return self._repack(data, action_id, mutate)

    def deletion_patches(
        self,
        data: bytes | bytearray,
        action_id: int,
        instruction_index: int,
    ) -> tuple[tuple[int, bytes, bytes], ...]:
        record = self.record(action_id, data)
        if not 0 <= instruction_index < len(record.instructions):
            raise IndexError("行动事件指令索引超出范围。")

        def mutate(items: list[_PlannedInstruction]) -> None:
            del items[instruction_index]

        return self._repack(data, action_id, mutate)

    def record_replacement_patches(
        self,
        data: bytes | bytearray,
        action_id: int,
        raw: bytes,
        *,
        source_pointer: int | None = None,
    ) -> tuple[tuple[int, bytes, bytes], ...]:
        value = bytes(raw)
        if not value:
            raise ValueError("行动事件记录不能为空。")
        parsed: list[tuple[int, bytes]] = []
        cursor = 0
        while cursor < len(value):
            length = ChapterEventCodec.instruction_length(value[cursor], value, cursor)
            if cursor + length > len(value):
                raise ValueError("行动事件原码的最后一条指令不完整。")
            parsed.append((cursor, value[cursor:cursor + length]))
            cursor += length

        def mutate(items: list[_PlannedInstruction]) -> None:
            base = (
                self.record(action_id, data).pointer
                if source_pointer is None
                else source_pointer
            )
            items[:] = [
                _PlannedInstruction(
                    item,
                    base + offset,
                )
                for offset, item in parsed
            ]

        return self._repack(data, action_id, mutate)
