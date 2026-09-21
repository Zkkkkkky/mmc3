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
        for phase in range(3):
            for chapter in range(32):
                self.instructions(chapter, phase)

    @staticmethod
    def bank(chapter: int, phase: int) -> int:
        if not 0 <= chapter < 32 or not 0 <= phase < 3:
            raise IndexError("关卡或事件阶段编号无效。")
        return 0x1E if phase < 2 else (0x1B if chapter < 10 else 0x1F)

    def instructions(self, chapter: int, phase: int) -> tuple[LegacyScenarioInstruction, ...]:
        bank = self.bank(chapter, phase)
        start = self.pointers[phase][chapter]
        end = min((p for p in self._starts[bank] if p > start), default=self.BANK_ENDS[bank])
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
