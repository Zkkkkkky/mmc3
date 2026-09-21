"""Enumerate the legacy M06 transform-dialogue editor without saving."""

from __future__ import annotations

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
ROOT = REPO / "output" / "verification" / "legacy-ui-probe-m06-transform-20260920"
OUTPUT = ROOT / "M06_变形起飞对话.json"


def controls(hwnd: int) -> list[dict[str, object]]:
    result: list[dict[str, object]] = []

    def visit(child: int, _extra: object) -> bool:
        result.append(
            {
                "class": win32gui.GetClassName(child),
                "text": win32gui.GetWindowText(child),
                "control_id": int(win32gui.GetDlgCtrlID(child)),
                "rect": list(win32gui.GetWindowRect(child)),
                "visible": bool(win32gui.IsWindowVisible(child)),
                "enabled": bool(win32gui.IsWindowEnabled(child)),
            }
        )
        return True

    win32gui.EnumChildWindows(hwnd, visit, None)
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
                {"op": "list_select", "class": "ListBox", "control_id": 630, "row": 5},
            ),
            0,
        )
        database = driver.current_window
        assert database is not None
        selector = driver._control(1540, "ComboBox")
        selector_state = {
            "selected_index": int(selector.selected_index()),
            "item_texts": list(selector.item_texts()),
        }
        edit_text = driver._control(1530, "Button").window_text()
        ROOT.mkdir(parents=True, exist_ok=True)
        bindings: list[dict[str, object]] = []
        for binding_index, binding_text in enumerate(selector_state["item_texts"]):
            if binding_text == "添加":
                continue
            driver.current_window = database
            driver.perform(
                (
                    {
                        "op": "select_index_message",
                        "class": "ComboBox",
                        "control_id": 1540,
                        "value": binding_index,
                    },
                    {"op": "click_id", "class": "Button", "control_id": 1530},
                ),
                0,
            )
            modal = driver._wait_window(
                lambda window: window.class_name() == "WTWindow"
                and int(window.handle) != int(database.handle)
                and window.window_text() not in {"", "数据库"}
            )
            driver.current_window = modal
            payload_controls = controls(int(modal.handle))
            control_state: dict[str, object] = {}
            for child in payload_controls:
                if not child["visible"] or child["class"] not in {"ComboBox", "ListBox"}:
                    continue
                try:
                    control = driver._control(
                        int(child["control_id"]), str(child["class"])
                    )
                except RuntimeError as error:
                    control_state[str(child["control_id"])] = {
                        "class": child["class"],
                        "error": str(error),
                    }
                    continue
                try:
                    selected = int(control.selected_index())
                except Exception:
                    selected = None
                try:
                    items = list(control.item_texts())
                except Exception:
                    items = []
                control_state[str(child["control_id"])] = {
                    "class": child["class"],
                    "selected_index": selected,
                    "item_texts": items,
                }
            left, top, right, bottom = win32gui.GetWindowRect(int(modal.handle))
            shot = ROOT / f"M06_变形起飞对话_{binding_index + 1}.png"
            ImageGrab.grab(bbox=(left, top, right, bottom)).save(shot)
            bindings.append(
                {
                    "selector_index": binding_index,
                    "selector_text": binding_text,
                    "title": modal.window_text(),
                    "controls": payload_controls,
                    "control_state": control_state,
                    "screenshot": shot.relative_to(REPO).as_posix(),
                }
            )
            driver.perform(
                (
                    {"op": "click_id", "class": "Button", "control_id": 100},
                    {"op": "window", "title": "数据库", "settle_seconds": 0.2},
                ),
                0,
            )
        OUTPUT.write_text(
            json.dumps(
                {
                    "pid": pid,
                    "character_row": 5,
                    "database_selector": selector_state,
                    "database_edit_text": edit_text,
                    "bindings": bindings,
                },
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
