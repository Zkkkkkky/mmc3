from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from tools.report_reference_save_matrix import build_report, checklist_rows, render_markdown


ROOT = Path(__file__).resolve().parents[1]


class ReferenceSaveMatrixTests(unittest.TestCase):
    def test_parses_only_numbered_rows_in_section_five(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "M03.md"
            path.write_text(
                "\n".join(
                    [
                        "## 4. 数据",
                        "| 9 | 不应读取 | x | y | z |",
                        "## 5. 黄金对照采集清单",
                        "| # | 采集对象 | 参考版操作 | 预期差分语义 | 备注 |",
                        "|---|---|---|---|---|",
                        "| 1 | 等级 | 改一级并保存 | 单字节 | 冷启动 |",
                        "## 6. 禁区",
                        "| 2 | 不应读取 | x | y | z |",
                    ]
                ),
                encoding="utf-8",
            )

            rows = checklist_rows(path, "M03")

        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["target"], "等级")
        self.assertEqual(rows[0]["expected_diff"], "单字节")

    def test_markdown_marks_modules_without_goldens(self) -> None:
        report = {
            "counts": {
                "modules": 1,
                "documented_scenarios": 1,
                "configured_fields": 0,
                "configured_discovery_fields": 0,
                "configured_unarchived_fields": 0,
                "registered_fields": 0,
                "passed_golden_fields": 0,
                "modules_without_registered_fields": 1,
                "field_scope_modules_complete": 0,
                "field_scope_modules_incomplete": 1,
                "known_final_denominator_fields": 0,
            },
            "scope_note": "note",
            "final_denominator_ready": False,
            "final_denominator_note": "not ready",
            "modules": [
                {
                    "module": "M03",
                    "documented_scenarios": 1,
                    "configured_fields": 0,
                    "configured_discovery_fields": 0,
                    "configured_unarchived_fields": 0,
                    "registered_fields": 0,
                    "passed_golden_fields": 0,
                    "has_registered_field": False,
                    "field_scope_classification": "field_scope_incomplete",
                    "denominator_complete": False,
                    "denominator_count": None,
                    "known_families": ["部署字段"],
                    "field_scope_remaining": "待定位",
                }
            ],
            "configured_unarchived": [],
            "scenarios": [
                {
                    "module": "M03",
                    "scenario": 1,
                    "target": "等级",
                    "reference_action": "保存",
                    "expected_diff": "单字节",
                    "notes": "",
                }
            ],
        }
        markdown = render_markdown(report)
        self.assertIn("待建黄金", markdown)
        self.assertIn("等级", markdown)
        self.assertIn("最终 G1 分母可用：否", markdown)

    def test_repository_scope_exposes_only_the_reviewed_final_denominator(self) -> None:
        report = build_report(ROOT)

        self.assertTrue(report["final_denominator_ready"])
        self.assertEqual(report["counts"]["field_scope_modules_complete"], 18)
        self.assertEqual(report["counts"]["field_scope_modules_incomplete"], 0)
        self.assertEqual(report["counts"]["known_final_denominator_fields"], 6842)
        self.assertEqual(report["counts"]["configured_unarchived_fields"], 0)
        self.assertGreaterEqual(report["counts"]["configured_discovery_fields"], 1)
        incomplete = {
            item["module"]
            for item in report["modules"]
            if not item["denominator_complete"]
        }
        self.assertEqual(incomplete, set())
        m17 = next(item for item in report["modules"] if item["module"] == "M17")
        self.assertTrue(m17["denominator_complete"])
        self.assertEqual(m17["denominator_count"], 32)


if __name__ == "__main__":
    unittest.main()
