from __future__ import annotations

from dataclasses import dataclass

from ..errors import RomFormatError
from .chapter_event import ChapterEventCodec, OPCODE_LABELS


@dataclass(frozen=True)
class LegacyScenarioInstruction:
    scenario_id: int
    phase: int
    bank: int
    address: int
    file_offset: int
    raw: bytes

    @property
    def opcode(self) -> int:
        return self.raw[0] & 0x7F

    @property
    def label(self) -> str:
        overrides = {0x59: "播放我方地图音乐", 0x5A: "播放敌方地图音乐", 0x5C: "设置内存地址值", 0x5D: "内存数据运算", 0x27: "判断选项", 0x3C: "选项事件"}
        return overrides.get(self.opcode, OPCODE_LABELS.get(self.opcode, f"事件 ${self.opcode:02X}"))


class LegacyScenarioCodec:
    """Bank-aware chapter scripts selected by the actual $95A0-$964F loader."""

    PHASE_LABELS = ("界面事件", "回合事件", "即时事件")
    POINTER_TABLES = (0x35B10, 0x35B50, 0x35B90)
    LOADER_SIGNATURES = (
        (0x355B0, bytes.fromhex("A9 1E 85 00 8D 35 75 20 40 96 4C 20 80")),
        (0x355C0, bytes.fromhex("A9 1E 85 00 8D 35 75 20 40 96 4C 5C 80")),
        (0x35610, bytes.fromhex("AD 11 74 C9 21 B0 21 AD 11 74 C9 0A B0 0D A9 1B 85 00 8D 35 75 20 40 96 4C 8F 80 A9 1F 85 00 8D 35 75 20 40 96 4C 8F 80")),
    )
    BANK_ENDS = {0x1E: 0xADD5, 0x1B: 0xBFDA, 0x1F: 0xA5F5}
    BASELINE_TRAILING_DF = {0x1E: 19, 0x1B: 9, 0x1F: 19}
    JUMP_OPCODES = frozenset((0x55, 0x57, 0x58))

    def __init__(self, data: bytes | bytearray) -> None:
        self.data = bytes(data)
        for offset, expected in self.LOADER_SIGNATURES:
            if self.data[offset:offset + len(expected)] != expected:
                raise RomFormatError("章节事件的 Bank 调度代码与已验证版本不匹配。")
        self.pointers = tuple(tuple(int.from_bytes(self.data[table + 2 * i:table + 2 * i + 2], "little") for i in range(32)) for table in self.POINTER_TABLES)
        self._starts: dict[int, set[int]] = {bank: set() for bank in self.BANK_ENDS}
        for phase in range(3):
            for chapter in range(32):
                bank = self.bank(chapter, phase)
                pointer = self.pointers[phase][chapter]
                if not 0xA000 <= pointer < self.BANK_ENDS[bank]:
                    raise RomFormatError("章节事件入口超出对应 Bank 的脚本区。")
                self._starts[bank].add(pointer)
        self.bank_ends = {
            bank: self._logical_bank_end(bank)
            for bank in self.BANK_ENDS
        }
        for phase in range(3):
            for chapter in range(32):
                self.instructions(chapter, phase)

    @staticmethod
    def _bank_offset(bank: int, address: int = 0xA000) -> int:
        return 16 + bank * 0x2000 + address - 0xA000

    def _logical_bank_end(self, bank: int) -> int:
        """Exclude unreferenced trailing DF padding created by earlier repacks."""

        fixed_end = self.BANK_ENDS[bank]
        offset = self._bank_offset(bank, fixed_end)
        trailing = 0
        while offset - trailing > self._bank_offset(bank) and self.data[offset - trailing - 1] == 0xDF:
            trailing += 1
        # The stock ROM already uses a tail of distinct DF records, including
        # empty chapter entries.  Only DF bytes beyond that verified baseline
        # are capacity released by a later structural edit.
        text_end = fixed_end - max(0, trailing - self.BASELINE_TRAILING_DF[bank])
        referenced_end = max(self._starts[bank], default=0xA000) + 1
        return max(text_end, referenced_end)

    @staticmethod
    def bank(chapter: int, phase: int) -> int:
        if not 0 <= chapter < 32 or not 0 <= phase < 3:
            raise IndexError("关卡或事件阶段编号无效。")
        return 0x1E if phase < 2 else (0x1B if chapter < 10 else 0x1F)

    def instructions(self, chapter: int, phase: int) -> tuple[LegacyScenarioInstruction, ...]:
        bank = self.bank(chapter, phase)
        start = self.pointers[phase][chapter]
        end = min((p for p in self._starts[bank] if p > start), default=self.bank_ends[bank])
        address = start
        result = []
        while address < end:
            offset = 16 + bank * 0x2000 + address - 0xA000
            length = ChapterEventCodec.instruction_length(self.data[offset], self.data, offset)
            if address + length > end:
                raise RomFormatError("章节事件参数越过下一入口。")
            result.append(LegacyScenarioInstruction(chapter, phase, bank, address, offset, self.data[offset:offset + length]))
            address += length
        return tuple(result)

    def replacement_patch(self, instruction: LegacyScenarioInstruction, raw: bytes) -> tuple[int, bytes, bytes]:
        current = next((item for item in self.instructions(instruction.scenario_id, instruction.phase) if item.file_offset == instruction.file_offset), None)
        if current is None or current.raw != instruction.raw:
            raise ValueError("事件已变化，请重新载入。")
        if len(raw) != len(current.raw) or ChapterEventCodec.instruction_length(raw[0], raw, 0) != len(raw):
            raise ValueError(f"事件必须保持 {len(current.raw)} 字节，且参数长度须匹配操作码。")
        return current.file_offset, current.raw, bytes(raw)

    @staticmethod
    def _validate_sequence(raw: bytes, *, allow_empty: bool = False) -> tuple[bytes, ...]:
        value = bytes(raw)
        if not value:
            if allow_empty:
                return ()
            raise ValueError("事件指令不能为空。")
        rows = []
        cursor = 0
        while cursor < len(value):
            length = ChapterEventCodec.instruction_length(value[cursor], value, cursor)
            if cursor + length > len(value):
                raise ValueError("事件代码末尾含不完整指令。")
            rows.append(value[cursor:cursor + length])
            cursor += length
        return tuple(rows)

    def _views_for_bank(self, bank: int) -> dict[int, bytes]:
        """Return the union of linear records and verified branch-target views.

        Bank $1B contains one intentional overlapping stream: a branch enters
        the parameter byte of the linear view at $BE9B.  Keeping both views is
        essential when suffix bytes move, even though editing the overlap
        itself remains guarded.
        """

        views: dict[int, bytes] = {}
        starts = sorted(self._starts[bank])
        for index, start in enumerate(starts):
            end = starts[index + 1] if index + 1 < len(starts) else self.bank_ends[bank]
            address = start
            while address < end:
                offset = self._bank_offset(bank, address)
                length = ChapterEventCodec.instruction_length(
                    self.data[offset], self.data, offset
                )
                if address + length > end:
                    raise RomFormatError("章节事件参数越过下一入口。")
                views[address] = self.data[offset:offset + length]
                address += length

        pending = [
            int.from_bytes(raw[1:3], "little")
            for raw in views.values()
            if raw[0] & 0x7F in self.JUMP_OPCODES
        ]
        expanded: set[int] = set()
        while pending:
            address = pending.pop()
            if address in views or address in expanded:
                continue
            expanded.add(address)
            while address < self.bank_ends[bank] and address not in views:
                offset = self._bank_offset(bank, address)
                length = ChapterEventCodec.instruction_length(
                    self.data[offset], self.data, offset
                )
                if address + length > self.bank_ends[bank]:
                    raise RomFormatError("章节事件分支流越过安全边界。")
                raw = self.data[offset:offset + length]
                views[address] = raw
                if raw[0] & 0x7F in self.JUMP_OPCODES:
                    pending.append(int.from_bytes(raw[1:3], "little"))
                address += length
        return views

    def _structural_patches(
        self,
        instruction: LegacyScenarioInstruction,
        replacement: bytes,
    ) -> tuple[tuple[int, bytes, bytes], ...]:
        current = next(
            (
                item
                for item in self.instructions(instruction.scenario_id, instruction.phase)
                if item.address == instruction.address
            ),
            None,
        )
        if current is None or current.raw != instruction.raw or current.bank != instruction.bank:
            raise ValueError("事件已变化，请重新载入。")
        self._validate_sequence(replacement, allow_empty=True)
        bank = current.bank
        views = self._views_for_bank(bank)
        selected_start = current.address
        selected_end = selected_start + len(current.raw)
        for address, raw in views.items():
            if address == selected_start:
                continue
            if address < selected_end and selected_start < address + len(raw):
                raise ValueError(
                    f"当前字节同时属于 ${address:04X} 的分支解释，"
                    "不能进行变长操作；可继续等长修改参数。"
                )

        delta = len(replacement) - len(current.raw)
        if delta == 0:
            return ((current.file_offset, current.raw, bytes(replacement)),)
        fixed_end = self.BANK_ENDS[bank]
        used_end = self.bank_ends[bank]
        if used_end + delta > fixed_end:
            raise ValueError(
                f"Bank ${bank:02X} 事件池只剩 {fixed_end - used_end} 字节，"
                f"本次需要新增 {delta} 字节；请先缩短同 Bank 的其他指令。"
            )
        if used_end + delta <= 0xA000:
            raise ValueError("章节事件池重排结果无效。")

        def relocate(address: int) -> int:
            if address <= selected_start:
                return address
            if address >= selected_end:
                return address + delta
            raise ValueError(
                f"地址 ${address:04X} 指向被替换指令内部，不能安全变长。"
            )

        pool_offset = self._bank_offset(bank)
        fixed_size = fixed_end - 0xA000
        before_pool = self.data[pool_offset:pool_offset + fixed_size]
        local_start = selected_start - 0xA000
        local_end = selected_end - 0xA000
        logical_end = used_end - 0xA000
        packed = bytearray(
            before_pool[:local_start]
            + bytes(replacement)
            + before_pool[local_end:logical_end]
        )
        packed.extend(b"\xDF" * (fixed_size - len(packed)))

        # Rebase every jump in both the normal and overlapping instruction
        # views.  Conflicting writes fail closed instead of guessing.
        operand_writes: dict[int, bytes] = {}
        replacement_rows = self._validate_sequence(replacement, allow_empty=True)
        replacement_cursor = selected_start
        replacement_views: dict[int, bytes] = {}
        for raw in replacement_rows:
            replacement_views[replacement_cursor] = raw
            replacement_cursor += len(raw)
        for address, raw in (*views.items(), *replacement_views.items()):
            if selected_start <= address < selected_end and address not in replacement_views:
                continue
            opcode = raw[0] & 0x7F
            if opcode not in self.JUMP_OPCODES:
                continue
            target = int.from_bytes(raw[1:3], "little")
            new_address = address if address in replacement_views else relocate(address)
            new_target = relocate(target)
            write_at = new_address - 0xA000 + 1
            value = new_target.to_bytes(2, "little")
            previous = operand_writes.get(write_at)
            if previous is not None and previous != value:
                raise ValueError("重叠事件流要求不同的跳转重定位结果，已拒绝写入。")
            operand_writes[write_at] = value
        for offset, value in operand_writes.items():
            packed[offset:offset + 2] = value

        patches: list[tuple[int, bytes, bytes]] = []
        for phase, table in enumerate(self.POINTER_TABLES):
            values = list(self.pointers[phase])
            changed = False
            for chapter, pointer in enumerate(values):
                if self.bank(chapter, phase) != bank:
                    continue
                moved = relocate(pointer)
                if moved != pointer:
                    values[chapter] = moved
                    changed = True
            if changed:
                before = self.data[table:table + 64]
                after = b"".join(value.to_bytes(2, "little") for value in values)
                patches.append((table, before, after))
        patches.append((pool_offset, before_pool, bytes(packed)))

        candidate = bytearray(self.data)
        for offset, before, after in patches:
            if candidate[offset:offset + len(before)] != before:
                raise ValueError("章节事件数据在重排前已变化。")
            candidate[offset:offset + len(after)] = after
        LegacyScenarioCodec(candidate)
        return tuple(patches)

    def replacement_patches(
        self,
        instruction: LegacyScenarioInstruction,
        raw: bytes,
    ) -> tuple[tuple[int, bytes, bytes], ...]:
        return self._structural_patches(instruction, bytes(raw))

    def insertion_patches(
        self,
        instruction: LegacyScenarioInstruction,
        raw: bytes,
        *,
        after: bool,
    ) -> tuple[tuple[int, bytes, bytes], ...]:
        self._validate_sequence(raw)
        replacement = instruction.raw + bytes(raw) if after else bytes(raw) + instruction.raw
        return self._structural_patches(instruction, replacement)

    def deletion_patches(
        self,
        instruction: LegacyScenarioInstruction,
    ) -> tuple[tuple[int, bytes, bytes], ...]:
        return self._structural_patches(instruction, b"")
