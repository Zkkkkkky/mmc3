from __future__ import annotations

from pathlib import Path
import unittest

from tools.report_m12_animation_compatibility import analyze


ROOT = Path(__file__).resolve().parents[1]
ROM = ROOT / "output" / "rom" / "DC_kuorong_464K.nes"


@unittest.skipUnless(ROM.is_file(), "需要正式构建 ROM")
class M12AnimationReportTests(unittest.TestCase):
    def test_report_proves_puzzle_and_playback_scope(self) -> None:
        report = analyze(ROM)
        self.assertTrue(report["passed"])
        evidence = report["evidence"]
        self.assertEqual(evidence["complete_sprite_records"], 249)
        self.assertEqual(evidence["frame_rules"], 81)
        self.assertEqual(evidence["offline_complete_frame_rules"], 79)
        self.assertEqual(
            set(evidence["runtime_dependent_frame_rules"]), {"12", "21"}
        )
        self.assertEqual(len(evidence["sample"]["placements"]), 16)


if __name__ == "__main__":
    unittest.main()
