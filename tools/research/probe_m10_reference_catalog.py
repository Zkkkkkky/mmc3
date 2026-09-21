"""Read the complete M10 field surface from an isolated reference process."""

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
OUT = ROOT / "output/verification/legacy-m10-reference-catalog-20260920"
WORK = OUT / "read-only-work.nes"
REPORT = OUT / "catalog.json"
ERROR = OUT / "error.log"
DIALOGUE_EDIT_IDS = (1970, 1990, 2010, 2020, 2040, 2060, 2090)


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def open_other2(driver: Win32LegacyDriver) -> None:
    driver.current_window = driver._main()
    driver.perform(
        (
            {"op": "menu", "path": "数据->数据库"},
            {"op": "window", "title": "数据库"},
            {"op": "click_coords", "x": 485, "y": 62},
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


def combo_items(combo) -> list[str]:
    count = int(win32gui.SendMessage(combo.handle, 0x0146, 0, 0))
    result: list[str] = []
    for index in range(count):
        length = int(win32gui.SendMessage(combo.handle, 0x0149, index, 0))
        buffer = ctypes.create_unicode_buffer(length + 1)
        win32gui.SendMessage(combo.handle, 0x0148, index, buffer)
        result.append(buffer.value)
    return result


def listbox_items(box) -> list[str]:
    count = int(win32gui.SendMessage(box.handle, 0x018B, 0, 0))
    result: list[str] = []
    for row in range(count):
        length = int(win32gui.SendMessage(box.handle, 0x018A, row, 0))
        buffer = ctypes.create_unicode_buffer(length + 1)
        win32gui.SendMessage(box.handle, 0x0189, row, buffer)
        result.append(buffer.value)
    return result


def select_listbox(box, row: int) -> None:
    if win32gui.SendMessage(box.handle, 0x0186, row, 0) == -1:
        raise RuntimeError(f"ListBox row {row} is unavailable")
    parent = win32gui.GetParent(box.handle)
    win32gui.SendMessage(parent, win32con.WM_COMMAND, int(box.control_id()) | (1 << 16), box.handle)
    time.sleep(0.08)


def select_item(driver: Win32LegacyDriver, row: int, expected_name: str) -> None:
    table = control(driver, 1690, "SysListView32")
    table.set_focus()
    table.get_item(row, 0).ensure_visible()
    top = int(win32gui.SendMessage(table.handle, 0x1027, 0, 0))
    y = 165 + (row - top) * 25
    for delta in (0, -8, 8, -15, 15):
        driver.current_window.click_input(coords=(100, y + delta))
        time.sleep(0.15)
        if control(driver, 1710, "Edit").window_text() == expected_name:
            return
    raise RuntimeError(f"unable to select item {row}: {expected_name!r}")


def style_payload(item, class_name: str) -> dict[str, object]:
    style = int(win32gui.GetWindowLong(item.handle, -16))
    return {
        "style": style,
        "ex_style": int(win32gui.GetWindowLong(item.handle, -20)),
        "enabled": bool(win32gui.IsWindowEnabled(item.handle)),
        "visible": bool(win32gui.IsWindowVisible(item.handle)),
        "edit_read_only": bool(style & 0x0800) if class_name == "Edit" else None,
    }


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    shutil.copy2(SOURCE_ROM, WORK)
    baseline_sha = sha256(WORK)
    driver = Win32LegacyDriver()
    try:
        driver.launch(AUDIT / "SRW2_patched.exe", AUDIT)
        driver.open_rom(WORK)
        open_other2(driver)

        item_table = control(driver, 1690, "SysListView32")
        item_rows = listview_rows(item_table)
        items: list[dict[str, object]] = []
        for row, columns in enumerate(item_rows):
            expected_name = columns[0].split("：", 1)[-1]
            select_item(driver, row, expected_name)
            items.append({
                "row": row,
                "table": columns,
                "name": control(driver, 1710, "Edit").window_text(),
                "price": control(driver, 1730, "Edit").window_text(),
                "description": control(driver, 1780, "Edit").window_text(),
            })

        shop_box = control(driver, 1810, "ListBox")
        shop_labels = listbox_items(shop_box)
        shops: list[dict[str, object]] = []
        for row, label in enumerate(shop_labels):
            select_listbox(shop_box, row)
            shops.append({
                "row": row,
                "label": label,
                "items": [control(driver, control_id, "ComboBox").window_text() for control_id in (1870, 1880, 1890, 1900)],
                "item_indices": [int(win32gui.SendMessage(control(driver, control_id, "ComboBox").handle, 0x0147, 0, 0)) for control_id in (1870, 1880, 1890, 1900)],
                "clerk": control(driver, 1920, "ComboBox").window_text(),
                "clerk_index": int(win32gui.SendMessage(control(driver, 1920, "ComboBox").handle, 0x0147, 0, 0)),
                "dialogue": control(driver, 1940, "ComboBox").window_text(),
                "dialogue_index": int(win32gui.SendMessage(control(driver, 1940, "ComboBox").handle, 0x0147, 0, 0)),
                "dialogue_texts": [control(driver, control_id, "Edit").window_text() for control_id in DIALOGUE_EDIT_IDS],
                "enabled": {str(control_id): bool(win32gui.IsWindowEnabled(control(driver, control_id, "ComboBox" if control_id in (1870, 1880, 1890, 1900, 1920, 1940) else "Edit").handle)) for control_id in (*range(1870, 1910, 10), 1920, 1940, *DIALOGUE_EDIT_IDS)},
            })

        classes = {1690: "SysListView32", 1710: "Edit", 1730: "Edit", 1780: "Edit", 1810: "ListBox", 1870: "ComboBox", 1880: "ComboBox", 1890: "ComboBox", 1900: "ComboBox", 1920: "ComboBox", 1940: "ComboBox", **{item: "Edit" for item in DIALOGUE_EDIT_IDS}}
        payload = {
            "passed": True,
            "reference_pid": driver.pid,
            "source_rom": SOURCE_ROM.relative_to(ROOT).as_posix(),
            "source_sha256": baseline_sha,
            "rom_unchanged": sha256(WORK) == baseline_sha,
            "controls": {str(control_id): style_payload(control(driver, control_id, class_name), class_name) for control_id, class_name in classes.items()},
            "combo_options": {str(control_id): combo_items(control(driver, control_id, "ComboBox")) for control_id in (1870, 1880, 1890, 1900, 1920, 1940)},
            "counts": {"items": len(items), "shops": len(shops), "dialogue_slots_per_shop": len(DIALOGUE_EDIT_IDS)},
            "items": items,
            "shops": shops,
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
