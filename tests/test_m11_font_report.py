from __future__ import annotations

from pathlib import Path
import unittest

from tools.report_m11_font_compatibility import analyze


ROOT = Path(__file__).resolve().parents[1]
ROM = ROOT / "output" / "rom" / "DC_kuorong_464K.nes"


@unittest.skipUnless(ROM.is_file(), "需要正式构建 ROM")
class M11FontReportTests(unittest.TestCase):
    def test_report_proves_safe_assignment_and_full_font_roundtrip(self) -> None:
        report = analyze(ROM)
        self.assertTrue(report["passed"])
        self.assertEqual(report["font"]["independent_glyphs"], 2688)
        self.assertEqual(report["font"]["payload_bytes"], 48384)
        self.assertEqual(report["font"]["safe_unmapped_slots"], 76)
        self.assertEqual(report["font"]["first_safe_token"], "BAE3")
        self.assertEqual(report["probe"]["padding_regions_checked"], 192)
        self.assertTrue(
            report["checks"]["project_reopen_preserves_mapping_and_glyph"]
        )
        self.assertEqual(report["reference_all_fields"]["physical_fields"], 2688)
        self.assertEqual(report["reference_all_fields"]["safe_page_save_fields"], 672)


if __name__ == "__main__":
    unittest.main()
