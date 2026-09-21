"""Read every M12 selector row and its exposed editor values without saving."""

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
SOURCE = AUDIT / "audit.nes"
OUT = ROOT / "output/verification/legacy-m12-reference-catalog-20260920"
WORK = OUT / "read-only-work.nes"
REPORT = OUT / "catalog.json"


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def open_animation(driver: Win32LegacyDriver) -> None:
    main = driver._main()
    ctypes.windll.user32.PostMessageW(int(main.handle), win32con.WM_COMMAND, 20011, 0)
    driver.current_window = driver._wait_window(lambda item: item.window_text() == "地图动画")


def select_tab(driver: Win32LegacyDriver, x: int) -> None:
    rect = driver.current_window.rectangle()
    driver.current_window.click_input(coords=(int(x * rect.width() / 847), int(75 * rect.height() / 653)))
    time.sleep(0.15)


def listbox_items(box) -> list[str]:
    count = int(win32gui.SendMessage(box.handle, 0x018B, 0, 0))
    result = []
    for row in range(count):
        length = int(win32gui.SendMessage(box.handle, 0x018A, row, 0))
        buffer = ctypes.create_unicode_buffer(length + 1)
        win32gui.SendMessage(box.handle, 0x0189, row, buffer)
        result.append(buffer.value)
    return result


def select_listbox(box, row: int) -> None:
    win32gui.SendMessage(box.handle, 0x0186, row, 0)
    win32gui.SendMessage(win32gui.GetParent(box.handle), win32con.WM_COMMAND, int(box.control_id()) | (1 << 16), box.handle)
    time.sleep(0.015)


def combo_index(driver: Win32LegacyDriver, control_id: int) -> int:
    matches = [item for item in driver.current_window.descendants(class_name="ComboBox") if item.control_id() == control_id]
    if len(matches) != 1:
        raise RuntimeError(f"ComboBox {control_id} matched {len(matches)} controls")
    return int(win32gui.SendMessage(matches[0].handle, 0x0147, 0, 0))


def any_control(driver: Win32LegacyDriver, control_id: int, class_name: str):
    matches = [item for item in driver.current_window.descendants(class_name=class_name) if item.control_id() == control_id]
    if len(matches) != 1:
        raise RuntimeError(f"Control {control_id} matched {len(matches)} controls")
    return matches[0]


def rows_for_list(driver: Win32LegacyDriver, list_id: int, readers) -> list[dict[str, object]]:
    box = driver._control(list_id, "ListBox")
    labels = listbox_items(box)
    rows = []
    for row, label in enumerate(labels):
        select_listbox(box, row)
        item = {"row": row, "label": label}
        for key, reader in readers:
            item[key] = reader()
        rows.append(item)
    return rows


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    shutil.copy2(SOURCE, WORK)
    baseline = sha(WORK)
    driver = Win32LegacyDriver()
    try:
        driver.launch(AUDIT / "SRW2_patched.exe", AUDIT)
        driver.open_rom(WORK)
        open_animation(driver)
        select_tab(driver, 45)
        map_rows = rows_for_list(driver, 110, (("name", lambda: driver._control(280, "Edit").window_text()), ("instructions", lambda: listbox_items(driver._control(340, "ListBox")))))
        select_tab(driver, 95)
        movement = rows_for_list(driver, 160, (("name", lambda: driver._control(210, "Edit").window_text()), ("code", lambda: driver._control(190, "Edit").window_text())))
        sprite = rows_for_list(driver, 220, (("name", lambda: driver._control(260, "Edit").window_text()), ("code", lambda: driver._control(240, "Edit").window_text()), ("preview_index", lambda: combo_index(driver, 600)), ("x", lambda: driver._control(630, "Edit").window_text()), ("y", lambda: driver._control(650, "Edit").window_text())))
        background = rows_for_list(driver, 530, (("name", lambda: driver._control(570, "Edit").window_text()), ("code", lambda: driver._control(550, "Edit").window_text())))
        select_tab(driver, 145)
        spirit = rows_for_list(driver, 360, (("animation_index", lambda: combo_index(driver, 400)),))
        map_weapon = rows_for_list(driver, 410, tuple((f"animation_{slot + 1}_index", lambda control_id=control_id: combo_index(driver, control_id)) for slot, control_id in enumerate((450, 480, 500, 520))))
        classes = {110:"ListBox",120:"Button",150:"Button",160:"ListBox",190:"Edit",210:"Edit",220:"ListBox",240:"Edit",260:"Edit",280:"Edit",300:"Button",310:"Button",320:"Button",330:"Button",340:"ListBox",360:"ListBox",380:"Button",400:"ComboBox",410:"ListBox",430:"Button",450:"ComboBox",480:"ComboBox",500:"ComboBox",520:"ComboBox",530:"ListBox",550:"Edit",570:"Edit",600:"ComboBox",630:"Edit",650:"Edit"}
        controls = {}
        for control_id, class_name in classes.items():
            try:
                item = any_control(driver, control_id, class_name)
            except RuntimeError:
                # Revisit the owning tab for controls hidden by the current tab.
                select_tab(driver, 45 if control_id in {110,120,150,280,340} else 95 if control_id in {160,190,210,220,240,260,320,330,530,550,570,600,630,650} else 145)
                item = driver._control(control_id, class_name)
            style = int(win32gui.GetWindowLong(item.handle, -16))
            controls[str(control_id)] = {"class": class_name, "style": style, "enabled": bool(win32gui.IsWindowEnabled(item.handle)), "edit_read_only": bool(style & 0x0800) if class_name == "Edit" else None}
        payload = {"passed": True, "source_sha256": baseline, "rom_unchanged": sha(WORK) == baseline, "controls": controls, "counts": {"map": len(map_rows), "movement": len(movement), "sprite": len(sprite), "background": len(background), "spirit": len(spirit), "map_weapon": len(map_weapon)}, "map": map_rows, "movement": movement, "sprite": sprite, "background": background, "spirit": spirit, "map_weapon": map_weapon}
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
        (OUT / "error.log").write_text(traceback.format_exc(), encoding="utf-8")
        raise
    raise SystemExit(result)
