"""Enumerate the legacy M14 selectors and per-record child lists read-only."""

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
SOURCE = AUDIT / "默认配置文件/测试.nes"
OUT = ROOT / "output/verification/legacy-m14-reference-catalog-20260920"
RUNTIME = OUT / "reference-runtime"
ROM = OUT / "probe.nes"
RESULT = OUT / "catalog.json"
PAGE_X = (45, 105, 165, 225, 285, 345)


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def prepare() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    if RUNTIME.exists():
        shutil.rmtree(RUNTIME)
    RUNTIME.mkdir()
    shutil.copy2(AUDIT / "SRW2_patched.exe", RUNTIME / "SRW2_patched.exe")
    shutil.copytree(AUDIT / "默认配置文件/默认配置文件", RUNTIME / "默认配置文件")
    shutil.copy2(SOURCE, ROM)


def open_editor(driver: Win32LegacyDriver) -> None:
    main = driver._main()
    ctypes.windll.user32.PostMessageW(int(main.handle), win32con.WM_COMMAND, 20015, 0)
    driver.current_window = driver._wait_window(
        lambda item: item.class_name() == "WTWindow" and item.window_text() == "事件编辑",
        timeout=12.0,
    )


def page(driver: Win32LegacyDriver, index: int) -> None:
    rect = driver.current_window.rectangle()
    driver.current_window.click_input(
        coords=(int(PAGE_X[index] * rect.width() / 993), int(52 * rect.height() / 644))
    )
    time.sleep(0.25)


def any_control(driver: Win32LegacyDriver, control_id: int, class_name: str):
    matches = [
        item for item in driver.current_window.descendants(class_name=class_name)
        if item.control_id() == control_id
    ]
    if len(matches) != 1:
        raise RuntimeError(f"control {control_id}/{class_name} matched {len(matches)}")
    return matches[0]


def select_list(control, row: int) -> None:
    if win32gui.SendMessage(control.handle, 0x0186, row, 0) == -1:
        raise RuntimeError(f"list row {row} unavailable")
    parent = win32gui.GetParent(control.handle)
    win32gui.SendMessage(parent, win32con.WM_COMMAND, int(control.control_id()) | (1 << 16), control.handle)
    time.sleep(0.035)


def select_combo(control, row: int) -> None:
    if win32gui.SendMessage(control.handle, 0x014E, row, 0) == -1:
        raise RuntimeError(f"combo row {row} unavailable")
    parent = win32gui.GetParent(control.handle)
    control_id = int(control.control_id())
    for notification in (1, 9, 8):
        win32gui.SendMessage(parent, win32con.WM_COMMAND, control_id | (notification << 16), control.handle)
    time.sleep(0.035)


def list_payload(control, include_items: bool = True) -> dict[str, object]:
    count = int(control.item_count())
    return {
        "count": count,
        "items": control.item_texts() if include_items else [],
    }


def main() -> int:
    prepare()
    baseline = sha(ROM)
    driver = Win32LegacyDriver()
    payload: dict[str, object] = {}
    try:
        driver.launch(RUNTIME / "SRW2_patched.exe", RUNTIME)
        driver.open_rom(ROM)
        open_editor(driver)

        page(driver, 0)
        chapters = any_control(driver, 220, "ListBox")
        phase_lists = [any_control(driver, control_id, "ListBox") for control_id in (140, 150, 160)]
        chapter_rows = []
        for row in range(int(chapters.item_count())):
            select_list(chapters, row)
            chapter_rows.append(
                {
                    "row": row,
                    "label": chapters.item_texts()[row],
                    "title": any_control(driver, 600, "Edit").window_text(),
                    "initial_victory": any_control(driver, 190, "Edit").window_text(),
                    "phase_counts": [int(control.item_count()) for control in phase_lists],
                    "phase_first": [control.item_texts()[:1] for control in phase_lists],
                }
            )

        page(driver, 1)
        actions = any_control(driver, 260, "ListBox")
        action_code = any_control(driver, 240, "ListBox")
        action_items = actions.item_texts()
        action_rows = []
        for row in range(int(actions.item_count())):
            select_list(actions, row)
            action_rows.append(
                {
                    "row": row,
                    "label": action_items[row],
                    "name": any_control(driver, 390, "Edit").window_text(),
                    "instruction_count": int(action_code.item_count()),
                    "first_instruction": action_code.item_texts()[:1],
                }
            )

        page(driver, 2)
        surrender = any_control(driver, 310, "ListBox")
        surrender_code = any_control(driver, 290, "ListBox")
        surrender_items = surrender.item_texts()
        surrender_rows = []
        for row in range(int(surrender.item_count())):
            select_list(surrender, row)
            surrender_rows.append(
                {
                    "row": row,
                    "label": surrender_items[row],
                    "chapter": any_control(driver, 430, "ComboBox").window_text(),
                    "ally": any_control(driver, 440, "ComboBox").window_text(),
                    "enemy": any_control(driver, 460, "ComboBox").window_text(),
                    "instruction_count": int(surrender_code.item_count()),
                }
            )

        page(driver, 3)
        maps = any_control(driver, 360, "ListBox")
        map_code = any_control(driver, 340, "ListBox")
        map_items = maps.item_texts()
        map_rows = []
        for row in range(int(maps.item_count())):
            select_list(maps, row)
            map_rows.append(
                {
                    "row": row,
                    "label": map_items[row],
                    "name": any_control(driver, 490, "Edit").window_text(),
                    "instruction_count": int(map_code.item_count()),
                    "first_instruction": map_code.item_texts()[:1],
                }
            )

        page(driver, 4)
        story_groups = any_control(driver, 570, "ComboBox")
        story_records = any_control(driver, 560, "ListBox")
        story_group_items = story_groups.item_texts()
        story_rows = []
        for group in range(len(story_group_items)):
            select_combo(story_groups, group)
            records = story_records.item_texts()
            samples = []
            for row in range(len(records)):
                select_list(story_records, row)
                samples.append(any_control(driver, 520, "Edit").window_text())
            story_rows.append({"group": group, "label": story_group_items[group], "records": records, "texts": samples})

        page(driver, 5)
        victory_records = any_control(driver, 630, "ListBox")
        victory_items = victory_records.item_texts()
        victory_rows = []
        for row in range(len(victory_items)):
            select_list(victory_records, row)
            victory_rows.append(
                {
                    "row": row,
                    "label": victory_items[row],
                    "text": any_control(driver, 650, "Edit").window_text(),
                }
            )

        payload = {
            "passed": True,
            "rom_sha256_before": baseline,
            "chapter_rows": chapter_rows,
            "action_rows": action_rows,
            "surrender_rows": surrender_rows,
            "map_rows": map_rows,
            "story_rows": story_rows,
            "victory_rows": victory_rows,
            "counts": {
                "chapters": len(chapter_rows),
                "chapter_phase_instructions": [sum(item["phase_counts"][phase] for item in chapter_rows) for phase in range(3)],
                "actions": len(action_rows),
                "action_instructions": sum(item["instruction_count"] for item in action_rows),
                "surrender": len(surrender_rows),
                "surrender_instructions": sum(item["instruction_count"] for item in surrender_rows),
                "maps": len(map_rows),
                "map_instructions": sum(item["instruction_count"] for item in map_rows),
                "story_groups": len(story_rows),
                "story_records": sum(len(item["records"]) for item in story_rows),
                "victory_records": len(victory_rows),
            },
        }
    finally:
        driver.stop()
    payload["rom_sha256_after"] = sha(ROM)
    payload["rom_unchanged"] = payload["rom_sha256_after"] == baseline
    payload["passed"] = bool(payload["passed"] and payload["rom_unchanged"])
    RESULT.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return 0 if payload["passed"] else 1


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception:
        OUT.mkdir(parents=True, exist_ok=True)
        (OUT / "error.log").write_text(traceback.format_exc(), encoding="utf-8")
        raise
