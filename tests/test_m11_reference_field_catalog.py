from __future__ import annotations

import json
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


class M11ReferenceFieldCatalogTests(unittest.TestCase):
    def test_probe_confirms_controls_pages_and_alias_columns(self) -> None:
        source = json.loads((ROOT / "output/verification/legacy-m11-reference-catalog-20260920/catalog.json").read_text(encoding="utf-8"))
        self.assertTrue(source["passed"])
        self.assertTrue(source["rom_unchanged"])
        self.assertEqual(source["pages"], ["B8", "B9", "BA", "BB", "C8", "C9", "CA", "CB", "D8", "D9", "DA", "DB"])
        self.assertTrue(source["controls"]["140"]["edit_read_only"])
        self.assertFalse(source["controls"]["300"]["edit_read_only"])
        samples = {(item["row"], item["column"]): item for item in source["grid_samples"]}
        self.assertEqual(samples[(0, 14)]["values"]["160"], samples[(0, 0)]["values"]["160"])
        self.assertEqual(samples[(0, 15)]["values"]["160"], samples[(0, 0)]["values"]["160"])

    def test_catalog_has_all_physical_glyphs_and_no_reserved_bytes(self) -> None:
        report = json.loads((ROOT / "output/reports/m11-reference-field-catalog.json").read_text(encoding="utf-8"))
        self.assertEqual(report["counts"]["physical_fields"], 2688)
        offsets = [field["offset"] for field in report["fields"]]
        self.assertEqual(len(offsets), len(set(offsets)))
        self.assertTrue(all(field["column"] < 14 and field["length"] == 18 for field in report["fields"]))


if __name__ == "__main__":
    unittest.main()
