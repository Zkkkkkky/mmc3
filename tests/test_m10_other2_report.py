from __future__ import annotations

from pathlib import Path
import unittest

from tools.report_m10_other2_compatibility import analyze


ROOT = Path(__file__).resolve().parents[1]
ROM = ROOT / "output" / "rom" / "DC_kuorong_464K.nes"


@unittest.skipUnless(ROM.is_file(), "需要正式构建 ROM")
class M10Other2ReportTests(unittest.TestCase):
    def test_report_closes_implementation_scope_without_claiming_acceptance(self) -> None:
        report = analyze(ROM)
        self.assertTrue(report["passed"])
        self.assertEqual(
            report["delivery_status"],
            "implementation_complete_reference_and_user_pending",
        )
        evidence = report["evidence"]
        self.assertEqual(evidence["item_names"]["records"], 24)
        self.assertEqual(evidence["item_names"]["pool_capacity"], 184)
        self.assertEqual(evidence["item_prices"]["records"], 24)
        self.assertEqual(evidence["item_descriptions"]["no_op_roundtrips"], 24)
        self.assertEqual(evidence["shops"]["item_counts"], [4, 4, 4, 4, 1])
        self.assertEqual(len(evidence["shops"]["invalid_ids"]), 10)
        self.assertEqual(evidence["shop_dialogues"]["no_op_roundtrips"], 35)
        self.assertEqual(len(report["pending_acceptance"]), 2)


if __name__ == "__main__":
    unittest.main()
