"""Enumerate the reference M16 save editor and probe per-column edit affordances.

The probe operates on an isolated SAV copy and never invokes either write/save
button.  It opens a compatible ROM only to expose the legacy Data menu.
"""

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


AUDIT = ROOT / "output" / "build" / "legacy-diff-audit"
OUT = ROOT / "output" / "verification" / "legacy-m16-reference-controls-20260920"
RUNTIME = OUT / "reference-runtime"
ROM = OUT / "probe.nes"
SAVE = OUT / "probe.sav"
RESULT = OUT / "catalog.json"
SOURCE_ROM = AUDIT / "默认配置文件" / "测试.nes"
SOURCE_SAVE = ROOT / "references" / "emulator-state" / "fceux" / "sav" / "DC_kuorong.sav"


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def prepare() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    if RUNTIME.exists():
        shutil.rmtree(RUNTIME)
    RUNTIME.mkdir()
    shutil.copy2(AUDIT / "SRW2_patched.exe", RUNTIME / "SRW2_patched.exe")
    shutil.copytree(AUDIT / "默认配置文件" / "默认配置文件", RUNTIME / "默认配置文件")
    shutil.copy2(SOURCE_ROM, ROM)
    shutil.copy2(SOURCE_SAVE, SAVE)


def open_save_editor(driver: Win32LegacyDriver) -> None:
    main = driver._main()
    ctypes.windll.user32.PostMessageW(int(main.handle), win32con.WM_COMMAND, 20021, 0)
    driver.current_window = driver._wait_window(
        lambda item: item.class_name() == "WTWindow"
        and item.window_text().startswith("存档编辑器")
        and any(control.control_id() == 160 for control in item.descendants(class_name="Button")),
        timeout=12.0,
    )


def load_save(driver: Win32LegacyDriver) -> None:
    driver._control(160, "Button").click()
    dialog = driver._wait_window(
        lambda item: item.class_name() == "#32770"
        and item.is_visible()
        and item.window_text().startswith("打开"),
        timeout=10.0,
    )
    edits = [
        item for item in dialog.descendants(class_name="Edit")
        if item.is_visible() and item.is_enabled()
    ]
    if not edits:
        raise RuntimeError("save picker has no filename edit")
    edits[-1].set_edit_text(str(SAVE))
    ok = win32gui.GetDlgItem(int(dialog.handle), 1)
    if not ok:
        raise RuntimeError("save picker has no IDOK")
    win32gui.PostMessage(ok, win32con.BM_CLICK, 0, 0)
    deadline = time.monotonic() + 10.0
    while win32gui.IsWindow(int(dialog.handle)) and time.monotonic() < deadline:
        time.sleep(0.05)
    driver._control(190, "Button").click()
    deadline = time.monotonic() + 8.0
    table = driver._control(100, "SysListView32")
    while table.item_count() == 0 and time.monotonic() < deadline:
        time.sleep(0.05)


def visible_controls(window) -> list[dict[str, object]]:
    result = []
    for item in window.descendants():
        try:
            if not item.is_visible():
                continue
            result.append(
                {
                    "handle": int(item.handle),
                    "class": item.class_name(),
                    "control_id": int(item.control_id()),
                    "text": item.window_text(),
                    "enabled": bool(item.is_enabled()),
                }
            )
        except Exception:
            continue
    return result


def table_snapshot(table) -> dict[str, object]:
    column_count = int(table.column_count())
    headers = []
    for column in range(column_count):
        info = table.get_column(column)
        headers.append(str(info.get("text", "")))
    rows = []
    for row in range(int(table.item_count())):
        rows.append([table.get_item(row, column).text() for column in range(column_count)])
    return {"column_count": column_count, "headers": headers, "rows": rows}


def window_inventory(driver: Win32LegacyDriver) -> list[dict[str, object]]:
    result = []
    for item in driver.app.windows():
        try:
            if item.is_visible():
                result.append(
                    {
                        "handle": int(item.handle),
                        "class": item.class_name(),
                        "title": item.window_text(),
                    }
                )
        except Exception:
            continue
    return result


def window_details(driver: Win32LegacyDriver) -> list[dict[str, object]]:
    details = []
    for item in driver.app.windows():
        try:
            if not item.is_visible():
                continue
            details.append(
                {
                    "handle": int(item.handle),
                    "class": item.class_name(),
                    "title": item.window_text(),
                    "controls": visible_controls(item),
                }
            )
        except Exception:
            continue
    return details


def dismiss_new_windows(driver: Win32LegacyDriver, known_handles: set[int]) -> None:
    for item in driver.app.windows():
        try:
            if not item.is_visible() or int(item.handle) in known_handles:
                continue
            buttons = [
                control for control in item.descendants(class_name="Button")
                if control.is_visible() and control.is_enabled()
            ]
            cancel = next((control for control in buttons if control.control_id() == 2), None)
            ok = next((control for control in buttons if control.control_id() == 1), None)
            if cancel or ok:
                (cancel or ok).click()
            else:
                item.type_keys("{ESC}", set_foreground=True)
            time.sleep(0.1)
        except Exception:
            continue


def probe_columns(driver: Win32LegacyDriver, control_id: int) -> list[dict[str, object]]:
    table = driver._control(control_id, "SysListView32")
    if not table.item_count():
        return []
    results = []
    for column in range(int(table.column_count())):
        before_controls = visible_controls(driver.current_window)
        before_windows = window_inventory(driver)
        before_window_handles = {int(item["handle"]) for item in before_windows}
        before_handles = {int(item["handle"]) for item in before_controls}
        cell = table.get_item(0, column)
        cell_rect = cell.rectangle()
        table.double_click_input(
            coords=(
                (int(cell_rect.left) + int(cell_rect.right)) // 2,
                (int(cell_rect.top) + int(cell_rect.bottom)) // 2,
            )
        )
        time.sleep(0.35)
        after_controls = visible_controls(driver.current_window)
        after_windows = window_inventory(driver)
        after_details = window_details(driver)
        new_controls = [item for item in after_controls if int(item["handle"]) not in before_handles]
        changed = [
            item for item in after_controls
            if item["class"] in {"Edit", "ComboBox"}
            and item not in before_controls
        ]
        results.append(
            {
                "column": column,
                "cell_text": table.get_item(0, column).text(),
                "new_controls": new_controls,
                "new_edit_or_combo": changed,
                "windows_before": before_windows,
                "windows_after": after_windows,
                "new_window_details": [
                    item for item in after_details
                    if int(item["handle"]) not in before_window_handles
                ],
            }
        )
        # Dismiss an editor or modal without committing any value.
        dismiss_new_windows(driver, before_window_handles)
        if new_controls:
            driver.current_window.type_keys("{ESC}", set_foreground=True)
        time.sleep(0.12)
    return results


def main() -> int:
    prepare()
    original_save_sha = sha256(SAVE)
    original_rom_sha = sha256(ROM)
    driver = Win32LegacyDriver()
    try:
        driver.launch(RUNTIME / "SRW2_patched.exe", RUNTIME)
        driver.open_rom(ROM)
        open_save_editor(driver)
        load_save(driver)
        upper = driver._control(100, "SysListView32")
        lower = driver._control(110, "SysListView32")
        payload = {
            "passed": True,
            "input_rom": str(SOURCE_ROM.relative_to(ROOT)).replace("\\", "/"),
            "input_save": str(SOURCE_SAVE.relative_to(ROOT)).replace("\\", "/"),
            "rom_sha256_before": original_rom_sha,
            "save_sha256_before": original_save_sha,
            "upper": table_snapshot(upper),
            "lower": table_snapshot(lower),
            "upper_column_probes": probe_columns(driver, 100),
            "lower_column_probes": probe_columns(driver, 110),
            "visible_controls": visible_controls(driver.current_window),
        }
    finally:
        driver.stop()
    payload["rom_sha256_after"] = sha256(ROM)
    payload["save_sha256_after"] = sha256(SAVE)
    payload["rom_unchanged"] = payload["rom_sha256_after"] == original_rom_sha
    payload["save_unchanged"] = payload["save_sha256_after"] == original_save_sha
    payload["passed"] = bool(payload["rom_unchanged"] and payload["save_unchanged"])
    RESULT.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return 0 if payload["passed"] else 1


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception:
        OUT.mkdir(parents=True, exist_ok=True)
        (OUT / "error.log").write_text(traceback.format_exc(), encoding="utf-8")
        raise
