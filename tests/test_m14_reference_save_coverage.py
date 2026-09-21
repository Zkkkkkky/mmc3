from __future__ import annotations

import unittest

from tools.report_m14_reference_save_coverage import PERSISTENT, build


class M14ReferenceSaveCoverageTests(unittest.TestCase):
    def test_partial_chain_never_claims_full_coverage(self) -> None:
        report = build()
        counts = report["counts"]
        self.assertEqual(counts["catalog_fields"], 3217)
        self.assertEqual(counts["persistent_catalog_fields"], 2674)
        self.assertEqual(counts["volatile_catalog_fields"], 543)
        self.assertEqual(counts["read_only_instruction_rows"], 9920)
        self.assertEqual(
            counts["persistent_catalog_fields"] + counts["volatile_catalog_fields"],
            counts["catalog_fields"],
        )
        self.assertLessEqual(counts["safe_denominator_fields"], 2674)
        self.assertLessEqual(counts["completed_fields"], counts["catalog_fields"])
        self.assertEqual(sum(counts["families"].values()), counts["completed_fields"])
        self.assertEqual(sum(counts["statuses"].values()), counts["completed_fields"])
        self.assertEqual(
            counts["safe_denominator_fields"],
            sum(
                value
                for family, value in counts["families"].items()
                if family in PERSISTENT
            ),
        )
        self.assertEqual(
            counts["remaining_fields"],
            counts["catalog_fields"] - counts["completed_fields"],
        )
        for check in (
            "catalog_passed",
            "sequences_contiguous",
            "catalog_identities_match",
            "hash_links_contiguous",
            "byte_ranges_replay",
            "requested_value_observed_before_each_save",
            "persistent_and_volatile_family_classification_matches",
        ):
            self.assertTrue(report["checks"][check], check)
        if counts["remaining_fields"] or not report["checks"]["two_fresh_final_inventories_match"]:
            self.assertFalse(report["passed"])
            self.assertEqual(report["status"], "collecting")
        else:
            self.assertTrue(report["passed"])
            self.assertEqual(report["status"], "complete")
            self.assertEqual(counts["safe_denominator_fields"], 2674)
            self.assertEqual(counts["cold_inventory_fields"], 3217)


if __name__ == "__main__":
    unittest.main()
