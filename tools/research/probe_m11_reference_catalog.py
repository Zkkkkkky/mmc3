"""Read M11 controls, page selectors and grid selection semantics."""

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
OUT = ROOT / "output/verification/legacy-m11-reference-catalog-20260920"
WORK = OUT / "read-only-work.nes"
REPORT = OUT / "catalog.json"


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def combo_items(combo) -> list[str]:
    count = int(win32gui.SendMessage(combo.handle, 0x0146, 0, 0))
    result = []
    for index in range(count):
        length = int(win32gui.SendMessage(combo.handle, 0x0149, index, 0))
        buffer = ctypes.create_unicode_buffer(length + 1)
        win32gui.SendMessage(combo.handle, 0x0148, index, buffer)
        result.append(buffer.value)
    return result


def open_font(driver: Win32LegacyDriver) -> None:
    main = driver._main()
    if not ctypes.windll.user32.PostMessageW(int(main.handle), win32con.WM_COMMAND, 20009, 0):
        raise RuntimeError("font menu command failed")
    window = driver._wait_window(lambda item: item.window_text() == "字库编辑")
    driver.current_window = window


def selected(driver: Win32LegacyDriver) -> dict[str, str]:
    return {str(control_id): driver._control(control_id, "Edit").window_text() for control_id in (140, 150, 160, 300)}


def click_cell(driver: Win32LegacyDriver, row: int, column: int) -> dict[str, object]:
    grid = driver._control(110)
    rect = grid.rectangle()
    width, height = int(rect.width()), int(rect.height())
    x = max(1, min(width - 2, int((column + 0.5) * width / 16)))
    y = max(1, min(height - 2, int((row + 0.5) * height / 16)))
    grid.click_input(coords=(x, y))
    time.sleep(0.12)
    return {"row": row, "column": column, "click": [x, y], "values": selected(driver)}


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    shutil.copy2(SOURCE, WORK)
    baseline = sha(WORK)
    driver = Win32LegacyDriver()
    try:
        driver.launch(AUDIT / "SRW2_patched.exe", AUDIT)
        driver.open_rom(WORK)
        open_font(driver)
        controls = {}
        for control_id, class_name in ((110, None), (130, "ComboBox"), (140, "Edit"), (150, "Edit"), (160, "Edit"), (170, "Button"), (240, "Button"), (250, "Button"), (260, "Button"), (300, "Edit"), (310, "Button")):
            item = driver._control(control_id, class_name)
            style = int(win32gui.GetWindowLong(item.handle, -16))
            controls[str(control_id)] = {"class": item.class_name(), "text": item.window_text(), "style": style, "ex_style": int(win32gui.GetWindowLong(item.handle, -20)), "edit_read_only": bool(style & 0x0800) if item.class_name() == "Edit" else None}
        pages = combo_items(driver._control(130, "ComboBox"))
        page_samples = []
        for index, page in enumerate(pages):
            driver.perform(({"op": "select_index_message", "class": "ComboBox", "control_id": 130, "value": index},), 0)
            page_samples.append({"index": index, "page": page, "cell_00": click_cell(driver, 0, 0)})
        driver.perform(({"op": "select_index_message", "class": "ComboBox", "control_id": 130, "value": pages.index("C8")},), 0)
        grid_samples = [click_cell(driver, row, column) for row, column in ((0, 0), (0, 13), (0, 14), (0, 15), (1, 0), (15, 13), (15, 14), (15, 15))]
        payload = {"passed": True, "reference_pid": driver.pid, "source_sha256": baseline, "rom_unchanged": sha(WORK) == baseline, "controls": controls, "pages": pages, "page_samples": page_samples, "grid_samples": grid_samples}
        REPORT.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print(json.dumps({"pages": len(pages), "samples": len(grid_samples)}, ensure_ascii=False))
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
