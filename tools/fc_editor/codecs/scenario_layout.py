from __future__ import annotations

import hashlib
import struct

from ..errors import RomFormatError
from ..models import PlayerPlacement, ScenarioEntity, ScenarioLayout
from ..rom_image import RomImage


class ScenarioLayoutCodec:
    """Lossless codec for scenario prelude, enemy, guest and player placement lists."""

    def __init__(self, rom: RomImage) -> None:
        self.rom = rom
        self.pointers = self._read_pointers()
        self.offsets = tuple(self.pointer_to_file_offset(pointer) for pointer in self.pointers)
        unique_pointers = sorted(set(self.pointers))
        capacity_by_pointer = {
            pointer: (
                unique_pointers[index + 1]
                if index + 1 < len(unique_pointers)
                else self.rom.profile.scenario_data_end_pointer
            )
            - pointer
            for index, pointer in enumerate(unique_pointers)
        }
        if any(capacity <= 0 for capacity in capacity_by_pointer.values()):
            raise RomFormatError("场景部署记录容量无效。")
        self.capacities = tuple(capacity_by_pointer[pointer] for pointer in self.pointers)

    def _read_pointers(self) -> tuple[int, ...]:
        profile = self.rom.profile
        if profile.scenario_count == 0:
            return ()
        pointers = struct.unpack(
            f"<{profile.scenario_count}H",
            self.rom.read(profile.scenario_pointer_table_offset, profile.scenario_count * 2),
        )
        if pointers[0] != profile.scenario_first_pointer:
            raise RomFormatError("场景部署指针表起始标记不正确。")
        if any(
            not profile.scenario_data_window_base
            <= pointer
            < profile.scenario_data_end_pointer
            for pointer in pointers
        ):
            raise RomFormatError("场景部署指针超出当前 ROM 的存储区。")
        return tuple(pointers)

    def pointer_to_file_offset(self, pointer: int) -> int:
        profile = self.rom.profile
        if not profile.scenario_data_window_base <= pointer < profile.scenario_data_end_pointer:
            raise ValueError(f"场景 CPU 指针 ${pointer:04X} 无效。")
        return (
            16
            + profile.scenario_data_prg_bank * 0x2000
            + pointer
            - profile.scenario_data_window_base
        )

    def record_offset(self, map_id: int) -> int:
        if not 0 <= map_id < self.rom.profile.scenario_count:
            raise IndexError(
                f"Scenario ID must be between 00 and {self.rom.profile.scenario_count - 1:02X}"
            )
        return self.offsets[map_id]

    @staticmethod
    def _read_until_sentinel(block: bytes, cursor: int, label: str) -> tuple[tuple[int, ...], int]:
        values: list[int] = []
        while cursor < len(block) and block[cursor] != 0xFF:
            values.append(block[cursor])
            cursor += 1
        if cursor >= len(block):
            raise RomFormatError(f"{label}缺少 FF 结束标记。")
        return tuple(values), cursor + 1

    @staticmethod
    def _read_fixed_entries(
        block: bytes,
        cursor: int,
        size: int,
        label: str,
    ) -> tuple[tuple[bytes, ...], int]:
        entries: list[bytes] = []
        while cursor < len(block) and block[cursor] != 0xFF:
            end = cursor + size
            if end > len(block):
                raise RomFormatError(f"{label}记录不完整。")
            entries.append(block[cursor:end])
            cursor = end
        if cursor >= len(block):
            raise RomFormatError(f"{label}缺少 FF 结束标记。")
        return tuple(entries), cursor + 1

    def decode(self, map_id: int, data: bytes | None = None) -> ScenarioLayout:
        source = self.rom.data if data is None else data
        offset = self.record_offset(map_id)
        capacity = self.capacities[map_id]
        block = bytes(source[offset : offset + capacity])
        if len(block) != capacity:
            raise RomFormatError(f"场景 {map_id:02X} 部署数据块不完整。")
        prelude, cursor = self._read_until_sentinel(block, 0, "场景前导列表")
        enemy_raw, cursor = self._read_fixed_entries(block, cursor, 6, "敌方部署")
        guest_raw, cursor = self._read_fixed_entries(block, cursor, 6, "客军部署")
        player_raw, cursor = self._read_fixed_entries(block, cursor, 4, "我方出击位")
        enemies = tuple(ScenarioEntity(*entry) for entry in enemy_raw)
        guests = tuple(ScenarioEntity(*entry) for entry in guest_raw)
        placements = tuple(PlayerPlacement(*entry) for entry in player_raw)
        return ScenarioLayout(
            map_id,
            self.pointers[map_id],
            prelude,
            enemies,
            guests,
            placements,
            block[:cursor],
            capacity,
        )

    @staticmethod
    def encode(layout: ScenarioLayout) -> bytes:
        result = bytearray(layout.prelude)
        result.append(0xFF)
        for entity in layout.enemies:
            result.extend(entity.to_bytes())
        result.append(0xFF)
        for entity in layout.guests:
            result.extend(entity.to_bytes())
        result.append(0xFF)
        for placement in layout.player_placements:
            result.extend(placement.to_bytes())
        result.append(0xFF)
        return bytes(result)

    @staticmethod
    def semantic_digest(layout: ScenarioLayout) -> str:
        return hashlib.sha256(ScenarioLayoutCodec.encode(layout)).hexdigest().upper()

    def replacement_patch(
        self,
        data: bytes,
        layout: ScenarioLayout,
    ) -> tuple[int, bytes, bytes]:
        offset = self.record_offset(layout.map_id)
        capacity = self.capacities[layout.map_id]
        encoded = self.encode(layout)
        if len(encoded) > capacity:
            raise ValueError(
                f"场景 {layout.map_id:02X} 部署数据需要 {len(encoded)} 字节，"
                f"原数据块只有 {capacity} 字节。"
            )
        before = bytes(data[offset : offset + capacity])
        after = encoded + before[len(encoded) :]
        return offset, before, after

    def round_trip(self, map_id: int) -> bool:
        layout = self.decode(map_id)
        return self.encode(layout) == layout.raw
