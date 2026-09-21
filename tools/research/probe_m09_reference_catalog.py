"""Read the complete M09 field surface from an isolated reference process."""

from __future__ import annotations

import ctypes
import hashlib
import json
import shutil
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
SOURCE_ROM = AUDIT / "audit.nes"
OUT = ROOT / "output/verification/legacy-m09-reference-catalog-20260920"
WORK = OUT / "read-only-work.nes"
REPORT = OUT / "catalog.json"
ERROR = OUT / "error.log"


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def open_other1(driver: Win32LegacyDriver) -> None:
    driver.current_window = driver._main()
    driver.perform(
        (
            {"op": "menu", "path": "数据->数据库"},
            {"op": "window", "title": "数据库"},
            {"op": "click_coords", "x": 390, "y": 62},
        ),
        0,
    )


def control(driver: Win32LegacyDriver, control_id: int, class_name: str):
    return driver._control(control_id, class_name)


def listview_rows(table) -> list[list[str]]:
    try:
        columns = max(1, int(table.column_count()))
    except Exception:
        columns = 1
    return [
        [table.get_item(row, column).text() for column in range(columns)]
        for row in range(int(table.item_count()))
    ]


def combobox_items(combo) -> list[str]:
    count = int(win32gui.SendMessage(combo.handle, 0x0146, 0, 0))  # CB_GETCOUNT
    result: list[str] = []
    for index in range(count):
        length = int(win32gui.SendMessage(combo.handle, 0x0149, index, 0))
        buffer = ctypes.create_unicode_buffer(length + 1)
        win32gui.SendMessage(combo.handle, 0x0148, index, buffer)
        result.append(buffer.value)
    return result


def select_listbox(listbox, row: int) -> None:
    if win32gui.SendMessage(listbox.handle, 0x0186, row, 0) == -1:  # LB_SETCURSEL
        raise RuntimeError(f"ListBox row {row} is unavailable")
    parent = win32gui.GetParent(listbox.handle)
    wparam = int(listbox.control_id()) | (1 << 16)  # LBN_SELCHANGE
    win32gui.SendMessage(parent, win32con.WM_COMMAND, wparam, listbox.handle)
    time.sleep(0.03)


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    shutil.copy2(SOURCE_ROM, WORK)
    baseline_sha = sha256(WORK)
    driver = Win32LegacyDriver()
    try:
        driver.launch(AUDIT / "SRW2_patched.exe", AUDIT)
        driver.open_rom(WORK)
        open_other1(driver)

        distance_combo = control(driver, 1600, "ComboBox")
        growth_combo = control(driver, 2620, "ComboBox")
        experience_table = control(driver, 1570, "SysListView32")
        distance_table = control(driver, 1580, "SysListView32")
        growth_table = control(driver, 2610, "SysListView32")
        system_list = control(driver, 1750, "ListBox")
        system_edit = control(driver, 1770, "Edit")

        distance: list[dict[str, object]] = []
        distance_items = combobox_items(distance_combo)
        for index, label in enumerate(distance_items):
            driver.perform(
                ({"op": "select_index_message", "class": "ComboBox", "control_id": 1600, "value": index},),
                0,
            )
            distance.append({"selector_index": index, "selector": label, "rows": listview_rows(distance_table)})

        growth: list[dict[str, object]] = []
        growth_items = combobox_items(growth_combo)
        for index, label in enumerate(growth_items):
            driver.perform(
                ({"op": "select_index_message", "class": "ComboBox", "control_id": 2620, "value": index},),
                0,
            )
            growth.append({"selector_index": index, "selector": label, "rows": listview_rows(growth_table)})

        system_count = int(win32gui.SendMessage(system_list.handle, 0x018B, 0, 0))
        system: list[dict[str, object]] = []
        for row in range(system_count):
            length = int(win32gui.SendMessage(system_list.handle, 0x018A, row, 0))
            buffer = ctypes.create_unicode_buffer(length + 1)
            win32gui.SendMessage(system_list.handle, 0x0189, row, buffer)
            select_listbox(system_list, row)
            system.append({"row": row, "label": buffer.value, "text": system_edit.window_text()})

        payload = {
            "passed": True,
            "reference_pid": driver.pid,
            "source_rom": SOURCE_ROM.relative_to(ROOT).as_posix(),
            "source_sha256": baseline_sha,
            "rom_unchanged": sha256(WORK) == baseline_sha,
            "controls": {
                "distance_selector_id": 1600,
                "distance_table_id": 1580,
                "experience_table_id": 1570,
                "experience_edit_id": 1620,
                "system_list_id": 1750,
                "system_edit_id": 1770,
                "growth_selector_id": 2620,
                "growth_table_id": 2610,
                "growth_quick_edit_button_id": 2650,
                "styles": {
                    str(control_id): {
                        "style": int(win32gui.GetWindowLong(control(driver, control_id, class_name).handle, -16)),
                        "ex_style": int(win32gui.GetWindowLong(control(driver, control_id, class_name).handle, -20)),
                        "edit_read_only": bool(int(win32gui.GetWindowLong(control(driver, control_id, class_name).handle, -16)) & 0x0800) if class_name == "Edit" else None,
                    }
                    for control_id, class_name in ((1620, "Edit"), (1650, "Edit"), (1640, "Edit"), (1770, "Edit"))
                },
            },
            "counts": {
                "distance_selectors": len(distance),
                "distance_rows": sum(len(item["rows"]) for item in distance),
                "experience_rows": int(experience_table.item_count()),
                "system_rows": len(system),
                "growth_selectors": len(growth),
                "growth_rows": sum(len(item["rows"]) for item in growth),
            },
            "distance": distance,
            "experience": listview_rows(experience_table),
            "system": system,
            "growth": growth,
        }
        REPORT.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print(json.dumps(payload["counts"], ensure_ascii=False))
        return 0
    finally:
        driver.stop()


if __name__ == "__main__":
    try:
        result = main()
    except Exception:
        OUT.mkdir(parents=True, exist_ok=True)
        ERROR.write_text(traceback.format_exc(), encoding="utf-8")
        raise
    raise SystemExit(result)
