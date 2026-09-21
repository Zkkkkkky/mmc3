"""Enumerate every reachable legacy M07 weapon control without saving.

The generic inventory contains all lazy-created database controls, including
hidden controls from unrelated pages.  This focused probe records the actual
weapon page, all three owner-drawn animation subpages, and the code editor
dialog while leaving the input ROM untouched.
"""

from __future__ import annotations

import hashlib
import json
import sys
import time
from pathlib import Path

import win32gui
from PIL import ImageGrab

REPO = Path(__file__).resolve().parents[2]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from tools.golden_pipeline_collect import Win32LegacyDriver


AUDIT = REPO / "output" / "build" / "legacy-diff-audit"
ROOT = REPO / "output" / "verification" / "legacy-ui-probe-m07-weapon-20260920"
OUTPUT = ROOT / "M07_武器修改完整控件.json"


def controls(hwnd: int) -> list[dict[str, object]]:
    result: list[dict[str, object]] = []

    def visit(child: int, _extra: object) -> bool:
        item: dict[str, object] = {
            "class": win32gui.GetClassName(child),
            "text": win32gui.GetWindowText(child),
            "control_id": int(win32gui.GetDlgCtrlID(child)),
            "rect": list(win32gui.GetWindowRect(child)),
            "visible": bool(win32gui.IsWindowVisible(child)),
            "enabled": bool(win32gui.IsWindowEnabled(child)),
        }
        if item["class"] in {"ComboBox", "ListBox"}:
            try:
                control = driver._control(
                    int(item["control_id"]), str(item["class"])
                )
            except Exception as error:  # diagnostic evidence, never a write
                item["enumeration_error"] = str(error)
            else:
                try:
                    item["item_texts"] = list(control.item_texts())
                except Exception as error:
                    item["items_error"] = str(error)
                try:
                    if item["class"] == "ComboBox":
                        item["selected_index"] = int(control.selected_index())
                    else:
                        selected = list(control.selected_indices())
                        item["selected_indices"] = [int(value) for value in selected]
                except Exception as error:
                    item["selection_error"] = str(error)
        result.append(item)
        return True

    win32gui.EnumChildWindows(hwnd, visit, None)
    return result


def capture(hwnd: int, stem: str) -> dict[str, object]:
    ROOT.mkdir(parents=True, exist_ok=True)
    left, top, right, bottom = win32gui.GetWindowRect(hwnd)
    shot = ROOT / f"{stem}.png"
    image = ImageGrab.grab(bbox=(left, top, right, bottom))
    image.save(shot)
    return {
        "title": win32gui.GetWindowText(hwnd),
        "screenshot": shot.relative_to(REPO).as_posix(),
        "pixel_sha256": hashlib.sha256(image.tobytes()).hexdigest(),
        "controls": controls(hwnd),
    }


def visible_signature(items: list[dict[str, object]]) -> list[list[object]]:
    return sorted(
        [
            [item["class"], item["control_id"], item["text"]]
            for item in items
            if item["visible"]
        ],
        key=lambda value: (str(value[0]), int(value[1]), str(value[2])),
    )


def click_relative(hwnd: int, x: int, y: int) -> None:
    left, top, _right, _bottom = win32gui.GetWindowRect(hwnd)
    win32gui.SetForegroundWindow(hwnd)
    import win32api
    import win32con

    win32api.SetCursorPos((left + x, top + y))
    win32api.mouse_event(win32con.MOUSEEVENTF_LEFTDOWN, 0, 0)
    win32api.mouse_event(win32con.MOUSEEVENTF_LEFTUP, 0, 0)
    time.sleep(0.35)


def main() -> int:
    global driver
    driver = Win32LegacyDriver()
    before = (AUDIT / "m05-reference-baseline.nes").read_bytes()
    try:
        pid = driver.launch(AUDIT / "SRW2_patched.exe", AUDIT)
        driver.open_rom(AUDIT / "m05-reference-baseline.nes")
        driver.perform(
            (
                {"op": "menu", "path": "数据->数据库"},
                {"op": "window", "title": "数据库"},
                {"op": "click_coords", "x": 220, "y": 73},
                {"op": "list_select", "class": "ListBox", "control_id": 610, "row": 0},
            ),
            0,
        )
        database = driver.current_window
        assert database is not None
        database_hwnd = int(database.handle)

        pages: list[dict[str, object]] = []
        # The legacy CPageControl is owner-drawn and does not expose tab
        # children.  Sweep its header band and retain each distinct visible
        # control state.  Coordinates are relative to the database window.
        for sequence, x in enumerate((385, 490, 625), start=1):
            click_relative(database_hwnd, x, 294)
            snapshot = capture(database_hwnd, f"M07_武器子页_{sequence}")
            signature = visible_signature(snapshot["controls"])
            if any(page["visible_signature"] == signature for page in pages):
                continue
            snapshot["probe_coordinate"] = [x, 294]
            snapshot["visible_signature"] = signature
            pages.append(snapshot)

        driver.current_window = database
        # Select the first animation page before opening its pointer/code
        # editor.  The dialog is observed and cancelled; no field is changed.
        click_relative(database_hwnd, 385, 294)
        driver.perform(
            ({"op": "click_id_message", "class": "Button", "control_id": 2560},),
            0,
        )
        modal = driver._wait_window(
            lambda window: int(window.handle) != database_hwnd
            and window.window_text().startswith("请输入")
        )
        code_dialog = capture(int(modal.handle), "M07_代码编辑弹窗")
        driver.current_window = modal
        try:
            driver.perform(({"op": "click_id", "class": "Button", "control_id": 2},), 0)
        except RuntimeError:
            win32gui.PostMessage(int(modal.handle), 0x0010, 0, 0)
        time.sleep(0.2)

        after = (AUDIT / "m05-reference-baseline.nes").read_bytes()
        driver.current_window = database
        payload = {
            "pid": pid,
            "weapon_row": 0,
            "rom_unchanged": before == after,
            "main_page": capture(database_hwnd, "M07_武器主页面"),
            "distinct_subpages": pages,
            "code_dialog": code_dialog,
        }
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
