from __future__ import annotations

from pathlib import Path
import unittest

from tools.report_m13_text_conversion_compatibility import analyze


ROOT = Path(__file__).resolve().parents[1]
ROM = ROOT / "output" / "rom" / "DC_kuorong_464K.nes"


@unittest.skipUnless(ROM.is_file(), "需要正式构建 ROM")
class M13TextConversionReportTests(unittest.TestCase):
    def test_report_covers_reference_table_ui_and_read_only_boundary(self) -> None:
        report = analyze(ROM)
        self.assertTrue(report["passed"])
        self.assertEqual(report["reference_table"]["line_count"], 3328)
        self.assertEqual(report["reference_table"]["nonempty_mapping_count"], 2713)
        self.assertEqual(report["reference_table"]["unique_value_count"], 2297)
        self.assertEqual(report["reference_table"]["duplicate_alias_count"], 416)
        self.assertEqual(report["reference_ui"]["control_ids"], [100, 110, 120, 130, 140, 150])
        self.assertEqual(report["product"]["visible_direct_child_count"], 6)
        self.assertTrue(report["checks"]["conversion_does_not_modify_rom"])


if __name__ == "__main__":
    unittest.main()
