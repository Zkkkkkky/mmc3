from __future__ import annotations

import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PIPELINE = ROOT / "tools" / "run_remaining_reference_pipeline.ps1"
WATCHDOGS = (
    ROOT / "tools" / "run_m14_reference_watchdog.ps1",
    ROOT / "tools" / "run_reference_collector_watchdog.ps1",
)


class RemainingReferencePipelineTests(unittest.TestCase):
    def test_watchdogs_run_as_waited_children_in_required_order(self) -> None:
        source = PIPELINE.read_text(encoding="utf-8")

        for token in (
            "function Invoke-Watchdog",
            "Start-Process",
            "-WindowStyle Hidden",
            "-Wait",
            "-PassThru",
            "$process.ExitCode -ne 0",
        ):
            self.assertIn(token, source)

        m14 = source.index("run_m14_reference_watchdog.ps1")
        m03 = source.index("collect_m03_all_reference_fields.py")
        m04 = source.index("collect_m04_all_reference_fields.py")
        report_m14 = source.index("report_m14_reference_save_coverage.py")
        report_m03 = source.index("report_m03_reference_save_coverage.py")
        report_m04 = source.index("report_m04_reference_save_coverage.py")
        self.assertLess(m14, m03)
        self.assertLess(m03, m04)
        self.assertLess(m04, report_m14)
        self.assertLess(report_m14, report_m03)
        self.assertLess(report_m03, report_m04)

    def test_stall_restart_is_not_counted_again_as_a_normal_exit(self) -> None:
        for path in WATCHDOGS:
            source = path.read_text(encoding="utf-8").lower()
            self.assertIn("$restartrequested = $false", source, path.name)
            self.assertIn("$restartrequested = $true", source, path.name)
            self.assertIn("if ($restartrequested) { continue }", source, path.name)

    def test_generic_watchdog_allows_bounded_final_inventory_startup(self) -> None:
        source = WATCHDOGS[1].read_text(encoding="utf-8").lower()
        self.assertIn("$before -eq $expectedtotal", source)
        self.assertIn("{ 240 } else { 60 }", source)
        self.assertIn("-ge $stallseconds", source)
        self.assertIn("-redirectstandardoutput", source)
        self.assertIn("-redirectstandarderror", source)
        self.assertIn("watchdog-attempt-$attemptstamp.error.log", source)
        self.assertIn("$child.waitforexit()", source)
        self.assertIn("function read-summarypassed", source)
        self.assertIn("$collectorsucceeded", source)


if __name__ == "__main__":
    unittest.main()
