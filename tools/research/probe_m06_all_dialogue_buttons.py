"""Enumerate every M06 dialogue button and modal without saving the ROM."""

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
ROOT = REPO / "output" / "verification" / "legacy-ui-probe-m06-dialogue-all-20260920"
OUTPUT = ROOT / "M06_人物对话全部按钮.json"
BUTTONS = (
    (1420, "攻击特殊1"),
    (1430, "攻击特殊2"),
    (1440, "攻击特殊3"),
    (1450, "攻击命中"),
    (1460, "攻击被阻断"),
    (1470, "防御无反击命中"),
    (1480, "防御无反击回避"),
    (1490, "防御反击命中"),
    (1500, "防御反击回避"),
    (1510, "防御重伤"),
    (1520, "防御击落"),
)


def _modal(pid: int, excluded: set[int]) -> int:
    candidates: list[int] = []

    def visit(hwnd: int, _extra: object) -> bool:
        _thread_id, process_id = win32process.GetWindowThreadProcessId(hwnd)
        if (
            process_id == pid
            and hwnd not in excluded
            and win32gui.IsWindowVisible(hwnd)
            and win32gui.GetClassName(hwnd) == "WTWindow"
        ):
            candidates.append(hwnd)
        return True

    deadline = time.monotonic() + 8.0
    while time.monotonic() < deadline:
        candidates.clear()
        win32gui.EnumWindows(visit, None)
        if candidates:
            return candidates[0]
        time.sleep(0.1)
    raise TimeoutError("dialogue modal did not appear")


def _window_payload(hwnd: int) -> dict[str, object]:
    children: list[dict[str, object]] = []

    def visit(child: int, _extra: object) -> bool:
        children.append(
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
    return {
        "title": win32gui.GetWindowText(hwnd),
        "class": win32gui.GetClassName(hwnd),
        "rect": list(win32gui.GetWindowRect(hwnd)),
        "children": children,
    }


def main() -> int:
    ROOT.mkdir(parents=True, exist_ok=True)
    shots = ROOT / "screenshots"
    shots.mkdir(parents=True, exist_ok=True)
    driver = Win32LegacyDriver()
    results: list[dict[str, object]] = []
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
        database_hwnd = int(driver.current_window.handle)
        excluded = {database_hwnd}
        for control_id, label in BUTTONS:
            driver.perform(({"op": "click_id", "class": "Button", "control_id": control_id},), 0)
            time.sleep(0.4)
            hwnd = _modal(pid, excluded)
            payload = _window_payload(hwnd)
            payload.update({"button_id": control_id, "label": label})
            driver.current_window = driver._wait_window(
                lambda window: int(window.handle) == hwnd
            )
            control_state: dict[str, object] = {}
            for child in payload["children"]:
                if not child["visible"] or child["class"] not in {"ComboBox", "ListBox"}:
                    continue
                child_id = int(child["control_id"])
                control = driver._control(child_id, str(child["class"]))
                try:
                    selected_index = int(control.selected_index())
                except Exception:
                    selected_index = None
                try:
                    item_texts = list(control.item_texts())
                except Exception:
                    item_texts = []
                control_state[str(child_id)] = {
                    "class": child["class"],
                    "selected_index": selected_index,
                    "item_texts": item_texts,
                }
            payload["control_state"] = control_state
            left, top, right, bottom = payload["rect"]
            safe_label = re.sub(r'[<>:"/\\|?*]+', "_", label)
            shot = shots / f"{control_id}_{safe_label}.png"
            ImageGrab.grab(bbox=(left, top, right, bottom)).save(shot)
            payload["screenshot"] = shot.relative_to(REPO).as_posix()
            results.append(payload)
            cancel = next(
                (
                    child
                    for child in payload["children"]
                    if child["class"] == "Button"
                    and child["visible"]
                    and child["text"] in {"取消", "关闭"}
                ),
                None,
            )
            if cancel is None:
                win32gui.PostMessage(hwnd, 0x0010, 0, 0)
            else:
                driver.perform(
                    ({"op": "click_id", "class": "Button", "control_id": int(cancel["control_id"])},),
                    0,
                )
            driver.current_window = driver._wait_window(lambda window: window.window_text() == "数据库")
            time.sleep(0.2)
        OUTPUT.write_text(
            json.dumps({"pid": pid, "buttons": results}, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        print(OUTPUT)
        return 0
    finally:
        driver.stop()


if __name__ == "__main__":
    raise SystemExit(main())
