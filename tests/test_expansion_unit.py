from __future__ import annotations

import struct
import unittest
from dataclasses import replace
from pathlib import Path

from py65.devices.mpu6502 import MPU

from fc_editor.expansion_unit import (
    ATTRIBUTE_TABLE,
    CONFIGURATION_TABLE,
    PACKED_BODY_TABLE,
    PACKED_FRAGMENT_TABLE,
    RESOURCE_DESCRIPTOR_TABLE_OFFSET,
    SINGLE_RESOURCE_DATA_START,
    SINGLE_RESOURCE_TABLE,
    UNIT_ATTRIBUTE_SELECTOR,
    UNIT_BODY_SELECTOR,
    UNIT_CONFIGURATION_SELECTOR,
    UNIT_FRAGMENT_SELECTOR,
    UNIT_NAME_SELECTOR,
    UnitExpansionRecords,
    extract_unit_expansion_records,
    pack_unit_expansion,
    validate_unit_expansion_payload,
)


ROOT = Path(__file__).resolve().parents[1]
TARGET_ROM = ROOT / "output" / "rom" / "DC_kuorong_464K.nes"
TARGET_PAIRS = ((0x50, 0x51), (0x52, 0x53), (0x54, 0x55))
TARGET_PAIRS_64 = TARGET_PAIRS + ((0x56, 0x57),)
TARGET_PAIRS_80 = TARGET_PAIRS_64 + ((0x58, 0x59),)


class _Mmc3Memory:
    """Minimal Mapper 194 PRG view needed by the stock resource resolver."""

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


class UnitExpansionPackingTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.rom = TARGET_ROM.read_bytes()
        cls.source = extract_unit_expansion_records(cls.rom)
        cls.packed = pack_unit_expansion(cls.rom, TARGET_PAIRS, records=cls.source)

    def test_all_255_ids_round_trip_every_relocated_resource(self) -> None:
        expected_by_selector = {
            UNIT_ATTRIBUTE_SELECTOR: self.source.attributes,
            UNIT_NAME_SELECTOR: self.source.names,
            UNIT_CONFIGURATION_SELECTOR: self.source.configurations,
            UNIT_BODY_SELECTOR: self.source.body_scripts,
            UNIT_FRAGMENT_SELECTOR: self.source.fragment_scripts,
        }
        for selector, records in expected_by_selector.items():
            layout = self.packed.resource(selector)
            self.assertEqual(layout.pointers[0], 0)
            self.assertEqual(len(set(layout.pointers[1:])), 0xFF)
            for record_id, expected in enumerate(records, 1):
                with self.subTest(selector=selector, record_id=record_id):
                    self.assertEqual(
                        self.packed.record_bytes(selector, record_id),
                        expected,
                    )

    def test_all_255_ids_round_trip_at_64_and_80_kib(self) -> None:
        expected_by_selector = {
            UNIT_ATTRIBUTE_SELECTOR: self.source.attributes,
            UNIT_NAME_SELECTOR: self.source.names,
            UNIT_CONFIGURATION_SELECTOR: self.source.configurations,
            UNIT_BODY_SELECTOR: self.source.body_scripts,
            UNIT_FRAGMENT_SELECTOR: self.source.fragment_scripts,
        }
        for pairs in (TARGET_PAIRS_64, TARGET_PAIRS_80):
            packed = pack_unit_expansion(self.rom, pairs, records=self.source)
            for selector, records in expected_by_selector.items():
                for record_id, expected in enumerate(records, 1):
                    with self.subTest(
                        kib=len(pairs) * 16,
                        selector=selector,
                        record_id=record_id,
                    ):
                        self.assertEqual(
                            packed.record_bytes(selector, record_id),
                            expected,
                        )

    def test_payload_validator_decodes_all_resources_at_48_64_and_80_kib(self) -> None:
        for pairs in (TARGET_PAIRS, TARGET_PAIRS_64, TARGET_PAIRS_80):
            packed = pack_unit_expansion(self.rom, pairs, records=self.source)
            decoded = validate_unit_expansion_payload(
                packed.apply(self.rom),
                pairs,
            )
            with self.subTest(kib=len(pairs) * 16):
                self.assertEqual(decoded, self.source)

    def test_payload_validator_rejects_every_active_directory(self) -> None:
        for pairs in (TARGET_PAIRS, TARGET_PAIRS_64, TARGET_PAIRS_80):
            packed = pack_unit_expansion(self.rom, pairs, records=self.source)
            applied = packed.apply(self.rom)
            for layout in packed.resources:
                damaged = bytearray(applied)
                offset = (
                    16
                    + layout.pair_start * 0x2000
                    + layout.directory_index * 2
                )
                damaged[offset : offset + 2] = b"\x00\x00"
                with self.subTest(
                    kib=len(pairs) * 16,
                    selector=layout.selector,
                ):
                    with self.assertRaisesRegex(ValueError, "目录"):
                        validate_unit_expansion_payload(damaged, pairs)

    def test_payload_validator_rejects_every_resource_pointer_table(self) -> None:
        for pairs in (TARGET_PAIRS, TARGET_PAIRS_64, TARGET_PAIRS_80):
            packed = pack_unit_expansion(self.rom, pairs, records=self.source)
            applied = packed.apply(self.rom)
            for layout in packed.resources:
                damaged = bytearray(applied)
                offset = (
                    16
                    + layout.pair_start * 0x2000
                    + layout.pointer_table
                    - 0x8000
                    + 2
                )
                damaged[offset : offset + 2] = b"\x00\x00"
                with self.subTest(
                    kib=len(pairs) * 16,
                    selector=layout.selector,
                ):
                    with self.assertRaises(ValueError):
                        validate_unit_expansion_payload(damaged, pairs)

    def test_payload_validator_rejects_missing_record_terminators(self) -> None:
        terminated_selectors = (
            UNIT_NAME_SELECTOR,
            UNIT_BODY_SELECTOR,
            UNIT_FRAGMENT_SELECTOR,
        )
        for pairs in (TARGET_PAIRS, TARGET_PAIRS_64, TARGET_PAIRS_80):
            packed = pack_unit_expansion(self.rom, pairs, records=self.source)
            applied = packed.apply(self.rom)
            for selector in terminated_selectors:
                layout = packed.resource(selector)
                record = packed.record_bytes(selector, 1)
                self.assertEqual(record[-1], 0xFF)
                damaged = bytearray(applied)
                terminator_offset = (
                    16
                    + layout.pair_start * 0x2000
                    + layout.pointers[1]
                    - 0x8000
                    + len(record)
                    - 1
                )
                damaged[terminator_offset] = 0
                with self.subTest(kib=len(pairs) * 16, selector=selector):
                    with self.assertRaisesRegex(ValueError, r"\$FF"):
                        validate_unit_expansion_payload(damaged, pairs)

    def test_mirror_pairs_keep_every_verified_loader_call_site(self) -> None:
        core = self.packed.pair(0x50).image
        configuration = self.packed.pair(0x52).image
        source_core = self.rom[0x48010 : 0x4C010]
        source_configuration = self.rom[0x08010 : 0x0C010]

        # Selector $71 returns into Bank $24 at these two addresses.  The target
        # mirror must therefore retain the exact executable bytes there.
        for address in (0x806D, 0x829B):
            start = address - 0x8000
            self.assertEqual(core[start : start + 3], b"\x20\x0B\xC1")
            self.assertEqual(core[start - 8 : start + 24], source_core[start - 8 : start + 24])

        # Selector $74 has eleven equivalent direct calls in Bank $04.
        for address in (
            0x843C,
            0x86B7,
            0x8816,
            0x8DD4,
            0x8DEE,
            0x8E52,
            0x8EA3,
            0x94A3,
            0x9508,
            0x9556,
            0x95B2,
        ):
            start = address - 0x8000
            self.assertEqual(configuration[start : start + 3], b"\x20\x0B\xC1")
            self.assertEqual(
                configuration[start - 8 : start + 24],
                source_configuration[start - 8 : start + 24],
            )

    def test_directories_tables_capacities_and_known_payload_sizes(self) -> None:
        self.assertEqual(len(self.packed.pair_images), 3)
        self.assertTrue(all(len(pair.image) == 0x4000 for pair in self.packed.pair_images))

        core = self.packed.pair(0x50).image
        configuration = self.packed.pair(0x52).image
        composition = self.packed.pair(0x54).image
        self.assertEqual(struct.unpack_from("<H", core, 4)[0], ATTRIBUTE_TABLE)
        self.assertEqual(struct.unpack_from("<H", core, 12)[0], 0x98F8)
        self.assertEqual(struct.unpack_from("<H", configuration, 12)[0], CONFIGURATION_TABLE)
        self.assertEqual(struct.unpack_from("<H", composition, 0)[0], PACKED_BODY_TABLE)
        self.assertEqual(struct.unpack_from("<H", composition, 2)[0], PACKED_FRAGMENT_TABLE)

        self.assertEqual(sum(map(len, self.source.attributes)), 4080)
        self.assertEqual(sum(map(len, self.source.names)), 1456)
        self.assertEqual(sum(map(len, self.source.configurations)), 2550)
        self.assertEqual(sum(map(len, self.source.body_scripts)), 6838)
        self.assertEqual(sum(map(len, self.source.fragment_scripts)), 5852)
        self.assertEqual(self.packed.composition_capacity, 0x3BF0)
        self.assertEqual(self.packed.composition_used, 12690)
        self.assertEqual(self.packed.composition_available, 2654)
        self.assertGreaterEqual(self.packed.resource(UNIT_NAME_SELECTOR).pool_capacity, 3644)
        self.assertGreaterEqual(
            self.packed.resource(UNIT_CONFIGURATION_SELECTOR).pool_capacity,
            3369,
        )

    def test_64_kib_binds_body_and_fragment_to_independent_pairs(self) -> None:
        packed = pack_unit_expansion(
            self.rom,
            TARGET_PAIRS_64,
            records=self.source,
        )
        body = packed.resource(UNIT_BODY_SELECTOR)
        fragment = packed.resource(UNIT_FRAGMENT_SELECTOR)
        self.assertEqual(len(packed.pair_images), 4)
        self.assertEqual((body.pair_start, fragment.pair_start), (0x54, 0x56))
        self.assertEqual(body.directory_index, 0)
        self.assertEqual(fragment.directory_index, 1)
        self.assertEqual(body.pointer_table, SINGLE_RESOURCE_TABLE)
        self.assertEqual(fragment.pointer_table, SINGLE_RESOURCE_TABLE)
        self.assertEqual(body.pool_capacity, 0xC000 - SINGLE_RESOURCE_DATA_START)
        self.assertEqual(fragment.pool_capacity, body.pool_capacity)
        self.assertEqual(packed.composition_capacity, 31_712)
        self.assertEqual(packed.composition_available, 19_022)

        descriptors = {
            patch.selector: patch.after for patch in packed.descriptor_patches
        }
        self.assertEqual(descriptors[UNIT_BODY_SELECTOR], b"\xF0\x54")
        self.assertEqual(descriptors[UNIT_FRAGMENT_SELECTOR], b"\xF1\x56")

    def test_80_kib_binds_names_to_a_real_runtime_pool(self) -> None:
        packed = pack_unit_expansion(
            self.rom,
            TARGET_PAIRS_80,
            records=self.source,
        )
        names = packed.resource(UNIT_NAME_SELECTOR)
        self.assertEqual(len(packed.pair_images), 5)
        self.assertEqual(names.pair_start, 0x58)
        self.assertEqual(names.directory_index, 6)
        self.assertEqual(names.pointer_table, SINGLE_RESOURCE_TABLE)
        self.assertEqual(names.pool_capacity, 0xC000 - SINGLE_RESOURCE_DATA_START)
        self.assertEqual(names.used_bytes, 1456)
        descriptor = next(
            patch
            for patch in packed.descriptor_patches
            if patch.selector == UNIT_NAME_SELECTOR
        )
        self.assertEqual(descriptor.after, b"\xF6\x58")

        # Moving names must not erase the dormant stock name table/data inside
        # the mandatory core-code mirror.
        source_core = self.rom[0x48010 : 0x4C010]
        core = packed.pair(0x50).image
        self.assertEqual(core[0x18F8:0x1DAE], source_core[0x18F8:0x1DAE])

    def test_descriptor_patches_target_only_active_fixed_bank_copy(self) -> None:
        patches = {patch.selector: patch for patch in self.packed.descriptor_patches}
        expected = {
            UNIT_NAME_SELECTOR: (b"\xF6\x24", b"\xF6\x50"),
            UNIT_BODY_SELECTOR: (b"\xF0\x28", b"\xF0\x54"),
            UNIT_FRAGMENT_SELECTOR: (b"\xF1\x28", b"\xF1\x54"),
            UNIT_ATTRIBUTE_SELECTOR: (b"\xF2\x24", b"\xF2\x50"),
            UNIT_CONFIGURATION_SELECTOR: (b"\x26\x40", b"\xF6\x52"),
        }
        for selector, (before, after) in expected.items():
            patch = patches[selector]
            self.assertEqual(patch.offset, RESOURCE_DESCRIPTOR_TABLE_OFFSET + selector * 2)
            self.assertEqual(patch.before, before)
            self.assertEqual(patch.after, after)
            self.assertGreaterEqual(patch.offset, 0xFE010)

        applied = self.packed.apply(self.rom)
        for patch in patches.values():
            self.assertEqual(applied[patch.offset : patch.offset + 2], patch.after)
        for pair in self.packed.pair_images:
            self.assertEqual(
                applied[pair.file_offset : pair.file_offset + 0x4000],
                pair.image,
            )

    def test_py65_attribute_loader_returns_into_core_mirror(self) -> None:
        applied = self.packed.apply(self.rom)
        memory = _Mmc3Memory(applied, 0x24, 0x25)
        unit_id = 0xA7
        memory[0x04E1] = unit_id
        mpu = MPU(memory=memory, pc=0x8064)

        _run_until(mpu, 0x807C)

        self.assertEqual((memory.first_bank, memory.second_bank), (0x50, 0x51))
        self.assertEqual(
            bytes(memory[0x04EE : 0x04FE]),
            self.source.attributes[unit_id - 1],
        )

    def test_py65_configuration_loader_returns_into_configuration_mirror(self) -> None:
        applied = self.packed.apply(self.rom)
        memory = _Mmc3Memory(applied, 0x04, 0x05)
        unit_id = 0xD2
        memory[0x04E1] = unit_id
        mpu = MPU(memory=memory, pc=0x95A9)

        _run_until(mpu, 0x95C1)

        self.assertEqual((memory.first_bank, memory.second_bank), (0x52, 0x53))
        self.assertEqual(
            bytes(memory[0x04F0 : 0x04F9]),
            self.source.configurations[unit_id - 1][1:10],
        )

    def test_py65_fixed_resolver_reads_both_composition_directories(self) -> None:
        applied = self.packed.apply(self.rom)
        for selector, expected_records in (
            (UNIT_BODY_SELECTOR, self.source.body_scripts),
            (UNIT_FRAGMENT_SELECTOR, self.source.fragment_scripts),
        ):
            unit_id = 0xFF
            memory = _Mmc3Memory(applied, 0x04, 0x05)
            memory[0x0018] = selector
            memory[0x0019] = unit_id
            # Emulate an outstanding JSR whose RTS target is $0200.
            memory[0x01FE] = 0xFF
            memory[0x01FF] = 0x01
            mpu = MPU(memory=memory, pc=0xFD4F)
            mpu.sp = 0xFD

            _run_until(mpu, 0x0200)

            pointer = memory[0x0018] | memory[0x0019] << 8
            expected = expected_records[unit_id - 1]
            self.assertEqual((memory.first_bank, memory.second_bank), (0x54, 0x55))
            self.assertEqual(
                bytes(memory[pointer : pointer + len(expected)]),
                expected,
            )

    def test_py65_resolver_reaches_split_composition_and_name_pairs(self) -> None:
        for pairs, expectations in (
            (
                TARGET_PAIRS_64,
                (
                    (UNIT_BODY_SELECTOR, 0x54, self.source.body_scripts),
                    (UNIT_FRAGMENT_SELECTOR, 0x56, self.source.fragment_scripts),
                ),
            ),
            (
                TARGET_PAIRS_80,
                (
                    (UNIT_NAME_SELECTOR, 0x58, self.source.names),
                ),
            ),
        ):
            packed = pack_unit_expansion(self.rom, pairs, records=self.source)
            applied = packed.apply(self.rom)
            for selector, expected_bank, expected_records in expectations:
                record_id = 0xA7
                memory = _Mmc3Memory(applied, 0x04, 0x05)
                memory[0x0018] = selector
                memory[0x0019] = record_id
                memory[0x01FE] = 0xFF
                memory[0x01FF] = 0x01
                mpu = MPU(memory=memory, pc=0xFD4F)
                mpu.sp = 0xFD

                _run_until(mpu, 0x0200)

                pointer = memory[0x0018] | memory[0x0019] << 8
                expected = expected_records[record_id - 1]
                self.assertEqual(memory.first_bank, expected_bank)
                self.assertEqual(memory.second_bank, expected_bank + 1)
                self.assertEqual(
                    bytes(memory[pointer : pointer + len(expected)]),
                    expected,
                )

    def test_py65_name_renderer_restores_mapping_after_external_name_pair(self) -> None:
        packed = pack_unit_expansion(
            self.rom,
            TARGET_PAIRS_80,
            records=self.source,
        )
        memory = _Mmc3Memory(packed.apply(self.rom), 0x04, 0x05)
        memory[0x0018] = UNIT_NAME_SELECTOR
        memory[0x0019] = 0xA7
        memory[0x04DE] = 0x04
        memory[0x04DF] = 0x05
        memory[0x01FE] = 0xFF
        memory[0x01FF] = 0x01
        mpu = MPU(memory=memory, pc=0xFC13)
        mpu.sp = 0xFD
        mpu.a = 0

        _run_until(mpu, 0x0200)

        self.assertEqual((memory.first_bank, memory.second_bank), (0x04, 0x05))
        self.assertEqual(memory[0x06EF], 0)

    def test_rejects_discontinuous_reserved_and_overlapping_pairs(self) -> None:
        with self.assertRaisesRegex(ValueError, "不连续"):
            pack_unit_expansion(
                self.rom,
                ((0x60, 0x65), (0x50, 0x51), (0x52, 0x53)),
                records=self.source,
            )
        with self.assertRaisesRegex(ValueError, "可用资源区"):
            pack_unit_expansion(
                self.rom,
                ((0x60, 0x61), (0x50, 0x51), (0x52, 0x53)),
                records=self.source,
            )
        with self.assertRaisesRegex(ValueError, "重叠"):
            pack_unit_expansion(
                self.rom,
                ((0x50, 0x51), (0x51, 0x52), (0x54, 0x55)),
                records=self.source,
            )
        for invalid_pairs in (
            TARGET_PAIRS[:2],
            TARGET_PAIRS_80 + ((0x5A, 0x5B),),
        ):
            with self.assertRaisesRegex(ValueError, "48/64/80 KiB"):
                pack_unit_expansion(
                    self.rom,
                    invalid_pairs,
                    records=self.source,
                )

    def test_capacity_failure_is_atomic_and_descriptive(self) -> None:
        oversized_names = tuple(b"A" * 15 + b"\xFF" for _ in range(0xFF))
        oversized = replace(self.source, names=oversized_names)
        self.assertIsInstance(oversized, UnitExpansionRecords)
        with self.assertRaisesRegex(ValueError, "机体名称池容量不足"):
            pack_unit_expansion(self.rom, TARGET_PAIRS, records=oversized)

        packed = pack_unit_expansion(
            self.rom,
            TARGET_PAIRS_80,
            records=oversized,
        )
        for record_id, expected in enumerate(oversized_names, 1):
            self.assertEqual(
                packed.record_bytes(UNIT_NAME_SELECTOR, record_id),
                expected,
            )

    def test_64_kib_capacity_accepts_payload_rejected_by_48_kib(self) -> None:
        enlarged_body = list(self.source.body_scripts)
        enlarged_body[0] = b"\x01" * 3000 + enlarged_body[0]
        enlarged = replace(self.source, body_scripts=tuple(enlarged_body))
        with self.assertRaisesRegex(ValueError, "碎片拼图池容量不足"):
            pack_unit_expansion(self.rom, TARGET_PAIRS, records=enlarged)

        packed = pack_unit_expansion(
            self.rom,
            TARGET_PAIRS_64,
            records=enlarged,
        )
        self.assertEqual(
            packed.record_bytes(UNIT_BODY_SELECTOR, 1),
            enlarged_body[0],
        )


if __name__ == "__main__":
    unittest.main()
