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
        self.assertEqual(report["counts"]["guarded_pending_actions"], 10)
        self.assertEqual(report["counts"]["classified_capacity_boundaries"], 1)
        self.assertEqual(report["counts"]["guarded_actions_with_discovery"], 10)
        self.assertEqual(report["counts"]["prepared_discovery_recipes"], 25)
        self.assertEqual(report["counts"]["promoted_golden_recipes"], 17)
        self.assertEqual(report["counts"]["pending_discovery_recipes"], 8)
        self.assertEqual(len(set(report["golden_save_fields"])), 33)
        self.assertEqual(
            set(report["prepared_discovery_recipes"]),
            {
                "body_compressed_upload_bmp",
                "fragment_compressed_upload_bmp",
                "main_clear_body",
                "main_clear_fragment",
                "body_upload_bmp",
                "fragment_upload_bmp",
                "icon_upload_bmp",
                "icon_binding_double_click",
                "body_puzzle_clear",
                "body_puzzle_move_up",
                "body_puzzle_move_down",
                "body_puzzle_move_left",
                "body_puzzle_move_right",
                "body_puzzle_template_8x8",
                "body_puzzle_template_7x9",
                "body_puzzle_template_9x7",
                "body_puzzle_template_10x6",
                "body_puzzle_swap_banks",
                "fragment_puzzle_move_up",
                "fragment_puzzle_move_down",
                "fragment_puzzle_move_left",
                "fragment_puzzle_move_right",
                "fragment_puzzle_clear",
                "fragment_puzzle_flip_horizontal",
                "fragment_puzzle_flip_vertical",
            },
        )
        recipes = report["prepared_discovery_recipes"].values()
        self.assertEqual(sum(item["status"] == "promoted_golden" for item in recipes), 17)
        recipes = report["prepared_discovery_recipes"].values()
        self.assertEqual(sum(item["status"] == "prepared_not_promoted" for item in recipes), 8)
        self.assertTrue(
            all(
                item["sha256"]
                and (
                    item["promotion_guarded"] is True
                    or item["promotion_complete"] is True
                )
                for item in report["prepared_discovery_recipes"].values()
            )
        )
        self.assertTrue(report["checks"]["action_recipes_reviewed"])
        self.assertTrue(
            report["checks"]["pending_recipes_have_explicit_dynamic_blockers"]
        )
        self.assertTrue(
            report["checks"]["pending_recipes_have_actionable_classification"]
        )
        pending = {
            name: item
            for name, item in report["prepared_discovery_recipes"].items()
            if item["status"] == "prepared_not_promoted"
        }
        self.assertEqual(len(pending), 8)
        self.assertTrue(
            all(item["dynamic_evidence"] is not None for item in pending.values())
        )
        self.assertIn(
            "exceeds_30_second_budget",
            pending["body_upload_bmp"]["promotion_blockers"],
        )
        self.assertTrue(
            pending["body_upload_bmp"]["dynamic_evidence"][
                "reopen_matches_original"
            ]
        )
        self.assertEqual(
            pending["body_upload_bmp"]["evidence_classification"],
            "reference_action_not_persistent",
        )
        self.assertEqual(
            pending["main_clear_body"]["evidence_classification"],
            "reference_cold_reopen_mismatch",
        )
        self.assertIn(
            "cold_reopen_does_not_match_expected",
            pending["main_clear_body"]["promotion_blockers"],
        )

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
        self.assertTrue(
            all(item["prepared_recipe_keys"] for item in report["guarded_pending_actions"])
        )
        self.assertTrue(report["checks"]["every_pending_action_has_reviewed_recipe"])
        self.assertEqual(
            {item["action"] for item in report["guarded_pending_actions"]},
            {
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
        self.assertEqual(
            report["classified_capacity_boundaries"],
            [
                {
                    "control_id": 130,
                    "action": "add_unit",
                    "classification": "byte_id_space_full",
                    "available_ids": "$01-$FF",
                    "slot_count": 255,
                    "product_behavior": "disabled_with_direct_edit_of_existing_empty_slots",
                }
            ],
        )


if __name__ == "__main__":
    unittest.main()
