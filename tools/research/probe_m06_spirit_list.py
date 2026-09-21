"""Enumerate the legacy M06 owner-drawn spirit list without saving the ROM."""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path

import win32con
import win32gui
import win32process
from PIL import ImageChops, ImageGrab

REPO = Path(__file__).resolve().parents[2]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from tools.golden_pipeline_collect import Win32LegacyDriver


AUDIT = REPO / "output" / "build" / "legacy-diff-audit"
OUTPUT = (
    REPO
    / "output"
    / "verification"
    / "legacy-ui-probe-m06-spirit-20260920"
    / "controls"
    / "M06_数据库_人物修改_精神列表交互.json"
)


def list_state(listbox: object) -> dict[str, object]:
    hwnd = int(listbox.handle)
    count = int(win32gui.SendMessage(hwnd, 0x018B, 0, 0))  # LB_GETCOUNT
    return {
        "count": count,
        "selected_index": int(win32gui.SendMessage(hwnd, 0x0188, 0, 0)),
        "item_texts": list(listbox.item_texts()),
        "item_data": [
            int(win32gui.SendMessage(hwnd, 0x0199, index, 0))  # LB_GETITEMDATA
            for index in range(count)
        ],
        "style": int(win32gui.GetWindowLong(hwnd, win32con.GWL_STYLE)),
    }


def window_inventory(pid: int) -> list[dict[str, object]]:
    windows: list[dict[str, object]] = []

    def visit_top(hwnd: int, _extra: object) -> bool:
        _thread_id, process_id = win32process.GetWindowThreadProcessId(hwnd)
        if process_id != pid or not win32gui.IsWindow(hwnd):
            return True
        children: list[dict[str, object]] = []

        def visit_child(child: int, _child_extra: object) -> bool:
            children.append(
                {
                    "hwnd": child,
                    "class": win32gui.GetClassName(child),
                    "text": win32gui.GetWindowText(child),
                    "control_id": int(win32gui.GetDlgCtrlID(child)),
                    "rect": list(win32gui.GetWindowRect(child)),
                    "visible": bool(win32gui.IsWindowVisible(child)),
                    "enabled": bool(win32gui.IsWindowEnabled(child)),
                }
            )
            return True

        win32gui.EnumChildWindows(hwnd, visit_child, None)
        windows.append(
            {
                "hwnd": hwnd,
                "class": win32gui.GetClassName(hwnd),
                "title": win32gui.GetWindowText(hwnd),
                "rect": list(win32gui.GetWindowRect(hwnd)),
                "visible": bool(win32gui.IsWindowVisible(hwnd)),
                "enabled": bool(win32gui.IsWindowEnabled(hwnd)),
                "children": children,
            }
        )
        return True

    win32gui.EnumWindows(visit_top, None)
    return windows


def main() -> int:
    driver = Win32LegacyDriver()
    payload: dict[str, object] = {}
    try:
        pid = driver.launch(AUDIT / "SRW2_patched.exe", AUDIT)
        driver.open_rom(AUDIT / "m05-reference-baseline.nes")
        driver.perform(
            (
                {"op": "menu", "path": "数据->数据库"},
                {"op": "window", "title": "数据库"},
                {"op": "click_coords", "x": 130, "y": 73},
                {"op": "list_select", "class": "ListBox", "control_id": 630, "row": 0},
            ),
            0,
        )
        spirit_list = driver._control(1270, "ListBox")
        image_dir = OUTPUT.parent.parent / "screenshots"
        image_dir.mkdir(parents=True, exist_ok=True)
        control_rect = spirit_list.rectangle()
        rect = (
            int(control_rect.left),
            int(control_rect.top),
            int(control_rect.right),
            int(control_rect.bottom),
        )
        before_image = ImageGrab.grab(bbox=rect)
        before_path = image_dir / "M06_精神列表_点击前.png"
        before_image.save(before_path)
        payload["pid"] = pid
        payload["list_rect"] = list(rect)
        payload["before_image"] = str(before_path.relative_to(REPO)).replace("\\", "/")
        payload["before"] = list_state(spirit_list)
        spirit_list.click_input(coords=(8, 12))
        time.sleep(0.4)
        after_image = ImageGrab.grab(bbox=rect)
        after_path = image_dir / "M06_精神列表_勾选后.png"
        after_image.save(after_path)
        diff_box = ImageChops.difference(before_image, after_image).getbbox()
        payload["after_image"] = str(after_path.relative_to(REPO)).replace("\\", "/")
        payload["single_click_diff_box"] = list(diff_box) if diff_box else None
        payload["after_single_click"] = list_state(spirit_list)
        spirit_list.click_input(coords=(8, 12))
        time.sleep(0.3)
        reverted_image = ImageGrab.grab(bbox=rect)
        reverted_path = image_dir / "M06_精神列表_恢复后.png"
        reverted_image.save(reverted_path)
        payload["reverted_image"] = str(reverted_path.relative_to(REPO)).replace("\\", "/")
        payload["reverted_pixels_equal"] = (
            list(reverted_image.get_flattened_data())
            == list(before_image.get_flattened_data())
        )
        payload["after_revert_click"] = list_state(spirit_list)
        spirit_list.double_click_input(coords=(55, 12))
        time.sleep(0.8)
        payload["after_double_click_windows"] = window_inventory(pid)
        OUTPUT.parent.mkdir(parents=True, exist_ok=True)
        OUTPUT.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        print(OUTPUT)
        return 0
    finally:
        driver.stop()


if __name__ == "__main__":
    raise SystemExit(main())
