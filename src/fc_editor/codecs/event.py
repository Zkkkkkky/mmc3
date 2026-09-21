from __future__ import annotations

from dataclasses import dataclass
from typing import Literal


EventEvidence = Literal["confirmed", "structural"]


@dataclass(frozen=True)
class EventOpcodeSpec:
    opcode: int
    label: str
    handler: int
    evidence: EventEvidence
    length_rule: str


@dataclass(frozen=True)
class EventInstruction:
    offset: int
    opcode: int
    raw: bytes
    label: str
    truncated: bool = False


EVENT_OPCODE_SPECS = (
    EventOpcodeSpec(0xF0, "批量写入内存", 0xEB4F, "structural", "3 + count"),
    EventOpcodeSpec(0xF1, "显示标志子命令", 0xEB71, "structural", "2"),
    EventOpcodeSpec(0xF2, "批量切换映射", 0xEBF0, "structural", "3 + count"),
    EventOpcodeSpec(0xF3, "调用服务", 0xEC08, "structural", "3"),
    EventOpcodeSpec(0xF4, "设置状态", 0xEC21, "structural", "2"),
    EventOpcodeSpec(0xF5, "设置坐标或槽位", 0xEC2A, "structural", "3"),
    EventOpcodeSpec(0xF6, "设置显示状态", 0xEC49, "structural", "2"),
    EventOpcodeSpec(0xF7, "设置对象属性", 0xEC52, "structural", "3"),
    EventOpcodeSpec(0xF8, "生成绝对坐标对象", 0xED53, "structural", "flags"),
    EventOpcodeSpec(0xF9, "生成相对坐标对象", 0xED8E, "structural", "flags"),
    EventOpcodeSpec(0xFA, "移除对象", 0xEE16, "structural", "2"),
    EventOpcodeSpec(0xFB, "显示对象", 0xEE35, "structural", "2"),
    EventOpcodeSpec(0xFC, "隐藏对象", 0xEE45, "structural", "2"),
    EventOpcodeSpec(0xFD, "移动镜头", 0xEE55, "structural", "3"),
    EventOpcodeSpec(0xFE, "循环或跳转", 0xEEF9, "structural", "4"),
    EventOpcodeSpec(0xFF, "脚本结束", 0xEF21, "confirmed", "1"),
)
EVENT_OPCODE_BY_VALUE = {spec.opcode: spec for spec in EVENT_OPCODE_SPECS}


class EventScriptCodec:
    """Lossless structural decoder for the fixed-bank visual event VM.

    The registry documents the dispatcher at CPU $E844.  It deliberately does
    not claim to be the game's chapter-flow or dialogue-choice format.
    """

    @staticmethod
    def instruction_length(data: bytes, offset: int) -> int:
        if not 0 <= offset < len(data):
            raise IndexError("事件脚本偏移超出数据范围。")
        opcode = data[offset]
        if opcode < 0xF0:
            return 1
        if opcode in (0xF0, 0xF2):
            if offset + 2 >= len(data):
                return 3
            return 3 + data[offset + 2]
        if opcode in (0xF8, 0xF9):
            if offset + 1 >= len(data):
                return 2
            flags = data[offset + 1]
            return 7 + (0 if flags & 0x80 else 1) + (0 if flags & 0x40 else 1)
        return {
            0xF1: 2,
            0xF3: 3,
            0xF4: 2,
            0xF5: 3,
            0xF6: 2,
            0xF7: 3,
            0xFA: 2,
            0xFB: 2,
            0xFC: 2,
            0xFD: 3,
            0xFE: 4,
            0xFF: 1,
        }[opcode]

    @classmethod
    def decode(cls, data: bytes, *, stop_at_end: bool = True) -> tuple[EventInstruction, ...]:
        instructions: list[EventInstruction] = []
        position = 0
        while position < len(data):
            opcode = data[position]
            expected_length = cls.instruction_length(data, position)
            end = min(position + expected_length, len(data))
            spec = EVENT_OPCODE_BY_VALUE.get(opcode)
            instructions.append(
                EventInstruction(
                    position,
                    opcode,
                    data[position:end],
                    "延时帧" if spec is None else spec.label,
                    end - position != expected_length,
                )
            )
            position = end
            if opcode == 0xFF and stop_at_end:
                break
        return tuple(instructions)
