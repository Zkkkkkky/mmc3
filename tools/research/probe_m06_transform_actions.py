"""Probe add/clear actions in the legacy M06 transform-dialogue group without saving."""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path

import win32gui
import win32process

REPO = Path(__file__).resolve().parents[2]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from tools.golden_pipeline_collect import Win32LegacyDriver
from tools.research.probe_m06_transform_dialogue import controls


AUDIT = REPO / "output" / "build" / "legacy-diff-audit"
ROOT = REPO / "output" / "verification" / "legacy-ui-probe-m06-transform-actions-20260920"
OUTPUT = ROOT / "M06_变形起飞添加清空.json"


def windows_for_pid(pid: int) -> list[dict[str, object]]:
    result: list[dict[str, object]] = []

    def visit(hwnd: int, _extra: object) -> bool:
        _, owner_pid = win32process.GetWindowThreadProcessId(hwnd)
        if owner_pid == pid and win32gui.IsWindowVisible(hwnd):
            result.append(
                {
                    "title": win32gui.GetWindowText(hwnd),
                    "class": win32gui.GetClassName(hwnd),
                    "rect": list(win32gui.GetWindowRect(hwnd)),
                    "controls": controls(hwnd),
                }
            )
        return True

    win32gui.EnumWindows(visit, None)
    return result


def run_action(action: str) -> dict[str, object]:
    driver = Win32LegacyDriver()
    try:
        pid = driver.launch(AUDIT / "SRW2_patched.exe", AUDIT)
        driver.open_rom(AUDIT / "m05-reference-baseline.nes")
        driver.perform(
            (
                {"op": "menu", "path": "数据->数据库"},
                {"op": "window", "title": "数据库"},
                {"op": "click_coords", "x": 130, "y": 73},
                {"op": "list_select", "class": "ListBox", "control_id": 630, "row": 5},
            ),
            0,
        )
        selector = driver._control(1540, "ComboBox")
        before = {
            "selected_index": int(selector.selected_index()),
            "item_texts": list(selector.item_texts()),
        }
        if action == "add":
            driver.perform(
                (
                    {
                        "op": "select_index_message",
                        "class": "ComboBox",
                        "control_id": 1540,
                        "value": len(before["item_texts"]) - 1,
                    },
                ),
                0,
            )
        elif action == "clear":
            driver.perform(
                (
                    {
                        "op": "select_index_message",
                        "class": "ComboBox",
                        "control_id": 1540,
                        "value": 1,
                    },
                    {"op": "click_id", "class": "Button", "control_id": 2180},
                ),
                0,
            )
        else:
            raise ValueError(action)
        time.sleep(0.8)
        selector_after = driver._control(1540, "ComboBox")
        after = {
            "selected_index": int(selector_after.selected_index()),
            "item_texts": list(selector_after.item_texts()),
            "edit_button_text": driver._control(1530, "Button").window_text(),
        }
        return {
            "pid": pid,
            "before": before,
            "after": after,
            "windows_after": windows_for_pid(pid),
        }
    finally:
        driver.stop()


def main() -> int:
    ROOT.mkdir(parents=True, exist_ok=True)
    payload = {"add": run_action("add"), "clear": run_action("clear")}
    OUTPUT.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(OUTPUT)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
