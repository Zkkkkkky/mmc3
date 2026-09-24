from __future__ import annotations

from pathlib import Path
import unittest

from tools.report_m14_scenario_compatibility import analyze


ROOT = Path(__file__).resolve().parents[1]
ROM = ROOT / "output" / "rom" / "DC_kuorong_464K.nes"


@unittest.skipUnless(ROM.is_file(), "需要正式构建 ROM")
class M14ScenarioReportTests(unittest.TestCase):
    def test_report_proves_supported_scope_and_lists_every_open_boundary(self) -> None:
        report = analyze(ROM)
        self.assertTrue(report["passed"])
        self.assertEqual(report["delivery_status"], "implementation_complete")
        self.assertEqual(report["reference_ui"]["node_count"], 72)
        self.assertEqual(
            set(
                report["reference_binary_capacity_strings"][
                    "event_error_templates"
                ]
            ),
            {
                "界面事件",
                "回合事件",
                "即时事件",
                "行动事件",
                "劝降事件",
                "地图事件",
            },
        )
        self.assertEqual(
            len(
                report["reference_binary_capacity_strings"][
                    "story_display_templates"
                ]
            ),
            9,
        )
        self.assertEqual(
            report["reference_button_690"],
            {
                "handler_offset": "0x1A0C57",
                "capacity_function_offset": "0x194936",
                "message_title": "提示",
                "signature_exact": True,
            },
        )
        self.assertEqual(report["legacy_scenario"]["group_count"], 96)
        self.assertEqual(report["legacy_scenario"]["instruction_count"], 4274)
        self.assertEqual(
            report["legacy_scenario"]["physical_pool_usage"],
            {
                "界面事件和回合事件": {"$1E": 3541},
                "即时事件": {"$1B": 8154, "$1F": 1525},
            },
        )
        self.assertEqual(report["global_events"]["instruction_count"], 2637)
        self.assertEqual(
            report["independent_action_events"]["pointer_count"], 256
        )
        self.assertEqual(
            report["independent_action_events"]["data_bank"], "$26"
        )
        self.assertEqual(
            report["independent_action_events"]["free_bytes"], 210
        )
        self.assertEqual(report["persuasion"]["editable_count"], 4)
        self.assertEqual(report["story_text"]["record_count"], 1837)
        self.assertEqual(
            report["story_text"]["split_37"]["writable_text_slots"], 51
        )
        self.assertEqual(
            report["story_text"]["split_37"]["protected_non_text_slots"],
            ["$00"],
        )
        self.assertFalse(report["story_text"]["split_37"]["relocatable"])
        self.assertEqual(report["chapter_victory"]["record_count"], 13)
        self.assertEqual(report["chapter_victory"]["start_file_offset"], "0x07A010")
        self.assertTrue(report["chapter_victory"]["fixed_total_pool"])
        self.assertTrue(report["chapter_victory"]["variable_record_length"])
        self.assertEqual(report["chapter_titles"]["record_count"], 32)
        self.assertEqual(
            report["chapter_titles"]["pointer_table_file_offset"],
            "0x016111",
        )
        self.assertTrue(report["chapter_titles"]["fixed_total_pool"])
        self.assertTrue(report["chapter_titles"]["variable_record_length"])
        self.assertEqual(report["incomplete_requirements"], [])
        self.assertTrue(
            report["checks"][
                "reference_button_690_handler_and_message_shape_are_exact"
            ]
        )
        self.assertTrue(
            report["checks"]["space_check_uses_verified_physical_pools"]
        )
        self.assertTrue(
            report["checks"][
                "chapter_victory_shared_pool_edit_is_exact"
            ]
        )
        self.assertTrue(
            report["checks"]["initial_victory_editor_is_rom_bound"]
        )
        self.assertTrue(
            report["checks"][
                "chapter_title_tables_and_shared_pool_edit_are_exact"
            ]
        )
        self.assertTrue(
            report["checks"]["title_preview_is_rom_bound_and_editable"]
        )
        self.assertTrue(
            report["checks"]["independent_action_table_is_complete"]
        )
        self.assertTrue(
            report["checks"][
                "action_insert_delete_repack_and_undo_are_exact"
            ]
        )


if __name__ == "__main__":
    unittest.main()
