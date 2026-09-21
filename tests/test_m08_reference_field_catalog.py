from __future__ import annotations

import unittest

from tools.report_m08_reference_field_catalog import build_catalog


class M08ReferenceFieldCatalogTests(unittest.TestCase):
    def test_repository_evidence_catalog_is_complete_and_unique(self) -> None:
        report = build_catalog()
        self.assertTrue(report["rom_unchanged"])
        self.assertEqual(report["counts"]["segments"], 5)
        self.assertEqual(report["counts"]["rows"], 644)
        self.assertEqual(report["counts"]["ui_fields"], 1248)
        self.assertEqual(
            [(item["segment"], item["rows"], item["variants"]) for item in report["groups"]],
            [("00", 256, 604), ("01", 16, 18), ("04", 256, 509), ("05", 64, 64), ("07", 52, 53)],
        )
        ids = [item["field_id"] for item in report["fields"]]
        self.assertEqual(len(ids), len(set(ids)))
        alias = report["verified_physical_aliases"][0]
        self.assertEqual(alias["source_field_id"], "M08/07/000/000")
        self.assertEqual(alias["reopen_field_id"], "M08/05/000/000")


if __name__ == "__main__":
    unittest.main()
