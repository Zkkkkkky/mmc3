"""Small Win32 helpers for the reference editor's owner-drawn map pages."""

from __future__ import annotations

import ctypes
import time
from ctypes import wintypes
from typing import Any

import win32con
import win32gui

from tools.research import legacy_ui_probe as ui


VK_DOWN = 0x28


def press(vk: int) -> None:
    ui.keybd(vk)
    time.sleep(0.07)
    ui.keybd(vk, up=True)
    time.sleep(0.12)


def select_main_page(driver: Any, page_index: int) -> None:
    """Select owner-drawn main page 0/1/2 by its verified 80px header."""

    main = driver._main()
    tree = ui.enum_child_tree(int(main.handle))
    pages = ui.find_controls(tree, cls="CPageControl")
    if len(pages) != 1:
        raise RuntimeError(f"main CPageControl matched {len(pages)}")
    main_rect = ui.get_window_rect(int(main.handle))
    page_rect = pages[0]["rect"]
    dx, dy = ui._client_offset(int(main.handle))
    screen_x = page_rect["left"] + 40 + page_index * 80
    screen_y = page_rect["top"] + 24
    point = (
        screen_x - main_rect["left"] - dx,
        screen_y - main_rect["top"] - dy,
    )
    for attempt in range(3):
        if ui.real_click_at(int(main.handle), *point):
            break
        ui.force_foreground(int(main.handle))
        time.sleep(0.25 * (attempt + 1))
    else:
        screen = wintypes.POINT(*point)
        ctypes.windll.user32.ClientToScreen(int(main.handle), ctypes.byref(screen))
        hit = int(ctypes.windll.user32.WindowFromPoint(screen))
        root = int(win32gui.GetAncestor(hit, win32con.GA_ROOT)) if hit else 0
        if root == int(main.handle):
            # Windows can deny SetForegroundWindow to a freshly launched
            # inventory process even though the verified point belongs to
            # that exact reference main window.  Targeted window messages
            # preserve the owner-drawn page click without risking input to a
            # foreign window.  A foreign root still fails closed below.
            ui.post_click_at(int(main.handle), *point)
            time.sleep(0.35)
            driver.current_window = driver._main()
            return
        raise RuntimeError(
            f"main page {page_index} click failed after 3 attempts; "
            f"main={int(main.handle)} screen=({screen.x},{screen.y}) "
            f"hit={hit}:{ui.get_class_name(hit)!r} "
            f"root={root}:{ui.get_class_name(root)!r}"
        )
    time.sleep(0.35)
    driver.current_window = driver._main()


def select_map(driver: Any, map_id: int) -> None:
    control = driver._control(100, "ListBox")
    control.select(map_id)
    time.sleep(0.3)


def map_control(driver: Any) -> Any:
    return driver._control(500)


def cell_size(width: int, height: int) -> int:
    # The reference editor keeps a fixed 20px cell even for 32x32 maps; its
    # 460x420 owner-drawn control is a clipped 23x21 viewport.
    return 20


def cell_client_point(driver: Any, x: int, y: int, width: int, height: int) -> tuple[int, int]:
    main = driver._main()
    target = map_control(driver)
    rect = target.rectangle()
    main_rect = ui.get_window_rect(int(main.handle))
    dx, dy = ui._client_offset(int(main.handle))
    size = cell_size(width, height)
    screen_x = int(rect.left) + x * size + size // 2
    screen_y = int(rect.top) + y * size + size // 2
    return screen_x - main_rect["left"] - dx, screen_y - main_rect["top"] - dy


def context_command(driver: Any, x: int, y: int, width: int, height: int, down_count: int) -> None:
    main = driver._main()
    point = cell_client_point(driver, x, y, width, height)
    for attempt in range(3):
        if ui.real_click_at(int(main.handle), *point, button="right"):
            break
        ui.force_foreground(int(main.handle))
        time.sleep(0.25 * (attempt + 1))
    else:
        screen = wintypes.POINT(*point)
        ctypes.windll.user32.ClientToScreen(int(main.handle), ctypes.byref(screen))
        hit = int(ctypes.windll.user32.WindowFromPoint(screen))
        root = int(ctypes.windll.user32.GetAncestor(hit, 2)) if hit else 0
        raise RuntimeError(
            f"map right click failed at ({x}, {y}) after 3 attempts; "
            f"main={int(main.handle)} screen=({screen.x},{screen.y}) "
            f"hit={hit}:{ui.get_class_name(hit)!r} "
            f"hit_pid={ui.window_pid(hit) if hit else 0} "
            f"hit_text={ui.get_window_text(hit)!r} "
            f"root={root}:{ui.get_class_name(root)!r} "
            f"root_pid={ui.window_pid(root) if root else 0} "
            f"root_text={ui.get_window_text(root)!r} "
            f"root_rect={ui.get_window_rect(root) if root else {}}"
        )
    time.sleep(0.25)
    for _ in range(down_count):
        press(VK_DOWN)
    press(ui.VK_RETURN)


def wait_dialog(driver: Any, title: str, timeout: float = 8.0) -> Any:
    dialog = driver._wait_window(lambda item: item.window_text() == title, timeout=timeout)
    driver.current_window = dialog
    return dialog


def combo(driver: Any, control_id: int) -> Any:
    return driver._control(control_id, "ComboBox")


def combo_index(driver: Any, control_id: int) -> int:
    return int(combo(driver, control_id).selected_index())


def set_combo(driver: Any, control_id: int, index: int) -> None:
    selected = combo(driver, control_id)
    count = len(selected.item_texts())
    if not 0 <= index < count:
        raise ValueError(f"combo {control_id} index {index} outside 0..{count - 1}")
    selected.select(index)
    time.sleep(0.12)


def click_button(driver: Any, control_id: int) -> None:
    driver._control(control_id, "Button").click()
    time.sleep(0.3)


def drag_cell(driver: Any, source: tuple[int, int], target: tuple[int, int], width: int, height: int) -> None:
    """Real left-button drag between two owner-drawn map cells."""

    main = driver._main()
    source_client = cell_client_point(driver, *source, width, height)
    target_client = cell_client_point(driver, *target, width, height)

    def to_screen(point: tuple[int, int]) -> tuple[int, int]:
        raw = wintypes.POINT(*point)
        if not ctypes.windll.user32.ClientToScreen(int(main.handle), ctypes.byref(raw)):
            raise RuntimeError("ClientToScreen failed during map drag")
        return raw.x, raw.y

    sx, sy = to_screen(source_client)
    tx, ty = to_screen(target_client)
    if not ui.force_foreground(int(main.handle)):
        raise RuntimeError("could not foreground reference main window for drag")
    ctypes.windll.user32.SetCursorPos(sx, sy)
    time.sleep(0.12)
    ctypes.windll.user32.mouse_event(ui.MOUSEEVENTF_LEFTDOWN, 0, 0, 0, 0)
    for step in range(1, 7):
        nx = sx + (tx - sx) * step // 6
        ny = sy + (ty - sy) * step // 6
        ctypes.windll.user32.SetCursorPos(nx, ny)
        time.sleep(0.04)
    ctypes.windll.user32.mouse_event(ui.MOUSEEVENTF_LEFTUP, 0, 0, 0, 0)
    time.sleep(0.35)


def save(driver: Any) -> None:
    driver.current_window = driver._main()
    driver.save()
    # The legacy save writes the ROM before its modal acknowledgement has
    # necessarily closed.  The generic driver can therefore return while an
    # owned #32770 still covers the map.  Dismiss only this process's visible
    # acknowledgement buttons and wait for the modal to disappear.
    deadline = time.monotonic() + 3.0
    while time.monotonic() < deadline:
        dialogs = [
            window
            for window in driver.app.windows(visible_only=True)
            if window.class_name() == "#32770"
        ]
        if not dialogs:
            break
        for dialog in dialogs:
            buttons = [
                button
                for button in dialog.descendants(class_name="Button")
                if button.window_text().replace("&", "") in {"确定", "是", "保存"}
            ]
            if buttons:
                buttons[0].click()
            else:
                win32gui.PostMessage(int(dialog.handle), win32con.WM_CLOSE, 0, 0)
        time.sleep(0.1)
    driver.current_window = driver._main()
    time.sleep(0.2)


def close_dialog_cancel(driver: Any, control_id: int) -> None:
    dialog = driver.current_window
    handle = int(dialog.handle)
    for attempt in range(3):
        driver.current_window = dialog
        click_button(driver, control_id)
        deadline = time.monotonic() + 1.5
        while time.monotonic() < deadline:
            if not win32gui.IsWindow(handle) or not win32gui.IsWindowVisible(handle):
                driver.current_window = driver._main()
                return
            time.sleep(0.1)
        ui.force_foreground(handle)
        time.sleep(0.2 * (attempt + 1))
    raise RuntimeError(
        f"dialog cancel button {control_id} did not close "
        f"{ui.get_window_text(handle)!r} after 3 attempts"
    )
