from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from tools.report_legacy_control_inventory import build_report, render_markdown


class LegacyControlInventoryTests(unittest.TestCase):
    def test_inventory_separates_canonical_and_diagnostic_snapshots(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            tree = {
                "class": "WTWindow",
                "text": "数据库",
                "ctrl_id": 0,
                "visible": True,
                "enabled": True,
                "children": [
                    {
                        "class": "Edit",
                        "text": "7",
                        "ctrl_id": 120,
                        "visible": True,
                        "enabled": True,
                        "children": [],
                    },
                    {
                        "class": "Button",
                        "text": "确定",
                        "ctrl_id": 100,
                        "visible": True,
                        "enabled": True,
                        "children": [],
                    },
                ],
            }
            for tag in ("C01_数据库", "DIAG_阻塞弹窗1"):
                (root / f"{tag}.json").write_text(
                    json.dumps(
                        {
                            "tag": tag,
                            "title": "数据库",
                            "class": "WTWindow",
                            "tree": tree,
                        },
                        ensure_ascii=False,
                    ),
                    encoding="utf-8",
                )

            report = build_report(root)

        self.assertEqual(report["counts"]["snapshot_files"], 2)
        self.assertEqual(report["counts"]["canonical_snapshots"], 1)
        self.assertEqual(report["counts"]["diagnostic_snapshots"], 1)
        self.assertEqual(report["counts"]["canonical_interactive_occurrences"], 2)
        self.assertEqual(report["counts"]["unique_window_titles"], 1)
        self.assertEqual(report["counts"]["unique_interactive_signatures"], 2)
        self.assertEqual(report["counts"]["unique_visible_interactive_signatures"], 2)
        self.assertEqual(report["interactive_class_occurrences"], {"Button": 1, "Edit": 1})
        self.assertEqual(
            {item["control_id"] for item in report["unique_interactive_controls"]},
            {100, 120},
        )
        self.assertIn("C01_数据库", render_markdown(report))

    def test_inventory_coalesces_repeated_main_window_controls(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            for tag, title, visible in (
                ("B02_载入A", "SRW2扩容版修改器V1.0：C:\\A.nes", False),
                ("B04_载入B", "SRW2扩容版修改器V1.0：D:\\B.nes", True),
            ):
                (root / f"{tag}.json").write_text(
                    json.dumps(
                        {
                            "tag": tag,
                            "title": title,
                            "class": "WTWindow",
                            "tree": {
                                "class": "WTWindow",
                                "text": title,
                                "ctrl_id": 0,
                                "visible": True,
                                "enabled": True,
                                "children": [
                                    {
                                        "class": "Edit",
                                        "text": "",
                                        "ctrl_id": 440,
                                        "visible": visible,
                                        "enabled": visible,
                                        "children": [],
                                    }
                                ],
                            },
                        },
                        ensure_ascii=False,
                    ),
                    encoding="utf-8",
                )

            report = build_report(root)

        self.assertEqual(report["counts"]["canonical_interactive_occurrences"], 2)
        self.assertEqual(report["counts"]["unique_interactive_signatures"], 1)
        self.assertEqual(report["counts"]["unique_visible_interactive_signatures"], 1)
        item = report["unique_interactive_controls"][0]
        self.assertTrue(item["observed_visible"])
        self.assertTrue(item["observed_enabled"])
        self.assertEqual(len(item["snapshot_tags"]), 2)


if __name__ == "__main__":
    unittest.main()
