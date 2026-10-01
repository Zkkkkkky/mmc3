from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from tools.report_legacy_memory_distribution import (
    DEFAULT_CASES_ROOT,
    DEFAULT_GOLDEN_ROOT,
    DEFAULT_SCOPE_MATRIX,
    EvidenceCase,
    bank_descriptor,
    build_report,
    group_offsets,
    load_cases,
    load_scope_matrix,
    render_markdown,
)


class LegacyMemoryDistributionTests(unittest.TestCase):
    def test_groups_nearby_offsets_without_claiming_full_contiguity(self) -> None:
        self.assertEqual(
            group_offsets((0x10, 0x12, 0x30, 0x31), maximum_gap=2),
            ((0x10, 0x12), (0x30, 0x31)),
        )

    def test_describes_ines_file_bank(self) -> None:
        self.assertEqual(bank_descriptor(0x10)["bank"], 0)
        self.assertEqual(bank_descriptor(0x2010)["bank"], 1)
        self.assertEqual(bank_descriptor(0x200F)["bank_offset"], 0x1FFF)

    def test_report_keeps_observed_and_missing_modules_separate(self) -> None:
        cases = (
            EvidenceCase(Path("case-a.json"), "M05", "name", "a", True, (0x100, 0x102)),
            EvidenceCase(Path("case-b.json"), "M05", "name", "b", False, (0x103,)),
            EvidenceCase(Path("case-c.json"), "M07", "script", "c", True, (0x4000,)),
        )
        report = build_report(cases, maximum_gap=2)
        self.assertEqual(report["scanned_case_count"], 3)
        self.assertEqual(report["case_count"], 2)
        self.assertEqual(report["modules_with_evidence"], ["M05", "M07"])
        self.assertIn("M06", report["modules_without_archived_save_pairs"])
        name = report["modules"]["M05"]["fields"]["name"]
        self.assertEqual(name["observed_changed_bytes"], 2)
        self.assertEqual(name["write_zones"][0]["start"], 0x100)
        self.assertEqual(name["write_zones"][0]["end_inclusive"], 0x102)
        self.assertIn("尚无归档保存对", render_markdown(report))

    def test_reviewed_index_is_used_without_reparsing_large_live_diffs(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            golden = root / "golden"
            golden.mkdir()
            (golden / "index.json").write_text(
                """{
                  "fields": {
                    "M06/name/cold": {
                      "module": "M06", "field": "name", "case_id": "cold",
                      "archive": "M06-name-cold.json", "passed": true,
                      "required_offsets": [256], "optional_offsets": [258],
                      "changed_count": 12
                    }
                  }
                }""",
                encoding="utf-8",
            )
            cases = load_cases(root / "missing-live-cases", golden)
            self.assertEqual(len(cases), 1)
            self.assertEqual(cases[0].offsets, (256, 258))
            report = build_report(cases, maximum_gap=2)
            field = report["modules"]["M06"]["fields"]["name"]
            self.assertEqual(field["direct_target_bytes"], 1)
            self.assertEqual(field["shared_repack_bytes"], 1)
            self.assertEqual(field["collateral_rewrite_events"], 10)

    def test_repository_report_covers_current_golden_and_specialized_modules(self) -> None:
        report = build_report(
            load_cases(DEFAULT_CASES_ROOT, DEFAULT_GOLDEN_ROOT),
            scope_matrix=load_scope_matrix(DEFAULT_SCOPE_MATRIX),
        )
        self.assertEqual(report["scanned_case_count"], 246)
        self.assertEqual(report["case_count"], 239)
        self.assertEqual(len(report["modules"]), 19)
        self.assertEqual(
            report["modules"]["M03"]["specialized_direct_target_bytes"],
            1380,
        )
        self.assertEqual(
            report["modules"]["M04"]["specialized_direct_target_bytes"],
            103,
        )
        self.assertEqual(
            report["modules"]["M11"]["specialized_direct_target_bytes"],
            672 * 18,
        )


if __name__ == "__main__":
    unittest.main()
