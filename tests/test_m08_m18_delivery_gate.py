from __future__ import annotations

import unittest
from unittest.mock import patch

from tools import report_m08_m18_delivery_gate as delivery_gate


class M08M18DeliveryGateTests(unittest.TestCase):
    def test_machine_reports_and_all_current_scopes_have_user_acceptance(self) -> None:
        report = delivery_gate.analyze()
        self.assertTrue(report["machine_gate_passed"])
        self.assertEqual(report["counts"]["modules"], 11)
        self.assertEqual(report["counts"]["machine_gate_passed"], 11)
        self.assertEqual(report["counts"]["implementation_scope_complete"], 11)
        self.assertEqual(report["counts"]["user_accepted"], 11)
        self.assertTrue(report["implementation_complete"])
        self.assertTrue(report["user_acceptance_complete"])
        self.assertTrue(report["overall_delivery_complete"])
        self.assertEqual(
            report["current_build_verification"]["full_regression_tests"], 746
        )
        self.assertTrue(
            report["current_build_verification"]["full_regression_passed"]
        )
        self.assertEqual(
            report["current_build_verification"]["self_test_exit_code"], 0
        )
        self.assertFalse(
            report["current_build_verification"][
                "current_build_click_smoke_performed"
            ]
        )
        self.assertTrue(
            report["current_build_verification"]["matches_current_executable"]
        )
        self.assertTrue(
            report["current_build_verification"]["mesen_runtime_passed"]
        )
        self.assertEqual(
            report["current_build_verification"]["mesen_runtime_checks"], 17
        )
        self.assertTrue(report["agent_ui_smoke"]["passed"])
        self.assertFalse(report["agent_ui_smoke"]["matches_current_executable"])
        self.assertIn("已逐项审计", report["blocking_reasons"][0])
        self.assertEqual(
            report["modules"]["M12"]["status"],
            "user_accepted_guarded_scope",
        )
        self.assertEqual(report["modules"]["M18"]["user_acceptance"], "accepted")
        self.assertTrue(
            all(
                item["user_acceptance"] == "accepted"
                for item in report["modules"].values()
            )
        )
        self.assertTrue(
            all(
                item["checklist_declares_current_executable"]
                for item in report["modules"].values()
            )
        )

    def test_missing_checklist_fails_gate_without_crashing(self) -> None:
        declaration = dict(delivery_gate.MODULES["M08"])
        declaration["checklist"] = "docs/does-not-exist.md"
        with patch.dict(delivery_gate.MODULES, {"M08": declaration}):
            report = delivery_gate.analyze()
        self.assertFalse(report["machine_gate_passed"])
        self.assertFalse(report["modules"]["M08"]["checklist_exists"])
        self.assertFalse(
            report["modules"]["M08"]["checklist_declares_current_executable"]
        )


if __name__ == "__main__":
    unittest.main()
