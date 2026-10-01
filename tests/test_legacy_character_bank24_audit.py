from __future__ import annotations

import unittest
from pathlib import Path

from tools.audit_legacy_character_bank24 import audit, pack_bank24, parse_bank24
from tools.audit_legacy_character_portrait_pool import (
    audit as audit_portrait_tail,
    pack_portrait_tail,
    parse_portrait_tail,
)


ROOT = Path(__file__).resolve().parents[1]
BASELINE_ROM = ROOT / "references" / "rom" / "baselines" / "DC_kuorong.nes"


class LegacyCharacterBank24AuditTests(unittest.TestCase):
    def test_current_immutable_baseline_rebuilds_exactly(self) -> None:
        report = audit(BASELINE_ROM)

        self.assertTrue(report["exact_rebuild"])
        self.assertEqual(report["mismatch_count"], 0)
        self.assertEqual(
            report["roots"],
            [
                "$83F0",
                "$875F",
                "$8EBF",
                "$9449",
                "$9766",
                "$98F8",
                "$9DAD",
                "$A415",
            ],
        )
        self.assertEqual(report["used_end"], "$A929")
        self.assertEqual(report["capacity"], 15_184)
        self.assertEqual(report["used"], 9_529)
        self.assertEqual(report["remaining"], 5_655)

    def test_all_eight_logical_resources_have_expected_id_counts(self) -> None:
        logical = parse_bank24(BASELINE_ROM.read_bytes())

        self.assertEqual(
            tuple(
                len(items)
                for items in (
                    logical.character_attributes,
                    logical.unit_attributes,
                    logical.weapon_attributes,
                    logical.normal_names,
                    logical.battle_names,
                    logical.unit_names,
                    logical.weapon_names,
                    logical.scenarios,
                )
            ),
            (200, 255, 255, 200, 200, 255, 256, 32),
        )
        _packed, roots, used_end = pack_bank24(logical)
        self.assertEqual(roots[-1], 0xA415)
        self.assertEqual(used_end, 0xA929)


class LegacyCharacterPortraitTailAuditTests(unittest.TestCase):
    def test_current_immutable_baseline_rebuilds_portrait_tail_exactly(self) -> None:
        report = audit_portrait_tail(BASELINE_ROM)

        self.assertTrue(report["exact_rebuild"])
        self.assertEqual(report["mismatch_count"], 0)
        self.assertEqual(report["portrait_root"], "$AA36")
        self.assertEqual(report["configuration_root"], "$ADB9")
        self.assertEqual(report["used_end"], "$B2C8")
        self.assertEqual((report["used"], report["capacity"], report["remaining"]),
                         (2_194, 2_992, 798))
        self.assertEqual(report["unique_portraits"], 71)
        self.assertEqual(report["unique_configurations"], 85)
        self.assertEqual(report["configuration_record_lengths"], {"9": 67, "10": 18})

    def test_portrait_and_configuration_roots_are_repacked_together(self) -> None:
        portrait_root, logical = parse_portrait_tail(BASELINE_ROM.read_bytes())

        _packed, configuration_root, used_end = pack_portrait_tail(
            portrait_root, logical
        )
        self.assertEqual(portrait_root, 0xAA36)
        self.assertEqual(configuration_root, 0xADB9)
        self.assertEqual(used_end, 0xB2C8)


if __name__ == "__main__":
    unittest.main()
