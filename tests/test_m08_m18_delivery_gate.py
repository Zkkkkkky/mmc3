from __future__ import annotations

import unittest

from tools.report_m08_m18_delivery_gate import analyze


class M08M18DeliveryGateTests(unittest.TestCase):
    def test_all_machine_reports_pass_without_claiming_user_acceptance(self) -> None:
        report = analyze()
        self.assertTrue(report["machine_gate_passed"])
        self.assertEqual(report["counts"]["modules"], 11)
        self.assertEqual(report["counts"]["machine_gate_passed"], 11)
        self.assertEqual(report["counts"]["implementation_scope_complete"], 11)
        self.assertEqual(report["counts"]["user_accepted"], 0)
        self.assertTrue(report["implementation_complete"])
        self.assertFalse(report["user_acceptance_complete"])
        self.assertFalse(report["overall_delivery_complete"])
        self.assertEqual(
            report["current_build_verification"]["full_regression_tests"], 647
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
            "implementation_complete_guarded_reference_and_user_pending",
        )
        self.assertTrue(
            all(
                item["user_acceptance"] == "pending"
                for item in report["modules"].values()
            )
        )


if __name__ == "__main__":
    unittest.main()
