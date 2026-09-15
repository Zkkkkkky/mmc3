"""M00 live-collection orchestration tests without starting a GUI."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from typing import Any
from unittest.mock import Mock, patch

from tools import golden_pipeline_collect as collector
from tools import golden_pipeline_core as core


def case_payload() -> dict[str, Any]:
    return {
        "module": "M17",
        "field": "hit_threshold",
        "case_id": "cold_start_01",
        "requested_value": 71,
        "expected_before": 70,
        "expected_offsets": [10],
        "required_offsets": [10],
        "optional_offsets": [],
        "extra_allowed": [],
        "navigation": [{"op": "window", "title": "其他"}],
        "edit_steps": [{"op": "set_text", "control_id": 830, "value": "$requested"}],
        "read_selector": {"class": "Edit", "control_id": 830, "value_type": "int"},
    }


class FakeDriver:
    next_pid = 4000
    launched: list[int] = []
    stopped: list[int] = []
    unexpected_write = False
    stale_reopen = False

    def __init__(self) -> None:
        self.pid: int | None = None
        self.rom: Path | None = None
        self.requested: int | None = None

    def launch(self, executable: Path, work_dir: Path) -> int:
        self.pid = FakeDriver.next_pid
        FakeDriver.next_pid += 1
        FakeDriver.launched.append(self.pid)
        return self.pid

    def open_rom(self, rom_path: Path) -> None:
        self.rom = rom_path

    def perform(self, steps: tuple[dict[str, Any], ...], requested: int | str) -> None:
        if any(step["op"] == "set_text" for step in steps):
            self.requested = int(requested)

    def read(self, selector: dict[str, Any]) -> int:
        assert self.rom is not None
        if FakeDriver.stale_reopen and self.pid == FakeDriver.launched[-1] and len(FakeDriver.launched) == 2:
            return 70
        return self.rom.read_bytes()[10]

    def save(self) -> None:
        assert self.rom is not None and self.requested is not None
        data = bytearray(self.rom.read_bytes())
        data[10] = self.requested
        if FakeDriver.unexpected_write:
            data[11] = 9
        self.rom.write_bytes(data)

    def stop(self) -> None:
        if self.pid is not None:
            FakeDriver.stopped.append(self.pid)


class LiveCollectionTests(unittest.TestCase):
    def setUp(self) -> None:
        FakeDriver.next_pid = 4000
        FakeDriver.launched = []
        FakeDriver.stopped = []
        FakeDriver.unexpected_write = False
        FakeDriver.stale_reopen = False
        self.temp = tempfile.TemporaryDirectory()
        self.repo = Path(self.temp.name)
        self.audit = self.repo / core.AUDIT_DIR_RELATIVE
        self.audit.mkdir(parents=True)
        self.baseline = self.audit / "audit.nes"
        self.baseline.write_bytes(bytes([0] * 10 + [70] + [0] * 10))
        self.exe = self.audit / "SRW2_patched.exe"
        self.exe.write_bytes(b"test-double")

    def tearDown(self) -> None:
        self.temp.cleanup()

    def collect(self, payload: dict[str, Any] | None = None) -> tuple[Path, dict[str, Any]]:
        return collector.collect_case(
            self.repo,
            collector.CaseSpec.from_payload(payload or case_payload()),
            self.baseline,
            self.exe,
            FakeDriver,
        )

    def test_full_closure_uses_two_processes_and_persists_four_elements(self) -> None:
        run_dir, report = self.collect()
        self.assertTrue(report["passed"])
        self.assertEqual(FakeDriver.launched, [4000, 4001])
        self.assertEqual(FakeDriver.stopped, [4000, 4001])
        self.assertEqual(report["reopen_mode"], "new_process")
        self.assertEqual(report["requested_value"], 71)
        self.assertEqual(report["changed_offsets"], [10])
        self.assertEqual(report["removed_normalization"], [])
        self.assertEqual(report["reopen_value"], 71)
        self.assertTrue(report["within_budget"])
        self.assertEqual((run_dir / "before.nes").read_bytes()[10], 70)
        self.assertEqual((run_dir / "after.nes").read_bytes()[10], 71)
        saved = json.loads((run_dir / "case.json").read_text(encoding="utf-8"))
        self.assertEqual(saved, report)
        indexed = json.loads((self.repo / collector.LIVE_RESULTS_RELATIVE).read_text(encoding="utf-8"))
        self.assertEqual(indexed, [report])
        adapted = core._adapt_live(indexed)
        self.assertEqual(adapted[0].snapshot_dir, run_dir.relative_to(self.repo).as_posix())
        self.assertEqual(adapted[0].reopen_mode, "new_process")

    def test_unexpected_offset_cannot_pass(self) -> None:
        FakeDriver.unexpected_write = True
        _, report = self.collect()
        self.assertFalse(report["passed"])
        self.assertEqual(report["unexpected_offsets"], [11])

    def test_stale_reopen_cannot_pass(self) -> None:
        FakeDriver.stale_reopen = True
        _, report = self.collect()
        self.assertFalse(report["passed"])
        self.assertFalse(report["reopen_matches_request"])

    def test_over_budget_cannot_pass_even_when_diff_and_reopen_match(self) -> None:
        _, report = collector.collect_case(
            self.repo,
            collector.CaseSpec.from_payload(case_payload()),
            self.baseline,
            self.exe,
            FakeDriver,
            budget_seconds=0.000000001,
        )
        self.assertFalse(report["passed"])
        self.assertFalse(report["within_budget"])
        self.assertEqual(report["unexpected_offsets"], [])
        self.assertTrue(report["reopen_matches_request"])

    def test_case_is_never_overwritten(self) -> None:
        self.collect()
        with self.assertRaises(FileExistsError):
            self.collect()

    def test_reference_executable_is_rejected(self) -> None:
        reference = self.repo / "references" / "legacy_modifier" / "SRW2_patched.exe"
        reference.parent.mkdir(parents=True)
        reference.write_bytes(b"immutable")
        with self.assertRaises(ValueError):
            collector.collect_case(
                self.repo,
                collector.CaseSpec.from_payload(case_payload()),
                self.baseline,
                reference,
                FakeDriver,
            )
        self.assertFalse((self.repo / collector.LIVE_CASES_RELATIVE).exists())

    def test_invalid_operation_and_offset_partition_are_rejected(self) -> None:
        payload = case_payload()
        payload["edit_steps"] = [{"op": "python", "source": "arbitrary"}]
        with self.assertRaises(ValueError):
            collector.CaseSpec.from_payload(payload)
        payload = case_payload()
        payload["optional_offsets"] = [10]
        with self.assertRaises(ValueError):
            collector.CaseSpec.from_payload(payload)

    def test_list_row_navigation_is_configurable_but_rejects_bad_indices(self) -> None:
        payload = case_payload()
        payload["navigation"] = [
            {"op": "list_double_click", "control_id": 400, "row": 0, "column": 2}
        ]
        spec = collector.CaseSpec.from_payload(payload)
        self.assertEqual(spec.navigation[0]["op"], "list_double_click")
        payload["navigation"][0]["row"] = -1
        with self.assertRaises(ValueError):
            collector.CaseSpec.from_payload(payload)

    def test_win32_adapter_waits_for_disk_save_and_process_exit(self) -> None:
        driver = collector.Win32LegacyDriver()
        driver.app = Mock()
        driver.app.windows.return_value = []
        driver.pid = 9001
        driver.current_rom = self.baseline

        def save_to_disk(_: str) -> None:
            self.baseline.write_bytes(bytes([0] * 10 + [71] + [0] * 10))

        main = Mock()
        main.menu_select.side_effect = save_to_disk
        with patch.object(driver, "_main", return_value=main):
            driver.save()
        app = driver.app
        driver.stop()
        main.menu_select.assert_called_once_with("文件->保存")
        app.wait_for_process_exit.assert_called_once_with(timeout=5)
        self.assertIsNone(driver.app)
        self.assertIsNone(driver.pid)

    def test_win32_adapter_rejects_unconfirmed_process_exit(self) -> None:
        driver = collector.Win32LegacyDriver()
        app = Mock()
        app.wait_for_process_exit.side_effect = TimeoutError("still running")
        driver.app = app
        driver.pid = 9001
        with self.assertRaisesRegex(RuntimeError, "did not exit"):
            driver.stop()


if __name__ == "__main__":
    unittest.main()
