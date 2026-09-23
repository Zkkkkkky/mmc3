from __future__ import annotations

import unittest

from tools.report_m12_reference_field_coverage import build


class M12ReferenceFieldCoverageTests(unittest.TestCase):
    def test_full_reference_scope_is_classified_and_guarded(self) -> None:
        report = build()
        self.assertTrue(report["passed"])
        self.assertEqual(report["logical_fields"], 1281)
        self.assertEqual(report["safe_denominator_fields"], 241)
        self.assertEqual(report["classification_counts"], {
            "no_effect": 894,
            "reference_persistent_product_narrow_guarded": 146,
            "safe_persistent": 241,
        })
        self.assertTrue(all(report["checks"].values()))
        call_fields = [
            item
            for item in report["fields"]
            if item["family"].startswith("spirit_animation")
            or item["family"].startswith("map_weapon_animation_")
        ]
        self.assertEqual(len(call_fields), 43)
        self.assertEqual(
            sum(item["classification"] == "safe_persistent" for item in call_fields),
            43,
        )
        self.assertEqual(
            {
                item["current_call_offset"]
                for item in call_fields
                if item["classification"] == "reference_persistent_product_unmapped"
            },
            set(),
        )


if __name__ == "__main__":
    unittest.main()
