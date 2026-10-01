import unittest

from tools.audit_m05_puzzle_golden_parity import audit


class M05PuzzleGoldenParityTests(unittest.TestCase):
    def test_all_promoted_puzzle_actions_match_legacy_bytes(self) -> None:
        report = audit()
        self.assertEqual(report["golden_actions"], 17)
        self.assertEqual(report["failed"], 0)
        self.assertEqual(report["passed"], 17)
        self.assertEqual(
            report["fragment_import_rule"],
            "retain proven global minimum-tile cover",
        )


if __name__ == "__main__":
    unittest.main()
