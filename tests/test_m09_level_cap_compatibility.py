from __future__ import annotations

from pathlib import Path
import unittest

from tools.report_m09_level_cap_compatibility import analyze


ROOT = Path(__file__).resolve().parents[1]
ROM = ROOT / "output" / "rom" / "DC_kuorong_464K.nes"
AUDIT_BEFORE = ROOT / "output" / "build" / "legacy-diff-audit" / "audit.nes"
AUDIT_AFTER = (
    ROOT
    / "output"
    / "build"
    / "legacy-diff-audit"
    / "cases"
    / "legacy_level_cap"
    / "after.nes"
)


class M09LevelCapCompatibilityTests(unittest.TestCase):
    def test_current_99_level_layout_rejects_legacy_60_to_61_repack(self) -> None:
        report = analyze(ROM, AUDIT_BEFORE, AUDIT_AFTER)
        supported = report["supported_rom"]
        legacy = report["legacy_audit"]

        self.assertTrue(report["passed"])
        self.assertEqual(supported["runtime_compare"], "C9 62")
        self.assertEqual(supported["verified_level_cap"], 99)
        self.assertEqual(supported["experience_entries"], 99)
        self.assertEqual(set(supported["first_growth_widths"]), {50})
        self.assertEqual(legacy["before_runtime_level_cap"], 60)
        self.assertEqual(legacy["after_runtime_level_cap"], 61)
        self.assertEqual(set(legacy["before_growth_widths"]), {30})
        self.assertEqual(set(legacy["after_growth_widths"]), {31})
        self.assertEqual(legacy["changed_bytes"], 3778)
        self.assertEqual(legacy["changed_prg_banks"], {"0x04": 19, "0x05": 3753})
        self.assertEqual(legacy["normalization_changes"], 6)
        self.assertFalse(legacy["accepted_by_current_product"])


if __name__ == "__main__":
    unittest.main()
