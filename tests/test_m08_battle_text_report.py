from __future__ import annotations

from pathlib import Path
import unittest

from tools.report_m08_battle_text_compatibility import analyze


ROOT = Path(__file__).resolve().parents[1]
ROM = ROOT / "output" / "rom" / "DC_kuorong_464K.nes"


@unittest.skipUnless(ROM.is_file(), "需要正式构建 ROM")
class M08BattleTextReportTests(unittest.TestCase):
    def test_report_proves_fixed_bank_repack_and_gap_isolation(self) -> None:
        report = analyze(ROM)
        self.assertTrue(report["passed"])
        self.assertEqual(report["arenas"]["2A"]["capacity"], 5432)
        self.assertEqual(report["arenas"]["0E"]["capacity"], 6294)
        self.assertEqual(report["arenas"]["2A"]["free"], 0)
        self.assertEqual(report["arenas"]["0E"]["free"], 0)
        self.assertNotEqual(
            report["repack_2a"]["pointer_before"],
            report["repack_2a"]["pointer_after"],
        )
        self.assertTrue(
            all(
                row["unchanged"]
                for row in report["repack_0e"]["protected_non_text_gaps"]
            )
        )
        self.assertTrue(report["overflow"]["rejected"])


if __name__ == "__main__":
    unittest.main()
