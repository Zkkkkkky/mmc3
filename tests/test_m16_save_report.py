from __future__ import annotations

import unittest

from tools.report_m16_save_compatibility import (
    DEFAULT_BATTLE_SAVE,
    DEFAULT_SAVE,
    analyze,
)


class M16SaveCompatibilityReportTests(unittest.TestCase):
    def test_reference_fceux_saves_pass_compatibility_report(self) -> None:
        report = analyze(DEFAULT_SAVE, DEFAULT_BATTLE_SAVE)

        self.assertTrue(report["passed"])
        self.assertEqual(report["layout"]["save_size"], 8192)
        self.assertTrue(report["round_trip"]["no_op_identical"])
        self.assertEqual(report["round_trip"]["unexpected_offsets"], [])
        self.assertTrue(report["round_trip"]["checksum_valid_after_mutation"])
        self.assertEqual(report["battle_save"]["enemy_battle_rows"], 7)


if __name__ == "__main__":
    unittest.main()
