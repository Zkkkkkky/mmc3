from __future__ import annotations

from pathlib import Path
import unittest

from tools.report_m09_other1_compatibility import analyze


ROOT = Path(__file__).resolve().parents[1]
ROM = ROOT / "output" / "rom" / "DC_kuorong_464K.nes"
AUDIT_BEFORE = ROOT / "output" / "build" / "legacy-diff-audit" / "audit.nes"
AUDIT_AFTER = (
    ROOT
    / "output"
    / "build"
    / "legacy-diff-audit"
    / "cases"
    / "legacy_level_cap"
    / "after.nes"
)


@unittest.skipUnless(
    ROM.is_file() and AUDIT_BEFORE.is_file() and AUDIT_AFTER.is_file(),
    "需要正式 ROM 与旧等级审计样本",
)
class M09Other1ReportTests(unittest.TestCase):
    def test_report_closes_implementation_scope_without_claiming_acceptance(self) -> None:
        report = analyze(ROM, AUDIT_BEFORE, AUDIT_AFTER)
        self.assertTrue(report["passed"])
        self.assertEqual(
            report["delivery_status"],
            "reference_field_scope_complete_product_compatibility_and_user_pending",
        )
        evidence = report["evidence"]
        self.assertEqual(evidence["distance_hit"]["shape"], [4, 16])
        self.assertEqual(evidence["experience"]["entries"], 99)
        self.assertEqual(evidence["system_text"]["indices"], 221)
        self.assertEqual(
            evidence["system_text"]["no_op_roundtrips"],
            evidence["system_text"]["variants"],
        )
        self.assertEqual(evidence["growth"]["slots"], 53)
        self.assertEqual(evidence["growth"]["unique_records"], 14)
        self.assertEqual(evidence["growth"]["values_per_record"], 99)
        self.assertEqual(evidence["growth"]["record_bytes"], 50)
        self.assertTrue(evidence["level_cap"]["passed"])
        self.assertTrue(evidence["reference_all_fields"]["passed"])
        self.assertEqual(evidence["reference_all_fields"]["saved_fields"], 412)
        self.assertEqual(len(report["pending_acceptance"]), 2)


if __name__ == "__main__":
    unittest.main()
