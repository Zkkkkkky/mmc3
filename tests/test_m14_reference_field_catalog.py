from __future__ import annotations

import unittest

from tools.report_m14_reference_field_catalog import build


class M14ReferenceFieldCatalogTests(unittest.TestCase):
    def test_direct_field_catalog_and_read_only_instruction_scope(self) -> None:
        report = build()
        self.assertTrue(report["passed"])
        self.assertEqual(report["field_count"], 3217)
        self.assertEqual(report["read_only_instruction_rows"], 9920)
        self.assertEqual(
            report["family_counts"],
            {
                "chapter_title": 32,
                "chapter_initial_victory": 32,
                "action_name": 256,
                "surrender_chapter": 32,
                "surrender_ally": 32,
                "surrender_enemy": 32,
                "map_name": 255,
                "story_text": 2295,
                "victory_text": 251,
            },
        )
        self.assertTrue(all(report["checks"].values()))


if __name__ == "__main__":
    unittest.main()
