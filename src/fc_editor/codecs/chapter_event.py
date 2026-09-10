from __future__ import annotations

import struct
from dataclasses import dataclass

from ..errors import RomFormatError
from ..profiles import ChapterEventSpec
from ..rom_image import RomImage


# Length includes the opcode. Values come from the bank $1A dispatch table and
# its handlers. Opcode $43 is the sole data-dependent instruction.
INSTRUCTION_LENGTHS = (
    2, 2, 3, 2, 2, 2, 2, 2, 3, 4, 3, 2, 4, 2, 3, 3,
    6, 2, 3, 5, 1, 2, 2, 3, 3, 3, 2, 2, 3, 1, 2, 3,
    3, 4, 4, 5, 7, 3, 1, 2, 1, 1, 1, 1, 1, 1, 1, 1,
    2, 3, 3, 3, 2, 4, 2, 3, 2, 2, 8, 2, 2, 8, 4, 4,
    4, 4, 4, 0, 3, 1, 3, 2, 2, 2, 7, 7, 5, 4, 3, 3,
    3, 2, 2, 3, 3, 3, 4, 3, 3, 2, 2, 2, 5, 8, 2, 1,
    2, 2, 1, 1, 2, 3, 2, 1, 1, 2, 1, 1, 1, 5, 2, 5,
    2, 1, 1, 1, 2, 7, 7, 5, 1, 1, 1,
)


ACTION_LABELS = {
    0x4A: "客军增援",
    0x4B: "敌军增援",
    0x4C: "我方出击/加入",
    0x4D: "替换人物与机体",
    0x4E: "更换机体",
    0x67: "转为临时友军",
    0x68: "转为敌军",
    0x69: "正式加入我方（说得/加入）",
    0x6A: "当前单位自爆",
    0x6B: "移除当前单位",
    0x75: "客军增援（别名）",
    0x76: "敌军增援（别名）",
    0x77: "我方出击/加入（别名）",
}


OPCODE_LABELS = {
    0x00: "回合判定",
    0x01: "开关判定",
    0x02: "人物行动限制位判定",
    0x03: "人物在队伍判定",
    0x04: "人物在战场判定",
    0x05: "人物在母舰判定",
    0x06: "敌方数量判定",
    0x07: "我方数量判定",
    0x08: "持有道具判定",
    0x09: "指定人物受伤判定",
    0x0A: "我方进入范围判定",
    0x0B: "敌方进入范围判定",
    0x0C: "人物进入坐标判定",
    0x0D: "当前人物行动限制判定",
    0x0E: "接触人物判定",
    0x0F: "当前人物坐标判定",
    0x10: "当前人物范围判定",
    0x11: "敌人距离判定",
    0x12: "当前人物受伤判定",
    0x13: "攻击/击落判定",
    0x14: "向最近敌人移动",
    0x15: "向指定人物移动判定",
    0x16: "无视机动力移向人物",
    0x17: "按指定机动力移向坐标",
    0x18: "移向坐标判定",
    0x19: "无视机动力移向坐标",
    0x1A: "自动攻击判定",
    0x1B: "攻击指定人物判定",
    0x1C: "排除指定人物的攻击判定",
    0x1D: "地图炮攻击判定",
    0x1E: "选择人物上下文",
    **{opcode: f"保留条件 ${opcode:02X}（默认处理）" for opcode in range(0x1F, 0x40)},
    0x40: "无光标人物对话",
    0x41: "光标指向人物并对话",
    0x42: "光标对话调用",
    0x43: "打开文字窗口",
    0x44: "在文字窗口显示文本",
    0x45: "关闭对白窗口",
    0x46: "光标移至坐标",
    0x47: "光标移至人物",
    0x48: "光标移至人物并等待",
    0x49: "写入事件临时变量",
    0x4A: "客军增援",
    0x4B: "敌军增援",
    0x4C: "我方出击/加入",
    0x4D: "替换人物与机体",
    0x4E: "更换人物机体",
    0x4F: "获得道具",
    0x50: "获得金钱",
    0x51: "打开事件开关",
    0x52: "关闭事件开关",
    0x53: "限制人物移动",
    0x54: "解除人物移动限制",
    0x55: "无条件跳转",
    0x56: "否定判定",
    0x57: "条件成立跳转",
    0x58: "条件不成立跳转",
    0x59: "设置我方阶段音乐",
    0x5A: "设置敌方阶段音乐",
    0x5B: "立即播放音乐",
    0x5C: "等待指定帧数",
    0x5D: "等待指定帧数（变体）",
    0x5E: "等待指定帧数（变体）",
    0x5F: "保留/无效果",
    0x60: "限制当前人物移动",
    0x61: "解除当前人物移动限制",
    0x62: "执行攻击或移动",
    0x63: "执行待机",
    0x64: "光标控制指定人物",
    0x65: "传真效果移动到坐标",
    0x66: "当前人物更换机体（不恢复）",
    0x67: "转为临时友军",
    0x68: "转为敌军",
    0x69: "正式加入我方（说得/加入）",
    0x6A: "当前单位自爆",
    0x6B: "当前单位撤退/离场",
    0x6C: "刷新移动坐标",
    0x6D: "直接获得经验与金钱",
    0x6E: "指定队友离队",
    0x6F: "人物直接加入队伍",
    0x70: "提升队员等级",
    0x71: "关卡胜利",
    0x72: "关卡失败",
    0x73: "游戏通关",
    0x74: "扩展事件指令 $74",
    0x75: "客军增援（扩展别名）",
    0x76: "敌军增援（扩展别名）",
    0x77: "我方出击/加入（扩展别名）",
    0x78: "扩展事件指令 $78",
    0x79: "扩展事件指令 $79",
    0x7A: "扩展事件指令 $7A",
}


ACTION_FIELDS = {
    0x4A: ("X", "Y", "人物ID", "机体ID", "等级", "AI/标志"),
    0x4B: ("X", "Y", "人物ID", "机体ID", "等级", "AI/标志"),
    0x4C: ("X/特殊标志", "Y", "队伍槽", "标志"),
    0x4D: ("目标人物ID", "新人物ID", "新机体ID"),
    0x4E: ("目标人物ID", "新机体ID"),
    0x69: ("队伍/成长参数",),
    0x75: ("X", "Y", "机体ID", "人物ID", "等级", "AI/标志"),
    0x76: ("X", "Y", "机体ID", "人物ID", "等级", "AI/标志"),
    0x77: ("X/特殊标志", "Y", "队伍槽", "标志"),
}


@dataclass(frozen=True)
class ChapterEventContext:
    scenario_id: int
    phase: int
    label: str


@dataclass(frozen=True)
class ChapterEventInstruction:
    address: int
    file_offset: int
    raw_opcode: int
    opcode: int
    raw: bytes
    contexts: tuple[ChapterEventContext, ...]

    @property
    def is_terminal(self) -> bool:
        return bool(self.raw_opcode & 0x80)

    @property
    def action_label(self) -> str:
        return OPCODE_LABELS.get(self.opcode, f"未知操作码 ${self.opcode:02X}")

    @property
    def field_labels(self) -> tuple[str, ...]:
        return ACTION_FIELDS.get(self.opcode, ())

    @property
    def parameters(self) -> tuple[int, ...]:
        return tuple(self.raw[1:])


class ChapterEventCodec:
    """Lossless fixed-address editor for DC's chapter event VM."""

    def __init__(self, rom: RomImage) -> None:
        spec = rom.profile.chapter_events
        if spec is None:
            raise ValueError("当前ROM配置没有章节事件布局。")
        self.rom = rom
        self.spec = spec
        self.phase_pointers = self._read_phase_pointers(rom.data)
        self._validate_phase_pointers(self.phase_pointers)
        # Validate that the known baseline is instruction-aligned.
        self.instructions(rom.data)

    def code_address_to_file_offset(self, address: int) -> int:
        if not 0x8000 <= address < 0xA000:
            raise ValueError(f"事件代码地址 ${address:04X} 无效。")
        return 16 + self.spec.code_prg_bank * 0x2000 + address - 0x8000

    def data_address_to_file_offset(self, address: int) -> int:
        if not self.spec.data_start <= address < self.spec.data_end:
            raise ValueError(f"事件数据地址 ${address:04X} 无效。")
        return (
            16
            + self.spec.data_prg_bank * 0x2000
            + address
            - self.spec.data_window_base
        )

    def _read_phase_pointers(self, data: bytes) -> tuple[tuple[int, ...], ...]:
        result = []
        for table in self.spec.pointer_tables:
            offset = self.code_address_to_file_offset(table)
            size = self.spec.scenario_count * 2
            if offset + size > len(data):
                raise RomFormatError("章节事件指针表超出ROM。")
            result.append(struct.unpack(f"<{self.spec.scenario_count}H", data[offset : offset + size]))
        return tuple(tuple(values) for values in result)

    def _validate_phase_pointers(self, pointers: tuple[tuple[int, ...], ...]) -> None:
        for phase, values in enumerate(pointers):
            if any(not self.spec.data_start <= value < self.spec.data_end for value in values):
                raise RomFormatError(f"章节事件阶段 {phase + 1} 的指针超出脚本区。")

    @staticmethod
    def instruction_length(raw_opcode: int, data: bytes, offset: int) -> int:
        opcode = raw_opcode & 0x7F
        if opcode >= len(INSTRUCTION_LENGTHS):
            raise RomFormatError(f"未知章节事件操作码 ${raw_opcode:02X}。")
        length = INSTRUCTION_LENGTHS[opcode]
        if opcode == 0x43:
            if offset + 1 >= len(data):
                raise RomFormatError("章节事件操作码 $43 缺少参数。")
            length = 3 if data[offset + 1] in (0x0B, 0x0C) else 2
        return length

    def contexts_for_address(self, address: int) -> tuple[ChapterEventContext, ...]:
        contexts = []
        for phase, pointers in enumerate(self.phase_pointers):
            starts = sorted(set(pointers))
            eligible = [start for start in starts if start <= address]
            if not eligible:
                continue
            start = eligible[-1]
            next_starts = [candidate for candidate in starts if candidate > start]
            end = next_starts[0] if next_starts else self.spec.data_end
            if address < end:
                for scenario_id, pointer in enumerate(pointers):
                    if pointer != start:
                        continue
                    contexts.append(
                        ChapterEventContext(
                            scenario_id,
                            phase,
                            self.spec.phase_labels[phase],
                        )
                    )
        return tuple(contexts)

    def instructions(self, data: bytes | bytearray | None = None) -> tuple[ChapterEventInstruction, ...]:
        source = self.rom.data if data is None else bytes(data)
        start = self.data_address_to_file_offset(self.spec.data_start)
        end = start + self.spec.data_end - self.spec.data_start
        block = source[start:end]
        if len(block) != end - start:
            raise RomFormatError("章节事件脚本区不完整。")
        result = []
        cursor = 0
        while cursor < len(block):
            raw_opcode = block[cursor]
            length = self.instruction_length(raw_opcode, block, cursor)
            if cursor + length > len(block):
                raise RomFormatError("章节事件参数越过脚本区。")
            address = self.spec.data_start + cursor
            result.append(
                ChapterEventInstruction(
                    address,
                    start + cursor,
                    raw_opcode,
                    raw_opcode & 0x7F,
                    block[cursor : cursor + length],
                    self.contexts_for_address(address),
                )
            )
            cursor += length
        return tuple(result)

    def actions(self, data: bytes | bytearray | None = None) -> tuple[ChapterEventInstruction, ...]:
        return tuple(
            instruction
            for instruction in self.instructions(data)
            if instruction.opcode in ACTION_LABELS
        )

    def instruction_at(
        self,
        address: int,
        data: bytes | bytearray | None = None,
    ) -> ChapterEventInstruction:
        return next(
            (item for item in self.instructions(data) if item.address == address),
            None,
        ) or self._raise_missing(address)

    @staticmethod
    def _raise_missing(address: int):
        raise ValueError(f"${address:04X} 不是章节事件指令起始地址。")

    def replacement_patch(
        self,
        data: bytes | bytearray,
        address: int,
        replacement: bytes,
    ) -> tuple[int, bytes, bytes]:
        instruction = self.instruction_at(address, data)
        if len(replacement) != len(instruction.raw):
            raise ValueError(
                f"事件指令必须保持 {len(instruction.raw)} 字节；当前为 {len(replacement)} 字节。"
            )
        new_length = self.instruction_length(replacement[0], replacement, 0)
        if new_length != len(replacement):
            raise ValueError(
                f"新操作码需要 {new_length} 字节，与原槽 {len(replacement)} 字节不兼容。"
            )
        return instruction.file_offset, instruction.raw, bytes(replacement)
