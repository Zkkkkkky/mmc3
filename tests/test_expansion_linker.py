from __future__ import annotations

import struct
import unittest
from pathlib import Path

from fc_editor.codecs.map import MapCodec
from fc_editor.expansion import (
    AVAILABLE_EXPANSION_BANKS,
    EXPANSION_METADATA_OFFSET,
    EXPANSION_METADATA_SIZE,
    ExpansionPlan,
    pack_maps,
    pack_pointer_records,
    pack_units,
)
from fc_editor.rom_image import RomImage


ROOT = Path(__file__).resolve().parents[1]
TARGET_ROM = ROOT / "output" / "rom" / "DC_kuorong_464K.nes"


class ExpansionPlanTests(unittest.TestCase):
    def test_recommended_split_uses_all_safe_banks_without_overlap(self) -> None:
        plan = ExpansionPlan.from_kib(304, 48, 112)
        self.assertEqual(plan.total_kib, 464)
        self.assertEqual(plan.unassigned_kib, 0)
        self.assertEqual(len(plan.map_banks), 38)
        self.assertEqual(len(plan.unit_banks), 6)
        self.assertEqual(len(plan.story_pairs), 7)
        assigned = plan.map_banks + plan.unit_banks + plan.story_banks
        self.assertEqual(len(assigned), len(set(assigned)))
        self.assertEqual(set(assigned), set(AVAILABLE_EXPANSION_BANKS))
        self.assertTrue(set(assigned).isdisjoint({0x61, 0x62, 0x63, 0x64, 0x7E, 0x7F}))

    def test_metadata_round_trip_and_checksum(self) -> None:
        plan = ExpansionPlan.from_kib(
            64,
            80,
            32,
            story_group_mask=0b0000101,
            flags=0x07,
        )
        rom = bytearray(EXPANSION_METADATA_OFFSET + EXPANSION_METADATA_SIZE)
        rom[
            EXPANSION_METADATA_OFFSET : EXPANSION_METADATA_OFFSET
            + EXPANSION_METADATA_SIZE
        ] = plan.to_bytes()
        self.assertEqual(ExpansionPlan.from_bytes(rom), plan)
        rom[-1] ^= 0x01
        with self.assertRaisesRegex(ValueError, "校验"):
            ExpansionPlan.from_bytes(rom)

    def test_story_groups_keep_stable_pair_assignments(self) -> None:
        plan = ExpansionPlan.from_kib(16, 48, 32)
        plan = plan.with_story_selector(0x3B)
        first_pair = plan.story_pair_for(0x3B)
        plan = plan.with_story_selector(0x32)
        self.assertEqual(plan.story_pair_for(0x3B), first_pair)
        self.assertNotEqual(plan.story_pair_for(0x32), first_pair)

    def test_story_quota_is_pair_aligned_and_limited(self) -> None:
        with self.assertRaisesRegex(ValueError, "16 KiB"):
            ExpansionPlan.from_kib(8, 8, 8)
        with self.assertRaisesRegex(ValueError, "112 KiB"):
            ExpansionPlan.from_kib(8, 48, 128)
        with self.assertRaisesRegex(ValueError, "48、64 或 80"):
            ExpansionPlan.from_kib(16, 56, 16)


class ExpansionPackingTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.rom = RomImage.load(TARGET_ROM)

    def test_current_maps_pack_into_two_banks(self) -> None:
        codec = MapCodec(self.rom)
        records = [codec.decode(map_id).raw for map_id in range(self.rom.profile.map_count)]
        packed = pack_maps(records, (0x40, 0x41))
        self.assertEqual(len(packed.bank_images), 2)
        self.assertEqual(packed.used_bytes, sum(map(len, records)))
        for pointer, bank in zip(packed.pointers, packed.banks):
            self.assertIn(bank, (0x40, 0x41))
            self.assertTrue(0xA000 <= pointer <= 0xBFFF)

    def test_worst_case_maps_need_fifteen_banks(self) -> None:
        records = [bytes((32, 32)) + bytes(1024) for _ in range(100)]
        with self.assertRaisesRegex(ValueError, "120 KiB"):
            pack_maps(records, tuple(range(0x40, 0x4E)))
        packed = pack_maps(records, tuple(range(0x40, 0x4F)))
        self.assertEqual(len(packed.bank_images), 15)

    def test_unit_image_has_independent_pointer_for_every_id(self) -> None:
        records = [bytes((unit_id,)) * 16 for unit_id in range(1, 0x100)]
        image = pack_units(records, 0x40)
        self.assertEqual(len(image), 0x2000)
        self.assertEqual(int.from_bytes(image[:2], "little"), 0x8010)
        pointers = struct.unpack("<256H", image[0x10:0x210])
        self.assertEqual(pointers[0], 0)
        self.assertEqual(pointers[1], 0x8210)
        self.assertEqual(pointers[-1], 0x91F0)
        self.assertEqual(len(set(pointers[1:])), 0xFF)

    def test_story_group_builder_preserves_aliases_by_payload(self) -> None:
        image, pointers = pack_pointer_records(
            (b"A\xff", b"B\xff", b"A\xff"),
            pointer_count=3,
            pair=True,
        )
        self.assertEqual(len(image), 0x4000)
        self.assertEqual(pointers[0], pointers[2])
        self.assertNotEqual(pointers[0], pointers[1])


if __name__ == "__main__":
    unittest.main()
