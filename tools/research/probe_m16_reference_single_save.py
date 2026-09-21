"""Probe one M16 upper-table field through write/save on isolated copies."""

from __future__ import annotations

import ctypes
import json
import sys
import time
import traceback
from pathlib import Path

import win32con
from pywinauto import win32defines
from pywinauto.remote_memory_block import RemoteMemoryBlock

ROOT_HINT = Path(__file__).resolve().parents[2]
if str(ROOT_HINT) not in sys.path:
    sys.path.insert(0, str(ROOT_HINT))

from tools.research import probe_m16_reference_controls as controls


OUT = controls.ROOT / "output" / "verification" / "legacy-m16-reference-single-save-20260920"
RESULT = OUT / "result.json"


def diff_ranges(before: bytes, after: bytes) -> list[dict[str, object]]:
    changed = [index for index, pair in enumerate(zip(before, after)) if pair[0] != pair[1]]
    if not changed:
        return []
    ranges = []
    start = previous = changed[0]
    for offset in changed[1:] + [changed[-1] + 2]:
        if offset != previous + 1:
            end = previous + 1
            ranges.append(
                {
                    "start": start,
                    "end_exclusive": end,
                    "before_hex": before[start:end].hex().upper(),
                    "after_hex": after[start:end].hex().upper(),
                }
            )
            start = offset
        previous = offset
    return ranges


def set_item_text(table, row: int, column: int, value: str) -> None:
    item = table.LVITEM()
    item.iSubItem = column
    text = table.create_buffer(value if table.is_unicode() else value.encode("mbcs"))
    remote = RemoteMemoryBlock(table)
    try:
        item.pszText = remote.Address() + ctypes.sizeof(item) + 8
        remote.Write(text, item.pszText)
        remote.Write(item)
        message = (
            win32defines.LVM_SETITEMTEXTW
            if table.is_unicode()
            else win32defines.LVM_SETITEMTEXTA
        )
        if not table.send_message(message, row, remote):
            raise RuntimeError(f"ListView rejected row={row} column={column}")
    finally:
        del remote


def visible_windows(driver) -> list[dict[str, object]]:
    result = []
    for window in driver.app.windows():
        try:
            if window.is_visible():
                result.append(
                    {
                        "handle": int(window.handle),
                        "class": window.class_name(),
                        "title": window.window_text(),
                        "texts": [
                            item.window_text() for item in window.descendants()
                            if item.is_visible() and item.window_text()
                        ],
                    }
                )
        except Exception:
            continue
    return result


def main() -> int:
    controls.prepare()
    OUT.mkdir(parents=True, exist_ok=True)
    work_save = controls.SAVE
    before = work_save.read_bytes()
    driver = controls.Win32LegacyDriver()
    payload: dict[str, object] = {}
    try:
        driver.launch(controls.RUNTIME / "SRW2_patched.exe", controls.RUNTIME)
        driver.open_rom(controls.ROM)
        controls.open_save_editor(driver)
        controls.load_save(driver)
        table = driver._control(100, "SysListView32")
        original = table.get_item(0, 9).text()
        requested = str((int(original) + 1) & 0xFFFF)
        set_item_text(table, 0, 9, requested)
        observed_after_set = table.get_item(0, 9).text()
        disk_after_set = work_save.read_bytes()
        driver._control(170, "Button").click()
        time.sleep(0.5)
        windows_after_write = visible_windows(driver)
        disk_after_write = work_save.read_bytes()
        modal_after_write = [
            item for item in windows_after_write
            if item["class"] == "#32770"
        ]
        if not modal_after_write:
            driver._control(180, "Button").click()
            time.sleep(0.8)
        windows_after_save = visible_windows(driver)
        disk_after_save = work_save.read_bytes()
        payload = {
            "field": "upper.row0.exp",
            "original": original,
            "requested": requested,
            "observed_after_set": observed_after_set,
            "disk_changed_after_set": disk_after_set != before,
            "disk_changed_after_write": disk_after_write != before,
            "disk_changed_after_save": disk_after_save != before,
            "windows_after_write": windows_after_write,
            "windows_after_save": windows_after_save,
            "ranges_after_save": diff_ranges(before, disk_after_save),
        }
    finally:
        driver.stop()
    payload["passed"] = bool(
        payload.get("observed_after_set") == payload.get("requested")
        and not payload.get("disk_changed_after_set")
        and not payload.get("disk_changed_after_write")
    )
    RESULT.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return 0 if payload["passed"] else 1


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception:
        OUT.mkdir(parents=True, exist_ok=True)
        (OUT / "error.log").write_text(traceback.format_exc(), encoding="utf-8")
        raise
