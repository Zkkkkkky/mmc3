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
    0x0A: "剩余金钱判定",
    0x0B: "待机数量判定",
    0x0C: "人物进入坐标判定",
    0x0D: "当前人物行动限制判定",
    0x0E: "与某人距离判定（行动）",
    0x0F: "进入某坐标判定（行动）",
    0x10: "进入某范围判定（行动）",
    0x11: "周围有无敌方判定（行动）",
    0x12: "剩余HP判定（行动）",
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
    0x1F: "提升五围（仅限我方，行动）",
    0x20: "剩余HP判定",
    0x21: "地址量位判定",
    0x22: "属性某位判定（行动）",
    0x23: "属性值少于判定（行动）",
    0x24: "范围内机体数量判定",
    0x25: "周围机体数量判定（行动）",
    0x26: "选项判定",
    0x27: "选项判断",
    0x30: "播放战场动画",
    0x31: "人物 HP 增减",
    0x32: "人物 HP 增减（变体）",
    0x33: "人物 HP 增减（变体）",
    0x34: "按百分比恢复 HP",
    0x35: "设置或取消状态位",
    0x36: "强制移动某人（行动）",
    0x38: "传送到人物周围",
    0x39: "恢复精神值",
    0x3A: "范围内机体 HP 增减",
    0x3B: "敌方精神效果",
    0x3C: "选项事件",
    0x3D: "范围内机体 HP 增减（变体）",
    0x3E: "周围机体 HP 增减",
    0x3F: "周围机体 HP 增减（变体）",
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
    0x00: ("目标回合",),
    0x01: ("开关与状态",),
    0x02: ("人物ID", "行动限制代码"),
    0x03: ("人物ID",),
    0x04: ("人物ID",),
    0x05: ("人物ID",),
    0x06: ("敌方数量",),
    0x07: ("我方数量",),
    0x08: ("道具ID", "数量/状态"),
    0x09: ("人物ID", "HP低字节", "HP高字节"),
    0x0A: ("X", "Y"),
    0x0B: ("范围/状态",),
    0x0C: ("人物ID", "X", "Y"),
    0x0D: ("行动限制代码",),
    0x0E: ("人物ID", "目标人物ID"),
    0x0F: ("X", "Y"),
    0x10: ("人物ID", "X", "Y", "范围", "标志"),
    0x11: ("距离",),
    0x12: ("HP低字节", "HP高字节"),
    0x13: ("人物ID", "攻击/击落标志", "附加参数", "状态"),
    0x15: ("目标人物ID",),
    0x16: ("目标人物ID",),
    0x17: ("X", "Y"),
    0x18: ("X", "Y"),
    0x19: ("X", "Y"),
    0x1A: ("攻击标志",),
    0x1B: ("目标人物ID",),
    0x1C: ("排除人物ID", "攻击标志"),
    0x1D: (),
    0x1E: ("人物ID",),
    0x27: ("选项编号/状态",),
    0x3C: ("选项数量",),
    0x40: ("头像ID", "文本组", "文本编号"),
    0x41: ("人物/头像ID", "文本组", "文本编号"),
    0x42: ("文本组", "文本编号", "附加参数"),
    0x43: ("窗口样式/位置",),
    0x44: ("文本组", "文本编号"),
    0x46: ("X", "Y"),
    0x47: ("人物ID",),
    0x48: ("人物ID",),
    0x49: ("临时变量值",),
    0x4A: ("X", "Y", "人物ID", "机体ID", "等级", "AI/标志"),
    0x4B: ("X", "Y", "人物ID", "机体ID", "等级", "AI/标志"),
    0x4C: ("X/特殊标志", "Y", "队伍槽", "标志"),
    0x4D: ("目标人物ID", "新人物ID", "新机体ID"),
    0x4E: ("目标人物ID", "新机体ID"),
    0x4F: ("道具ID", "数量/状态"),
    0x50: ("金钱低字节", "金钱高字节"),
    0x51: ("事件开关",),
    0x52: ("事件开关",),
    0x53: ("人物ID", "限制代码"),
    0x54: ("人物ID", "限制代码"),
    0x55: ("跳转地址低字节", "跳转地址高字节"),
    0x57: ("跳转地址低字节", "跳转地址高字节"),
    0x58: ("跳转地址低字节", "跳转地址高字节"),
    0x59: ("音乐命令",),
    0x5A: ("音乐命令",),
    0x5B: ("音乐命令",),
    0x5C: ("地址低字节", "地址高字节", "写入值", "模式"),
    0x5D: ("参数1", "参数2", "参数3", "参数4", "参数5", "参数6", "参数7"),
    0x5E: ("帧数",),
    0x60: ("限制代码",),
    0x61: ("限制代码",),
    0x62: (),
    0x64: ("人物ID",),
    0x65: ("X", "Y"),
    0x66: ("机体ID",),
    0x69: ("队伍/成长参数",),
    0x75: ("X", "Y", "机体ID", "人物ID", "等级", "AI/标志"),
    0x76: ("X", "Y", "机体ID", "人物ID", "等级", "AI/标志"),
    0x77: ("X/特殊标志", "Y", "队伍槽", "标志"),
}


OPCODE_HELP = {
    0x00: "检查当前回合是否满足条件；满足后继续执行后续指令。",
    0x01: "检查指定的本关或全局开关是否处于要求的开/关状态。",
    0x02: "检查某个人物的行动限制代码。",
    0x03: "检查人物是否已经加入我方队伍。",
    0x04: "检查人物是否正在当前战场上。",
    0x05: "检查人物是否位于母舰中。",
    0x06: "按当前敌方单位数量判断。",
    0x07: "按当前我方单位数量判断。",
    0x08: "检查指定道具的持有状态或数量。",
    0x09: "检查指定人物的当前 HP 是否达到条件。",
    0x0A: "检查玩家当前持有金钱是否达到指定条件。",
    0x0B: "检查已经结束行动、进入待机的单位数量。",
    0x0C: "检查指定人物是否到达指定坐标。",
    0x0D: "检查当前行动人物的限制代码。",
    0x0E: "行动时检查当前人物与指定人物的距离。",
    0x0F: "行动时检查当前人物是否进入指定坐标。",
    0x10: "行动时检查当前人物是否进入指定范围。",
    0x11: "行动时检查当前人物周围是否存在敌方单位。",
    0x12: "行动时检查当前人物的剩余 HP。",
    0x13: "检查指定人物是否攻击或击落目标。",
    0x14: "让当前人物向最近的敌人移动。",
    0x15: "让当前人物向指定人物移动。",
    0x16: "忽略通常机动力限制，向指定人物移动。",
    0x17: "按给定机动力向坐标移动。",
    0x18: "向指定坐标移动并产生判定结果。",
    0x19: "忽略通常机动力限制，向指定坐标移动。",
    0x1A: "让当前人物自动选择目标并攻击。",
    0x1B: "让当前人物只攻击指定人物。",
    0x1C: "攻击时排除指定人物。",
    0x1D: "执行地图炮攻击判断。",
    0x1E: "在不移动光标的情况下，把事件控制对象切换到指定人物。",
    0x1F: "提升我方人物的五项能力值。",
    0x20: "检查指定对象的剩余 HP。",
    0x21: "检查指定运行时地址中的位状态。",
    0x22: "行动时检查对象属性中的指定位。",
    0x23: "行动时检查对象属性值是否小于指定值。",
    0x24: "检查指定地图范围内的机体数量。",
    0x25: "行动时检查当前人物周围的机体数量。",
    0x26: "判断选项事件中的选择结果。",
    0x27: "判断文字选项窗口中被选择的项目。",
    0x3C: "建立一个分支选项事件，后续判断读取选择结果。",
    0x40: "显示不移动光标的对白；参数引用头像和剧情文字。",
    0x41: "把光标指向指定人物，然后显示对白。",
    0x42: "调用一条对白记录。",
    0x43: "打开剧情文字窗口，并设置窗口样式或位置。",
    0x44: "在已经打开的文字窗口中显示指定剧情文字。",
    0x45: "关闭当前剧情文字窗口。",
    0x46: "把地图光标移动到指定 X/Y 坐标。",
    0x47: "把地图光标移动到指定人物。",
    0x48: "把光标移动到人物并等待移动完成。",
    0x4A: "在指定坐标生成一台客军机体。",
    0x4B: "在指定坐标生成一台敌军机体。",
    0x4C: "安排我方单位出击或加入战场。",
    0x4D: "把目标记录同时替换为新人物和新机体。",
    0x4E: "更换指定人物当前驾驶的机体。",
    0x4F: "增加或减少指定道具。",
    0x50: "增加或减少玩家持有的金钱。",
    0x51: "打开指定事件开关。",
    0x52: "关闭指定事件开关。",
    0x53: "给指定人物设置移动限制。",
    0x54: "解除指定人物的移动限制。",
    0x55: "无条件跳到脚本中的另一个地址。",
    0x56: "把上一条条件判断的真假结果反转。",
    0x57: "上一条判断成立时跳到指定脚本地址。",
    0x58: "上一条判断不成立时跳到指定脚本地址。",
    0x59: "设置我方阶段使用的地图背景音乐。",
    0x5A: "设置敌方阶段使用的地图背景音乐。",
    0x5B: "立即播放指定背景音乐。",
    0x5C: "向指定运行时内存地址写入一个值。",
    0x5D: "等待指定帧数后继续事件。",
    0x5E: "等待指定帧数后继续事件。",
    0x60: "限制当前人物移动。",
    0x61: "解除当前人物的移动限制。",
    0x62: "让当前人物按参数执行移动或攻击。",
    0x63: "结束当前人物行动并进入待机。",
    0x64: "把事件控制对象切换到指定人物。",
    0x65: "以传真效果移动到指定坐标。",
    0x66: "给当前人物临时更换机体。",
    0x67: "把当前单位转为临时友军。",
    0x68: "把当前单位转为敌军。",
    0x69: "让当前人物正式加入我方队伍。",
    0x6A: "让当前单位执行自爆。",
    0x6B: "让当前单位撤退并离开战场。",
    0x71: "判定本关胜利。",
    0x72: "判定本关失败。",
    0x73: "进入游戏通关流程。",
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
