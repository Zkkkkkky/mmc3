from __future__ import annotations

import unittest

from tools.report_m16_reference_field_coverage import build


class M16ReferenceFieldCoverageTests(unittest.TestCase):
    def test_reference_scope_is_complete_but_runtime_blocked(self) -> None:
        report = build()
        self.assertTrue(report["passed"])
        self.assertEqual(report["physical_controls"], 13)
        self.assertEqual(report["logical_field_families"], 18)
        self.assertEqual(report["safe_denominator_fields"], 0)
        self.assertEqual(
            report["classification_counts"],
            {"navigation_only": 1, "reference_runtime_error_blocked": 17},
        )
        self.assertTrue(all(report["checks"].values()))


if __name__ == "__main__":
    unittest.main()
