import unittest

from tools.report_m03_reference_save_coverage import build


class M03ReferenceSaveCoverageTests(unittest.TestCase):
    def test_partial_report_never_claims_complete(self) -> None:
        report = build()
        counts = report["counts"]
        self.assertEqual(counts["physical_fields"], 2134)
        self.assertEqual(counts["catalog_fields"], 1380)
        self.assertLessEqual(counts["completed_fields"], 1380)
        self.assertEqual(counts["remaining_fields"], 1380 - counts["completed_fields"])
        self.assertEqual(counts["safe_denominator_fields"], counts["completed_fields"])
        self.assertEqual(counts["excluded_reference_no_rom_effect"], 52)
        self.assertEqual(counts["excluded_reference_off_viewport"], 702)
        self.assertEqual(counts["runtime_route_selector_views"], 96)
        self.assertEqual(counts["guarded_structural_type_actions"], 386)
        self.assertEqual(counts["logical_ui_entries"], 2616)
        self.assertEqual(
            counts["catalog_fields"]
            + counts["excluded_reference_no_rom_effect"]
            + counts["excluded_reference_off_viewport"],
            2134,
        )
        for check in (
            "catalog_passed",
            "sequences_contiguous",
            "catalog_identities_match",
            "hash_links_contiguous",
            "each_save_changes_exactly_target_byte",
            "requested_value_persisted_exactly",
            "coordinate_result_changed_and_isolated",
            "byte_chain_replays",
            "tail_matches_work_rom",
        ):
            self.assertTrue(report["checks"][check], check)
        if counts["completed_fields"] < 1380 or not report["checks"]["two_fresh_reference_inventories_match"]:
            self.assertFalse(report["passed"])
            self.assertEqual(report["status"], "collecting")
        else:
            self.assertTrue(report["passed"])
            self.assertEqual(counts["safe_denominator_fields"], 1380)
            self.assertEqual(counts["fresh_inventory_fields"], 1380)


if __name__ == "__main__":
    unittest.main()
