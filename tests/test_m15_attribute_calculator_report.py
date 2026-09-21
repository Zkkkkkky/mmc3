from __future__ import annotations

from pathlib import Path
import unittest

from tools.report_m15_attribute_calculator import analyze


ROOT = Path(__file__).resolve().parents[1]
ROM = ROOT / "output" / "rom" / "DC_kuorong_464K.nes"


@unittest.skipUnless(ROM.is_file(), "需要正式构建 ROM")
class M15AttributeCalculatorReportTests(unittest.TestCase):
    def test_report_closes_implementation_scope_without_claiming_acceptance(self) -> None:
        report = analyze(ROM)
        self.assertTrue(report["passed"])
        self.assertEqual(
            report["delivery_status"],
            "implementation_complete_reference_and_user_pending",
        )
        self.assertEqual(report["ui"]["default"]["character_count"], 200)
        self.assertEqual(report["ui"]["unit_09_weapon_ids"], [7, 11])
        self.assertEqual(report["calculation"]["default"]["predicted_damage"], 143)
        self.assertEqual(report["calculation"]["default"]["actual_damage"], 107)
        self.assertEqual(len(report["pending_acceptance"]), 2)


if __name__ == "__main__":
    unittest.main()
