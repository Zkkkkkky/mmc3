from __future__ import annotations

import json
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "output/verification/legacy-m11-all-fields-20260920"


class M11AllGlyphFieldsTests(unittest.TestCase):
    def test_summary_and_all_field_evidence(self) -> None:
        summary = json.loads((OUT / "summary.json").read_text(encoding="utf-8"))
        self.assertTrue(summary["passed"])
        self.assertEqual(summary["physical_fields"], 2688)
        self.assertEqual(summary["covered_fields"], 2688)
        self.assertEqual(summary["safe_page_save_fields"], 672)
        self.assertEqual(summary["unsafe_or_no_effect_fields"], 2016)
        self.assertEqual(summary["page_save_cases"], 12)
        self.assertEqual(summary["isolated_single_glyph_cases"], 12)
        self.assertEqual(summary["two_cold_process_cases_passed"], 24)
        evidence = [json.loads(line) for line in (OUT / "glyph-page-save-evidence.jsonl").read_text(encoding="utf-8").splitlines()]
        self.assertEqual(len(evidence), 2688)
        self.assertEqual([item["sequence"] for item in evidence], list(range(2688)))
        self.assertTrue(all(item["length"] == 18 and item["two_cold_process_cell_match"] for item in evidence))

    def test_each_case_is_confined_and_cold_readable(self) -> None:
        cases = json.loads((OUT / "save-cases.json").read_text(encoding="utf-8"))
        self.assertEqual(len(cases), 24)
        self.assertTrue(all(item["reserved_unchanged"] and item["cold_cell_matches"] for item in cases))
        self.assertTrue(all(item["all_224_fields_blank"] for item in cases if item["kind"] == "clear_page"))
        self.assertTrue(all(item["classification"] == "unsafe_extra_write" for item in cases if item["kind"] == "single_glyph"))


if __name__ == "__main__":
    unittest.main()
