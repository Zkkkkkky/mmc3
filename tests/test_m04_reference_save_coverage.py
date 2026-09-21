import unittest

from tools.report_m04_reference_save_coverage import build


class M04ReferenceSaveCoverageTests(unittest.TestCase):
    def test_partial_report_never_claims_complete(self) -> None:
        report = build()
        counts = report["counts"]
        self.assertEqual(counts["physical_fields"], 176)
        self.assertEqual(counts["records"], 44)
        self.assertEqual(counts["catalog_fields"], 103)
        self.assertLessEqual(counts["completed_fields"], 103)
        self.assertEqual(counts["remaining_fields"], 103 - counts["completed_fields"])
        self.assertEqual(counts["safe_denominator_fields"], counts["completed_fields"])
        self.assertEqual(counts["excluded_reference_off_viewport"], 44)
        self.assertEqual(counts["excluded_reference_forced_unlimited"], 29)
        self.assertEqual(
            counts["catalog_fields"]
            + counts["excluded_reference_off_viewport"]
            + counts["excluded_reference_forced_unlimited"],
            176,
        )
        for check in (
            "catalog_passed",
            "sequences_contiguous",
            "catalog_identities_match",
            "each_isolated_case_changes_exactly_target_byte",
        ):
            self.assertTrue(report["checks"][check], check)
        if counts["completed_fields"] < 103 or not (
            report["checks"]["aggregate_replays_all_cases"]
            and report["checks"]["two_fresh_reference_inventories_match"]
        ):
            self.assertFalse(report["passed"])
            self.assertEqual(report["status"], "collecting")
        else:
            self.assertTrue(report["passed"])
            self.assertEqual(counts["safe_denominator_fields"], 103)
            self.assertEqual(counts["fresh_inventory_fields"], 103)


if __name__ == "__main__":
    unittest.main()
