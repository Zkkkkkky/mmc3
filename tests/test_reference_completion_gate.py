from __future__ import annotations

import unittest

from tools.report_reference_completion_gate import (
    EXPECTED_FINAL_SAFE_DENOMINATOR,
    build,
)


class ReferenceCompletionGateTests(unittest.TestCase):
    def test_all_modules_and_reviewed_denominator_are_complete(self) -> None:
        report = build()
        self.assertEqual(report["counts"]["modules"], 18)
        self.assertEqual(report["counts"]["scope_complete"], 18)
        self.assertEqual(report["counts"]["scope_incomplete"], 0)
        self.assertEqual(
            {item["module"] for item in report["modules"] if not item["scope_complete"]},
            set(),
        )
        self.assertTrue(report["passed"])
        self.assertEqual(report["status"], "complete")
        self.assertTrue(report["checks"]["matrix_and_scope_agree"])
        self.assertTrue(
            report["checks"]["final_safe_denominator_matches_reviewed_scope"]
        )

    def test_complete_gate_requires_the_reviewed_6885_field_denominator(self) -> None:
        report = build()
        self.assertEqual(EXPECTED_FINAL_SAFE_DENOMINATOR, 6885)
        if report["passed"]:
            self.assertEqual(report["counts"]["scope_complete"], 18)
            self.assertEqual(report["counts"]["evidence_passed"], 18)
            self.assertEqual(
                report["counts"]["safe_denominator_fields"],
                EXPECTED_FINAL_SAFE_DENOMINATOR,
            )
            self.assertTrue(
                report["checks"]["final_safe_denominator_matches_reviewed_scope"]
            )

    def test_every_completed_positive_denominator_has_matching_evidence(self) -> None:
        report = build()
        for item in report["modules"]:
            if item["scope_complete"] and int(item["denominator_count"] or 0) > 0:
                self.assertTrue(item["evidence_passed"], item["module"])
                self.assertEqual(item["evidence_count"], item["denominator_count"])


if __name__ == "__main__":
    unittest.main()
