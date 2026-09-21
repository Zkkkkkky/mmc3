from __future__ import annotations

import unittest

from tools.report_m08_reference_physical_catalog import DEFAULT_ROM, DEFAULT_UI, build_catalog


class M08ReferencePhysicalCatalogTests(unittest.TestCase):
    def test_reference_saved_layout_matches_all_enumerated_ui_fields(self) -> None:
        report = build_catalog(DEFAULT_ROM, DEFAULT_UI)
        self.assertEqual(report["counts"]["groups"], 5)
        self.assertEqual(report["counts"]["rows"], 644)
        self.assertEqual(report["counts"]["ui_fields"], 1248)
        self.assertEqual(report["counts"]["unique_physical_fields"], 1095)
        self.assertEqual(report["counts"]["duplicate_ui_references"], 153)
        groups = {item["segment"]: item for item in report["groups"]}
        self.assertEqual(groups["00"]["table_pointer"], 0xAFA4)
        self.assertEqual(groups["01"]["table_pointer"], 0xB7D2)
        self.assertEqual(groups["04"]["table_pointer"], 0xA134)
        self.assertEqual(groups["05"]["table_pointer"], 0xAAC6)
        self.assertEqual(groups["07"]["table_pointer"], 0xAE55)
        alias = next(
            item for item in report["aliases"]
            if "M08/05/000/000" in item["field_ids"]
        )
        self.assertIn("M08/07/000/000", alias["field_ids"])


if __name__ == "__main__":
    unittest.main()
