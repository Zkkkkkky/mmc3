from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from tools.report_legacy_memory_distribution import (
    EvidenceCase,
    bank_descriptor,
    build_report,
    group_offsets,
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


if __name__ == "__main__":
    unittest.main()
