"""Enumerate the reachable legacy M08 battle-dialogue controls without saving."""

from __future__ import annotations

import hashlib
import json
import sys
import time
import ctypes
from pathlib import Path

import win32gui
from PIL import ImageGrab

REPO = Path(__file__).resolve().parents[2]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from tools.golden_pipeline_collect import Win32LegacyDriver

AUDIT = REPO / "output" / "build" / "legacy-diff-audit"
ROOT = REPO / "output" / "verification" / "legacy-ui-probe-m08-battle-20260920"
OUTPUT = ROOT / "M08_战斗对话完整控件.json"


def click_relative(hwnd: int, x: int, y: int) -> None:
    import win32api
    import win32con

    left, top, _right, _bottom = win32gui.GetWindowRect(hwnd)
    win32gui.SetForegroundWindow(hwnd)
    win32api.SetCursorPos((left + x, top + y))
    win32api.mouse_event(win32con.MOUSEEVENTF_LEFTDOWN, 0, 0)
    win32api.mouse_event(win32con.MOUSEEVENTF_LEFTUP, 0, 0)
    time.sleep(0.4)


def enumerate_controls(driver: Win32LegacyDriver, hwnd: int) -> list[dict[str, object]]:
    result: list[dict[str, object]] = []

    def visit(child: int, _extra: object) -> bool:
        class_name = win32gui.GetClassName(child)
        control_id = int(win32gui.GetDlgCtrlID(child))
        item: dict[str, object] = {
            "class": class_name,
            "text": win32gui.GetWindowText(child),
            "control_id": control_id,
            "rect": list(win32gui.GetWindowRect(child)),
            "visible": bool(win32gui.IsWindowVisible(child)),
            "enabled": bool(win32gui.IsWindowEnabled(child)),
        }
        if class_name in {"ComboBox", "ListBox"} and item["visible"]:
            try:
                control = driver._control(control_id, class_name)
                item["item_texts"] = list(control.item_texts())
                if class_name == "ComboBox":
                    item["selected_index"] = int(control.selected_index())
                else:
                    item["selected_indices"] = [
                        int(value) for value in control.selected_indices()
                    ]
            except Exception as error:
                item["enumeration_error"] = str(error)
        result.append(item)
        return True

    win32gui.EnumChildWindows(hwnd, visit, None)
    return result


def capture(driver: Win32LegacyDriver, hwnd: int, stem: str) -> dict[str, object]:
    ROOT.mkdir(parents=True, exist_ok=True)
    left, top, right, bottom = win32gui.GetWindowRect(hwnd)
    image = ImageGrab.grab(bbox=(left, top, right, bottom))
    path = ROOT / f"{stem}.png"
    image.save(path)
    return {
        "screenshot": path.relative_to(REPO).as_posix(),
        "pixel_sha256": hashlib.sha256(image.tobytes()).hexdigest(),
        "controls": enumerate_controls(driver, hwnd),
    }


def listbox_texts(hwnd: int) -> list[str]:
    count = int(win32gui.SendMessage(hwnd, 0x018B, 0, 0))  # LB_GETCOUNT
    result: list[str] = []
    for index in range(count):
        length = int(win32gui.SendMessage(hwnd, 0x018A, index, 0))  # LB_GETTEXTLEN
        if length < 0:
            raise RuntimeError(f"LB_GETTEXTLEN failed for item {index}")
        buffer = ctypes.create_unicode_buffer(length + 1)
        copied = int(win32gui.SendMessage(hwnd, 0x0189, index, buffer))  # LB_GETTEXT
        if copied < 0:
            raise RuntimeError(f"LB_GETTEXT failed for item {index}")
        result.append(buffer.value)
    return result


def main() -> int:
    driver = Win32LegacyDriver()
    baseline = AUDIT / "m05-reference-baseline.nes"
    before = baseline.read_bytes()
    try:
        pid = driver.launch(AUDIT / "SRW2_patched.exe", AUDIT)
        driver.open_rom(baseline)
        driver.perform(
            (
                {"op": "menu", "path": "数据->数据库"},
                {"op": "window", "title": "数据库"},
                {"op": "click_coords", "x": 310, "y": 73},
            ),
            0,
        )
        database = driver.current_window
        assert database is not None
        hwnd = int(database.handle)
        main_page = capture(driver, hwnd, "M08_战斗对话主页面")

        segment_samples: list[dict[str, object]] = []
        variant_counts: list[dict[str, object]] = []
        combo = driver._control(1410, "ComboBox")
        combo_items = list(combo.item_texts())
        for index in range(len(combo_items)):
            driver.perform(
                ({"op": "select_index_message", "class": "ComboBox", "control_id": 1410, "value": index},),
                0,
            )
            row_items = list(driver._control(1390, "ListBox").item_texts())
            segment_samples.append(
                {
                    "segment_index": index,
                    "segment_text": combo_items[index],
                    "row_count": len(row_items),
                    "first_rows": row_items[:3],
                    "last_rows": row_items[-3:],
                }
            )

            row_box = driver._control(1390, "ListBox")
            variant_box = driver._control(2580, "ListBox")
            parent = win32gui.GetParent(row_box.handle)
            counts: list[int] = []
            rows: list[dict[str, object]] = []
            for row in range(len(row_items)):
                selected = win32gui.SendMessage(row_box.handle, 0x0186, row, 0)
                if selected == -1:
                    raise RuntimeError(f"row {row} rejected in segment {combo_items[index]}")
                win32gui.SendMessage(parent, 0x0111, 1390 | (1 << 16), row_box.handle)
                time.sleep(0.02)
                variants = listbox_texts(int(variant_box.handle))
                counts.append(len(variants))
                rows.append(
                    {
                        "row": row,
                        "summary": row_items[row],
                        "variants": variants,
                    }
                )
            variant_counts.append(
                {
                    "segment_index": index,
                    "segment_text": combo_items[index],
                    "row_count": len(counts),
                    "variant_total": sum(counts),
                    "minimum_variants": min(counts),
                    "maximum_variants": max(counts),
                    "counts": counts,
                    "rows": rows,
                }
            )

        # Owner-drawn inner CPageControl: capture both header regions and keep
        # their visible control states. Coordinates are database-relative.
        views: list[dict[str, object]] = []
        for label, x in (("按列表", 475), ("按内容", 535)):
            click_relative(hwnd, x, 135)
            views.append({"probe": [x, 135], "label": label, **capture(driver, hwnd, f"M08_内页_{label}")})

        after = baseline.read_bytes()
        OUTPUT.write_text(
            json.dumps(
                {
                    "pid": pid,
                    "rom_unchanged": before == after,
                    "main_page": main_page,
                    "segment_count": len(combo_items),
                    "segments": segment_samples,
                    "variant_counts": variant_counts,
                    "variant_total": sum(item["variant_total"] for item in variant_counts),
                    "inner_views": views,
                },
                ensure_ascii=False,
                indent=2,
            )
            + "\n",
            encoding="utf-8",
        )
        print(OUTPUT)
        return 0
    finally:
        driver.stop()


if __name__ == "__main__":
    raise SystemExit(main())
