from __future__ import annotations

import unittest
from pathlib import Path

from py65.devices.mpu6502 import MPU

from fc_editor.codecs.map import MapCodec
from fc_editor.codecs.map_trigger import MapTriggerCodec
from fc_editor.codecs.scenario_layout import ScenarioLayoutCodec
from fc_editor.expansion_map import (
    SCENARIO_BANK_DIRECTORY_OFFSET,
    SCENARIO_HOOK_CODE,
    SCENARIO_HOOK_OFFSET,
    SCENARIO_RESOLVE_CALL_OFFSET,
    SCENARIO_RESOLVE_CALL_ORIGINAL,
    SCENARIO_RESOLVE_CALL_PATCH,
    TERRAIN_BANK_DIRECTORY_OFFSET,
    TERRAIN_DISPATCH_OFFSET,
    TERRAIN_DISPATCH_ORIGINAL,
    TERRAIN_DISPATCH_PATCH,
    TRIGGER_BANK_DIRECTORY_OFFSET,
    TRIGGER_DISPATCH_CALL_OFFSET,
    TRIGGER_DISPATCH_CALL_ORIGINAL,
    TRIGGER_DISPATCH_CALL_PATCH,
    TRIGGER_HOOK_CODE,
    TRIGGER_HOOK_OFFSET,
    link_map_resources,
    pack_map_resources,
    read_expanded_map_layout,
    read_expanded_map_payloads,
)
from fc_editor.rom_image import RomImage


ROOT = Path(__file__).resolve().parents[1]
TARGET_ROM = ROOT / "output" / "rom" / "DC_kuorong_464K.nes"


class _Mmc3Memory:
    """Minimal Mapper 194 PRG view for executing the three map hooks."""

    def __init__(self, rom: bytes, first_bank: int, second_bank: int) -> None:
        self.rom = rom
        self.ram = bytearray(0x10000)
        self.first_bank = first_bank
        self.second_bank = second_bank
        self.mapper_register = 0

    def _prg_byte(self, bank: int, offset: int) -> int:
        return self.rom[16 + bank * 0x2000 + offset]

    def __getitem__(self, address):
        if isinstance(address, slice):
            start, stop, step = address.indices(0x10000)
            return [self[index] for index in range(start, stop, step)]
        address &= 0xFFFF
        if 0x8000 <= address < 0xA000:
            return self._prg_byte(self.first_bank, address - 0x8000)
        if 0xA000 <= address < 0xC000:
            return self._prg_byte(self.second_bank, address - 0xA000)
        if 0xC000 <= address < 0xE000:
            return self._prg_byte(0x7E, address - 0xC000)
        if address >= 0xE000:
            return self._prg_byte(0x7F, address - 0xE000)
        return self.ram[address]

    def __setitem__(self, address, value) -> None:
        address &= 0xFFFF
        value &= 0xFF
        if address == 0x8000:
            self.mapper_register = value
            return
        if address == 0x8001:
            register = self.mapper_register & 0x07
            if register == 6:
                self.first_bank = value
            elif register == 7:
                self.second_bank = value
            return
        self.ram[address] = value


def _run_until(mpu: MPU, address: int, *, limit: int = 20_000) -> None:
    for _step in range(limit):
        if mpu.pc == address:
            return
        mpu.step()
    raise AssertionError(f"6502 在 {limit} 步内未到达 ${address:04X}。")


def _prepare_rts(memory: _Mmc3Memory, mpu: MPU, target: int = 0x0200) -> None:
    """Install one synthetic JSR return frame for a hook entered directly."""

    return_address = target - 1
    memory[0x01FE] = return_address & 0xFF
    memory[0x01FF] = return_address >> 8
    mpu.sp = 0xFD


class ExpandedMapLinkerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.rom = RomImage.load(TARGET_ROM)
        cls.source = cls.rom.data
        map_codec = MapCodec(cls.rom)
        scenario_codec = ScenarioLayoutCodec(cls.rom)
        trigger_codec = MapTriggerCodec(cls.rom)
        cls.terrain = tuple(
            map_codec.decode(map_id).raw
            for map_id in range(cls.rom.profile.map_count)
        )
        cls.scenarios = tuple(
            scenario_codec.encode(scenario_codec.decode(map_id))
            for map_id in range(cls.rom.profile.scenario_count)
        )
        cls.triggers = tuple(
            trigger_codec.encode_entries(trigger_codec.decode(map_id).entries)
            for map_id in range(trigger_codec.spec.scenario_count)
        )
        cls.linked, cls.packed, _patches = link_map_resources(
            cls.source,
            cls.terrain,
            cls.scenarios,
            cls.triggers,
            (0x40, 0x41),
        )

    def test_stock_hook_sites_and_holes_match_certified_bytes(self) -> None:
        self.assertEqual(
            self.source[
                TERRAIN_DISPATCH_OFFSET : TERRAIN_DISPATCH_OFFSET
                + len(TERRAIN_DISPATCH_ORIGINAL)
            ],
            TERRAIN_DISPATCH_ORIGINAL,
        )
        self.assertEqual(
            self.source[
                SCENARIO_RESOLVE_CALL_OFFSET : SCENARIO_RESOLVE_CALL_OFFSET + 3
            ],
            SCENARIO_RESOLVE_CALL_ORIGINAL,
        )
        self.assertEqual(
            self.source[
                TRIGGER_DISPATCH_CALL_OFFSET : TRIGGER_DISPATCH_CALL_OFFSET + 3
            ],
            TRIGGER_DISPATCH_CALL_ORIGINAL,
        )
        self.assertEqual(
            self.source[SCENARIO_HOOK_OFFSET : SCENARIO_HOOK_OFFSET + len(SCENARIO_HOOK_CODE)],
            bytes(len(SCENARIO_HOOK_CODE)),
        )
        self.assertEqual(
            self.source[TRIGGER_HOOK_OFFSET : TRIGGER_HOOK_OFFSET + len(TRIGGER_HOOK_CODE)],
            bytes(len(TRIGGER_HOOK_CODE)),
        )

    def test_current_terrain_deployment_and_triggers_share_two_banks(self) -> None:
        linked, packed, patches = link_map_resources(
            self.source,
            self.terrain,
            self.scenarios,
            self.triggers,
            (0x40, 0x41),
        )
        self.assertEqual(packed.used_bytes, 15_716)
        self.assertEqual(packed.used_bank_count, 2)
        self.assertEqual(len(packed.bank_images), 2)
        self.assertTrue(patches)

        payloads = read_expanded_map_payloads(linked)
        self.assertEqual(payloads.terrain, self.terrain)
        self.assertEqual(payloads.scenarios, self.scenarios)
        self.assertEqual(payloads.triggers, self.triggers)

        layout = read_expanded_map_layout(linked)
        self.assertEqual(layout.used_banks, (0x40, 0x41))
        self.assertTrue(
            all(item.pointer >= 0xA000 for item in layout.terrain)
        )
        self.assertTrue(
            all(0x8000 <= item.pointer < 0xA000 for item in layout.scenarios)
        )
        self.assertTrue(
            all(item.pointer >= 0xA000 for item in layout.triggers)
        )
        self.assertEqual(
            (layout.scenarios[0].bank, layout.scenarios[0].pointer),
            (layout.scenarios[1].bank, layout.scenarios[1].pointer),
        )
        self.assertEqual(
            (layout.triggers[0].bank, layout.triggers[0].pointer),
            (layout.triggers[1].bank, layout.triggers[1].pointer),
        )

    def test_link_writes_exact_dispatch_and_directory_bytes(self) -> None:
        linked, packed, _patches = link_map_resources(
            self.source,
            self.terrain,
            self.scenarios,
            self.triggers,
            (0x40, 0x41),
        )
        self.assertEqual(
            linked[
                TERRAIN_DISPATCH_OFFSET : TERRAIN_DISPATCH_OFFSET
                + len(TERRAIN_DISPATCH_PATCH)
            ],
            TERRAIN_DISPATCH_PATCH,
        )
        self.assertEqual(
            linked[
                SCENARIO_RESOLVE_CALL_OFFSET : SCENARIO_RESOLVE_CALL_OFFSET + 3
            ],
            SCENARIO_RESOLVE_CALL_PATCH,
        )
        self.assertEqual(
            linked[SCENARIO_HOOK_OFFSET : SCENARIO_HOOK_OFFSET + len(SCENARIO_HOOK_CODE)],
            SCENARIO_HOOK_CODE,
        )
        self.assertEqual(
            linked[
                TRIGGER_DISPATCH_CALL_OFFSET : TRIGGER_DISPATCH_CALL_OFFSET + 3
            ],
            TRIGGER_DISPATCH_CALL_PATCH,
        )
        self.assertEqual(
            linked[TRIGGER_HOOK_OFFSET : TRIGGER_HOOK_OFFSET + len(TRIGGER_HOOK_CODE)],
            TRIGGER_HOOK_CODE,
        )
        self.assertEqual(
            linked[
                TERRAIN_BANK_DIRECTORY_OFFSET : TERRAIN_BANK_DIRECTORY_OFFSET
                + len(packed.terrain_banks)
            ],
            bytes(packed.terrain_banks),
        )
        self.assertEqual(
            linked[
                SCENARIO_BANK_DIRECTORY_OFFSET : SCENARIO_BANK_DIRECTORY_OFFSET
                + len(packed.scenario_banks)
            ],
            bytes(packed.scenario_banks),
        )
        self.assertEqual(
            linked[
                TRIGGER_BANK_DIRECTORY_OFFSET : TRIGGER_BANK_DIRECTORY_OFFSET
                + len(packed.trigger_banks)
            ],
            bytes(packed.trigger_banks),
        )

    def test_py65_terrain_dispatch_maps_record_and_returns_pointer(self) -> None:
        map_id = 0x2A
        memory = _Mmc3Memory(self.linked, 0x02, 0x03)
        memory[0x0018] = 0x6B
        memory[0x0019] = map_id
        memory[0x7411] = map_id
        memory[0x7532] = 0
        mpu = MPU(memory=memory, pc=0x9B87)
        _prepare_rts(memory, mpu)

        _run_until(mpu, 0x0200)

        pointer = memory[0x0018] | memory[0x0019] << 8
        self.assertEqual(pointer, self.packed.terrain_pointers[map_id])
        self.assertEqual(memory.second_bank, self.packed.terrain_banks[map_id])
        self.assertEqual(memory[0x04DF], self.packed.terrain_banks[map_id])
        self.assertEqual(mpu.a, self.packed.terrain_banks[map_id])
        self.assertEqual(mpu.sp, 0xFF)

    def test_py65_scenario_hook_maps_record_and_returns_to_caller(self) -> None:
        map_id = 0x1A
        memory = _Mmc3Memory(self.linked, 0x24, 0x25)
        memory[0x0018] = 0x6E
        memory[0x0019] = map_id
        memory[0x7411] = map_id
        mpu = MPU(memory=memory, pc=0xA940)
        mpu.a = map_id
        _prepare_rts(memory, mpu)

        _run_until(mpu, 0x0200)

        pointer = memory[0x0018] | memory[0x0019] << 8
        self.assertEqual(pointer, self.packed.scenario_pointers[map_id])
        self.assertEqual(memory.first_bank, self.packed.scenario_banks[map_id])
        self.assertEqual(memory.second_bank, 0x25)
        self.assertEqual(memory[0x04DE], self.packed.scenario_banks[map_id])
        self.assertEqual(mpu.a, map_id)
        self.assertEqual(mpu.sp, 0xFF)

    def test_py65_trigger_hook_maps_record_and_preserves_registers(self) -> None:
        map_id = 0x17
        memory = _Mmc3Memory(self.linked, 0x0A, 0x0B)
        memory[0x7411] = map_id
        mpu = MPU(memory=memory, pc=0x9ED4)
        mpu.a = 0xCC
        mpu.x = 0x35
        mpu.y = 0x79
        _prepare_rts(memory, mpu)

        _run_until(mpu, 0x0200)

        self.assertEqual(memory.first_bank, 0x0A)
        self.assertEqual(memory.second_bank, self.packed.trigger_banks[map_id])
        self.assertEqual(memory[0x04DF], self.packed.trigger_banks[map_id])
        self.assertEqual(mpu.a, map_id)
        self.assertEqual(mpu.x, 0x35)
        self.assertEqual(mpu.y, 0x79)
        self.assertEqual(mpu.sp, 0xFF)

    def test_capacity_failure_is_atomic(self) -> None:
        mutable_source = bytearray(self.source)
        before = bytes(mutable_source)
        with self.assertRaisesRegex(ValueError, "16 KiB"):
            link_map_resources(
                mutable_source,
                self.terrain,
                self.scenarios,
                self.triggers,
                (0x40,),
            )
        self.assertEqual(bytes(mutable_source), before)

    def test_relink_is_deterministic_and_clears_released_bank(self) -> None:
        first, _packed, _patches = link_map_resources(
            self.source,
            self.terrain,
            self.scenarios,
            self.triggers,
            (0x40, 0x41, 0x42),
        )
        second, repacked, _patches = link_map_resources(
            first,
            self.terrain,
            self.scenarios,
            self.triggers,
            (0x40, 0x41),
            clear_banks=(0x40, 0x41, 0x42),
        )
        third, _again, _patches = link_map_resources(
            second,
            self.terrain,
            self.scenarios,
            self.triggers,
            (0x40, 0x41),
        )
        self.assertEqual(second, third)
        released = 16 + 0x42 * 0x2000
        self.assertEqual(second[released : released + 0x2000], bytes(0x2000))
        self.assertEqual(repacked.used_bytes, 15_716)

    def test_scenario_prelude_runtime_limit_is_enforced(self) -> None:
        invalid = list(self.scenarios)
        invalid[0] = bytes(255) + bytes((0xFF, 0xFF, 0xFF, 0xFF))
        with self.assertRaisesRegex(Exception, "254"):
            pack_map_resources(
                self.terrain,
                tuple(invalid),
                self.triggers,
                (0x40, 0x41, 0x42),
            )


if __name__ == "__main__":
    unittest.main()
