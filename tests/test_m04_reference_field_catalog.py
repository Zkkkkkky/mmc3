import unittest

from tools.report_m04_reference_field_catalog import build


class M04ReferenceFieldCatalogTests(unittest.TestCase):
    def test_all_trigger_record_bytes_are_cataloged(self) -> None:
        report = build()
        self.assertTrue(report["passed"])
        self.assertEqual(report["counts"]["maps"], 32)
        self.assertEqual(report["counts"]["nonempty_maps"], 16)
        self.assertEqual(report["counts"]["records"], 44)
        self.assertEqual(report["counts"]["physical_fields"], 176)
        self.assertEqual(report["counts"]["persistent_candidate_fields"], 103)
        self.assertEqual(report["counts"]["reference_forced_unlimited_fields"], 29)
        self.assertEqual(report["counts"]["reference_off_viewport_fields"], 44)
        self.assertEqual(report["reference_editor_controls"]["visible_control_count"], 10)
        self.assertTrue(report["checks"]["reference_editor_core_controls_present"])
        self.assertTrue(report["checks"]["existing_record_requires_delete_and_readd"])


if __name__ == "__main__":
    unittest.main()
