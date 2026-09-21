"""Enumerate both legacy M06 portrait upload file dialogs without selecting a file."""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path

import win32con
import win32gui

REPO = Path(__file__).resolve().parents[2]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from tools.golden_pipeline_collect import Win32LegacyDriver
from tools.research.probe_m06_transform_dialogue import controls


AUDIT = REPO / "output" / "build" / "legacy-diff-audit"
ROOT = REPO / "output" / "verification" / "legacy-ui-probe-m06-portrait-upload-20260920"
OUTPUT = ROOT / "M06_头像上传文件框.json"


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
        dialogs: list[dict[str, object]] = []
        for control_id, kind in ((790, "front"), (800, "back")):
            driver.current_window = database
            driver.perform(
                ({"op": "click_id", "class": "Button", "control_id": control_id},),
                0,
            )
            confirmation = driver._wait_window(
                lambda window: window.class_name() == "#32770" and window.is_visible()
            )
            driver.current_window = confirmation
            confirmation_payload = {
                "title": confirmation.window_text(),
                "controls": controls(int(confirmation.handle)),
            }
            driver.perform(
                ({"op": "click_id", "class": "Button", "control_id": 7},), 0
            )
            dialog = driver._wait_window(
                lambda window: window.class_name() == "#32770"
                and window.is_visible()
                and int(window.handle) != int(confirmation.handle)
            )
            dialogs.append(
                {
                    "kind": kind,
                    "confirmation": confirmation_payload,
                    "title": dialog.window_text(),
                    "controls": controls(int(dialog.handle)),
                }
            )
            win32gui.PostMessage(int(dialog.handle), win32con.WM_CLOSE, 0, 0)
            deadline = time.monotonic() + 5.0
            while time.monotonic() < deadline and win32gui.IsWindow(int(dialog.handle)):
                time.sleep(0.05)
        ROOT.mkdir(parents=True, exist_ok=True)
        OUTPUT.write_text(
            json.dumps({"pid": pid, "dialogs": dialogs}, ensure_ascii=False, indent=2)
            + "\n",
            encoding="utf-8",
        )
        print(OUTPUT)
        return 0
    finally:
        driver.stop()


if __name__ == "__main__":
    raise SystemExit(main())
