"""Enumerate one legacy M06 direct-dialogue editor without saving the ROM."""

from __future__ import annotations

import json
import re
import sys
import time
from pathlib import Path

import win32gui
import win32process
from PIL import ImageGrab

REPO = Path(__file__).resolve().parents[2]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from tools.golden_pipeline_collect import Win32LegacyDriver


AUDIT = REPO / "output" / "build" / "legacy-diff-audit"
ROOT = REPO / "output" / "verification" / "legacy-ui-probe-m06-dialogue-20260920"
OUTPUT = ROOT / "controls" / "M06_数据库_人物修改_攻击命中对话窗口.json"


def inventory(pid: int) -> list[dict[str, object]]:
    result: list[dict[str, object]] = []

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
        result.append(
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
    return result


def main() -> int:
    driver = Win32LegacyDriver()
    try:
        pid = driver.launch(AUDIT / "SRW2_patched.exe", AUDIT)
        driver.open_rom(AUDIT / "m05-reference-baseline.nes")
        driver.perform(
            (
                {"op": "menu", "path": "数据->数据库"},
                {"op": "window", "title": "数据库"},
                {"op": "click_coords", "x": 130, "y": 73},
                {"op": "list_select", "class": "ListBox", "control_id": 630, "row": 0},
                {"op": "click_id", "class": "Button", "control_id": 1450},
            ),
            0,
        )
        time.sleep(0.8)
        modal = driver._wait_window(lambda window: window.window_text() == "防御对话")
        driver.current_window = modal
        combo_state: dict[str, object] = {}
        for control_id in (120, 130):
            combo = driver._control(control_id, "ComboBox")
            combo_state[str(control_id)] = {
                "selected_index": int(combo.selected_index()),
                "item_texts": list(combo.item_texts()),
            }
        windows = inventory(pid)
        visible = [item for item in windows if item["visible"]]
        shots = ROOT / "screenshots"
        shots.mkdir(parents=True, exist_ok=True)
        for index, item in enumerate(visible, 1):
            left, top, right, bottom = item["rect"]
            if right > left and bottom > top:
                title = re.sub(r'[<>:"/\\|?*]+', "_", str(item["title"] or "untitled"))
                path = shots / f"M06_攻击命中_{index}_{title[:80]}.png"
                ImageGrab.grab(bbox=(left, top, right, bottom)).save(path)
                item["screenshot"] = str(path.relative_to(REPO)).replace("\\", "/")
        OUTPUT.parent.mkdir(parents=True, exist_ok=True)
        OUTPUT.write_text(
            json.dumps(
                {"pid": pid, "combo_state": combo_state, "windows": windows},
                ensure_ascii=False,
                indent=2,
            ) + "\n",
            encoding="utf-8",
        )
        print(OUTPUT)
        return 0
    finally:
        driver.stop()


if __name__ == "__main__":
    raise SystemExit(main())
