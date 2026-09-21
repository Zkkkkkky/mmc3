"""Enumerate M07 animation edit dialogs and instruction entry points read-only."""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path

import win32con
import win32gui
import win32process
from PIL import ImageGrab

REPO = Path(__file__).resolve().parents[2]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from tools.golden_pipeline_collect import Win32LegacyDriver

AUDIT = REPO / "output" / "build" / "legacy-diff-audit"
ROOT = REPO / "output" / "verification" / "legacy-ui-probe-m07-animation-20260920"
OUTPUT = ROOT / "M07_武器动画编辑入口.json"


def click_relative(hwnd: int, x: int, y: int) -> None:
    import win32api

    left, top, _right, _bottom = win32gui.GetWindowRect(hwnd)
    win32gui.SetForegroundWindow(hwnd)
    win32api.SetCursorPos((left + x, top + y))
    win32api.mouse_event(win32con.MOUSEEVENTF_LEFTDOWN, 0, 0)
    win32api.mouse_event(win32con.MOUSEEVENTF_LEFTUP, 0, 0)
    time.sleep(0.3)


def child_controls(hwnd: int) -> list[dict[str, object]]:
    result: list[dict[str, object]] = []

    def visit(child: int, _extra: object) -> bool:
        result.append(
            {
                "class": win32gui.GetClassName(child),
                "text": win32gui.GetWindowText(child),
                "control_id": int(win32gui.GetDlgCtrlID(child)),
                "rect": list(win32gui.GetWindowRect(child)),
                "visible": bool(win32gui.IsWindowVisible(child)),
                "enabled": bool(win32gui.IsWindowEnabled(child)),
            }
        )
        return True

    win32gui.EnumChildWindows(hwnd, visit, None)
    return result


def capture(hwnd: int, stem: str) -> dict[str, object]:
    ROOT.mkdir(parents=True, exist_ok=True)
    left, top, right, bottom = win32gui.GetWindowRect(hwnd)
    shot = ROOT / f"{stem}.png"
    ImageGrab.grab(bbox=(left, top, right, bottom)).save(shot)
    return {
        "title": win32gui.GetWindowText(hwnd),
        "class": win32gui.GetClassName(hwnd),
        "screenshot": shot.relative_to(REPO).as_posix(),
        "controls": child_controls(hwnd),
    }


def visible_process_windows(pid: int, excluded: set[int]) -> list[int]:
    result: list[int] = []

    def visit(hwnd: int, _extra: object) -> bool:
        try:
            _thread, owner_pid = win32process.GetWindowThreadProcessId(hwnd)
            if (
                owner_pid == pid
                and hwnd not in excluded
                and win32gui.IsWindowVisible(hwnd)
                and win32gui.GetWindowText(hwnd)
            ):
                result.append(hwnd)
        except Exception:
            pass
        return True

    win32gui.EnumWindows(visit, None)
    return result


def wait_modal(pid: int, excluded: set[int], timeout: float = 3.0) -> int | None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        found = visible_process_windows(pid, excluded)
        if found:
            return found[-1]
        time.sleep(0.1)
    return None


def cancel_modal(hwnd: int) -> None:
    for control_id in (2, 100, 110):
        child = win32gui.GetDlgItem(hwnd, control_id)
        if child and win32gui.IsWindowVisible(child):
            win32gui.PostMessage(child, 0x00F5, 0, 0)
            time.sleep(0.2)
            if not win32gui.IsWindow(hwnd) or not win32gui.IsWindowVisible(hwnd):
                return
    win32gui.PostMessage(hwnd, win32con.WM_CLOSE, 0, 0)
    time.sleep(0.2)


def list_items(driver: Win32LegacyDriver, control_id: int) -> list[str]:
    return list(driver._control(control_id, "ListBox").item_texts())


def open_code_dialog(
    driver: Win32LegacyDriver,
    database_hwnd: int,
    pid: int,
    page_x: int,
    stem: str,
) -> dict[str, object]:
    click_relative(database_hwnd, page_x, 294)
    excluded = {database_hwnd, int(driver._main().handle)}
    driver.perform(
        ({"op": "click_id_message", "class": "Button", "control_id": 2560},),
        0,
    )
    modal = wait_modal(pid, excluded, 4.0)
    if modal is None:
        return {"opened": False}
    payload = {"opened": True, **capture(modal, stem)}
    database = driver.current_window
    driver.current_window = driver.app.window(handle=modal)
    payload["value"] = driver.read(
        {"class": "Edit", "control_id": 1001, "value_type": "str"}
    )
    cancel_modal(modal)
    driver.current_window = database
    return payload


def double_click_row(
    driver: Win32LegacyDriver,
    database_hwnd: int,
    pid: int,
    control_id: int,
    row: int,
    stem: str,
) -> dict[str, object]:
    control = driver._control(control_id, "ListBox")
    control.select(row)
    hwnd = int(control.handle)
    parent = win32gui.GetParent(hwnd)
    excluded = {database_hwnd, int(driver._main().handle)}
    win32gui.SendMessage(parent, win32con.WM_COMMAND, control_id | (2 << 16), hwnd)
    modal = wait_modal(pid, excluded, 2.5)
    payload: dict[str, object] = {"row": row, "opened": modal is not None}
    if modal is not None:
        payload.update(capture(modal, stem))
        cancel_modal(modal)
    return payload


def main() -> int:
    driver = Win32LegacyDriver()
    before = (AUDIT / "m05-reference-baseline.nes").read_bytes()
    try:
        pid = driver.launch(AUDIT / "SRW2_patched.exe", AUDIT)
        driver.open_rom(AUDIT / "m05-reference-baseline.nes")
        driver.perform(
            (
                {"op": "menu", "path": "数据->数据库"},
                {"op": "window", "title": "数据库"},
                {"op": "click_coords", "x": 220, "y": 73},
                {"op": "list_select", "class": "ListBox", "control_id": 610, "row": 0},
            ),
            0,
        )
        database = driver.current_window
        assert database is not None
        database_hwnd = int(database.handle)

        ally_pointer = open_code_dialog(
            driver, database_hwnd, pid, 385, "M07_我方动画代码编辑"
        )
        enemy_pointer = open_code_dialog(
            driver, database_hwnd, pid, 490, "M07_敌方动画代码编辑"
        )

        driver.current_window = database
        click_relative(database_hwnd, 385, 294)
        ally_items = list_items(driver, 2530)
        instruction_dialogs = []
        for row in range(min(4, len(ally_items))):
            instruction_dialogs.append(
                {
                    "text": ally_items[row],
                    **double_click_row(
                        driver,
                        database_hwnd,
                        pid,
                        2530,
                        row,
                        f"M07_我方指令_{row:03d}",
                    ),
                }
            )

        enemy_samples: list[dict[str, object]] = []
        nonempty_enemy: dict[str, object] | None = None
        click_relative(database_hwnd, 490, 294)
        weapon_count = len(list_items(driver, 610))
        for weapon_row in range(weapon_count):
            driver.current_window = database
            driver.perform(
                ({"op": "list_select", "class": "ListBox", "control_id": 610, "row": weapon_row},),
                0,
            )
            items = list_items(driver, 2520)
            meaningful = [
                (index, text)
                for index, text in enumerate(items)
                if "空代码" not in text and "动画结束" not in text
            ]
            enemy_samples.append(
                {
                    "weapon_row": weapon_row,
                    "first_items": items[:8],
                    "meaningful_count": len(meaningful),
                }
            )
            if meaningful:
                row, text = meaningful[0]
                nonempty_enemy = {
                    "weapon_row": weapon_row,
                    "instruction_row": row,
                    "text": text,
                    **double_click_row(
                        driver,
                        database_hwnd,
                        pid,
                        2520,
                        row,
                        "M07_敌方首个可编辑指令",
                    ),
                }
                break

        after = (AUDIT / "m05-reference-baseline.nes").read_bytes()
        OUTPUT.write_text(
            json.dumps(
                {
                    "pid": pid,
                    "rom_unchanged": before == after,
                    "ally_pointer_dialog": ally_pointer,
                    "enemy_pointer_dialog": enemy_pointer,
                    "ally_instruction_dialogs": instruction_dialogs,
                    "enemy_samples": enemy_samples,
                    "nonempty_enemy_instruction": nonempty_enemy,
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
