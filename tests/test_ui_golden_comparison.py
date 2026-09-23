from __future__ import annotations

import unittest

from tools.build_ui_golden_comparison import COMPARISONS, collect_report, render_markdown


class UiGoldenComparisonTest(unittest.TestCase):
    def test_manifest_covers_all_reference_visual_windows(self) -> None:
        self.assertEqual(len(COMPARISONS), 11)
        self.assertEqual(len({spec.key for spec in COMPARISONS}), len(COMPARISONS))
        self.assertEqual(
            {spec.module for spec in COMPARISONS},
            {"M02", "M03", "M04", "M05-M10", "M11", "M12", "M13", "M14", "M15", "M16", "M17"},
        )
        for spec in COMPARISONS:
            self.assertTrue(spec.legacy_features)
            self.assertIsInstance(spec.legacy_features, tuple)
            self.assertIsInstance(spec.extensions, tuple)
            self.assertIn(spec.verdict, {"legacy_core_aligned", "legacy_core_plus_extension"})

    def test_checked_in_screenshots_form_a_complete_traceable_report(self) -> None:
        report = collect_report()
        self.assertTrue(report["passed"], report["missing"])
        self.assertEqual(report["pair_count"], 11)
        self.assertFalse(report["pixel_identity_required"])
        for pair in report["pairs"]:
            self.assertEqual(len(pair["legacy"]["sha256"]), 64)
            self.assertEqual(len(pair["current"]["sha256"]), 64)
            self.assertGreater(pair["legacy"]["width"], 0)
            self.assertGreater(pair["current"]["height"], 0)

        markdown = render_markdown(report)
        self.assertIn("十一组对照总览", markdown)
        for spec in COMPARISONS:
            self.assertIn(f"pairs/{spec.key}.png", markdown)


if __name__ == "__main__":
    unittest.main()
