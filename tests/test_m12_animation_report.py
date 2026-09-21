from __future__ import annotations

from pathlib import Path
import unittest

from tools.report_m12_animation_compatibility import analyze


ROOT = Path(__file__).resolve().parents[1]
ROM = ROOT / "output" / "rom" / "DC_kuorong_464K.nes"


@unittest.skipUnless(ROM.is_file(), "需要正式构建 ROM")
class M12AnimationReportTests(unittest.TestCase):
    def test_report_proves_safe_scope_and_explicit_deferred_boundary(self) -> None:
        report = analyze(ROM)
        self.assertTrue(report["passed"])
        self.assertEqual(
            report["delivery_status"],
            "implementation_complete_guarded_scope",
        )
        evidence = report["evidence"]
        self.assertEqual(
            evidence["table_counts"],
            {
                "map": 153,
                "ally": 256,
                "enemy": 256,
                "background": 106,
                "movement": 157,
                "sprite": 249,
            },
        )
        self.assertEqual(
            evidence["safe_patches"]["map"]["changed_indices"], [5]
        )
        self.assertEqual(
            evidence["safe_patches"]["movement"]["changed_indices"], [2]
        )
        self.assertEqual(
            evidence["safe_patches"]["sprite_code_first_tile"]["changed_indices"], [2]
        )
        self.assertTrue(
            report["checks"]["sprite_code_patch_is_golden_first_tile_only"]
        )
        self.assertTrue(report["checks"]["sprite_anchor_write_is_rejected"])
        animation_calls = evidence["animation_calls"]
        self.assertEqual(animation_calls["detected"], 86)
        self.assertEqual(animation_calls["editable"], 76)
        self.assertEqual(animation_calls["read_only"], 10)
        self.assertEqual(
            animation_calls["verified_contexts"],
            {
                "直接设置/调用序列": 56,
                "战斗流程调用序列": 8,
                "带参数精神调用序列": 2,
                "连续动画调用序列": 4,
                "奇迹闪烁调用序列": 4,
                "资料集地址/编号清单": 2,
            },
        )
        read_only_sites = animation_calls["read_only_sites"]
        self.assertEqual(len(read_only_sites), 10)
        self.assertEqual(
            [site["file_offset"] for site in read_only_sites],
            [
                "0x03804A",
                "0x0380DF",
                "0x0384B0",
                "0x03853D",
                "0x038982",
                "0x038E68",
                "0x038EEA",
                "0x038EF3",
                "0x03B9DC",
                "0x03B9E0",
            ],
        )
        self.assertEqual(
            {site["reason_code"] for site in read_only_sites},
            {
                "reference_value_conflict",
                "no_matching_reference_context",
                "id_meaning_only",
                "reference_address_mismatch",
                "embedded_vm_data_unverified",
            },
        )
        self.assertEqual(len(animation_calls["reference_audit"]["files"]), 6)
        self.assertTrue(report["checks"]["read_only_call_audit_complete"])
        self.assertEqual(
            evidence["background_boundary"]["static_reference_rule_ids"],
            ["$03", "$04", "$05", "$06", "$18", "$19"],
        )
        self.assertEqual(
            evidence["background_boundary"]["write_enabled"],
            "69_exact_boundary_parameter_records",
        )
        self.assertEqual(evidence["background_boundary"]["complete_records"], 75)
        self.assertEqual(evidence["background_boundary"]["editable_records"], 69)
        self.assertEqual(evidence["background_boundary"]["read_only_records"], 37)
        editable_backgrounds = evidence["background_boundary"]["editable_rule_ids"]
        self.assertEqual(len(editable_backgrounds), 69)
        self.assertEqual(
            editable_backgrounds[:7],
            ["$00", "$01", "$03", "$04", "$05", "$06", "$07"],
        )
        self.assertEqual(editable_backgrounds[-4:], ["$51", "$53", "$58", "$59"])
        self.assertEqual(
            evidence["safe_patches"]["background_body"]["changed_indices"],
            [5],
        )
        static_decodes = evidence["background_boundary"]["static_rule_decodes"]
        self.assertEqual(
            set(static_decodes),
            {"$03", "$04", "$05", "$06", "$18", "$19"},
        )
        self.assertTrue(
            all(
                item["complete"]
                and item["consumed"] == item["record_bytes"]
                for item in static_decodes.values()
            )
        )
        self.assertEqual(
            static_decodes["$03"]["editable_parameter_offsets"],
            [5, 6, 8, 9, 11, 12],
        )
        self.assertTrue(
            report["checks"][
                "background_static_rules_decode_to_parameter_boundaries"
            ]
        )
        self.assertTrue(report["checks"]["background_all_slots_classified"])
        self.assertEqual(
            len(evidence["background_boundary"]["slot_classification"]),
            106,
        )
        self.assertEqual(evidence["map_clone"]["new_index"], "$3F")
        self.assertEqual(evidence["map_clone"]["initial_verified_zero_pool_bytes"], 2306)
        self.assertEqual(evidence["sprite_clone"]["new_index"], "$EB")
        self.assertEqual(evidence["sprite_clone"]["pool_bytes"], 88)
        self.assertEqual(evidence["sprite_clone"]["maximum_first_copy_bytes"], 83)
        self.assertTrue(report["checks"]["sprite_clone_uses_reserved_tail_pool"])
        self.assertEqual(evidence["movement_clone"]["new_index"], "$7D")
        self.assertEqual(evidence["movement_clone"]["pool_bytes"], 32)
        self.assertEqual(evidence["movement_clone"]["maximum_first_copy_bytes"], 31)
        self.assertEqual(evidence["movement_clone"]["binding_after"], "7D")
        self.assertTrue(
            report["checks"][
                "movement_clone_uses_reserved_tail_and_unique_binding"
            ]
        )
        self.assertEqual(
            evidence["background_boundary"]["maximum_pointer_span"], 1420
        )
        self.assertEqual(evidence["complete_sprite_records"], 249)
        self.assertEqual(evidence["frame_rules"], 81)
        self.assertEqual(evidence["offline_complete_frame_rules"], 79)
        self.assertEqual(
            set(evidence["runtime_dependent_frame_rules"]), {"12", "21"}
        )
        self.assertEqual(len(evidence["sample"]["placements"]), 16)
        self.assertEqual(len(report["deferred_scope"]), 3)


if __name__ == "__main__":
    unittest.main()
