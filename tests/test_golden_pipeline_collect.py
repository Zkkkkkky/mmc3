"""M00 live-collection orchestration tests without starting a GUI."""

from __future__ import annotations

import json
import os
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

    def test_caller_cannot_relax_hard_thirty_second_budget(self) -> None:
        with patch.object(collector.time, "perf_counter", side_effect=(0.0, 31.0)):
            _, report = collector.collect_case(
                self.repo,
                collector.CaseSpec.from_payload(case_payload()),
                self.baseline,
                self.exe,
                FakeDriver,
                budget_seconds=90.0,
            )

        self.assertFalse(report["passed"])
        self.assertFalse(report["within_budget"])
        self.assertEqual(report["budget_seconds"], 30.0)
        self.assertEqual(report["requested_budget_seconds"], 90.0)
        self.assertIn("exceeds 30.00s", report["pending_reason"])

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

    def test_listbox_selection_is_whitelisted_but_rejects_bad_row(self) -> None:
        payload = case_payload()
        payload["navigation"] = [
            {"op": "list_select", "class": "ListBox", "control_id": 120, "row": 1}
        ]
        spec = collector.CaseSpec.from_payload(payload)
        self.assertEqual(spec.navigation[0]["row"], 1)
        payload["navigation"][0]["row"] = -1
        with self.assertRaises(ValueError):
            collector.CaseSpec.from_payload(payload)

    def test_control_relative_click_is_whitelisted_and_bounded(self) -> None:
        payload = case_payload()
        payload["navigation"] = [
            {
                "op": "click_control_coords",
                "class": "CPageControl",
                "control_id": 100,
                "x": 140,
                "y": 30,
                "click_count": 2,
                "wait_control_id": 220,
            }
        ]
        spec = collector.CaseSpec.from_payload(payload)
        self.assertEqual(spec.navigation[0]["control_id"], 100)
        self.assertEqual(spec.navigation[0]["click_count"], 2)
        self.assertEqual(spec.navigation[0]["wait_control_id"], 220)
        payload["navigation"][0]["click_count"] = 3
        with self.assertRaises(ValueError):
            collector.CaseSpec.from_payload(payload)
        payload["navigation"][0]["click_count"] = 2
        del payload["navigation"][0]["x"]
        with self.assertRaises(ValueError):
            collector.CaseSpec.from_payload(payload)

    def test_assert_value_is_whitelisted_but_requires_a_value(self) -> None:
        payload = case_payload()
        payload["edit_steps"] = [
            {
                "op": "assert_value",
                "class": "Edit",
                "control_id": 650,
                "value": "$requested",
                "value_type": "int",
            }
        ]
        spec = collector.CaseSpec.from_payload(payload)
        self.assertEqual(spec.edit_steps[0]["value_type"], "int")
        del payload["edit_steps"][0]["value"]
        with self.assertRaises(ValueError):
            collector.CaseSpec.from_payload(payload)

    def test_checkbox_write_and_read_are_whitelisted_and_bounded(self) -> None:
        payload = case_payload()
        payload["requested_value"] = 1
        payload["expected_before"] = 0
        payload["edit_steps"] = [
            {
                "op": "set_check",
                "class": "Button",
                "control_id": 130,
                "value": "$requested",
            }
        ]
        payload["read_selector"] = {
            "class": "Button",
            "control_id": 130,
            "value_type": "check",
        }
        spec = collector.CaseSpec.from_payload(payload)
        self.assertEqual(spec.edit_steps[0]["op"], "set_check")
        self.assertEqual(spec.read_selector["value_type"], "check")
        payload["edit_steps"][0]["value"] = 2
        with self.assertRaises(ValueError):
            collector.CaseSpec.from_payload(payload)

    def test_combo_index_can_be_read_as_an_integer(self) -> None:
        payload = case_payload()
        payload["requested_value"] = 2
        payload["expected_before"] = 1
        payload["edit_steps"] = [
            {
                "op": "select_index",
                "class": "ComboBox",
                "control_id": 100,
                "value": "$requested",
            }
        ]
        payload["read_selector"] = {
            "class": "ComboBox",
            "control_id": 100,
            "value_type": "combo_index",
        }
        spec = collector.CaseSpec.from_payload(payload)
        self.assertEqual(spec.read_selector["value_type"], "combo_index")

    def test_combo_item_count_and_separate_reopen_navigation_are_supported(self) -> None:
        payload = case_payload()
        payload["requested_value"] = 4
        payload["expected_before"] = 3
        payload["read_navigation"] = [{"op": "window", "title": "数据库"}]
        payload["edit_steps"] = [
            {
                "op": "select_index_message",
                "class": "ComboBox",
                "control_id": 1540,
                "value": 2,
            }
        ]
        payload["read_selector"] = {
            "class": "ComboBox",
            "control_id": 1540,
            "value_type": "combo_item_count",
        }
        spec = collector.CaseSpec.from_payload(payload)
        self.assertEqual(spec.read_navigation[0]["title"], "数据库")
        self.assertEqual(spec.read_selector["value_type"], "combo_item_count")

    def test_control_pixel_hash_is_a_string_selector(self) -> None:
        payload = case_payload()
        payload["requested_value"] = "a" * 64
        payload["expected_before"] = "b" * 64
        payload["read_selector"] = {
            "class": "_EL_PicBox",
            "control_id": 1360,
            "value_type": "control_pixel_sha256",
        }
        spec = collector.CaseSpec.from_payload(payload)
        self.assertEqual(spec.read_selector["value_type"], "control_pixel_sha256")

    def test_list_item_count_is_an_integer_selector(self) -> None:
        payload = case_payload()
        payload["requested_value"] = 201
        payload["expected_before"] = 200
        payload["read_selector"] = {
            "class": "ListBox",
            "control_id": 630,
            "value_type": "list_item_count",
        }
        spec = collector.CaseSpec.from_payload(payload)
        self.assertEqual(spec.read_selector["value_type"], "list_item_count")

    def test_list_item_text_is_a_string_selector(self) -> None:
        payload = case_payload()
        payload["requested_value"] = "001：等待：001帧"
        payload["expected_before"] = "000：动画结束"
        payload["read_selector"] = {
            "class": "ListBox",
            "control_id": 2530,
            "value_type": "list_item_text",
            "item_index": 0,
        }
        spec = collector.CaseSpec.from_payload(payload)
        self.assertEqual(spec.read_selector["value_type"], "list_item_text")

        payload["read_selector"]["item_index"] = -1
        with self.assertRaisesRegex(ValueError, "nonnegative item_index"):
            collector.CaseSpec.from_payload(payload)

    def test_keyboard_combo_selection_is_whitelisted(self) -> None:
        payload = case_payload()
        payload["requested_value"] = 1
        payload["expected_before"] = 0
        payload["edit_steps"] = [
            {
                "op": "select_index_keyboard",
                "class": "ComboBox",
                "control_id": 120,
                "value": "$requested",
            }
        ]
        payload["read_selector"] = {
            "class": "ComboBox",
            "control_id": 120,
            "value_type": "combo_index",
        }
        spec = collector.CaseSpec.from_payload(payload)
        self.assertEqual(spec.edit_steps[0]["op"], "select_index_keyboard")

    def test_message_combo_selection_is_whitelisted(self) -> None:
        payload = case_payload()
        payload["requested_value"] = 1
        payload["expected_before"] = 0
        payload["edit_steps"] = [
            {
                "op": "select_index_message",
                "class": "ComboBox",
                "control_id": 120,
                "value": "$requested",
            }
        ]
        payload["read_selector"] = {
            "class": "ComboBox",
            "control_id": 120,
            "value_type": "combo_index",
        }
        spec = collector.CaseSpec.from_payload(payload)
        self.assertEqual(spec.edit_steps[0]["op"], "select_index_message")

    def test_click_combo_selection_is_whitelisted(self) -> None:
        payload = case_payload()
        payload["requested_value"] = 1
        payload["expected_before"] = 0
        payload["edit_steps"] = [
            {
                "op": "select_index_click",
                "class": "ComboBox",
                "control_id": 120,
                "value": "$requested",
            }
        ]
        payload["read_selector"] = {
            "class": "ComboBox",
            "control_id": 120,
            "value_type": "combo_index",
        }
        spec = collector.CaseSpec.from_payload(payload)
        self.assertEqual(spec.edit_steps[0]["op"], "select_index_click")

    def test_owner_drawn_spirit_checkbox_selector_and_pixel_reader(self) -> None:
        from PIL import Image, ImageDraw

        payload = case_payload()
        payload["requested_value"] = 1
        payload["expected_before"] = 0
        payload["read_selector"] = {
            "class": "ListBox",
            "control_id": 1270,
            "value_type": "checkbox_pixel",
            "item_index": 0,
        }
        spec = collector.CaseSpec.from_payload(payload)
        self.assertEqual(spec.read_selector["item_index"], 0)
        blank = Image.new("RGB", (460, 170), "white")
        checked = blank.copy()
        ImageDraw.Draw(checked).line((5, 7, 11, 12), fill="black", width=2)
        self.assertEqual(collector._owner_drawn_spirit_checkbox_state(blank, 0), 0)
        self.assertEqual(collector._owner_drawn_spirit_checkbox_state(checked, 0), 1)
        lower_checked = blank.copy()
        ImageDraw.Draw(lower_checked).line((312, 154, 318, 159), fill="black", width=2)
        self.assertEqual(collector._owner_drawn_spirit_checkbox_state(lower_checked, 23), 1)
        payload["read_selector"]["item_index"] = 24
        with self.assertRaises(ValueError):
            collector.CaseSpec.from_payload(payload)

    def test_notified_text_write_is_whitelisted(self) -> None:
        payload = case_payload()
        payload["edit_steps"] = [
            {
                "op": "set_text_notify",
                "class": "Edit",
                "control_id": 250,
                "value": "$requested",
            }
        ]
        spec = collector.CaseSpec.from_payload(payload)
        self.assertEqual(spec.edit_steps[0]["op"], "set_text_notify")

    def test_real_control_click_is_whitelisted(self) -> None:
        payload = case_payload()
        payload["edit_steps"] = [
            {
                "op": "click_id_input",
                "class": "_EL_Label",
                "control_id": 280,
            }
        ]
        spec = collector.CaseSpec.from_payload(payload)
        self.assertEqual(spec.edit_steps[0]["op"], "click_id_input")

    def test_message_control_click_is_whitelisted(self) -> None:
        payload = case_payload()
        payload["edit_steps"] = [
            {"op": "click_id_message", "class": "Button", "control_id": 7}
        ]
        spec = collector.CaseSpec.from_payload(payload)
        self.assertEqual(spec.edit_steps[0]["op"], "click_id_message")

    def test_named_extra_allowed_profile_expands_ranges(self) -> None:
        payload = case_payload()
        payload["extra_allowed_profile"] = "m05_appearance_normalization_v1"
        spec = collector.CaseSpec.from_payload(payload)
        self.assertEqual(spec.extra_allowed_profile, "m05_appearance_normalization_v1")
        self.assertEqual(len(spec.extra_allowed), 1584)
        self.assertIn(33457, spec.extra_allowed)
        self.assertIn(47158, spec.extra_allowed)

    def test_discovery_case_allows_empty_expected_offsets(self) -> None:
        payload = case_payload()
        payload["case_kind"] = "discovery"
        payload["expected_offsets"] = []
        payload["required_offsets"] = []
        spec = collector.CaseSpec.from_payload(payload)
        self.assertEqual(spec.case_kind, "discovery")
        self.assertEqual(spec.expected_offsets, ())

    def test_hash_pinned_source_profile_expands_discovery_offsets(self) -> None:
        payload = case_payload()
        payload["extra_allowed_profile"] = "m05_unit_type_0_to_1_v1"
        spec = collector.CaseSpec.from_payload(payload)
        self.assertEqual(len(spec.extra_allowed), 14065)
        self.assertNotIn(33457, spec.extra_allowed)
        self.assertIn(45164, spec.extra_allowed)

    def test_real_keyboard_text_write_is_whitelisted(self) -> None:
        payload = case_payload()
        payload["edit_steps"] = [
            {
                "op": "type_text",
                "class": "Edit",
                "control_id": 250,
                "value": "$requested",
            }
        ]
        spec = collector.CaseSpec.from_payload(payload)
        self.assertEqual(spec.edit_steps[0]["op"], "type_text")

    def test_win32_adapter_waits_for_disk_save_and_process_exit(self) -> None:
        driver = collector.Win32LegacyDriver()
        driver.app = Mock()
        driver.app.windows.return_value = []
        driver.pid = 9001
        driver.current_rom = self.baseline
        previous_mtime = self.baseline.stat().st_mtime_ns

        def save_to_disk(_window: object, _path: str) -> None:
            self.baseline.write_bytes(bytes([0] * 10 + [71] + [0] * 10))
            os.utime(self.baseline, ns=(previous_mtime, previous_mtime))

        main = Mock()
        with patch.object(driver, "_main", return_value=main), patch.object(
            driver, "_menu_command", side_effect=save_to_disk
        ) as menu_command:
            driver.save()
        with patch("win32api.OpenProcess", return_value=123) as open_process, patch(
            "win32api.TerminateProcess"
        ) as terminate_process, patch(
            "win32event.WaitForSingleObject", return_value=0
        ) as wait_for_exit, patch("win32api.CloseHandle") as close_handle:
            driver.stop()
        menu_command.assert_called_once_with(main, "文件->保存")
        open_process.assert_called_once()
        terminate_process.assert_called_once_with(123, 0)
        wait_for_exit.assert_called_once_with(123, 5000)
        close_handle.assert_called_once_with(123)
        self.assertIsNone(driver.app)
        self.assertIsNone(driver.pid)

    def test_win32_adapter_rejects_unconfirmed_process_exit(self) -> None:
        driver = collector.Win32LegacyDriver()
        app = Mock()
        driver.app = app
        driver.pid = 9001
        with patch("win32api.OpenProcess", return_value=123), patch(
            "win32api.TerminateProcess"
        ), patch("win32event.WaitForSingleObject", return_value=258), patch(
            "win32api.CloseHandle"
        ):
            with self.assertRaisesRegex(RuntimeError, "did not exit"):
                driver.stop()

    def test_map_animation_menu_is_a_whitelisted_legacy_command(self) -> None:
        self.assertEqual(collector.LEGACY_MENU_COMMANDS["数据->地图动画"], 20011)


if __name__ == "__main__":
    unittest.main()
