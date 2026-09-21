import unittest

from tools.report_m03_reference_field_catalog import build


class M03ReferenceFieldCatalogTests(unittest.TestCase):
    def test_all_deployment_bytes_and_ui_only_entries_are_cataloged(self) -> None:
        report = build()
        self.assertTrue(report["passed"])
        self.assertEqual(report["counts"]["records"], 386)
        self.assertEqual(report["counts"]["records_by_family"], {"enemy": 290, "player": 91, "guest": 5})
        self.assertEqual(report["counts"]["physical_fields"], 2134)
        self.assertEqual(report["counts"]["persistent_candidate_fields"], 1380)
        self.assertEqual(report["counts"]["reference_no_rom_effect_fields"], 52)
        self.assertEqual(report["counts"]["reference_off_viewport_fields"], 702)
        self.assertEqual(report["counts"]["runtime_route_selector_views"], 96)
        self.assertEqual(report["counts"]["guarded_structural_type_actions"], 386)
        self.assertEqual(report["reference_editor_controls"]["visible_control_count"], 16)
        self.assertTrue(report["checks"]["reference_editor_core_controls_present"])
        self.assertTrue(report["checks"]["existing_record_editor_opened"])


if __name__ == "__main__":
    unittest.main()
