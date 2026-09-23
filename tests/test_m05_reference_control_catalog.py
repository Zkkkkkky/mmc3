import unittest

from tools.report_m05_reference_control_catalog import build


class M05ReferenceControlCatalogTests(unittest.TestCase):
    def test_controls_and_save_fields_are_exhaustively_classified(self) -> None:
        report = build()
        self.assertTrue(report["passed"])
        self.assertEqual(report["counts"]["controls"], 125)
        self.assertEqual(
            report["counts"]["controls_by_surface"],
            {
                "main": 56,
                "special_skill": 8,
                "icon_binding": 5,
                "body_puzzle": 29,
                "fragment_puzzle": 27,
            },
        )
        self.assertEqual(report["counts"]["golden_save_fields"], 33)
        self.assertEqual(report["counts"]["classified_non_rom_fields"], 5)
        self.assertEqual(report["counts"]["guarded_pending_actions"], 11)
        self.assertEqual(report["counts"]["prepared_discovery_recipes"], 16)
        self.assertEqual(len(set(report["golden_save_fields"])), 33)
        self.assertEqual(
            set(report["prepared_discovery_recipes"]),
            {
                "body_upload_bmp",
                "fragment_upload_bmp",
                "icon_upload_bmp",
                "icon_binding_double_click",
                "body_puzzle_clear",
                "body_puzzle_move_up",
                "body_puzzle_move_down",
                "body_puzzle_move_left",
                "body_puzzle_move_right",
                "fragment_puzzle_move_up",
                "fragment_puzzle_move_down",
                "fragment_puzzle_move_left",
                "fragment_puzzle_move_right",
                "fragment_puzzle_clear",
                "fragment_puzzle_flip_horizontal",
                "fragment_puzzle_flip_vertical",
            },
        )
        self.assertTrue(
            all(
                item["status"] == "prepared_not_promoted"
                and item["case_kind"] == "discovery"
                and item["promotion_guarded"] is True
                and item["sha256"]
                for item in report["prepared_discovery_recipes"].values()
            )
        )
        self.assertTrue(report["checks"]["action_discovery_recipes_not_promoted"])

    def test_puzzle_dialogs_include_canvas_and_commit_controls(self) -> None:
        report = build()
        puzzle_controls = [
            item
            for item in report["controls"]
            if item["surface"] in {"body_puzzle", "fragment_puzzle"}
        ]
        self.assertEqual(len(puzzle_controls), 56)
        self.assertEqual(
            sum(str(item["class"]).startswith("Afx:") for item in puzzle_controls),
            13,
        )
        self.assertTrue(
            any(
                item["surface"] == "body_puzzle"
                and item["control_id"] == 340
                and item["text"] == "确定"
                for item in puzzle_controls
            )
        )
        self.assertTrue(
            any(
                item["surface"] == "fragment_puzzle"
                and item["text"] == "确定"
                for item in puzzle_controls
            )
        )

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
