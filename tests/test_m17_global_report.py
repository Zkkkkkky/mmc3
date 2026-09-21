from __future__ import annotations

from pathlib import Path
import unittest

from tools.report_m17_global_compatibility import analyze


ROOT = Path(__file__).resolve().parents[1]
ROM = ROOT / "output" / "rom" / "DC_kuorong_464K.nes"
INDEX = ROOT / "output" / "build" / "legacy-diff-audit" / "golden" / "index.json"


@unittest.skipUnless(ROM.is_file() and INDEX.is_file(), "需要正式 ROM 和黄金档案")
class M17GlobalCompatibilityReportTests(unittest.TestCase):
    def test_report_rechecks_product_diffs_and_reference_archives(self) -> None:
        report = analyze(ROM, INDEX)
        self.assertTrue(report["passed"])
        self.assertEqual(
            report["delivery_status"],
            "aligned_regression_guard_user_checklist_pending",
        )
        self.assertEqual(report["reference_golden"]["case_count"], 33)
        self.assertEqual(report["reference_golden"]["logical_field_count"], 32)
        self.assertEqual(len(report["product_diffs"]["double_hit"]["changed_offsets"]), 9)
        self.assertEqual(report["product_diffs"]["initial_roster"]["sentinel_value"], 0xFF)


if __name__ == "__main__":
    unittest.main()
