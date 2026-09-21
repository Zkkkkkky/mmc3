"""Read M12 map pointer dialogs and per-row map-weapon enablement without saving."""

from __future__ import annotations

import ctypes
import hashlib
import json
import sys
import time
import traceback
from pathlib import Path

import win32con
import win32gui

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools.golden_pipeline_collect import Win32LegacyDriver


AUDIT = ROOT / "output/build/legacy-diff-audit"
OUT = ROOT / "output/verification/legacy-m12-reference-catalog-20260920"
WORK = OUT / "read-only-work.nes"
BASE_CATALOG = OUT / "catalog.json"
REPORT = OUT / "pointer-fields.json"
PROGRESS = OUT / "pointer-fields-progress.json"


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def mark(row: int, stage: str) -> None:
    PROGRESS.write_text(
        json.dumps({"row": row, "stage": stage, "time": time.time()}) + "\n",
        encoding="utf-8",
    )


def open_animation(driver: Win32LegacyDriver) -> None:
    main = driver._main()
    ctypes.windll.user32.PostMessageW(int(main.handle), win32con.WM_COMMAND, 20011, 0)
    driver.current_window = driver._wait_window(lambda item: item.window_text() == "地图动画")


def select_tab(driver: Win32LegacyDriver, x: int) -> None:
    rect = driver.current_window.rectangle()
    driver.current_window.click_input(
        coords=(int(x * rect.width() / 847), int(75 * rect.height() / 653))
    )
    time.sleep(0.15)


def select_listbox(driver: Win32LegacyDriver, control_id: int, row: int) -> None:
    box = driver._control(control_id, "ListBox")
    win32gui.SendMessage(box.handle, 0x0186, row, 0)
    win32gui.SendMessage(
        win32gui.GetParent(box.handle),
        win32con.WM_COMMAND,
        int(box.control_id()) | (1 << 16),
        box.handle,
    )
    time.sleep(0.02)


def control(driver: Win32LegacyDriver, control_id: int, class_name: str):
    matches = [
        item
        for item in driver.current_window.descendants(class_name=class_name)
        if item.control_id() == control_id
    ]
    if len(matches) != 1:
        raise RuntimeError(f"{class_name} {control_id} matched {len(matches)} controls")
    return matches[0]


def main() -> int:
    base = json.loads(BASE_CATALOG.read_text(encoding="utf-8"))
    expected_map_rows = int(base["counts"]["map"])
    expected_weapon_rows = int(base["counts"]["map_weapon"])
    baseline = sha(WORK)
    driver = Win32LegacyDriver()
    try:
        driver.launch(AUDIT / "SRW2_patched.exe", AUDIT)
        driver.open_rom(WORK)
        open_animation(driver)
        animation_window = driver.current_window

        select_tab(driver, 45)
        pointers: list[dict[str, object]] = []
        for row in range(expected_map_rows):
            mark(row, "select_row")
            select_listbox(driver, 110, row)
            button = driver._control(150, "Button")
            mark(row, "open_dialog")
            # The button handler owns a modal loop, so a synchronous
            # SendMessage would not return until the dialog had already been
            # dismissed. Post the click so the collector can inspect/cancel it.
            win32gui.PostMessage(button.handle, win32con.BM_CLICK, 0, 0)
            dialog = driver._wait_window(
                lambda item: item.is_visible()
                and int(item.handle) != int(animation_window.handle)
                and item.window_text().startswith("请输入"),
                timeout=4.0,
            )
            driver.current_window = dialog
            mark(row, "read_edit")
            edit = control(driver, 1001, "Edit")
            pointers.append(
                {
                    "row": row,
                    "value": edit.window_text(),
                    "dialog_title": dialog.window_text(),
                }
            )
            mark(row, "cancel_dialog")
            cancel = control(driver, 2, "Button")
            dialog_handle = int(dialog.handle)
            cancel.click_input()
            deadline = time.monotonic() + 2.0
            while win32gui.IsWindow(dialog_handle) and time.monotonic() < deadline:
                time.sleep(0.01)
            if win32gui.IsWindow(dialog_handle):
                raise RuntimeError(f"Map pointer dialog did not close at row {row}")
            mark(row, "dialog_closed")
            driver.current_window = animation_window

        select_tab(driver, 145)
        weapon_rows: list[dict[str, object]] = []
        for row in range(expected_weapon_rows):
            select_listbox(driver, 410, row)
            slots = []
            for slot, control_id in enumerate((450, 480, 500, 520), start=1):
                combo = control(driver, control_id, "ComboBox")
                raw = int(win32gui.SendMessage(combo.handle, 0x0147, 0, 0))
                slots.append(
                    {
                        "slot": slot,
                        "control_id": control_id,
                        "enabled": bool(win32gui.IsWindowEnabled(combo.handle)),
                        "selected_index": -1 if raw == 0xFFFFFFFF else raw,
                    }
                )
            weapon_rows.append({"row": row, "slots": slots})

        payload = {
            "passed": True,
            "source_sha256": baseline,
            "rom_unchanged": sha(WORK) == baseline,
            "map_pointer_count": len(pointers),
            "enabled_map_weapon_slot_count": sum(
                int(slot["enabled"]) for row in weapon_rows for slot in row["slots"]
            ),
            "map_pointers": pointers,
            "map_weapon": weapon_rows,
        }
        REPORT.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        print(
            json.dumps(
                {
                    "map_pointer_count": payload["map_pointer_count"],
                    "enabled_map_weapon_slot_count": payload[
                        "enabled_map_weapon_slot_count"
                    ],
                    "rom_unchanged": payload["rom_unchanged"],
                },
                ensure_ascii=False,
            )
        )
        return 0
    finally:
        driver.stop()


if __name__ == "__main__":
    try:
        result = main()
    except Exception:
        OUT.mkdir(parents=True, exist_ok=True)
        (OUT / "pointer-fields-error.log").write_text(
            traceback.format_exc(), encoding="utf-8"
        )
        raise
    raise SystemExit(result)
