from __future__ import annotations

import unittest

from tools.report_m12_reference_field_coverage import build


class M12ReferenceFieldCoverageTests(unittest.TestCase):
    def test_full_reference_scope_is_classified_and_guarded(self) -> None:
        report = build()
        self.assertTrue(report["passed"])
        self.assertEqual(report["logical_fields"], 1281)
        self.assertEqual(report["safe_denominator_fields"], 198)
        self.assertEqual(report["classification_counts"], {
            "no_effect": 894,
            "reference_persistent_product_blocked": 189,
            "safe_persistent": 198,
        })
        self.assertTrue(all(report["checks"].values()))


if __name__ == "__main__":
    unittest.main()
