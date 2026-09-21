import unittest

from tools.report_m05_reference_control_catalog import build


class M05ReferenceControlCatalogTests(unittest.TestCase):
    def test_controls_and_save_fields_are_exhaustively_classified(self) -> None:
        report = build()
        self.assertTrue(report["passed"])
        self.assertEqual(report["counts"]["controls"], 69)
        self.assertEqual(
            report["counts"]["controls_by_surface"],
            {"main": 56, "special_skill": 8, "icon_binding": 5},
        )
        self.assertEqual(report["counts"]["golden_save_fields"], 33)
        self.assertEqual(report["counts"]["classified_non_rom_fields"], 5)
        self.assertEqual(report["counts"]["guarded_pending_actions"], 11)
        self.assertEqual(len(set(report["golden_save_fields"])), 33)

    def test_pending_actions_keep_explicit_reasons(self) -> None:
        report = build()
        self.assertTrue(all(item["reason"] for item in report["guarded_pending_actions"]))
        self.assertEqual(
            {item["action"] for item in report["guarded_pending_actions"]},
            {
                "add_unit",
                "upload_body",
                "upload_fragment",
                "compressed_upload_body",
                "compressed_upload_fragment",
                "body_puzzle",
                "fragment_puzzle",
                "icon_binding",
                "upload_icon",
                "clear_body",
                "clear_fragment",
            },
        )


if __name__ == "__main__":
    unittest.main()
