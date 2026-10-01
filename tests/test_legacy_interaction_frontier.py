from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from tools.report_legacy_interaction_frontier import (
    _canonical_control_identity,
    build_report,
)
from tools.report_weapon_ff_matrix import (
    EXPECTED_ACTION_CASES,
    EXPECTED_CASES,
    build_matrix,
)


class LegacyInteractionFrontierTests(unittest.TestCase):
    def test_main_runtime_control_aliases_collapse_to_current_golden_identity(self) -> None:
        title = "SRW2扩容版修改器V1.0：<ROM>"
        self.assertEqual(
            _canonical_control_identity(title, "ComboBox", 660),
            ("ComboBox", 680),
        )
        self.assertEqual(
            _canonical_control_identity(title, "Button", 640),
            ("Button", 660),
        )
        self.assertEqual(
            _canonical_control_identity(title, "Jy_iext1_05", 600),
            ("Afx:400000:b:10003:900015:0", 610),
        )
        self.assertEqual(
            _canonical_control_identity(title, "Jy_iext1_05", 650),
            ("Afx:400000:b:10003:900015:0", 670),
        )
        for image_base in ("3c60000", "5e20000", "400000"):
            self.assertEqual(
                _canonical_control_identity(
                    title, f"Afx:{image_base}:b:10003:900015:0", 130,
                ),
                ("Afx:400000:b:10003:900015:0", 130),
            )
        self.assertEqual(
            _canonical_control_identity("其他", "ComboBox", 660),
            ("ComboBox", 660),
        )

    def test_unique_nonzero_control_id_collapses_snapshot_tree_path_drift(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "output" / "verification"
            for index, prefix_count in enumerate((2, 5)):
                controls = root / f"legacy-ui-probe-{index}" / "controls"
                controls.mkdir(parents=True)
                children = [
                    {
                        "class": "Static", "ctrl_id": 0, "text": f"spacer-{slot}",
                        "visible": False, "enabled": True, "children": [],
                    }
                    for slot in range(prefix_count)
                ]
                children.append(
                    {
                        "class": "CPageControl", "ctrl_id": 2570, "text": "",
                        "visible": True, "enabled": True, "children": [],
                    }
                )
                snapshot = {
                    "tag": f"dialogue-{index}", "title": "数据库",
                    "tree": {
                        "class": "WTWindow", "ctrl_id": 0, "text": "数据库",
                        "visible": True, "enabled": True, "children": children,
                    },
                }
                (controls / "dialogue.json").write_text(
                    json.dumps(snapshot, ensure_ascii=False), encoding="utf-8"
                )

            report = build_report(root)
            page_actions = [
                item for item in report["actions"]
                if item["control_class"] == "CPageControl"
                and item["control_id"] == 2570
            ]
            self.assertEqual(len(page_actions), 3)
            self.assertTrue(all(item["tree_path"] == [2] for item in page_actions))
            self.assertTrue(
                all(item["source_tree_paths"] == [[2], [5]] for item in page_actions)
            )

    def test_reused_control_id_remains_path_sensitive(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "output" / "verification"
            controls = root / "legacy-ui-probe-reused" / "controls"
            controls.mkdir(parents=True)
            snapshot = {
                "tag": "reused", "title": "重复控件",
                "tree": {
                    "class": "WTWindow", "ctrl_id": 0, "text": "重复控件",
                    "visible": True, "enabled": True,
                    "children": [
                        {
                            "class": "Button", "ctrl_id": 10, "text": "甲",
                            "visible": True, "enabled": True, "children": [],
                        },
                        {
                            "class": "Button", "ctrl_id": 10, "text": "乙",
                            "visible": True, "enabled": True, "children": [],
                        },
                    ],
                },
            }
            (controls / "reused.json").write_text(
                json.dumps(snapshot, ensure_ascii=False), encoding="utf-8"
            )

            report = build_report(root)
            button_actions = [
                item for item in report["actions"]
                if item["control_class"] == "Button" and item["control_id"] == 10
            ]
            self.assertEqual(len(button_actions), 6)
            self.assertEqual(
                {tuple(item["tree_path"]) for item in button_actions}, {(0,), (1,)}
            )

    def test_main_window_rom_paths_do_not_multiply_function_denominator(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "output" / "verification"
            for index, rom_path in enumerate((r"D:\probe-a.nes", r"E:\probe-b.nes")):
                controls = root / f"legacy-ui-probe-{index}" / "controls"
                controls.mkdir(parents=True)
                snapshot = {
                    "tag": f"main-{index}",
                    "title": f"SRW2扩容版修改器V1.0：{rom_path}",
                    "tree": {
                        "class": "WTWindow", "ctrl_id": 0,
                        "text": "main", "visible": True, "enabled": True,
                        "children": [
                            {
                                "class": "Button", "ctrl_id": 10,
                                "text": "数据库", "visible": True,
                                "enabled": True, "children": [],
                            }
                        ],
                    },
                }
                (controls / "main.json").write_text(
                    json.dumps(snapshot, ensure_ascii=False), encoding="utf-8"
                )

            report = build_report(root)
            button_actions = [
                item for item in report["actions"]
                if item["control_class"] == "Button"
            ]
            self.assertEqual(len(button_actions), 3)
            self.assertEqual(
                {item["window"] for item in button_actions},
                {"SRW2扩容版修改器V1.0：<ROM>"},
            )
            self.assertTrue(
                all(len(item["source_snapshots"]) == 2 for item in button_actions)
            )

    def test_weapon_ff_matrix_requires_all_exact_goldens_and_maps_only_exercised_actions(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "output" / "verification"
            for session, (sha256_after, diff_count, _label) in EXPECTED_CASES.items():
                discovery = root / session / "interaction-discovery"
                discovery.mkdir(parents=True)
                (discovery / "weapon-ff-save-golden.json").write_text(
                    json.dumps(
                        {
                            "validated": True,
                            "selector_closed_by_action": True,
                            "sha256_after": sha256_after,
                            "diff_count": diff_count,
                        },
                        ensure_ascii=False,
                    ),
                    encoding="utf-8",
                )
            for session, expected in EXPECTED_ACTION_CASES.items():
                discovery = root / session / "interaction-discovery"
                discovery.mkdir(parents=True)
                payload = {"validated": True}
                payload.update(
                    {key: value for key, value in expected.items() if key != "label"}
                )
                (discovery / "weapon-ff-save-golden.json").write_text(
                    json.dumps(payload, ensure_ascii=False), encoding="utf-8"
                )
            frontier = Path(tmp) / "frontier.json"
            frontier.write_text(
                json.dumps(
                    {
                        "actions": [
                            {
                                "action_id": "insert-action",
                                "window": "武器修改",
                                "control_class": "ContextMenuItem",
                                "control_id": 20014,
                                "observed_text": "插入",
                                "action": "activate_context_command",
                                "context_origin": {
                                    "control_class": "ListBox",
                                    "control_id": 2530,
                                    "control_index": 10,
                                    "observed_text": "",
                                },
                            },
                            {
                                "action_id": "ff-left-click",
                                "window": "武器指令",
                                "control_class": "Button",
                                "control_id": 190,
                                "observed_text": "FF动画结束",
                                "action": "left_click",
                            },
                            {
                                "action_id": "ff-keyboard",
                                "window": "武器指令",
                                "control_class": "Button",
                                "control_id": 190,
                                "observed_text": "FF动画结束",
                                "action": "keyboard_activate",
                            },
                            {
                                "action_id": "ff-right-click",
                                "window": "武器指令",
                                "control_class": "Button",
                                "control_id": 190,
                                "observed_text": "FF动画结束",
                                "action": "right_click",
                            },
                        ]
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )

            matrix = build_matrix(root, frontier)
            self.assertTrue(matrix["validated"])
            self.assertEqual(len(matrix["cases"]), 8)
            self.assertEqual(
                [item["action_id"] for item in matrix["execution_records"]],
                [
                    "insert-action", "ff-left-click", "ff-keyboard",
                    "ff-right-click",
                ],
            )

            bad = next(iter(EXPECTED_CASES))
            path = root / bad / "interaction-discovery" / "weapon-ff-save-golden.json"
            payload = json.loads(path.read_text(encoding="utf-8"))
            payload["diff_count"] += 1
            path.write_text(json.dumps(payload), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "FF golden mismatch"):
                build_matrix(root, frontier)

    def test_standard_custom_menu_and_conditional_actions_remain_pending(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "output" / "verification"
            controls = root / "legacy-ui-probe-sample" / "controls"
            controls.mkdir(parents=True)
            base = {
                "tag": "state-a",
                "title": "数据库",
                "tree": {
                    "class": "WTWindow", "ctrl_id": 0, "text": "数据库",
                    "visible": True, "enabled": True,
                    "children": [
                        {"class": "Button", "ctrl_id": 10, "text": "确定", "visible": True, "enabled": True, "children": []},
                        {"class": "_EL_DrawPanel", "ctrl_id": 20, "text": "", "visible": True, "enabled": True, "children": []},
                        {"class": "Edit", "ctrl_id": 30, "text": "", "visible": False, "enabled": False, "children": []},
                    ],
                },
            }
            (controls / "a.json").write_text(json.dumps(base, ensure_ascii=False), encoding="utf-8")
            changed = json.loads(json.dumps(base))
            changed["tag"] = "state-b"
            changed["tree"]["children"][2]["visible"] = True
            changed["tree"]["children"][2]["enabled"] = True
            (controls / "b.json").write_text(json.dumps(changed, ensure_ascii=False), encoding="utf-8")
            (controls / "menu.json").write_text(
                json.dumps([{"text": "数据", "items": [{"text": "数据库", "id": 20008}]}], ensure_ascii=False),
                encoding="utf-8",
            )

            report = build_report(root)
            actions = {(item["control_class"], item["action"]) for item in report["actions"]}
            self.assertIn(("Button", "right_click"), actions)
            self.assertIn(("_EL_DrawPanel", "drag_grid"), actions)
            self.assertIn(("Edit", "discover_state_triggers"), actions)
            self.assertIn(("MenuItem", "activate"), actions)
            self.assertFalse(report["closed"])
            self.assertEqual(report["counts"]["by_status"], {"pending": report["counts"]["actions"]})

    def test_visible_movement_simulator_canvas_gets_region_gestures(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "output" / "verification"
            controls = root / "legacy-ui-probe-simulator" / "controls"
            controls.mkdir(parents=True)
            snapshot = {
                "tag": "simulator",
                "title": "运行规律模拟",
                "tree": {
                    "class": "WTWindow",
                    "ctrl_id": 0,
                    "text": "运行规律模拟",
                    "visible": True,
                    "enabled": True,
                    "children": [
                        {
                            "class": "Afx:400000:b:10003:900015:0",
                            "ctrl_id": 100,
                            "text": "",
                            "visible": True,
                            "enabled": True,
                            "children": [],
                        },
                        {
                            "class": "Afx:unrelated",
                            "ctrl_id": 999,
                            "text": "",
                            "visible": True,
                            "enabled": True,
                            "children": [],
                        },
                        {
                            "class": "_EL_DrawPanel",
                            "ctrl_id": 280,
                            "text": "",
                            "visible": False,
                            "enabled": False,
                            "children": [],
                        },
                    ],
                },
            }
            (controls / "simulator.json").write_text(
                json.dumps(snapshot, ensure_ascii=False), encoding="utf-8"
            )

            report = build_report(root)
            canvas_actions = {
                item["action"]
                for item in report["actions"]
                if item["control_id"] == 100
            }
            self.assertEqual(
                canvas_actions,
                {
                    "left_click_regions",
                    "double_click_regions",
                    "right_click_regions",
                    "drag_regions",
                },
            )
            self.assertFalse(
                any(item["control_id"] == 999 for item in report["actions"])
            )
            self.assertFalse(
                any(item["control_id"] == 280 for item in report["actions"])
            )

    def test_permanently_hidden_or_disabled_templates_do_not_create_gestures(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "output" / "verification"
            controls = root / "legacy-ui-probe-hidden" / "controls"
            controls.mkdir(parents=True)
            snapshot = {
                "tag": "hidden-templates",
                "title": "规律",
                "tree": {
                    "class": "WTWindow", "ctrl_id": 0, "text": "规律",
                    "visible": True, "enabled": True,
                    "children": [
                        {
                            "class": "AfxWnd42s", "ctrl_id": 1008,
                            "text": "<", "visible": False, "enabled": True,
                            "children": [],
                        },
                        {
                            "class": "Button", "ctrl_id": 77,
                            "text": "占位", "visible": True, "enabled": False,
                            "children": [],
                        },
                    ],
                },
            }
            (controls / "hidden.json").write_text(
                json.dumps(snapshot, ensure_ascii=False), encoding="utf-8"
            )

            report = build_report(root)
            self.assertFalse(
                any(item["control_id"] in {77, 1008} for item in report["actions"])
            )

    def test_stock_edit_context_menu_is_counted_as_reachability_not_product_commands(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "output" / "verification"
            discovery = (
                root / "legacy-ui-probe-platform-menu" /
                "interaction-discovery"
            )
            discovery.mkdir(parents=True)
            menu = [
                {"text": "撤消(&U)", "id": 1},
                {"text": "剪切(&T)", "id": 2},
                {"text": "复制(&C)", "id": 3},
                {"text": "粘贴(&P)", "id": 4},
                {"text": "全选(&A)", "id": 5},
                {"text": "显示 Unicode 控制字符(&S)", "id": 6},
            ]
            (discovery / "platform.json").write_text(
                json.dumps(
                    {
                        "records": [
                            {
                                "state": "规律", "class": "Edit",
                                "control_id": 240, "control_index": 1,
                                "text": "FF", "menus": [menu],
                            }
                        ]
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )

            report = build_report(root)
            self.assertEqual(report["sources"]["platform_context_menu_origins"], 1)
            self.assertFalse(
                any(
                    item["action"] == "activate_platform_context_command"
                    for item in report["actions"]
                )
            )

    def test_execution_record_can_close_single_action(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "output" / "verification"
            controls = root / "legacy-ui-probe-sample" / "controls"
            controls.mkdir(parents=True)
            (controls / "menu.json").write_text(
                json.dumps([{"text": "关于", "id": 20025}], ensure_ascii=False), encoding="utf-8"
            )
            first = build_report(root)
            action_id = first["actions"][0]["action_id"]
            evidence = Path(tmp) / "execution.json"
            evidence.write_text(
                json.dumps({"records": [{"action_id": action_id, "status": "passed", "result": "关于窗口"}]}, ensure_ascii=False),
                encoding="utf-8",
            )
            second = build_report(root, evidence)
            self.assertTrue(second["closed"])
            self.assertEqual(second["counts"]["by_status"], {"passed": 1})

    def test_validated_discovery_can_embed_execution_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "output" / "verification"
            session = root / "legacy-ui-probe-cancel"
            controls = session / "controls"
            discovery = session / "interaction-discovery"
            controls.mkdir(parents=True)
            discovery.mkdir(parents=True)
            snapshot = {
                "tag": "cancel",
                "title": "定义声音",
                "tree": {
                    "class": "WTWindow", "ctrl_id": 0, "text": "定义声音",
                    "visible": True, "enabled": True,
                    "children": [
                        {"class": "Button", "ctrl_id": 110, "text": "取消", "visible": True, "enabled": True, "children": []},
                    ],
                },
            }
            (controls / "cancel.json").write_text(
                json.dumps(snapshot, ensure_ascii=False), encoding="utf-8"
            )
            first = build_report(root)
            action_id = next(
                item["action_id"] for item in first["actions"]
                if item["action"] == "left_click"
            )
            (discovery / "cancel-golden.json").write_text(
                json.dumps(
                    {
                        "validated": True,
                        "records": [{"command": "F4", "status": "cancelled"}],
                        "execution_records": [
                            {"action_id": action_id, "status": "passed", "result": "零写入"}
                        ],
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            second = build_report(root)
            self.assertEqual(second["counts"]["by_status"]["passed"], 1)
            self.assertEqual(second["sources"]["embedded_execution_records"], 1)

    def test_validated_context_discovery_adds_commands_and_rejects_false_tabs(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "output" / "verification"
            valid = root / "legacy-ui-probe-valid" / "interaction-discovery"
            invalid = root / "legacy-ui-probe-invalid" / "interaction-discovery"
            valid.mkdir(parents=True)
            invalid.mkdir(parents=True)
            record = {
                "state": "机体修改",
                "class": "ListBox",
                "control_id": 420,
                "control_index": 3,
                "text": "[01]001: 盖塔",
                "menus": [[{"text": "导出机体", "id": 20003}]],
            }
            (valid / "menus.json").write_text(
                json.dumps(
                    {
                        "tabs": [{"label": "机体修改", "phase2_signature_match": True}],
                        "records": [record],
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            false_record = dict(record)
            false_record["state"] = "伪人物修改"
            (invalid / "menus.json").write_text(
                json.dumps(
                    {
                        "tabs": [{"label": "伪人物修改"}],
                        "records": [false_record],
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )

            report = build_report(root)
            context_actions = [
                item
                for item in report["actions"]
                if item["control_class"] == "ContextMenuItem"
            ]
            self.assertEqual([item["observed_text"] for item in context_actions], ["导出机体"])
            self.assertEqual(report["sources"]["interaction_discovery_files"], 1)
            self.assertEqual(report["sources"]["rejected_interaction_discovery_files"], 1)

    def test_nested_page_context_probes_are_added_after_signature_gate(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "output" / "verification"
            discovery = root / "legacy-ui-probe-rules" / "interaction-discovery"
            discovery.mkdir(parents=True)
            (discovery / "weapon-rule-pages.json").write_text(
                json.dumps(
                    {
                        "validated": True,
                        "tabs": [
                            {
                                "label": "光束组图规律",
                                "phase2_signature_match": True,
                            }
                        ],
                        "records": [
                            {
                                "label": "光束组图规律",
                                "context_probes": [
                                    {
                                        "state": "武器规律/光束组图规律",
                                        "class": "Edit",
                                        "control_id": 250,
                                        "control_index": 2,
                                        "text": "消除屏幕1",
                                        "menus": [[{"text": "复制", "id": 769}]],
                                    }
                                ],
                            }
                        ],
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )

            report = build_report(root)
            context_actions = [
                item
                for item in report["actions"]
                if item["control_class"] == "ContextMenuItem"
            ]
            self.assertEqual([item["observed_text"] for item in context_actions], ["复制"])
            self.assertEqual(report["sources"]["interaction_discovery_files"], 1)
            self.assertEqual(report["sources"]["rejected_interaction_discovery_files"], 0)

    def test_failed_recursive_command_session_cannot_pollute_frontier(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "output" / "verification"
            session = root / "legacy-ui-probe-recursive-dbcmd-bad"
            controls = session / "controls"
            discovery = session / "interaction-discovery"
            controls.mkdir(parents=True)
            discovery.mkdir(parents=True)
            (controls / "foreign.json").write_text(
                json.dumps(
                    {
                        "tag": "foreign",
                        "title": "其他应用",
                        "tree": {
                            "class": "Button",
                            "ctrl_id": 1,
                            "text": "不应计入",
                            "visible": True,
                            "enabled": True,
                            "children": [],
                        },
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            (discovery / "database-command-descendants.json").write_text(
                json.dumps({"validated": False, "records": []}),
                encoding="utf-8",
            )

            report = build_report(root)
            self.assertEqual(report["counts"]["actions"], 0)
            self.assertEqual(report["sources"]["snapshot_files"], 0)
            self.assertEqual(
                report["sources"]["rejected_interaction_discovery_files"], 1
            )


if __name__ == "__main__":
    unittest.main()
