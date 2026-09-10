from __future__ import annotations

import struct
from dataclasses import dataclass

from ..errors import RomFormatError
from ..rom_image import RomImage


@dataclass(frozen=True)
class PersuasionRule:
    slot: int
    scenario_id: int
    persuader_id: int
    target_id: int
    script_address: int
    file_offset: int

    @property
    def raw(self) -> bytes:
        return bytes((self.scenario_id, self.persuader_id, self.target_id))


class PersuasionRuleCodec:
    """Fixed-size editor for DC's chapter/persuader/target match table."""

    RECORD_SIZE = 3
    TERMINATOR = 0xFF

    def __init__(self, rom: RomImage) -> None:
        spec = rom.profile.persuasion_rules
        if spec is None:
            raise ValueError("当前ROM配置没有已验证的劝降规则表。")
        self.rom = rom
        self.spec = spec
        table_end = spec.table_offset + spec.slot_count * self.RECORD_SIZE
        pointer_end = spec.script_pointer_table_offset + spec.slot_count * 2
        if table_end >= len(rom.data) or pointer_end > len(rom.data):
            raise RomFormatError("劝降规则表或脚本指针表超出ROM。")
        if rom.data[table_end] != self.TERMINATOR:
            raise RomFormatError("劝降规则表缺少 $FF 结束码。")
        self.script_pointers = struct.unpack(
            f"<{spec.slot_count}H",
            rom.data[spec.script_pointer_table_offset:pointer_end],
        )
        chapter = rom.profile.chapter_events
        if chapter is not None and any(
            not chapter.data_start <= pointer < chapter.data_end
            for pointer in self.script_pointers
        ):
            raise RomFormatError("劝降事件脚本指针超出已验证脚本区。")
        for slot in range(spec.editable_count):
            self.validate_rule(self.decode(slot), rom.profile.scenario_count)

    def record_offset(self, slot: int) -> int:
        if not 0 <= slot < self.spec.slot_count:
            raise IndexError("劝降规则槽位超出范围。")
        return self.spec.table_offset + slot * self.RECORD_SIZE

    def decode(
        self,
        slot: int,
        data: bytes | bytearray | None = None,
    ) -> PersuasionRule:
        source = self.rom.data if data is None else bytes(data)
        offset = self.record_offset(slot)
        raw = source[offset:offset + self.RECORD_SIZE]
        if len(raw) != self.RECORD_SIZE:
            raise RomFormatError("劝降规则记录不完整。")
        return PersuasionRule(
            slot,
            raw[0],
            raw[1],
            raw[2],
            self.script_pointers[slot],
            offset,
        )

    def editable_rules(
        self,
        data: bytes | bytearray | None = None,
    ) -> tuple[PersuasionRule, ...]:
        return tuple(
            self.decode(slot, data) for slot in range(self.spec.editable_count)
        )

    @staticmethod
    def validate_rule(rule: PersuasionRule, scenario_count: int) -> None:
        if not 0 <= rule.scenario_id < scenario_count:
            raise ValueError(
                f"劝降规则 ${rule.slot:02X} 的章节 ${rule.scenario_id:02X} 越界。"
            )
        for label, value in (
            ("劝说者", rule.persuader_id),
            ("目标", rule.target_id),
        ):
            if not 1 <= value <= 0xC7:
                raise ValueError(
                    f"劝降规则 ${rule.slot:02X} 的{label}ID ${value:02X} 无效。"
                )

    def replacement_patch(
        self,
        data: bytes | bytearray,
        slot: int,
        scenario_id: int,
        persuader_id: int,
        target_id: int,
    ) -> tuple[int, bytes, bytes]:
        if not 0 <= slot < self.spec.editable_count:
            raise ValueError(
                f"槽位 ${slot:02X} 没有独立安全脚本，不允许激活。"
            )
        current = self.decode(slot, data)
        changed = PersuasionRule(
            slot,
            scenario_id,
            persuader_id,
            target_id,
            current.script_address,
            current.file_offset,
        )
        self.validate_rule(changed, self.rom.profile.scenario_count)
        return current.file_offset, current.raw, changed.raw
