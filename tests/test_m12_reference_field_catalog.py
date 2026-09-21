from __future__ import annotations

from pathlib import Path
import unittest

from tools.report_m12_reference_field_catalog import build


ROOT = Path(__file__).resolve().parents[1]
CATALOG = ROOT / "output/verification/legacy-m12-reference-catalog-20260920/catalog.json"
POINTERS = ROOT / "output/verification/legacy-m12-reference-catalog-20260920/pointer-fields.json"


@unittest.skipUnless(CATALOG.is_file() and POINTERS.is_file(), "需要 M12 参考版只读目录")
class M12ReferenceFieldCatalogTests(unittest.TestCase):
    def test_all_exposed_rows_and_fields_are_registered(self) -> None:
        report = build(CATALOG, POINTERS)
        self.assertTrue(report["passed"])
        self.assertEqual(report["field_count"], 1281)
        self.assertEqual(
            report["reference_row_counts"],
            {"map": 152, "movement": 114, "sprite": 198, "background": 32, "spirit": 24, "map_weapon": 13},
        )
        self.assertEqual(report["family_counts"]["map_pointer_action_input"], 1)
        self.assertEqual(report["family_counts"]["sprite_code"], 198)
        self.assertEqual(report["persistence_candidate_counts"]["external_metadata"], 496)
        self.assertEqual(report["persistence_candidate_counts"]["rom"], 387)
        self.assertEqual(report["persistence_candidate_counts"]["unsafe_action_input"], 1)
        self.assertNotIn("blank_slot", report["persistence_candidate_counts"])
        self.assertEqual(report["family_counts"]["map_weapon_animation_2"], 2)
        self.assertEqual(report["family_counts"]["map_weapon_animation_3"], 2)
        self.assertEqual(report["family_counts"]["map_weapon_animation_4"], 2)
        self.assertEqual(report["persistence_candidate_counts"]["ui_only"], 1)
        self.assertEqual(report["family_counts"]["sprite_preview_selector"], 1)
        self.assertEqual(report["persistence_candidate_counts"]["reference_no_effect_candidate"], 396)


if __name__ == "__main__":
    unittest.main()
