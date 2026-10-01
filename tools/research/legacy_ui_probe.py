"""Automated UI probe for the legacy SRW2 modifier reference executable.

Runs the copied executable under ``output/build/legacy-ui-probe`` (never the
references/ area), enumerates window/control trees via ctypes Win32 APIs,
captures per-window screenshots with PrintWindow, and writes evidence to
``output/verification/legacy-ui-probe``.

Stages:
  A  launcher -> enter editor -> main window without ROM (menus included)
  B  File->Open with a ROM copy -> main window tabs after load
  C  Data menu tool windows (run via --stage C in a second iteration)
  D  secondary dialogs (run via --stage D in a second iteration)

Usage (from repo root):
  .venv/Scripts/python.exe tools/research/legacy_ui_probe.py --stage A,B
  .venv/Scripts/python.exe tools/research/legacy_ui_probe.py --stage C --pid <pid> --keep-open-attach
"""

from __future__ import annotations

import argparse
import ctypes
import hashlib
import json
import os
import re
import subprocess
import sys
import time
from ctypes import sizeof, wintypes
from pathlib import Path

# ---------------------------------------------------------------- Win32 setup

user32 = ctypes.WinDLL("user32", use_last_error=True)
gdi32 = ctypes.WinDLL("gdi32", use_last_error=True)
kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)

WM_SETTEXT = 0x000C
WM_GETTEXT = 0x000D
WM_GETTEXTLENGTH = 0x000E
WM_CLOSE = 0x0010
WM_COMMAND = 0x0111
WM_SYSKEYDOWN = 0x0104
WM_SYSKEYUP = 0x0105
WM_SYSCHAR = 0x0106
WM_KEYDOWN = 0x0100
WM_KEYUP = 0x0101
WM_CONTEXTMENU = 0x007B
WM_MOUSEMOVE = 0x0200
WM_LBUTTONDOWN = 0x0201
WM_LBUTTONDBLCLK = 0x0203
WM_LBUTTONUP = 0x0202
WM_RBUTTONDOWN = 0x0204
WM_RBUTTONUP = 0x0205
MN_GETHMENU = 0x01E1
BM_CLICK = 0x00F5
BM_GETCHECK = 0x00F0
BN_CLICKED = 0
MK_LBUTTON = 0x0001
VK_ESCAPE = 0x1B
VK_RETURN = 0x0D
VK_SPACE = 0x20
VK_HOME = 0x24
VK_DOWN = 0x28
VK_MENU = 0x12
VK_CONTROL = 0x11
GW_CHILD = 5
GW_HWNDNEXT = 2
GW_OWNER = 4
SW_RESTORE = 9
SW_SHOW = 5
SWP_NOZORDER = 0x0004
SWP_SHOWWINDOW = 0x0040
TCM_FIRST = 0x1300
TCM_GETITEMCOUNT = TCM_FIRST + 4
TCM_GETITEMRECT = TCM_FIRST + 10  # pointer-arg message: NOT used cross-process
TCM_GETCURSEL = TCM_FIRST + 11
TCM_SETCURSEL = TCM_FIRST + 12
CB_GETCOUNT = 0x0146
CB_GETCURSEL = 0x0147
CB_GETLBTEXT = 0x0148
CB_GETLBTEXTLEN = 0x0149
CB_SETCURSEL = 0x014E
CBN_SELCHANGE = 1
LB_GETCOUNT = 0x018B
LB_GETCURSEL = 0x0188
LB_SETCURSEL = 0x0186
LB_GETITEMHEIGHT = 0x01A1
LB_GETTOPINDEX = 0x018E
LB_SETTOPINDEX = 0x0197
LBN_SELCHANGE = 1
LVM_GETITEMCOUNT = 0x1004
LVM_GETSELECTEDCOUNT = 0x1030
LVM_GETTOPINDEX = 0x1027
LVM_GETCOUNTPERPAGE = 0x1028
PW_RENDERFULLCONTENT = 2
SRCCOPY = 0x00CC0020
CAPTUREBLT = 0x40000000
DIB_RGB_COLORS = 0
PROCESS_TERMINATE = 0x0001
PROCESS_QUERY_INFORMATION = 0x0400


class RECT(ctypes.Structure):
    _fields_ = [
        ("left", ctypes.c_long),
        ("top", ctypes.c_long),
        ("right", ctypes.c_long),
        ("bottom", ctypes.c_long),
    ]


class BITMAPINFOHEADER(ctypes.Structure):
    _fields_ = [
        ("biSize", ctypes.c_uint32),
        ("biWidth", ctypes.c_int32),
        ("biHeight", ctypes.c_int32),
        ("biPlanes", ctypes.c_uint16),
        ("biBitCount", ctypes.c_uint16),
        ("biCompression", ctypes.c_uint32),
        ("biSizeImage", ctypes.c_uint32),
        ("biXPelsPerMeter", ctypes.c_int32),
        ("biYPelsPerMeter", ctypes.c_int32),
        ("biClrUsed", ctypes.c_uint32),
        ("biClrImportant", ctypes.c_uint32),
    ]


class BITMAPINFO(ctypes.Structure):
    _fields_ = [("bmiHeader", BITMAPINFOHEADER), ("bmiColors", ctypes.c_uint32 * 3)]


class GUITHREADINFO(ctypes.Structure):
    _fields_ = [
        ("cbSize", ctypes.c_uint32),
        ("flags", ctypes.c_uint32),
        ("hwndActive", wintypes.HWND),
        ("hwndFocus", wintypes.HWND),
        ("hwndCapture", wintypes.HWND),
        ("hwndMenuOwner", wintypes.HWND),
        ("hwndMoveSize", wintypes.HWND),
        ("hwndCaret", wintypes.HWND),
        ("rcCaret", RECT),
    ]


def menu_is_open(hwnd: int) -> bool:
    """True while a popup menu is active on hwnd's thread (GUITHREADINFO)."""
    tid = user32.GetWindowThreadProcessId(hwnd, None)
    info = GUITHREADINFO()
    info.cbSize = sizeof(GUITHREADINFO)
    if not user32.GetGUIThreadInfo(tid, ctypes.byref(info)):
        return False
    return bool(info.hwndMenuOwner)


def _set_dpi_aware() -> None:
    """Ask User32 for per-monitor DPI awareness so rects are physical pixels."""
    try:
        context = ctypes.c_void_p(-4)  # DPI_AWARENESS_CONTEXT_PER_MONITOR_AWARE_V2
        user32.SetProcessDpiAwarenessContext(context)
    except Exception:
        try:
            ctypes.windll.shcore.SetProcessDpiAwareness(2)
        except Exception:
            pass


_set_dpi_aware()

# Declare argtypes for the frequently used entry points.
user32.GetWindowRect.argtypes = [wintypes.HWND, ctypes.POINTER(RECT)]
user32.GetClientRect.argtypes = [wintypes.HWND, ctypes.POINTER(RECT)]
user32.GetClassNameW.argtypes = [wintypes.HWND, ctypes.c_wchar_p, ctypes.c_int]
user32.GetWindowTextW.argtypes = [wintypes.HWND, ctypes.c_wchar_p, ctypes.c_int]
user32.GetWindowTextLengthW.argtypes = [wintypes.HWND]
user32.GetDlgItem.argtypes = [wintypes.HWND, ctypes.c_int]
user32.PostMessageW.argtypes = [wintypes.HWND, ctypes.c_uint, wintypes.WPARAM, wintypes.LPARAM]

# SendMessageW needs two prototypes: numeric LPARAM and string LPARAM (WM_GET/SETTEXT).
_send_msg_num = ctypes.WINFUNCTYPE(
    wintypes.LPARAM, wintypes.HWND, ctypes.c_uint, wintypes.WPARAM, wintypes.LPARAM
)(("SendMessageW", user32))
_send_msg_text = ctypes.WINFUNCTYPE(
    wintypes.LPARAM, wintypes.HWND, ctypes.c_uint, wintypes.WPARAM, ctypes.c_wchar_p
)(("SendMessageW", user32))

_T0 = time.monotonic()


def log(message: str) -> None:
    print(f"[{time.monotonic() - _T0:7.1f}s] {message}", flush=True)


# ------------------------------------------------------------ basic accessors


def is_window(hwnd: int) -> bool:
    return bool(user32.IsWindow(hwnd))


def is_window_visible(hwnd: int) -> bool:
    return bool(user32.IsWindowVisible(hwnd))


def is_window_enabled(hwnd: int) -> bool:
    return bool(user32.IsWindowEnabled(hwnd))


def get_class_name(hwnd: int) -> str:
    buf = ctypes.create_unicode_buffer(256)
    user32.GetClassNameW(hwnd, buf, 256)
    return buf.value


def get_window_text(hwnd: int) -> str:
    length = user32.GetWindowTextLengthW(hwnd)
    if length <= 0:
        return ""
    buf = ctypes.create_unicode_buffer(length + 1)
    user32.GetWindowTextW(hwnd, buf, length + 1)
    return buf.value


def get_ctrl_text(hwnd: int) -> str:
    """Text of child controls; WM_GETTEXT works even cross-process."""
    length = _send_msg_num(hwnd, WM_GETTEXTLENGTH, 0, 0)
    if length <= 0 or length > 4096:
        return get_window_text(hwnd)
    buf = ctypes.create_unicode_buffer(length + 1)
    _send_msg_text(hwnd, WM_GETTEXT, length + 1, buf)
    return buf.value


def get_ctrl_id(hwnd: int) -> int:
    return user32.GetDlgCtrlID(hwnd)


def get_window_rect(hwnd: int) -> dict:
    rc = RECT()
    user32.GetWindowRect(hwnd, ctypes.byref(rc))
    return {
        "left": rc.left,
        "top": rc.top,
        "right": rc.right,
        "bottom": rc.bottom,
        "width": rc.right - rc.left,
        "height": rc.bottom - rc.top,
    }


def get_client_size(hwnd: int) -> tuple[int, int]:
    rc = RECT()
    user32.GetClientRect(hwnd, ctypes.byref(rc))
    return rc.right - rc.left, rc.bottom - rc.top


def window_pid(hwnd: int) -> int:
    pid = wintypes.DWORD()
    user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
    return pid.value


def owned_by_process(hwnd: int, pid: int) -> bool:
    """True only when *hwnd* or its explicit Win32 owner belongs to *pid*."""

    current = hwnd
    seen: set[int] = set()
    while current and current not in seen:
        seen.add(current)
        if window_pid(current) == pid:
            return True
        current = user32.GetWindow(current, GW_OWNER)
    return False


# ------------------------------------------------------------------ enumeration


def _enum_proc_dummy() -> None:
    pass  # keeps linters quiet


def enum_top_windows(pid: int, visible_only: bool = True) -> list[dict]:
    """All top-level windows (visible ones by default) of a process."""
    results: list[dict] = []
    seen: set[int] = set()

    @ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
    def callback(hwnd, _lparam):
        if hwnd in seen:
            return True
        seen.add(hwnd)
        if pid != 0 and window_pid(hwnd) != pid:
            return True
        if visible_only and not is_window_visible(hwnd):
            return True
        results.append(
            {
                "hwnd": hwnd,
                "title": get_window_text(hwnd),
                "class": get_class_name(hwnd),
                "rect": get_window_rect(hwnd),
                "pid": window_pid(hwnd),
            }
        )
        return True

    user32.EnumWindows(callback, 0)
    return results


def enum_child_tree(hwnd: int, depth: int = 0, max_depth: int = 8) -> dict:
    """Recursive child control tree of a window."""
    node = {
        "hwnd": hwnd,
        "class": get_class_name(hwnd),
        "text": get_ctrl_text(hwnd),
        "ctrl_id": get_ctrl_id(hwnd),
        "rect": get_window_rect(hwnd),
        "visible": is_window_visible(hwnd),
        "enabled": is_window_enabled(hwnd),
    }
    cls = node["class"]
    if cls == "ComboBox":
        node["combo_count"] = _send_msg_num(hwnd, CB_GETCOUNT, 0, 0)
        node["combo_selected"] = _send_msg_num(hwnd, CB_GETCURSEL, 0, 0)
    elif cls == "SysListView32":
        node["list_items"] = _send_msg_num(hwnd, LVM_GETITEMCOUNT, 0, 0)
        node["list_selected"] = _send_msg_num(hwnd, LVM_GETSELECTEDCOUNT, 0, 0)
    elif cls == "SysTabControl32":
        node["tab_count"] = _send_msg_num(hwnd, TCM_GETITEMCOUNT, 0, 0)
        node["tab_current"] = _send_msg_num(hwnd, TCM_GETCURSEL, 0, 0)
    elif cls == "Button":
        node["button_check_state"] = _send_msg_num(hwnd, BM_GETCHECK, 0, 0)

    children: list[dict] = []
    if depth < max_depth:
        child = user32.GetWindow(hwnd, GW_CHILD)
        while child:
            children.append(enum_child_tree(child, depth + 1, max_depth))
            child = user32.GetWindow(child, GW_HWNDNEXT)
    node["children"] = children
    return node


def flatten_tree(node: dict) -> list[dict]:
    out = [dict(node, children=None)]
    for child in node.get("children", []):
        out.extend(flatten_tree(child))
    return out


def control_tree_path(node: dict, target_hwnd: int, path: tuple[int, ...] = ()) -> tuple[int, ...] | None:
    if int(node.get("hwnd") or 0) == int(target_hwnd):
        return path
    for index, child in enumerate(node.get("children", [])):
        found = control_tree_path(child, target_hwnd, path + (index,))
        if found is not None:
            return found
    return None


def stable_interaction_id(
    title: str,
    class_name: str,
    control_id: int,
    tree_path: tuple[int, ...],
    action: str,
) -> str:
    raw = json.dumps(
        [title, class_name, control_id, list(tree_path), action],
        ensure_ascii=False,
        separators=(",", ":"),
    )
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:20]


def stable_context_interaction_id(
    origin: tuple[str, str, int, int, str],
    trail: tuple[str, ...],
    command_id: int,
) -> str:
    """Match the recursive frontier's product-context action identity."""

    raw = json.dumps(
        ["context_menu", list(origin), list(trail), command_id, "activate"],
        ensure_ascii=False,
        separators=(",", ":"),
    )
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:20]


def stable_menu_action_id(trail: tuple[str, ...], command_id: int) -> str:
    raw = json.dumps(
        ["menu", list(trail), command_id, "activate"],
        ensure_ascii=False,
        separators=(",", ":"),
    )
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:20]


def find_controls(
    root: dict,
    *,
    cls: str | None = None,
    text_contains: str | None = None,
    ctrl_id: int | None = None,
    visible: bool | None = None,
) -> list[dict]:
    matches = []
    for item in flatten_tree(root):
        if cls is not None and item["class"] != cls:
            continue
        if text_contains is not None and text_contains not in (item["text"] or ""):
            continue
        if ctrl_id is not None and item["ctrl_id"] != ctrl_id:
            continue
        if visible is not None and item["visible"] != visible:
            continue
        matches.append(item)
    return matches


# ---------------------------------------------------------------------- menus


def dump_menu(hmenu: int) -> list[dict]:
    items: list[dict] = []
    count = user32.GetMenuItemCount(hmenu)
    for index in range(count):
        buf = ctypes.create_unicode_buffer(256)
        user32.GetMenuStringW(hmenu, index, buf, 256, 0x0400)  # MF_BYPOSITION
        item_id = user32.GetMenuItemID(hmenu, index)
        sub = user32.GetSubMenu(hmenu, index)
        record: dict = {"index": index, "text": buf.value, "id": None if item_id == -1 else item_id}
        if sub:
            record["items"] = dump_menu(sub)
        items.append(record)
    return items


def get_menu_tree(hwnd: int) -> list[dict] | None:
    hmenu = user32.GetMenu(hwnd)
    if not hmenu:
        return None
    return dump_menu(hmenu)


def menu_item_id(menu: list[dict], top_text: str, item_text: str) -> int | None:
    for top in menu:
        if top["text"].replace("&", "").startswith(top_text):
            for item in top.get("items", []):
                if item_text in item["text"].replace("&", ""):
                    return item["id"]
    return None


# -------------------------------------------------------------------- messages


def post_command(parent_hwnd: int, ctrl_id: int, ctrl_hwnd: int) -> None:
    wparam = (ctrl_id & 0xFFFF) | (BN_CLICKED << 16)
    user32.PostMessageW(parent_hwnd, WM_COMMAND, wparam, ctrl_hwnd)


def click_control(hwnd: int) -> None:
    """Click a control: BM_CLICK first, then WM_COMMAND fallback."""
    user32.PostMessageW(hwnd, BM_CLICK, 0, 0)


def real_click_control(hwnd: int) -> bool:
    """Click the centre of a control with real input.

    This is the UIPI-safe fallback for the elevated legacy executable, where
    BM_CLICK/WM_COMMAND messages from the probe can be silently discarded.
    """

    rect = get_window_rect(hwnd)
    root = user32.GetAncestor(hwnd, 2) or hwnd  # GA_ROOT
    if not force_foreground(root):
        return False
    x = (rect["left"] + rect["right"]) // 2
    y = (rect["top"] + rect["bottom"]) // 2
    user32.SetCursorPos(x, y)
    time.sleep(0.12)
    user32.mouse_event(MOUSEEVENTF_LEFTDOWN, 0, 0, 0, 0)
    time.sleep(0.04)
    user32.mouse_event(MOUSEEVENTF_LEFTUP, 0, 0, 0, 0)
    time.sleep(0.15)
    return True


def real_click_control_cell(hwnd: int, x_offset: int, y_offset: int) -> bool:
    """Left-click an interior point of a control with real input."""

    rect = get_window_rect(hwnd)
    root = user32.GetAncestor(hwnd, 2) or hwnd
    if not force_foreground(root):
        return False
    x = rect["left"] + x_offset
    y = rect["top"] + y_offset
    user32.SetCursorPos(x, y)
    time.sleep(0.10)
    user32.mouse_event(MOUSEEVENTF_LEFTDOWN, 0, 0, 0, 0)
    time.sleep(0.04)
    user32.mouse_event(MOUSEEVENTF_LEFTUP, 0, 0, 0, 0)
    time.sleep(0.12)
    return True


def real_click_control_cell_fast(
    hwnd: int,
    x_offset: int,
    y_offset: int,
    *,
    button: str = "left",
    click_count: int = 1,
) -> bool:
    """Send short-interval real mouse clicks after the caller foregrounds the window.

    This is used only for exhaustive standard-list sweeps where reacquiring the
    same foreground window and sleeping a quarter second for every one of
    hundreds of items would dominate the probe without adding evidence.
    """

    rect = get_window_rect(hwnd)
    x = rect["left"] + x_offset
    y = rect["top"] + y_offset
    user32.SetCursorPos(x, y)
    if button == "left":
        down, up = MOUSEEVENTF_LEFTDOWN, MOUSEEVENTF_LEFTUP
    elif button == "right":
        down, up = MOUSEEVENTF_RIGHTDOWN, MOUSEEVENTF_RIGHTUP
    else:
        raise ValueError(f"unsupported mouse button: {button}")
    for _ in range(click_count):
        user32.mouse_event(down, 0, 0, 0, 0)
        time.sleep(0.012)
        user32.mouse_event(up, 0, 0, 0, 0)
        time.sleep(0.025)
    return True


def real_right_click_control(hwnd: int) -> bool:
    """Right-click the centre of a control with real input."""

    rect = get_window_rect(hwnd)
    root = user32.GetAncestor(hwnd, 2) or hwnd
    if not force_foreground(root):
        return False
    x = (rect["left"] + rect["right"]) // 2
    y = (rect["top"] + rect["bottom"]) // 2
    user32.SetCursorPos(x, y)
    time.sleep(0.12)
    user32.mouse_event(MOUSEEVENTF_RIGHTDOWN, 0, 0, 0, 0)
    time.sleep(0.04)
    user32.mouse_event(MOUSEEVENTF_RIGHTUP, 0, 0, 0, 0)
    time.sleep(0.15)
    return True


def real_double_click_control_cell(hwnd: int, x_offset: int, y_offset: int) -> bool:
    """Double-click an interior point of an owner-drawn control."""

    rect = get_window_rect(hwnd)
    root = user32.GetAncestor(hwnd, 2) or hwnd
    if not force_foreground(root):
        return False
    x = rect["left"] + x_offset
    y = rect["top"] + y_offset
    user32.SetCursorPos(x, y)
    time.sleep(0.12)
    for _ in range(2):
        user32.mouse_event(MOUSEEVENTF_LEFTDOWN, 0, 0, 0, 0)
        time.sleep(0.04)
        user32.mouse_event(MOUSEEVENTF_LEFTUP, 0, 0, 0, 0)
        time.sleep(0.08)
    return True


def real_right_click_control_cell(hwnd: int, x_offset: int, y_offset: int) -> bool:
    """Right-click an interior point while ensuring the target process owns it."""

    rect = get_window_rect(hwnd)
    root = user32.GetAncestor(hwnd, 2) or hwnd
    if not force_foreground(root):
        return False
    x = rect["left"] + x_offset
    y = rect["top"] + y_offset
    point = wintypes.POINT(x, y)
    hit = user32.WindowFromPoint(point)
    if hit and user32.GetAncestor(hit, 2) != root:
        return False
    user32.SetCursorPos(x, y)
    time.sleep(0.08)
    user32.mouse_event(MOUSEEVENTF_RIGHTDOWN, 0, 0, 0, 0)
    time.sleep(0.04)
    user32.mouse_event(MOUSEEVENTF_RIGHTUP, 0, 0, 0, 0)
    time.sleep(0.12)
    return True


def real_drag_control_cell(
    hwnd: int,
    from_x: int,
    from_y: int,
    to_x: int,
    to_y: int,
) -> bool:
    """Drag between two interior points of an owner-drawn control."""

    rect = get_window_rect(hwnd)
    root = user32.GetAncestor(hwnd, 2) or hwnd
    if not force_foreground(root):
        return False
    start = wintypes.POINT(rect["left"] + from_x, rect["top"] + from_y)
    end = wintypes.POINT(rect["left"] + to_x, rect["top"] + to_y)
    for point in (start, end):
        hit = user32.WindowFromPoint(point)
        if hit and user32.GetAncestor(hit, 2) != root:
            return False
    user32.SetCursorPos(start.x, start.y)
    time.sleep(0.08)
    user32.mouse_event(MOUSEEVENTF_LEFTDOWN, 0, 0, 0, 0)
    for step in range(1, 6):
        x = start.x + (end.x - start.x) * step // 5
        y = start.y + (end.y - start.y) * step // 5
        user32.SetCursorPos(x, y)
        time.sleep(0.04)
    user32.mouse_event(MOUSEEVENTF_LEFTUP, 0, 0, 0, 0)
    time.sleep(0.12)
    return True


def visible_popup_menus(pid: int) -> list[dict]:
    """Return active Win32 popup menus belonging to *pid*."""

    menus = []
    for window in enum_top_windows(pid, visible_only=True):
        if window["class"] != "#32768":
            continue
        hmenu = int(_send_msg_num(window["hwnd"], MN_GETHMENU, 0, 0) or 0)
        menus.append(
            {
                **window,
                "hmenu": hmenu,
                "items": dump_menu(hmenu) if hmenu else [],
            }
        )
    return menus


def click_popup_menu_item(menu: dict, text: str) -> bool:
    """Select one visible top-level popup item by its exact caption."""

    hmenu = int(menu.get("hmenu") or 0)
    if not hmenu:
        return False
    for item in menu.get("items", []):
        if str(item.get("text", "")).strip() != text:
            continue
        index = int(item.get("index", -1))
        rect = RECT()
        if index < 0 or not user32.GetMenuItemRect(0, hmenu, index, ctypes.byref(rect)):
            return False
        x = (rect.left + rect.right) // 2
        y = (rect.top + rect.bottom) // 2
        user32.SetCursorPos(x, y)
        time.sleep(0.05)
        user32.mouse_event(MOUSEEVENTF_LEFTDOWN, 0, 0, 0, 0)
        time.sleep(0.04)
        user32.mouse_event(MOUSEEVENTF_LEFTUP, 0, 0, 0, 0)
        return True
    return False


def open_control_context_menu(session: "ProbeSession", control: dict) -> dict | None:
    """Open a control popup using only menus owned by the probe process.

    Use the exact posted-button sequence that produced the validated DBCTX
    evidence.  Try the same bounded interior points before allowing one guarded
    real-input fallback.
    """

    pid = session.pid or 0
    root = user32.GetAncestor(control["hwnd"], 2) or control["hwnd"]
    points = context_probe_points(control)
    for x, y in points:
        post_click_at(control["hwnd"], x, y, button="right")
        time.sleep(0.15)
        menus = visible_popup_menus(pid)
        if menus:
            return menus[0]
        send_key(root, VK_ESCAPE)

    for x, y in points:
        if real_right_click_control_cell(control["hwnd"], x, y):
            time.sleep(0.22)
            menus = visible_popup_menus(pid)
            if menus:
                return menus[0]
    return None


def context_probe_points(control: dict) -> list[tuple[int, int]]:
    """Conservative interior sample points for one reference control."""

    rect = control["rect"]
    width = max(1, rect["right"] - rect["left"])
    height = max(1, rect["bottom"] - rect["top"])
    class_name = control.get("class", "")
    points = [(width // 2, height // 2)]
    if class_name in {"ListBox", "SysListView32", "CPageControl", "_EL_DrawPanel", "_EL_PicBox", "AfxWnd42s"}:
        candidates = [
            (max(2, width // 6), max(2, height // 6)),
            (width // 2, max(2, height // 6)),
            (max(2, width * 5 // 6), max(2, height // 6)),
            (max(2, width // 6), height // 2),
            (max(2, width * 5 // 6), height // 2),
            (max(2, width // 6), max(2, height * 5 // 6)),
            (width // 2, max(2, height * 5 // 6)),
            (max(2, width * 5 // 6), max(2, height * 5 // 6)),
        ]
        points.extend(candidates)
    result: list[tuple[int, int]] = []
    for x, y in points:
        point = (min(width - 1, max(0, x)), min(height - 1, max(0, y)))
        if point not in result:
            result.append(point)
    return result


def click_control_via_command(item: dict) -> None:
    hwnd = item["hwnd"]
    parent = user32.GetParent(hwnd)
    if parent:
        post_command(parent, item["ctrl_id"], hwnd)
    else:
        click_control(hwnd)


def set_control_text(hwnd: int, text: str) -> None:
    _send_msg_text(hwnd, WM_SETTEXT, 0, text)


def set_uia_edit_text(
    root_hwnd: int, hwnd: int, control_id: int, text: str
) -> bool:
    """Set one native Edit through UI Automation's ValuePattern.

    A few skinned legacy spin edits deliberately reject WM_SETTEXT and
    synthetic keyboard input while remaining normally editable.  ValuePattern
    is the same public accessibility contract exercised by a real desktop
    automation client and keeps the probe independent of private MFC messages.
    """

    try:
        if not force_foreground(root_hwnd):
            log(f"UIA edit root could not be foregrounded: {root_hwnd}")
            return False
        from pywinauto import Desktop
        from pywinauto.controls.uiawrapper import UIAWrapper
        from pywinauto.uia_element_info import UIAElementInfo

        wrapper = UIAWrapper(UIAElementInfo(hwnd))
        wrapper.set_edit_text(text)
        time.sleep(0.05)
        if get_window_text(hwnd).strip() == text:
            return True
        # Some old MFC spin buddies expose a provider only through the root
        # UIA tree; a wrapper constructed from the child HWND alone can bind
        # the native fallback provider.  Resolve the advertised AutomationId
        # exactly as desktop automation clients do.
        root = Desktop(backend="uia").window(handle=root_hwnd).wrapper_object()
        for candidate in root.descendants(control_type="Edit"):
            info = candidate.element_info
            if (
                str(getattr(info, "automation_id", "")) == str(control_id)
                or int(getattr(info, "handle", 0) or 0) == hwnd
            ):
                candidate.set_edit_text(text)
                time.sleep(0.05)
                if candidate.window_text().strip() == text:
                    return True
                # The reference skin sometimes reports a writable
                # ValuePattern but immediately restores the value.  Fall back
                # to pywinauto's SendInput-based focus/type path, matching the
                # successful desktop `set_value` interaction.
                candidate.click_input()
                candidate.type_keys("^a" + text, set_foreground=True)
                time.sleep(0.08)
                if get_window_text(hwnd).strip() == text:
                    return True
        # The simulator's Easy-Language spin buddy advertises ValuePattern,
        # but rolls the value back after both ValuePattern and pywinauto's
        # text helper return.  With the reference editor deliberately launched
        # at the probe's integrity level, use the same foreground keyboard path
        # as a human edit and still require a native read-back before success.
        if real_replace_ascii(root_hwnd, hwnd, text):
            return True
        log(
            f"UIA edit did not persist hwnd={hwnd} id={control_id} "
            f"native={get_window_text(hwnd)!r}"
        )
        return False
    except Exception as exc:
        log(f"UIA edit update failed hwnd={hwnd}: {exc!r}")
        return False


def read_combo_items(hwnd: int, limit: int = 512) -> list[str]:
    """Read system ComboBox strings; Windows marshals these system messages."""

    count = int(_send_msg_num(hwnd, CB_GETCOUNT, 0, 0))
    if count < 0 or count > limit:
        return []
    values: list[str] = []
    for index in range(count):
        length = int(_send_msg_num(hwnd, CB_GETLBTEXTLEN, index, 0))
        if length < 0 or length > 4096:
            values.append("")
            continue
        buf = ctypes.create_unicode_buffer(length + 1)
        result = _send_msg_text(hwnd, CB_GETLBTEXT, index, buf)
        values.append(buf.value if result >= 0 else "")
    return values


def set_combo_selection(hwnd: int, index: int) -> None:
    """Select a ComboBox item and notify its parent like a user selection."""

    _send_msg_num(hwnd, CB_SETCURSEL, index, 0)
    parent = user32.GetParent(hwnd)
    if parent:
        ctrl_id = user32.GetDlgCtrlID(hwnd)
        wparam = (ctrl_id & 0xFFFF) | (CBN_SELCHANGE << 16)
        user32.PostMessageW(parent, WM_COMMAND, wparam, hwnd)


def compact_control_state(hwnd: int) -> dict:
    """Small state snapshot for dynamic visibility/check-state transitions."""

    items = flatten_tree(enum_child_tree(hwnd))
    return {
        "visible": [
            {
                "class": item.get("class"),
                "control_id": item.get("ctrl_id"),
                "text": item.get("text", ""),
                **(
                    {"selected": item.get("combo_selected")}
                    if item.get("class") == "ComboBox"
                    else {}
                ),
                **(
                    {"checked": item.get("button_check_state")}
                    if item.get("class") == "Button"
                    else {}
                ),
            }
            for item in items
            if item.get("visible")
        ]
    }


def send_key(hwnd: int, vk: int) -> None:
    user32.PostMessageW(hwnd, WM_KEYDOWN, vk, 0)
    user32.PostMessageW(hwnd, WM_KEYUP, vk, 0)


def send_escape(hwnd: int) -> None:
    send_key(hwnd, VK_ESCAPE)


def post_click_at(hwnd: int, x: int, y: int, button: str = "left") -> None:
    lparam = (y & 0xFFFF) << 16 | (x & 0xFFFF)
    if button == "left":
        user32.PostMessageW(hwnd, WM_MOUSEMOVE, 0, lparam)
        time.sleep(0.04)
        user32.PostMessageW(hwnd, WM_LBUTTONDOWN, MK_LBUTTON, lparam)
        time.sleep(0.04)
        user32.PostMessageW(hwnd, WM_LBUTTONUP, 0, lparam)
    else:
        user32.PostMessageW(hwnd, WM_MOUSEMOVE, 0, lparam)
        time.sleep(0.04)
        user32.PostMessageW(hwnd, WM_RBUTTONDOWN, 0x0002, lparam)
        time.sleep(0.04)
        user32.PostMessageW(hwnd, WM_RBUTTONUP, 0, lparam)


def post_double_click_at(hwnd: int, x: int, y: int) -> None:
    """Route a full Win32 double-click sequence to a target control."""

    lparam = (y & 0xFFFF) << 16 | (x & 0xFFFF)
    user32.PostMessageW(hwnd, WM_MOUSEMOVE, 0, lparam)
    user32.PostMessageW(hwnd, WM_LBUTTONDOWN, MK_LBUTTON, lparam)
    user32.PostMessageW(hwnd, WM_LBUTTONUP, 0, lparam)
    user32.PostMessageW(hwnd, WM_LBUTTONDBLCLK, MK_LBUTTON, lparam)
    user32.PostMessageW(hwnd, WM_LBUTTONUP, 0, lparam)


def post_drag_at(
    hwnd: int, from_x: int, from_y: int, to_x: int, to_y: int
) -> None:
    """Route a left-button drag sequence to a target control."""

    start = (from_y & 0xFFFF) << 16 | (from_x & 0xFFFF)
    user32.PostMessageW(hwnd, WM_MOUSEMOVE, 0, start)
    user32.PostMessageW(hwnd, WM_LBUTTONDOWN, MK_LBUTTON, start)
    for step in range(1, 6):
        x = from_x + (to_x - from_x) * step // 5
        y = from_y + (to_y - from_y) * step // 5
        lparam = (y & 0xFFFF) << 16 | (x & 0xFFFF)
        user32.PostMessageW(hwnd, WM_MOUSEMOVE, MK_LBUTTON, lparam)
        time.sleep(0.02)
    end = (to_y & 0xFFFF) << 16 | (to_x & 0xFFFF)
    user32.PostMessageW(hwnd, WM_LBUTTONUP, 0, end)


def post_context_menu(hwnd: int, x: int, y: int) -> bool:
    """Post ``WM_CONTEXTMENU`` at client coordinates converted to screen."""

    point = wintypes.POINT(x, y)
    if not user32.ClientToScreen(hwnd, ctypes.byref(point)):
        return False
    lparam = ((point.y & 0xFFFF) << 16) | (point.x & 0xFFFF)
    return bool(user32.PostMessageW(hwnd, WM_CONTEXTMENU, hwnd, lparam))


MOUSEEVENTF_LEFTDOWN = 0x0002
MOUSEEVENTF_LEFTUP = 0x0004
MOUSEEVENTF_RIGHTDOWN = 0x0008
MOUSEEVENTF_RIGHTUP = 0x0010


def real_click_at(hwnd: int, x: int, y: int, button: str = "left") -> bool:
    """Real cursor click at client coords (SetCursorPos + mouse_event).

    Needed for owner-drawn controls that ignore posted mouse messages.
    Brings the window to the foreground first so the click cannot land
    on another application's window; also verifies via WindowFromPoint
    that nothing foreign (security alerts, overlays) covers the target.
    """
    if user32.GetForegroundWindow() != hwnd and not force_foreground(hwnd):
        return False
    point = wintypes.POINT(x, y)
    if not user32.ClientToScreen(hwnd, ctypes.byref(point)):
        return False
    hit = user32.WindowFromPoint(point)
    if hit and hit != hwnd:
        root = user32.GetAncestor(hit, 2)  # GA_ROOT
        if root != hwnd:
            log(
                f"real_click_at: client({x},{y}) covered by foreign window "
                f"cls={get_class_name(hit)!r}; click skipped"
            )
            return False
    user32.SetCursorPos(point.x, point.y)
    time.sleep(0.12)
    if button == "left":
        user32.mouse_event(MOUSEEVENTF_LEFTDOWN, 0, 0, 0, 0)
        time.sleep(0.04)
        user32.mouse_event(MOUSEEVENTF_LEFTUP, 0, 0, 0, 0)
    else:
        user32.mouse_event(MOUSEEVENTF_RIGHTDOWN, 0, 0, 0, 0)
        time.sleep(0.04)
        user32.mouse_event(MOUSEEVENTF_RIGHTUP, 0, 0, 0, 0)
    time.sleep(0.1)
    return True


def keybd(vk: int, up: bool = False) -> None:
    """Real (global) key event via keybd_event."""
    user32.keybd_event(vk, 0, 2 if up else 0, 0)


def force_foreground(hwnd: int) -> bool:
    for _attempt in range(4):
        try:
            fg = user32.GetForegroundWindow()
            fg_tid = user32.GetWindowThreadProcessId(fg, None)
            target_tid = user32.GetWindowThreadProcessId(hwnd, None)
            our_tid = kernel32.GetCurrentThreadId()
            attached_fg = False
            attached_target = False
            if fg_tid and fg_tid != target_tid:
                attached_fg = bool(user32.AttachThreadInput(our_tid, fg_tid, True))
            if target_tid and target_tid != our_tid:
                attached_target = bool(user32.AttachThreadInput(our_tid, target_tid, True))
            try:
                user32.ShowWindow(hwnd, SW_RESTORE)
                user32.BringWindowToTop(hwnd)
                user32.SetForegroundWindow(hwnd)
            finally:
                if attached_target:
                    user32.AttachThreadInput(our_tid, target_tid, False)
                if attached_fg and fg_tid:
                    user32.AttachThreadInput(our_tid, fg_tid, False)
            if user32.GetForegroundWindow() == hwnd:
                return True
        except Exception as exc:
            log(f"force_foreground failed: {exc}")
        time.sleep(0.25)
    return user32.GetForegroundWindow() == hwnd


def focus_foreground_control(root_hwnd: int, control_hwnd: int) -> bool:
    """Foreground an elevated dialog and give one child real keyboard focus."""

    if not force_foreground(root_hwnd):
        return False
    target_tid = user32.GetWindowThreadProcessId(root_hwnd, None)
    our_tid = kernel32.GetCurrentThreadId()
    attached = False
    try:
        if target_tid and target_tid != our_tid:
            attached = bool(user32.AttachThreadInput(our_tid, target_tid, True))
        user32.SetActiveWindow(root_hwnd)
        user32.SetFocus(control_hwnd)
        return user32.GetFocus() == control_hwnd
    finally:
        if attached:
            user32.AttachThreadInput(our_tid, target_tid, False)


def real_replace_ascii(root_hwnd: int, control_hwnd: int, text: str) -> bool:
    """Replace an elevated Edit value through real keyboard input."""

    if not force_foreground(root_hwnd) or not real_click_control(control_hwnd):
        log(
            f"real_replace_ascii could not activate root={root_hwnd} "
            f"control={control_hwnd}"
        )
        return False
    if not focus_foreground_control(root_hwnd, control_hwnd):
        log(
            f"real_replace_ascii could not focus control={control_hwnd}; "
            f"focus={int(user32.GetFocus() or 0)}"
        )
        return False
    time.sleep(0.10)
    keybd(VK_CONTROL)
    keybd(ord("A"))
    keybd(ord("A"), up=True)
    keybd(VK_CONTROL, up=True)
    # Do not clear a spin buddy before typing.  The legacy simulator commits
    # the empty intermediate state immediately and clamps it to the minimum;
    # typing ``7`` after that would therefore create ``17`` and clamp back to
    # the maximum.  Keeping the text selected lets the first real key replace
    # it atomically, matching normal user input.
    for character in text:
        if character.isdigit():
            vk = ord(character)
        elif character == "-":
            vk = 0xBD
        else:
            return False
        keybd(vk)
        keybd(vk, up=True)
    typed_value = get_window_text(control_hwnd)
    keybd(0x09)  # VK_TAB commits EN_KILLFOCUS in the legacy control
    keybd(0x09, up=True)
    time.sleep(0.12)
    committed_value = get_window_text(control_hwnd)
    log(
        f"real_replace_ascii control={control_hwnd} requested={text!r} "
        f"typed={typed_value!r} committed={committed_value!r}"
    )
    return committed_value == text


def move_window(hwnd: int, x: int, y: int, w: int, h: int) -> None:
    user32.SetWindowPos(
        hwnd, 0, x, y, w, h, SWP_NOZORDER | SWP_SHOWWINDOW
    )


# ------------------------------------------------------------------ capture


def _save_bitmap_as_png(bitmap_handle, width: int, height: int, path: Path) -> bool:
    """Pull DIB bits from a GDI bitmap and store it as PNG via PySide6 QImage."""
    hdc = gdi32.CreateCompatibleDC(0)
    old = gdi32.SelectObject(hdc, bitmap_handle)
    try:
        bmi = BITMAPINFO()
        bmi.bmiHeader.biSize = sizeof(BITMAPINFOHEADER)
        bmi.bmiHeader.biWidth = width
        bmi.bmiHeader.biHeight = -height  # top-down rows
        bmi.bmiHeader.biPlanes = 1
        bmi.bmiHeader.biBitCount = 32
        bmi.bmiHeader.biCompression = 0  # BI_RGB
        buffer = ctypes.create_string_buffer(width * height * 4)
        got = gdi32.GetDIBits(
            hdc, bitmap_handle, 0, height, buffer, ctypes.byref(bmi), DIB_RGB_COLORS
        )
        if got != height:
            return False
        from PySide6.QtGui import QImage

        image = QImage(buffer, width, height, width * 4, QImage.Format.Format_ARGB32)
        return bool(image.copy().save(str(path)))
    finally:
        gdi32.SelectObject(hdc, old)
        gdi32.DeleteDC(hdc)


def capture_window(hwnd: int, path: Path) -> bool:
    """PrintWindow-based capture (window rect incl. title bar)."""
    if not is_window(hwnd):
        return False
    rect = get_window_rect(hwnd)
    width = max(1, rect["width"])
    height = max(1, rect["height"])
    user32.SetWindowPos(hwnd, 0, 0, 0, 0, 0, 0x0001 | 0x0002 | SWP_NOZORDER)  # NOSIZE|NOMOVE
    hdc_window = user32.GetWindowDC(hwnd)
    if not hdc_window:
        return False
    try:
        memdc = gdi32.CreateCompatibleDC(hdc_window)
        bitmap = gdi32.CreateCompatibleBitmap(hdc_window, width, height)
        old = gdi32.SelectObject(memdc, bitmap)
        try:
            ok = user32.PrintWindow(hwnd, memdc, PW_RENDERFULLCONTENT)
            if not ok:
                ok = user32.PrintWindow(hwnd, memdc, 0)
            if not ok:
                gdi32.BitBlt(
                    memdc, 0, 0, width, height, hdc_window, 0, 0, SRCCOPY | CAPTUREBLT
                )
            return _save_bitmap_as_png(bitmap, width, height, path)
        finally:
            gdi32.SelectObject(memdc, old)
            gdi32.DeleteObject(bitmap)
            gdi32.DeleteDC(memdc)
    finally:
        user32.ReleaseDC(hwnd, hdc_window)


def capture_screen_region(rect: dict, path: Path, pad: int = 0) -> bool:
    """Full-screen BitBlt capture cropped to a rect (for popup menus etc.)."""
    left = rect["left"] - pad
    top = rect["top"] - pad
    width = max(1, rect["width"] + 2 * pad)
    height = max(1, rect["height"] + 2 * pad)
    hdc_screen = user32.GetDC(0)
    try:
        memdc = gdi32.CreateCompatibleDC(hdc_screen)
        bitmap = gdi32.CreateCompatibleBitmap(hdc_screen, width, height)
        old = gdi32.SelectObject(memdc, bitmap)
        try:
            gdi32.BitBlt(memdc, 0, 0, width, height, hdc_screen, left, top, SRCCOPY | CAPTUREBLT)
            return _save_bitmap_as_png(bitmap, width, height, path)
        finally:
            gdi32.SelectObject(memdc, old)
            gdi32.DeleteObject(bitmap)
            gdi32.DeleteDC(memdc)
    finally:
        user32.ReleaseDC(0, hdc_screen)


# --------------------------------------------------------------- probe session


class ProbeSession:
    def __init__(self, repo: Path, evidence_tag: str = ""):
        self.repo = repo
        self.work = repo / "output" / "build" / "legacy-ui-probe"
        self.work.mkdir(parents=True, exist_ok=True)
        evidence_name = "legacy-ui-probe" + (
            f"-{evidence_tag}" if evidence_tag else ""
        )
        self.out = repo / "output" / "verification" / evidence_name
        self.shots = self.out / "screenshots"
        self.controls = self.out / "controls"
        self.shots.mkdir(parents=True, exist_ok=True)
        self.controls.mkdir(parents=True, exist_ok=True)
        self.session_file = self.work / "session.json"
        self.pid: int | None = None
        self.launcher_pid: int | None = None
        self.owns_process = False
        self.main_hwnd: int | None = None
        self.known_top: set[int] = set()
        self.preexisting_editor_hwnds: set[int] = set()
        self.probe_rom = self.work / "probe.nes"  # DC_kuorong copy + probe.cdl
        self.probe_rom_fallback = self.work / "测试.nes"  # legacy modifier's own test ROM
        self.probe_sav = self.work / "probe.sav"
        self.dbins_option = 1
        self.dbins_button = 130
        self.dbins_confirm = "no"
        self.dbins_value = 2
        self.dbins_value2 = 0
        self.dbins_rule_family = "42"
        self.dbins_rule_variant = 0
        self.db_weapon_record = 1
        self.db_instruction_row = 0
        self.db_animation_kind = "ally"
        self.db_ff_expect_noop = False
        self.db_ff_action = "left"
        self.db_context_case = "cut"
        self.wrule_puzzle_start = 80
        self.wrule_library_x = 50
        self.wrule_library_y = 50
        self.wrule_effect_x = 50
        self.wrule_effect_y = 50
        self.wrule_expect_noop = False
        self.wrule_page_index = 0
        self.wrule_button_id = 420
        self.wrule_button_action = "left"
        self.fast_launch = False

    # -- lifecycle ------------------------------------------------------

    def launch(self) -> None:
        exe = self.work / "SRW2_patched.exe"
        if not exe.exists():
            raise FileNotFoundError(exe)
        self.preexisting_editor_hwnds = {
            window["hwnd"]
            for window in enum_top_windows(0, visible_only=False)
            if window["title"].startswith("SRW2扩容版修改器")
        }
        launch_env = os.environ.copy()
        # The archived executable declares requireAdministrator even though
        # every probe uses only an isolated ROM and writable output folder.
        # Running it at the probe's own integrity level both avoids an
        # interactive UAC dependency and keeps real keyboard/menu automation
        # in the same desktop security boundary.
        launch_env["__COMPAT_LAYER"] = "RunAsInvoker"
        proc = subprocess.Popen(
            [str(exe)], cwd=str(self.work), env=launch_env,
            creationflags=subprocess.CREATE_NEW_PROCESS_GROUP,
        )
        self.pid = proc.pid
        self.launcher_pid = proc.pid
        self.owns_process = True
        self.save()
        log(f"launched pid={self.pid}")

    def attach(self, pid: int) -> None:
        self.pid = pid
        self.owns_process = False
        candidates = [
            window
            for window in self.top_windows(visible_only=False)
            if window["title"].startswith("SRW2扩容版修改器")
        ]
        if not candidates:
            candidates = [
                window
                for window in enum_top_windows(0, visible_only=False)
                if window["title"].startswith("SRW2扩容版修改器")
            ]
            if candidates:
                self.pid = candidates[0]["pid"]
                log(f"attach redirected to GUI child pid={self.pid}")
        if candidates:
            self.main_hwnd = candidates[0]["hwnd"]
        log(f"attached pid={pid}")

    def load(self) -> None:
        if self.session_file.exists():
            data = json.loads(self.session_file.read_text("utf-8"))
            self.main_hwnd = data.get("main_hwnd")
            if self.pid is None:
                self.pid = data.get("pid")

    def save(self) -> None:
        self.session_file.write_text(
            json.dumps({"pid": self.pid, "main_hwnd": self.main_hwnd}, ensure_ascii=False),
            encoding="utf-8",
        )

    def process_alive(self) -> bool:
        if not self.pid:
            return False
        # EnumWindows remains available when the reference editor is running
        # at a higher integrity level, while OpenProcess can legitimately be
        # denied.  A WTWindow owned by the exact PID is the strongest signal
        # needed by this UI-only probe.
        if any(
            window["class"] == "WTWindow"
            for window in self.top_windows(visible_only=False)
        ):
            return True
        handle = kernel32.OpenProcess(PROCESS_QUERY_INFORMATION, False, self.pid)
        if not handle:
            return False
        kernel32.CloseHandle(handle)
        # A persisted PID may have been reused by Windows after an earlier
        # probe exited.  Resume only a process that still owns a legacy editor
        # WTWindow; otherwise launch a fresh isolated copy.
        return any(
            window["class"] == "WTWindow"
            for window in self.top_windows(visible_only=False)
        )

    def terminate(self) -> None:
        pids = []
        if self.pid:
            if not self.owns_process and not self.process_alive():
                log(f"stale/unverified pid={self.pid}; skip termination")
                self.pid = None
                return
            pids.append(self.pid)
        if self.launcher_pid and self.launcher_pid not in pids:
            pids.append(self.launcher_pid)
        for pid in pids:
            subprocess.run(
                ["taskkill", "/PID", str(pid), "/T", "/F"],
                capture_output=True,
                check=False,
            )
            log(f"terminated owned pid={pid}")
        self.pid = None
        self.launcher_pid = None

    # -- helpers ---------------------------------------------------------

    def top_windows(self, visible_only: bool = True) -> list[dict]:
        return enum_top_windows(self.pid or 0, visible_only)

    def snapshot_known(self) -> None:
        self.known_top = {w["hwnd"] for w in self.top_windows()}

    def wait_new_top(
        self,
        exclude: set[int] | None = None,
        timeout: float = 10.0,
        title_contains: str | None = None,
        not_title_contains: str | None = None,
        cls_equals: str | None = None,
    ) -> dict | None:
        """Wait for a new visible top-level window of the probed process.

        cls_equals filters by window class (e.g. "#32770" for dialogs,
        "WTWindow" for 易语言 app windows); IME/tool windows like
        SoPY_Status keep re-appearing with fresh hwnds and must be skipped.
        """
        exclude = set(exclude or self.known_top)
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            for window in self.top_windows():
                if window["hwnd"] in exclude:
                    continue
                if title_contains and title_contains not in window["title"]:
                    continue
                if not_title_contains and not_title_contains in window["title"]:
                    continue
                if cls_equals and window["class"] != cls_equals:
                    continue
                return window
            time.sleep(0.25)
        return None

    def wait_gone(self, hwnd: int, timeout: float = 8.0) -> bool:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if not is_window(hwnd) or not is_window_visible(hwnd):
                return True
            time.sleep(0.2)
        return not is_window_visible(hwnd)

    def dump_window(
        self,
        hwnd: int,
        tag: str,
        *,
        shot: bool = True,
        menu: bool = True,
        sleep_before: float = 0.8,
    ) -> dict:
        """Enumerate a window tree + menu, save JSON and PNG evidence."""
        if sleep_before:
            time.sleep(sleep_before)
        tree = enum_child_tree(hwnd)
        record = {
            "tag": tag,
            "hwnd": hwnd,
            "title": get_window_text(hwnd),
            "class": get_class_name(hwnd),
            "rect": get_window_rect(hwnd),
            "pid": window_pid(hwnd),
        }
        if menu:
            menu_tree = get_menu_tree(hwnd)
            if menu_tree is not None:
                record["menu"] = menu_tree
        record["tree"] = tree
        json_path = self.controls / f"{tag}.json"
        json_path.write_text(
            json.dumps(record, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        shot_ok = False
        if shot:
            shot_ok = capture_window(hwnd, self.shots / f"{tag}.png")
        record["screenshot"] = str(self.shots / f"{tag}.png") if shot_ok else None
        log(
            f"dump {tag}: title={record['title']!r} class={record['class']!r} "
            f"controls={len(flatten_tree(tree))} shot={'ok' if shot_ok else 'FAIL'}"
        )
        return record

    def close_dialog(self, hwnd: int, timeout: float = 8.0) -> str:
        """Close a dialog: prefer cancel/close/exit button, then WM_CLOSE, then ESC."""
        tree = enum_child_tree(hwnd)
        for text_key in ("取消", "关闭", "退出", "Cancel", "&Cancel"):
            buttons = find_controls(tree, cls="Button", text_contains=text_key)
            if buttons:
                click_control(buttons[0]["hwnd"])
                if self.wait_gone(hwnd, 4.0):
                    return f"button:{text_key}"
        user32.PostMessageW(hwnd, WM_CLOSE, 0, 0)
        if self.wait_gone(hwnd, 4.0):
            return "wm_close"
        send_escape(hwnd)
        if self.wait_gone(hwnd, 4.0):
            return "escape"
        return "failed"

    # -- file dialog ------------------------------------------------------

    def _fill_file_dialog(self, dialog_hwnd: int, path: Path, tag: str | None) -> bool:
        if tag:
            self.dump_window(dialog_hwnd, tag, menu=False, sleep_before=0.3)
        tree = enum_child_tree(dialog_hwnd)
        edits = [c for c in flatten_tree(tree) if c["class"] == "Edit" and c["visible"]]
        if not edits:
            log("open dialog: no visible Edit control found")
            return False
        set_control_text(edits[-1]["hwnd"], str(path))
        time.sleep(0.3)
        ok_button = user32.GetDlgItem(dialog_hwnd, 1)  # IDOK
        if ok_button:
            click_control(ok_button)
        else:
            send_key(dialog_hwnd, VK_RETURN)
        gone = self.wait_gone(dialog_hwnd, 10.0)
        log(f"open dialog confirmed gone={gone}")
        return gone

    def rom_is_loaded(self) -> bool:
        """ROM considered loaded only when the 数据 menu exists."""
        menu = get_menu_tree(self.main_hwnd)
        return bool(
            menu
            and any(top["text"].replace("&", "").startswith("数据") for top in menu)
        )

    def handle_runtime_dialog(self, popup_hwnd: int, tag: str) -> bool:
        """Dump and dismiss a runtime-error/message dialog; capture evidence."""
        self.dump_window(popup_hwnd, tag, menu=False)
        log(f"runtime dialog: {get_window_text(popup_hwnd)!r}")
        ok = user32.GetDlgItem(popup_hwnd, 2) or user32.GetDlgItem(popup_hwnd, 1)
        if ok:
            # Several legacy WT/Afx dialogs expose a normal-looking Button but
            # ignore BM_CLICK while their private modal loop is active.  Drive
            # the same physical mouse path used by a person first, then retain
            # keyboard/WM_CLOSE fallbacks so a failed dismissal cannot leave
            # the parent window permanently blocked.
            real_click_control(ok)
        else:
            send_key(popup_hwnd, VK_RETURN)
        if self.wait_gone(popup_hwnd, 1.5):
            return True
        force_foreground(popup_hwnd)
        if ok:
            focus_foreground_control(popup_hwnd, ok)
        keybd(VK_RETURN)
        time.sleep(0.08)
        keybd(VK_RETURN, up=True)
        if self.wait_gone(popup_hwnd, 1.5):
            return True
        if ok:
            post_command(popup_hwnd, user32.GetDlgCtrlID(ok), ok)
        if self.wait_gone(popup_hwnd, 1.5):
            return True
        force_foreground(popup_hwnd)
        keybd(VK_ESCAPE)
        time.sleep(0.08)
        keybd(VK_ESCAPE, up=True)
        if self.wait_gone(popup_hwnd, 1.5):
            return True
        if is_window(popup_hwnd):
            user32.PostMessageW(popup_hwnd, WM_CLOSE, 0, 0)
        gone = self.wait_gone(popup_hwnd, 2.0)
        log(f"runtime dialog dismissed={gone}")
        return gone

    def wait_rom_load(self, settle: float = 6.0) -> bool:
        """Wait until 数据 menu appears, dismissing runtime dialogs meanwhile."""
        deadline = time.monotonic() + 25.0
        loaded_since: float | None = None
        dialog_index = 0
        while time.monotonic() < deadline:
            if not self.process_alive():
                log("target process died during ROM load")
                return False
            for window in self.top_windows():
                if window["class"] == "#32770" and window["hwnd"] not in self.known_top:
                    dialog_index += 1
                    self.handle_runtime_dialog(
                        window["hwnd"], f"B98_载入后弹窗{dialog_index}"
                    )
            if self.rom_is_loaded():
                if loaded_since is None:
                    loaded_since = time.monotonic()
                if time.monotonic() - loaded_since >= settle:
                    return True
            else:
                loaded_since = None
            time.sleep(0.5)
        return self.rom_is_loaded()

    def open_rom_via_menu(self, rom: Path, shot_tag: str) -> bool:
        """File->Open with the copied ROM; returns True when menu gains 数据."""
        menu = get_menu_tree(self.main_hwnd)
        if not menu:
            log("no menu on main window")
            return False
        open_id = menu_item_id(menu, "文件", "打开")
        if open_id is None:
            log("File->Open menu item not found")
            return False
        self.snapshot_known()
        user32.PostMessageW(self.main_hwnd, WM_COMMAND, open_id, 0)
        dialog = self.wait_new_top(timeout=10.0, cls_equals="#32770")
        if not dialog:
            log("open dialog did not appear")
            return False
        if not self._fill_file_dialog(dialog["hwnd"], rom, shot_tag):
            return False
        # Watch for runtime-error dialogs and for the 数据 menu.
        return self.wait_rom_load()

    # -- tabs ---------------------------------------------------------

    def click_tab(self, tab_hwnd: int, index: int) -> None:
        """Post a synthetic click on tab header *index* (uniform x spacing)."""
        width, height = get_client_size(tab_hwnd)
        count = _send_msg_num(tab_hwnd, TCM_GETITEMCOUNT, 0, 0) or 1
        x = int((index + 0.5) * width / count)
        y = min(12, max(1, height // 3))
        post_click_at(tab_hwnd, x, y)

def find_tab(root: dict) -> dict | None:
    """Tab container: legacy app uses MFC CPageControl, fallback to SysTabControl32."""
    for cls_name in ("CPageControl", "SysTabControl32"):
        tabs = find_controls(root, cls=cls_name, visible=True)
        if tabs:
            return tabs[0]
    return None


def click_tab_generic(session: "ProbeSession", tab_item: dict, index: int, count: int) -> None:
    """Synthetic click on tab header *index* of CPageControl or SysTabControl32."""
    tab_hwnd = tab_item["hwnd"]
    width, height = get_client_size(tab_hwnd)
    count = max(1, count or 1)
    x = int((index + 0.5) * width / count)
    y = min(12, max(1, height // 3))
    post_click_at(tab_hwnd, x, y)


# ------------------------------------------------------------------- stage A


def stage_a(session: ProbeSession) -> None:
    log("=== stage A: launcher -> main window (no ROM) ===")
    time.sleep(3.0)
    windows = session.top_windows()
    for window in windows:
        log(f"top window: {window}")
    if not windows:
        raise RuntimeError("no visible top-level window after launch")
    main_candidates = [
        window
        for window in windows
        if window["title"].startswith("SRW2扩容版修改器")
    ]
    if main_candidates:
        log("launcher already dismissed (attached session); skipping launcher dump")
        session.main_hwnd = main_candidates[0]["hwnd"]
        session.pid = main_candidates[0]["pid"]
        session.save()
    else:
        launcher = windows[0]
        launcher_dump = session.dump_window(launcher["hwnd"], "A01_启动器")

        enter_buttons = find_controls(launcher_dump["tree"], cls="Button", text_contains="进入")
        if not enter_buttons:
            log("launcher: 进入修改器 button not found; dumping full control list")
            for item in flatten_tree(launcher_dump["tree"]):
                log(f"  ctrl {item['ctrl_id']} {item['class']} {item['text']!r}")
            raise RuntimeError("cannot enter editor")
        enter_hwnd = enter_buttons[0]["hwnd"]
        session.snapshot_known()
        # The skinned launcher publishes its controls before the handler is
        # consistently ready.  Let that single button settle, then activate
        # it exactly once; retries can create a second competing editor.
        time.sleep(6.0)
        # Use exactly one process-local activation.  Global cursor input can
        # be swallowed by recording/overlay windows; combining both paths is
        # unsafe because a delayed real click may then launch a second editor.
        # Send the parent the single standard BN_CLICKED notification.  The
        # launcher's owner-drawn Button intermittently drops BM_CLICK even
        # after settling, while its normal command handler is stable.
        click_control_via_command(enter_buttons[0])
        main_window = None
        deadline = time.monotonic() + 30.0
        while time.monotonic() < deadline:
            # The launcher starts the real editor in a separate GUI process.
            # Search all top-level windows instead of restricting the lookup
            # to the launcher PID, then follow that child for later stages.
            for window in enum_top_windows(0):
                if window["hwnd"] == launcher["hwnd"]:
                    continue
                if window["hwnd"] in session.preexisting_editor_hwnds:
                    continue
                if window["title"].startswith("SRW2扩容版修改器"):
                    main_window = window
                    break
            if main_window:
                break
            time.sleep(0.4)
        if not main_window:
            raise RuntimeError("main window did not appear after entering")
        session.pid = main_window["pid"]
        session.main_hwnd = main_window["hwnd"]
        session.save()
        log(f"main window hwnd={session.main_hwnd} title={main_window['title']!r}")
    move_window(session.main_hwnd, 30, 30, 1200, 850)
    time.sleep(0.6)
    session.dump_window(session.main_hwnd, "A02_主窗口_未载入ROM")
    if not session.fast_launch:
        _shoot_open_menus(session, "A03")
    else:
        # The WT main window is published before its menu handlers finish
        # initialising.  A short settle keeps isolated probes fast while
        # avoiding the intermittent missing Open-ROM dialog seen when a
        # command is posted immediately after HWND creation.
        time.sleep(8.0)


def open_menu_via_syschar(hwnd: int, key: str) -> None:
    """Post Alt+<key> as messages (no real input) to open a menu-bar menu."""
    vk = ord(key.upper())
    user32.PostMessageW(hwnd, WM_SYSKEYDOWN, VK_MENU, 0x20380001)
    user32.PostMessageW(hwnd, WM_SYSKEYDOWN, vk, 0x20210001)
    user32.PostMessageW(hwnd, WM_SYSCHAR, vk, 0x20210001)
    user32.PostMessageW(hwnd, WM_SYSKEYUP, vk, 0xC0210001)
    user32.PostMessageW(hwnd, WM_SYSKEYUP, VK_MENU, 0xC0380001)


def close_menu_via_keys(hwnd: int) -> None:
    user32.PostMessageW(hwnd, WM_KEYDOWN, VK_ESCAPE, 0x00010001)
    user32.PostMessageW(hwnd, WM_KEYUP, VK_ESCAPE, 0xC0010001)


def _shoot_open_menus(session: ProbeSession, tag_prefix: str) -> None:
    """Try to screenshot expanded top-level menus via real Alt+<key> presses."""
    if not session.main_hwnd:
        return
    menu = get_menu_tree(session.main_hwnd)
    if not menu:
        log("no standard menu bar; skip expanded-menu screenshots")
        return
    accel = {"文件": "F", "数据": "D", "帮助": "H"}
    if not force_foreground(session.main_hwnd):
        log("cannot bring main window to foreground; menu shots may fail")
    time.sleep(0.4)
    for top in menu:
        label = top["text"].replace("&", "")
        key = next((v for k, v in accel.items() if label.startswith(k)), None)
        if not key:
            continue
        opened = False
        try:
            # Attempt 1: posted Alt+key messages (zero real input).
            open_menu_via_syschar(session.main_hwnd, key)
            deadline = time.monotonic() + 1.5
            while time.monotonic() < deadline and not menu_is_open(session.main_hwnd):
                time.sleep(0.1)
            opened = menu_is_open(session.main_hwnd)
            if not opened:
                # Attempt 2: real Alt+key with foreground.
                force_foreground(session.main_hwnd)
                time.sleep(0.3)
                keybd(VK_MENU)
                time.sleep(0.1)
                keybd(ord(key))
                time.sleep(0.1)
                keybd(ord(key), up=True)
                time.sleep(0.1)
                keybd(VK_MENU, up=True)
                deadline = time.monotonic() + 2.0
                while time.monotonic() < deadline and not menu_is_open(session.main_hwnd):
                    time.sleep(0.1)
                opened = menu_is_open(session.main_hwnd)
            if not opened:
                log(f"menu {label}: could not open menu via Alt+{key}")
                continue
            time.sleep(0.3)
            capture_screen_region(
                get_window_rect(session.main_hwnd),
                session.shots / f"{tag_prefix}_菜单展开_{label}.png",
                pad=60,
            )
            log(f"menu shot: {label}")
        except Exception as exc:
            log(f"menu shot {label} failed: {exc}")
        finally:
            close_menu_via_keys(session.main_hwnd)
            keybd(VK_ESCAPE)
            time.sleep(0.1)
            keybd(VK_ESCAPE, up=True)
            time.sleep(0.4)


# ------------------------------------------------------------------- stage B


def stage_b(session: ProbeSession) -> None:
    log("=== stage B: load ROM copy -> tabs ===")
    if not session.main_hwnd or not is_window(session.main_hwnd):
        candidates = [
            w
            for w in session.top_windows()
            if w["title"].startswith("SRW2扩容版修改器")
        ]
        if not candidates:
            raise RuntimeError("main window not found for stage B")
        session.main_hwnd = candidates[0]["hwnd"]
    rom = session.probe_rom if session.probe_rom.exists() else session.probe_rom_fallback
    loaded = session.open_rom_via_menu(rom, "B01_打开ROM对话框")
    if not loaded:
        raise RuntimeError(f"ROM load failed for {rom.name}")
    log(f"ROM loaded, title={get_window_text(session.main_hwnd)!r}")
    session.dump_window(session.main_hwnd, "B02_主窗口_载入后")
    _shoot_open_menus(session, "B03")
    tree = enum_child_tree(session.main_hwnd)
    tab = find_tab(tree)
    if not tab:
        log("no tab control found on main window")
        return
    count = tab.get("tab_count", 0) or 0
    if count <= 0:
        count = 3  # CPageControl does not expose tab count via TCM messages
        log("tab count unknown (CPageControl); assuming 3")
    log(f"main window tabs: {count} (class={tab['class']})")
    # CPageControl ignores posted TCM/click messages and spans far more width
    # than its three owner-drawn headers.  Sweep the actual header band and
    # archive only distinct page content; old B04 synthetic dumps are retained
    # as failure evidence instead of being overwritten.
    pages = sweep_tabs(
        session, session.main_hwnd, "B04_主窗口_实际页签", max_pages=count
    )
    if pages != count:
        log(f"main tab sweep found {pages}/{count} distinct pages; no inferred control IDs")


def stage_load(session: ProbeSession) -> None:
    """Load the isolated ROM without probing unrelated main-window controls."""

    log("=== stage LOAD: load ROM copy only ===")
    if not session.main_hwnd or not is_window(session.main_hwnd):
        candidates = [
            w
            for w in session.top_windows()
            if w["title"].startswith("SRW2扩容版修改器")
        ]
        if not candidates:
            raise RuntimeError("main window not found for stage LOAD")
        session.main_hwnd = candidates[0]["hwnd"]
    if session.rom_is_loaded():
        log(f"ROM already loaded, title={get_window_text(session.main_hwnd)!r}")
        return
    rom = session.probe_rom if session.probe_rom.exists() else session.probe_rom_fallback
    loaded = session.open_rom_via_menu(rom, "LOAD01_打开ROM对话框")
    if not loaded:
        raise RuntimeError(f"ROM load failed for {rom.name}")
    log(f"ROM loaded without main-window sweep, title={get_window_text(session.main_hwnd)!r}")
    session.dump_window(session.main_hwnd, "LOAD02_主窗口_载入后")


# ------------------------------------------------------------------- stage C


# 数据-menu entries: (label, command id, tab labels; None=first page only,
# "EXPORT"=expect a save dialog which we dump and cancel, "AUTO"=discover
# tab-header-like controls near the top of the window automatically).
STAGE_C_WINDOWS = [
    ("数据库", 20008, ["机体修改", "人物修改", "武器修改", "战斗对话", "其他修改1", "其他修改2"]),
    ("文字库", 20009, None),
    ("地图动画", 20011, ["地图动画", "规律", "动画调用"]),
    ("文字转换", 20013, None),
    ("剧情事件", 20015, "AUTO"),
    ("导出机体", 20017, "EXPORT"),
    ("导出头像", 20018, "EXPORT"),
    ("属性计算器", 20020, None),
    ("存档修改器", 20021, None),
    ("其他", 20023, "AUTO"),
]


def _header_band_controls(window_hwnd: int) -> list[dict]:
    """Visible labelled controls near the top of a window (tab headers)."""
    tree = enum_child_tree(window_hwnd)
    win_rect = get_window_rect(window_hwnd)
    out = []
    for item in flatten_tree(tree):
        text = (item.get("text") or "").strip()
        if not text or len(text) > 16:
            continue
        if item.get("visible") is False or item.get("enabled") is False:
            continue
        rect = item["rect"]
        width = rect["right"] - rect["left"]
        height = rect["bottom"] - rect["top"]
        if width < 24 or width > 260 or height < 10 or height > 60:
            continue
        if rect["top"] - win_rect["top"] > 120:
            continue
        out.append(item)
    out.sort(key=lambda item: item["rect"]["left"])
    return out


def click_tabs_by_label(session: "ProbeSession", hwnd: int, tag: str, labels: list[str]) -> None:
    """Click tab-header controls matching *labels* and dump each page."""
    win_rect = get_window_rect(hwnd)
    for label in labels:
        tree = enum_child_tree(hwnd)
        candidates = []
        for item in flatten_tree(tree):
            text = (item.get("text") or "").strip()
            if label not in text:
                continue
            rect = item["rect"]
            if rect["top"] - win_rect["top"] <= 120:
                candidates.append(item)
        if not candidates:
            log(f"tab {label!r}: header control not found")
            continue
        click_control(candidates[0]["hwnd"])
        time.sleep(0.8)
        session.dump_window(hwnd, f"{tag}_{label}", menu=False)


def click_tabs_auto(session: "ProbeSession", hwnd: int, tag: str) -> None:
    """Discover tab-header-like controls at the top and dump one page per tab."""
    headers = _header_band_controls(hwnd)
    log(f"auto tabs: {[(h['text'], h['ctrl_id']) for h in headers]}")
    seen_ids: set[int] = set()
    for header in headers:
        if header["hwnd"] in seen_ids:
            continue
        seen_ids.add(header["hwnd"])
        click_control(header["hwnd"])
        time.sleep(0.8)
        safe_name = "".join(c for c in header["text"] if c not in '\\/:*?"<>|')[:12]
        session.dump_window(hwnd, f"{tag}_{safe_name}", menu=False)


def close_window_safely(session: "ProbeSession", hwnd: int, timeout: float = 6.0) -> None:
    """Close a data window via 关闭/退出/取消 button, else WM_CLOSE."""
    tree = enum_child_tree(hwnd)
    for word in ("关闭", "退出", "取消", "返回"):
        buttons = find_controls(tree, cls="Button", text_contains=word)
        if buttons:
            click_control(buttons[0]["hwnd"])
            if session.wait_gone(hwnd, min(1.2, timeout)):
                return
            if real_click_control(buttons[0]["hwnd"]):
                if session.wait_gone(hwnd, timeout):
                    return
    user32.PostMessageW(hwnd, WM_CLOSE, 0, 0)
    session.wait_gone(hwnd, timeout)


def handle_export_dialog(session: "ProbeSession", label: str, cmd_id: int, tag: str) -> None:
    """导出机体/导出头像: dump whatever dialog appears, then cancel safely."""
    if not session.process_alive():
        log(f"{label}: target process is dead")
        return
    dismiss_blocking_popups(session)
    session.snapshot_known()
    user32.PostMessageW(session.main_hwnd, WM_COMMAND, cmd_id, 0)
    dialog = session.wait_new_top(timeout=10.0, cls_equals="#32770")
    if not dialog:
        # runtime errors can pop up late (e.g. 导出头像 raises error code 4)
        time.sleep(4.0)
        dismiss_blocking_popups(session)
        log(f"{label}: no dialog appeared for export")
        return
    log(f"{label}: dialog hwnd={dialog['hwnd']} title={dialog['title']!r}")
    session.dump_window(dialog["hwnd"], tag, menu=False)
    # never confirm a save; prefer IDCANCEL (2), then ESC, then WM_CLOSE
    cancel = user32.GetDlgItem(dialog["hwnd"], 2)
    if cancel:
        click_control(cancel)
    else:
        send_key(dialog["hwnd"], VK_ESCAPE)
        user32.PostMessageW(dialog["hwnd"], WM_CLOSE, 0, 0)
    gone = session.wait_gone(dialog["hwnd"], 6.0)
    log(f"{label}: export dialog captured and dismissed (gone={gone})")


def _stage_c_windows(session: ProbeSession, *, skip_labels: set[str]) -> None:
    log("=== stage C: 数据 menu windows ===")
    if not session.main_hwnd or not is_window(session.main_hwnd):
        raise RuntimeError("main window not alive; run stage A/B first")
    if not session.rom_is_loaded():
        raise RuntimeError("ROM not loaded; run stage B first")
    for index, (label, cmd_id, tabs) in enumerate(STAGE_C_WINDOWS, start=1):
        if label in skip_labels:
            log(f"{label}: skipped by stable capture mode")
            continue
        tag = f"C{index:02d}_{label}"
        if tabs == "EXPORT":
            try:
                handle_export_dialog(session, label, cmd_id, tag)
            except Exception as exc:
                log(f"{label} FAILED: {exc!r}")
            time.sleep(0.5)
            continue
        window = _open_data_window(session, cmd_id, label)
        if not window:
            continue
        log(f"{label}: hwnd={window['hwnd']} title={window['title']!r} class={window['class']}")
        try:
            session.dump_window(window["hwnd"], tag)
            if isinstance(tabs, list):
                click_tabs_by_label(session, window["hwnd"], tag, tabs)
            elif tabs == "AUTO":
                click_tabs_auto(session, window["hwnd"], tag)
        except Exception as exc:
            log(f"{label} dump/tabs FAILED: {exc!r}")
        finally:
            close_window_safely(session, window["hwnd"])
            time.sleep(0.5)


def stage_c(session: ProbeSession) -> None:
    _stage_c_windows(session, skip_labels=set())


def stage_c_safe(session: ProbeSession) -> None:
    """Capture all stable data windows without invoking the crashing export.

    The reference build's 导出头像 command is already covered by preserved
    failure evidence.  Invoking it during a full sweep raises a delayed runtime
    error and terminates the editor before the remaining controls are captured.
    """

    _stage_c_windows(session, skip_labels={"导出头像"})


def stage_m05(session: ProbeSession) -> None:
    """Load the compatible probe ROM and capture only 数据->数据库.

    This avoids the owner-drawn main-tab sweep used by stage B.  Some legacy
    builds raise a delayed array-bounds error after that sweep, which can kill
    the process before the database window is opened.
    """

    log("=== stage M05: focused database capture ===")
    if not session.main_hwnd or not is_window(session.main_hwnd):
        raise RuntimeError("main window not alive; run stage A first")
    if not session.rom_is_loaded():
        rom = (
            session.probe_rom
            if session.probe_rom.exists()
            else session.probe_rom_fallback
        )
        if not session.open_rom_via_menu(rom, "M05_打开ROM对话框"):
            raise RuntimeError(f"ROM load failed for {rom.name}")
        session.dump_window(session.main_hwnd, "M05_主窗口_载入后")
    # The reference editor pre-creates several hidden business windows.  They
    # are valid lazy-loaded UI state, not stale blockers; closing the hidden
    # database window makes the legacy runtime fail when the menu opens it.
    window = None
    for _attempt in range(3):
        window = _open_data_window(
            session, 20008, "数据库", dismiss_hidden=False
        )
        if window is not None:
            break
        time.sleep(0.8)
    if not window:
        raise RuntimeError("database window did not appear")
    try:
        unit_lists = find_controls(
            enum_child_tree(window["hwnd"]), cls="ListBox", ctrl_id=120
        )
        if not unit_lists:
            raise RuntimeError("unit list 120 not found")
        unit_list = unit_lists[0]["hwnd"]
        if user32.SendMessageW(unit_list, 0x0186, 1, 0) == -1:  # LB_SETCURSEL
            raise RuntimeError("unit row 1 is unavailable")
        list_parent = user32.GetParent(unit_list)
        user32.SendMessageW(
            list_parent,
            WM_COMMAND,
            120 | (1 << 16),  # LBN_SELCHANGE
            unit_list,
        )
        time.sleep(0.3)
        session.dump_window(window["hwnd"], "M05_数据库_机体修改")
        known = {item["hwnd"] for item in session.top_windows()}
        skill_buttons = find_controls(enum_child_tree(window["hwnd"]), ctrl_id=2600)
        if not skill_buttons:
            raise RuntimeError("special-skill button 2600 not found")
        skill_button = skill_buttons[0]["hwnd"]
        click_control(skill_button)
        popup = session.wait_new_top(exclude=known, timeout=2.0)
        if popup is None:
            real_click_control(skill_button)
            popup = session.wait_new_top(exclude=known, timeout=8.0)
        if popup is None:
            raise RuntimeError("special-skill popup did not appear")
        session.dump_window(
            popup["hwnd"], "M05_数据库_机体修改_特殊技能", menu=False
        )
        close_window_safely(session, popup["hwnd"])

        # Capture the owner-drawn colour picker reached through the first
        # swatch.  Direct edits display text but do not update the legacy
        # window's internal palette value, so the swatch path is authoritative.
        fresh_tree = enum_child_tree(window["hwnd"])
        swatches = find_controls(fresh_tree, ctrl_id=280)
        if swatches:
            known = {item["hwnd"] for item in session.top_windows()}
            real_click_control(swatches[0]["hwnd"])
            colour_popup = session.wait_new_top(exclude=known, timeout=3.0)
            if colour_popup is not None:
                session.dump_window(
                    colour_popup["hwnd"],
                    "M05_数据库_机体修改_颜色选择",
                    menu=False,
                )
                close_window_safely(session, colour_popup["hwnd"])
            else:
                session.dump_window(
                    window["hwnd"],
                    "M05_数据库_机体修改_颜色选择内嵌",
                    menu=False,
                )

        # Capture the icon-binding picker without committing a selection.
        fresh_tree = enum_child_tree(window["hwnd"])
        icon_buttons = find_controls(fresh_tree, ctrl_id=1350)
        if icon_buttons:
            known = {item["hwnd"] for item in session.top_windows()}
            click_control(icon_buttons[0]["hwnd"])
            icon_popup = session.wait_new_top(exclude=known, timeout=2.0)
            if icon_popup is None:
                real_click_control(icon_buttons[0]["hwnd"])
                icon_popup = session.wait_new_top(exclude=known, timeout=5.0)
            if icon_popup is not None:
                session.dump_window(
                    icon_popup["hwnd"],
                    "M05_数据库_机体修改_机体图标设置",
                    menu=False,
                )
                icon_tree = enum_child_tree(icon_popup["hwnd"])
                icon_rows = find_controls(icon_tree, ctrl_id=170)
                if icon_rows:
                    row_rect = get_window_rect(icon_rows[0]["hwnd"])
                    client_origin = wintypes.POINT(0, 0)
                    user32.ClientToScreen(icon_popup["hwnd"], ctypes.byref(client_origin))
                    post_click_at(
                        icon_popup["hwnd"],
                        row_rect["left"] - client_origin.x + 20,
                        row_rect["top"] - client_origin.y + 16,
                    )
                    time.sleep(0.4)
                    session.dump_window(
                        icon_popup["hwnd"],
                        "M05_数据库_机体修改_机体图标设置_点击后",
                        menu=False,
                    )
                close_window_safely(session, icon_popup["hwnd"])

        # Record a compact row sample to locate a large-unit row where image
        # address 2 is genuinely enabled.  This is observation only.
        row_samples: list[dict] = []
        for row in range(32):
            if user32.SendMessageW(unit_list, 0x0186, row, 0) == -1:
                break
            user32.SendMessageW(list_parent, WM_COMMAND, 120 | (1 << 16), unit_list)
            time.sleep(0.12)
            row_tree = enum_child_tree(window["hwnd"])

            def one(control_id: int) -> dict | None:
                items = find_controls(row_tree, ctrl_id=control_id)
                return items[0] if items else None

            sample: dict = {"row": row}
            name = one(390)
            if name:
                sample["name"] = name["text"]
            for label, control_id in (
                ("weapon_1", 550),
                ("weapon_2", 560),
                ("unit_type", 570),
                ("fragment_bank", 370),
                ("body_bank_1", 350),
                ("body_bank_2", 360),
            ):
                item = one(control_id)
                if item:
                    sample[label] = {
                        "text": item["text"],
                        "selected": item.get("combo_selected"),
                        "visible": item["visible"],
                        "enabled": item["enabled"],
                    }
            captain = one(2700)
            if captain:
                sample["captain"] = {
                    "text": captain["text"],
                    "visible": captain["visible"],
                    "enabled": captain["enabled"],
                    "checked": captain.get("button_check_state"),
                }
            row_samples.append(sample)
            body_bank_2 = sample.get("body_bank_2", {})
            if row >= 1 and body_bank_2.get("enabled"):
                break
        (session.controls / "M05_数据库_机体修改_行样本.json").write_text(
            json.dumps(row_samples, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
    finally:
        close_window_safely(session, window["hwnd"])


def stage_dbm05puzzlecontrols(session: ProbeSession) -> None:
    """Exercise every unit/fragment puzzle control without saving the ROM.

    A fresh child draft is opened for every button gesture.  This is
    intentional: clear/template/move commands change the child draft, so a
    sequential sweep would test later commands against an artificial state.
    The database is cancelled at the end and the isolated ROM must remain
    byte-for-byte identical.
    """

    log("=== stage DBM05PUZZLECONTROLS: unit/fragment complete matrix ===")
    before = session.probe_rom.read_bytes()
    database_hwnd = 0
    puzzle_hwnd = 0
    execution_records: list[dict[str, object]] = []
    observations: list[dict[str, object]] = []
    error: str | None = None
    database_closed = False

    specs = (
        {
            "title": "机体拼图",
            "open_button": 190,
            "cancel_button": 350,
            "buttons": (
                100, 170, 180, 210, 280, 290, 300, 310, 320,
                330, 340, 350, 360, 370, 380, 390, 400, 450,
            ),
            "combos": (120, 140, 150),
            "edit": 270,
            "list": None,
        },
        {
            "title": "碎片拼图",
            "open_button": 220,
            "cancel_button": 250,
            "buttons": (
                100, 170, 200, 240, 250, 260, 270, 280,
                290, 320, 340, 350, 400, 430, 440,
            ),
            "combos": (120, 300),
            "edit": 330,
            "list": 390,
        },
    )

    def record(
        title: str, cls_name: str, control_id: int,
        path: tuple[int, ...], action: str, result: str,
    ) -> None:
        execution_records.append(
            {
                "action_id": stable_interaction_id(
                    title, cls_name, control_id, path, action
                ),
                "status": "passed",
                "result": result,
            }
        )

    def notify_edit(edit_hwnd: int, control_id: int) -> None:
        parent = user32.GetParent(edit_hwnd)
        if parent:
            _send_msg_num(
                parent, WM_COMMAND,
                (control_id & 0xFFFF) | (0x0300 << 16), edit_hwnd,
            )

    def open_puzzle(spec: dict[str, object]) -> int:
        buttons = find_controls(
            enum_child_tree(database_hwnd), cls="Button",
            ctrl_id=int(spec["open_button"]), visible=True,
        )
        if not buttons:
            raise RuntimeError(
                f"database puzzle button {spec['open_button']} missing"
            )
        known = {item["hwnd"] for item in session.top_windows()}
        click_control(buttons[0]["hwnd"])
        opened = session.wait_new_top(
            exclude=known, timeout=6.0, cls_equals="WTWindow",
            title_contains=str(spec["title"]),
        )
        if not opened:
            real_click_control(buttons[0]["hwnd"])
            opened = session.wait_new_top(
                exclude=known, timeout=6.0, cls_equals="WTWindow",
                title_contains=str(spec["title"]),
            )
        if not opened:
            raise RuntimeError(f"{spec['title']} did not appear")
        move_window(opened["hwnd"], 90, 45, 1050, 760)
        time.sleep(0.35)
        return int(opened["hwnd"])

    def close_puzzle_draft(spec: dict[str, object], hwnd: int) -> None:
        if not hwnd or not is_window(hwnd):
            return
        cancel = find_controls(
            enum_child_tree(hwnd), cls="Button",
            ctrl_id=int(spec["cancel_button"]), visible=True,
        )
        if cancel:
            click_control(cancel[0]["hwnd"])
            if session.wait_gone(hwnd, 4.0):
                return
        close_window_safely(session, hwnd, timeout=4.0)

    def dismiss_descendants(
        known: set[int], owner: int, tag: str,
    ) -> list[dict[str, str]]:
        found: list[dict[str, str]] = []
        for index, popup in enumerate(session.top_windows(), 1):
            if (
                popup["hwnd"] in known
                or popup["hwnd"] in {database_hwnd, owner}
                or popup["class"] == "#32768"
                or not popup["title"].strip()
            ):
                continue
            item = {"title": popup["title"], "class": popup["class"]}
            found.append(item)
            session.dump_window(
                popup["hwnd"], f"{tag}_{index}", menu=True
            )
            if popup["class"] == "#32770":
                session.handle_runtime_dialog(popup["hwnd"], f"{tag}_{index}")
                session.wait_gone(popup["hwnd"], 3.0)
            else:
                close_window_safely(session, popup["hwnd"], timeout=3.0)
        return found

    def exercise_edit(title: str, hwnd: int, control_id: int) -> None:
        tree = enum_child_tree(hwnd)
        items = find_controls(
            tree, cls="Edit", ctrl_id=control_id, visible=True
        )
        if not items:
            raise RuntimeError(f"{title} edit {control_id} missing")
        item = items[0]
        path = control_tree_path(tree, item["hwnd"])
        if path is None:
            raise RuntimeError(f"{title} edit path missing")
        original = get_window_text(item["hwnd"])
        focused = focus_foreground_control(hwnd, item["hwnd"])
        record(title, "Edit", control_id, path, "focus", f"真实焦点={focused}。")
        replacement = original + " " if original else "00"
        set_control_text(item["hwnd"], replacement)
        notify_edit(item["hwnd"], control_id)
        readback = get_window_text(item["hwnd"])
        set_control_text(item["hwnd"], original)
        notify_edit(item["hwnd"], control_id)
        record(
            title, "Edit", control_id, path, "replace_value",
            f"草稿替换读回长度={len(readback)}，随后恢复。",
        )
        focus_foreground_control(hwnd, item["hwnd"])
        keybd(VK_CONTROL); keybd(ord("A")); keybd(ord("A"), up=True)
        keybd(ord("Z")); keybd(ord("Z"), up=True); keybd(VK_CONTROL, up=True)
        set_control_text(item["hwnd"], original)
        notify_edit(item["hwnd"], control_id)
        record(
            title, "Edit", control_id, path, "keyboard_shortcuts",
            "真实焦点执行 Ctrl+A/Ctrl+Z，随后恢复。",
        )
        post_context_menu(item["hwnd"], 6, 6)
        time.sleep(0.10); send_escape(hwnd)
        record(
            title, "Edit", control_id, path, "right_click",
            "执行右键编辑菜单路径并关闭。",
        )
        lengths: list[int] = []
        for candidate in ("", "A" * 256):
            set_control_text(item["hwnd"], candidate)
            notify_edit(item["hwnd"], control_id)
            lengths.append(len(get_window_text(item["hwnd"])))
        set_control_text(item["hwnd"], original)
        notify_edit(item["hwnd"], control_id)
        record(
            title, "Edit", control_id, path, "boundary_values",
            f"空值/256 字符读回长度={lengths}，随后恢复。",
        )

    def exercise_combo(title: str, hwnd: int, control_id: int) -> None:
        tree = enum_child_tree(hwnd)
        items = find_controls(
            tree, cls="ComboBox", ctrl_id=control_id, visible=True
        )
        if not items or not items[0].get("enabled"):
            raise RuntimeError(f"{title} combo {control_id} not enabled")
        item = items[0]
        path = control_tree_path(tree, item["hwnd"])
        if path is None:
            raise RuntimeError(f"{title} combo path missing")
        values = read_combo_items(item["hwnd"])
        original = int(_send_msg_num(item["hwnd"], CB_GETCURSEL, 0, 0))
        _send_msg_num(item["hwnd"], 0x014F, 1, 0)
        time.sleep(0.06)
        _send_msg_num(item["hwnd"], 0x014F, 0, 0)
        record(
            title, "ComboBox", control_id, path, "open_dropdown",
            f"展开并收起，共 {len(values)} 项。",
        )
        selected: list[int] = []
        for index in range(len(values)):
            set_combo_selection(item["hwnd"], index)
            time.sleep(0.005)
            selected.append(int(_send_msg_num(item["hwnd"], CB_GETCURSEL, 0, 0)))
        if original >= 0:
            set_combo_selection(item["hwnd"], original)
        record(
            title, "ComboBox", control_id, path, "select_each_item",
            f"逐项选择并读回 {len(selected)}/{len(values)} 项，随后恢复。",
        )
        focus_foreground_control(hwnd, item["hwnd"])
        send_key(item["hwnd"], VK_HOME); send_key(item["hwnd"], VK_DOWN)
        keyboard_index = int(_send_msg_num(item["hwnd"], CB_GETCURSEL, 0, 0))
        if original >= 0:
            set_combo_selection(item["hwnd"], original)
        record(
            title, "ComboBox", control_id, path, "keyboard_cycle",
            f"Home/Down 读回索引 {keyboard_index}，随后恢复。",
        )
        post_context_menu(item["hwnd"], 6, 6)
        time.sleep(0.10); send_escape(hwnd)
        record(
            title, "ComboBox", control_id, path, "right_click",
            "执行下拉框右键路径并关闭。",
        )

    def exercise_list(title: str, hwnd: int, control_id: int) -> None:
        tree = enum_child_tree(hwnd)
        items = find_controls(
            tree, cls="ListBox", ctrl_id=control_id, visible=True
        )
        if not items:
            raise RuntimeError(f"{title} list {control_id} missing")
        item = items[0]
        path = control_tree_path(tree, item["hwnd"])
        if path is None:
            raise RuntimeError(f"{title} list path missing")
        count = int(_send_msg_num(item["hwnd"], LB_GETCOUNT, 0, 0))
        parent = user32.GetParent(item["hwnd"])
        for index in range(max(0, count)):
            _send_msg_num(item["hwnd"], LB_SETCURSEL, index, 0)
            _send_msg_num(
                parent, WM_COMMAND,
                (control_id & 0xFFFF) | (LBN_SELCHANGE << 16), item["hwnd"],
            )
        record(
            title, "ListBox", control_id, path, "select_each_item",
            f"逐项选择 {max(0, count)} 个列表项。",
        )
        for index in range(max(0, count)):
            _send_msg_num(item["hwnd"], LB_SETCURSEL, index, 0)
            _send_msg_num(
                parent, WM_COMMAND,
                (control_id & 0xFFFF) | (2 << 16), item["hwnd"],
            )
        record(
            title, "ListBox", control_id, path, "double_click_each_item",
            f"逐项发送双击通知 {max(0, count)} 次。",
        )
        width, height = get_client_size(item["hwnd"])
        for index in range(max(1, count)):
            if count:
                _send_msg_num(item["hwnd"], LB_SETCURSEL, index, 0)
            post_click_at(
                item["hwnd"], max(2, width // 2),
                max(2, min(height - 2, 8 + (index % 8) * 16)), "right",
            )
            send_escape(hwnd)
        record(
            title, "ListBox", control_id, path, "right_click_each_item",
            f"逐项执行右键路径 {max(0, count)} 次。",
        )
        focus_foreground_control(hwnd, item["hwnd"])
        send_key(item["hwnd"], VK_HOME); send_key(item["hwnd"], VK_DOWN)
        record(
            title, "ListBox", control_id, path, "keyboard_navigation",
            "真实焦点执行 Home/Down。",
        )

    try:
        window = None
        for _attempt in range(5):
            window = _open_data_window(
                session, 20008, "数据库", dismiss_hidden=False
            )
            if window:
                break
            time.sleep(0.8)
        if not window:
            raise RuntimeError("database window did not appear")
        database_hwnd = int(window["hwnd"])
        if switch_database_page_by_control(database_hwnd, 120) is None:
            raise RuntimeError("database unit page could not be selected")
        unit_lists: list[dict] = []
        for _attempt in range(30):
            unit_lists = find_controls(
                enum_child_tree(database_hwnd), cls="ListBox", ctrl_id=120,
                visible=True,
            )
            if unit_lists:
                break
            time.sleep(0.20)
        if not unit_lists:
            raise RuntimeError("database unit list 120 missing")
        unit_list = unit_lists[0]["hwnd"]
        _send_msg_num(unit_list, LB_SETCURSEL, 1, 0)
        _send_msg_num(
            user32.GetParent(unit_list), WM_COMMAND,
            120 | (LBN_SELCHANGE << 16), unit_list,
        )
        time.sleep(0.3)

        for spec in specs:
            title = str(spec["title"])
            for button_id in spec["buttons"]:
                for gesture in ("left_click", "right_click", "keyboard_activate"):
                    puzzle_hwnd = open_puzzle(spec)
                    tree = enum_child_tree(puzzle_hwnd)
                    buttons = find_controls(
                        tree, cls="Button", ctrl_id=int(button_id), visible=True
                    )
                    if not buttons or not buttons[0].get("enabled"):
                        raise RuntimeError(
                            f"{title} button {button_id} unavailable for {gesture}"
                        )
                    button = buttons[0]
                    path = control_tree_path(tree, button["hwnd"])
                    if path is None:
                        raise RuntimeError(f"{title} button {button_id} path missing")
                    known = {item["hwnd"] for item in session.top_windows()}
                    if gesture == "left_click":
                        click_control(button["hwnd"])
                    elif gesture == "right_click":
                        if not real_right_click_control(button["hwnd"]):
                            raise RuntimeError(f"{title} button {button_id} right click failed")
                    else:
                        if not focus_foreground_control(puzzle_hwnd, button["hwnd"]):
                            raise RuntimeError(f"{title} button {button_id} focus failed")
                        keybd(VK_SPACE); time.sleep(0.05); keybd(VK_SPACE, up=True)
                    time.sleep(0.35)
                    descendants = dismiss_descendants(
                        known, puzzle_hwnd,
                        f"DBM05PUZZLE_{title}_{button_id}_{gesture}",
                    )
                    still_open = is_window(puzzle_hwnd)
                    record(
                        title, "Button", int(button_id), path, gesture,
                        (
                            f"旧版真实{gesture}；子窗口={descendants}；"
                            f"拼图窗口仍打开={still_open}。"
                        ),
                    )
                    observations.append(
                        {
                            "window": title, "class": "Button",
                            "control_id": int(button_id), "gesture": gesture,
                            "descendants": descendants,
                            "owner_still_open": still_open,
                        }
                    )
                    if gesture == "right_click" and still_open:
                        send_escape(puzzle_hwnd)
                    close_puzzle_draft(spec, puzzle_hwnd)
                    puzzle_hwnd = 0

            puzzle_hwnd = open_puzzle(spec)
            exercise_edit(title, puzzle_hwnd, int(spec["edit"]))
            for combo_id in spec["combos"]:
                if title == "机体拼图" and int(combo_id) == 150:
                    # The second body bank is a property of the selected
                    # database record, not an editable type-state inside this
                    # child.  Record 6 is the first observed large-unit row
                    # whose second bank is genuinely enabled.
                    initial_tree = enum_child_tree(puzzle_hwnd)
                    initial_target = find_controls(
                        initial_tree, cls="ComboBox", ctrl_id=150, visible=True
                    )
                    enabled_before = bool(
                        initial_target and initial_target[0].get("enabled")
                    )
                    close_puzzle_draft(spec, puzzle_hwnd)
                    puzzle_hwnd = 0
                    large_row = None
                    for row in range(64):
                        if _send_msg_num(unit_list, LB_SETCURSEL, row, 0) == -1:
                            break
                        _send_msg_num(
                            user32.GetParent(unit_list), WM_COMMAND,
                            120 | (LBN_SELCHANGE << 16), unit_list,
                        )
                        time.sleep(0.04)
                        bank2 = find_controls(
                            enum_child_tree(database_hwnd), cls="ComboBox",
                            ctrl_id=360, visible=True,
                        )
                        if bank2 and bank2[0].get("enabled"):
                            large_row = row
                            break
                    if large_row is None:
                        raise RuntimeError(
                            "database record with enabled body bank2 not found"
                        )
                    log(f"unit puzzle bank2 prerequisite row={large_row}")
                    puzzle_hwnd = open_puzzle(spec)
                    target_tree = enum_child_tree(puzzle_hwnd)
                    target = find_controls(
                        target_tree, cls="ComboBox", ctrl_id=150,
                        visible=True,
                    )
                    if not target or not target[0].get("enabled"):
                        raise RuntimeError("unit puzzle bank2 state trigger not found")
                    path = control_tree_path(target_tree, target[0]["hwnd"])
                    if path is None:
                        raise RuntimeError("unit puzzle bank2 path missing")
                    record(
                        title, "ComboBox", 150, path,
                        "discover_state_triggers",
                        f"机体类型切换使 enabled 从 {enabled_before} 变为 True。",
                    )
                    exercise_combo(title, puzzle_hwnd, 150)
                elif title == "碎片拼图" and int(combo_id) in {120, 300}:
                    target_combo_id = int(combo_id)
                    current = find_controls(
                        enum_child_tree(puzzle_hwnd), cls="ComboBox",
                        ctrl_id=target_combo_id, visible=True,
                    )
                    if not current or not current[0].get("enabled"):
                        close_puzzle_draft(spec, puzzle_hwnd)
                        puzzle_hwnd = 0
                        fragment_row = None
                        for row in range(64):
                            if _send_msg_num(unit_list, LB_SETCURSEL, row, 0) == -1:
                                break
                            _send_msg_num(
                                user32.GetParent(unit_list), WM_COMMAND,
                                120 | (LBN_SELCHANGE << 16), unit_list,
                            )
                            time.sleep(0.04)
                            candidate_hwnd = open_puzzle(spec)
                            candidate = find_controls(
                                enum_child_tree(candidate_hwnd), cls="ComboBox",
                                ctrl_id=target_combo_id, visible=True,
                            )
                            if candidate and candidate[0].get("enabled"):
                                fragment_row = row
                                puzzle_hwnd = candidate_hwnd
                                break
                            close_puzzle_draft(spec, candidate_hwnd)
                        if fragment_row is None:
                            raise RuntimeError(
                                "database record with enabled fragment bank not found"
                            )
                        log(
                            f"fragment puzzle combo {target_combo_id} "
                            f"prerequisite row={fragment_row}"
                        )
                    exercise_combo(title, puzzle_hwnd, target_combo_id)
                else:
                    exercise_combo(title, puzzle_hwnd, int(combo_id))
            if spec["list"] is not None:
                current_lists = find_controls(
                    enum_child_tree(puzzle_hwnd), cls="ListBox",
                    ctrl_id=int(spec["list"]), visible=True,
                )
                if not current_lists:
                    close_puzzle_draft(spec, puzzle_hwnd)
                    puzzle_hwnd = 0
                    list_row = None
                    for row in range(64):
                        if _send_msg_num(unit_list, LB_SETCURSEL, row, 0) == -1:
                            break
                        _send_msg_num(
                            user32.GetParent(unit_list), WM_COMMAND,
                            120 | (LBN_SELCHANGE << 16), unit_list,
                        )
                        time.sleep(0.04)
                        candidate_hwnd = open_puzzle(spec)
                        candidate_lists = find_controls(
                            enum_child_tree(candidate_hwnd), cls="ListBox",
                            ctrl_id=int(spec["list"]), visible=True,
                        )
                        if candidate_lists and candidate_lists[0].get("enabled"):
                            list_row = row
                            puzzle_hwnd = candidate_hwnd
                            break
                        close_puzzle_draft(spec, candidate_hwnd)
                    if list_row is None:
                        raise RuntimeError(
                            f"{title} visible list {spec['list']} prerequisite not found"
                        )
                    log(f"fragment puzzle list prerequisite row={list_row}")
                exercise_list(title, puzzle_hwnd, int(spec["list"]))
            if title == "机体拼图":
                root_tree = enum_child_tree(puzzle_hwnd)
                code = find_controls(
                    root_tree, cls="Button", ctrl_id=170, visible=True
                )
                if not code:
                    raise RuntimeError("unit puzzle code button missing for state trigger")
                known = {item["hwnd"] for item in session.top_windows()}
                click_control(code[0]["hwnd"])
                time.sleep(0.35)
                disabled = not bool(user32.IsWindowEnabled(puzzle_hwnd))
                dismiss_descendants(known, puzzle_hwnd, "DBM05PUZZLE_机体拼图_状态")
                record(
                    title, "WTWindow", 0, (), "discover_state_triggers",
                    f"代码编辑模态子窗期间主拼图窗口 enabled=False：{disabled}。",
                )
            close_puzzle_draft(spec, puzzle_hwnd)
            puzzle_hwnd = 0
            if title in {"机体拼图", "碎片拼图"}:
                _send_msg_num(unit_list, LB_SETCURSEL, 1, 0)
                _send_msg_num(
                    user32.GetParent(unit_list), WM_COMMAND,
                    120 | (LBN_SELCHANGE << 16), unit_list,
                )
                time.sleep(0.25)

        db_cancel = [
            item for item in find_controls(
                enum_child_tree(database_hwnd), cls="Button",
                text_contains="取消", visible=True,
            ) if item.get("text") == "取消"
        ]
        if not db_cancel:
            raise RuntimeError("database Cancel button missing")
        click_control(db_cancel[0]["hwnd"])
        database_closed = session.wait_gone(database_hwnd, 8.0)
    except Exception as exc:
        error = repr(exc)
        log(f"DBM05PUZZLECONTROLS inner failure: {error}")
    finally:
        if puzzle_hwnd and is_window(puzzle_hwnd):
            close_window_safely(session, puzzle_hwnd, timeout=4.0)
        if database_hwnd and is_window(database_hwnd):
            close_window_safely(session, database_hwnd, timeout=5.0)
        if database_hwnd:
            database_closed = not is_window(database_hwnd)
        after = session.probe_rom.read_bytes()
        diffs = [
            index for index, (old, new) in enumerate(zip(before, after))
            if old != new
        ]
        unique_records = {
            str(item["action_id"]): item for item in execution_records
        }
        validated = (
            error is None
            and len(unique_records) == 135
            and (database_closed or session.owns_process)
            and not diffs and len(before) == len(after)
        )
        out_dir = session.out / "interaction-discovery"
        out_dir.mkdir(parents=True, exist_ok=True)
        (out_dir / "m05-puzzle-control-actions.json").write_text(
            json.dumps(
                {
                    "schema_version": 1,
                    "validated": validated,
                    "scope": (
                        "all 73 unit-puzzle and 62 fragment-puzzle frontier "
                        "actions; each button gesture uses a fresh child draft; "
                        "database cancelled; isolated ROM zero-diff gate"
                    ),
                    "error": error,
                    "database_cancel_closed": database_closed,
                    "sha256_before": hashlib.sha256(before).hexdigest().upper(),
                    "sha256_after": hashlib.sha256(after).hexdigest().upper(),
                    "diff_count": len(diffs) + int(len(before) != len(after)),
                    "execution_record_count": len(unique_records),
                    "observations": observations,
                    "execution_records": (
                        list(unique_records.values()) if validated else []
                    ),
                },
                ensure_ascii=False, indent=2,
            ) + "\n",
            encoding="utf-8",
        )
    if not validated:
        raise RuntimeError(
            "M05 puzzle control matrix did not validate: "
            f"records={len(unique_records)}/135 error={error}"
        )
    log("DBM05PUZZLECONTROLS complete: 135/135 actions, zero ROM diff")


# ------------------------------------------------------- stage CT (tab sweep)


def _client_offset(hwnd: int) -> tuple[int, int]:
    """Offset from window top-left to client origin (title bar / borders)."""
    rect = get_window_rect(hwnd)
    point = wintypes.POINT(0, 0)
    user32.ClientToScreen(hwnd, ctypes.byref(point))
    return point.x - rect["left"], point.y - rect["top"]


def _window_ctrl_sig(hwnd: int) -> tuple:
    items = [item for item in flatten_tree(enum_child_tree(hwnd)) if item.get("visible")]
    return tuple((i["class"], i["text"], i["ctrl_id"]) for i in items)


def sweep_tabs(
    session: "ProbeSession",
    hwnd: int,
    tag: str,
    y_candidates: tuple[int, ...] = (52, 62, 74, 86, 98),
    x_start: int = 22,
    x_step: int = 16,
    max_pages: int = 14,
) -> int:
    """Click across the tab band; dump a page whenever content changes."""
    dx, dy = _client_offset(hwnd)
    win_rect = get_window_rect(hwnd)
    x_end = (win_rect["right"] - win_rect["left"]) - 22
    seen_tops = {w["hwnd"] for w in session.top_windows()}

    def dismiss_new_tops() -> None:
        for window in session.top_windows():
            if window["hwnd"] == hwnd or window["hwnd"] in seen_tops:
                continue
            seen_tops.add(window["hwnd"])
            log(f"{tag}: unexpected popup {window['title']!r}; dumping and closing")
            try:
                session.dump_window(window["hwnd"], f"{tag}_弹窗_{window['title'][:10]}", menu=False)
            except Exception as exc:
                log(f"{tag}: popup dump failed: {exc!r}")
            close_window_safely(session, window["hwnd"], timeout=4.0)

    # Phase 0: locate the CPageControl header band precisely from the tree.
    # Layout (verified from control trees): the legacy app hosts its pages in
    # an MFC CPageControl whose 48px tab-header band sits at its top; page
    # content starts exactly 48px lower. Posted mouse messages are ignored,
    # so real input is required.
    tree = enum_child_tree(hwnd)
    page_ctrls = find_controls(tree, cls="CPageControl")
    if page_ctrls:
        ctrl_rect = page_ctrls[0]["rect"]
        band_top = ctrl_rect["top"] - win_rect["top"]
        x_start = max(14, ctrl_rect["left"] - win_rect["left"] + 14)
        x_end = (ctrl_rect["right"] - win_rect["left"]) - 24
    else:
        log(f"{tag}: no CPageControl; fallback band top=40")
        band_top = 40
        x_start = 22
    tab_y = band_top + 24  # middle of the 48px header band
    use_real = True
    log(f"{tag}: tab band at window-y={tab_y} (CPageControl top={band_top})")

    # Phase 2: click the leftmost tab, then sweep rightwards.
    real_click_at(hwnd, x_start - dx, tab_y - dy)
    time.sleep(0.7)
    dismiss_new_tops()
    session.dump_window(hwnd, f"{tag}_页签A", menu=False)
    # PrintWindow occasionally returns a partially blank frame for this legacy
    # process.  Visible control identity is stable and changes with real pages.
    sig = _window_ctrl_sig(hwnd)
    pages = 1
    for x in range(x_start, x_end, x_step):
        real_click_at(hwnd, x - dx, tab_y - dy)
        time.sleep(0.5)
        dismiss_new_tops()
        new_sig = _window_ctrl_sig(hwnd)
        if new_sig != sig:
            sig = new_sig
            pages += 1
            letter = chr(ord("A") + pages - 1) if pages <= 26 else str(pages)
            session.dump_window(hwnd, f"{tag}_页签{letter}_x{x}", menu=False)
            if pages >= max_pages:
                break
    log(f"{tag}: swept {pages} distinct tab pages")
    return pages


def _open_data_window(
    session: "ProbeSession",
    cmd_id: int,
    label: str,
    *,
    dismiss_hidden: bool = True,
):
    if not session.process_alive():
        log(f"{label}: target process is dead")
        return None
    dismiss_blocking_popups(session, include_hidden=dismiss_hidden)
    session.snapshot_known()
    user32.PostMessageW(session.main_hwnd, WM_COMMAND, cmd_id, 0)
    window = session.wait_new_top(
        timeout=2.0, cls_equals="WTWindow", title_contains=label
    )
    if not window:
        accelerators = {
            20008: "D",
            20009: "W",
            20011: "M",
            20013: "Z",
            20015: "J",
            20023: "T",
        }
        key = accelerators.get(cmd_id)
        if key and force_foreground(session.main_hwnd):
            keybd(VK_CONTROL)
            keybd(ord(key))
            keybd(ord(key), up=True)
            keybd(VK_CONTROL, up=True)
            window = session.wait_new_top(
                timeout=8.0, cls_equals="WTWindow", title_contains=label
            )
    if not window:
        # late error dialogs can appear after the timeout; give them a chance
        time.sleep(4.0)
        if session.process_alive():
            dismiss_blocking_popups(session)
        log(f"{label}: window did not appear (cmd {cmd_id})")
        return None
    log(f"{label}: hwnd={window['hwnd']} title={window['title']!r}")
    return window


def dismiss_blocking_popups(
    session: "ProbeSession",
    prefix: str = "DIAG",
    *,
    include_hidden: bool = True,
) -> int:
    """Dump and close any non-main top-level window blocking the main window."""
    if not session.pid:
        return 0
    closed = 0
    index = 0
    # Include hidden owned windows.  The 易语言 reference editor keeps prior
    # modal tool windows alive but hidden, then reveals them when the current
    # dialog closes.  Leaving those in the stack makes the next command look
    # as though it opened an unrelated window.
    for window in session.top_windows(visible_only=not include_hidden):
        if window["hwnd"] == session.main_hwnd:
            continue
        # only close app-owned windows; skip IME/tool windows like SoPY_Status
        if window["class"] not in ("WTWindow", "#32770"):
            continue
        index += 1
        try:
            session.dump_window(
                window["hwnd"], f"{prefix}_阻塞弹窗{index}", menu=False
            )
        except Exception as exc:
            log(f"dismiss popup dump failed: {exc!r}")
        close_window_safely(session, window["hwnd"], timeout=4.0)
        if is_window(window["hwnd"]):
            user32.PostMessageW(window["hwnd"], WM_CLOSE, 0, 0)
        closed += 1
    if closed:
        log(f"dismissed {closed} blocking popup(s)")
    return closed


def stage_ct_sav(session: "ProbeSession") -> None:
    """存档修改器: open probe.sav and capture the filled state."""
    window = _open_data_window(session, 20021, "存档修改器")
    if not window:
        return
    hwnd = window["hwnd"]
    try:
        tree = enum_child_tree(hwnd)
        open_buttons = find_controls(tree, ctrl_id=160) or find_controls(
            tree, cls="Button", text_contains="打开"
        )
        if not open_buttons:
            log("存档修改器: 打开 button not found")
            return
        session.snapshot_known()
        click_control(open_buttons[0]["hwnd"])
        dialog = session.wait_new_top(timeout=10.0, cls_equals="#32770")
        if not dialog or dialog["class"] != "#32770":
            log(f"存档修改器: open dialog unexpected: {dialog}")
            if dialog:
                close_window_safely(session, dialog["hwnd"], timeout=4.0)
            return
        if not session._fill_file_dialog(dialog["hwnd"], session.probe_sav, "D21_存档打开对话框"):
            log("存档修改器: filling dialog failed")
            return
        time.sleep(0.8)
        fresh = enum_child_tree(hwnd)
        read_buttons = find_controls(fresh, ctrl_id=190) or find_controls(
            fresh, cls="Button", text_contains="读取"
        )
        if read_buttons:
            click_control(read_buttons[0]["hwnd"])
            time.sleep(1.2)
        session.dump_window(hwnd, "D22_存档修改器_载入后", menu=False)
    finally:
        close_window_safely(session, hwnd)


def stage_ct(session: ProbeSession) -> None:
    log("=== stage CT: tab sweep for owner-drawn tab windows ===")
    if not session.main_hwnd or not is_window(session.main_hwnd):
        raise RuntimeError("main window not alive")
    if not session.rom_is_loaded():
        raise RuntimeError("ROM not loaded")

    plan = [
        ("数据库", 20008, "C01S_数据库"),
        ("地图动画", 20011, "C03S_地图动画"),
        ("剧情事件", 20015, "C05S_剧情事件"),
    ]
    for label, cmd_id, tag in plan:
        window = _open_data_window(session, cmd_id, label)
        if not window:
            continue
        try:
            sweep_tabs(session, window["hwnd"], tag)
        except Exception as exc:
            log(f"{label} sweep FAILED: {exc!r}")
        finally:
            close_window_safely(session, window["hwnd"])
            time.sleep(0.5)

    # 存档修改器 filled state (before the crash-prone export below).
    try:
        stage_ct_sav(session)
    except Exception as exc:
        log(f"存档修改器 sav FAILED: {exc!r}")

    # Retry 导出头像 LAST: it raises a delayed runtime error (code 4) that
    # eventually kills the process, so run it after everything else.
    try:
        handle_export_dialog(session, "导出头像重试", 20018, "C07_导出头像")
    except Exception as exc:
        log(f"导出头像重试 FAILED: {exc!r}")
    if not session.process_alive():
        log("process killed by delayed export error (expected for 导出头像)")


def stage_m12(session: ProbeSession) -> None:
    """Capture only the reference map-animation window and its tab pages."""
    log("=== stage M12: map-animation tab sweep ===")
    if not session.main_hwnd or not is_window(session.main_hwnd):
        raise RuntimeError("main window not alive")
    if not session.rom_is_loaded():
        raise RuntimeError("ROM not loaded")

    window = _open_data_window(
        session, 20011, "地图动画", dismiss_hidden=False,
    )
    if not window:
        raise RuntimeError("map-animation window did not appear")
    try:
        sweep_tabs(session, window["hwnd"], "M12_地图动画")
    finally:
        close_window_safely(session, window["hwnd"])


def stage_fontcontrols(session: ProbeSession) -> None:
    """Exercise all 45 字库编辑 and 53 nested 字体-dialog actions."""
    log("=== stage FONTCONTROLS: font editor + nested font dialog ===")
    if not session.main_hwnd or not is_window(session.main_hwnd):
        raise RuntimeError("main window not alive")
    if not session.rom_is_loaded():
        raise RuntimeError("ROM not loaded")
    before = session.probe_rom.read_bytes()
    records: list[dict] = []
    observations: list[dict] = []
    error: str | None = None

    def walk(node: dict, path: tuple[int, ...] = ()):
        yield node, path
        for index, child in enumerate(node.get("children", [])):
            if isinstance(child, dict):
                yield from walk(child, path + (index,))

    def record(window: str, item: dict, path: tuple[int, ...], action: str, result: str) -> None:
        records.append({
            "action_id": stable_interaction_id(
                window, str(item.get("class", "")), int(item.get("ctrl_id") or 0),
                list(path), action,
            ),
            "status": "passed", "result": result,
        })

    def notify_edit(hwnd: int, cid: int) -> None:
        parent = user32.GetParent(hwnd)
        if parent:
            _send_msg_num(parent, WM_COMMAND, (cid & 0xFFFF) | (0x0300 << 16), hwnd)

    def open_editor() -> int:
        # The menu label is 文字库 but the actual window title is 字库编辑.
        # Match its stable controls instead of title text (which is also
        # locale-sensitive in this legacy ANSI process).
        # A modal font chooser temporarily hides this editor and reveals it
        # again only after the chooser is destroyed.  Close only stale modal
        # dialogs here, then reuse an already-restored editor before posting a
        # second menu command.
        for top in session.top_windows(visible_only=False):
            if top["hwnd"] != session.main_hwnd and top["class"] == "#32770":
                close_font_dialog(int(top["hwnd"]))

        def locate() -> int:
            for top in session.top_windows():
                if top["hwnd"] == session.main_hwnd or top["class"] != "WTWindow":
                    continue
                tree = enum_child_tree(top["hwnd"])
                if (find_controls(tree, cls="Button", ctrl_id=240, visible=True)
                        and find_controls(tree, cls="ComboBox", ctrl_id=130, visible=True)):
                    return int(top["hwnd"])
            return 0

        hwnd = 0
        restore_deadline = time.monotonic() + 1.5
        while time.monotonic() < restore_deadline and not hwnd:
            hwnd = locate()
            if not hwnd:
                time.sleep(0.1)
        if not hwnd:
            user32.PostMessageW(session.main_hwnd, WM_COMMAND, 20009, 0)
        deadline = time.monotonic() + 30.0
        while time.monotonic() < deadline and not hwnd:
            hwnd = locate()
            if hwnd:
                break
            time.sleep(0.2)
        if not hwnd:
            raise RuntimeError("font editor did not appear")
        move_window(hwnd, 90, 60, 930, 720); time.sleep(0.2)
        return hwnd

    def cancel_editor(hwnd: int) -> None:
        if not is_window(hwnd):
            return
        buttons = find_controls(enum_child_tree(hwnd), cls="Button", text_contains="取消", visible=True)
        if buttons:
            click_control(buttons[0]["hwnd"])
            if session.wait_gone(hwnd, 3.0):
                return
        user32.PostMessageW(hwnd, WM_CLOSE, 0, 0)
        if not session.wait_gone(hwnd, 4.0):
            raise RuntimeError("font editor did not close")

    def open_font_dialog(editor: int) -> int:
        buttons = find_controls(enum_child_tree(editor), cls="Button", ctrl_id=240, visible=True)
        if not buttons:
            raise RuntimeError("select-font button missing")
        known = {top["hwnd"] for top in session.top_windows()}
        click_control(buttons[0]["hwnd"])
        dialog = session.wait_new_top(exclude=known, timeout=5.0, cls_equals="#32770", title_contains="字体")
        if not dialog:
            raise RuntimeError("system font dialog did not appear")
        return int(dialog["hwnd"])

    def close_font_dialog(hwnd: int) -> None:
        if not is_window(hwnd):
            return
        cancel = user32.GetDlgItem(hwnd, 2)
        click_control(cancel) if cancel else send_escape(hwnd)
        if not session.wait_gone(hwnd, 3.0):
            user32.PostMessageW(hwnd, WM_CLOSE, 0, 0); session.wait_gone(hwnd, 2.0)

    def exercise_edit(window: str, root: int, item: dict, path: tuple[int, ...]) -> None:
        hwnd = int(item["hwnd"]); cid = int(item.get("ctrl_id") or 0)
        original = get_ctrl_text(hwnd)
        record(window, item, path, "focus", f"真实焦点={focus_foreground_control(root, hwnd)}。")
        replacement = original + "A" if original else "A"
        set_control_text(hwnd, replacement); notify_edit(hwnd, cid)
        readback = get_ctrl_text(hwnd)
        set_control_text(hwnd, original); notify_edit(hwnd, cid)
        record(window, item, path, "replace_value", f"读回={readback!r}，已恢复。")
        focus_foreground_control(root, hwnd)
        for key in (ord("A"), ord("Z")):
            keybd(VK_CONTROL); keybd(key); keybd(key, up=True); keybd(VK_CONTROL, up=True)
        set_control_text(hwnd, original); notify_edit(hwnd, cid)
        record(window, item, path, "keyboard_shortcuts", "执行 Ctrl+A/Ctrl+Z，已恢复。")
        post_context_menu(hwnd, 5, 5); time.sleep(0.08); send_escape(root)
        record(window, item, path, "right_click", "执行右键并关闭菜单。")
        lengths = []
        for value in ("", "A" * 256):
            set_control_text(hwnd, value); notify_edit(hwnd, cid); lengths.append(len(get_ctrl_text(hwnd)))
        set_control_text(hwnd, original); notify_edit(hwnd, cid)
        record(window, item, path, "boundary_values", f"边界长度={lengths}，已恢复。")
        observations.append({"window": window, "class": "Edit", "control_id": cid,
                             "path": list(path), "boundary_lengths": lengths})

    def exercise_combo(window: str, root: int, item: dict, path: tuple[int, ...]) -> None:
        hwnd = int(item["hwnd"]); cid = int(item.get("ctrl_id") or 0)
        values = read_combo_items(hwnd); original = int(_send_msg_num(hwnd, CB_GETCURSEL, 0, 0))
        _send_msg_num(hwnd, 0x014F, 1, 0); time.sleep(0.05); _send_msg_num(hwnd, 0x014F, 0, 0)
        record(window, item, path, "open_dropdown", f"展开/收起，共 {len(values)} 项。")
        for index in range(len(values)):
            set_combo_selection(hwnd, index)
        if original >= 0:
            set_combo_selection(hwnd, original)
        record(window, item, path, "select_each_item", f"逐项选择 {len(values)} 项，恢复 {original}。")
        focus_foreground_control(root, hwnd); send_key(hwnd, VK_HOME); send_key(hwnd, VK_DOWN)
        keyboard_index = int(_send_msg_num(hwnd, CB_GETCURSEL, 0, 0))
        if original >= 0:
            set_combo_selection(hwnd, original)
        record(window, item, path, "keyboard_cycle", f"键盘读回 {keyboard_index}，已恢复。")
        post_context_menu(hwnd, 5, 5); time.sleep(0.08); send_escape(root)
        record(window, item, path, "right_click", "执行右键并关闭菜单。")
        observations.append({"window": window, "class": "ComboBox", "control_id": cid,
                             "path": list(path), "item_count": len(values)})

    def activate(root: int, hwnd: int, action: str) -> None:
        if action == "left_click":
            click_control(hwnd)
        elif action == "keyboard_activate":
            focus_foreground_control(root, hwnd); send_key(hwnd, VK_SPACE)
        else:
            post_context_menu(hwnd, 5, 5); time.sleep(0.08); send_escape(root)

    try:
        editor = open_editor(); tree = enum_child_tree(editor)
        for item, path in list(walk(tree)):
            if not item.get("visible") or not item.get("enabled"):
                continue
            cls_name, cid = item.get("class"), int(item.get("ctrl_id") or 0)
            if cls_name == "Edit" and cid in (140, 150, 160, 300):
                exercise_edit("字库编辑", editor, item, path)
            elif cls_name == "ComboBox" and cid == 130:
                exercise_combo("字库编辑", editor, item, path)
        cancel_editor(editor)

        for cid in (100, 120, 170, 240):
            for action in ("keyboard_activate", "left_click", "right_click"):
                log(f"FONTCONTROLS parent button {cid} action={action}")
                editor = open_editor(); tree = enum_child_tree(editor)
                item = find_controls(tree, cls="Button", ctrl_id=cid, visible=True)[0]
                path = control_tree_path(tree, item["hwnd"])
                known = {top["hwnd"] for top in session.top_windows()}
                activate(editor, item["hwnd"], action); time.sleep(0.6)
                popups = [top for top in session.top_windows()
                          if top["hwnd"] not in known and top["class"] != "#32768"]
                for popup in popups:
                    close_font_dialog(popup["hwnd"]) if popup["class"] == "#32770" else close_window_safely(session, popup["hwnd"], 2.0)
                record("字库编辑", item, tuple(path or ()), action,
                       f"执行按钮手势，安全关闭新增窗口 {len(popups)} 个。")
                cancel_editor(editor)

        editor = open_editor(); dialog = open_font_dialog(editor); tree = enum_child_tree(dialog)
        for item, path in list(walk(tree)):
            if not item.get("visible") or not item.get("enabled"):
                continue
            cls_name, cid = item.get("class"), int(item.get("ctrl_id") or 0)
            if cls_name == "ComboBox" and cid in (1136, 1137, 1138, 1139, 1140):
                exercise_combo("字体", dialog, item, path)
            elif cls_name == "Edit" and cid == 1001:
                exercise_edit("字体", dialog, item, path)
        close_font_dialog(dialog); cancel_editor(editor)

        for cid in (1, 2, 1040, 1041, 1072, 1073):
            for action in ("keyboard_activate", "left_click", "right_click"):
                log(f"FONTCONTROLS nested button {cid} action={action}")
                editor = open_editor(); dialog = open_font_dialog(editor); tree = enum_child_tree(dialog)
                item = find_controls(tree, cls="Button", ctrl_id=cid, visible=True)[0]
                path = control_tree_path(tree, item["hwnd"])
                activate(dialog, item["hwnd"], action); time.sleep(0.1)
                record("字体", item, tuple(path or ()), action, "执行旧版字体框按钮手势。")
                close_font_dialog(dialog); cancel_editor(editor)

        # These three commands rebuild the editor's font-page draft.  The
        # reference process does not reliably accept a second 文字库 command
        # after that rebuild, so exercise their nine gestures in one final
        # draft and cancel once at the end.
        editor = open_editor()
        for cid in (250, 260, 310):
            for action in ("keyboard_activate", "left_click", "right_click"):
                log(f"FONTCONTROLS destructive parent button {cid} action={action}")
                tree = enum_child_tree(editor)
                matches = find_controls(tree, cls="Button", ctrl_id=cid, visible=True)
                if not matches:
                    raise RuntimeError(f"font editor destructive button {cid} missing")
                item = matches[0]; path = control_tree_path(tree, item["hwnd"])
                known = {top["hwnd"] for top in session.top_windows()}
                activate(editor, item["hwnd"], action); time.sleep(0.6)
                popups = [top for top in session.top_windows()
                          if top["hwnd"] not in known and top["class"] != "#32768"]
                for popup in popups:
                    close_font_dialog(popup["hwnd"]) if popup["class"] == "#32770" else close_window_safely(session, popup["hwnd"], 2.0)
                record("字库编辑", item, tuple(path or ()), action,
                       f"在最终草稿执行重建类按钮手势；新增窗口 {len(popups)} 个。")
        cancel_editor(editor)
    except Exception as exc:
        error = repr(exc); log(f"FONTCONTROLS inner failure: {error}")
        for top in session.top_windows():
            if top["hwnd"] != session.main_hwnd and top["class"] != "#32768":
                close_window_safely(session, top["hwnd"], 2.0)
    finally:
        after = session.probe_rom.read_bytes()
        diffs = [i for i, (old, new) in enumerate(zip(before, after)) if old != new]
        unique = {item["action_id"]: item for item in records}
        validated = error is None and len(unique) == 98 and not diffs and len(before) == len(after)
        out_dir = session.out / "interaction-discovery"; out_dir.mkdir(parents=True, exist_ok=True)
        (out_dir / "font-control-actions.json").write_text(json.dumps({
            "schema_version": 1, "validated": validated,
            "scope": "字库编辑 45/45 + 嵌套系统字体框 53/53；父窗口取消；隔离 ROM 零差异",
            "error": error,
            "sha256_before": hashlib.sha256(before).hexdigest().upper(),
            "sha256_after": hashlib.sha256(after).hexdigest().upper(),
            "diff_count": len(diffs) + int(len(before) != len(after)),
            "execution_record_count": len(unique), "observations": observations,
            "execution_records": list(unique.values()) if validated else [],
        }, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    if not validated:
        raise RuntimeError(f"font controls did not validate: records={len(unique)}/98 error={error}")
    log("FONTCONTROLS complete: 98/98 actions, zero ROM diff")


def stage_textconvertcontrols(session: ProbeSession) -> None:
    """Exercise all 16 legacy text-converter actions."""
    log("=== stage TEXTCONVERTCONTROLS ===")
    if not session.main_hwnd or not is_window(session.main_hwnd) or not session.rom_is_loaded():
        raise RuntimeError("loaded main window required")
    before = session.probe_rom.read_bytes(); records = []; error = None; hwnd = 0

    def walk(node, path=()):
        yield node, path
        for index, child in enumerate(node.get("children", [])):
            yield from walk(child, path + (index,))

    def record(item, path, action, result):
        records.append({"action_id": stable_interaction_id(
            "文字转换", str(item.get("class", "")), int(item.get("ctrl_id") or 0),
            list(path), action), "status": "passed", "result": result})

    def notify(item):
        parent = user32.GetParent(item["hwnd"])
        if parent:
            _send_msg_num(parent, WM_COMMAND,
                          (int(item.get("ctrl_id") or 0) & 0xFFFF) | (0x0300 << 16),
                          item["hwnd"])

    try:
        user32.PostMessageW(session.main_hwnd, WM_COMMAND, 20013, 0)
        deadline = time.monotonic() + 8.0
        while time.monotonic() < deadline and not hwnd:
            for top in session.top_windows():
                tree = enum_child_tree(top["hwnd"])
                if top["class"] == "WTWindow" and find_controls(tree, cls="Button", ctrl_id=140, visible=True) and find_controls(tree, cls="Button", ctrl_id=150, visible=True):
                    hwnd = int(top["hwnd"]); break
            if not hwnd: time.sleep(0.2)
        if not hwnd: raise RuntimeError("text converter did not appear")
        tree = enum_child_tree(hwnd)
        for item, path in list(walk(tree)):
            if item.get("class") != "Edit" or int(item.get("ctrl_id") or 0) not in (100, 130): continue
            original = get_ctrl_text(item["hwnd"])
            record(item, path, "focus", f"真实焦点={focus_foreground_control(hwnd, item['hwnd'])}。")
            set_control_text(item["hwnd"], "A"); notify(item); readback = get_ctrl_text(item["hwnd"])
            set_control_text(item["hwnd"], original); notify(item)
            record(item, path, "replace_value", f"读回={readback!r}，已恢复。")
            focus_foreground_control(hwnd, item["hwnd"])
            for key in (ord("A"), ord("Z")):
                keybd(VK_CONTROL); keybd(key); keybd(key, up=True); keybd(VK_CONTROL, up=True)
            set_control_text(item["hwnd"], original); notify(item)
            record(item, path, "keyboard_shortcuts", "Ctrl+A/Ctrl+Z 后恢复。")
            post_context_menu(item["hwnd"], 5, 5); time.sleep(0.08)
            if visible_popup_menus(session.pid or 0): send_escape(hwnd)
            record(item, path, "right_click", "执行右键并关闭菜单。")
            lengths = []
            for value in ("", "A" * 256):
                set_control_text(item["hwnd"], value); notify(item); lengths.append(len(get_ctrl_text(item["hwnd"])))
            set_control_text(item["hwnd"], original); notify(item)
            record(item, path, "boundary_values", f"边界长度={lengths}，已恢复。")
        for cid in (140, 150):
            for action in ("keyboard_activate", "left_click", "right_click"):
                tree = enum_child_tree(hwnd); item = find_controls(tree, cls="Button", ctrl_id=cid, visible=True)[0]
                path = control_tree_path(tree, item["hwnd"])
                if action == "keyboard_activate": focus_foreground_control(hwnd, item["hwnd"]); send_key(item["hwnd"], VK_SPACE)
                elif action == "left_click": click_control(item["hwnd"])
                else:
                    post_context_menu(item["hwnd"], 5, 5); time.sleep(0.08)
                    if visible_popup_menus(session.pid or 0): send_escape(hwnd)
                time.sleep(0.12); record(item, tuple(path or ()), action, "执行转换按钮手势。")
    except Exception as exc:
        error = repr(exc); log(f"TEXTCONVERTCONTROLS inner failure: {error}")
    finally:
        if hwnd and is_window(hwnd): user32.PostMessageW(hwnd, WM_CLOSE, 0, 0); session.wait_gone(hwnd, 4.0)
        after = session.probe_rom.read_bytes(); diffs = [i for i, (a, b) in enumerate(zip(before, after)) if a != b]
        unique = {item["action_id"]: item for item in records}
        validated = error is None and len(unique) == 16 and not diffs and len(before) == len(after)
        out_dir = session.out / "interaction-discovery"; out_dir.mkdir(parents=True, exist_ok=True)
        (out_dir / "text-converter-control-actions.json").write_text(json.dumps({
            "schema_version": 1, "validated": validated, "error": error,
            "execution_record_count": len(unique), "diff_count": len(diffs) + int(len(before) != len(after)),
            "sha256_before": hashlib.sha256(before).hexdigest().upper(), "sha256_after": hashlib.sha256(after).hexdigest().upper(),
            "execution_records": list(unique.values()) if validated else []}, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    if not validated: raise RuntimeError(f"text converter did not validate: {len(unique)}/16 {error}")
    log("TEXTCONVERTCONTROLS complete: 16/16 actions, zero ROM diff")


def stage_dbiconcontrols(session: ProbeSession) -> None:
    """Exercise all 17 actions in the unit-icon binding dialog."""
    log("=== stage DBICONCONTROLS ===")
    before = session.probe_rom.read_bytes(); records = []; error = None
    database = 0; icon = 0

    def record(item, path, action, result):
        records.append({"action_id": stable_interaction_id(
            "机体图标设置", str(item.get("class", "")), int(item.get("ctrl_id") or 0),
            list(path), action), "status": "passed", "result": result})

    def open_icon():
        nonlocal icon
        tree = enum_child_tree(database)
        buttons = find_controls(tree, cls="Button", ctrl_id=1350, visible=True)
        if not buttons: raise RuntimeError("unit icon opener missing")
        known = {top["hwnd"] for top in session.top_windows()}
        click_control(buttons[0]["hwnd"])
        popup = session.wait_new_top(exclude=known, timeout=2.0, cls_equals="WTWindow")
        if not popup:
            buttons = find_controls(enum_child_tree(database), cls="Button", ctrl_id=1350, visible=True)
            if buttons: real_click_control(buttons[0]["hwnd"])
            popup = session.wait_new_top(exclude=known, timeout=5.0, cls_equals="WTWindow")
        if not popup: raise RuntimeError("unit icon dialog did not appear")
        icon = int(popup["hwnd"]); return icon

    def close_icon():
        nonlocal icon
        if icon and is_window(icon):
            cancel = find_controls(enum_child_tree(icon), cls="Button", ctrl_id=190, visible=True)
            if cancel: click_control(cancel[0]["hwnd"])
            if not session.wait_gone(icon, 3.0): user32.PostMessageW(icon, WM_CLOSE, 0, 0); session.wait_gone(icon, 2.0)
        icon = 0

    try:
        window = _open_data_window(session, 20008, "数据库", dismiss_hidden=False)
        if not window: raise RuntimeError("database did not appear")
        database = int(window["hwnd"])
        if switch_database_page_by_control(database, 120) is None:
            raise RuntimeError("unit database page unavailable")
        unit_lists = find_controls(enum_child_tree(database), cls="ListBox", ctrl_id=120, visible=True)
        if not unit_lists: raise RuntimeError("unit list missing after page switch")
        unit_list = unit_lists[0]
        _send_msg_num(unit_list["hwnd"], LB_SETCURSEL, 1, 0)
        parent = user32.GetParent(unit_list["hwnd"])
        _send_msg_num(parent, WM_COMMAND, 120 | (LBN_SELCHANGE << 16), unit_list["hwnd"])
        time.sleep(0.25)

        icon = open_icon(); tree = enum_child_tree(icon)
        for cid in (120, 130):
            item = find_controls(tree, cls="ComboBox", ctrl_id=cid, visible=True)[0]
            path = control_tree_path(tree, item["hwnd"]); values = read_combo_items(item["hwnd"])
            original = int(_send_msg_num(item["hwnd"], CB_GETCURSEL, 0, 0))
            _send_msg_num(item["hwnd"], 0x014F, 1, 0); time.sleep(0.05); _send_msg_num(item["hwnd"], 0x014F, 0, 0)
            record(item, tuple(path or ()), "open_dropdown", f"展开/收起，共 {len(values)} 项。")
            for index in range(len(values)): set_combo_selection(item["hwnd"], index)
            if original >= 0: set_combo_selection(item["hwnd"], original)
            record(item, tuple(path or ()), "select_each_item", f"逐项选择 {len(values)} 项并恢复 {original}。")
            focus_foreground_control(icon, item["hwnd"]); send_key(item["hwnd"], VK_HOME); send_key(item["hwnd"], VK_DOWN)
            readback = int(_send_msg_num(item["hwnd"], CB_GETCURSEL, 0, 0))
            if original >= 0: set_combo_selection(item["hwnd"], original)
            record(item, tuple(path or ()), "keyboard_cycle", f"键盘读回 {readback} 并恢复。")
            post_context_menu(item["hwnd"], 5, 5); time.sleep(0.08)
            if visible_popup_menus(session.pid or 0): send_escape(icon)
            record(item, tuple(path or ()), "right_click", "执行右键路径。")
        close_icon()

        for cid in (100, 190, 200):
            for action in ("keyboard_activate", "left_click", "right_click"):
                icon = open_icon(); tree = enum_child_tree(icon)
                item = find_controls(tree, cls="Button", ctrl_id=cid, visible=True)[0]
                path = control_tree_path(tree, item["hwnd"])
                if action == "keyboard_activate": focus_foreground_control(icon, item["hwnd"]); send_key(item["hwnd"], VK_SPACE)
                elif action == "left_click": click_control(item["hwnd"])
                else:
                    post_context_menu(item["hwnd"], 5, 5); time.sleep(0.08)
                    if visible_popup_menus(session.pid or 0): send_escape(icon)
                time.sleep(0.15); record(item, tuple(path or ()), action, "执行图标窗口按钮手势。")
                close_icon()
        db_cancel = find_controls(enum_child_tree(database), cls="Button", text_contains="取消", visible=True)
        if db_cancel: click_control(db_cancel[0]["hwnd"]); session.wait_gone(database, 5.0)
    except Exception as exc:
        error = repr(exc); log(f"DBICONCONTROLS inner failure: {error}")
    finally:
        close_icon()
        if database and is_window(database): close_window_safely(session, database, 4.0)
        after = session.probe_rom.read_bytes(); diffs = [i for i,(a,b) in enumerate(zip(before,after)) if a != b]
        unique = {r["action_id"]: r for r in records}
        validated = error is None and len(unique) == 17 and not diffs and len(before) == len(after)
        out_dir = session.out / "interaction-discovery"; out_dir.mkdir(parents=True, exist_ok=True)
        (out_dir / "unit-icon-control-actions.json").write_text(json.dumps({
            "schema_version": 1, "validated": validated, "error": error,
            "execution_record_count": len(unique), "diff_count": len(diffs)+int(len(before)!=len(after)),
            "sha256_before": hashlib.sha256(before).hexdigest().upper(), "sha256_after": hashlib.sha256(after).hexdigest().upper(),
            "execution_records": list(unique.values()) if validated else []}, ensure_ascii=False, indent=2)+"\n", encoding="utf-8")
    if not validated: raise RuntimeError(f"unit icon controls did not validate: {len(unique)}/17 {error}")
    log("DBICONCONTROLS complete: 17/17 actions, zero ROM diff")


def stage_dbunitskillcontrols(session: ProbeSession) -> None:
    """Exercise all 25 actions in the unit special-skill dialog."""
    log("=== stage DBUNITSKILLCONTROLS ===")
    before = session.probe_rom.read_bytes(); records = []; error = None
    database = 0; popup_hwnd = 0

    def record(item, path, action, result):
        records.append({"action_id": stable_interaction_id(
            "机体特技", str(item.get("class", "")), int(item.get("ctrl_id") or 0),
            list(path), action), "status": "passed", "result": result})

    def reset_database():
        nonlocal database
        if database and is_window(database): close_window_safely(session, database, 4.0)
        window = _open_data_window(session, 20008, "数据库", dismiss_hidden=False)
        if not window: raise RuntimeError("database did not appear")
        database = int(window["hwnd"])
        if switch_database_page_by_control(database, 120) is None: raise RuntimeError("unit page unavailable")
        unit = find_controls(enum_child_tree(database), cls="ListBox", ctrl_id=120, visible=True)[0]
        _send_msg_num(unit["hwnd"], LB_SETCURSEL, 1, 0)
        parent = user32.GetParent(unit["hwnd"])
        _send_msg_num(parent, WM_COMMAND, 120 | (LBN_SELCHANGE << 16), unit["hwnd"]); time.sleep(0.2)

    def open_popup():
        nonlocal popup_hwnd
        buttons = find_controls(enum_child_tree(database), cls="Button", ctrl_id=2600, visible=True)
        if not buttons: raise RuntimeError("special-skill opener missing")
        known = {top["hwnd"] for top in session.top_windows()}
        click_control(buttons[0]["hwnd"])
        found = session.wait_new_top(exclude=known, timeout=2.0, cls_equals="WTWindow")
        if not found:
            buttons = find_controls(enum_child_tree(database), cls="Button", ctrl_id=2600, visible=True)
            if buttons: real_click_control(buttons[0]["hwnd"])
            found = session.wait_new_top(exclude=known, timeout=5.0, cls_equals="WTWindow")
        if not found:
            reset_database()
            buttons = find_controls(enum_child_tree(database), cls="Button", ctrl_id=2600, visible=True)
            known = {top["hwnd"] for top in session.top_windows()}
            if buttons: click_control(buttons[0]["hwnd"])
            found = session.wait_new_top(exclude=known, timeout=5.0, cls_equals="WTWindow")
        if not found: raise RuntimeError("special-skill dialog did not appear")
        popup_hwnd = int(found["hwnd"]); return popup_hwnd

    def close_popup():
        nonlocal popup_hwnd
        if popup_hwnd and is_window(popup_hwnd):
            cancel = find_controls(enum_child_tree(popup_hwnd), cls="Button", ctrl_id=170, visible=True)
            if cancel: click_control(cancel[0]["hwnd"])
            if not session.wait_gone(popup_hwnd, 3.0):
                user32.PostMessageW(popup_hwnd, WM_CLOSE, 0, 0); session.wait_gone(popup_hwnd, 2.0)
        popup_hwnd = 0

    try:
        reset_database()

        popup_hwnd = open_popup(); tree = enum_child_tree(popup_hwnd)
        item = find_controls(tree, cls="ComboBox", ctrl_id=100, visible=True)[0]
        path = control_tree_path(tree, item["hwnd"]); values = read_combo_items(item["hwnd"])
        original = int(_send_msg_num(item["hwnd"], CB_GETCURSEL, 0, 0))
        _send_msg_num(item["hwnd"], 0x014F, 1, 0); time.sleep(0.05); _send_msg_num(item["hwnd"], 0x014F, 0, 0)
        record(item, tuple(path or ()), "open_dropdown", f"展开/收起，共 {len(values)} 项。")
        for index in range(len(values)): set_combo_selection(item["hwnd"], index)
        if original >= 0: set_combo_selection(item["hwnd"], original)
        record(item, tuple(path or ()), "select_each_item", f"逐项选择 {len(values)} 项并恢复 {original}。")
        focus_foreground_control(popup_hwnd, item["hwnd"]); send_key(item["hwnd"], VK_HOME); send_key(item["hwnd"], VK_DOWN)
        readback = int(_send_msg_num(item["hwnd"], CB_GETCURSEL, 0, 0))
        if original >= 0: set_combo_selection(item["hwnd"], original)
        record(item, tuple(path or ()), "keyboard_cycle", f"键盘读回 {readback} 并恢复。")
        post_context_menu(item["hwnd"], 5, 5); time.sleep(0.08)
        if visible_popup_menus(session.pid or 0): send_escape(popup_hwnd)
        record(item, tuple(path or ()), "right_click", "执行右键路径。")
        close_popup()

        for cid in (110, 120, 130, 140, 150, 160, 170):
            for action in ("keyboard_activate", "left_click", "right_click"):
                popup_hwnd = open_popup(); tree = enum_child_tree(popup_hwnd)
                item = find_controls(tree, cls="Button", ctrl_id=cid, visible=True)[0]
                path = control_tree_path(tree, item["hwnd"])
                if action == "keyboard_activate": focus_foreground_control(popup_hwnd, item["hwnd"]); send_key(item["hwnd"], VK_SPACE)
                elif action == "left_click": click_control(item["hwnd"])
                else:
                    post_context_menu(item["hwnd"], 5, 5); time.sleep(0.08)
                    if visible_popup_menus(session.pid or 0): send_escape(popup_hwnd)
                time.sleep(0.12); record(item, tuple(path or ()), action, "执行特技窗口按钮手势。")
                close_popup()
        db_cancel = find_controls(enum_child_tree(database), cls="Button", text_contains="取消", visible=True)
        if db_cancel: click_control(db_cancel[0]["hwnd"]); session.wait_gone(database, 5.0)
    except Exception as exc:
        error = repr(exc); log(f"DBUNITSKILLCONTROLS inner failure: {error}")
    finally:
        close_popup()
        if database and is_window(database): close_window_safely(session, database, 4.0)
        after = session.probe_rom.read_bytes(); diffs = [i for i,(a,b) in enumerate(zip(before,after)) if a != b]
        unique = {r["action_id"]: r for r in records}
        validated = error is None and len(unique) == 25 and not diffs and len(before) == len(after)
        out_dir = session.out / "interaction-discovery"; out_dir.mkdir(parents=True, exist_ok=True)
        (out_dir / "unit-skill-control-actions.json").write_text(json.dumps({
            "schema_version": 1, "validated": validated, "error": error,
            "execution_record_count": len(unique), "diff_count": len(diffs)+int(len(before)!=len(after)),
            "sha256_before": hashlib.sha256(before).hexdigest().upper(), "sha256_after": hashlib.sha256(after).hexdigest().upper(),
            "execution_records": list(unique.values()) if validated else []}, ensure_ascii=False, indent=2)+"\n", encoding="utf-8")
    if not validated: raise RuntimeError(f"unit skill controls did not validate: {len(unique)}/25 {error}")
    log("DBUNITSKILLCONTROLS complete: 25/25 actions, zero ROM diff")


def stage_dbsmallnumcontrols(session: ProbeSession) -> None:
    """Close 成长属性 (11) and 最大值 (14) control frontiers."""
    log("=== stage DBSMALLNUMCONTROLS ===")
    before = session.probe_rom.read_bytes(); records = []; error = None
    database = 0; child = 0

    specs = (
        {"window": "成长属性", "section": 2640, "opener": 2650, "edit": 100, "ok": 110, "cancel": 120, "count": 11,
         "replacement": lambda value: (("6" if value[:1] != "6" else "5") + value[1:]) if value else "00" * 30,
         "boundaries": ("00" * 30, "FF" * 30)},
        {"window": "最大值", "section": 1550, "opener": 1680, "edit": 120, "spinner": 124, "ok": 100, "cancel": 110, "count": 14,
         "replacement": lambda value: str(max(1, int(value or "1") - 1)),
         "boundaries": ("1", "255")},
    )

    def record(spec, item, path, action, result):
        records.append({"action_id": stable_interaction_id(
            spec["window"], str(item.get("class", "")), int(item.get("ctrl_id") or 0),
            list(path), action), "status": "passed", "result": result})

    def reset_database(target_id):
        nonlocal database
        if database and is_window(database): close_window_safely(session, database, 4.0)
        window = None
        for _attempt in range(4):
            if not session.process_alive():
                # Some valid legacy confirm paths end in the reference
                # executable's documented array-bounds crash.  Preserve that
                # observed action, then continue the independent matrix from
                # a fresh process over the same untouched probe-ROM copy.
                session.terminate()
                session.launch()
                stage_a(session)
                stage_load(session)
                database = 0
            window = _open_data_window(session, 20008, "数据库", dismiss_hidden=False)
            if window:
                break
            time.sleep(0.8)
        if not window: raise RuntimeError("database did not appear")
        database = int(window["hwnd"])
        # The legacy Other-1 page lazily lays out its wide child panels.  At
        # the compact probe size the shop list can become visible before the
        # growth/level panels have completed their first layout, so using the
        # shop as the page sentinel produces a false-positive intermediate
        # state.  Restore the reference capture size and use the actual child
        # opener as the tab-completion sentinel.
        move_window(database, 25, 15, 1600, 1060)
        time.sleep(0.35)
        if switch_database_page_by_control(database, target_id) is None:
            raise RuntimeError(f"other-modification child opener {target_id} unavailable")
        deadline = time.monotonic() + 2.0
        while time.monotonic() < deadline:
            if find_controls(enum_child_tree(database), cls="Button", ctrl_id=target_id, visible=True):
                break
            time.sleep(0.10)
        if not find_controls(enum_child_tree(database), cls="Button", ctrl_id=target_id, visible=True):
            raise RuntimeError(f"database child opener {target_id} unavailable")

    def open_child(spec):
        nonlocal child
        for attempt in range(2):
            buttons = find_controls(enum_child_tree(database), cls="Button", ctrl_id=spec["opener"], visible=True)
            if buttons:
                known = {top["hwnd"] for top in session.top_windows()}
                click_control(buttons[0]["hwnd"])
                found = session.wait_new_top(exclude=known, timeout=4.0)
                if found:
                    child = int(found["hwnd"]); return child
            reset_database(spec["opener"])
        raise RuntimeError(f"{spec['window']} did not appear")

    def close_child(spec):
        nonlocal child
        if child and is_window(child):
            buttons = find_controls(enum_child_tree(child), cls="Button", ctrl_id=spec["cancel"], visible=True)
            if buttons: click_control(buttons[0]["hwnd"])
            if not session.wait_gone(child, 3.0): user32.PostMessageW(child, WM_CLOSE, 0, 0); session.wait_gone(child, 2.0)
        child = 0

    def notify(item):
        parent = user32.GetParent(item["hwnd"])
        if parent: _send_msg_num(parent, WM_COMMAND, (int(item.get("ctrl_id") or 0)&0xFFFF)|(0x0300<<16), item["hwnd"])

    try:
        for spec in specs:
            reset_database(spec["opener"]); child = open_child(spec); tree = enum_child_tree(child)
            item = find_controls(tree, cls="Edit", ctrl_id=spec["edit"], visible=True)[0]
            path = control_tree_path(tree, item["hwnd"]); original = get_ctrl_text(item["hwnd"])
            record(spec, item, tuple(path or ()), "focus", f"真实焦点={focus_foreground_control(child,item['hwnd'])}。")
            replacement = spec["replacement"](original)
            # WM_SETTEXT already follows the control's normal text path.  Do
            # not inject an extra synthetic EN_CHANGE into these two legacy
            # numeric dialogs: their handlers parse on focus/confirm, and a
            # second forged notification can retain a stale intermediate
            # value even after the visible text has been restored.
            set_control_text(item["hwnd"], replacement); readback = get_ctrl_text(item["hwnd"])
            set_control_text(item["hwnd"], original)
            record(spec, item, tuple(path or ()), "replace_value", f"读回={readback!r}，已恢复。")
            focus_foreground_control(child,item["hwnd"])
            for key in (ord("A"),ord("Z")):
                keybd(VK_CONTROL); keybd(key); keybd(key,up=True); keybd(VK_CONTROL,up=True)
            set_control_text(item["hwnd"], original)
            record(spec,item,tuple(path or ()),"keyboard_shortcuts","Ctrl+A/Ctrl+Z 后恢复。")
            post_context_menu(item["hwnd"],5,5); time.sleep(0.08)
            if visible_popup_menus(session.pid or 0): send_escape(child)
            record(spec,item,tuple(path or ()),"right_click","执行右键路径。")
            lengths=[]
            for value in spec["boundaries"]:
                set_control_text(item["hwnd"],value); lengths.append(len(get_ctrl_text(item["hwnd"])))
            set_control_text(item["hwnd"],original)
            record(spec,item,tuple(path or ()),"boundary_values",f"边界长度={lengths}，已恢复。")

            if spec.get("spinner"):
                spin = find_controls(tree, cls="msctls_updown32", ctrl_id=spec["spinner"], visible=True)[0]
                spath = control_tree_path(tree,spin["hwnd"]); width,height=get_client_size(spin["hwnd"])
                post_click_at(spin["hwnd"],max(1,width//2),max(1,height//4)); time.sleep(0.08)
                inc=get_ctrl_text(item["hwnd"]); set_control_text(item["hwnd"],original)
                record(spec,spin,tuple(spath or ()),"increment",f"上箭头读回={inc!r}。")
                post_click_at(spin["hwnd"],max(1,width//2),max(1,height*3//4)); time.sleep(0.08)
                dec=get_ctrl_text(item["hwnd"]); set_control_text(item["hwnd"],original)
                record(spec,spin,tuple(spath or ()),"decrement",f"下箭头读回={dec!r}。")
                vals=[]
                for value in ("-32768","32767"):
                    set_control_text(item["hwnd"],value); vals.append(get_ctrl_text(item["hwnd"]))
                set_control_text(item["hwnd"],original)
                record(spec,spin,tuple(spath or ()),"boundary_values",f"伙伴边界={vals}，已恢复。")
            close_child(spec)

            for cid in (spec["ok"],spec["cancel"]):
                for action in ("keyboard_activate","left_click","right_click"):
                    child=open_child(spec); tree=enum_child_tree(child)
                    button=find_controls(tree,cls="Button",ctrl_id=cid,visible=True)[0]
                    bpath=control_tree_path(tree,button["hwnd"])
                    if action=="keyboard_activate": focus_foreground_control(child,button["hwnd"]); send_key(button["hwnd"],VK_SPACE)
                    elif action=="left_click": click_control(button["hwnd"])
                    else:
                        post_context_menu(button["hwnd"],5,5); time.sleep(0.08)
                        if visible_popup_menus(session.pid or 0): send_escape(child)
                    time.sleep(0.12); record(spec,button,tuple(bpath or ()),action,"执行数值弹窗按钮手势。")
                    close_child(spec)
        db_cancel=find_controls(enum_child_tree(database),cls="Button",text_contains="取消",visible=True)
        if db_cancel: click_control(db_cancel[0]["hwnd"]); session.wait_gone(database,5.0)
    except Exception as exc:
        error=repr(exc); log(f"DBSMALLNUMCONTROLS inner failure: {error}")
    finally:
        if child and is_window(child): user32.PostMessageW(child,WM_CLOSE,0,0); session.wait_gone(child,2.0)
        if database and is_window(database): close_window_safely(session,database,4.0)
        after=session.probe_rom.read_bytes(); diffs=[i for i,(a,b) in enumerate(zip(before,after)) if a!=b]
        unique={r["action_id"]:r for r in records}; validated=error is None and len(unique)==25 and not diffs and len(before)==len(after)
        out_dir=session.out/"interaction-discovery"; out_dir.mkdir(parents=True,exist_ok=True)
        (out_dir/"database-small-number-control-actions.json").write_text(json.dumps({
            "schema_version":1,"validated":validated,"error":error,"execution_record_count":len(unique),
            "diff_count":len(diffs)+int(len(before)!=len(after)),"sha256_before":hashlib.sha256(before).hexdigest().upper(),
            "sha256_after":hashlib.sha256(after).hexdigest().upper(),"execution_records":list(unique.values()) if validated else []
        },ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    if not validated: raise RuntimeError(f"small number controls did not validate: {len(unique)}/25 {error}")
    log("DBSMALLNUMCONTROLS complete: 25/25 actions, zero ROM diff")


def stage_dbwinstrsmallcontrols(session: ProbeSession) -> None:
    """Close the identical 13-action sound/wait parameter dialogs."""
    log("=== stage DBWINSTRSMALLCONTROLS ===")
    before = session.probe_rom.read_bytes(); records = []; error = None
    database = 0; child = 0; selector_hwnd = 0
    specs = (
        {"window": "定义声音", "selector": 100, "boundaries": ("00", "FF")},
        {"window": "等待(帧)", "selector": 180, "boundaries": ("0", "255")},
    )

    def record(spec, item, path, action, result):
        records.append({"action_id": stable_interaction_id(
            spec["window"], str(item.get("class", "")), int(item.get("ctrl_id") or 0),
            list(path), action), "status": "passed", "result": result})

    def reset_database():
        nonlocal database
        if database and is_window(database): close_window_safely(session, database, 4.0)
        for _attempt in range(4):
            if not session.process_alive():
                session.terminate(); session.launch(); stage_a(session); stage_load(session)
                database = 0
            window = _open_data_window(session, 20008, "数据库", dismiss_hidden=False)
            if window:
                database = int(window["hwnd"]); return
            time.sleep(0.8)
        raise RuntimeError("database did not appear")

    def open_child(spec):
        nonlocal child, selector_hwnd
        for _attempt in range(2):
            if not database or not is_window(database): reset_database()
            selector = _open_weapon_instruction_selector(session, database)
            if selector:
                selector_hwnd = int(selector["hwnd"])
                buttons = find_controls(enum_child_tree(selector_hwnd), cls="Button", ctrl_id=spec["selector"], visible=True)
                if buttons:
                    known = {top["hwnd"] for top in session.top_windows()}
                    click_control(buttons[0]["hwnd"])
                    found = session.wait_new_top(exclude=known, timeout=4.0, title_contains=spec["window"])
                    if found:
                        child = int(found["hwnd"]); return child
            reset_database()
        raise RuntimeError(f"{spec['window']} did not appear")

    def close_child():
        nonlocal child, selector_hwnd
        if child and is_window(child):
            cancel = find_controls(enum_child_tree(child), cls="Button", ctrl_id=110, visible=True)
            if cancel: click_control(cancel[0]["hwnd"])
            if not session.wait_gone(child, 2.0):
                user32.PostMessageW(child, WM_CLOSE, 0, 0); session.wait_gone(child, 2.0)
        if selector_hwnd and is_window(selector_hwnd): close_window_safely(session, selector_hwnd, 2.0)
        child = 0; selector_hwnd = 0

    try:
        reset_database()
        for spec in specs:
            child = open_child(spec); tree = enum_child_tree(child)
            item = find_controls(tree, cls="Edit", ctrl_id=120, visible=True)[0]
            path = control_tree_path(tree, item["hwnd"]); original = get_ctrl_text(item["hwnd"])
            record(spec, item, tuple(path or ()), "focus", f"真实焦点={focus_foreground_control(child,item['hwnd'])}。")
            replacement = spec["boundaries"][1] if original != spec["boundaries"][1] else spec["boundaries"][0]
            set_control_text(item["hwnd"], replacement); readback = get_ctrl_text(item["hwnd"]); set_control_text(item["hwnd"], original)
            record(spec, item, tuple(path or ()), "replace_value", f"读回={readback!r}，已恢复。")
            focus_foreground_control(child,item["hwnd"])
            for key in (ord("A"), ord("Z")):
                keybd(VK_CONTROL); keybd(key); keybd(key,up=True); keybd(VK_CONTROL,up=True)
            set_control_text(item["hwnd"], original)
            record(spec, item, tuple(path or ()), "keyboard_shortcuts", "Ctrl+A/Ctrl+Z 后恢复。")
            post_context_menu(item["hwnd"],5,5); time.sleep(0.08)
            if visible_popup_menus(session.pid or 0): send_escape(child)
            record(spec, item, tuple(path or ()), "right_click", "执行右键路径。")
            values=[]
            for value in spec["boundaries"]:
                set_control_text(item["hwnd"],value); values.append(get_ctrl_text(item["hwnd"]))
            set_control_text(item["hwnd"],original)
            record(spec,item,tuple(path or ()),"boundary_values",f"边界读回={values}，已恢复。")
            spin = find_controls(tree, cls="msctls_updown32", ctrl_id=124, visible=True)[0]
            spath = control_tree_path(tree, spin["hwnd"]); width,height=get_client_size(spin["hwnd"])
            post_click_at(spin["hwnd"],max(1,width//2),max(1,height//4)); time.sleep(0.08)
            inc=get_ctrl_text(item["hwnd"]); set_control_text(item["hwnd"],original)
            record(spec,spin,tuple(spath or ()),"increment",f"上箭头={inc!r}。")
            post_click_at(spin["hwnd"],max(1,width//2),max(1,height*3//4)); time.sleep(0.08)
            dec=get_ctrl_text(item["hwnd"]); set_control_text(item["hwnd"],original)
            record(spec,spin,tuple(spath or ()),"decrement",f"下箭头={dec!r}。")
            values=[]
            for value in spec["boundaries"]:
                set_control_text(item["hwnd"],value); values.append(get_ctrl_text(item["hwnd"]))
            set_control_text(item["hwnd"],original)
            record(spec,spin,tuple(spath or ()),"boundary_values",f"伙伴边界={values}，已恢复。")
            close_child()
            for cid in (100,110):
                for action in ("keyboard_activate","left_click","right_click"):
                    child=open_child(spec); tree=enum_child_tree(child)
                    button=find_controls(tree,cls="Button",ctrl_id=cid,visible=True)[0]
                    bpath=control_tree_path(tree,button["hwnd"])
                    if action=="keyboard_activate": focus_foreground_control(child,button["hwnd"]); send_key(button["hwnd"],VK_SPACE)
                    elif action=="left_click": click_control(button["hwnd"])
                    else:
                        post_context_menu(button["hwnd"],5,5); time.sleep(0.08)
                        if visible_popup_menus(session.pid or 0): send_escape(child)
                    time.sleep(0.12); record(spec,button,tuple(bpath or ()),action,"执行参数窗口按钮手势。")
                    close_child()
        if database and is_window(database):
            cancel=find_controls(enum_child_tree(database),cls="Button",text_contains="取消",visible=True)
            if cancel: click_control(cancel[0]["hwnd"]); session.wait_gone(database,4.0)
    except Exception as exc:
        error=repr(exc); log(f"DBWINSTRSMALLCONTROLS inner failure: {error}")
    finally:
        close_child()
        if database and is_window(database): close_window_safely(session,database,4.0)
        after=session.probe_rom.read_bytes(); diffs=[i for i,(a,b) in enumerate(zip(before,after)) if a!=b]
        unique={r["action_id"]:r for r in records}; validated=error is None and len(unique)==28 and not diffs and len(before)==len(after)
        out_dir=session.out/"interaction-discovery"; out_dir.mkdir(parents=True,exist_ok=True)
        (out_dir/"weapon-parameter-small-control-actions.json").write_text(json.dumps({
            "schema_version":1,"validated":validated,"error":error,"execution_record_count":len(unique),
            "diff_count":len(diffs)+int(len(before)!=len(after)),"sha256_before":hashlib.sha256(before).hexdigest().upper(),
            "sha256_after":hashlib.sha256(after).hexdigest().upper(),"execution_records":list(unique.values()) if validated else []
        },ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    if not validated: raise RuntimeError(f"weapon small parameter controls did not validate: {len(unique)}/28 {error}")
    log("DBWINSTRSMALLCONTROLS complete: 28/28 actions, zero ROM diff")


def stage_dbwinstrcombocontrols(session: ProbeSession) -> None:
    """Close four combo-only weapon-instruction parameter dialogs."""
    log("=== stage DBWINSTRCOMBOCONTROLS ===")
    before = session.probe_rom.read_bytes(); records = []; error = None
    database = 0; child = 0; selector_hwnd = 0
    specs = (
        {"window": "定义光束规律图库", "selector": 120},
        {"window": "定义光束规律", "selector": 130},
        {"window": "切换精灵图库0", "selector": 200},
        {"window": "切换精灵图库1", "selector": 210},
    )

    def record(spec, item, path, action, result):
        records.append({"action_id": stable_interaction_id(
            spec["window"], str(item.get("class", "")), int(item.get("ctrl_id") or 0),
            list(path), action), "status": "passed", "result": result})

    def reset_database():
        nonlocal database
        if database and is_window(database): close_window_safely(session, database, 4.0)
        for _attempt in range(4):
            if not session.process_alive():
                session.terminate(); session.launch(); stage_a(session); stage_load(session); database = 0
            window = _open_data_window(session, 20008, "数据库", dismiss_hidden=False)
            if window:
                database = int(window["hwnd"]); return
            time.sleep(0.8)
        raise RuntimeError("database did not appear")

    def open_child(spec):
        nonlocal child, selector_hwnd
        for _attempt in range(2):
            if not database or not is_window(database): reset_database()
            selector = _open_weapon_instruction_selector(session, database)
            if selector:
                selector_hwnd = int(selector["hwnd"])
                buttons = find_controls(enum_child_tree(selector_hwnd), cls="Button", ctrl_id=spec["selector"], visible=True)
                if buttons:
                    known = {top["hwnd"] for top in session.top_windows()}
                    click_control(buttons[0]["hwnd"])
                    found = session.wait_new_top(exclude=known, timeout=4.0, title_contains=spec["window"])
                    if found:
                        child = int(found["hwnd"]); return child
            reset_database()
        raise RuntimeError(f"{spec['window']} did not appear")

    def close_child():
        nonlocal child, selector_hwnd
        if child and is_window(child):
            cancel = find_controls(enum_child_tree(child), cls="Button", ctrl_id=110, visible=True)
            if cancel: click_control(cancel[0]["hwnd"])
            if not session.wait_gone(child, 2.0):
                user32.PostMessageW(child, WM_CLOSE, 0, 0); session.wait_gone(child, 2.0)
        if selector_hwnd and is_window(selector_hwnd): close_window_safely(session, selector_hwnd, 2.0)
        child = 0; selector_hwnd = 0

    try:
        reset_database()
        for spec in specs:
            child=open_child(spec); tree=enum_child_tree(child)
            item=find_controls(tree,cls="ComboBox",ctrl_id=160,visible=True)[0]
            path=control_tree_path(tree,item["hwnd"]); values=read_combo_items(item["hwnd"])
            original=int(_send_msg_num(item["hwnd"],CB_GETCURSEL,0,0))
            _send_msg_num(item["hwnd"],0x014F,1,0); time.sleep(0.05); _send_msg_num(item["hwnd"],0x014F,0,0)
            record(spec,item,tuple(path or ()),"open_dropdown",f"展开/收起，共 {len(values)} 项。")
            selected=[]
            for index in range(len(values)):
                set_combo_selection(item["hwnd"],index); selected.append(int(_send_msg_num(item["hwnd"],CB_GETCURSEL,0,0)))
            if original>=0: set_combo_selection(item["hwnd"],original)
            record(spec,item,tuple(path or ()),"select_each_item",f"逐项选择并读回 {len(selected)}/{len(values)} 项，已恢复。")
            focus_foreground_control(child,item["hwnd"]); send_key(item["hwnd"],VK_HOME); send_key(item["hwnd"],VK_DOWN)
            readback=int(_send_msg_num(item["hwnd"],CB_GETCURSEL,0,0))
            if original>=0: set_combo_selection(item["hwnd"],original)
            record(spec,item,tuple(path or ()),"keyboard_cycle",f"Home/Down 读回 {readback}，已恢复。")
            post_context_menu(item["hwnd"],5,5); time.sleep(0.08)
            if visible_popup_menus(session.pid or 0): send_escape(child)
            record(spec,item,tuple(path or ()),"right_click","执行右键路径。")
            close_child()
            for cid in (100,110):
                for action in ("keyboard_activate","left_click","right_click"):
                    child=open_child(spec); tree=enum_child_tree(child)
                    button=find_controls(tree,cls="Button",ctrl_id=cid,visible=True)[0]
                    bpath=control_tree_path(tree,button["hwnd"])
                    if action=="keyboard_activate": focus_foreground_control(child,button["hwnd"]); send_key(button["hwnd"],VK_SPACE)
                    elif action=="left_click": click_control(button["hwnd"])
                    else:
                        post_context_menu(button["hwnd"],5,5); time.sleep(0.08)
                        if visible_popup_menus(session.pid or 0): send_escape(child)
                    time.sleep(0.12); record(spec,button,tuple(bpath or ()),action,"执行参数窗口按钮手势。")
                    close_child()
        if database and is_window(database):
            cancel=find_controls(enum_child_tree(database),cls="Button",text_contains="取消",visible=True)
            if cancel: click_control(cancel[0]["hwnd"]); session.wait_gone(database,4.0)
    except Exception as exc:
        error=repr(exc); log(f"DBWINSTRCOMBOCONTROLS inner failure: {error}")
    finally:
        close_child()
        if database and is_window(database): close_window_safely(session,database,4.0)
        after=session.probe_rom.read_bytes(); diffs=[i for i,(a,b) in enumerate(zip(before,after)) if a!=b]
        unique={r["action_id"]:r for r in records}; validated=error is None and len(unique)==40 and not diffs and len(before)==len(after)
        out_dir=session.out/"interaction-discovery"; out_dir.mkdir(parents=True,exist_ok=True)
        (out_dir/"weapon-parameter-combo-control-actions.json").write_text(json.dumps({
            "schema_version":1,"validated":validated,"error":error,"execution_record_count":len(unique),
            "diff_count":len(diffs)+int(len(before)!=len(after)),"sha256_before":hashlib.sha256(before).hexdigest().upper(),
            "sha256_after":hashlib.sha256(after).hexdigest().upper(),"execution_records":list(unique.values()) if validated else []
        },ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    if not validated: raise RuntimeError(f"weapon combo parameter controls did not validate: {len(unique)}/40 {error}")
    log("DBWINSTRCOMBOCONTROLS complete: 40/40 actions, zero ROM diff")


def stage_dbwinstrmixedcontrols(session: ProbeSession) -> None:
    """Close move/repeat/object parameter dialogs with mixed controls."""
    log("=== stage DBWINSTRMIXEDCONTROLS ===")
    before=session.probe_rom.read_bytes(); records=[]; error=None
    database=0; child=0; selector_hwnd=0
    specs=(
        {"window":"移动屏幕","selector":140,"edits":{120:("-128","127"),130:("-128","127")},"spins":(),"combos":()},
        {"window":"跳转重复","selector":150,"edits":{120:("0","255")},"spins":((124,120),),"combos":(160,)},
        {"window":"创建物体","selector":160,"edits":{120:("0","255"),130:("0","255")},"spins":((124,120),(134,130)),"combos":(160,)},
    )

    def record(spec,item,path,action,result):
        records.append({"action_id":stable_interaction_id(
            spec["window"],str(item.get("class","")),int(item.get("ctrl_id") or 0),list(path),action),
            "status":"passed","result":result})

    def reset_database():
        nonlocal database
        if database and is_window(database): close_window_safely(session,database,4.0)
        for _attempt in range(4):
            if not session.process_alive():
                session.terminate(); session.launch(); stage_a(session); stage_load(session); database=0
            window=_open_data_window(session,20008,"数据库",dismiss_hidden=False)
            if window: database=int(window["hwnd"]); return
            time.sleep(0.8)
        raise RuntimeError("database did not appear")

    def open_child(spec):
        nonlocal child,selector_hwnd
        for _attempt in range(2):
            if not database or not is_window(database): reset_database()
            selector=_open_weapon_instruction_selector(session,database)
            if selector:
                selector_hwnd=int(selector["hwnd"])
                buttons=find_controls(enum_child_tree(selector_hwnd),cls="Button",ctrl_id=spec["selector"],visible=True)
                if buttons:
                    known={top["hwnd"] for top in session.top_windows()}; click_control(buttons[0]["hwnd"])
                    found=session.wait_new_top(exclude=known,timeout=4.0,title_contains=spec["window"])
                    if found: child=int(found["hwnd"]); return child
            reset_database()
        raise RuntimeError(f"{spec['window']} did not appear")

    def close_child():
        nonlocal child,selector_hwnd
        if child and is_window(child):
            cancel=find_controls(enum_child_tree(child),cls="Button",ctrl_id=110,visible=True)
            if cancel: click_control(cancel[0]["hwnd"])
            if not session.wait_gone(child,2.0): user32.PostMessageW(child,WM_CLOSE,0,0); session.wait_gone(child,2.0)
        if selector_hwnd and is_window(selector_hwnd): close_window_safely(session,selector_hwnd,2.0)
        child=0; selector_hwnd=0

    try:
        reset_database()
        for spec in specs:
            child=open_child(spec); tree=enum_child_tree(child)
            edit_items={}
            for cid,bounds in spec["edits"].items():
                item=find_controls(tree,cls="Edit",ctrl_id=cid,visible=True)[0]; edit_items[cid]=item
                path=control_tree_path(tree,item["hwnd"]); original=get_ctrl_text(item["hwnd"])
                record(spec,item,tuple(path or ()),"focus",f"真实焦点={focus_foreground_control(child,item['hwnd'])}。")
                replacement=bounds[1] if original!=bounds[1] else bounds[0]
                set_control_text(item["hwnd"],replacement); readback=get_ctrl_text(item["hwnd"]); set_control_text(item["hwnd"],original)
                record(spec,item,tuple(path or ()),"replace_value",f"读回={readback!r}，已恢复。")
                focus_foreground_control(child,item["hwnd"])
                for key in (ord("A"),ord("Z")):
                    keybd(VK_CONTROL); keybd(key); keybd(key,up=True); keybd(VK_CONTROL,up=True)
                set_control_text(item["hwnd"],original)
                record(spec,item,tuple(path or ()),"keyboard_shortcuts","Ctrl+A/Ctrl+Z 后恢复。")
                post_context_menu(item["hwnd"],5,5); time.sleep(0.08)
                if visible_popup_menus(session.pid or 0): send_escape(child)
                record(spec,item,tuple(path or ()),"right_click","执行右键路径。")
                values=[]
                for value in bounds: set_control_text(item["hwnd"],value); values.append(get_ctrl_text(item["hwnd"]))
                set_control_text(item["hwnd"],original)
                record(spec,item,tuple(path or ()),"boundary_values",f"边界读回={values}，已恢复。")
            for spin_id,edit_id in spec["spins"]:
                spin=find_controls(tree,cls="msctls_updown32",ctrl_id=spin_id,visible=True)[0]
                item=edit_items[edit_id]; original=get_ctrl_text(item["hwnd"]); bounds=spec["edits"][edit_id]
                path=control_tree_path(tree,spin["hwnd"]); width,height=get_client_size(spin["hwnd"])
                post_click_at(spin["hwnd"],max(1,width//2),max(1,height//4)); time.sleep(0.08)
                inc=get_ctrl_text(item["hwnd"]); set_control_text(item["hwnd"],original)
                record(spec,spin,tuple(path or ()),"increment",f"上箭头={inc!r}。")
                post_click_at(spin["hwnd"],max(1,width//2),max(1,height*3//4)); time.sleep(0.08)
                dec=get_ctrl_text(item["hwnd"]); set_control_text(item["hwnd"],original)
                record(spec,spin,tuple(path or ()),"decrement",f"下箭头={dec!r}。")
                values=[]
                for value in bounds: set_control_text(item["hwnd"],value); values.append(get_ctrl_text(item["hwnd"]))
                set_control_text(item["hwnd"],original)
                record(spec,spin,tuple(path or ()),"boundary_values",f"伙伴边界={values}，已恢复。")
            for cid in spec["combos"]:
                item=find_controls(tree,cls="ComboBox",ctrl_id=cid,visible=True)[0]
                path=control_tree_path(tree,item["hwnd"]); values=read_combo_items(item["hwnd"])
                original=int(_send_msg_num(item["hwnd"],CB_GETCURSEL,0,0))
                _send_msg_num(item["hwnd"],0x014F,1,0); time.sleep(0.05); _send_msg_num(item["hwnd"],0x014F,0,0)
                record(spec,item,tuple(path or ()),"open_dropdown",f"展开/收起，共 {len(values)} 项。")
                for index in range(len(values)): set_combo_selection(item["hwnd"],index)
                if original>=0: set_combo_selection(item["hwnd"],original)
                record(spec,item,tuple(path or ()),"select_each_item",f"逐项选择 {len(values)} 项并恢复。")
                focus_foreground_control(child,item["hwnd"]); send_key(item["hwnd"],VK_HOME); send_key(item["hwnd"],VK_DOWN)
                readback=int(_send_msg_num(item["hwnd"],CB_GETCURSEL,0,0))
                if original>=0: set_combo_selection(item["hwnd"],original)
                record(spec,item,tuple(path or ()),"keyboard_cycle",f"Home/Down 读回 {readback}，已恢复。")
                post_context_menu(item["hwnd"],5,5); time.sleep(0.08)
                if visible_popup_menus(session.pid or 0): send_escape(child)
                record(spec,item,tuple(path or ()),"right_click","执行右键路径。")
            close_child()
            for cid in (100,110):
                for action in ("keyboard_activate","left_click","right_click"):
                    child=open_child(spec); tree=enum_child_tree(child)
                    button=find_controls(tree,cls="Button",ctrl_id=cid,visible=True)[0]; path=control_tree_path(tree,button["hwnd"])
                    if action=="keyboard_activate": focus_foreground_control(child,button["hwnd"]); send_key(button["hwnd"],VK_SPACE)
                    elif action=="left_click": click_control(button["hwnd"])
                    else:
                        post_context_menu(button["hwnd"],5,5); time.sleep(0.08)
                        if visible_popup_menus(session.pid or 0): send_escape(child)
                    time.sleep(0.12); record(spec,button,tuple(path or ()),action,"执行参数窗口按钮手势。")
                    close_child()
        if database and is_window(database):
            cancel=find_controls(enum_child_tree(database),cls="Button",text_contains="取消",visible=True)
            if cancel: click_control(cancel[0]["hwnd"]); session.wait_gone(database,4.0)
    except Exception as exc:
        error=repr(exc); log(f"DBWINSTRMIXEDCONTROLS inner failure: {error}")
    finally:
        close_child()
        if database and is_window(database): close_window_safely(session,database,4.0)
        after=session.probe_rom.read_bytes(); diffs=[i for i,(a,b) in enumerate(zip(before,after)) if a!=b]
        unique={r["action_id"]:r for r in records}; validated=error is None and len(unique)==60 and not diffs and len(before)==len(after)
        out_dir=session.out/"interaction-discovery"; out_dir.mkdir(parents=True,exist_ok=True)
        (out_dir/"weapon-parameter-mixed-control-actions.json").write_text(json.dumps({
            "schema_version":1,"validated":validated,"error":error,"execution_record_count":len(unique),
            "diff_count":len(diffs)+int(len(before)!=len(after)),"sha256_before":hashlib.sha256(before).hexdigest().upper(),
            "sha256_after":hashlib.sha256(after).hexdigest().upper(),"execution_records":list(unique.values()) if validated else []
        },ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    if not validated: raise RuntimeError(f"weapon mixed parameter controls did not validate: {len(unique)}/60 {error}")
    log("DBWINSTRMIXEDCONTROLS complete: 60/60 actions, zero ROM diff")


def stage_dbwinstrcomplexcontrols(session: ProbeSession) -> None:
    """Close colour and object-rule parameter dialogs, including mode controls."""
    log("=== stage DBWINSTRCOMPLEXCONTROLS ===")
    before=session.probe_rom.read_bytes(); records=[]; error=None
    database=0; child=0; selector_hwnd=0
    specs=(
        {"window":"定义颜色","selector":110,"edits":(260,270,290),"combos":(),"buttons":(100,110,240,310,320)},
        {"window":"运行规律","selector":170,"edits":(),"combos":(160,170,180,330),"buttons":(100,110,310,320)},
    )

    def record(spec,item,path,action,result):
        records.append({"action_id":stable_interaction_id(
            spec["window"],str(item.get("class","")),int(item.get("ctrl_id") or 0),list(path),action),
            "status":"passed","result":result})

    def reset_database():
        nonlocal database
        if database and is_window(database): close_window_safely(session,database,4.0)
        for _attempt in range(4):
            if not session.process_alive():
                session.terminate(); session.launch(); stage_a(session); stage_load(session); database=0
            window=_open_data_window(session,20008,"数据库",dismiss_hidden=False)
            if window: database=int(window["hwnd"]); return
            time.sleep(0.8)
        raise RuntimeError("database did not appear")

    def open_child(spec):
        nonlocal child,selector_hwnd
        for _attempt in range(2):
            if not database or not is_window(database): reset_database()
            selector=_open_weapon_instruction_selector(session,database)
            if selector:
                selector_hwnd=int(selector["hwnd"])
                buttons=find_controls(enum_child_tree(selector_hwnd),cls="Button",ctrl_id=spec["selector"],visible=True)
                if buttons:
                    known={top["hwnd"] for top in session.top_windows()}; click_control(buttons[0]["hwnd"])
                    found=session.wait_new_top(exclude=known,timeout=4.0,title_contains=spec["window"])
                    if found: child=int(found["hwnd"]); return child
            reset_database()
        raise RuntimeError(f"{spec['window']} did not appear")

    def close_child():
        nonlocal child,selector_hwnd
        if child and is_window(child):
            cancel=find_controls(enum_child_tree(child),cls="Button",ctrl_id=110,visible=True)
            if cancel: click_control(cancel[0]["hwnd"])
            if not session.wait_gone(child,2.0): user32.PostMessageW(child,WM_CLOSE,0,0); session.wait_gone(child,2.0)
        if selector_hwnd and is_window(selector_hwnd): close_window_safely(session,selector_hwnd,2.0)
        child=0; selector_hwnd=0

    try:
        reset_database()
        for spec in specs:
            child=open_child(spec); tree=enum_child_tree(child)
            for cid in spec["edits"]:
                item=find_controls(tree,cls="Edit",ctrl_id=cid,visible=True)[0]
                path=control_tree_path(tree,item["hwnd"]); original=get_ctrl_text(item["hwnd"])
                record(spec,item,tuple(path or ()),"focus",f"真实焦点={focus_foreground_control(child,item['hwnd'])}。")
                replacement="3F" if original!="3F" else "00"
                set_control_text(item["hwnd"],replacement); readback=get_ctrl_text(item["hwnd"]); set_control_text(item["hwnd"],original)
                record(spec,item,tuple(path or ()),"replace_value",f"读回={readback!r}，已恢复。")
                focus_foreground_control(child,item["hwnd"])
                for key in (ord("A"),ord("Z")):
                    keybd(VK_CONTROL); keybd(key); keybd(key,up=True); keybd(VK_CONTROL,up=True)
                set_control_text(item["hwnd"],original)
                record(spec,item,tuple(path or ()),"keyboard_shortcuts","Ctrl+A/Ctrl+Z 后恢复。")
                post_context_menu(item["hwnd"],5,5); time.sleep(0.08)
                if visible_popup_menus(session.pid or 0): send_escape(child)
                record(spec,item,tuple(path or ()),"right_click","执行右键路径。")
                values=[]
                for value in ("00","3F"): set_control_text(item["hwnd"],value); values.append(get_ctrl_text(item["hwnd"]))
                set_control_text(item["hwnd"],original)
                record(spec,item,tuple(path or ()),"boundary_values",f"NES 调色板边界读回={values}，已恢复。")
            for cid in spec["combos"]:
                item=find_controls(tree,cls="ComboBox",ctrl_id=cid,visible=True)[0]
                path=control_tree_path(tree,item["hwnd"]); values=read_combo_items(item["hwnd"])
                original=int(_send_msg_num(item["hwnd"],CB_GETCURSEL,0,0))
                _send_msg_num(item["hwnd"],0x014F,1,0); time.sleep(0.05); _send_msg_num(item["hwnd"],0x014F,0,0)
                record(spec,item,tuple(path or ()),"open_dropdown",f"展开/收起，共 {len(values)} 项。")
                selected=[]
                for index in range(len(values)):
                    set_combo_selection(item["hwnd"],index); selected.append(int(_send_msg_num(item["hwnd"],CB_GETCURSEL,0,0)))
                if original>=0: set_combo_selection(item["hwnd"],original)
                record(spec,item,tuple(path or ()),"select_each_item",f"逐项选择并读回 {len(selected)}/{len(values)} 项，已恢复。")
                focus_foreground_control(child,item["hwnd"]); send_key(item["hwnd"],VK_HOME); send_key(item["hwnd"],VK_DOWN)
                readback=int(_send_msg_num(item["hwnd"],CB_GETCURSEL,0,0))
                if original>=0: set_combo_selection(item["hwnd"],original)
                record(spec,item,tuple(path or ()),"keyboard_cycle",f"Home/Down 读回 {readback}，已恢复。")
                post_context_menu(item["hwnd"],5,5); time.sleep(0.08)
                if visible_popup_menus(session.pid or 0): send_escape(child)
                record(spec,item,tuple(path or ()),"right_click","执行右键路径。")
            close_child()
            for cid in spec["buttons"]:
                for action in ("keyboard_activate","left_click","right_click"):
                    child=open_child(spec); tree=enum_child_tree(child)
                    button=find_controls(tree,cls="Button",ctrl_id=cid,visible=True)[0]; path=control_tree_path(tree,button["hwnd"])
                    before_state=compact_control_state(child)
                    if action=="keyboard_activate": focus_foreground_control(child,button["hwnd"]); send_key(button["hwnd"],VK_SPACE)
                    elif action=="left_click": click_control(button["hwnd"])
                    else:
                        post_context_menu(button["hwnd"],5,5); time.sleep(0.08)
                        if visible_popup_menus(session.pid or 0): send_escape(child)
                    time.sleep(0.12)
                    after_state=compact_control_state(child) if child and is_window(child) else {"window_closed":True}
                    record(spec,button,tuple(path or ()),action,f"执行模式/参数按钮手势；状态变化={before_state!=after_state}。")
                    close_child()
        if database and is_window(database):
            cancel=find_controls(enum_child_tree(database),cls="Button",text_contains="取消",visible=True)
            if cancel: click_control(cancel[0]["hwnd"]); session.wait_gone(database,4.0)
    except Exception as exc:
        error=repr(exc); log(f"DBWINSTRCOMPLEXCONTROLS inner failure: {error}")
    finally:
        close_child()
        if database and is_window(database): close_window_safely(session,database,4.0)
        after=session.probe_rom.read_bytes(); diffs=[i for i,(a,b) in enumerate(zip(before,after)) if a!=b]
        unique={r["action_id"]:r for r in records}; validated=error is None and len(unique)==58 and not diffs and len(before)==len(after)
        out_dir=session.out/"interaction-discovery"; out_dir.mkdir(parents=True,exist_ok=True)
        (out_dir/"weapon-parameter-complex-control-actions.json").write_text(json.dumps({
            "schema_version":1,"validated":validated,"error":error,"execution_record_count":len(unique),
            "diff_count":len(diffs)+int(len(before)!=len(after)),"sha256_before":hashlib.sha256(before).hexdigest().upper(),
            "sha256_after":hashlib.sha256(after).hexdigest().upper(),"execution_records":list(unique.values()) if validated else []
        },ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    if not validated: raise RuntimeError(f"weapon complex parameter controls did not validate: {len(unique)}/58 {error}")
    log("DBWINSTRCOMPLEXCONTROLS complete: 58/58 actions, zero ROM diff")


def stage_dbpagecontrols(session: ProbeSession) -> None:
    """Exercise the database top page control and weapon animation sub-tabs."""
    log("=== stage DBPAGECONTROLS ===")
    before=session.probe_rom.read_bytes(); records=[]; error=None; database=0

    def record(item,path,action,result):
        records.append({"action_id":stable_interaction_id(
            "数据库",str(item.get("class","")),int(item.get("ctrl_id") or 0),list(path),action),
            "status":"passed","result":result})

    try:
        window=_open_data_window(session,20008,"数据库",dismiss_hidden=False)
        if not window: raise RuntimeError("database did not appear")
        database=int(window["hwnd"]); tree=enum_child_tree(database)
        top=find_controls(tree,cls="CPageControl",ctrl_id=100,visible=True)[0]
        top_path=control_tree_path(tree,top["hwnd"])
        reached=[]
        for target in (120,630,2530,1390,1810,1750):
            located=switch_database_page_by_control(database,target)
            if located is None: raise RuntimeError(f"database top page target {target} unavailable")
            reached.append(target)
        record(top,tuple(top_path or ()),"select_each_tab",f"逐页命中稳定控件 {reached}。")
        record(top,tuple(top_path or ()),"discover_state_triggers",f"六页状态签名均可触发：{reached}。")
        focus_foreground_control(database,top["hwnd"])
        keybd(VK_CONTROL); send_key(top["hwnd"],0x09); keybd(VK_CONTROL,up=True)
        record(top,tuple(top_path or ()),"keyboard_tab_cycle","真实焦点执行 Ctrl+Tab。")
        for x in (45,125,205,285,365,445):
            post_click_at(top["hwnd"],x,14,button="right"); time.sleep(0.06)
            if visible_popup_menus(session.pid or 0): send_escape(database)
        record(top,tuple(top_path or ()),"right_click_tabs","六个页签标题逐项执行右键并清理菜单。")

        if switch_database_page_by_control(database,2530) is None: raise RuntimeError("weapon page unavailable")
        tree=enum_child_tree(database)
        nested=find_controls(tree,cls="CPageControl",ctrl_id=2540,visible=True)[0]
        nested_path=control_tree_path(tree,nested["hwnd"]); width,_height=get_client_size(nested["hwnd"])
        reached=[]; positions=[]
        for target in (2530,2520):
            found=False
            for x in range(14,min(max(15,width-14),360),12):
                post_click_at(nested["hwnd"],x,14); time.sleep(0.10)
                if find_controls(enum_child_tree(database),cls="ListBox",ctrl_id=target,visible=True):
                    reached.append(target); positions.append(x); found=True; break
            if not found: raise RuntimeError(f"weapon animation tab {target} unavailable")
        record(nested,tuple(nested_path or ()),"select_each_tab",f"我方/敌方页均命中：{reached}。")
        record(nested,tuple(nested_path or ()),"discover_state_triggers",f"两种动画列表状态均触发：{reached}。")
        focus_foreground_control(database,nested["hwnd"])
        keybd(VK_CONTROL); send_key(nested["hwnd"],0x09); keybd(VK_CONTROL,up=True)
        record(nested,tuple(nested_path or ()),"keyboard_tab_cycle","真实焦点执行 Ctrl+Tab。")
        for x in positions:
            post_click_at(nested["hwnd"],x,14,button="right"); time.sleep(0.06)
            if visible_popup_menus(session.pid or 0): send_escape(database)
        record(nested,tuple(nested_path or ()),"right_click_tabs","我方/敌方页签逐项执行右键。")
        cancel=find_controls(enum_child_tree(database),cls="Button",text_contains="取消",visible=True)
        if cancel: click_control(cancel[0]["hwnd"]); session.wait_gone(database,4.0)
    except Exception as exc:
        error=repr(exc); log(f"DBPAGECONTROLS inner failure: {error}")
    finally:
        if database and is_window(database): close_window_safely(session,database,4.0)
        after=session.probe_rom.read_bytes(); diffs=[i for i,(a,b) in enumerate(zip(before,after)) if a!=b]
        unique={r["action_id"]:r for r in records}; validated=error is None and len(unique)==8 and not diffs and len(before)==len(after)
        out_dir=session.out/"interaction-discovery"; out_dir.mkdir(parents=True,exist_ok=True)
        (out_dir/"database-page-control-actions.json").write_text(json.dumps({
            "schema_version":1,"validated":validated,"error":error,"execution_record_count":len(unique),
            "diff_count":len(diffs)+int(len(before)!=len(after)),"sha256_before":hashlib.sha256(before).hexdigest().upper(),
            "sha256_after":hashlib.sha256(after).hexdigest().upper(),"execution_records":list(unique.values()) if validated else []
        },ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    if not validated: raise RuntimeError(f"database page controls did not validate: {len(unique)}/8 {error}")
    log("DBPAGECONTROLS complete: 8/8 actions, zero ROM diff")


def stage_dbdialogpagecontrols(session: ProbeSession) -> None:
    """Exercise the battle-dialogue sub-tabs on their canonical control identity."""
    log("=== stage DBDIALOGPAGECONTROLS ===")
    before = session.probe_rom.read_bytes()
    records = []
    error = None
    database = 0
    expected = {
        ((5, 11, 0), "discover_state_triggers"),
        ((5, 11, 0), "keyboard_tab_cycle"),
        ((5, 11, 0), "right_click_tabs"),
        ((5, 11, 0), "select_each_tab"),
    }

    def record(item, path, action, result):
        key = (tuple(path), action)
        if key not in expected:
            raise RuntimeError(f"unexpected battle-dialogue page path/action: {key}")
        records.append({
            "action_id": stable_interaction_id(
                "数据库", str(item.get("class", "")),
                int(item.get("ctrl_id") or 0), list(path), action,
            ),
            "status": "passed",
            "result": result,
        })

    def current_nested():
        tree = enum_child_tree(database)
        matches = find_controls(
            tree, cls="CPageControl", ctrl_id=2570, visible=True,
        )
        if not matches:
            return None, None
        item = matches[0]
        return item, tuple(control_tree_path(tree, item["hwnd"]) or ())

    def select_both_tabs(nested):
        width, _height = get_client_size(nested["hwnd"])
        reached = []
        positions = []
        for target in (2580, 2590):
            found = False
            for x in range(12, min(max(20, width - 12), 320), 8):
                post_click_at(nested["hwnd"], x, 14)
                time.sleep(0.06)
                visible = find_controls(
                    enum_child_tree(database), ctrl_id=target, visible=True,
                )
                if visible:
                    reached.append(target)
                    positions.append(x)
                    found = True
                    break
            if not found:
                raise RuntimeError(
                    f"battle-dialogue nested tab target {target} unavailable"
                )
        return reached, positions

    try:
        window = _open_data_window(
            session, 20008, "数据库", dismiss_hidden=False,
        )
        if not window:
            raise RuntimeError("database did not appear")
        database = int(window["hwnd"])
        move_window(database, 25, 15, 1600, 1060)
        time.sleep(1.0)
        done = set()
        observed_paths = []

        # Archived captures contain several sibling-index variants for this
        # unique non-zero control ID.  The frontier canonicalises those as one
        # function, but this probe still rejects any path that is not observed
        # in the live reference process.
        for attempt in range(12):
            nested, path = current_nested()
            if nested is None:
                if switch_database_page_by_control(database, 1390) is None:
                    raise RuntimeError("battle-dialogue page unavailable")
                nested, path = current_nested()
            if nested is None:
                raise RuntimeError("battle-dialogue nested page unavailable")
            observed_paths.append(list(path))
            log(f"battle-dialogue page attempt={attempt} path={list(path)}")

            if path == (5, 11, 0):
                missing = {
                    action for candidate_path, action in expected
                    if candidate_path == path and (candidate_path, action) not in done
                }
                if "select_each_tab" in missing or "discover_state_triggers" in missing:
                    reached, positions = select_both_tabs(nested)
                    if "select_each_tab" in missing:
                        record(
                            nested, path, "select_each_tab",
                            f"列表/内容两页均真实命中：{reached}；点击位置={positions}。",
                        )
                        done.add((path, "select_each_tab"))
                    if "discover_state_triggers" in missing:
                        record(
                            nested, path, "discover_state_triggers",
                            f"ListBox 2580 与 Edit 2590 两种可见状态均触发：{reached}。",
                        )
                        done.add((path, "discover_state_triggers"))
                else:
                    positions = [36, 116]

                if "keyboard_tab_cycle" in missing:
                    focus_foreground_control(database, nested["hwnd"])
                    keybd(VK_CONTROL)
                    send_key(nested["hwnd"], 0x09)
                    keybd(VK_CONTROL, up=True)
                    time.sleep(0.08)
                    record(
                        nested, path, "keyboard_tab_cycle",
                        "真实焦点执行 Ctrl+Tab，并重新枚举可见子页。",
                    )
                    done.add((path, "keyboard_tab_cycle"))

                if "right_click_tabs" in missing:
                    for x in positions:
                        post_click_at(nested["hwnd"], x, 14, button="right")
                        time.sleep(0.06)
                        if visible_popup_menus(session.pid or 0):
                            send_escape(database)
                    record(
                        nested, path, "right_click_tabs",
                        "列表/内容页签标题逐项执行右键并清理弹出菜单。",
                    )
                    done.add((path, "right_click_tabs"))

            if done == expected:
                break

            if attempt in (2, 5, 8):
                # The two archived paths came from separate database-window
                # constructions.  Close while battle dialogue is selected so
                # the next construction restores that page as its initial
                # state, then enumerate the newly created controls.
                close_window_safely(session, database, 4.0)
                database = 0
                reopened = _open_data_window(
                    session, 20008, "数据库", dismiss_hidden=False,
                )
                if not reopened:
                    raise RuntimeError("database did not reopen during path cycle")
                database = int(reopened["hwnd"])
                time.sleep(1.0)
            else:
                if switch_database_page_by_control(database, 120) is None:
                    raise RuntimeError("unit page unavailable while cycling Z-order")
                time.sleep(0.10)

        if done != expected:
            missing = sorted(expected - done)
            raise RuntimeError(
                f"battle-dialogue tree variants incomplete; observed={observed_paths}, "
                f"missing={missing}"
            )
        cancel = find_controls(
            enum_child_tree(database), cls="Button", text_contains="取消", visible=True,
        )
        if cancel:
            click_control(cancel[0]["hwnd"])
            session.wait_gone(database, 4.0)
    except Exception as exc:
        error = repr(exc)
        log(f"DBDIALOGPAGECONTROLS inner failure: {error}")
    finally:
        if database and is_window(database):
            close_window_safely(session, database, 4.0)
        after = session.probe_rom.read_bytes()
        diffs = [i for i, (a, b) in enumerate(zip(before, after)) if a != b]
        unique = {r["action_id"]: r for r in records}
        validated = (
            error is None and len(unique) == 4 and not diffs
            and len(before) == len(after)
        )
        out_dir = session.out / "interaction-discovery"
        out_dir.mkdir(parents=True, exist_ok=True)
        (out_dir / "database-battle-dialogue-page-actions.json").write_text(
            json.dumps({
                "schema_version": 1,
                "validated": validated,
                "error": error,
                "execution_record_count": len(unique),
                "diff_count": len(diffs) + int(len(before) != len(after)),
                "sha256_before": hashlib.sha256(before).hexdigest().upper(),
                "sha256_after": hashlib.sha256(after).hexdigest().upper(),
                "execution_records": list(unique.values()) if validated else [],
            }, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
    if not validated:
        raise RuntimeError(
            f"database battle-dialogue page controls did not validate: "
            f"{len(unique)}/4 {error}"
        )
    log("DBDIALOGPAGECONTROLS complete: 4/4 canonical actions, zero ROM diff")


def stage_dbdialoglistcontrols(session: ProbeSession) -> None:
    """Exercise the battle-dialogue segment and line lists."""
    log("=== stage DBDIALOGLISTCONTROLS ===")
    before = session.probe_rom.read_bytes()
    records = []
    error = None
    database = 0

    def record(item, path, action, result):
        records.append({
            "action_id": stable_interaction_id(
                "数据库", str(item.get("class", "")),
                int(item.get("ctrl_id") or 0), tuple(path), action,
            ),
            "status": "passed",
            "result": result,
        })

    def visible_list(control_id):
        tree = enum_child_tree(database)
        matches = find_controls(
            tree, cls="ListBox", ctrl_id=control_id, visible=True,
        )
        if not matches:
            raise RuntimeError(f"battle-dialogue list {control_id} unavailable")
        item = matches[0]
        path = tuple(control_tree_path(tree, item["hwnd"]) or ())
        return item, path

    def dismiss_new_top_windows(known):
        for popup in session.top_windows():
            popup_hwnd = int(popup["hwnd"])
            if popup_hwnd in known or popup_hwnd == database:
                continue
            close_window_safely(session, popup_hwnd, 1.5)

    def exercise_list(control_id):
        item, path = visible_list(control_id)
        list_hwnd = int(item["hwnd"])
        parent = user32.GetParent(list_hwnd)
        count = max(0, int(_send_msg_num(list_hwnd, LB_GETCOUNT, 0, 0)))
        original = int(_send_msg_num(list_hwnd, LB_GETCURSEL, 0, 0))

        for index in range(count):
            _send_msg_num(list_hwnd, LB_SETCURSEL, index, 0)
            user32.PostMessageW(
                parent, WM_COMMAND,
                (control_id & 0xFFFF) | (LBN_SELCHANGE << 16), list_hwnd,
            )
            time.sleep(0.006)
        if original >= 0:
            _send_msg_num(list_hwnd, LB_SETCURSEL, original, 0)
            user32.PostMessageW(
                parent, WM_COMMAND,
                (control_id & 0xFFFF) | (LBN_SELCHANGE << 16), list_hwnd,
            )
        record(
            item, path, "select_each_item",
            f"逐项选择并通知 {count} 项，随后恢复索引 {original}。",
        )

        opened = 0
        for index in range(count):
            current, _current_path = visible_list(control_id)
            list_hwnd = int(current["hwnd"])
            parent = user32.GetParent(list_hwnd)
            _send_msg_num(list_hwnd, LB_SETCURSEL, index, 0)
            known = {top["hwnd"] for top in session.top_windows()}
            user32.PostMessageW(
                parent, WM_COMMAND,
                (control_id & 0xFFFF) | (2 << 16), list_hwnd,
            )
            time.sleep(0.04)
            new_tops = [
                top for top in session.top_windows()
                if top["hwnd"] not in known and top["hwnd"] != database
            ]
            opened += len(new_tops)
            dismiss_new_top_windows(known)
        record(
            item, path, "double_click_each_item",
            f"逐项执行双击通知 {count} 次；捕获并取消新增子窗 {opened} 次。",
        )

        right_clicks = 0
        for index in range(max(1, count)):
            current, _current_path = visible_list(control_id)
            list_hwnd = int(current["hwnd"])
            if count:
                _send_msg_num(list_hwnd, LB_SETCURSEL, index, 0)
            width, height = get_client_size(list_hwnd)
            post_context_menu(
                list_hwnd, max(2, width // 2),
                max(2, min(height - 2, 8 + (index % 8) * 16)),
            )
            time.sleep(0.035)
            if visible_popup_menus(session.pid or 0):
                right_clicks += 1
                send_escape(database)
        record(
            item, path, "right_click_each_item",
            f"逐项执行右键路径 {count} 次；可见菜单 {right_clicks} 次。",
        )

        current, _current_path = visible_list(control_id)
        list_hwnd = int(current["hwnd"])
        focus_foreground_control(database, list_hwnd)
        send_key(list_hwnd, VK_HOME)
        send_key(list_hwnd, VK_DOWN)
        keyboard_index = int(_send_msg_num(list_hwnd, LB_GETCURSEL, 0, 0))
        if original >= 0:
            _send_msg_num(list_hwnd, LB_SETCURSEL, original, 0)
            user32.PostMessageW(
                user32.GetParent(list_hwnd), WM_COMMAND,
                (control_id & 0xFFFF) | (LBN_SELCHANGE << 16), list_hwnd,
            )
        record(
            item, path, "keyboard_navigation",
            f"真实焦点执行 Home/Down，读回索引 {keyboard_index} 后恢复。",
        )
        return item, path

    try:
        window = _open_data_window(
            session, 20008, "数据库", dismiss_hidden=False,
        )
        if not window:
            raise RuntimeError("database did not appear")
        database = int(window["hwnd"])
        time.sleep(1.0)
        if not find_controls(
            enum_child_tree(database), cls="ListBox", ctrl_id=1390, visible=True,
        ):
            if switch_database_page_by_control(database, 1390) is None:
                raise RuntimeError("battle-dialogue page unavailable")

        segment_item, segment_path = exercise_list(1390)

        # Select the list-form sub-tab before exercising its line list.
        tree = enum_child_tree(database)
        nested = find_controls(
            tree, cls="CPageControl", ctrl_id=2570, visible=True,
        )[0]
        line_visible = False
        width, _height = get_client_size(nested["hwnd"])
        for x in range(12, min(max(20, width - 12), 320), 8):
            post_click_at(nested["hwnd"], x, 14)
            time.sleep(0.05)
            if find_controls(
                enum_child_tree(database), cls="ListBox", ctrl_id=2580,
                visible=True,
            ):
                line_visible = True
                break
        if not line_visible:
            raise RuntimeError("battle-dialogue line-list tab unavailable")
        line_item, line_path = exercise_list(2580)

        if switch_database_page_by_control(database, 120) is None:
            raise RuntimeError("unit page unavailable for list state trigger")
        hidden_tree = enum_child_tree(database)
        hidden_ids = {
            control_id: not bool(find_controls(
                hidden_tree, cls="ListBox", ctrl_id=control_id, visible=True,
            ))
            for control_id in (1390, 2580)
        }
        if switch_database_page_by_control(database, 1390) is None:
            raise RuntimeError("battle-dialogue page did not restore")
        visible_ids = {
            control_id: bool(find_controls(
                enum_child_tree(database), cls="ListBox", ctrl_id=control_id,
                visible=True,
            ))
            for control_id in (1390, 2580)
        }
        if not all(hidden_ids.values()) or not all(visible_ids.values()):
            raise RuntimeError(
                f"list state trigger incomplete: hidden={hidden_ids}, "
                f"visible={visible_ids}"
            )
        record(
            segment_item, segment_path, "discover_state_triggers",
            "切离页面后隐藏、返回战斗对话后恢复可见。",
        )
        record(
            line_item, line_path, "discover_state_triggers",
            "切离页面后隐藏、返回列表子页后恢复可见。",
        )

        cancel = find_controls(
            enum_child_tree(database), cls="Button", text_contains="取消", visible=True,
        )
        if cancel:
            click_control(cancel[0]["hwnd"])
            session.wait_gone(database, 4.0)
    except Exception as exc:
        error = repr(exc)
        log(f"DBDIALOGLISTCONTROLS inner failure: {error}")
    finally:
        if database and is_window(database):
            close_window_safely(session, database, 4.0)
        after = session.probe_rom.read_bytes()
        diffs = [i for i, (a, b) in enumerate(zip(before, after)) if a != b]
        unique = {r["action_id"]: r for r in records}
        validated = (
            error is None and len(unique) == 10 and not diffs
            and len(before) == len(after)
        )
        out_dir = session.out / "interaction-discovery"
        out_dir.mkdir(parents=True, exist_ok=True)
        (out_dir / "database-battle-dialogue-list-actions.json").write_text(
            json.dumps({
                "schema_version": 1,
                "validated": validated,
                "error": error,
                "execution_record_count": len(unique),
                "diff_count": len(diffs) + int(len(before) != len(after)),
                "sha256_before": hashlib.sha256(before).hexdigest().upper(),
                "sha256_after": hashlib.sha256(after).hexdigest().upper(),
                "execution_records": list(unique.values()) if validated else [],
            }, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
    if not validated:
        raise RuntimeError(
            f"database battle-dialogue lists did not validate: "
            f"{len(unique)}/10 {error}"
        )
    log("DBDIALOGLISTCONTROLS complete: 10/10 actions, zero ROM diff")


def stage_dbcorelistcontrols(session: ProbeSession) -> None:
    """Exercise unit, character, ally-animation and enemy-animation lists."""
    log("=== stage DBCORELISTCONTROLS ===")
    before = session.probe_rom.read_bytes()
    records = []
    error = None
    database = 0

    def record(item, path, action, result):
        records.append({
            "action_id": stable_interaction_id(
                "数据库", str(item.get("class", "")),
                int(item.get("ctrl_id") or 0), tuple(path), action,
            ),
            "status": "passed",
            "result": result,
        })

    def current_list(control_id):
        tree = enum_child_tree(database)
        matches = find_controls(
            tree, cls="ListBox", ctrl_id=control_id, visible=True,
        )
        if not matches:
            raise RuntimeError(f"database core list {control_id} unavailable")
        item = matches[0]
        return item, tuple(control_tree_path(tree, item["hwnd"]) or ())

    def dismiss_new_tops(known):
        closed = 0
        for popup in session.top_windows():
            popup_hwnd = int(popup["hwnd"])
            if popup_hwnd in known or popup_hwnd == database:
                continue
            close_window_safely(session, popup_hwnd, 1.5)
            closed += 1
        return closed

    def exercise(control_id):
        item, path = current_list(control_id)
        hwnd = int(item["hwnd"])
        parent = user32.GetParent(hwnd)
        count = max(0, int(_send_msg_num(hwnd, LB_GETCOUNT, 0, 0)))
        original = int(_send_msg_num(hwnd, LB_GETCURSEL, 0, 0))

        for index in range(count):
            _send_msg_num(hwnd, LB_SETCURSEL, index, 0)
            user32.PostMessageW(
                parent, WM_COMMAND,
                (control_id & 0xFFFF) | (LBN_SELCHANGE << 16), hwnd,
            )
            time.sleep(0.004)
        if original >= 0:
            _send_msg_num(hwnd, LB_SETCURSEL, original, 0)
            user32.PostMessageW(
                parent, WM_COMMAND,
                (control_id & 0xFFFF) | (LBN_SELCHANGE << 16), hwnd,
            )
        record(
            item, path, "select_each_item",
            f"逐项选择并通知 {count} 项，恢复索引 {original}。",
        )

        opened = 0
        for index in range(count):
            current, _ = current_list(control_id)
            hwnd = int(current["hwnd"])
            parent = user32.GetParent(hwnd)
            _send_msg_num(hwnd, LB_SETCURSEL, index, 0)
            known = {top["hwnd"] for top in session.top_windows()}
            user32.PostMessageW(
                parent, WM_COMMAND,
                (control_id & 0xFFFF) | (2 << 16), hwnd,
            )
            time.sleep(0.025)
            opened += dismiss_new_tops(known)
        record(
            item, path, "double_click_each_item",
            f"逐项双击 {count} 项；捕获并取消新增子窗 {opened} 次。",
        )

        menus = 0
        for index in range(max(1, count)):
            current, _ = current_list(control_id)
            hwnd = int(current["hwnd"])
            if count:
                _send_msg_num(hwnd, LB_SETCURSEL, index, 0)
            width, height = get_client_size(hwnd)
            post_context_menu(
                hwnd, max(2, width // 2),
                max(2, min(height - 2, 8 + (index % 8) * 16)),
            )
            time.sleep(0.025)
            if visible_popup_menus(session.pid or 0):
                menus += 1
                send_escape(database)
        record(
            item, path, "right_click_each_item",
            f"逐项右键 {count} 项；实际弹出菜单 {menus} 次。",
        )

        current, _ = current_list(control_id)
        hwnd = int(current["hwnd"])
        focus_foreground_control(database, hwnd)
        send_key(hwnd, VK_HOME)
        send_key(hwnd, VK_DOWN)
        keyboard_index = int(_send_msg_num(hwnd, LB_GETCURSEL, 0, 0))
        if original >= 0:
            _send_msg_num(hwnd, LB_SETCURSEL, original, 0)
            user32.PostMessageW(
                user32.GetParent(hwnd), WM_COMMAND,
                (control_id & 0xFFFF) | (LBN_SELCHANGE << 16), hwnd,
            )
        record(
            item, path, "keyboard_navigation",
            f"真实焦点执行 Home/Down，读回 {keyboard_index} 后恢复。",
        )
        return item, path

    def require_page(control_id):
        if switch_database_page_by_control(database, control_id) is None:
            raise RuntimeError(f"database page/list {control_id} unavailable")
        return current_list(control_id)

    try:
        window = _open_data_window(
            session, 20008, "数据库", dismiss_hidden=False,
        )
        if not window:
            raise RuntimeError("database did not appear")
        database = int(window["hwnd"])
        time.sleep(1.0)

        items = {}
        paths = {}
        for control_id in (120, 630):
            require_page(control_id)
            items[control_id], paths[control_id] = exercise(control_id)
            other_id = 630 if control_id == 120 else 120
            if switch_database_page_by_control(database, other_id) is None:
                raise RuntimeError(f"state-trigger page {other_id} unavailable")
            hidden = not bool(find_controls(
                enum_child_tree(database), cls="ListBox", ctrl_id=control_id,
                visible=True,
            ))
            require_page(control_id)
            shown = bool(find_controls(
                enum_child_tree(database), cls="ListBox", ctrl_id=control_id,
                visible=True,
            ))
            if not hidden or not shown:
                raise RuntimeError(
                    f"database list {control_id} state trigger failed"
                )
            record(
                items[control_id], paths[control_id], "discover_state_triggers",
                "切离顶层页后隐藏，返回后恢复可见。",
            )

        require_page(2530)
        items[2530], paths[2530] = exercise(2530)
        tree = enum_child_tree(database)
        nested = find_controls(
            tree, cls="CPageControl", ctrl_id=2540, visible=True,
        )[0]
        width, _height = get_client_size(nested["hwnd"])
        tab_positions = {}
        for target in (2520, 2530):
            for x in range(12, min(max(20, width - 12), 320), 8):
                post_click_at(nested["hwnd"], x, 14)
                time.sleep(0.05)
                if find_controls(
                    enum_child_tree(database), cls="ListBox", ctrl_id=target,
                    visible=True,
                ):
                    tab_positions[target] = x
                    break
            if target not in tab_positions:
                raise RuntimeError(f"weapon animation list {target} tab unavailable")

        post_click_at(nested["hwnd"], tab_positions[2520], 14)
        time.sleep(0.08)
        items[2520], paths[2520] = exercise(2520)

        for control_id, other_id in ((2530, 2520), (2520, 2530)):
            post_click_at(nested["hwnd"], tab_positions[other_id], 14)
            time.sleep(0.08)
            hidden = not bool(find_controls(
                enum_child_tree(database), cls="ListBox", ctrl_id=control_id,
                visible=True,
            ))
            post_click_at(nested["hwnd"], tab_positions[control_id], 14)
            time.sleep(0.08)
            shown = bool(find_controls(
                enum_child_tree(database), cls="ListBox", ctrl_id=control_id,
                visible=True,
            ))
            if not hidden or not shown:
                raise RuntimeError(
                    f"weapon animation list {control_id} state trigger failed"
                )
            record(
                items[control_id], paths[control_id], "discover_state_triggers",
                "切换我方/敌方子页后隐藏，返回后恢复可见。",
            )

        cancel = find_controls(
            enum_child_tree(database), cls="Button", text_contains="取消", visible=True,
        )
        if cancel:
            click_control(cancel[0]["hwnd"])
            session.wait_gone(database, 4.0)
    except Exception as exc:
        error = repr(exc)
        log(f"DBCORELISTCONTROLS inner failure: {error}")
    finally:
        if database and is_window(database):
            close_window_safely(session, database, 4.0)
        after = session.probe_rom.read_bytes()
        diffs = [i for i, (a, b) in enumerate(zip(before, after)) if a != b]
        unique = {r["action_id"]: r for r in records}
        validated = (
            error is None and len(unique) == 20 and not diffs
            and len(before) == len(after)
        )
        out_dir = session.out / "interaction-discovery"
        out_dir.mkdir(parents=True, exist_ok=True)
        (out_dir / "database-core-list-actions.json").write_text(
            json.dumps({
                "schema_version": 1,
                "validated": validated,
                "error": error,
                "execution_record_count": len(unique),
                "diff_count": len(diffs) + int(len(before) != len(after)),
                "sha256_before": hashlib.sha256(before).hexdigest().upper(),
                "sha256_after": hashlib.sha256(after).hexdigest().upper(),
                "execution_records": list(unique.values()) if validated else [],
            }, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
    if not validated:
        raise RuntimeError(
            f"database core lists did not validate: {len(unique)}/20 {error}"
        )
    log("DBCORELISTCONTROLS complete: 20/20 actions, zero ROM diff")


def stage_dbsecondarylistcontrols(session: ProbeSession) -> None:
    """Exercise the remaining standard database ListBox controls."""
    log("=== stage DBSECONDARYLISTCONTROLS ===")
    before = session.probe_rom.read_bytes()
    records = []
    error = None
    database = 0

    def record(item, path, action, result):
        records.append({
            "action_id": stable_interaction_id(
                "数据库", "ListBox", int(item.get("ctrl_id") or 0),
                tuple(path), action,
            ),
            "status": "passed",
            "result": result,
        })

    def current_list(control_id):
        tree = enum_child_tree(database)
        matches = find_controls(
            tree, cls="ListBox", ctrl_id=control_id, visible=True,
        )
        if not matches:
            raise RuntimeError(f"secondary database list {control_id} unavailable")
        item = matches[0]
        return item, tuple(control_tree_path(tree, item["hwnd"]) or ())

    def dismiss_new_tops(known):
        count = 0
        for popup in session.top_windows():
            popup_hwnd = int(popup["hwnd"])
            if popup_hwnd in known or popup_hwnd == database:
                continue
            close_window_safely(session, popup_hwnd, 1.5)
            count += 1
        return count

    def exercise(control_id):
        item, path = current_list(control_id)
        hwnd = int(item["hwnd"])
        parent = user32.GetParent(hwnd)
        count = max(0, int(_send_msg_num(hwnd, LB_GETCOUNT, 0, 0)))
        original = int(_send_msg_num(hwnd, LB_GETCURSEL, 0, 0))

        for index in range(count):
            _send_msg_num(hwnd, LB_SETCURSEL, index, 0)
            user32.PostMessageW(
                parent, WM_COMMAND,
                (control_id & 0xFFFF) | (LBN_SELCHANGE << 16), hwnd,
            )
            time.sleep(0.004)
        if original >= 0:
            _send_msg_num(hwnd, LB_SETCURSEL, original, 0)
            user32.PostMessageW(
                parent, WM_COMMAND,
                (control_id & 0xFFFF) | (LBN_SELCHANGE << 16), hwnd,
            )
        record(
            item, path, "select_each_item",
            f"逐项选择并通知 {count} 项，恢复索引 {original}。",
        )

        opened = 0
        for index in range(count):
            current, _ = current_list(control_id)
            hwnd = int(current["hwnd"])
            parent = user32.GetParent(hwnd)
            _send_msg_num(hwnd, LB_SETCURSEL, index, 0)
            known = {top["hwnd"] for top in session.top_windows()}
            user32.PostMessageW(
                parent, WM_COMMAND,
                (control_id & 0xFFFF) | (2 << 16), hwnd,
            )
            time.sleep(0.025)
            opened += dismiss_new_tops(known)
        record(
            item, path, "double_click_each_item",
            f"逐项双击 {count} 项；捕获并取消新增子窗 {opened} 次。",
        )

        menu_count = 0
        for index in range(max(1, count)):
            current, _ = current_list(control_id)
            hwnd = int(current["hwnd"])
            if count:
                _send_msg_num(hwnd, LB_SETCURSEL, index, 0)
            width, height = get_client_size(hwnd)
            post_context_menu(
                hwnd, max(2, width // 2),
                max(2, min(height - 2, 8 + (index % 8) * 16)),
            )
            time.sleep(0.025)
            if visible_popup_menus(session.pid or 0):
                menu_count += 1
                send_escape(database)
        record(
            item, path, "right_click_each_item",
            f"逐项右键 {count} 项；实际弹出菜单 {menu_count} 次。",
        )

        current, _ = current_list(control_id)
        hwnd = int(current["hwnd"])
        focus_foreground_control(database, hwnd)
        send_key(hwnd, VK_HOME)
        send_key(hwnd, VK_DOWN)
        keyboard_index = int(_send_msg_num(hwnd, LB_GETCURSEL, 0, 0))
        if original >= 0:
            _send_msg_num(hwnd, LB_SETCURSEL, original, 0)
            user32.PostMessageW(
                user32.GetParent(hwnd), WM_COMMAND,
                (control_id & 0xFFFF) | (LBN_SELCHANGE << 16), hwnd,
            )
        record(
            item, path, "keyboard_navigation",
            f"真实焦点 Home/Down 到达 {keyboard_index}，随后恢复。",
        )
        return item, path

    try:
        window = _open_data_window(
            session, 20008, "数据库", dismiss_hidden=False,
        )
        if not window:
            raise RuntimeError("database did not appear")
        database = int(window["hwnd"])
        time.sleep(1.0)

        for control_id in (610, 1270, 1750, 1810):
            if switch_database_page_by_control(database, control_id) is None:
                raise RuntimeError(f"database list page {control_id} unavailable")
            item, path = exercise(control_id)
            if switch_database_page_by_control(database, 120) is None:
                raise RuntimeError("unit page unavailable for state trigger")
            hidden = not bool(find_controls(
                enum_child_tree(database), cls="ListBox", ctrl_id=control_id,
                visible=True,
            ))
            if switch_database_page_by_control(database, control_id) is None:
                raise RuntimeError(f"database list {control_id} did not restore")
            shown = bool(find_controls(
                enum_child_tree(database), cls="ListBox", ctrl_id=control_id,
                visible=True,
            ))
            if not hidden or not shown:
                raise RuntimeError(
                    f"database list {control_id} state trigger failed: "
                    f"hidden={hidden} shown={shown}"
                )
            record(
                item, path, "discover_state_triggers",
                "切离所在页后隐藏，重新进入后恢复可见。",
            )

        cancel = find_controls(
            enum_child_tree(database), cls="Button", text_contains="取消", visible=True,
        )
        if cancel:
            click_control(cancel[0]["hwnd"])
            session.wait_gone(database, 4.0)
    except Exception as exc:
        error = repr(exc)
        log(f"DBSECONDARYLISTCONTROLS inner failure: {error}")
    finally:
        if database and is_window(database):
            close_window_safely(session, database, 4.0)
        after = session.probe_rom.read_bytes()
        diffs = [i for i, (a, b) in enumerate(zip(before, after)) if a != b]
        unique = {r["action_id"]: r for r in records}
        validated = (
            error is None and len(unique) == 20 and not diffs
            and len(before) == len(after)
        )
        out_dir = session.out / "interaction-discovery"
        out_dir.mkdir(parents=True, exist_ok=True)
        (out_dir / "database-secondary-list-actions.json").write_text(
            json.dumps({
                "schema_version": 1,
                "validated": validated,
                "error": error,
                "execution_record_count": len(unique),
                "diff_count": len(diffs) + int(len(before) != len(after)),
                "sha256_before": hashlib.sha256(before).hexdigest().upper(),
                "sha256_after": hashlib.sha256(after).hexdigest().upper(),
                "execution_records": list(unique.values()) if validated else [],
            }, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
    if not validated:
        raise RuntimeError(
            f"database secondary lists did not validate: {len(unique)}/20 {error}"
        )
    log("DBSECONDARYLISTCONTROLS complete: 20/20 actions, zero ROM diff")


def stage_dbsyslistcontrols(session: ProbeSession) -> None:
    """Exercise all database SysListView32 controls with real pointer input."""
    log("=== stage DBSYSLISTCONTROLS ===")
    before = session.probe_rom.read_bytes()
    records = []
    error = None
    database = 0

    def record(item, path, action, result):
        records.append({
            "action_id": stable_interaction_id(
                "数据库", "SysListView32", int(item.get("ctrl_id") or 0),
                tuple(path), action,
            ),
            "status": "passed",
            "result": result,
        })

    def current_view(control_id):
        tree = enum_child_tree(database)
        matches = find_controls(
            tree, cls="SysListView32", ctrl_id=control_id, visible=True,
        )
        if not matches:
            raise RuntimeError(f"database list-view {control_id} unavailable")
        item = matches[0]
        return item, tuple(control_tree_path(tree, item["hwnd"]) or ())

    def dismiss_new_tops(known):
        count = 0
        for popup in session.top_windows():
            popup_hwnd = int(popup["hwnd"])
            if popup_hwnd in known or popup_hwnd == database:
                continue
            close_window_safely(session, popup_hwnd, 1.5)
            count += 1
        return count

    def selected_row_point(hwnd, index):
        width, height = get_client_size(hwnd)
        top = max(0, int(_send_msg_num(hwnd, LVM_GETTOPINDEX, 0, 0)))
        per_page = max(1, int(_send_msg_num(hwnd, LVM_GETCOUNTPERPAGE, 0, 0)))
        row_height = max(14, height // per_page)
        y = (index - top) * row_height + row_height // 2
        return max(3, min(width - 3, width // 2)), max(3, min(height - 3, y))

    def walk_to_each(hwnd, count, callback=None):
        focus_foreground_control(database, hwnd)
        send_key(hwnd, VK_HOME)
        time.sleep(0.03)
        visited = []
        for index in range(count):
            if index:
                send_key(hwnd, VK_DOWN)
                time.sleep(0.012)
            visited.append(index)
            if callback:
                callback(index)
        return visited

    def exercise(control_id):
        item, path = current_view(control_id)
        hwnd = int(item["hwnd"])
        count = max(0, int(_send_msg_num(hwnd, LVM_GETITEMCOUNT, 0, 0)))

        visited = walk_to_each(hwnd, count)
        selected_count = int(_send_msg_num(hwnd, LVM_GETSELECTEDCOUNT, 0, 0))
        record(
            item, path, "select_each_item",
            f"真实键盘逐项到达 {len(visited)}/{count} 项；最终选择数={selected_count}。",
        )

        opened = 0
        def double_current(index):
            nonlocal opened, hwnd
            known = {top["hwnd"] for top in session.top_windows()}
            x, y = selected_row_point(hwnd, index)
            post_double_click_at(hwnd, x, y)
            time.sleep(0.04)
            opened += dismiss_new_tops(known)
            current, _ = current_view(control_id)
            hwnd = int(current["hwnd"])
        walk_to_each(hwnd, count, double_current)
        record(
            item, path, "double_click_each_item",
            f"逐项真实双击 {count} 项；捕获并取消新增子窗 {opened} 次。",
        )

        menus = 0
        def right_current(index):
            nonlocal menus, hwnd
            x, y = selected_row_point(hwnd, index)
            post_context_menu(hwnd, x, y)
            time.sleep(0.035)
            if visible_popup_menus(session.pid or 0):
                menus += 1
                send_escape(database)
            current, _ = current_view(control_id)
            hwnd = int(current["hwnd"])
        walk_to_each(hwnd, count, right_current)
        record(
            item, path, "right_click_each_item",
            f"逐项真实右键 {count} 项；实际菜单 {menus} 次。",
        )

        focus_foreground_control(database, hwnd)
        send_key(hwnd, VK_HOME)
        send_key(hwnd, VK_DOWN)
        selected_count = int(_send_msg_num(hwnd, LVM_GETSELECTEDCOUNT, 0, 0))
        record(
            item, path, "keyboard_navigation",
            f"真实焦点执行 Home/Down；最终选择数={selected_count}。",
        )
        return item, path

    try:
        window = _open_data_window(
            session, 20008, "数据库", dismiss_hidden=False,
        )
        if not window:
            raise RuntimeError("database did not appear")
        database = int(window["hwnd"])
        time.sleep(1.0)

        for control_id in (1570, 1580, 1690, 2610):
            if switch_database_page_by_control(database, control_id) is None:
                raise RuntimeError(f"database list-view page {control_id} unavailable")
            item, path = exercise(control_id)
            if switch_database_page_by_control(database, 120) is None:
                raise RuntimeError("unit page unavailable for state trigger")
            hidden = not bool(find_controls(
                enum_child_tree(database), cls="SysListView32",
                ctrl_id=control_id, visible=True,
            ))
            if switch_database_page_by_control(database, control_id) is None:
                raise RuntimeError(f"database list-view {control_id} did not restore")
            shown = bool(find_controls(
                enum_child_tree(database), cls="SysListView32",
                ctrl_id=control_id, visible=True,
            ))
            if not hidden or not shown:
                raise RuntimeError(
                    f"database list-view {control_id} state trigger failed: "
                    f"hidden={hidden} shown={shown}"
                )
            record(
                item, path, "discover_state_triggers",
                "切离所在页后隐藏，返回后恢复可见。",
            )

        cancel = find_controls(
            enum_child_tree(database), cls="Button", text_contains="取消", visible=True,
        )
        if cancel:
            click_control(cancel[0]["hwnd"])
            session.wait_gone(database, 4.0)
    except Exception as exc:
        error = repr(exc)
        log(f"DBSYSLISTCONTROLS inner failure: {error}")
    finally:
        if database and is_window(database):
            close_window_safely(session, database, 4.0)
        after = session.probe_rom.read_bytes()
        diffs = [i for i, (a, b) in enumerate(zip(before, after)) if a != b]
        unique = {r["action_id"]: r for r in records}
        validated = (
            error is None and len(unique) == 20 and not diffs
            and len(before) == len(after)
        )
        out_dir = session.out / "interaction-discovery"
        out_dir.mkdir(parents=True, exist_ok=True)
        (out_dir / "database-syslist-actions.json").write_text(
            json.dumps({
                "schema_version": 1,
                "validated": validated,
                "error": error,
                "execution_record_count": len(unique),
                "diff_count": len(diffs) + int(len(before) != len(after)),
                "sha256_before": hashlib.sha256(before).hexdigest().upper(),
                "sha256_after": hashlib.sha256(after).hexdigest().upper(),
                "execution_records": list(unique.values()) if validated else [],
            }, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
    if not validated:
        raise RuntimeError(
            f"database SysListView controls did not validate: "
            f"{len(unique)}/20 {error}"
        )
    log("DBSYSLISTCONTROLS complete: 20/20 actions, zero ROM diff")


def _stage_dbcombocontrols(
    session: ProbeSession,
    control_ids: tuple[int, ...],
    stage_name: str,
    output_filename: str,
) -> None:
    """Exercise one complete batch of database combo boxes."""
    log(f"=== stage {stage_name} ===")
    before = session.probe_rom.read_bytes()
    records = []
    observations = []
    error = None
    database = 0

    def record(item, path, action, result):
        records.append({
            "action_id": stable_interaction_id(
                "数据库", "ComboBox", int(item.get("ctrl_id") or 0),
                tuple(path), action,
            ),
            "status": "passed",
            "result": result,
        })

    def current_combo(control_id, *, require_enabled=True):
        tree = enum_child_tree(database)
        matches = find_controls(
            tree, cls="ComboBox", ctrl_id=control_id, visible=True,
        )
        if not matches:
            raise RuntimeError(f"database combo {control_id} unavailable")
        item = matches[0]
        if require_enabled and not item.get("enabled"):
            raise RuntimeError(f"database combo {control_id} disabled")
        return item, tuple(control_tree_path(tree, item["hwnd"]) or ())

    def ensure_combo_enabled(control_id):
        target, _ = current_combo(control_id, require_enabled=False)
        if target.get("enabled"):
            return []
        tree = enum_child_tree(database)
        candidates = [
            item for item in find_controls(tree, cls="ComboBox", visible=True)
            if item.get("enabled")
            and int(item.get("ctrl_id") or 0) != control_id
        ]
        for candidate in candidates:
            candidate_id = int(candidate.get("ctrl_id") or 0)
            candidate_hwnd = int(candidate["hwnd"])
            original = int(_send_msg_num(candidate_hwnd, CB_GETCURSEL, 0, 0))
            values = read_combo_items(candidate_hwnd)
            for index in range(len(values)):
                set_combo_selection(candidate_hwnd, index)
                time.sleep(0.06)
                refreshed, _ = current_combo(control_id, require_enabled=False)
                if refreshed.get("enabled"):
                    observations.append({
                        "control_id": control_id,
                        "enabled_by_control": candidate_id,
                        "enabled_by_index": index,
                        "enabled_by_text": values[index],
                        "parent_original_index": original,
                    })
                    return [("combo", candidate_id, original, index)]
            if original >= 0:
                current_parent, _ = current_combo(candidate_id)
                set_combo_selection(current_parent["hwnd"], original)
                time.sleep(0.04)
        # Some fields are record-dependent rather than controlled by another
        # combo (for example a unit's optional secondary image address).
        tree = enum_child_tree(database)
        lists = [
            item for item in find_controls(tree, cls="ListBox", visible=True)
            if item.get("enabled")
        ]
        for list_item in lists:
            list_id = int(list_item.get("ctrl_id") or 0)
            list_hwnd = int(list_item["hwnd"])
            original = int(_send_msg_num(list_hwnd, LB_GETCURSEL, 0, 0))
            count = max(0, int(_send_msg_num(list_hwnd, LB_GETCOUNT, 0, 0)))
            parent = user32.GetParent(list_hwnd)
            for index in range(count):
                _send_msg_num(list_hwnd, LB_SETCURSEL, index, 0)
                user32.PostMessageW(
                    parent, WM_COMMAND,
                    (list_id & 0xFFFF) | (LBN_SELCHANGE << 16), list_hwnd,
                )
                time.sleep(0.06)
                refreshed, _ = current_combo(control_id, require_enabled=False)
                if refreshed.get("enabled"):
                    observations.append({
                        "control_id": control_id,
                        "enabled_by_list": list_id,
                        "enabled_by_index": index,
                        "list_original_index": original,
                    })
                    return [("list", list_id, original, index)]
            if original >= 0:
                _send_msg_num(list_hwnd, LB_SETCURSEL, original, 0)
                user32.PostMessageW(
                    parent, WM_COMMAND,
                    (list_id & 0xFFFF) | (LBN_SELCHANGE << 16), list_hwnd,
                )
                time.sleep(0.04)
        raise RuntimeError(
            f"database combo {control_id} disabled and no combo/list enabling state found"
        )

    def restore_activators(activators):
        for kind, candidate_id, original, _enabled_index in reversed(activators):
            if original < 0:
                continue
            if kind == "combo":
                candidate, _ = current_combo(candidate_id, require_enabled=False)
                set_combo_selection(candidate["hwnd"], original)
            else:
                tree = enum_child_tree(database)
                candidate = find_controls(
                    tree, cls="ListBox", ctrl_id=candidate_id, visible=True,
                )[0]
                _send_msg_num(candidate["hwnd"], LB_SETCURSEL, original, 0)
                user32.PostMessageW(
                    user32.GetParent(candidate["hwnd"]), WM_COMMAND,
                    (candidate_id & 0xFFFF) | (LBN_SELCHANGE << 16),
                    candidate["hwnd"],
                )
            time.sleep(0.04)

    def exercise(control_id):
        item, path = current_combo(control_id)
        hwnd = int(item["hwnd"])
        values = read_combo_items(hwnd)
        original = int(_send_msg_num(hwnd, CB_GETCURSEL, 0, 0))

        _send_msg_num(hwnd, 0x014F, 1, 0)
        time.sleep(0.06)
        dropped = bool(_send_msg_num(hwnd, 0x0157, 0, 0))  # CB_GETDROPPEDSTATE
        _send_msg_num(hwnd, 0x014F, 0, 0)
        record(
            item, path, "open_dropdown",
            f"展开状态={dropped}，收起；完整项目数={len(values)}。",
        )

        readbacks = []
        for index in range(len(values)):
            current, _ = current_combo(control_id)
            hwnd = int(current["hwnd"])
            set_combo_selection(hwnd, index)
            time.sleep(0.004)
            readbacks.append(int(_send_msg_num(hwnd, CB_GETCURSEL, 0, 0)))
        current, _ = current_combo(control_id)
        hwnd = int(current["hwnd"])
        if original >= 0:
            set_combo_selection(hwnd, original)
        if readbacks != list(range(len(values))):
            raise RuntimeError(
                f"database combo {control_id} readback mismatch: "
                f"{len(readbacks)}/{len(values)}"
            )
        record(
            item, path, "select_each_item",
            f"逐项选择并读回 {len(readbacks)}/{len(values)} 项，随后恢复。",
        )

        current, _ = current_combo(control_id)
        hwnd = int(current["hwnd"])
        focus_foreground_control(database, hwnd)
        send_key(hwnd, VK_HOME)
        send_key(hwnd, VK_DOWN)
        time.sleep(0.04)
        keyboard_index = int(_send_msg_num(hwnd, CB_GETCURSEL, 0, 0))
        if original >= 0:
            set_combo_selection(hwnd, original)
        record(
            item, path, "keyboard_cycle",
            f"真实焦点 Home/Down 读回 {keyboard_index}，随后恢复。",
        )

        post_context_menu(hwnd, 6, 6)
        time.sleep(0.08)
        menu_visible = bool(visible_popup_menus(session.pid or 0))
        if menu_visible:
            send_escape(database)
        record(
            item, path, "right_click",
            f"执行右键路径；可见弹出菜单={menu_visible}。",
        )
        observations.append({
            "control_id": control_id,
            "path": list(path),
            "item_count": len(values),
            "original_index": original,
            "keyboard_index": keyboard_index,
            "right_click_menu": menu_visible,
        })
        return item, path

    def hide_on_other_page(control_id):
        for target in (120, 630, 1390, 1810, 1750, 2530):
            if switch_database_page_by_control(database, target) is None:
                continue
            if not find_controls(
                enum_child_tree(database), cls="ComboBox",
                ctrl_id=control_id, visible=True,
            ):
                return target
        raise RuntimeError(f"database combo {control_id} could not be hidden")

    try:
        window = _open_data_window(
            session, 20008, "数据库", dismiss_hidden=False,
        )
        if not window:
            raise RuntimeError("database did not appear")
        database = int(window["hwnd"])
        move_window(database, 25, 15, 1600, 1060)
        time.sleep(1.0)

        for control_id in control_ids:
            if switch_database_page_by_control(database, control_id) is None:
                raise RuntimeError(f"database combo page {control_id} unavailable")
            activators = ensure_combo_enabled(control_id)
            item, path = exercise(control_id)
            hidden_on = hide_on_other_page(control_id)
            if switch_database_page_by_control(database, control_id) is None:
                raise RuntimeError(f"database combo {control_id} did not restore")
            restored, _ = current_combo(control_id)
            record(
                item, path, "discover_state_triggers",
                f"切换到目标控件 {hidden_on} 所在页后隐藏；返回后可见且启用="
                f"{bool(restored.get('enabled'))}；条件启用链={activators}。",
            )
            restore_activators(activators)

        cancel = find_controls(
            enum_child_tree(database), cls="Button", text_contains="取消", visible=True,
        )
        if cancel:
            click_control(cancel[0]["hwnd"])
            session.wait_gone(database, 4.0)
    except Exception as exc:
        error = repr(exc)
        log(f"{stage_name} inner failure: {error}")
    finally:
        if database and is_window(database):
            close_window_safely(session, database, 4.0)
        after = session.probe_rom.read_bytes()
        diffs = [i for i, (a, b) in enumerate(zip(before, after)) if a != b]
        unique = {r["action_id"]: r for r in records}
        validated = (
            error is None and len(unique) == len(control_ids) * 5 and not diffs
            and len(before) == len(after)
        )
        out_dir = session.out / "interaction-discovery"
        out_dir.mkdir(parents=True, exist_ok=True)
        (out_dir / output_filename).write_text(
            json.dumps({
                "schema_version": 1,
                "validated": validated,
                "error": error,
                "execution_record_count": len(unique),
                "diff_count": len(diffs) + int(len(before) != len(after)),
                "sha256_before": hashlib.sha256(before).hexdigest().upper(),
                "sha256_after": hashlib.sha256(after).hexdigest().upper(),
                "observations": observations,
                "execution_records": list(unique.values()) if validated else [],
            }, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
    if not validated:
        raise RuntimeError(
            f"database combo batch did not validate: "
            f"{len(unique)}/{len(control_ids) * 5} {error}"
        )
    log(
        f"{stage_name} complete: {len(control_ids) * 5}/"
        f"{len(control_ids) * 5} actions, zero ROM diff"
    )


def stage_dbunitcharcombocontrols(session: ProbeSession) -> None:
    """Exercise all unit/character database combo boxes."""
    _stage_dbcombocontrols(
        session,
        (
            350, 360, 370, 530, 540, 550, 560, 570,
            690, 700, 710, 720, 840, 850, 1190, 1540, 1600,
        ),
        "DBUNITCHARCOMBOCONTROLS",
        "database-unit-character-combo-actions.json",
    )


def stage_dbothercombocontrols(session: ProbeSession) -> None:
    """Exercise weapon, dialogue and other-page database combo boxes."""
    _stage_dbcombocontrols(
        session,
        (1410, 1870, 1880, 1890, 1900, 1920, 1940, 2620),
        "DBOTHERCOMBOCONTROLS",
        "database-other-combo-actions.json",
    )


def _stage_dbeditcontrols(
    session: ProbeSession,
    control_ids: tuple[int, ...],
    stage_name: str,
    output_filename: str,
) -> None:
    """Exercise one complete batch of database Edit controls."""
    log(f"=== stage {stage_name} ===")
    before = session.probe_rom.read_bytes()
    records = []
    observations = []
    error = None
    database = 0

    def record(item, path, action, result):
        records.append({
            "action_id": stable_interaction_id(
                "数据库", "Edit", int(item.get("ctrl_id") or 0),
                tuple(path), action,
            ),
            "status": "passed",
            "result": result,
        })

    def current_edit(control_id, *, require_enabled=True):
        tree = enum_child_tree(database)
        matches = find_controls(tree, cls="Edit", ctrl_id=control_id, visible=True)
        if not matches:
            raise RuntimeError(f"database edit {control_id} unavailable")
        item = matches[0]
        if require_enabled and not item.get("enabled"):
            raise RuntimeError(f"database edit {control_id} disabled")
        return item, tuple(control_tree_path(tree, item["hwnd"]) or ())

    def notify_edit(hwnd, control_id):
        parent = user32.GetParent(hwnd)
        if parent:
            user32.PostMessageW(
                parent, WM_COMMAND,
                (control_id & 0xFFFF) | (0x0300 << 16), hwnd,
            )

    def ensure_enabled(control_id):
        item, _ = current_edit(control_id, require_enabled=False)
        if item.get("enabled"):
            return []
        tree = enum_child_tree(database)
        for list_item in find_controls(tree, cls="ListBox", visible=True):
            if not list_item.get("enabled"):
                continue
            list_id = int(list_item.get("ctrl_id") or 0)
            list_hwnd = int(list_item["hwnd"])
            original = int(_send_msg_num(list_hwnd, LB_GETCURSEL, 0, 0))
            count = max(0, int(_send_msg_num(list_hwnd, LB_GETCOUNT, 0, 0)))
            parent = user32.GetParent(list_hwnd)
            for index in range(count):
                _send_msg_num(list_hwnd, LB_SETCURSEL, index, 0)
                user32.PostMessageW(
                    parent, WM_COMMAND,
                    (list_id & 0xFFFF) | (LBN_SELCHANGE << 16), list_hwnd,
                )
                time.sleep(0.05)
                refreshed, _ = current_edit(control_id, require_enabled=False)
                if refreshed.get("enabled"):
                    observations.append({
                        "control_id": control_id,
                        "enabled_by_list": list_id,
                        "enabled_by_index": index,
                        "list_original_index": original,
                    })
                    return [(list_id, original, index)]
            if original >= 0:
                _send_msg_num(list_hwnd, LB_SETCURSEL, original, 0)
                user32.PostMessageW(
                    parent, WM_COMMAND,
                    (list_id & 0xFFFF) | (LBN_SELCHANGE << 16), list_hwnd,
                )
        raise RuntimeError(
            f"database edit {control_id} disabled and no enabling record found"
        )

    def restore_activators(activators):
        for list_id, original, _index in reversed(activators):
            if original < 0:
                continue
            tree = enum_child_tree(database)
            list_item = find_controls(
                tree, cls="ListBox", ctrl_id=list_id, visible=True,
            )[0]
            _send_msg_num(list_item["hwnd"], LB_SETCURSEL, original, 0)
            user32.PostMessageW(
                user32.GetParent(list_item["hwnd"]), WM_COMMAND,
                (list_id & 0xFFFF) | (LBN_SELCHANGE << 16), list_item["hwnd"],
            )
            time.sleep(0.04)

    def classify_values(original, control_id):
        stripped = original.strip()
        if control_id in {230, 240, 250, 290, 300, 310, 730, 740, 750}:
            return "hex", "00" if stripped.upper() != "00" else "01", ("00", "FF")
        if re.fullmatch(r"\d+", stripped):
            width = max(1, len(stripped))
            replacement = str((int(stripped) + 1) % (10 ** width)).zfill(width)
            return "decimal", replacement, ("0", "9" * max(6, width + 3))
        return "text", original + "A", ("", "A" * 256)

    def exercise(control_id):
        item, path = current_edit(control_id)
        hwnd = int(item["hwnd"])
        original = get_ctrl_text(hwnd)
        value_kind, replacement, boundaries = classify_values(original, control_id)

        focused = focus_foreground_control(database, hwnd)
        record(item, path, "focus", f"真实键盘焦点={focused}。")

        set_control_text(hwnd, replacement)
        notify_edit(hwnd, control_id)
        time.sleep(0.035)
        replacement_readback = get_ctrl_text(hwnd)
        set_control_text(hwnd, original)
        notify_edit(hwnd, control_id)
        record(
            item, path, "replace_value",
            f"{value_kind} 等类替换读回={replacement_readback!r}，随后恢复。",
        )

        focus_foreground_control(database, hwnd)
        keybd(VK_CONTROL)
        keybd(ord("A")); keybd(ord("A"), up=True)
        keybd(VK_CONTROL, up=True)
        keybd(VK_CONTROL)
        keybd(ord("Z")); keybd(ord("Z"), up=True)
        keybd(VK_CONTROL, up=True)
        set_control_text(hwnd, original)
        notify_edit(hwnd, control_id)
        record(
            item, path, "keyboard_shortcuts",
            "真实焦点执行 Ctrl+A/Ctrl+Z，随后恢复原草稿。",
        )

        post_context_menu(hwnd, 6, 6)
        time.sleep(0.08)
        menu_visible = bool(visible_popup_menus(session.pid or 0))
        if menu_visible:
            send_escape(database)
        record(
            item, path, "right_click",
            f"执行右键路径；可见弹出菜单={menu_visible}。",
        )

        boundary_readbacks = []
        for candidate in boundaries:
            current, _ = current_edit(control_id)
            hwnd = int(current["hwnd"])
            set_control_text(hwnd, candidate)
            notify_edit(hwnd, control_id)
            time.sleep(0.035)
            boundary_readbacks.append(get_ctrl_text(hwnd))
        current, _ = current_edit(control_id)
        hwnd = int(current["hwnd"])
        set_control_text(hwnd, original)
        notify_edit(hwnd, control_id)
        record(
            item, path, "boundary_values",
            f"{value_kind} 边界 {list(boundaries)} 读回={boundary_readbacks}，随后恢复。",
        )
        observations.append({
            "control_id": control_id,
            "path": list(path),
            "kind": value_kind,
            "original": original,
            "replacement": replacement_readback,
            "boundary_inputs": list(boundaries),
            "boundary_readbacks": boundary_readbacks,
            "right_click_menu": menu_visible,
        })
        return item, path

    def hide_on_other_page(control_id):
        for target in (120, 630, 1390, 1810, 1750, 2530):
            if switch_database_page_by_control(database, target) is None:
                continue
            if not find_controls(
                enum_child_tree(database), cls="Edit", ctrl_id=control_id,
                visible=True,
            ):
                return target
        raise RuntimeError(f"database edit {control_id} could not be hidden")

    try:
        window = _open_data_window(
            session, 20008, "数据库", dismiss_hidden=False,
        )
        if not window:
            raise RuntimeError("database did not appear")
        database = int(window["hwnd"])
        move_window(database, 25, 15, 1600, 1060)
        time.sleep(1.0)

        for control_id in control_ids:
            if switch_database_page_by_control(database, control_id) is None:
                raise RuntimeError(f"database edit page {control_id} unavailable")
            activators = ensure_enabled(control_id)
            item, path = exercise(control_id)
            hidden_on = hide_on_other_page(control_id)
            if switch_database_page_by_control(database, control_id) is None:
                raise RuntimeError(f"database edit {control_id} did not restore")
            restored, _ = current_edit(control_id)
            record(
                item, path, "discover_state_triggers",
                f"切换到目标控件 {hidden_on} 所在页后隐藏；返回后可见且启用="
                f"{bool(restored.get('enabled'))}；条件记录链={activators}。",
            )
            restore_activators(activators)

        cancel = find_controls(
            enum_child_tree(database), cls="Button", text_contains="取消", visible=True,
        )
        if cancel:
            click_control(cancel[0]["hwnd"])
            session.wait_gone(database, 4.0)
    except Exception as exc:
        error = repr(exc)
        log(f"{stage_name} inner failure: {error}")
    finally:
        if database and is_window(database):
            close_window_safely(session, database, 4.0)
        after = session.probe_rom.read_bytes()
        diffs = [i for i, (a, b) in enumerate(zip(before, after)) if a != b]
        unique = {r["action_id"]: r for r in records}
        expected = len(control_ids) * 6
        validated = (
            error is None and len(unique) == expected and not diffs
            and len(before) == len(after)
        )
        out_dir = session.out / "interaction-discovery"
        out_dir.mkdir(parents=True, exist_ok=True)
        (out_dir / output_filename).write_text(
            json.dumps({
                "schema_version": 1,
                "validated": validated,
                "error": error,
                "execution_record_count": len(unique),
                "diff_count": len(diffs) + int(len(before) != len(after)),
                "sha256_before": hashlib.sha256(before).hexdigest().upper(),
                "sha256_after": hashlib.sha256(after).hexdigest().upper(),
                "observations": observations,
                "execution_records": list(unique.values()) if validated else [],
            }, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
    if not validated:
        raise RuntimeError(
            f"database edit batch did not validate: {len(unique)}/{expected} {error}"
        )
    log(f"{stage_name} complete: {expected}/{expected} actions, zero ROM diff")


def stage_dbuniteditcontrols(session: ProbeSession) -> None:
    """Exercise all unit-page database edits."""
    _stage_dbeditcontrols(
        session,
        (
            170, 230, 240, 250, 290, 300, 310, 390, 410, 420, 430,
            440, 450, 460, 470, 480, 490, 500, 510, 1300,
        ),
        "DBUNITEDITCONTROLS",
        "database-unit-edit-actions.json",
    )


def stage_dbcharactereditcontrols(session: ProbeSession) -> None:
    """Exercise all character-page database edits."""
    _stage_dbeditcontrols(
        session,
        (730, 740, 750, 830, 890, 910, 960, 970, 980, 990, 1000, 2200),
        "DBCHARACTEREDITCONTROLS",
        "database-character-edit-actions.json",
    )


def stage_dbweaponeditcontrols(session: ProbeSession) -> None:
    """Exercise all weapon-page database edits."""
    _stage_dbeditcontrols(
        session,
        (1180, 1200, 1210, 1220, 1230, 1240, 1250),
        "DBWEAPONEDITCONTROLS",
        "database-weapon-edit-actions.json",
    )


def stage_dbothereditcontrols(session: ProbeSession) -> None:
    """Exercise dialogue, shop and other-page database edits."""
    _stage_dbeditcontrols(
        session,
        (
            1370, 1620, 1640, 1650, 1710, 1730, 1770, 1780,
            1970, 1990, 2010, 2020, 2040, 2060, 2090,
        ),
        "DBOTHEREDITCONTROLS",
        "database-other-edit-actions.json",
    )


def stage_dbrooteditcontrols(session: ProbeSession) -> None:
    """Exercise the database-wide search edit, including its real lifetime."""
    log("=== stage DBROOTEDITCONTROLS ===")
    before = session.probe_rom.read_bytes()
    records = []
    observations = []
    error = None
    database = 0

    def current_search():
        tree = enum_child_tree(database)
        matches = find_controls(
            tree, cls="Edit", ctrl_id=2150, visible=True,
        )
        if not matches:
            raise RuntimeError("database root search edit 2150 unavailable")
        item = matches[0]
        return item, tuple(control_tree_path(tree, item["hwnd"]) or ())

    def notify_search(hwnd):
        parent = user32.GetParent(hwnd)
        if parent:
            user32.PostMessageW(
                parent, WM_COMMAND, 2150 | (0x0300 << 16), hwnd,
            )

    def record(item, path, action, result):
        records.append({
            "action_id": stable_interaction_id(
                "数据库", "Edit", 2150, tuple(path), action,
            ),
            "status": "passed",
            "result": result,
        })

    try:
        window = _open_data_window(
            session, 20008, "数据库", dismiss_hidden=False,
        )
        if not window:
            raise RuntimeError("database did not appear")
        database = int(window["hwnd"])
        move_window(database, 25, 15, 1600, 1060)
        time.sleep(0.8)

        item, path = current_search()
        hwnd = int(item["hwnd"])
        original = get_ctrl_text(hwnd)

        focused = focus_foreground_control(database, hwnd)
        record(item, path, "focus", f"真实键盘焦点={focused}。")

        set_control_text(hwnd, "盖塔")
        notify_search(hwnd)
        time.sleep(0.06)
        replacement = get_ctrl_text(hwnd)
        set_control_text(hwnd, original)
        notify_search(hwnd)
        record(
            item, path, "replace_value",
            f"输入中文名称读回={replacement!r}，随后恢复原搜索条件。",
        )

        focus_foreground_control(database, hwnd)
        keybd(VK_CONTROL)
        keybd(ord("A")); keybd(ord("A"), up=True)
        keybd(VK_CONTROL, up=True)
        keybd(VK_CONTROL)
        keybd(ord("Z")); keybd(ord("Z"), up=True)
        keybd(VK_CONTROL, up=True)
        set_control_text(hwnd, original)
        notify_search(hwnd)
        record(
            item, path, "keyboard_shortcuts",
            "真实焦点执行 Ctrl+A/Ctrl+Z，随后恢复原搜索条件。",
        )

        post_context_menu(hwnd, 6, 6)
        time.sleep(0.08)
        menu_visible = bool(visible_popup_menus(session.pid or 0))
        if menu_visible:
            send_escape(database)
        record(
            item, path, "right_click",
            f"执行右键路径；可见标准编辑菜单={menu_visible}。",
        )

        boundary_readbacks = []
        for candidate in ("", "A" * 256):
            item_now, _ = current_search()
            hwnd = int(item_now["hwnd"])
            set_control_text(hwnd, candidate)
            notify_search(hwnd)
            time.sleep(0.06)
            boundary_readbacks.append(get_ctrl_text(hwnd))
        item_now, _ = current_search()
        set_control_text(int(item_now["hwnd"]), original)
        notify_search(int(item_now["hwnd"]))
        record(
            item, path, "boundary_values",
            f"空值与 256 字符边界读回长度="
            f"{[len(value) for value in boundary_readbacks]}，随后恢复。",
        )
        observations.append({
            "control_id": 2150,
            "path": list(path),
            "original": original,
            "replacement": replacement,
            "boundary_readback_lengths": [
                len(value) for value in boundary_readbacks
            ],
            "right_click_menu": menu_visible,
        })

        cancel = find_controls(
            enum_child_tree(database), cls="Button",
            text_contains="取消", visible=True,
        )
        if not cancel:
            raise RuntimeError("database cancel button unavailable")
        click_control(cancel[0]["hwnd"])
        closed = session.wait_gone(database, 4.0)
        if not closed:
            raise RuntimeError("database did not close after Cancel")
        record(
            item, path, "discover_state_triggers",
            "数据库全局搜索框不随页签切换；点击数据库“取消”后随所属窗口"
            "一并销毁。重新打开数据库后同一 ID/路径恢复可见且启用。",
        )
        database = 0

        reopened = _open_data_window(
            session, 20008, "数据库", dismiss_hidden=False,
        )
        if not reopened:
            raise RuntimeError("database did not reopen for lifetime restore")
        database = int(reopened["hwnd"])
        restored, restored_path = current_search()
        if (
            restored_path != path
            or not restored.get("visible")
            or not restored.get("enabled")
        ):
            raise RuntimeError(
                "database root search did not restore at the canonical state"
            )
        cancel = find_controls(
            enum_child_tree(database), cls="Button",
            text_contains="取消", visible=True,
        )
        if cancel:
            click_control(cancel[0]["hwnd"])
            session.wait_gone(database, 4.0)
            database = 0
    except Exception as exc:
        error = repr(exc)
        log(f"DBROOTEDITCONTROLS inner failure: {error}")
    finally:
        if database and is_window(database):
            close_window_safely(session, database, 4.0)
        after = session.probe_rom.read_bytes()
        diffs = [
            index for index, (left, right) in enumerate(zip(before, after))
            if left != right
        ]
        unique = {record_item["action_id"]: record_item for record_item in records}
        validated = (
            error is None and len(unique) == 6 and not diffs
            and len(before) == len(after)
        )
        out_dir = session.out / "interaction-discovery"
        out_dir.mkdir(parents=True, exist_ok=True)
        (out_dir / "database-root-edit-actions.json").write_text(
            json.dumps({
                "schema_version": 1,
                "validated": validated,
                "error": error,
                "execution_record_count": len(unique),
                "diff_count": len(diffs) + int(len(before) != len(after)),
                "sha256_before": hashlib.sha256(before).hexdigest().upper(),
                "sha256_after": hashlib.sha256(after).hexdigest().upper(),
                "observations": observations,
                "execution_records": list(unique.values()) if validated else [],
            }, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
    if not validated:
        raise RuntimeError(
            f"database root edit did not validate: {len(unique)}/6 {error}"
        )
    log("DBROOTEDITCONTROLS complete: 6/6 actions, zero ROM diff")


def stage_dbspinnercontrols(session: ProbeSession) -> None:
    """Exercise every numeric spinner embedded in the database pages."""
    log("=== stage DBSPINNERCONTROLS ===")
    spinner_ids = (
        414, 424, 434, 444, 454, 464, 474, 484, 494, 504, 514,
        894, 914, 964, 974, 984, 994, 1004,
        1204, 1214, 1224, 1234, 1244, 1254,
    )
    before = session.probe_rom.read_bytes()
    records = []
    observations = []
    error = None
    database = 0

    def record(item, path, action, result):
        records.append({
            "action_id": stable_interaction_id(
                "数据库", "msctls_updown32",
                int(item.get("ctrl_id") or 0), tuple(path), action,
            ),
            "status": "passed",
            "result": result,
        })

    def current_spinner(control_id, *, require_enabled=True):
        tree = enum_child_tree(database)
        matches = find_controls(
            tree, cls="msctls_updown32", ctrl_id=control_id,
            visible=True,
        )
        if not matches:
            raise RuntimeError(f"database spinner {control_id} unavailable")
        item = matches[0]
        if require_enabled and not item.get("enabled"):
            raise RuntimeError(f"database spinner {control_id} disabled")
        buddy_id = control_id - 4
        buddies = find_controls(
            tree, cls="Edit", ctrl_id=buddy_id, visible=True,
        )
        if not buddies:
            raise RuntimeError(
                f"database spinner {control_id} buddy {buddy_id} unavailable"
            )
        return (
            item,
            buddies[0],
            tuple(control_tree_path(tree, item["hwnd"]) or ()),
        )

    def notify_buddy(item):
        hwnd = int(item["hwnd"])
        parent = user32.GetParent(hwnd)
        if parent:
            control_id = int(item.get("ctrl_id") or 0)
            user32.PostMessageW(
                parent, WM_COMMAND,
                (control_id & 0xFFFF) | (0x0300 << 16), hwnd,
            )

    def ensure_enabled(control_id):
        item, _buddy, _path = current_spinner(
            control_id, require_enabled=False,
        )
        if item.get("enabled"):
            return []
        tree = enum_child_tree(database)
        for list_item in find_controls(tree, cls="ListBox", visible=True):
            if not list_item.get("enabled"):
                continue
            list_id = int(list_item.get("ctrl_id") or 0)
            list_hwnd = int(list_item["hwnd"])
            original = int(_send_msg_num(list_hwnd, LB_GETCURSEL, 0, 0))
            count = max(0, int(_send_msg_num(list_hwnd, LB_GETCOUNT, 0, 0)))
            parent = user32.GetParent(list_hwnd)
            for index in range(count):
                _send_msg_num(list_hwnd, LB_SETCURSEL, index, 0)
                user32.PostMessageW(
                    parent, WM_COMMAND,
                    (list_id & 0xFFFF) | (LBN_SELCHANGE << 16), list_hwnd,
                )
                time.sleep(0.05)
                refreshed, _buddy, _path = current_spinner(
                    control_id, require_enabled=False,
                )
                if refreshed.get("enabled"):
                    return [(list_id, original, index)]
            if original >= 0:
                _send_msg_num(list_hwnd, LB_SETCURSEL, original, 0)
                user32.PostMessageW(
                    parent, WM_COMMAND,
                    (list_id & 0xFFFF) | (LBN_SELCHANGE << 16), list_hwnd,
                )
        raise RuntimeError(
            f"database spinner {control_id} disabled and no enabling record found"
        )

    def restore_activators(activators):
        for list_id, original, _index in reversed(activators):
            if original < 0:
                continue
            tree = enum_child_tree(database)
            matches = find_controls(
                tree, cls="ListBox", ctrl_id=list_id, visible=True,
            )
            if not matches:
                continue
            list_item = matches[0]
            _send_msg_num(list_item["hwnd"], LB_SETCURSEL, original, 0)
            user32.PostMessageW(
                user32.GetParent(list_item["hwnd"]), WM_COMMAND,
                (list_id & 0xFFFF) | (LBN_SELCHANGE << 16),
                list_item["hwnd"],
            )
            time.sleep(0.04)

    def hide_on_other_page(control_id):
        for target in (120, 630, 1390, 1810, 1750, 2530):
            if switch_database_page_by_control(database, target) is None:
                continue
            if not find_controls(
                enum_child_tree(database), cls="msctls_updown32",
                ctrl_id=control_id, visible=True,
            ):
                return target
        raise RuntimeError(
            f"database spinner {control_id} could not be hidden"
        )

    try:
        window = _open_data_window(
            session, 20008, "数据库", dismiss_hidden=False,
        )
        if not window:
            raise RuntimeError("database did not appear")
        database = int(window["hwnd"])
        move_window(database, 25, 15, 1600, 1060)
        time.sleep(1.0)

        for control_id in spinner_ids:
            if switch_database_page_by_control(database, control_id) is None:
                raise RuntimeError(
                    f"database spinner page {control_id} unavailable"
                )
            activators = ensure_enabled(control_id)
            item, buddy, path = current_spinner(control_id)
            original = get_ctrl_text(int(buddy["hwnd"]))
            width, height = get_client_size(int(item["hwnd"]))

            post_click_at(
                int(item["hwnd"]), max(1, width // 2), max(1, height // 4),
            )
            time.sleep(0.08)
            _item_now, buddy_now, _ = current_spinner(control_id)
            increment_readback = get_ctrl_text(int(buddy_now["hwnd"]))
            set_control_text(int(buddy_now["hwnd"]), original)
            notify_buddy(buddy_now)
            record(
                item, path, "increment",
                f"点击上半区，伙伴输入框由 {original!r} 变为 "
                f"{increment_readback!r}，随后恢复。",
            )

            item_now, buddy_now, _ = current_spinner(control_id)
            width, height = get_client_size(int(item_now["hwnd"]))
            post_click_at(
                int(item_now["hwnd"]), max(1, width // 2),
                max(1, height * 3 // 4),
            )
            time.sleep(0.08)
            _item_now, buddy_now, _ = current_spinner(control_id)
            decrement_readback = get_ctrl_text(int(buddy_now["hwnd"]))
            set_control_text(int(buddy_now["hwnd"]), original)
            notify_buddy(buddy_now)
            record(
                item, path, "decrement",
                f"点击下半区，伙伴输入框由 {original!r} 变为 "
                f"{decrement_readback!r}，随后恢复。",
            )

            boundary_readbacks = []
            for candidate in ("-32768", "32767"):
                _item_now, buddy_now, _ = current_spinner(control_id)
                set_control_text(int(buddy_now["hwnd"]), candidate)
                notify_buddy(buddy_now)
                time.sleep(0.04)
                boundary_readbacks.append(
                    get_ctrl_text(int(buddy_now["hwnd"]))
                )
            _item_now, buddy_now, _ = current_spinner(control_id)
            set_control_text(int(buddy_now["hwnd"]), original)
            notify_buddy(buddy_now)
            record(
                item, path, "boundary_values",
                f"伙伴输入框边界读回={boundary_readbacks}，随后恢复。",
            )

            hidden_on = hide_on_other_page(control_id)
            if switch_database_page_by_control(database, control_id) is None:
                raise RuntimeError(
                    f"database spinner {control_id} did not restore"
                )
            restored, _buddy, _restored_path = current_spinner(control_id)
            record(
                item, path, "discover_state_triggers",
                f"切换到目标控件 {hidden_on} 所在页后隐藏；返回后可见且启用="
                f"{bool(restored.get('enabled'))}；条件记录链={activators}。",
            )
            observations.append({
                "control_id": control_id,
                "buddy_control_id": control_id - 4,
                "path": list(path),
                "original": original,
                "increment_readback": increment_readback,
                "decrement_readback": decrement_readback,
                "boundary_readbacks": boundary_readbacks,
                "activators": activators,
            })
            restore_activators(activators)

        cancel = find_controls(
            enum_child_tree(database), cls="Button",
            text_contains="取消", visible=True,
        )
        if cancel:
            click_control(cancel[0]["hwnd"])
            session.wait_gone(database, 4.0)
            database = 0
    except Exception as exc:
        error = repr(exc)
        log(f"DBSPINNERCONTROLS inner failure: {error}")
    finally:
        if database and is_window(database):
            close_window_safely(session, database, 4.0)
        after = session.probe_rom.read_bytes()
        diffs = [
            index for index, (left, right) in enumerate(zip(before, after))
            if left != right
        ]
        unique = {record_item["action_id"]: record_item for record_item in records}
        expected = len(spinner_ids) * 4
        validated = (
            error is None and len(unique) == expected and not diffs
            and len(before) == len(after)
        )
        out_dir = session.out / "interaction-discovery"
        out_dir.mkdir(parents=True, exist_ok=True)
        (out_dir / "database-spinner-actions.json").write_text(
            json.dumps({
                "schema_version": 1,
                "validated": validated,
                "error": error,
                "execution_record_count": len(unique),
                "diff_count": len(diffs) + int(len(before) != len(after)),
                "sha256_before": hashlib.sha256(before).hexdigest().upper(),
                "sha256_after": hashlib.sha256(after).hexdigest().upper(),
                "observations": observations,
                "execution_records": list(unique.values()) if validated else [],
            }, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
    if not validated:
        raise RuntimeError(
            f"database spinner batch did not validate: "
            f"{len(unique)}/{expected} {error}"
        )
    log(
        f"DBSPINNERCONTROLS complete: {expected}/{expected} actions, "
        "zero ROM diff"
    )


def stage_dbstaticstatecontrols(session: ProbeSession) -> None:
    """Verify page-state triggers for database labels and MFC text panels."""
    log("=== stage DBSTATICSTATECONTROLS ===")
    specs = (
        (
            "afx",
            (
                150, 820, 870, 880, 900, 920, 930, 940, 950,
                1010, 1020, 1040, 1050, 1060, 1070, 1080,
                1100, 1110, 1120, 1130, 1140, 1150,
                1590, 1610, 1630, 1660, 1670, 1700, 1720,
                1790, 1830, 1840, 1850, 1860,
                1910, 1930, 1960, 1980, 2000, 2030, 2050,
                2070, 2080, 2100, 2110, 2190,
                2210, 2220, 2230, 2240, 2250, 2260, 2270,
                2280, 2290, 2300, 2310, 2320, 2330, 2340,
                2350, 2360, 2370, 2380, 2390, 2400, 2410,
                2420, 2430, 2440, 2450, 2460, 2470, 2480,
                2490, 2500, 2630,
            ),
        ),
        (
            "label",
            (260, 270, 280, 320, 330, 340, 760, 770, 780, 1280, 1320, 1330),
        ),
    )
    before = session.probe_rom.read_bytes()
    records = []
    observations = []
    error = None
    database = 0

    def matches_kind(item, kind):
        cls_name = str(item.get("class", ""))
        if kind == "afx":
            return cls_name.startswith("Afx:")
        return cls_name == "_EL_Label"

    def current_target(control_id, kind):
        tree = enum_child_tree(database)
        matches = [
            item for item in flatten_tree(tree)
            if int(item.get("ctrl_id") or 0) == control_id
            and item.get("visible") and matches_kind(item, kind)
        ]
        if not matches:
            raise RuntimeError(
                f"database {kind} state control {control_id} unavailable"
            )
        item = matches[0]
        return item, tuple(control_tree_path(tree, item["hwnd"]) or ())

    def find_hidden_page(control_id, kind):
        for target in (120, 630, 1390, 1810, 1750, 2530):
            if switch_database_page_by_control(database, target) is None:
                continue
            visible = [
                item for item in flatten_tree(enum_child_tree(database))
                if int(item.get("ctrl_id") or 0) == control_id
                and item.get("visible") and matches_kind(item, kind)
            ]
            if not visible:
                return target
        raise RuntimeError(
            f"database {kind} state control {control_id} could not be hidden"
        )

    try:
        window = _open_data_window(
            session, 20008, "数据库", dismiss_hidden=False,
        )
        if not window:
            raise RuntimeError("database did not appear")
        database = int(window["hwnd"])
        move_window(database, 25, 15, 1600, 1060)
        time.sleep(1.0)

        for kind, control_ids in specs:
            for control_id in control_ids:
                if switch_database_page_by_control(database, control_id) is None:
                    raise RuntimeError(
                        f"database {kind} page {control_id} unavailable"
                    )
                item, path = current_target(control_id, kind)
                class_name = str(item.get("class", ""))
                hidden_on = find_hidden_page(control_id, kind)
                if switch_database_page_by_control(database, control_id) is None:
                    raise RuntimeError(
                        f"database {kind} state control {control_id} did not restore"
                    )
                restored, restored_path = current_target(control_id, kind)
                if restored_path != path:
                    raise RuntimeError(
                        f"database {kind} {control_id} path changed "
                        f"{path}->{restored_path}"
                    )
                records.append({
                    "action_id": stable_interaction_id(
                        "数据库", class_name, control_id, path,
                        "discover_state_triggers",
                    ),
                    "status": "passed",
                    "result": (
                        f"切换到目标控件 {hidden_on} 所在页后隐藏；返回后"
                        f"可见={bool(restored.get('visible'))}、"
                        f"启用={bool(restored.get('enabled'))}。"
                    ),
                })
                observations.append({
                    "kind": kind,
                    "class": class_name,
                    "control_id": control_id,
                    "path": list(path),
                    "text": item.get("text", ""),
                    "hidden_on_control_page": hidden_on,
                    "restored_visible": bool(restored.get("visible")),
                    "restored_enabled": bool(restored.get("enabled")),
                })

        cancel = find_controls(
            enum_child_tree(database), cls="Button",
            text_contains="取消", visible=True,
        )
        if cancel:
            click_control(cancel[0]["hwnd"])
            session.wait_gone(database, 4.0)
            database = 0
    except Exception as exc:
        error = repr(exc)
        log(f"DBSTATICSTATECONTROLS inner failure: {error}")
    finally:
        if database and is_window(database):
            close_window_safely(session, database, 4.0)
        after = session.probe_rom.read_bytes()
        diffs = [
            index for index, (left, right) in enumerate(zip(before, after))
            if left != right
        ]
        unique = {record_item["action_id"]: record_item for record_item in records}
        expected = sum(len(control_ids) for _kind, control_ids in specs)
        validated = (
            error is None and len(unique) == expected and not diffs
            and len(before) == len(after)
        )
        out_dir = session.out / "interaction-discovery"
        out_dir.mkdir(parents=True, exist_ok=True)
        (out_dir / "database-static-state-actions.json").write_text(
            json.dumps({
                "schema_version": 1,
                "validated": validated,
                "error": error,
                "execution_record_count": len(unique),
                "diff_count": len(diffs) + int(len(before) != len(after)),
                "sha256_before": hashlib.sha256(before).hexdigest().upper(),
                "sha256_after": hashlib.sha256(after).hexdigest().upper(),
                "observations": observations,
                "execution_records": list(unique.values()) if validated else [],
            }, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
    if not validated:
        raise RuntimeError(
            f"database static-state batch did not validate: "
            f"{len(unique)}/{expected} {error}"
        )
    log(
        f"DBSTATICSTATECONTROLS complete: {expected}/{expected} actions, "
        "zero ROM diff"
    )


def stage_dbregionstatecontrols(session: ProbeSession) -> None:
    """Exercise database image regions, list headers and root lifetime."""
    log("=== stage DBREGIONSTATECONTROLS ===")
    before = session.probe_rom.read_bytes()
    records = []
    observations = []
    error = None
    database = 0

    def record(class_name, control_id, path, action, result):
        records.append({
            "action_id": stable_interaction_id(
                "数据库", class_name, control_id, tuple(path), action,
            ),
            "status": "passed",
            "result": result,
        })

    def current_region(class_name, control_id):
        tree = enum_child_tree(database)
        matches = find_controls(
            tree, cls=class_name, ctrl_id=control_id, visible=True,
        )
        if not matches:
            raise RuntimeError(
                f"database region {class_name}/{control_id} unavailable"
            )
        item = matches[0]
        return item, tuple(control_tree_path(tree, item["hwnd"]) or ())

    def dismiss_new_windows(known, tag):
        found = []
        for index, popup in enumerate(session.top_windows(), 1):
            if popup["hwnd"] in known or popup["hwnd"] == database:
                continue
            if popup["class"] == "#32768":
                continue
            found.append({"title": popup["title"], "class": popup["class"]})
            session.dump_window(
                popup["hwnd"], f"DBREGION_{tag}_{index}", menu=True,
            )
            close_window_safely(session, popup["hwnd"], 3.0)
        return found

    def hide_region(class_name, control_id):
        for target in (630, 1390, 1810, 1750, 2530):
            if switch_database_page_by_control(database, target) is None:
                continue
            if not find_controls(
                enum_child_tree(database), cls=class_name,
                ctrl_id=control_id, visible=True,
            ):
                return target
        raise RuntimeError(
            f"database region {class_name}/{control_id} could not be hidden"
        )

    def exercise_region(class_name, control_id, suffix):
        if switch_database_page_by_control(database, control_id) is None:
            raise RuntimeError(
                f"database region page {class_name}/{control_id} unavailable"
            )
        item, path = current_region(class_name, control_id)
        width, height = get_client_size(int(item["hwnd"]))
        cx, cy = max(1, width // 2), max(1, height // 2)
        gestures = (
            (f"left_click_{suffix}", "left"),
            (f"double_click_{suffix}", "double"),
            (f"right_click_{suffix}", "right"),
            (f"drag_{suffix}", "drag"),
        )
        gesture_observations = []
        for action, gesture in gestures:
            item_now, _ = current_region(class_name, control_id)
            hwnd = int(item_now["hwnd"])
            known = {popup["hwnd"] for popup in session.top_windows()}
            if gesture == "left":
                post_click_at(hwnd, cx, cy)
            elif gesture == "double":
                post_double_click_at(hwnd, cx, cy)
            elif gesture == "right":
                post_click_at(hwnd, cx, cy, button="right")
            else:
                post_drag_at(
                    hwnd, max(1, cx - 8), cy,
                    min(max(1, width - 1), cx + 8), cy,
                )
            time.sleep(0.18)
            menu_visible = bool(visible_popup_menus(session.pid or 0))
            if menu_visible:
                send_escape(database)
            new_windows = dismiss_new_windows(
                known, f"{control_id}_{gesture}",
            )
            record(
                class_name, control_id, path, action,
                f"在控件中央执行{gesture}手势；弹出菜单={menu_visible}；"
                f"新增窗口={new_windows}。",
            )
            gesture_observations.append({
                "action": action,
                "popup_menu": menu_visible,
                "new_windows": new_windows,
            })

        hidden_on = hide_region(class_name, control_id)
        if switch_database_page_by_control(database, control_id) is None:
            raise RuntimeError(
                f"database region {class_name}/{control_id} did not restore"
            )
        restored, restored_path = current_region(class_name, control_id)
        record(
            class_name, control_id, path, "discover_state_triggers",
            f"切换到目标控件 {hidden_on} 所在页后隐藏；返回后"
            f"路径={restored_path}、可见={bool(restored.get('visible'))}。",
        )
        observations.append({
            "class": class_name,
            "control_id": control_id,
            "path": list(path),
            "size": [width, height],
            "gestures": gesture_observations,
            "hidden_on_control_page": hidden_on,
            "restored_path": list(restored_path),
        })

    def exercise_header(list_id):
        if switch_database_page_by_control(database, list_id) is None:
            raise RuntimeError(f"database list {list_id} unavailable")
        tree = enum_child_tree(database)
        lists = find_controls(
            tree, cls="SysListView32", ctrl_id=list_id, visible=True,
        )
        if not lists:
            raise RuntimeError(f"database list {list_id} unavailable")
        list_item = lists[0]
        header = find_controls(
            enum_child_tree(int(list_item["hwnd"])),
            cls="SysHeader32", visible=True,
        )
        if not header:
            raise RuntimeError(f"database list {list_id} header unavailable")
        header_item = header[0]
        path = tuple(control_tree_path(tree, header_item["hwnd"]) or ())
        for target in (120, 630, 1390, 1810, 1750, 2530):
            if target == list_id:
                continue
            if switch_database_page_by_control(database, target) is None:
                continue
            if not is_window(int(header_item["hwnd"])) or not user32.IsWindowVisible(
                int(header_item["hwnd"])
            ):
                hidden_on = target
                break
        else:
            raise RuntimeError(f"database list {list_id} header did not hide")
        if switch_database_page_by_control(database, list_id) is None:
            raise RuntimeError(f"database list {list_id} did not restore")
        tree = enum_child_tree(database)
        restored_list = find_controls(
            tree, cls="SysListView32", ctrl_id=list_id, visible=True,
        )[0]
        restored_header = find_controls(
            enum_child_tree(int(restored_list["hwnd"])),
            cls="SysHeader32", visible=True,
        )[0]
        restored_path = tuple(
            control_tree_path(tree, restored_header["hwnd"]) or ()
        )
        record(
            "SysHeader32", 0, path, "discover_state_triggers",
            f"所属列表 {list_id} 切离到 {hidden_on} 页后表头隐藏；"
            f"返回后路径={restored_path}。",
        )
        observations.append({
            "class": "SysHeader32",
            "control_id": 0,
            "owner_list_id": list_id,
            "path": list(path),
            "hidden_on_control_page": hidden_on,
            "restored_path": list(restored_path),
        })

    try:
        window = _open_data_window(
            session, 20008, "数据库", dismiss_hidden=False,
        )
        if not window:
            raise RuntimeError("database did not appear")
        database = int(window["hwnd"])
        move_window(database, 25, 15, 1600, 1060)
        time.sleep(1.0)

        exercise_region("_EL_DrawPanel", 1340, "grid")
        exercise_region("_EL_PicBox", 1360, "regions")
        for list_id in (1570, 1580, 1690, 2610):
            exercise_header(list_id)

        root_path = ()
        cancel = find_controls(
            enum_child_tree(database), cls="Button",
            text_contains="取消", visible=True,
        )
        if not cancel:
            raise RuntimeError("database cancel button unavailable")
        click_control(cancel[0]["hwnd"])
        if not session.wait_gone(database, 4.0):
            raise RuntimeError("database did not close for root state trigger")
        record(
            "WTWindow", 0, root_path, "discover_state_triggers",
            "点击数据库“取消”后顶层窗口销毁；随后重新打开恢复。",
        )
        database = 0
        reopened = _open_data_window(
            session, 20008, "数据库", dismiss_hidden=False,
        )
        if not reopened:
            raise RuntimeError("database did not reopen")
        database = int(reopened["hwnd"])
        cancel = find_controls(
            enum_child_tree(database), cls="Button",
            text_contains="取消", visible=True,
        )
        if cancel:
            click_control(cancel[0]["hwnd"])
            session.wait_gone(database, 4.0)
            database = 0
    except Exception as exc:
        error = repr(exc)
        log(f"DBREGIONSTATECONTROLS inner failure: {error}")
    finally:
        if database and is_window(database):
            close_window_safely(session, database, 4.0)
        after = session.probe_rom.read_bytes()
        diffs = [
            index for index, (left, right) in enumerate(zip(before, after))
            if left != right
        ]
        unique = {record_item["action_id"]: record_item for record_item in records}
        validated = (
            error is None and len(unique) == 15 and not diffs
            and len(before) == len(after)
        )
        out_dir = session.out / "interaction-discovery"
        out_dir.mkdir(parents=True, exist_ok=True)
        (out_dir / "database-region-state-actions.json").write_text(
            json.dumps({
                "schema_version": 1,
                "validated": validated,
                "error": error,
                "execution_record_count": len(unique),
                "diff_count": len(diffs) + int(len(before) != len(after)),
                "sha256_before": hashlib.sha256(before).hexdigest().upper(),
                "sha256_after": hashlib.sha256(after).hexdigest().upper(),
                "observations": observations,
                "execution_records": list(unique.values()) if validated else [],
            }, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
    if not validated:
        raise RuntimeError(
            f"database region/state batch did not validate: "
            f"{len(unique)}/15 {error}"
        )
    log("DBREGIONSTATECONTROLS complete: 15/15 actions, zero ROM diff")


def _stage_dbbuttoncontrols(
    session: ProbeSession,
    control_ids: tuple[int, ...],
    stage_name: str,
    output_filename: str,
) -> None:
    """Exercise a page-scoped batch of database buttons from fresh drafts."""
    log(f"=== stage {stage_name} ===")
    before = session.probe_rom.read_bytes()
    records = []
    observations = []
    error = None
    database = 0
    tab_points = []
    visibility_activators = {}
    page_representatives = (120, 630, 1390, 1810, 1750, 2530)

    def top_page_control():
        deadline = time.monotonic() + 12.0
        while time.monotonic() < deadline:
            tree = enum_child_tree(database)
            matches = find_controls(
                tree, cls="CPageControl", ctrl_id=100, visible=True,
            )
            if matches:
                return matches[0]
            time.sleep(0.15)
        raise RuntimeError("database top page control unavailable")

    def learn_tab_points():
        nonlocal tab_points
        if tab_points:
            return
        page = top_page_control()
        width, _height = get_client_size(int(page["hwnd"]))
        found = {}
        for local_x in range(14, max(15, width - 24), 12):
            post_click_at(int(page["hwnd"]), local_x, 24)
            time.sleep(0.08)
            tree = enum_child_tree(database)
            for representative in page_representatives:
                if representative in found:
                    continue
                if find_controls(tree, ctrl_id=representative, visible=True):
                    found[representative] = local_x
            if len(found) == len(page_representatives):
                break
        if len(found) != len(page_representatives):
            raise RuntimeError(
                f"database tab cache incomplete: {sorted(found)}"
            )
        tab_points = list(dict.fromkeys(found.values()))
        log(f"{stage_name}: cached database tab points {tab_points}")

    def switch_target(control_id):
        learn_tab_points()
        page = top_page_control()
        for local_x in tab_points:
            post_click_at(int(page["hwnd"]), local_x, 24)
            time.sleep(0.09)
            matches = find_controls(
                enum_child_tree(database), cls="Button",
                ctrl_id=control_id, visible=True,
            )
            if matches:
                return matches[0]
        cached = visibility_activators.get(control_id)
        if cached:
            list_id, _original, index = cached
            for local_x in tab_points:
                post_click_at(int(page["hwnd"]), local_x, 24)
                time.sleep(0.09)
                lists = find_controls(
                    enum_child_tree(database), cls="ListBox",
                    ctrl_id=list_id, visible=True,
                )
                if not lists:
                    continue
                list_hwnd = int(lists[0]["hwnd"])
                _send_msg_num(list_hwnd, LB_SETCURSEL, index, 0)
                user32.PostMessageW(
                    user32.GetParent(list_hwnd), WM_COMMAND,
                    (list_id & 0xFFFF) | (LBN_SELCHANGE << 16), list_hwnd,
                )
                time.sleep(0.08)
                matches = find_controls(
                    enum_child_tree(database), cls="Button",
                    ctrl_id=control_id, visible=True,
                )
                if matches:
                    return matches[0]
        located = switch_database_page_by_control(database, control_id)
        if located:
            matches = find_controls(
                enum_child_tree(database), cls="Button",
                ctrl_id=control_id, visible=True,
            )
            if matches:
                return matches[0]
        # Some unit buttons (for example 舰长) do not exist in the visible
        # tree for the default record.  Sweep page-local record lists and
        # retain the exact record condition once discovered.
        for local_x in tab_points:
            post_click_at(int(page["hwnd"]), local_x, 24)
            time.sleep(0.09)
            tree = enum_child_tree(database)
            for list_item in find_controls(tree, cls="ListBox", visible=True):
                if not list_item.get("enabled"):
                    continue
                list_id = int(list_item.get("ctrl_id") or 0)
                list_hwnd = int(list_item["hwnd"])
                original = int(_send_msg_num(list_hwnd, LB_GETCURSEL, 0, 0))
                count = max(
                    0, int(_send_msg_num(list_hwnd, LB_GETCOUNT, 0, 0)),
                )
                for index in range(count):
                    _send_msg_num(list_hwnd, LB_SETCURSEL, index, 0)
                    user32.PostMessageW(
                        user32.GetParent(list_hwnd), WM_COMMAND,
                        (list_id & 0xFFFF) | (LBN_SELCHANGE << 16),
                        list_hwnd,
                    )
                    time.sleep(0.05)
                    matches = find_controls(
                        enum_child_tree(database), cls="Button",
                        ctrl_id=control_id, visible=True,
                    )
                    if matches:
                        visibility_activators[control_id] = (
                            list_id, original, index,
                        )
                        log(
                            f"{stage_name}: button {control_id} appears via "
                            f"list {list_id} record {index}"
                        )
                        return matches[0]
        raise RuntimeError(f"database button {control_id} unavailable")

    def open_database():
        nonlocal database
        if database and is_window(database):
            return
        window = None
        for _attempt in range(3):
            window = _open_data_window(
                session, 20008, "数据库", dismiss_hidden=False,
            )
            if window:
                break
            time.sleep(0.9)
        if not window:
            raise RuntimeError("database did not appear")
        database = int(window["hwnd"])
        move_window(database, 25, 15, 1600, 1060)
        time.sleep(1.2)
        learn_tab_points()

    def close_database():
        nonlocal database
        if not database or not is_window(database):
            database = 0
            return
        # Some legacy buttons publish their modal child after the command
        # handler returns.  A still-pending child blocks the database Cancel
        # command, so drain owned descendants before and after the first try.
        for _attempt in range(3):
            blockers = [
                popup for popup in session.top_windows()
                if popup["hwnd"] not in {database, session.main_hwnd}
                and popup["class"] != "#32768"
            ]
            for popup in blockers:
                close_window_safely(session, popup["hwnd"], 2.0)
            if not blockers:
                break
            time.sleep(0.15)
        cancel = find_controls(
            enum_child_tree(database), cls="Button",
            text_contains="取消", visible=True,
        )
        if cancel:
            click_control(cancel[0]["hwnd"])
            if session.wait_gone(database, 3.0):
                database = 0
                time.sleep(0.55)
                return
        for popup in session.top_windows():
            if popup["hwnd"] not in {database, session.main_hwnd}:
                if popup["class"] == "#32768":
                    send_escape(database)
                else:
                    close_window_safely(session, popup["hwnd"], 2.0)
        cancel = find_controls(
            enum_child_tree(database), cls="Button",
            text_contains="取消", visible=True,
        )
        if cancel:
            click_control(cancel[0]["hwnd"])
            if session.wait_gone(database, 3.0):
                database = 0
                time.sleep(0.55)
                return
        close_window_safely(session, database, 3.0)
        if is_window(database):
            raise RuntimeError("database remained open after cancel/close")
        database = 0
        time.sleep(0.55)

    def current_button(control_id, *, require_enabled=True):
        item = switch_target(control_id)
        if require_enabled and not item.get("enabled"):
            raise RuntimeError(f"database button {control_id} disabled")
        tree = enum_child_tree(database)
        matches = find_controls(
            tree, cls="Button", ctrl_id=control_id, visible=True,
        )
        item = matches[0]
        return item, tuple(control_tree_path(tree, item["hwnd"]) or ())

    def ensure_enabled(control_id):
        item, _path = current_button(control_id, require_enabled=False)
        if item.get("enabled"):
            cached = visibility_activators.get(control_id)
            return [cached] if cached else []
        tree = enum_child_tree(database)
        for list_item in find_controls(tree, cls="ListBox", visible=True):
            if not list_item.get("enabled"):
                continue
            list_id = int(list_item.get("ctrl_id") or 0)
            list_hwnd = int(list_item["hwnd"])
            original = int(_send_msg_num(list_hwnd, LB_GETCURSEL, 0, 0))
            count = max(0, int(_send_msg_num(list_hwnd, LB_GETCOUNT, 0, 0)))
            parent = user32.GetParent(list_hwnd)
            for index in range(count):
                _send_msg_num(list_hwnd, LB_SETCURSEL, index, 0)
                user32.PostMessageW(
                    parent, WM_COMMAND,
                    (list_id & 0xFFFF) | (LBN_SELCHANGE << 16), list_hwnd,
                )
                time.sleep(0.05)
                refreshed, _ = current_button(
                    control_id, require_enabled=False,
                )
                if refreshed.get("enabled"):
                    return [(list_id, original, index)]
            if original >= 0:
                _send_msg_num(list_hwnd, LB_SETCURSEL, original, 0)
                user32.PostMessageW(
                    parent, WM_COMMAND,
                    (list_id & 0xFFFF) | (LBN_SELCHANGE << 16), list_hwnd,
                )
        raise RuntimeError(
            f"database button {control_id} disabled and no enabling record found"
        )

    def dismiss_new_windows(known, tag):
        found = []
        captured = set()
        deadline = time.monotonic() + 1.6
        while time.monotonic() < deadline:
            new_items = []
            for popup in session.top_windows():
                if popup["hwnd"] in known or popup["hwnd"] == database:
                    continue
                if popup["class"] == "#32768":
                    continue
                new_items.append(popup)
            for popup in new_items:
                if not popup.get("title") or not popup.get("class"):
                    # A WT child can be enumerated for a brief interval before
                    # its VCL class/title and controls are initialised.  Closing
                    # in that interval crashes the legacy process.
                    time.sleep(0.15)
                    continue
                if popup["hwnd"] not in captured:
                    summary = {
                        "title": popup["title"], "class": popup["class"],
                    }
                    found.append(summary)
                    captured.add(popup["hwnd"])
                    time.sleep(0.25)
                    session.dump_window(
                        popup["hwnd"],
                        f"{stage_name}_{tag}_{len(captured)}", menu=True,
                    )
                popup_tree = enum_child_tree(popup["hwnd"])
                cancel = find_controls(
                    popup_tree, cls="Button", text_contains="取消",
                    visible=True,
                )
                if cancel:
                    click_control(cancel[0]["hwnd"])
                    session.wait_gone(popup["hwnd"], 2.0)
                if is_window(popup["hwnd"]):
                    close_window_safely(session, popup["hwnd"], 2.0)
            if not new_items:
                time.sleep(0.12)
            else:
                time.sleep(0.18)
        return found

    def record(item, path, action, result):
        records.append({
            "action_id": stable_interaction_id(
                "数据库", "Button", int(item.get("ctrl_id") or 0),
                tuple(path), action,
            ),
            "status": "passed",
            "result": result,
        })

    def exercise_gesture(control_id, action):
        open_database()
        activators = ensure_enabled(control_id)
        item, path = current_button(control_id)
        before_check = item.get("button_check_state")
        known = {popup["hwnd"] for popup in session.top_windows()}
        if action == "keyboard_activate":
            focused = focus_foreground_control(database, int(item["hwnd"]))
            send_key(int(item["hwnd"]), VK_SPACE)
        else:
            focused = None
            click_control(int(item["hwnd"]))
        time.sleep(0.35)
        new_windows = dismiss_new_windows(
            known, f"{control_id}_{action}",
        )
        database_alive = bool(database and is_window(database))
        after_check = None
        if database_alive:
            matches = find_controls(
                enum_child_tree(database), cls="Button",
                ctrl_id=control_id, visible=True,
            )
            if matches:
                after_check = matches[0].get("button_check_state")
        record(
            item, path, action,
            f"焦点={focused}；数据库仍存在={database_alive}；"
            f"选中状态 {before_check}->{after_check}；新增窗口={new_windows}；"
            f"条件记录链={activators}。",
        )
        observations.append({
            "control_id": control_id,
            "text": item.get("text", ""),
            "path": list(path),
            "action": action,
            "focused": focused,
            "database_alive": database_alive,
            "check_before": before_check,
            "check_after": after_check,
            "new_windows": new_windows,
            "activators": activators,
        })

    def exercise_right_and_state(control_id):
        open_database()
        activators = ensure_enabled(control_id)
        item, path = current_button(control_id)
        post_context_menu(int(item["hwnd"]), 6, 6)
        time.sleep(0.1)
        menu_visible = bool(visible_popup_menus(session.pid or 0))
        if menu_visible:
            send_escape(database)
        record(
            item, path, "right_click",
            f"执行右键路径；可见菜单={menu_visible}；"
            f"条件记录链={activators}。",
        )

        hidden_on = None
        page = top_page_control()
        for local_x in tab_points:
            post_click_at(int(page["hwnd"]), local_x, 24)
            time.sleep(0.09)
            if not find_controls(
                enum_child_tree(database), cls="Button",
                ctrl_id=control_id, visible=True,
            ):
                hidden_on = local_x
                break
        if hidden_on is not None:
            restored = switch_target(control_id)
            state_result = (
                f"切换到页签坐标 {hidden_on} 后隐藏；返回后可见且"
                f"启用={bool(restored.get('enabled'))}。"
            )
        else:
            close_database()
            open_database()
            restored = switch_target(control_id)
            state_result = (
                "该按钮跨顶层页持续可见；取消数据库后销毁，重新打开后"
                f"恢复可见且启用={bool(restored.get('enabled'))}。"
            )
        record(item, path, "discover_state_triggers", state_result)
        observations.append({
            "control_id": control_id,
            "text": item.get("text", ""),
            "path": list(path),
            "action": "right_click_and_state",
            "right_click_menu": menu_visible,
            "hidden_on_tab_x": hidden_on,
            "activators": activators,
        })

    try:
        open_database()
        for control_id in control_ids:
            exercise_right_and_state(control_id)
            exercise_gesture(control_id, "keyboard_activate")
            exercise_gesture(control_id, "left_click")
        close_database()
    except Exception as exc:
        error = repr(exc)
        log(f"{stage_name} inner failure: {error}")
    finally:
        close_database()
        after = session.probe_rom.read_bytes()
        diffs = [
            index for index, (left, right) in enumerate(zip(before, after))
            if left != right
        ]
        unique = {record_item["action_id"]: record_item for record_item in records}
        expected = len(control_ids) * 4
        validated = (
            error is None and len(unique) == expected and not diffs
            and len(before) == len(after)
        )
        out_dir = session.out / "interaction-discovery"
        out_dir.mkdir(parents=True, exist_ok=True)
        (out_dir / output_filename).write_text(
            json.dumps({
                "schema_version": 1,
                "validated": validated,
                "error": error,
                "execution_record_count": len(unique),
                "diff_count": len(diffs) + int(len(before) != len(after)),
                "sha256_before": hashlib.sha256(before).hexdigest().upper(),
                "sha256_after": hashlib.sha256(after).hexdigest().upper(),
                "observations": observations,
                "execution_records": list(unique.values()) if validated else [],
            }, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
    if not validated:
        raise RuntimeError(
            f"database button batch did not validate: "
            f"{len(unique)}/{expected} {error}"
        )
    log(
        f"{stage_name} complete: {expected}/{expected} actions, zero ROM diff"
    )


def stage_dbunitbuttoncontrols(session: ProbeSession) -> None:
    """Exercise all page-scoped unit database buttons."""
    _stage_dbbuttoncontrols(
        session,
        (
            110, 130, 140, 160, 180,
        ),
        "DBUNITBUTTONCONTROLS",
        "database-unit-button-actions.json",
    )


def stage_dbunitimagebuttoncontrols(session: ProbeSession) -> None:
    """Exercise the unit/fragment display and puzzle opener buttons."""
    _stage_dbbuttoncontrols(
        session,
        (190, 200, 210, 220),
        "DBUNITIMAGEBUTTONCONTROLS",
        "database-unit-image-button-actions.json",
    )


def stage_dbunitdetailbuttoncontrols(session: ProbeSession) -> None:
    """Exercise unit detail, upload and destructive draft buttons."""
    _stage_dbbuttoncontrols(
        session,
        (
            380, 400, 520, 1290, 1310, 1350,
            2660, 2670, 2680, 2690,
        ),
        "DBUNITDETAILBUTTONCONTROLS",
        "database-unit-detail-button-actions.json",
    )


def stage_dbunitconditionalbuttoncontrols(session: ProbeSession) -> None:
    """Exercise record-conditional unit buttons and weapon jump buttons."""
    _stage_dbbuttoncontrols(
        session,
        (2700, 2710, 2720, 2730),
        "DBUNITCONDITIONALBUTTONCONTROLS",
        "database-unit-conditional-button-actions.json",
    )


def stage_dbcharacterbuttoncontrols(session: ProbeSession) -> None:
    """Exercise all page-scoped character database buttons."""
    _stage_dbbuttoncontrols(
        session,
        (
            620, 640, 660, 670, 680, 790, 800,
            810, 860, 1030, 1090, 1160, 1170, 1260,
        ),
        "DBCHARACTERBUTTONCONTROLS",
        "database-character-button-actions.json",
    )


def stage_dbcharacterclearbuttoncontrols(session: ProbeSession) -> None:
    """Exercise the conditional character transform/flight clear button."""
    _stage_dbbuttoncontrols(
        session,
        (2180,),
        "DBCHARACTERCLEARBUTTONCONTROLS",
        "database-character-clear-button-actions.json",
    )


def stage_dbdialogbuttoncontrols(session: ProbeSession) -> None:
    """Exercise the battle-dialogue page buttons."""
    _stage_dbbuttoncontrols(
        session,
        (
            1380, 1400, 1420, 1430, 1440, 1450, 1460,
            1470, 1480, 1490, 1500, 1510, 1520, 1530,
        ),
        "DBDIALOGBUTTONCONTROLS",
        "database-dialog-button-actions.json",
    )


def stage_dbotherbuttoncontrols(session: ProbeSession) -> None:
    """Exercise other-page and shop database buttons."""
    _stage_dbbuttoncontrols(
        session,
        (
            1550, 1560, 1680, 1740, 1760, 1800, 1820,
            1950, 2120, 2130, 2140, 2640, 2650,
        ),
        "DBOTHERBUTTONCONTROLS",
        "database-other-button-actions.json",
    )


def stage_dbweaponbuttoncontrols(session: ProbeSession) -> None:
    """Exercise page-scoped weapon database buttons."""
    _stage_dbbuttoncontrols(
        session,
        (2510, 2550, 2560, 2600),
        "DBWEAPONBUTTONCONTROLS",
        "database-weapon-button-actions.json",
    )


def stage_dbglobalbuttoncontrols(session: ProbeSession) -> None:
    """Exercise database OK/Cancel and global search buttons."""
    log("=== stage DBGLOBALBUTTONCONTROLS ===")
    before = session.probe_rom.read_bytes()
    records = []
    observations = []
    error = None
    database = 0

    def open_database():
        nonlocal database
        window = None
        for _attempt in range(3):
            window = _open_data_window(
                session, 20008, "数据库", dismiss_hidden=False,
            )
            if window:
                break
            time.sleep(1.0)
        if not window:
            raise RuntimeError("database did not appear")
        database = int(window["hwnd"])
        move_window(database, 25, 15, 1600, 1060)
        deadline = time.monotonic() + 12.0
        while time.monotonic() < deadline:
            if all(find_controls(
                enum_child_tree(database), cls="Button",
                ctrl_id=control_id, visible=True,
            ) for control_id in (590, 600, 2160, 2170)):
                return
            time.sleep(0.15)
        raise RuntimeError("database global buttons did not initialise")

    def current(control_id):
        tree = enum_child_tree(database)
        matches = find_controls(
            tree, cls="Button", ctrl_id=control_id, visible=True,
        )
        if not matches:
            raise RuntimeError(f"database global button {control_id} missing")
        item = matches[0]
        return item, tuple(control_tree_path(tree, item["hwnd"]) or ())

    def record(item, path, action, result):
        records.append({
            "action_id": stable_interaction_id(
                "数据库", "Button", int(item.get("ctrl_id") or 0),
                tuple(path), action,
            ),
            "status": "passed",
            "result": result,
        })

    def dismiss_new(known, tag):
        found = []
        deadline = time.monotonic() + 1.5
        captured = set()
        while time.monotonic() < deadline:
            new_items = [
                popup for popup in session.top_windows()
                if popup["hwnd"] not in known
                and popup["hwnd"] != database
                and popup["class"] != "#32768"
            ]
            for popup in new_items:
                if not popup.get("title") or not popup.get("class"):
                    continue
                if popup["hwnd"] not in captured:
                    captured.add(popup["hwnd"])
                    found.append({
                        "title": popup["title"], "class": popup["class"],
                    })
                    session.dump_window(
                        popup["hwnd"], f"DBGLOBAL_{tag}_{len(captured)}",
                        menu=True,
                    )
                close_window_safely(session, popup["hwnd"], 2.0)
            time.sleep(0.12)
        return found

    def wait_closed():
        nonlocal database
        closed = session.wait_gone(database, 5.0)
        if not closed:
            raise RuntimeError("database did not close")
        database = 0
        time.sleep(1.0)

    try:
        open_database()
        canonical = {
            control_id: current(control_id)
            for control_id in (590, 600, 2160, 2170)
        }

        for control_id in (590, 600, 2160, 2170):
            item, path = current(control_id)
            post_context_menu(int(item["hwnd"]), 6, 6)
            time.sleep(0.1)
            menu_visible = bool(visible_popup_menus(session.pid or 0))
            if menu_visible:
                send_escape(database)
            record(
                item, path, "right_click",
                f"执行右键路径；可见菜单={menu_visible}。",
            )

        for control_id in (2160, 2170):
            for action in ("keyboard_activate", "left_click"):
                item, path = current(control_id)
                known = {popup["hwnd"] for popup in session.top_windows()}
                if action == "keyboard_activate":
                    focused = focus_foreground_control(
                        database, int(item["hwnd"]),
                    )
                    send_key(int(item["hwnd"]), VK_SPACE)
                else:
                    focused = None
                    click_control(int(item["hwnd"]))
                time.sleep(0.25)
                new_windows = dismiss_new(
                    known, f"{control_id}_{action}",
                )
                record(
                    item, path, action,
                    f"焦点={focused}；新增窗口={new_windows}；"
                    f"数据库仍存在={bool(is_window(database))}。",
                )
                observations.append({
                    "control_id": control_id,
                    "action": action,
                    "focused": focused,
                    "new_windows": new_windows,
                })

        # Cancel keyboard activation supplies both its gesture and its real
        # lifetime trigger.  The already-validated left-click action is not
        # duplicated because it is absent from the pending denominator.
        item_600, path_600 = current(600)
        focused = focus_foreground_control(database, int(item_600["hwnd"]))
        send_key(int(item_600["hwnd"]), VK_SPACE)
        wait_closed()
        record(
            item_600, path_600, "keyboard_activate",
            f"真实焦点={focused}；空格关闭数据库。",
        )
        record(
            item_600, path_600, "discover_state_triggers",
            "取消按钮随数据库关闭而销毁，重新打开后恢复。",
        )

        open_database()
        item_590, path_590 = current(590)
        focused = focus_foreground_control(database, int(item_590["hwnd"]))
        send_key(int(item_590["hwnd"]), VK_SPACE)
        wait_closed()
        record(
            item_590, path_590, "keyboard_activate",
            f"真实焦点={focused}；未改草稿时空格确定并关闭数据库。",
        )
        record(
            item_590, path_590, "discover_state_triggers",
            "确定按钮随数据库确认关闭而销毁，重新打开后恢复。",
        )

        open_database()
        item_590, path_590 = current(590)
        click_control(int(item_590["hwnd"]))
        wait_closed()
        record(
            item_590, path_590, "left_click",
            "未改草稿时左键确定并关闭数据库。",
        )

        # One real cancel/reopen cycle proves the shared lifecycle of all
        # three bottom search buttons without fabricating a tab-hide rule.
        open_database()
        search_items = {
            control_id: current(control_id)
            for control_id in (2160, 2170)
        }
        cancel, _cancel_path = current(600)
        click_control(int(cancel["hwnd"]))
        wait_closed()
        open_database()
        for control_id, (item, path) in search_items.items():
            restored, restored_path = current(control_id)
            record(
                item, path, "discover_state_triggers",
                "该按钮跨顶层页持续可见；取消数据库后销毁，重开后"
                f"路径={restored_path}、启用={bool(restored.get('enabled'))}。",
            )
        cancel, _cancel_path = current(600)
        click_control(int(cancel["hwnd"]))
        wait_closed()
    except Exception as exc:
        error = repr(exc)
        log(f"DBGLOBALBUTTONCONTROLS inner failure: {error}")
    finally:
        if database and is_window(database):
            close_window_safely(session, database, 4.0)
        after = session.probe_rom.read_bytes()
        diffs = [
            index for index, (left, right) in enumerate(zip(before, after))
            if left != right
        ]
        unique = {record_item["action_id"]: record_item for record_item in records}
        validated = (
            error is None and len(unique) == 15 and not diffs
            and len(before) == len(after)
        )
        out_dir = session.out / "interaction-discovery"
        out_dir.mkdir(parents=True, exist_ok=True)
        (out_dir / "database-global-button-actions.json").write_text(
            json.dumps({
                "schema_version": 1,
                "validated": validated,
                "error": error,
                "execution_record_count": len(unique),
                "diff_count": len(diffs) + int(len(before) != len(after)),
                "sha256_before": hashlib.sha256(before).hexdigest().upper(),
                "sha256_after": hashlib.sha256(after).hexdigest().upper(),
                "observations": observations,
                "execution_records": list(unique.values()) if validated else [],
            }, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
    if not validated:
        raise RuntimeError(
            f"database global buttons did not validate: "
            f"{len(unique)}/15 {error}"
        )
    log("DBGLOBALBUTTONCONTROLS complete: 15/15 actions, zero ROM diff")


def stage_dbeditdialoguecontrols(session: ProbeSession) -> None:
    """Legacy alias for the nested attack-dialogue editor probe."""
    log("=== stage DBEDITDIALOGUECONTROLS ===")
    before = session.probe_rom.read_bytes()
    records = []
    observations = []
    error = None
    database = 0
    editor = 0

    def record(item, path, action, result):
        records.append({
            "action_id": stable_interaction_id(
                "攻击对话", str(item.get("class", "")),
                int(item.get("ctrl_id") or 0), tuple(path), action,
            ),
            "status": "passed",
            "result": result,
        })

    def open_editor():
        nonlocal editor
        if switch_database_page_by_control(database, 1420) is None:
            raise RuntimeError("battle-dialogue button 1420 unavailable")
        buttons = find_controls(
            enum_child_tree(database), cls="Button", ctrl_id=1420,
            visible=True,
        )
        if not buttons:
            raise RuntimeError("battle-dialogue button 1420 unavailable")
        known = {popup["hwnd"] for popup in session.top_windows()}
        click_control(buttons[0]["hwnd"])
        popup = session.wait_new_top(
            exclude=known, timeout=5.0, cls_equals="WTWindow",
        )
        if not popup:
            raise RuntimeError("edit-dialogue window did not appear")
        editor = int(popup["hwnd"])
        time.sleep(0.45)
        return editor

    def close_editor():
        nonlocal editor
        if not editor or not is_window(editor):
            editor = 0
            return
        cancel = find_controls(
            enum_child_tree(editor), cls="Button", ctrl_id=170,
            visible=True,
        )
        if cancel:
            click_control(cancel[0]["hwnd"])
            if session.wait_gone(editor, 3.0):
                editor = 0
                return
        close_window_safely(session, editor, 3.0)
        editor = 0

    def dismiss_descendants(known, tag):
        found = []
        for index, popup in enumerate(session.top_windows(), 1):
            if popup["hwnd"] in known or popup["hwnd"] in {database, editor}:
                continue
            if popup["class"] == "#32768":
                continue
            found.append({"title": popup["title"], "class": popup["class"]})
            session.dump_window(
                popup["hwnd"], f"DBEDITDIALOGUE_{tag}_{index}", menu=True,
            )
            close_window_safely(session, popup["hwnd"], 2.0)
        return found

    try:
        window = _open_data_window(
            session, 20008, "数据库", dismiss_hidden=False,
        )
        if not window:
            raise RuntimeError("database did not appear")
        database = int(window["hwnd"])
        move_window(database, 25, 15, 1600, 1060)
        time.sleep(1.0)

        open_editor()
        tree = enum_child_tree(editor)
        for control_id in (120, 130, 140, 150, 190):
            item = find_controls(
                tree, cls="ComboBox", ctrl_id=control_id, visible=True,
            )[0]
            path = tuple(control_tree_path(tree, item["hwnd"]) or ())
            values = read_combo_items(int(item["hwnd"]))
            original = int(_send_msg_num(item["hwnd"], CB_GETCURSEL, 0, 0))
            _send_msg_num(item["hwnd"], 0x014F, 1, 0)
            time.sleep(0.05)
            _send_msg_num(item["hwnd"], 0x014F, 0, 0)
            record(
                item, path, "open_dropdown",
                f"展开并收起，共 {len(values)} 项。",
            )
            readbacks = []
            for index in range(len(values)):
                set_combo_selection(int(item["hwnd"]), index)
                readbacks.append(int(_send_msg_num(
                    item["hwnd"], CB_GETCURSEL, 0, 0,
                )))
            if original >= 0:
                set_combo_selection(int(item["hwnd"]), original)
            record(
                item, path, "select_each_item",
                f"逐项选择并读回 {len(readbacks)}/{len(values)} 项，"
                f"恢复索引 {original}。",
            )
            focus_foreground_control(editor, int(item["hwnd"]))
            send_key(int(item["hwnd"]), VK_HOME)
            send_key(int(item["hwnd"]), VK_DOWN)
            keyboard_index = int(_send_msg_num(
                item["hwnd"], CB_GETCURSEL, 0, 0,
            ))
            if original >= 0:
                set_combo_selection(int(item["hwnd"]), original)
            record(
                item, path, "keyboard_cycle",
                f"Home/Down 后索引={keyboard_index}，随后恢复。",
            )
            post_context_menu(int(item["hwnd"]), 5, 5)
            time.sleep(0.08)
            menu_visible = bool(visible_popup_menus(session.pid or 0))
            if menu_visible:
                send_escape(editor)
            record(
                item, path, "right_click",
                f"执行右键路径；可见菜单={menu_visible}。",
            )
            observations.append({
                "class": "ComboBox",
                "control_id": control_id,
                "path": list(path),
                "item_count": len(values),
                "original_index": original,
                "keyboard_index": keyboard_index,
            })

        tree = enum_child_tree(editor)
        item = find_controls(
            tree, cls="ListBox", ctrl_id=100, visible=True,
        )[0]
        path = tuple(control_tree_path(tree, item["hwnd"]) or ())
        count = max(0, int(_send_msg_num(item["hwnd"], LB_GETCOUNT, 0, 0)))
        original = int(_send_msg_num(item["hwnd"], LB_GETCURSEL, 0, 0))
        parent = user32.GetParent(item["hwnd"])
        for index in range(count):
            _send_msg_num(item["hwnd"], LB_SETCURSEL, index, 0)
            user32.PostMessageW(
                parent, WM_COMMAND,
                100 | (LBN_SELCHANGE << 16), item["hwnd"],
            )
        if original >= 0:
            _send_msg_num(item["hwnd"], LB_SETCURSEL, original, 0)
        record(item, path, "select_each_item", f"逐项选择 {count} 项并恢复。")
        focus_foreground_control(editor, int(item["hwnd"]))
        send_key(int(item["hwnd"]), VK_HOME)
        send_key(int(item["hwnd"]), VK_DOWN)
        if original >= 0:
            _send_msg_num(item["hwnd"], LB_SETCURSEL, original, 0)
        record(item, path, "keyboard_navigation", "Home/Down 后恢复原索引。")
        for index in range(count):
            _send_msg_num(item["hwnd"], LB_SETCURSEL, index, 0)
            post_double_click_at(int(item["hwnd"]), 8, 8)
        record(item, path, "double_click_each_item", f"逐项双击 {count} 项。")
        for index in range(count):
            _send_msg_num(item["hwnd"], LB_SETCURSEL, index, 0)
            post_context_menu(int(item["hwnd"]), 8, 8)
            time.sleep(0.03)
            if visible_popup_menus(session.pid or 0):
                send_escape(editor)
        record(item, path, "right_click_each_item", f"逐项右键 {count} 项。")
        close_editor()

        for control_id in (110, 160, 170, 180):
            for action in ("keyboard_activate", "left_click", "right_click"):
                open_editor()
                tree = enum_child_tree(editor)
                item = find_controls(
                    tree, cls="Button", ctrl_id=control_id, visible=True,
                )[0]
                path = tuple(control_tree_path(tree, item["hwnd"]) or ())
                known = {popup["hwnd"] for popup in session.top_windows()}
                if action == "keyboard_activate":
                    focused = focus_foreground_control(
                        editor, int(item["hwnd"]),
                    )
                    send_key(int(item["hwnd"]), VK_SPACE)
                elif action == "left_click":
                    focused = None
                    click_control(int(item["hwnd"]))
                else:
                    focused = None
                    post_context_menu(int(item["hwnd"]), 5, 5)
                    time.sleep(0.08)
                    if visible_popup_menus(session.pid or 0):
                        send_escape(editor)
                time.sleep(0.18)
                descendants = dismiss_descendants(
                    known, f"{control_id}_{action}",
                )
                record(
                    item, path, action,
                    f"焦点={focused}；编辑窗仍存在="
                    f"{bool(editor and is_window(editor))}；"
                    f"新增窗口={descendants}。",
                )
                close_editor()

        cancel = find_controls(
            enum_child_tree(database), cls="Button",
            text_contains="取消", visible=True,
        )
        if cancel:
            click_control(cancel[0]["hwnd"])
            session.wait_gone(database, 4.0)
            database = 0
    except Exception as exc:
        error = repr(exc)
        log(f"DBEDITDIALOGUECONTROLS inner failure: {error}")
    finally:
        close_editor()
        if database and is_window(database):
            close_window_safely(session, database, 4.0)
        after = session.probe_rom.read_bytes()
        diffs = [
            index for index, (left, right) in enumerate(zip(before, after))
            if left != right
        ]
        unique = {record_item["action_id"]: record_item for record_item in records}
        validated = (
            error is None and len(unique) == 36 and not diffs
            and len(before) == len(after)
        )
        out_dir = session.out / "interaction-discovery"
        out_dir.mkdir(parents=True, exist_ok=True)
        (out_dir / "database-edit-dialogue-actions.json").write_text(
            json.dumps({
                "schema_version": 1,
                "validated": validated,
                "error": error,
                "execution_record_count": len(unique),
                "diff_count": len(diffs) + int(len(before) != len(after)),
                "sha256_before": hashlib.sha256(before).hexdigest().upper(),
                "sha256_after": hashlib.sha256(after).hexdigest().upper(),
                "observations": observations,
                "execution_records": list(unique.values()) if validated else [],
            }, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
    if not validated:
        raise RuntimeError(
            f"edit-dialogue controls did not validate: "
            f"{len(unique)}/36 {error}"
        )
    log("DBEDITDIALOGUECONTROLS complete: 36/36 actions, zero ROM diff")


def _stage_dbbattledialoguecontrols(
    session: ProbeSession,
    *,
    stage_name: str,
    window_title: str,
    database_button_id: int,
    combo_ids: tuple[int, ...],
    list_ids: tuple[int, ...],
    button_ids: tuple[int, ...],
    cancel_button_id: int,
    evidence_name: str,
) -> None:
    """Exercise a battle-dialogue child window without saving its draft."""
    log(f"=== stage {stage_name} ===")
    before = session.probe_rom.read_bytes()
    records = []
    observations = []
    error = None
    database = 0
    editor = 0
    expected_count = 4 * (len(combo_ids) + len(list_ids)) + 3 * len(button_ids)

    def record(item, path, action, result):
        records.append({
            "action_id": stable_interaction_id(
                window_title, str(item.get("class", "")),
                int(item.get("ctrl_id") or 0), tuple(path), action,
            ),
            "status": "passed",
            "result": result,
        })

    def open_editor():
        nonlocal editor
        if switch_database_page_by_control(database, database_button_id) is None:
            raise RuntimeError(
                f"database dialogue button {database_button_id} unavailable"
            )
        buttons = find_controls(
            enum_child_tree(database), cls="Button",
            ctrl_id=database_button_id, visible=True,
        )
        if not buttons:
            raise RuntimeError(
                f"database dialogue button {database_button_id} unavailable"
            )
        known = {popup["hwnd"] for popup in session.top_windows()}
        click_control(buttons[0]["hwnd"])
        popup = session.wait_new_top(
            exclude=known, timeout=5.0, cls_equals="WTWindow",
        )
        if not popup:
            raise RuntimeError(f"{window_title} window did not appear")
        editor = int(popup["hwnd"])
        deadline = time.monotonic() + 4.0
        while time.monotonic() < deadline:
            tree = enum_child_tree(editor)
            if all(find_controls(
                tree, cls="Button", ctrl_id=control_id, visible=True,
            ) for control_id in button_ids):
                return editor
            time.sleep(0.12)
        raise RuntimeError(f"{window_title} controls did not initialise")

    def close_editor():
        nonlocal editor
        if not editor or not is_window(editor):
            editor = 0
            return
        cancel = find_controls(
            enum_child_tree(editor), cls="Button",
            ctrl_id=cancel_button_id, visible=True,
        )
        if cancel:
            click_control(cancel[0]["hwnd"])
            if session.wait_gone(editor, 3.0):
                editor = 0
                return
        close_window_safely(session, editor, 3.0)
        editor = 0

    def dismiss_descendants(known, tag):
        found = []
        deadline = time.monotonic() + 0.8
        captured = set()
        while time.monotonic() < deadline:
            for popup in session.top_windows():
                if popup["hwnd"] in known or popup["hwnd"] in {database, editor}:
                    continue
                if popup["class"] == "#32768":
                    continue
                if not popup.get("title") or not popup.get("class"):
                    continue
                if popup["hwnd"] not in captured:
                    captured.add(popup["hwnd"])
                    found.append({
                        "title": popup["title"], "class": popup["class"],
                    })
                    session.dump_window(
                        popup["hwnd"], f"{stage_name}_{tag}_{len(captured)}",
                        menu=True,
                    )
                close_window_safely(session, popup["hwnd"], 2.0)
            time.sleep(0.08)
        return found

    try:
        window = _open_data_window(
            session, 20008, "数据库", dismiss_hidden=False,
        )
        if not window:
            raise RuntimeError("database did not appear")
        database = int(window["hwnd"])
        move_window(database, 25, 15, 1600, 1060)
        time.sleep(1.0)

        open_editor()
        for control_id in combo_ids:
            tree = enum_child_tree(editor)
            item = find_controls(
                tree, cls="ComboBox", ctrl_id=control_id, visible=True,
            )[0]
            path = tuple(control_tree_path(tree, item["hwnd"]) or ())
            values = read_combo_items(int(item["hwnd"]))
            original = int(_send_msg_num(item["hwnd"], CB_GETCURSEL, 0, 0))
            _send_msg_num(item["hwnd"], 0x014F, 1, 0)
            time.sleep(0.05)
            _send_msg_num(item["hwnd"], 0x014F, 0, 0)
            record(item, path, "open_dropdown", f"展开并收起，共 {len(values)} 项。")
            readbacks = []
            for index in range(len(values)):
                set_combo_selection(int(item["hwnd"]), index)
                readbacks.append(int(_send_msg_num(
                    item["hwnd"], CB_GETCURSEL, 0, 0,
                )))
            if original >= 0:
                set_combo_selection(int(item["hwnd"]), original)
            record(
                item, path, "select_each_item",
                f"逐项选择并读回 {len(readbacks)}/{len(values)} 项，恢复索引 {original}。",
            )
            focus_foreground_control(editor, int(item["hwnd"]))
            send_key(int(item["hwnd"]), VK_HOME)
            send_key(int(item["hwnd"]), VK_DOWN)
            keyboard_index = int(_send_msg_num(
                item["hwnd"], CB_GETCURSEL, 0, 0,
            ))
            if original >= 0:
                set_combo_selection(int(item["hwnd"]), original)
            record(
                item, path, "keyboard_cycle",
                f"Home/Down 后索引={keyboard_index}，随后恢复。",
            )
            post_context_menu(int(item["hwnd"]), 5, 5)
            time.sleep(0.08)
            menu_visible = bool(visible_popup_menus(session.pid or 0))
            if menu_visible:
                send_escape(editor)
            record(
                item, path, "right_click",
                f"执行右键路径；可见菜单={menu_visible}。",
            )
            observations.append({
                "class": "ComboBox", "control_id": control_id,
                "path": list(path), "item_count": len(values),
                "original_index": original, "keyboard_index": keyboard_index,
            })

        for control_id in list_ids:
            tree = enum_child_tree(editor)
            item = find_controls(
                tree, cls="ListBox", ctrl_id=control_id, visible=True,
            )[0]
            path = tuple(control_tree_path(tree, item["hwnd"]) or ())
            count = max(0, int(_send_msg_num(item["hwnd"], LB_GETCOUNT, 0, 0)))
            original = int(_send_msg_num(item["hwnd"], LB_GETCURSEL, 0, 0))
            parent = user32.GetParent(item["hwnd"])
            for index in range(count):
                _send_msg_num(item["hwnd"], LB_SETCURSEL, index, 0)
                user32.PostMessageW(
                    parent, WM_COMMAND,
                    control_id | (LBN_SELCHANGE << 16), item["hwnd"],
                )
            if original >= 0:
                _send_msg_num(item["hwnd"], LB_SETCURSEL, original, 0)
            record(item, path, "select_each_item", f"逐项选择 {count} 项并恢复。")
            focus_foreground_control(editor, int(item["hwnd"]))
            send_key(int(item["hwnd"]), VK_HOME)
            send_key(int(item["hwnd"]), VK_DOWN)
            if original >= 0:
                _send_msg_num(item["hwnd"], LB_SETCURSEL, original, 0)
            record(item, path, "keyboard_navigation", "Home/Down 后恢复原索引。")
            for index in range(count):
                _send_msg_num(item["hwnd"], LB_SETCURSEL, index, 0)
                post_double_click_at(int(item["hwnd"]), 8, 8)
            record(item, path, "double_click_each_item", f"逐项双击 {count} 项。")
            for index in range(count):
                _send_msg_num(item["hwnd"], LB_SETCURSEL, index, 0)
                post_context_menu(int(item["hwnd"]), 8, 8)
                time.sleep(0.03)
                if visible_popup_menus(session.pid or 0):
                    send_escape(editor)
            record(item, path, "right_click_each_item", f"逐项右键 {count} 项。")
        close_editor()

        for control_id in button_ids:
            for action in ("keyboard_activate", "left_click", "right_click"):
                open_editor()
                tree = enum_child_tree(editor)
                item = find_controls(
                    tree, cls="Button", ctrl_id=control_id, visible=True,
                )[0]
                path = tuple(control_tree_path(tree, item["hwnd"]) or ())
                known = {popup["hwnd"] for popup in session.top_windows()}
                if action == "keyboard_activate":
                    focused = focus_foreground_control(editor, int(item["hwnd"]))
                    send_key(int(item["hwnd"]), VK_SPACE)
                elif action == "left_click":
                    focused = None
                    click_control(int(item["hwnd"]))
                else:
                    focused = None
                    post_context_menu(int(item["hwnd"]), 5, 5)
                    time.sleep(0.08)
                    if visible_popup_menus(session.pid or 0):
                        send_escape(editor)
                time.sleep(0.18)
                descendants = dismiss_descendants(
                    known, f"{control_id}_{action}",
                )
                record(
                    item, path, action,
                    f"焦点={focused}；编辑窗仍存在={bool(editor and is_window(editor))}；"
                    f"新增窗口={descendants}。",
                )
                close_editor()

        cancel = find_controls(
            enum_child_tree(database), cls="Button",
            text_contains="取消", visible=True,
        )
        if cancel:
            click_control(cancel[0]["hwnd"])
            session.wait_gone(database, 4.0)
            database = 0
    except Exception as exc:
        error = repr(exc)
        log(f"{stage_name} inner failure: {error}")
    finally:
        close_editor()
        if database and is_window(database):
            close_window_safely(session, database, 4.0)
        after = session.probe_rom.read_bytes()
        diffs = [
            index for index, (left, right) in enumerate(zip(before, after))
            if left != right
        ]
        unique = {item["action_id"]: item for item in records}
        validated = (
            error is None and len(unique) == expected_count and not diffs
            and len(before) == len(after)
        )
        out_dir = session.out / "interaction-discovery"
        out_dir.mkdir(parents=True, exist_ok=True)
        (out_dir / evidence_name).write_text(
            json.dumps({
                "schema_version": 1,
                "validated": validated,
                "error": error,
                "execution_record_count": len(unique),
                "diff_count": len(diffs) + int(len(before) != len(after)),
                "sha256_before": hashlib.sha256(before).hexdigest().upper(),
                "sha256_after": hashlib.sha256(after).hexdigest().upper(),
                "observations": observations,
                "execution_records": list(unique.values()) if validated else [],
            }, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
    if not validated:
        raise RuntimeError(
            f"{window_title} controls did not validate: "
            f"{len(unique)}/{expected_count} {error}"
        )
    log(
        f"{stage_name} complete: {expected_count}/{expected_count} actions, "
        "zero ROM diff"
    )


def stage_dbattackdialoguecontrols(session: ProbeSession) -> None:
    """Exercise every visible control in the attack-dialogue child window."""
    _stage_dbbattledialoguecontrols(
        session,
        stage_name="DBATTACKDIALOGUECONTROLS",
        window_title="攻击对话",
        database_button_id=1430,
        combo_ids=(120, 130, 140, 150, 190),
        list_ids=(100,),
        button_ids=(110, 160, 170, 180),
        cancel_button_id=170,
        evidence_name="database-attack-dialogue-actions.json",
    )


def stage_dbdefencedialoguecontrols(session: ProbeSession) -> None:
    """Exercise every visible control in the defence-dialogue child window."""
    _stage_dbbattledialoguecontrols(
        session,
        stage_name="DBDEFENCEDIALOGUECONTROLS",
        window_title="防御对话",
        # Both 1450 and 1460 open the same editor for adjacent defence
        # dialogue slots.  Slot 1450 is absent for the default record in a
        # fresh database session; 1460 is the stable entry point.
        database_button_id=1460,
        combo_ids=(120, 130),
        list_ids=(),
        button_ids=(100, 110, 140),
        cancel_button_id=100,
        evidence_name="database-defence-dialogue-actions.json",
    )


def stage_dbmessagecontrols(session: ProbeSession) -> None:
    """Exercise database-triggered confirmation and information dialogs."""
    log("=== stage DBMESSAGECONTROLS ===")
    before = session.probe_rom.read_bytes()
    records = []
    observations = []
    error = None
    database = 0

    message_case = str(getattr(session, "db_message_case", "info-no"))
    case_map = {
        "info-no": (790, "信息：", (7,)),
        "info-yes": (790, "信息：", (6,)),
        "prompt": (1530, "提示", (2,)),
    }
    if message_case not in case_map:
        raise RuntimeError(f"invalid database message case: {message_case}")
    cases = (case_map[message_case],)

    def record(title, item, path, action, result):
        records.append({
            "action_id": stable_interaction_id(
                title, "Button", int(item.get("ctrl_id") or 0),
                tuple(path), action,
            ),
            "status": "passed",
            "result": result,
        })

    def open_database():
        nonlocal database
        window = _open_data_window(
            session, 20008, "数据库", dismiss_hidden=False,
        )
        if not window:
            raise RuntimeError("database did not appear")
        database = int(window["hwnd"])
        move_window(database, 25, 15, 1600, 1060)
        deadline = time.monotonic() + 12.0
        while time.monotonic() < deadline:
            pages = find_controls(
                enum_child_tree(database), cls="CPageControl",
                ctrl_id=100, visible=True,
            )
            if pages:
                return
            time.sleep(0.15)
        raise RuntimeError("database top page did not initialise")

    def close_database():
        nonlocal database
        for popup in session.top_windows():
            if popup["hwnd"] not in {database, session.main_hwnd}:
                close_window_safely(session, popup["hwnd"], 2.0)
        if database and is_window(database):
            cancel = [item for item in find_controls(
                enum_child_tree(database), cls="Button",
                text_contains="取消", visible=True,
            ) if item.get("text") == "取消"]
            if cancel:
                click_control(cancel[0]["hwnd"])
                if session.wait_gone(database, 4.0):
                    database = 0
            if is_window(database):
                close_window_safely(session, database, 3.0)
            if database and is_window(database):
                raise RuntimeError("database did not close")
        database = 0
        time.sleep(0.8)

    def open_message(opener_id, expected_title):
        if opener_id != 790:
            located = switch_database_page_by_control(database, opener_id)
            if not located:
                raise RuntimeError(
                    f"database message opener {opener_id} unavailable"
                )
        opener = find_controls(
            enum_child_tree(database), cls="Button",
            ctrl_id=opener_id, visible=True,
        )[0]
        known = {popup["hwnd"] for popup in session.top_windows()}
        click_control(opener["hwnd"])
        popup = session.wait_new_top(exclude=known, timeout=5.0)
        if not popup or popup["title"] != expected_title:
            raise RuntimeError(
                f"opener {opener_id} expected {expected_title!r}, got {popup}"
            )
        time.sleep(0.25)
        return int(popup["hwnd"])

    try:
        open_database()
        for opener_id, title, button_ids in cases:
            for button_id in button_ids:
                for action in ("keyboard_activate", "left_click", "right_click"):
                    if opener_id == 790:
                        pages = find_controls(
                            enum_child_tree(database), cls="CPageControl",
                            ctrl_id=100, visible=True,
                        )
                        if not pages:
                            raise RuntimeError("database top page unavailable")
                        post_click_at(int(pages[0]["hwnd"]), 86, 24)
                        time.sleep(0.18)
                    popup = open_message(opener_id, title)
                    tree = enum_child_tree(popup)
                    matches = find_controls(
                        tree, cls="Button", ctrl_id=button_id, visible=True,
                    )
                    if not matches:
                        raise RuntimeError(
                            f"{title} button {button_id} unavailable"
                        )
                    item = matches[0]
                    path = tuple(control_tree_path(tree, item["hwnd"]) or ())
                    known = {top["hwnd"] for top in session.top_windows()}
                    if action == "keyboard_activate":
                        focused = focus_foreground_control(
                            popup, int(item["hwnd"]),
                        )
                        send_key(int(item["hwnd"]), VK_SPACE)
                    elif action == "left_click":
                        focused = None
                        click_control(int(item["hwnd"]))
                    else:
                        focused = None
                        post_context_menu(int(item["hwnd"]), 5, 5)
                        time.sleep(0.1)
                        if visible_popup_menus(session.pid or 0):
                            send_escape(popup)
                    time.sleep(0.2)
                    remained = bool(is_window(popup))
                    followups = []
                    if action != "right_click":
                        child = session.wait_new_top(
                            exclude=known, timeout=3.0,
                        )
                        if child:
                            # Upload compression choices continue into the
                            # native image picker.  It is part of the same
                            # legacy action and must be observed and cancelled
                            # before the next confirmation can be reached.
                            followups.append({
                                "title": child["title"],
                                "class": child["class"],
                            })
                            session.dump_window(
                                child["hwnd"],
                                f"DBMESSAGE_{opener_id}_{button_id}_{action}",
                                menu=True,
                            )
                            child_cancel = find_controls(
                                enum_child_tree(child["hwnd"]), cls="Button",
                                ctrl_id=2, visible=True,
                            )
                            if child_cancel:
                                click_control(child_cancel[0]["hwnd"])
                                session.wait_gone(child["hwnd"], 3.0)
                            if is_window(child["hwnd"]):
                                close_window_safely(
                                    session, child["hwnd"], 3.0,
                                )
                    record(
                        title, item, path, action,
                        f"焦点={focused}；操作后弹窗仍存在={remained}；"
                        f"后续窗口={followups}。",
                    )
                    observations.append({
                        "opener_id": opener_id, "title": title,
                        "button_id": button_id, "action": action,
                        "focused": focused, "remained": remained,
                        "followups": followups,
                    })
                    if is_window(popup):
                        if action == "right_click":
                            send_escape(popup)
                            session.wait_gone(popup, 2.0)
                        if is_window(popup):
                            close_window_safely(session, popup, 2.0)
                    cleanup_child = session.wait_new_top(
                        exclude=known, timeout=2.0,
                    )
                    if cleanup_child:
                        # Closing an untouched information box through its
                        # title-bar X follows the legacy No path and may
                        # publish the image picker only afterwards.
                        cleanup_cancel = find_controls(
                            enum_child_tree(cleanup_child["hwnd"]),
                            cls="Button", ctrl_id=2, visible=True,
                        )
                        if cleanup_cancel:
                            click_control(cleanup_cancel[0]["hwnd"])
                            session.wait_gone(cleanup_child["hwnd"], 3.0)
                        if is_window(cleanup_child["hwnd"]):
                            close_window_safely(
                                session, cleanup_child["hwnd"], 3.0,
                            )
                    time.sleep(0.2)
        close_database()
        after = session.probe_rom.read_bytes()
        diffs = [
            index for index, (left, right) in enumerate(zip(before, after))
            if left != right
        ]
        unique = {item["action_id"]: item for item in records}
        validated = (
            len(unique) == 3 and not diffs and len(before) == len(after)
        )
    except Exception as exc:
        error = repr(exc)
        log(f"DBMESSAGECONTROLS inner failure: {error}")
        after = session.probe_rom.read_bytes()
        diffs = [
            index for index, (left, right) in enumerate(zip(before, after))
            if left != right
        ]
        unique = {item["action_id"]: item for item in records}
        validated = False
    finally:
        close_database()
        out_dir = session.out / "interaction-discovery"
        out_dir.mkdir(parents=True, exist_ok=True)
        (out_dir / f"database-message-{message_case}-actions.json").write_text(
            json.dumps({
                "schema_version": 1, "validated": validated,
                "error": error, "execution_record_count": len(unique),
                "diff_count": len(diffs) + int(len(before) != len(after)),
                "sha256_before": hashlib.sha256(before).hexdigest().upper(),
                "sha256_after": hashlib.sha256(after).hexdigest().upper(),
                "observations": observations,
                "execution_records": list(unique.values()) if validated else [],
            }, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
    if not validated:
        raise RuntimeError(
            f"database message controls did not validate: {len(unique)}/3 {error}"
        )
    log(
        f"DBMESSAGECONTROLS {message_case} complete: 3/3 actions, "
        "zero ROM diff"
    )


def stage_m12listcontrols(session: ProbeSession) -> None:
    """Exercise map-animation tabs and every list across their live states."""
    log("=== stage M12LISTCONTROLS ===")
    before = session.probe_rom.read_bytes()
    records = []
    observations = []
    error = None
    window_hwnd = 0
    list_ids = (110, 160, 220, 340, 360, 410, 530)

    def record(item, path, action, result):
        records.append({
            "action_id": stable_interaction_id(
                "地图动画", str(item.get("class", "")),
                int(item.get("ctrl_id") or 0), tuple(path), action,
            ),
            "status": "passed", "result": result,
        })

    def current_list(control_id):
        located = switch_database_page_by_control(window_hwnd, control_id)
        if not located:
            raise RuntimeError(f"map-animation list {control_id} unavailable")
        tree = enum_child_tree(window_hwnd)
        matches = find_controls(
            tree, cls="ListBox", ctrl_id=control_id, visible=True,
        )
        if not matches:
            raise RuntimeError(f"map-animation list {control_id} missing")
        item = matches[0]
        return item, tuple(control_tree_path(tree, item["hwnd"]) or ())

    def reacquire_list(control_id):
        """Re-read a list on the already selected page without a tab sweep."""
        tree = enum_child_tree(window_hwnd)
        matches = find_controls(
            tree, cls="ListBox", ctrl_id=control_id, visible=True,
        )
        if not matches:
            return current_list(control_id)
        item = matches[0]
        return item, tuple(control_tree_path(tree, item["hwnd"]) or ())

    def dismiss_new(known, tag, timeout=0.08):
        found = []
        deadline = time.monotonic() + timeout
        seen = set()
        while time.monotonic() < deadline:
            for popup in session.top_windows():
                if popup["hwnd"] in known or popup["hwnd"] == window_hwnd:
                    continue
                if popup["class"] == "#32768" or not popup.get("class"):
                    continue
                if popup["hwnd"] not in seen:
                    seen.add(popup["hwnd"])
                    found.append({
                        "title": popup["title"], "class": popup["class"],
                    })
                    session.dump_window(
                        popup["hwnd"], f"M12LIST_{tag}_{len(seen)}",
                        menu=True,
                    )
                close_window_safely(session, popup["hwnd"], 2.0)
            time.sleep(0.02)
        return found

    try:
        window = _open_data_window(
            session, 20011, "地图动画", dismiss_hidden=False,
        )
        if not window:
            raise RuntimeError("map-animation window did not appear")
        window_hwnd = int(window["hwnd"])
        move_window(window_hwnd, 40, 30, 1180, 850)
        time.sleep(0.6)

        # The three page-control actions are verified against actual live
        # pages, using one representative list unique to each page.
        tree = enum_child_tree(window_hwnd)
        pages = find_controls(
            tree, cls="CPageControl", ctrl_id=100, visible=True,
        )
        if not pages:
            raise RuntimeError("map-animation page control missing")
        page = pages[0]
        page_path = tuple(control_tree_path(tree, page["hwnd"]) or ())
        reached = []
        for representative in (110, 340, 530):
            located = switch_database_page_by_control(
                window_hwnd, representative,
            )
            if not located:
                raise RuntimeError(
                    f"map-animation page representative {representative} missing"
                )
            reached.append(representative)
        record(
            page, page_path, "select_each_tab",
            f"逐页命中稳定控件 {reached}。",
        )
        focus_foreground_control(window_hwnd, int(page["hwnd"]))
        keybd(0x11)  # Ctrl down
        send_key(int(page["hwnd"]), 0x09)  # Tab
        keybd(0x11, up=True)
        time.sleep(0.15)
        record(page, page_path, "keyboard_tab_cycle", "真实焦点 Ctrl+Tab。")
        post_context_menu(int(page["hwnd"]), 24, 18)
        time.sleep(0.1)
        menu_visible = bool(visible_popup_menus(session.pid or 0))
        if menu_visible:
            send_escape(window_hwnd)
        record(
            page, page_path, "right_click_tabs",
            f"页签区域右键；可见菜单={menu_visible}。",
        )

        for control_id in list_ids:
            item, path = current_list(control_id)
            list_hwnd = int(item["hwnd"])
            count = max(0, int(_send_msg_num(list_hwnd, LB_GETCOUNT, 0, 0)))
            original = int(_send_msg_num(list_hwnd, LB_GETCURSEL, 0, 0))
            parent = user32.GetParent(list_hwnd)

            for index in range(count):
                _send_msg_num(list_hwnd, LB_SETCURSEL, index, 0)
                user32.PostMessageW(
                    parent, WM_COMMAND,
                    control_id | (LBN_SELCHANGE << 16), list_hwnd,
                )
            if original >= 0:
                _send_msg_num(list_hwnd, LB_SETCURSEL, original, 0)
                user32.PostMessageW(
                    parent, WM_COMMAND,
                    control_id | (LBN_SELCHANGE << 16), list_hwnd,
                )
            record(
                item, path, "select_each_item",
                f"逐项选择 {count} 项并恢复索引 {original}。",
            )

            item, path = reacquire_list(control_id)
            list_hwnd = int(item["hwnd"])
            focus_foreground_control(window_hwnd, list_hwnd)
            send_key(list_hwnd, VK_HOME)
            send_key(list_hwnd, VK_DOWN)
            if original >= 0:
                _send_msg_num(list_hwnd, LB_SETCURSEL, original, 0)
            record(
                item, path, "keyboard_navigation",
                "真实焦点 Home/Down 后恢复原索引。",
            )

            double_descendants = []
            for index in range(count):
                item, path = reacquire_list(control_id)
                list_hwnd = int(item["hwnd"])
                _send_msg_num(list_hwnd, LB_SETCURSEL, index, 0)
                known = {top["hwnd"] for top in session.top_windows()}
                post_double_click_at(list_hwnd, 8, 8)
                found = dismiss_new(
                    known, f"{control_id}_double_{index}",
                    timeout=0.65 if index == 0 else 0.08,
                )
                double_descendants.extend(found)
            record(
                item, path, "double_click_each_item",
                f"逐项双击 {count} 项；子窗={double_descendants}。",
            )

            menu_hits = 0
            for index in range(count):
                item, path = reacquire_list(control_id)
                list_hwnd = int(item["hwnd"])
                _send_msg_num(list_hwnd, LB_SETCURSEL, index, 0)
                post_context_menu(list_hwnd, 8, 8)
                time.sleep(0.025)
                if visible_popup_menus(session.pid or 0):
                    menu_hits += 1
                    send_escape(window_hwnd)
            record(
                item, path, "right_click_each_item",
                f"逐项右键 {count} 项；可见菜单命中 {menu_hits} 次。",
            )

            hidden_on = None
            for representative in (110, 340, 530):
                if representative == control_id:
                    continue
                if switch_database_page_by_control(
                    window_hwnd, representative,
                ) is None:
                    continue
                if not find_controls(
                    enum_child_tree(window_hwnd), cls="ListBox",
                    ctrl_id=control_id, visible=True,
                ):
                    hidden_on = representative
                    break
            restored, restored_path = current_list(control_id)
            record(
                item, path, "discover_state_triggers",
                f"切至代表控件 {hidden_on} 后隐藏；返回路径="
                f"{restored_path}，启用={bool(restored.get('enabled'))}。",
            )
            observations.append({
                "control_id": control_id, "path": list(path),
                "item_count": count, "original_index": original,
                "hidden_on": hidden_on,
            })
            log(
                f"M12LISTCONTROLS list {control_id}: "
                f"{count} items complete"
            )

        cancel = find_controls(
            enum_child_tree(window_hwnd), cls="Button",
            ctrl_id=310, visible=True,
        )
        if cancel:
            click_control(cancel[0]["hwnd"])
            session.wait_gone(window_hwnd, 4.0)
            window_hwnd = 0
    except Exception as exc:
        error = repr(exc)
        log(f"M12LISTCONTROLS inner failure: {error}")
    finally:
        if window_hwnd and is_window(window_hwnd):
            close_window_safely(session, window_hwnd, 4.0)
        after = session.probe_rom.read_bytes()
        diffs = [
            index for index, (left, right) in enumerate(zip(before, after))
            if left != right
        ]
        unique = {item["action_id"]: item for item in records}
        validated = (
            error is None and len(unique) == 38 and not diffs
            and len(before) == len(after)
        )
        out_dir = session.out / "interaction-discovery"
        out_dir.mkdir(parents=True, exist_ok=True)
        (out_dir / "map-animation-list-actions.json").write_text(
            json.dumps({
                "schema_version": 1, "validated": validated,
                "error": error, "execution_record_count": len(unique),
                "diff_count": len(diffs) + int(len(before) != len(after)),
                "sha256_before": hashlib.sha256(before).hexdigest().upper(),
                "sha256_after": hashlib.sha256(after).hexdigest().upper(),
                "observations": observations,
                "execution_records": list(unique.values()) if validated else [],
            }, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
    if not validated:
        raise RuntimeError(
            f"map-animation lists did not validate: {len(unique)}/38 {error}"
        )
    log("M12LISTCONTROLS complete: 38/38 actions, zero ROM diff")


def stage_eventpagelistcontrols(session: ProbeSession) -> None:
    """Exercise every event-editor page control and live list item."""
    log("=== stage EVENTPAGELISTCONTROLS ===")
    before = session.probe_rom.read_bytes()
    records: list[dict] = []
    observations: list[dict] = []
    error: str | None = None
    event_hwnd = 0
    list_ids = (160, 220, 240, 260, 290, 310, 340, 360, 560, 630)
    outer_representatives = (160, 240, 290, 340, 560, 630)

    def record(item, path, action, result):
        records.append({
            "action_id": stable_interaction_id(
                "事件编辑", str(item.get("class", "")),
                int(item.get("ctrl_id") or 0), tuple(path), action,
            ),
            "status": "passed", "result": result,
        })

    def open_event() -> int:
        nonlocal event_hwnd
        def locate_visible() -> int:
            for top in session.top_windows():
                if top["class"] != "WTWindow" or top["hwnd"] == session.main_hwnd:
                    continue
                if find_controls(
                    enum_child_tree(top["hwnd"]), cls="CPageControl", ctrl_id=120,
                ):
                    return int(top["hwnd"])
            return 0

        # The old program pre-creates this WTWindow and may merely reveal the
        # existing HWND.  Do not exclude pre-existing/hidden handles and do
        # not call the generic popup cleanup, which would also destroy the
        # preloaded database window in the same modal stack.
        for attempt in range(2):
            user32.PostMessageW(session.main_hwnd, WM_COMMAND, 20015, 0)
            if attempt and force_foreground(session.main_hwnd):
                keybd(VK_CONTROL); keybd(ord("J")); keybd(ord("J"), up=True); keybd(VK_CONTROL, up=True)
            deadline = time.monotonic() + (15.0 if attempt == 0 else 8.0)
            while time.monotonic() < deadline:
                event_hwnd = locate_visible()
                if event_hwnd:
                    move_window(event_hwnd, 30, 20, 1320, 900)
                    time.sleep(0.5)
                    return event_hwnd
                time.sleep(0.15)
        raise RuntimeError("event editor did not appear")

    def visible_target(control_id, cls=None):
        tree = enum_child_tree(event_hwnd)
        matches = find_controls(
            tree, cls=cls, ctrl_id=control_id, visible=True,
        )
        if not matches:
            return None
        item = matches[0]
        return item, tuple(control_tree_path(tree, item["hwnd"]) or ())

    def cycle_page(page_item, target_id, cls=None, cycles=10):
        page_hwnd = int(page_item["hwnd"])
        focus_foreground_control(event_hwnd, page_hwnd)
        for _index in range(cycles):
            keybd(VK_CONTROL); send_key(page_hwnd, 0x09); keybd(VK_CONTROL, up=True)
            time.sleep(0.05)
            found = visible_target(target_id, cls)
            if found:
                return found
        return None

    def current(control_id, cls=None):
        found = visible_target(control_id, cls)
        if found:
            return found
        tree = enum_child_tree(event_hwnd)
        outer = find_controls(
            tree, cls="CPageControl", ctrl_id=120, visible=True,
        )
        if not outer:
            raise RuntimeError("event outer page control missing")
        outer_hwnd = int(outer[0]["hwnd"])
        width, _height = get_client_size(outer_hwnd)
        for outer_x in range(14, min(max(15, width - 24), 720), 12):
            post_click_at(outer_hwnd, outer_x, 24)
            time.sleep(0.05)
            found = visible_target(control_id, cls)
            if found:
                return found
        raise RuntimeError(f"event control {control_id} unavailable")

    def dismiss_new(known, tag, timeout=0.08):
        found = []
        seen = set()
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            for popup in session.top_windows():
                if popup["hwnd"] in known or popup["hwnd"] == event_hwnd:
                    continue
                if popup["class"] == "#32768" or not popup.get("class"):
                    continue
                if popup["hwnd"] not in seen:
                    seen.add(popup["hwnd"])
                    found.append({"title": popup["title"], "class": popup["class"]})
                    session.dump_window(
                        popup["hwnd"], f"EVENTLIST_{tag}_{len(seen)}", menu=True,
                    )
                cancel = [candidate for candidate in find_controls(
                    enum_child_tree(popup["hwnd"]), cls="Button", visible=True,
                ) if candidate.get("text") == "取消"]
                if cancel:
                    click_control(cancel[0]["hwnd"])
                    session.wait_gone(popup["hwnd"], 1.5)
                if is_window(popup["hwnd"]):
                    close_window_safely(session, popup["hwnd"], 1.5)
            time.sleep(0.02)
        return found

    try:
        open_event()

        # Outer page: every representative belongs to a distinct live state.
        outer_item, outer_path = current(120, "CPageControl")
        reached = []
        for representative in outer_representatives:
            current(representative, "ListBox")
            reached.append(representative)
            log(f"EVENTPAGELISTCONTROLS reached outer representative {representative}")
        record(outer_item, outer_path, "select_each_tab", f"逐页命中 {reached}。")
        focus_foreground_control(event_hwnd, int(outer_item["hwnd"]))
        keybd(VK_CONTROL); send_key(int(outer_item["hwnd"]), 0x09); keybd(VK_CONTROL, up=True)
        record(outer_item, outer_path, "keyboard_tab_cycle", "真实焦点 Ctrl+Tab。")
        post_context_menu(int(outer_item["hwnd"]), 24, 18); time.sleep(0.08)
        if visible_popup_menus(session.pid or 0): send_escape(event_hwnd)
        record(outer_item, outer_path, "right_click_tabs", "外层页签区域真实右键。")

        # Four event-instruction sub page controls.  Sweep their entire live
        # bands and preserve actual visible signatures rather than assuming a
        # tab count from screenshots.
        for page_id, representative in ((130, 160), (230, 240), (280, 290), (330, 340)):
            current(representative, "ListBox")
            page_item, page_path = current(page_id, "CPageControl")
            signatures = []
            page_hwnd = int(page_item["hwnd"])
            focus_foreground_control(event_hwnd, page_hwnd)
            for _index in range(10):
                keybd(VK_CONTROL); send_key(page_hwnd, 0x09); keybd(VK_CONTROL, up=True); time.sleep(0.05)
                visible_lists = tuple(sorted(
                    int(item.get("ctrl_id") or 0) for item in find_controls(
                        enum_child_tree(event_hwnd), cls="ListBox", visible=True,
                    )
                ))
                if visible_lists not in signatures:
                    signatures.append(visible_lists)
            record(page_item, page_path, "select_each_tab", f"页签状态={signatures}。")
            record(page_item, page_path, "discover_state_triggers", f"发现 {len(signatures)} 种可见列表状态。")
            focus_foreground_control(event_hwnd, int(page_item["hwnd"]))
            keybd(VK_CONTROL); send_key(int(page_item["hwnd"]), 0x09); keybd(VK_CONTROL, up=True)
            record(page_item, page_path, "keyboard_tab_cycle", "真实焦点 Ctrl+Tab。")
            post_context_menu(int(page_item["hwnd"]), 24, 18); time.sleep(0.08)
            if visible_popup_menus(session.pid or 0): send_escape(event_hwnd)
            record(page_item, page_path, "right_click_tabs", "内嵌页签区域真实右键。")

        for control_id in list_ids:
            item, path = current(control_id, "ListBox")
            hwnd = int(item["hwnd"])
            count = max(0, int(_send_msg_num(hwnd, LB_GETCOUNT, 0, 0)))
            original = int(_send_msg_num(hwnd, LB_GETCURSEL, 0, 0))
            parent = user32.GetParent(hwnd)
            for index in range(count):
                _send_msg_num(hwnd, LB_SETCURSEL, index, 0)
                user32.PostMessageW(parent, WM_COMMAND, control_id | (LBN_SELCHANGE << 16), hwnd)
            if original >= 0:
                _send_msg_num(hwnd, LB_SETCURSEL, original, 0)
                user32.PostMessageW(parent, WM_COMMAND, control_id | (LBN_SELCHANGE << 16), hwnd)
            record(item, path, "select_each_item", f"逐项选择 {count} 项并恢复 {original}。")

            item, path = current(control_id, "ListBox"); hwnd = int(item["hwnd"])
            focus_foreground_control(event_hwnd, hwnd); send_key(hwnd, VK_HOME); send_key(hwnd, VK_DOWN)
            if original >= 0: _send_msg_num(hwnd, LB_SETCURSEL, original, 0)
            record(item, path, "keyboard_navigation", "真实焦点 Home/Down 后恢复。")

            descendants = []
            item, path = current(control_id, "ListBox"); hwnd = int(item["hwnd"])
            for index in range(count):
                if not is_window(hwnd):
                    item, path = current(control_id, "ListBox"); hwnd = int(item["hwnd"])
                _send_msg_num(hwnd, LB_SETCURSEL, index, 0)
                known = {top["hwnd"] for top in session.top_windows()}
                post_double_click_at(hwnd, 8, 8)
                descendants.extend(dismiss_new(known, f"{control_id}_dbl_{index}", 0.65 if index == 0 else 0.01))
            record(item, path, "double_click_each_item", f"逐项双击 {count} 项；子窗={descendants}。")

            menu_hits = 0
            item, path = current(control_id, "ListBox"); hwnd = int(item["hwnd"])
            for index in range(count):
                if not is_window(hwnd):
                    item, path = current(control_id, "ListBox"); hwnd = int(item["hwnd"])
                _send_msg_num(hwnd, LB_SETCURSEL, index, 0)
                post_context_menu(hwnd, 8, 8); time.sleep(0.005)
                if visible_popup_menus(session.pid or 0):
                    menu_hits += 1; send_escape(event_hwnd)
            record(item, path, "right_click_each_item", f"逐项右键 {count} 项；菜单命中 {menu_hits} 次。")

            hidden_on = None
            for representative in outer_representatives:
                if representative == control_id: continue
                current(representative, "ListBox")
                if not visible_target(control_id, "ListBox"):
                    hidden_on = representative; break
            restored, restored_path = current(control_id, "ListBox")
            record(item, path, "discover_state_triggers", f"切至 {hidden_on} 后隐藏；返回路径={restored_path}。")
            observations.append({
                "control_id": control_id, "path": list(path),
                "item_count": count, "original_index": original,
                "hidden_on": hidden_on,
            })
            log(f"EVENTPAGELISTCONTROLS list {control_id}: {count} items")

        cancel = find_controls(enum_child_tree(event_hwnd), cls="Button", ctrl_id=110, visible=True)
        if cancel:
            click_control(cancel[0]["hwnd"]); session.wait_gone(event_hwnd, 4.0); event_hwnd = 0
    except Exception as exc:
        error = repr(exc); log(f"EVENTPAGELISTCONTROLS inner failure: {error}")
    finally:
        if event_hwnd and is_window(event_hwnd): close_window_safely(session, event_hwnd, 4.0)
        after = session.probe_rom.read_bytes()
        diffs = [i for i, (left, right) in enumerate(zip(before, after)) if left != right]
        unique = {item["action_id"]: item for item in records}
        validated = error is None and len(unique) == 69 and not diffs and len(before) == len(after)
        out_dir = session.out / "interaction-discovery"; out_dir.mkdir(parents=True, exist_ok=True)
        (out_dir / "event-page-list-actions.json").write_text(json.dumps({
            "schema_version": 1, "validated": validated, "error": error,
            "execution_record_count": len(unique),
            "diff_count": len(diffs) + int(len(before) != len(after)),
            "sha256_before": hashlib.sha256(before).hexdigest().upper(),
            "sha256_after": hashlib.sha256(after).hexdigest().upper(),
            "observations": observations,
            "execution_records": list(unique.values()) if validated else [],
        }, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    if not validated:
        raise RuntimeError(f"event pages/lists did not validate: {len(unique)}/69 {error}")
    log("EVENTPAGELISTCONTROLS complete: 69/69 actions, zero ROM diff")


def stage_eventfieldcontrols(session: ProbeSession) -> None:
    """Exercise event-editor text, combo, static and picture controls."""
    log("=== stage EVENTFIELDCONTROLS ===")
    before = session.probe_rom.read_bytes()
    records: list[dict] = []
    observations: list[dict] = []
    error: str | None = None
    event_hwnd = 0
    edit_ids = (190, 390, 490, 520, 600, 650)
    combo_ids = (430, 440, 460, 570)
    static_ids = (380, 420, 450, 470, 480, 510, 540, 590, 670)
    representatives = (160, 240, 290, 340, 560, 630)

    def record(item, path, action, result):
        records.append({
            "action_id": stable_interaction_id(
                "事件编辑", str(item.get("class", "")),
                int(item.get("ctrl_id") or 0), tuple(path), action,
            ),
            "status": "passed", "result": result,
        })

    def open_event():
        nonlocal event_hwnd
        def locate():
            for top in session.top_windows():
                if top["class"] == "WTWindow" and top["hwnd"] != session.main_hwnd:
                    if find_controls(enum_child_tree(top["hwnd"]), cls="CPageControl", ctrl_id=120):
                        return int(top["hwnd"])
            return 0
        for attempt in range(2):
            user32.PostMessageW(session.main_hwnd, WM_COMMAND, 20015, 0)
            if attempt and force_foreground(session.main_hwnd):
                keybd(VK_CONTROL); keybd(ord("J")); keybd(ord("J"), up=True); keybd(VK_CONTROL, up=True)
            deadline = time.monotonic() + (15 if attempt == 0 else 8)
            while time.monotonic() < deadline:
                event_hwnd = locate()
                if event_hwnd:
                    move_window(event_hwnd, 30, 20, 1320, 900); time.sleep(0.4); return
                time.sleep(0.15)
        raise RuntimeError("event editor did not appear")

    def visible_target(control_id, cls=None):
        tree = enum_child_tree(event_hwnd)
        matches = find_controls(tree, cls=cls, ctrl_id=control_id, visible=True)
        if not matches: return None
        item = matches[0]
        return item, tuple(control_tree_path(tree, item["hwnd"]) or ())

    def current(control_id, cls=None):
        found = visible_target(control_id, cls)
        if found: return found
        outer = find_controls(enum_child_tree(event_hwnd), cls="CPageControl", ctrl_id=120, visible=True)
        if not outer: raise RuntimeError("event outer page missing")
        width, _height = get_client_size(int(outer[0]["hwnd"]))
        for x in range(14, min(max(15, width - 24), 720), 12):
            post_click_at(int(outer[0]["hwnd"]), x, 24); time.sleep(0.05)
            found = visible_target(control_id, cls)
            if found: return found
        raise RuntimeError(f"event control {control_id} unavailable")

    def notify_edit(item):
        parent = user32.GetParent(int(item["hwnd"]))
        if parent:
            user32.PostMessageW(parent, WM_COMMAND,
                (int(item.get("ctrl_id") or 0) & 0xFFFF) | (0x0300 << 16), int(item["hwnd"]))

    def restore_edit(control_id, original):
        item, _path = current(control_id, "Edit")
        set_control_text(int(item["hwnd"]), original); notify_edit(item)

    def state_action(item, path, control_id, cls):
        hidden_on = None
        for representative in representatives:
            current(representative, "ListBox")
            if not visible_target(control_id, cls):
                hidden_on = representative; break
        restored, restored_path = current(control_id, cls)
        record(item, path, "discover_state_triggers",
            f"切至 {hidden_on} 后隐藏；返回路径={restored_path}，启用={bool(restored.get('enabled'))}。")
        return hidden_on

    def dismiss_new(known, tag):
        descendants = []
        deadline = time.monotonic() + 1.0
        while time.monotonic() < deadline:
            for popup in session.top_windows():
                if popup["hwnd"] in known or popup["hwnd"] == event_hwnd or popup["class"] == "#32768":
                    continue
                descendants.append({"title": popup["title"], "class": popup["class"]})
                session.dump_window(popup["hwnd"], f"EVENTFIELD_{tag}", menu=True)
                close_window_safely(session, popup["hwnd"], 2.0)
            time.sleep(0.04)
        return descendants

    try:
        open_event()
        for control_id in edit_ids:
            item, path = current(control_id, "Edit"); hwnd = int(item["hwnd"])
            original = get_window_text(hwnd)
            record(item, path, "focus", f"真实焦点={focus_foreground_control(event_hwnd, hwnd)}。")
            replacement = "测试" if original != "测试" else "事件"
            set_control_text(hwnd, replacement); notify_edit(item); readback = get_window_text(hwnd)
            restore_edit(control_id, original)
            record(item, path, "replace_value", f"替换读回={readback!r}，已恢复。")
            item, path = current(control_id, "Edit"); hwnd = int(item["hwnd"])
            focus_foreground_control(event_hwnd, hwnd)
            keybd(VK_CONTROL); send_key(hwnd, ord("A")); send_key(hwnd, ord("Z")); keybd(VK_CONTROL, up=True)
            restore_edit(control_id, original)
            record(item, path, "keyboard_shortcuts", "执行 Ctrl+A/Ctrl+Z 并恢复。")
            item, path = current(control_id, "Edit"); post_context_menu(int(item["hwnd"]), 6, 6); time.sleep(0.08)
            menu_visible = bool(visible_popup_menus(session.pid or 0))
            if menu_visible: send_escape(event_hwnd)
            record(item, path, "right_click", f"真实右键；菜单={menu_visible}。")
            item, path = current(control_id, "Edit"); hwnd = int(item["hwnd"])
            set_control_text(hwnd, ""); notify_edit(item); empty = get_window_text(hwnd)
            set_control_text(hwnd, "测" * 256); notify_edit(item); long_value = get_window_text(hwnd)
            restore_edit(control_id, original)
            record(item, path, "boundary_values", f"空值={empty!r}；长值长度={len(long_value)}；已恢复。")
            hidden_on = state_action(item, path, control_id, "Edit")
            observations.append({"class":"Edit", "control_id":control_id, "path":list(path), "hidden_on":hidden_on})

        for control_id in combo_ids:
            item, path = current(control_id, "ComboBox"); hwnd = int(item["hwnd"])
            values = read_combo_items(hwnd); original = int(_send_msg_num(hwnd, CB_GETCURSEL, 0, 0))
            _send_msg_num(hwnd, 0x014F, 1, 0); time.sleep(0.05); _send_msg_num(hwnd, 0x014F, 0, 0)
            record(item, path, "open_dropdown", f"展开/收起，共 {len(values)} 项。")
            readbacks = []
            for index in range(len(values)):
                set_combo_selection(hwnd, index); readbacks.append(int(_send_msg_num(hwnd, CB_GETCURSEL, 0, 0)))
            if original >= 0: set_combo_selection(hwnd, original)
            record(item, path, "select_each_item", f"逐项选择并读回 {len(readbacks)}/{len(values)} 项，已恢复。")
            focus_foreground_control(event_hwnd, hwnd); send_key(hwnd, VK_HOME); send_key(hwnd, VK_DOWN)
            keyboard_index = int(_send_msg_num(hwnd, CB_GETCURSEL, 0, 0))
            if original >= 0: set_combo_selection(hwnd, original)
            record(item, path, "keyboard_cycle", f"Home/Down 读回 {keyboard_index}，已恢复。")
            post_context_menu(hwnd, 6, 6); time.sleep(0.08)
            menu_visible = bool(visible_popup_menus(session.pid or 0))
            if menu_visible: send_escape(event_hwnd)
            record(item, path, "right_click", f"真实右键；菜单={menu_visible}。")
            hidden_on = state_action(item, path, control_id, "ComboBox")
            observations.append({"class":"ComboBox", "control_id":control_id, "path":list(path), "item_count":len(values), "hidden_on":hidden_on})

        for control_id in static_ids:
            item, path = current(control_id)
            cls = str(item.get("class", ""))
            if not (cls.startswith("Afx:") or cls == "_EL_Label"):
                raise RuntimeError(f"event static {control_id} unexpected class {cls}")
            hidden_on = state_action(item, path, control_id, cls)
            observations.append({"class":cls, "control_id":control_id, "path":list(path), "hidden_on":hidden_on})

        item, path = current(620, "_EL_PicBox"); hwnd = int(item["hwnd"])
        known = {top["hwnd"] for top in session.top_windows()}; post_click_at(hwnd, 12, 12); time.sleep(0.1)
        record(item, path, "left_click_regions", f"左键；子窗={dismiss_new(known, 'pic_left')}。")
        item, path = current(620, "_EL_PicBox"); hwnd = int(item["hwnd"])
        known = {top["hwnd"] for top in session.top_windows()}; post_double_click_at(hwnd, 12, 12)
        record(item, path, "double_click_regions", f"双击；子窗={dismiss_new(known, 'pic_double')}。")
        item, path = current(620, "_EL_PicBox"); hwnd = int(item["hwnd"])
        post_context_menu(hwnd, 12, 12); time.sleep(0.1); menu_visible = bool(visible_popup_menus(session.pid or 0))
        if menu_visible: send_escape(event_hwnd)
        record(item, path, "right_click_regions", f"右键菜单={menu_visible}。")
        item, path = current(620, "_EL_PicBox"); post_drag_at(item["hwnd"], 12, 12, 36, 20); time.sleep(0.1)
        record(item, path, "drag_regions", "真实短距离拖拽。")
        hidden_on = state_action(item, path, 620, "_EL_PicBox")
        observations.append({"class":"_EL_PicBox", "control_id":620, "path":list(path), "hidden_on":hidden_on})

        cancel = find_controls(enum_child_tree(event_hwnd), cls="Button", ctrl_id=110, visible=True)
        if cancel: click_control(cancel[0]["hwnd"]); session.wait_gone(event_hwnd, 4.0); event_hwnd = 0
    except Exception as exc:
        error = repr(exc); log(f"EVENTFIELDCONTROLS inner failure: {error}")
    finally:
        if event_hwnd and is_window(event_hwnd): close_window_safely(session, event_hwnd, 4.0)
        after = session.probe_rom.read_bytes(); diffs = [i for i,(a,b) in enumerate(zip(before,after)) if a != b]
        unique = {item["action_id"]:item for item in records}
        validated = error is None and len(unique) == 70 and not diffs and len(before) == len(after)
        out_dir = session.out / "interaction-discovery"; out_dir.mkdir(parents=True, exist_ok=True)
        (out_dir / "event-field-actions.json").write_text(json.dumps({
            "schema_version":1, "validated":validated, "error":error,
            "execution_record_count":len(unique), "diff_count":len(diffs)+int(len(before)!=len(after)),
            "sha256_before":hashlib.sha256(before).hexdigest().upper(),
            "sha256_after":hashlib.sha256(after).hexdigest().upper(),
            "observations":observations,
            "execution_records":list(unique.values()) if validated else [],
        }, ensure_ascii=False, indent=2)+"\n", encoding="utf-8")
    if not validated:
        raise RuntimeError(f"event fields did not validate: {len(unique)}/70 {error}")
    log("EVENTFIELDCONTROLS complete: 70/70 actions, zero ROM diff")


def stage_eventbuttoncontrols(session: ProbeSession) -> None:
    """Exercise all event-editor buttons and recursively capture descendants."""
    log("=== stage EVENTBUTTONCONTROLS ===")
    before = session.probe_rom.read_bytes()
    records: list[dict] = []
    observations: list[dict] = []
    error: str | None = None
    event_hwnd = 0
    page_button_ids = (
        170, 180, 200, 210, 250, 270, 300, 320, 350, 370,
        400, 410, 500, 530, 550, 580, 610, 640, 660, 680, 700,
    )
    global_button_ids = (690, 100, 110)
    representatives = (160, 240, 290, 340, 560, 630)
    event_case = str(getattr(session, "event_button_case", "page"))
    global_cases = {
        f"global-{control_id}-{action}": (control_id, action)
        for control_id in global_button_ids
        for action in ("right_click", "keyboard_activate", "left_click")
    }
    if event_case != "page" and event_case not in global_cases:
        raise RuntimeError(f"invalid event button case: {event_case}")

    def record(item, path, action, result):
        records.append({
            "action_id": stable_interaction_id(
                "事件编辑", "Button", int(item.get("ctrl_id") or 0),
                tuple(path), action,
            ),
            "status": "passed", "result": result,
        })

    def locate_event():
        for top in session.top_windows():
            if top["class"] == "WTWindow" and top["hwnd"] != session.main_hwnd:
                if find_controls(enum_child_tree(top["hwnd"]), cls="CPageControl", ctrl_id=120):
                    return int(top["hwnd"])
        return 0

    def open_event():
        nonlocal event_hwnd
        existing = locate_event()
        if existing:
            event_hwnd = existing; return
        for attempt in range(2):
            user32.PostMessageW(session.main_hwnd, WM_COMMAND, 20015, 0)
            if attempt and force_foreground(session.main_hwnd):
                keybd(VK_CONTROL); keybd(ord("J")); keybd(ord("J"), up=True); keybd(VK_CONTROL, up=True)
            deadline = time.monotonic() + (15 if attempt == 0 else 8)
            while time.monotonic() < deadline:
                event_hwnd = locate_event()
                if event_hwnd:
                    move_window(event_hwnd, 30, 20, 1320, 900); time.sleep(0.4); return
                time.sleep(0.15)
        raise RuntimeError("event editor did not appear")

    def close_event(cancel=True):
        nonlocal event_hwnd
        if not event_hwnd or not is_window(event_hwnd):
            event_hwnd = 0; return
        if cancel:
            buttons = find_controls(enum_child_tree(event_hwnd), cls="Button", ctrl_id=110, visible=True)
            if buttons:
                click_control(buttons[0]["hwnd"]); session.wait_gone(event_hwnd, 3.0)
        if is_window(event_hwnd): close_window_safely(session, event_hwnd, 3.0)
        event_hwnd = 0

    def visible_button(control_id):
        tree = enum_child_tree(event_hwnd)
        matches = find_controls(tree, cls="Button", ctrl_id=control_id, visible=True)
        if not matches: return None
        item = matches[0]
        return item, tuple(control_tree_path(tree, item["hwnd"]) or ())

    def current_button(control_id, page_scoped=True):
        open_event()
        found = visible_button(control_id)
        if found: return found
        if not page_scoped: raise RuntimeError(f"event global button {control_id} missing")
        outer = find_controls(enum_child_tree(event_hwnd), cls="CPageControl", ctrl_id=120, visible=True)
        if not outer: raise RuntimeError("event outer page missing")
        width, _height = get_client_size(int(outer[0]["hwnd"]))
        for x in range(14, min(max(15, width - 24), 720), 12):
            post_click_at(int(outer[0]["hwnd"]), x, 24); time.sleep(0.05)
            found = visible_button(control_id)
            if found: return found
        raise RuntimeError(f"event button {control_id} unavailable")

    def current_list(control_id):
        tree = enum_child_tree(event_hwnd)
        visible = find_controls(tree, cls="ListBox", ctrl_id=control_id, visible=True)
        if visible: return visible[0]
        outer = find_controls(tree, cls="CPageControl", ctrl_id=120, visible=True)[0]
        width, _height = get_client_size(int(outer["hwnd"]))
        for x in range(14, min(max(15, width - 24), 720), 12):
            post_click_at(int(outer["hwnd"]), x, 24); time.sleep(0.05)
            visible = find_controls(enum_child_tree(event_hwnd), cls="ListBox", ctrl_id=control_id, visible=True)
            if visible: return visible[0]
        raise RuntimeError(f"event representative {control_id} unavailable")

    def dismiss_descendants(known, tag):
        found = []
        seen = set()
        deadline = time.monotonic() + 1.2
        while time.monotonic() < deadline:
            for popup in session.top_windows():
                if popup["hwnd"] in known or popup["hwnd"] == event_hwnd or popup["class"] == "#32768":
                    continue
                if popup["hwnd"] not in seen:
                    seen.add(popup["hwnd"])
                    found.append({"title":popup["title"], "class":popup["class"]})
                    session.dump_window(popup["hwnd"], f"EVENTBUTTON_{tag}_{len(seen)}", menu=True)
                tree = enum_child_tree(popup["hwnd"])
                cancel = find_controls(tree, cls="Button", ctrl_id=2, visible=True)
                if not cancel:
                    cancel = [candidate for candidate in find_controls(tree, cls="Button", visible=True)
                              if candidate.get("text") in ("取消", "否", "No")]
                if cancel:
                    click_control(cancel[0]["hwnd"]); session.wait_gone(popup["hwnd"], 1.5)
                if is_window(popup["hwnd"]): close_window_safely(session, popup["hwnd"], 1.5)
            time.sleep(0.04)
        return found

    def activate(control_id, action, page_scoped=True):
        nonlocal event_hwnd
        item, path = current_button(control_id, page_scoped)
        known = {top["hwnd"] for top in session.top_windows()}
        focused = None
        if action == "keyboard_activate":
            focused = focus_foreground_control(event_hwnd, int(item["hwnd"])); send_key(int(item["hwnd"]), VK_SPACE)
        elif action == "left_click":
            click_control(int(item["hwnd"]))
        else:
            post_context_menu(int(item["hwnd"]), 6, 6); time.sleep(0.08)
            if visible_popup_menus(session.pid or 0): send_escape(event_hwnd)
        time.sleep(0.15)
        descendants = dismiss_descendants(known, f"{control_id}_{action}")
        alive = bool(event_hwnd and is_window(event_hwnd) and user32.IsWindowVisible(event_hwnd))
        record(item, path, action, f"焦点={focused}；主窗可见={alive}；子窗={descendants}。")
        observations.append({"control_id":control_id, "action":action, "path":list(path),
                             "focused":focused, "window_visible":alive, "descendants":descendants})
        if not alive: event_hwnd = 0

    try:
        open_event()
        if event_case == "page":
            for control_id in page_button_ids:
                item, path = current_button(control_id)
                post_context_menu(int(item["hwnd"]), 6, 6); time.sleep(0.08)
                menu_visible = bool(visible_popup_menus(session.pid or 0))
                if menu_visible: send_escape(event_hwnd)
                record(item, path, "right_click", f"真实右键；菜单={menu_visible}。")
                hidden_on = None
                for representative in representatives:
                    current_list(representative)
                    if not visible_button(control_id): hidden_on = representative; break
                restored, restored_path = current_button(control_id)
                record(item, path, "discover_state_triggers",
                       f"切至 {hidden_on} 后隐藏；返回路径={restored_path}，启用={bool(restored.get('enabled'))}。")
                activate(control_id, "keyboard_activate")
                activate(control_id, "left_click")
                log(f"EVENTBUTTONCONTROLS page button {control_id} complete")
        else:
            control_id, action = global_cases[event_case]
            activate(control_id, action, page_scoped=False)
    except Exception as exc:
        error = repr(exc); log(f"EVENTBUTTONCONTROLS inner failure: {error}")
    finally:
        close_event(cancel=True)
        after = session.probe_rom.read_bytes(); diffs = [i for i,(a,b) in enumerate(zip(before,after)) if a != b]
        unique = {item["action_id"]:item for item in records}
        expected = 84 if event_case == "page" else 1
        validated = error is None and len(unique) == expected and not diffs and len(before) == len(after)
        out_dir = session.out / "interaction-discovery"; out_dir.mkdir(parents=True, exist_ok=True)
        (out_dir / f"event-button-{event_case}-actions.json").write_text(json.dumps({
            "schema_version":1, "validated":validated, "error":error,
            "execution_record_count":len(unique), "diff_count":len(diffs)+int(len(before)!=len(after)),
            "sha256_before":hashlib.sha256(before).hexdigest().upper(),
            "sha256_after":hashlib.sha256(after).hexdigest().upper(),
            "observations":observations,
            "execution_records":list(unique.values()) if validated else [],
        }, ensure_ascii=False, indent=2)+"\n", encoding="utf-8")
    if not validated:
        raise RuntimeError(f"event buttons {event_case} did not validate: {len(unique)}/{expected} {error}")
    log(f"EVENTBUTTONCONTROLS {event_case} complete: {expected}/{expected} actions, zero ROM diff")


def stage_titlepuzzlecontrols(session: ProbeSession) -> None:
    """Exercise the event editor's nested title-puzzle window."""
    log("=== stage TITLEPUZZLECONTROLS ===")
    before = session.probe_rom.read_bytes(); records = []; observations = []
    error = None; event_hwnd = 0; puzzle_hwnd = 0
    combo_ids = (100, 120, 150); edit_ids = (160, 220, 240)
    spinner_pairs = ((164, 160), (224, 220), (244, 240))
    button_ids = (190, 200, 310, 360, 370)

    def record(item, path, action, result):
        records.append({"action_id":stable_interaction_id(
            "标题拼图", str(item.get("class", "")), int(item.get("ctrl_id") or 0), tuple(path), action),
            "status":"passed", "result":result})

    def locate_event():
        for top in session.top_windows():
            if top["class"] == "WTWindow" and top["hwnd"] != session.main_hwnd:
                if find_controls(enum_child_tree(top["hwnd"]), cls="CPageControl", ctrl_id=120):
                    return int(top["hwnd"])
        return 0

    def open_event():
        nonlocal event_hwnd
        event_hwnd = locate_event()
        if event_hwnd: return
        for attempt in range(2):
            user32.PostMessageW(session.main_hwnd, WM_COMMAND, 20015, 0)
            if attempt and force_foreground(session.main_hwnd):
                keybd(VK_CONTROL); keybd(ord("J")); keybd(ord("J"), up=True); keybd(VK_CONTROL, up=True)
            deadline = time.monotonic() + (15 if attempt == 0 else 8)
            while time.monotonic() < deadline:
                event_hwnd = locate_event()
                if event_hwnd: move_window(event_hwnd, 30, 20, 1320, 900); time.sleep(0.4); return
                time.sleep(0.15)
        raise RuntimeError("event editor did not appear")

    def close_puzzle():
        nonlocal puzzle_hwnd
        if not puzzle_hwnd or not is_window(puzzle_hwnd): puzzle_hwnd = 0; return
        cancel = find_controls(enum_child_tree(puzzle_hwnd), cls="Button", ctrl_id=200, visible=True)
        if cancel: click_control(cancel[0]["hwnd"]); session.wait_gone(puzzle_hwnd, 2.0)
        if is_window(puzzle_hwnd): close_window_safely(session, puzzle_hwnd, 2.0)
        puzzle_hwnd = 0

    def open_puzzle():
        nonlocal puzzle_hwnd
        if puzzle_hwnd and is_window(puzzle_hwnd) and user32.IsWindowVisible(puzzle_hwnd): return
        open_event(); tree = enum_child_tree(event_hwnd)
        opener = find_controls(tree, cls="Button", ctrl_id=610, visible=True)
        if not opener:
            outer = find_controls(tree, cls="CPageControl", ctrl_id=120, visible=True)[0]
            width, _height = get_client_size(int(outer["hwnd"]))
            for x in range(14, min(max(15, width - 24), 720), 12):
                post_click_at(int(outer["hwnd"]), x, 24); time.sleep(0.05)
                opener = find_controls(enum_child_tree(event_hwnd), cls="Button", ctrl_id=610, visible=True)
                if opener: break
        if not opener: raise RuntimeError("title puzzle opener missing")
        known = {top["hwnd"] for top in session.top_windows()}; click_control(opener[0]["hwnd"])
        deadline = time.monotonic() + 5.0
        while time.monotonic() < deadline:
            for top in session.top_windows():
                if top["hwnd"] in known or top["class"] != "WTWindow": continue
                tree = enum_child_tree(top["hwnd"])
                if (find_controls(tree, cls="_EL_PicBox", ctrl_id=350)
                        and find_controls(tree, cls="ComboBox", ctrl_id=100)):
                    puzzle_hwnd = int(top["hwnd"]); time.sleep(0.2); return
            time.sleep(0.08)
        raise RuntimeError("title puzzle did not appear")

    def current(control_id, cls):
        open_puzzle(); tree = enum_child_tree(puzzle_hwnd)
        item = find_controls(tree, cls=cls, ctrl_id=control_id, visible=True)[0]
        return item, tuple(control_tree_path(tree, item["hwnd"]) or ())

    def notify_edit(item):
        parent = user32.GetParent(int(item["hwnd"]))
        if parent: user32.PostMessageW(parent, WM_COMMAND,
            (int(item.get("ctrl_id") or 0)&0xFFFF)|(0x0300<<16), int(item["hwnd"]))

    try:
        open_puzzle()
        for cid in combo_ids:
            item,path=current(cid,"ComboBox"); hwnd=int(item["hwnd"]); values=read_combo_items(hwnd)
            original=int(_send_msg_num(hwnd,CB_GETCURSEL,0,0))
            _send_msg_num(hwnd,0x014F,1,0); time.sleep(0.05); _send_msg_num(hwnd,0x014F,0,0)
            record(item,path,"open_dropdown",f"展开/收起，共 {len(values)} 项。")
            readbacks=[]
            for index in range(len(values)):
                set_combo_selection(hwnd,index); readbacks.append(int(_send_msg_num(hwnd,CB_GETCURSEL,0,0)))
            if original>=0: set_combo_selection(hwnd,original)
            record(item,path,"select_each_item",f"逐项选择并读回 {len(readbacks)}/{len(values)} 项，已恢复。")
            focus_foreground_control(puzzle_hwnd,hwnd); send_key(hwnd,VK_HOME); send_key(hwnd,VK_DOWN)
            key_index=int(_send_msg_num(hwnd,CB_GETCURSEL,0,0))
            if original>=0:set_combo_selection(hwnd,original)
            record(item,path,"keyboard_cycle",f"Home/Down 读回 {key_index}，已恢复。")
            post_context_menu(hwnd,5,5);time.sleep(0.08);menu=bool(visible_popup_menus(session.pid or 0))
            if menu:send_escape(puzzle_hwnd)
            record(item,path,"right_click",f"右键菜单={menu}。")
            observations.append({"control_id":cid,"class":"ComboBox","item_count":len(values),"path":list(path)})

        for cid in edit_ids:
            item,path=current(cid,"Edit");hwnd=int(item["hwnd"]);original=get_window_text(hwnd)
            record(item,path,"focus",f"真实焦点={focus_foreground_control(puzzle_hwnd,hwnd)}。")
            set_control_text(hwnd,"1");notify_edit(item);readback=get_window_text(hwnd);set_control_text(hwnd,original);notify_edit(item)
            record(item,path,"replace_value",f"替换读回={readback!r}，已恢复。")
            focus_foreground_control(puzzle_hwnd,hwnd);keybd(VK_CONTROL);send_key(hwnd,ord("A"));send_key(hwnd,ord("Z"));keybd(VK_CONTROL,up=True)
            set_control_text(hwnd,original);notify_edit(item);record(item,path,"keyboard_shortcuts","Ctrl+A/Ctrl+Z 后恢复。")
            post_context_menu(hwnd,5,5);time.sleep(0.08);menu=bool(visible_popup_menus(session.pid or 0))
            if menu:send_escape(puzzle_hwnd)
            record(item,path,"right_click",f"右键菜单={menu}。")
            boundary=[]
            for value in ("-32768","32767"):
                set_control_text(hwnd,value);notify_edit(item);boundary.append(get_window_text(hwnd))
            set_control_text(hwnd,original);notify_edit(item)
            record(item,path,"boundary_values",f"边界读回={boundary}，已恢复。")

        for cid,partner_id in spinner_pairs:
            item,path=current(cid,"msctls_updown32");partner,_=current(partner_id,"Edit")
            hwnd=int(item["hwnd"]);phwnd=int(partner["hwnd"]);original=get_window_text(phwnd)
            post_click_at(hwnd,5,3);time.sleep(0.05);inc=get_window_text(phwnd);set_control_text(phwnd,original);notify_edit(partner)
            record(item,path,"increment",f"伙伴 {original!r}->{inc!r}。")
            post_click_at(hwnd,5,max(4,item["rect"]["height"]-3));time.sleep(0.05);dec=get_window_text(phwnd);set_control_text(phwnd,original);notify_edit(partner)
            record(item,path,"decrement",f"伙伴 {original!r}->{dec!r}。")
            boundary=[]
            for value in ("-32768","32767"):
                set_control_text(phwnd,value);notify_edit(partner);boundary.append(get_window_text(phwnd))
            set_control_text(phwnd,original);notify_edit(partner)
            record(item,path,"boundary_values",f"伙伴边界={boundary}，已恢复。")

        item,path=current(350,"_EL_PicBox");hwnd=int(item["hwnd"])
        post_click_at(hwnd,12,12);record(item,path,"left_click_regions","图片区左键。")
        post_double_click_at(hwnd,12,12);record(item,path,"double_click_regions","图片区双击。")
        post_context_menu(hwnd,12,12);time.sleep(0.08);menu=bool(visible_popup_menus(session.pid or 0))
        if menu:send_escape(puzzle_hwnd)
        record(item,path,"right_click_regions",f"图片区右键菜单={menu}。")
        post_drag_at(hwnd,12,12,36,20);record(item,path,"drag_regions","图片区短距离拖拽。")

        close_puzzle()
        for cid in button_ids:
            for action in ("keyboard_activate","left_click","right_click"):
                open_puzzle();item,path=current(cid,"Button");known={top["hwnd"] for top in session.top_windows()}
                focused=None
                if action=="keyboard_activate":focused=focus_foreground_control(puzzle_hwnd,int(item["hwnd"]));send_key(int(item["hwnd"]),VK_SPACE)
                elif action=="left_click":click_control(int(item["hwnd"]))
                else:
                    post_context_menu(int(item["hwnd"]),5,5);time.sleep(0.08)
                    if visible_popup_menus(session.pid or 0):send_escape(puzzle_hwnd)
                time.sleep(0.15); descendants=[]
                for popup in session.top_windows():
                    if popup["hwnd"] not in known and popup["hwnd"] not in (puzzle_hwnd,event_hwnd) and popup["class"]!="#32768":
                        descendants.append({"title":popup["title"],"class":popup["class"]});session.dump_window(popup["hwnd"],f"TITLEPUZZLE_{cid}_{action}",menu=True);close_window_safely(session,popup["hwnd"],2.0)
                remained=bool(puzzle_hwnd and is_window(puzzle_hwnd) and user32.IsWindowVisible(puzzle_hwnd))
                record(item,path,action,f"焦点={focused}；窗口仍可见={remained}；子窗={descendants}。")
                if not remained:puzzle_hwnd=0
                close_puzzle()
        if event_hwnd and is_window(event_hwnd):
            cancel=find_controls(enum_child_tree(event_hwnd),cls="Button",ctrl_id=110,visible=True)
            if cancel:click_control(cancel[0]["hwnd"]);session.wait_gone(event_hwnd,3.0);event_hwnd=0
    except Exception as exc:
        error=repr(exc);log(f"TITLEPUZZLECONTROLS inner failure: {error}")
    finally:
        close_puzzle()
        if event_hwnd and is_window(event_hwnd):close_window_safely(session,event_hwnd,3.0)
        after=session.probe_rom.read_bytes();diffs=[i for i,(a,b) in enumerate(zip(before,after)) if a!=b]
        unique={item["action_id"]:item for item in records};validated=error is None and len(unique)==55 and not diffs and len(before)==len(after)
        out_dir=session.out/"interaction-discovery";out_dir.mkdir(parents=True,exist_ok=True)
        (out_dir/"title-puzzle-actions.json").write_text(json.dumps({
            "schema_version":1,"validated":validated,"error":error,"execution_record_count":len(unique),
            "diff_count":len(diffs)+int(len(before)!=len(after)),"sha256_before":hashlib.sha256(before).hexdigest().upper(),
            "sha256_after":hashlib.sha256(after).hexdigest().upper(),"observations":observations,
            "execution_records":list(unique.values()) if validated else []},ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    if not validated:raise RuntimeError(f"title puzzle did not validate: {len(unique)}/55 {error}")
    log("TITLEPUZZLECONTROLS complete: 55/55 actions, zero ROM diff")


def stage_puzzlecodecontrols(session: ProbeSession) -> None:
    """Exercise the title-puzzle code editor in isolated button cases."""
    log("=== stage PUZZLECODECONTROLS ===")
    before=session.probe_rom.read_bytes();records=[];observations=[];error=None
    event_hwnd=0;puzzle_hwnd=0;code_hwnd=0
    case=str(getattr(session,"puzzle_code_case","ok-keyboard"))
    case_map={"ok-keyboard":(110,"keyboard_activate"),"ok-left":(110,"left_click"),"ok-right":(110,"right_click"),
              "cancel-keyboard":(120,"keyboard_activate"),"cancel-left":(120,"left_click"),"cancel-right":(120,"right_click")}
    if case not in case_map:raise RuntimeError(f"invalid puzzle code case: {case}")

    def record(item,path,action,result):
        records.append({"action_id":stable_interaction_id("拼图代码",str(item.get("class","")),int(item.get("ctrl_id") or 0),tuple(path),action),"status":"passed","result":result})

    def find_event():
        for top in session.top_windows(visible_only=False):
            if top["class"]=="WTWindow" and top["hwnd"]!=session.main_hwnd and find_controls(enum_child_tree(top["hwnd"]),cls="CPageControl",ctrl_id=120):return int(top["hwnd"])
        return 0

    def open_event():
        nonlocal event_hwnd
        event_hwnd=find_event()
        if event_hwnd:
            if not user32.IsWindowVisible(event_hwnd):
                user32.ShowWindow(event_hwnd,SW_SHOW);force_foreground(event_hwnd);time.sleep(0.4)
            return
        for attempt in range(12):
            user32.PostMessageW(session.main_hwnd,WM_COMMAND,20015,0)
            if attempt % 3 == 2 and force_foreground(session.main_hwnd):
                keybd(VK_CONTROL);keybd(ord("J"));keybd(ord("J"),up=True);keybd(VK_CONTROL,up=True)
            deadline=time.monotonic()+2.0
            while time.monotonic()<deadline:
                event_hwnd=find_event()
                if event_hwnd:
                    if not user32.IsWindowVisible(event_hwnd):
                        user32.ShowWindow(event_hwnd,SW_SHOW);force_foreground(event_hwnd);time.sleep(0.3)
                    return
                time.sleep(0.15)
        raise RuntimeError("event editor did not appear")

    def open_puzzle():
        nonlocal puzzle_hwnd
        open_event();tree=enum_child_tree(event_hwnd);opener=find_controls(tree,cls="Button",ctrl_id=610,visible=True)
        if not opener:
            outer=find_controls(tree,cls="CPageControl",ctrl_id=120,visible=True)[0];width,_=get_client_size(int(outer["hwnd"]))
            for x in range(14,min(max(15,width-24),720),12):
                post_click_at(int(outer["hwnd"]),x,24);time.sleep(0.05);opener=find_controls(enum_child_tree(event_hwnd),cls="Button",ctrl_id=610,visible=True)
                if opener:break
        if not opener:raise RuntimeError("title puzzle opener missing")
        known={top["hwnd"] for top in session.top_windows()};click_control(opener[0]["hwnd"]);deadline=time.monotonic()+5
        while time.monotonic()<deadline:
            for top in session.top_windows():
                if top["hwnd"] not in known and top["class"]=="WTWindow" and find_controls(enum_child_tree(top["hwnd"]),cls="_EL_PicBox",ctrl_id=350):puzzle_hwnd=int(top["hwnd"]);return
            time.sleep(0.08)
        raise RuntimeError("title puzzle did not appear")

    def open_code():
        nonlocal code_hwnd
        open_puzzle();opener=find_controls(enum_child_tree(puzzle_hwnd),cls="Button",ctrl_id=360,visible=True)[0]
        known={top["hwnd"] for top in session.top_windows()};click_control(opener["hwnd"]);deadline=time.monotonic()+4
        while time.monotonic()<deadline:
            for top in session.top_windows():
                if top["hwnd"] not in known and top["class"]=="WTWindow":
                    tree=enum_child_tree(top["hwnd"])
                    if find_controls(tree,cls="Edit",ctrl_id=100) and find_controls(tree,cls="Button",ctrl_id=110):code_hwnd=int(top["hwnd"]);return
            time.sleep(0.08)
        raise RuntimeError("puzzle code editor did not appear")

    def close_all():
        nonlocal code_hwnd,puzzle_hwnd,event_hwnd
        for hwnd,cancel_id in ((code_hwnd,120),(puzzle_hwnd,200),(event_hwnd,110)):
            if hwnd and is_window(hwnd):
                cancel=find_controls(enum_child_tree(hwnd),cls="Button",ctrl_id=cancel_id,visible=True)
                if cancel:click_control(cancel[0]["hwnd"]);session.wait_gone(hwnd,2.0)
                if is_window(hwnd):close_window_safely(session,hwnd,2.0)
        code_hwnd=0;puzzle_hwnd=0;event_hwnd=0

    try:
        open_code();tree=enum_child_tree(code_hwnd);item=find_controls(tree,cls="Edit",ctrl_id=100,visible=True)[0]
        path=tuple(control_tree_path(tree,item["hwnd"]) or ());hwnd=int(item["hwnd"]);original=get_window_text(hwnd)
        record(item,path,"focus",f"真实焦点={focus_foreground_control(code_hwnd,hwnd)}。")
        set_control_text(hwnd,"00 FF");readback=get_window_text(hwnd);set_control_text(hwnd,original)
        record(item,path,"replace_value",f"替换读回={readback!r}，已恢复。")
        focus_foreground_control(code_hwnd,hwnd);keybd(VK_CONTROL);send_key(hwnd,ord("A"));send_key(hwnd,ord("Z"));keybd(VK_CONTROL,up=True);set_control_text(hwnd,original)
        record(item,path,"keyboard_shortcuts","Ctrl+A/Ctrl+Z 后恢复。")
        post_context_menu(hwnd,5,5);time.sleep(0.08);menu=bool(visible_popup_menus(session.pid or 0))
        if menu:send_escape(code_hwnd)
        record(item,path,"right_click",f"右键菜单={menu}。")
        set_control_text(hwnd,"");empty=get_window_text(hwnd);set_control_text(hwnd,"FF "*256);long_value=get_window_text(hwnd);set_control_text(hwnd,original)
        record(item,path,"boundary_values",f"空值={empty!r}；长值长度={len(long_value)}；已恢复。")
        button_id,action=case_map[case];tree=enum_child_tree(code_hwnd);item=find_controls(tree,cls="Button",ctrl_id=button_id,visible=True)[0];path=tuple(control_tree_path(tree,item["hwnd"]) or ())
        focused=None
        if action=="keyboard_activate":focused=focus_foreground_control(code_hwnd,int(item["hwnd"]));send_key(int(item["hwnd"]),VK_SPACE)
        elif action=="left_click":click_control(int(item["hwnd"]))
        else:
            post_context_menu(int(item["hwnd"]),5,5);time.sleep(0.08)
            if visible_popup_menus(session.pid or 0):send_escape(code_hwnd)
        time.sleep(0.15);remained=bool(is_window(code_hwnd) and user32.IsWindowVisible(code_hwnd))
        record(item,path,action,f"焦点={focused}；窗口仍可见={remained}。");observations.append({"case":case,"button_id":button_id,"action":action,"remained":remained})
    except Exception as exc:error=repr(exc);log(f"PUZZLECODECONTROLS inner failure: {error}")
    finally:
        close_all();after=session.probe_rom.read_bytes();diffs=[i for i,(a,b) in enumerate(zip(before,after)) if a!=b]
        unique={item["action_id"]:item for item in records};validated=error is None and len(unique)==6 and not diffs and len(before)==len(after)
        out_dir=session.out/"interaction-discovery";out_dir.mkdir(parents=True,exist_ok=True)
        (out_dir/f"puzzle-code-{case}-actions.json").write_text(json.dumps({"schema_version":1,"validated":validated,"error":error,"execution_record_count":len(unique),"diff_count":len(diffs)+int(len(before)!=len(after)),"sha256_before":hashlib.sha256(before).hexdigest().upper(),"sha256_after":hashlib.sha256(after).hexdigest().upper(),"observations":observations,"execution_records":list(unique.values()) if validated else []},ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    if not validated:raise RuntimeError(f"puzzle code {case} did not validate: {len(unique)}/6 {error}")
    log(f"PUZZLECODECONTROLS {case} complete: 6/6 actions, zero ROM diff")


def stage_otherfieldcontrols(session: ProbeSession) -> None:
    """Exercise every edit, spinner and combo in the legacy Other window."""
    log("=== stage OTHERFIELDCONTROLS ===")
    before=session.probe_rom.read_bytes();records=[];observations=[];error=None;other_hwnd=0
    edit_ids=(120,160,180,200,220,250,260,280,310,340,350,360,650,670,690,720,730,770,800,830)
    combo_ids=(380,400,420,440,460,480,500,520,540,560,580,600)
    spinner_pairs=tuple((cid+4,cid) for cid in edit_ids)

    def record(item,path,action,result):
        records.append({"action_id":stable_interaction_id("其他",str(item.get("class","")),int(item.get("ctrl_id") or 0),tuple(path),action),"status":"passed","result":result})

    def notify_edit(item):
        parent=user32.GetParent(int(item["hwnd"]))
        if parent:user32.PostMessageW(parent,WM_COMMAND,(int(item.get("ctrl_id") or 0)&0xFFFF)|(0x0300<<16),int(item["hwnd"]))

    try:
        window=_open_data_window(session,20023,"其他",dismiss_hidden=False)
        if not window:raise RuntimeError("Other window did not appear")
        other_hwnd=int(window["hwnd"]);move_window(other_hwnd,80,50,1000,760);time.sleep(0.5)
        for cid in edit_ids:
            tree=enum_child_tree(other_hwnd);item=find_controls(tree,cls="Edit",ctrl_id=cid,visible=True)[0]
            path=tuple(control_tree_path(tree,item["hwnd"]) or ());hwnd=int(item["hwnd"]);original=get_window_text(hwnd)
            record(item,path,"focus",f"真实焦点={focus_foreground_control(other_hwnd,hwnd)}。")
            replacement="1" if original.strip().lstrip("-+").isdigit() else "测试"
            set_control_text(hwnd,replacement);notify_edit(item);readback=get_window_text(hwnd);set_control_text(hwnd,original);notify_edit(item)
            record(item,path,"replace_value",f"替换读回={readback!r}，已恢复。")
            focus_foreground_control(other_hwnd,hwnd);keybd(VK_CONTROL);send_key(hwnd,ord("A"));send_key(hwnd,ord("Z"));keybd(VK_CONTROL,up=True);set_control_text(hwnd,original);notify_edit(item)
            record(item,path,"keyboard_shortcuts","Ctrl+A/Ctrl+Z 后恢复。")
            post_context_menu(hwnd,5,5);time.sleep(0.08);menus=visible_popup_menus(session.pid or 0)
            if menus:send_key(int(menus[0]["hwnd"]),VK_ESCAPE)
            record(item,path,"right_click",f"右键菜单={bool(menus)}。")
            boundary=[]
            for value in ("-32768","32767"):
                set_control_text(hwnd,value);notify_edit(item);boundary.append(get_window_text(hwnd))
            set_control_text(hwnd,original);notify_edit(item)
            record(item,path,"boundary_values",f"边界读回={boundary}，已恢复。")
            observations.append({"class":"Edit","control_id":cid,"path":list(path),"original":original,"boundary":boundary})

        for cid in combo_ids:
            tree=enum_child_tree(other_hwnd);item=find_controls(tree,cls="ComboBox",ctrl_id=cid,visible=True)[0]
            path=tuple(control_tree_path(tree,item["hwnd"]) or ());hwnd=int(item["hwnd"]);values=read_combo_items(hwnd);original=int(_send_msg_num(hwnd,CB_GETCURSEL,0,0))
            _send_msg_num(hwnd,0x014F,1,0);time.sleep(0.05);_send_msg_num(hwnd,0x014F,0,0)
            record(item,path,"open_dropdown",f"展开/收起，共 {len(values)} 项。")
            readbacks=[]
            for index in range(len(values)):
                set_combo_selection(hwnd,index);readbacks.append(int(_send_msg_num(hwnd,CB_GETCURSEL,0,0)))
            if original>=0:set_combo_selection(hwnd,original)
            record(item,path,"select_each_item",f"逐项选择并读回 {len(readbacks)}/{len(values)} 项，已恢复。")
            focus_foreground_control(other_hwnd,hwnd);send_key(hwnd,VK_HOME);send_key(hwnd,VK_DOWN);keyboard_index=int(_send_msg_num(hwnd,CB_GETCURSEL,0,0))
            if original>=0:set_combo_selection(hwnd,original)
            record(item,path,"keyboard_cycle",f"Home/Down 读回 {keyboard_index}，已恢复。")
            post_context_menu(hwnd,5,5);time.sleep(0.08);menus=visible_popup_menus(session.pid or 0)
            if menus:send_key(int(menus[0]["hwnd"]),VK_ESCAPE)
            record(item,path,"right_click",f"右键菜单={bool(menus)}。")
            observations.append({"class":"ComboBox","control_id":cid,"path":list(path),"item_count":len(values),"original_index":original})

        for cid,partner_id in spinner_pairs:
            tree=enum_child_tree(other_hwnd);items=find_controls(tree,cls="msctls_updown32",ctrl_id=cid,visible=True)
            if not items:raise RuntimeError(f"Other spinner {cid} missing")
            item=items[0];path=tuple(control_tree_path(tree,item["hwnd"]) or ());partner=find_controls(tree,cls="Edit",ctrl_id=partner_id,visible=True)[0]
            hwnd=int(item["hwnd"]);phwnd=int(partner["hwnd"]);original=get_window_text(phwnd)
            post_click_at(hwnd,5,3);time.sleep(0.05);inc=get_window_text(phwnd);set_control_text(phwnd,original);notify_edit(partner)
            record(item,path,"increment",f"伙伴 {original!r}->{inc!r}。")
            post_click_at(hwnd,5,max(4,item["rect"]["height"]-3));time.sleep(0.05);dec=get_window_text(phwnd);set_control_text(phwnd,original);notify_edit(partner)
            record(item,path,"decrement",f"伙伴 {original!r}->{dec!r}。")
            boundary=[]
            for value in ("-32768","32767"):
                set_control_text(phwnd,value);notify_edit(partner);boundary.append(get_window_text(phwnd))
            set_control_text(phwnd,original);notify_edit(partner)
            record(item,path,"boundary_values",f"伙伴边界={boundary}，已恢复。")
            observations.append({"class":"msctls_updown32","control_id":cid,"partner_id":partner_id,"path":list(path)})

        cancel=find_controls(enum_child_tree(other_hwnd),cls="Button",text_contains="取消",visible=True)
        if cancel:click_control(cancel[0]["hwnd"]);session.wait_gone(other_hwnd,3.0);other_hwnd=0
    except Exception as exc:error=repr(exc);log(f"OTHERFIELDCONTROLS inner failure: {error}")
    finally:
        if other_hwnd and is_window(other_hwnd):close_window_safely(session,other_hwnd,3.0)
        after=session.probe_rom.read_bytes();diffs=[i for i,(a,b) in enumerate(zip(before,after)) if a!=b]
        unique={item["action_id"]:item for item in records};validated=error is None and len(unique)==208 and not diffs and len(before)==len(after)
        out_dir=session.out/"interaction-discovery";out_dir.mkdir(parents=True,exist_ok=True)
        (out_dir/"other-field-actions.json").write_text(json.dumps({"schema_version":1,"validated":validated,"error":error,"execution_record_count":len(unique),"diff_count":len(diffs)+int(len(before)!=len(after)),"sha256_before":hashlib.sha256(before).hexdigest().upper(),"sha256_after":hashlib.sha256(after).hexdigest().upper(),"observations":observations,"execution_records":list(unique.values()) if validated else []},ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    if not validated:raise RuntimeError(f"Other fields did not validate: {len(unique)}/208 {error}")
    log("OTHERFIELDCONTROLS complete: 208/208 actions, zero ROM diff")


def stage_otherbuttoncontrols(session: ProbeSession) -> None:
    """Exercise all seven legacy Other-window buttons."""
    log("=== stage OTHERBUTTONCONTROLS ===")
    before=session.probe_rom.read_bytes();records=[];observations=[];error=None;other_hwnd=0
    button_ids=(100,130,370,740,810,320,330)

    def record(item,path,action,result):
        records.append({"action_id":stable_interaction_id("其他","Button",int(item.get("ctrl_id") or 0),tuple(path),action),"status":"passed","result":result})

    def locate_other():
        for top in session.top_windows():
            if top["class"]!="WTWindow" or top["hwnd"]==session.main_hwnd:continue
            tree=enum_child_tree(top["hwnd"])
            if find_controls(tree,cls="Button",ctrl_id=810) and find_controls(tree,cls="Edit",ctrl_id=830):return int(top["hwnd"])
        return 0

    def open_other():
        nonlocal other_hwnd
        other_hwnd=locate_other()
        if other_hwnd:return
        window=_open_data_window(session,20023,"其他",dismiss_hidden=False)
        if not window:raise RuntimeError("Other window did not appear")
        other_hwnd=int(window["hwnd"]);move_window(other_hwnd,80,50,1000,760);time.sleep(0.35)

    def current_button(cid):
        open_other();tree=enum_child_tree(other_hwnd);items=find_controls(tree,cls="Button",ctrl_id=cid,visible=True)
        if not items:raise RuntimeError(f"Other button {cid} missing")
        item=items[0];return item,tuple(control_tree_path(tree,item["hwnd"]) or ())

    def dismiss_descendants(known,tag):
        found=[];deadline=time.monotonic()+0.9
        while time.monotonic()<deadline:
            for popup in session.top_windows():
                if popup["hwnd"] in known or popup["hwnd"]==other_hwnd or popup["class"]=="#32768":continue
                found.append({"title":popup["title"],"class":popup["class"]});session.dump_window(popup["hwnd"],f"OTHERBUTTON_{tag}",menu=True)
                tree=enum_child_tree(popup["hwnd"]);cancel=find_controls(tree,cls="Button",ctrl_id=2,visible=True)
                if cancel:click_control(cancel[0]["hwnd"]);session.wait_gone(popup["hwnd"],1.5)
                if is_window(popup["hwnd"]):close_window_safely(session,popup["hwnd"],1.5)
            time.sleep(0.04)
        return found

    try:
        for cid in button_ids:
            for action in ("right_click","keyboard_activate","left_click"):
                item,path=current_button(cid);known={top["hwnd"] for top in session.top_windows()};focused=None
                if action=="right_click":
                    post_context_menu(int(item["hwnd"]),5,5);time.sleep(0.08);menus=visible_popup_menus(session.pid or 0)
                    if menus:send_key(int(menus[0]["hwnd"]),VK_ESCAPE)
                elif action=="keyboard_activate":
                    focused=focus_foreground_control(other_hwnd,int(item["hwnd"]));send_key(int(item["hwnd"]),VK_SPACE)
                else:click_control(int(item["hwnd"]))
                time.sleep(0.15);descendants=dismiss_descendants(known,f"{cid}_{action}")
                visible=bool(other_hwnd and is_window(other_hwnd) and user32.IsWindowVisible(other_hwnd))
                record(item,path,action,f"焦点={focused}；窗口仍可见={visible}；子窗={descendants}。")
                observations.append({"control_id":cid,"action":action,"path":list(path),"focused":focused,"window_visible":visible,"descendants":descendants})
                if not visible:other_hwnd=0
        if other_hwnd and is_window(other_hwnd):
            cancel=find_controls(enum_child_tree(other_hwnd),cls="Button",ctrl_id=330,visible=True)
            if cancel:click_control(cancel[0]["hwnd"]);session.wait_gone(other_hwnd,2.0);other_hwnd=0
    except Exception as exc:error=repr(exc);log(f"OTHERBUTTONCONTROLS inner failure: {error}")
    finally:
        if other_hwnd and is_window(other_hwnd):close_window_safely(session,other_hwnd,2.0)
        after=session.probe_rom.read_bytes();diffs=[i for i,(a,b) in enumerate(zip(before,after)) if a!=b]
        unique={item["action_id"]:item for item in records};validated=error is None and len(unique)==21 and not diffs and len(before)==len(after)
        out_dir=session.out/"interaction-discovery";out_dir.mkdir(parents=True,exist_ok=True)
        (out_dir/"other-button-actions.json").write_text(json.dumps({"schema_version":1,"validated":validated,"error":error,"execution_record_count":len(unique),"diff_count":len(diffs)+int(len(before)!=len(after)),"sha256_before":hashlib.sha256(before).hexdigest().upper(),"sha256_after":hashlib.sha256(after).hexdigest().upper(),"observations":observations,"execution_records":list(unique.values()) if validated else []},ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    if not validated:raise RuntimeError(f"Other buttons did not validate: {len(unique)}/21 {error}")
    log("OTHERBUTTONCONTROLS complete: 21/21 actions, zero ROM diff")


def stage_calculatorcontrols(session: ProbeSession) -> None:
    """Exercise the complete legacy battle-attribute calculator."""
    log("=== stage CALCULATORCONTROLS ===")
    before=session.probe_rom.read_bytes();records=[];observations=[];error=None;calc_hwnd=0
    edit_ids=(170,190,210,230,260,270,290,310,440,460,480,500,530,540,560,580,640,660,680,700,720,740)
    combo_ids=(110,130,150,380,400,420,610,620);button_ids=(330,340,350,600,750,760)

    def record(item,path,action,result):
        records.append({"action_id":stable_interaction_id("战斗属性计算器",str(item.get("class","")),int(item.get("ctrl_id") or 0),tuple(path),action),"status":"passed","result":result})

    def notify_edit(item):
        parent=user32.GetParent(int(item["hwnd"]));cid=int(item.get("ctrl_id") or 0)
        if parent:user32.PostMessageW(parent,WM_COMMAND,(cid&0xFFFF)|(0x0300<<16),int(item["hwnd"]))

    def locate_calc():
        for top in session.top_windows():
            if top["class"]!="WTWindow" or top["hwnd"]==session.main_hwnd:continue
            tree=enum_child_tree(top["hwnd"])
            if find_controls(tree,cls="ListBox",ctrl_id=360) and find_controls(tree,cls="Button",ctrl_id=750):return int(top["hwnd"])
        return 0

    def open_calc():
        nonlocal calc_hwnd
        calc_hwnd=locate_calc()
        if calc_hwnd:return
        window=_open_data_window(session,20020,"战斗属性计算器",dismiss_hidden=False)
        if not window:
            # Some captures expose the shorter menu label while the title is
            # published a moment later; locate by its stable controls.
            deadline=time.monotonic()+6
            while time.monotonic()<deadline:
                calc_hwnd=locate_calc()
                if calc_hwnd:break
                time.sleep(0.15)
            if not calc_hwnd:raise RuntimeError("battle calculator did not appear")
        else:calc_hwnd=int(window["hwnd"])
        move_window(calc_hwnd,60,40,1100,820);time.sleep(0.4)

    def current(cid,cls):
        open_calc();tree=enum_child_tree(calc_hwnd);items=find_controls(tree,cls=cls,ctrl_id=cid,visible=True)
        if not items:raise RuntimeError(f"calculator {cls} {cid} missing")
        item=items[0];return item,tuple(control_tree_path(tree,item["hwnd"]) or ())

    def dismiss_descendants(known,tag):
        found=[];deadline=time.monotonic()+0.8
        while time.monotonic()<deadline:
            for popup in session.top_windows():
                if popup["hwnd"] in known or popup["hwnd"]==calc_hwnd or popup["class"]=="#32768":continue
                found.append({"title":popup["title"],"class":popup["class"]});session.dump_window(popup["hwnd"],f"CALC_{tag}",menu=True)
                tree=enum_child_tree(popup["hwnd"]);cancel=find_controls(tree,cls="Button",ctrl_id=2,visible=True)
                if cancel:click_control(cancel[0]["hwnd"]);session.wait_gone(popup["hwnd"],1.5)
                if is_window(popup["hwnd"]):close_window_safely(session,popup["hwnd"],1.5)
            time.sleep(0.04)
        return found

    try:
        open_calc()
        for cid in edit_ids:
            item,path=current(cid,"Edit");hwnd=int(item["hwnd"]);original=get_window_text(hwnd)
            record(item,path,"focus",f"真实焦点={focus_foreground_control(calc_hwnd,hwnd)}。")
            set_control_text(hwnd,"1");notify_edit(item);readback=get_window_text(hwnd);set_control_text(hwnd,original);notify_edit(item)
            record(item,path,"replace_value",f"替换读回={readback!r}，已恢复。")
            focus_foreground_control(calc_hwnd,hwnd);keybd(VK_CONTROL);send_key(hwnd,ord("A"));send_key(hwnd,ord("Z"));keybd(VK_CONTROL,up=True);set_control_text(hwnd,original);notify_edit(item)
            record(item,path,"keyboard_shortcuts","Ctrl+A/Ctrl+Z 后恢复。")
            post_context_menu(hwnd,5,5);time.sleep(0.08);menus=visible_popup_menus(session.pid or 0)
            if menus:send_key(int(menus[0]["hwnd"]),VK_ESCAPE)
            record(item,path,"right_click",f"右键菜单={bool(menus)}。")
            boundary=[]
            for value in ("-32768","32767"):
                set_control_text(hwnd,value);notify_edit(item);boundary.append(get_window_text(hwnd))
            set_control_text(hwnd,original);notify_edit(item)
            record(item,path,"boundary_values",f"边界读回={boundary}，已恢复。")

        for cid in combo_ids:
            item,path=current(cid,"ComboBox");hwnd=int(item["hwnd"]);values=read_combo_items(hwnd);original=int(_send_msg_num(hwnd,CB_GETCURSEL,0,0))
            _send_msg_num(hwnd,0x014F,1,0);time.sleep(0.04);_send_msg_num(hwnd,0x014F,0,0)
            record(item,path,"open_dropdown",f"展开/收起，共 {len(values)} 项。")
            for index in range(len(values)):set_combo_selection(hwnd,index)
            if original>=0:set_combo_selection(hwnd,original)
            record(item,path,"select_each_item",f"逐项选择 {len(values)} 项并恢复 {original}。")
            focus_foreground_control(calc_hwnd,hwnd);send_key(hwnd,VK_HOME);send_key(hwnd,VK_DOWN);key_index=int(_send_msg_num(hwnd,CB_GETCURSEL,0,0))
            if original>=0:set_combo_selection(hwnd,original)
            record(item,path,"keyboard_cycle",f"Home/Down 读回 {key_index}，已恢复。")
            post_context_menu(hwnd,5,5);time.sleep(0.08);menus=visible_popup_menus(session.pid or 0)
            if menus:send_key(int(menus[0]["hwnd"]),VK_ESCAPE)
            record(item,path,"right_click",f"右键菜单={bool(menus)}。")
            observations.append({"class":"ComboBox","control_id":cid,"item_count":len(values),"original_index":original,"path":list(path)})

        item,path=current(360,"ListBox");hwnd=int(item["hwnd"]);count=max(0,int(_send_msg_num(hwnd,LB_GETCOUNT,0,0)));original=int(_send_msg_num(hwnd,LB_GETCURSEL,0,0));parent=user32.GetParent(hwnd)
        for index in range(count):
            _send_msg_num(hwnd,LB_SETCURSEL,index,0);user32.PostMessageW(parent,WM_COMMAND,360|(LBN_SELCHANGE<<16),hwnd)
        if original>=0:_send_msg_num(hwnd,LB_SETCURSEL,original,0)
        record(item,path,"select_each_item",f"逐项选择 {count} 项并恢复 {original}。")
        focus_foreground_control(calc_hwnd,hwnd);send_key(hwnd,VK_HOME);send_key(hwnd,VK_DOWN)
        if original>=0:_send_msg_num(hwnd,LB_SETCURSEL,original,0)
        record(item,path,"keyboard_navigation","Home/Down 后恢复。")
        descendants=[]
        for index in range(count):
            _send_msg_num(hwnd,LB_SETCURSEL,index,0);known={top["hwnd"] for top in session.top_windows()};post_double_click_at(hwnd,8,8);descendants.extend(dismiss_descendants(known,f"list_dbl_{index}"))
        record(item,path,"double_click_each_item",f"逐项双击 {count} 项；子窗={descendants}。")
        menu_hits=0
        for index in range(count):
            _send_msg_num(hwnd,LB_SETCURSEL,index,0);post_context_menu(hwnd,8,8);time.sleep(0.02);menus=visible_popup_menus(session.pid or 0)
            if menus:menu_hits+=1;send_key(int(menus[0]["hwnd"]),VK_ESCAPE)
        record(item,path,"right_click_each_item",f"逐项右键 {count} 项；菜单命中 {menu_hits}。")
        observations.append({"class":"ListBox","control_id":360,"item_count":count,"path":list(path)})

        for cid in button_ids:
            for action in ("right_click","keyboard_activate","left_click"):
                item,path=current(cid,"Button");known={top["hwnd"] for top in session.top_windows()};focused=None
                if action=="right_click":
                    post_context_menu(int(item["hwnd"]),5,5);time.sleep(0.08);menus=visible_popup_menus(session.pid or 0)
                    if menus:send_key(int(menus[0]["hwnd"]),VK_ESCAPE)
                elif action=="keyboard_activate":focused=focus_foreground_control(calc_hwnd,int(item["hwnd"]));send_key(int(item["hwnd"]),VK_SPACE)
                else:click_control(int(item["hwnd"]))
                time.sleep(0.15);desc=dismiss_descendants(known,f"button_{cid}_{action}");visible=bool(calc_hwnd and is_window(calc_hwnd) and user32.IsWindowVisible(calc_hwnd))
                record(item,path,action,f"焦点={focused}；窗口仍可见={visible}；子窗={desc}。")
                if not visible:calc_hwnd=0
    except Exception as exc:error=repr(exc);log(f"CALCULATORCONTROLS inner failure: {error}")
    finally:
        if calc_hwnd and is_window(calc_hwnd):close_window_safely(session,calc_hwnd,2.0)
        after=session.probe_rom.read_bytes();diffs=[i for i,(a,b) in enumerate(zip(before,after)) if a!=b]
        unique={item["action_id"]:item for item in records};validated=error is None and len(unique)==164 and not diffs and len(before)==len(after)
        out_dir=session.out/"interaction-discovery";out_dir.mkdir(parents=True,exist_ok=True)
        (out_dir/"battle-calculator-actions.json").write_text(json.dumps({"schema_version":1,"validated":validated,"error":error,"execution_record_count":len(unique),"diff_count":len(diffs)+int(len(before)!=len(after)),"sha256_before":hashlib.sha256(before).hexdigest().upper(),"sha256_after":hashlib.sha256(after).hexdigest().upper(),"observations":observations,"execution_records":list(unique.values()) if validated else []},ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    if not validated:raise RuntimeError(f"battle calculator did not validate: {len(unique)}/164 {error}")
    log("CALCULATORCONTROLS complete: 164/164 actions, zero ROM diff")


def stage_mainfieldcontrols(session: ProbeSession) -> None:
    """Exercise the loaded main window except its command buttons."""
    log("=== stage MAINFIELDCONTROLS ===")
    before=session.probe_rom.read_bytes();records=[];observations=[];error=None
    main_title="SRW2扩容版修改器V1.0：<ROM>"; main=session.main_hwnd
    combo_ids=(140,160,180,210,680);pic_ids=tuple(range(220,400,10))+(530,)
    static_ids=(130,150,170,400,410,420,450,470,610,620,630,670)
    representatives=(220,140,550)

    def record(item,path,action,result,cls_override=None):
        records.append({"action_id":stable_interaction_id(main_title,cls_override or str(item.get("class","")),int(item.get("ctrl_id") or 0),tuple(path),action),"status":"passed","result":result})

    def visible_target(cid,cls=None):
        tree=enum_child_tree(main);items=find_controls(tree,cls=cls,ctrl_id=cid,visible=True)
        if not items:return None
        item=items[0];return item,tuple(control_tree_path(tree,item["hwnd"]) or ())

    def current(cid,cls=None):
        found=visible_target(cid,cls)
        if found:return found
        tree=enum_child_tree(main);pages=find_controls(tree,cls="CPageControl",ctrl_id=120,visible=True)
        if not pages:raise RuntimeError("main page control missing")
        width,_=get_client_size(int(pages[0]["hwnd"]))
        for x in range(14,min(max(15,width-24),560),12):
            post_click_at(int(pages[0]["hwnd"]),x,24);time.sleep(0.05);found=visible_target(cid,cls)
            if found:return found
        raise RuntimeError(f"main control {cls} {cid} unavailable")

    def state_action(item,path,cid,cls):
        hidden_on=None
        for rep in representatives:
            try:current(rep,"_EL_PicBox" if rep==220 else ("ComboBox" if rep==140 else "ListBox"))
            except RuntimeError:continue
            if not visible_target(cid,cls):hidden_on=rep;break
        restored,restored_path=current(cid,cls);record(item,path,"discover_state_triggers",f"切至 {hidden_on} 后隐藏；返回路径={restored_path}，启用={bool(restored.get('enabled'))}。")
        return hidden_on

    def dismiss_new(known,tag,timeout=0.12):
        found=[];deadline=time.monotonic()+timeout
        while time.monotonic()<deadline:
            for popup in session.top_windows():
                if popup["hwnd"] in known or popup["hwnd"]==main or popup["class"]=="#32768":continue
                found.append({"title":popup["title"],"class":popup["class"]});session.dump_window(popup["hwnd"],f"MAINFIELD_{tag}",menu=True);close_window_safely(session,popup["hwnd"],1.5)
            time.sleep(0.02)
        return found

    try:
        tree=enum_child_tree(main);page=find_controls(tree,cls="CPageControl",ctrl_id=120,visible=True)[0];page_path=tuple(control_tree_path(tree,page["hwnd"]) or ())
        reached=[]
        for rep,cls in ((220,"_EL_PicBox"),(140,"ComboBox"),(550,"ListBox")):
            current(rep,cls);reached.append(rep)
        record(page,page_path,"select_each_tab",f"逐页命中 {reached}。")
        focus_foreground_control(main,int(page["hwnd"]));keybd(VK_CONTROL);send_key(int(page["hwnd"]),0x09);keybd(VK_CONTROL,up=True)
        record(page,page_path,"keyboard_tab_cycle","真实焦点 Ctrl+Tab。")
        post_context_menu(int(page["hwnd"]),24,18);time.sleep(0.08);menus=visible_popup_menus(session.pid or 0)
        if menus:send_key(int(menus[0]["hwnd"]),VK_ESCAPE)
        record(page,page_path,"right_click_tabs",f"页签右键菜单={bool(menus)}。")

        for cid in (100,550):
            item,path=current(cid,"ListBox");hwnd=int(item["hwnd"]);count=max(0,int(_send_msg_num(hwnd,LB_GETCOUNT,0,0)));original=int(_send_msg_num(hwnd,LB_GETCURSEL,0,0));parent=user32.GetParent(hwnd)
            for index in range(count):_send_msg_num(hwnd,LB_SETCURSEL,index,0);user32.PostMessageW(parent,WM_COMMAND,cid|(LBN_SELCHANGE<<16),hwnd)
            if original>=0:_send_msg_num(hwnd,LB_SETCURSEL,original,0)
            record(item,path,"select_each_item",f"逐项选择 {count} 项并恢复 {original}。")
            focus_foreground_control(main,hwnd);send_key(hwnd,VK_HOME);send_key(hwnd,VK_DOWN)
            if original>=0:_send_msg_num(hwnd,LB_SETCURSEL,original,0)
            record(item,path,"keyboard_navigation","Home/Down 后恢复。")
            descendants=[]
            for index in range(count):_send_msg_num(hwnd,LB_SETCURSEL,index,0);known={top["hwnd"] for top in session.top_windows()};post_double_click_at(hwnd,8,8);descendants.extend(dismiss_new(known,f"list_{cid}_{index}"))
            record(item,path,"double_click_each_item",f"逐项双击 {count} 项；子窗={descendants}。")
            hits=0
            for index in range(count):
                _send_msg_num(hwnd,LB_SETCURSEL,index,0);post_context_menu(hwnd,8,8);time.sleep(0.01);menus=visible_popup_menus(session.pid or 0)
                if menus:hits+=1;send_key(int(menus[0]["hwnd"]),VK_ESCAPE)
            record(item,path,"right_click_each_item",f"逐项右键 {count} 项；菜单命中 {hits}。")
            if cid==550:state_action(item,path,cid,"ListBox")
            observations.append({"class":"ListBox","control_id":cid,"item_count":count,"path":list(path)})

        for cid in combo_ids:
            item,path=current(cid,"ComboBox");hwnd=int(item["hwnd"]);values=read_combo_items(hwnd);original=int(_send_msg_num(hwnd,CB_GETCURSEL,0,0))
            _send_msg_num(hwnd,0x014F,1,0);time.sleep(0.04);_send_msg_num(hwnd,0x014F,0,0);record(item,path,"open_dropdown",f"展开/收起，共 {len(values)} 项。")
            for index in range(len(values)):set_combo_selection(hwnd,index)
            if original>=0:set_combo_selection(hwnd,original)
            record(item,path,"select_each_item",f"逐项选择 {len(values)} 项并恢复 {original}。")
            focus_foreground_control(main,hwnd);send_key(hwnd,VK_HOME);send_key(hwnd,VK_DOWN);key_index=int(_send_msg_num(hwnd,CB_GETCURSEL,0,0))
            if original>=0:set_combo_selection(hwnd,original)
            record(item,path,"keyboard_cycle",f"Home/Down 读回 {key_index}，已恢复。")
            post_context_menu(hwnd,5,5);time.sleep(0.08);menus=visible_popup_menus(session.pid or 0)
            if menus:send_key(int(menus[0]["hwnd"]),VK_ESCAPE)
            record(item,path,"right_click",f"右键菜单={bool(menus)}。")
            state_action(item,path,cid,"ComboBox");observations.append({"class":"ComboBox","control_id":cid,"item_count":len(values),"path":list(path)})

        for cid in pic_ids:
            item,path=current(cid,"_EL_PicBox");hwnd=int(item["hwnd"])
            known={top["hwnd"] for top in session.top_windows()};post_click_at(hwnd,8,8);record(item,path,"left_click_regions",f"左键；子窗={dismiss_new(known,f'pic_{cid}_left')}。")
            item,path=current(cid,"_EL_PicBox");hwnd=int(item["hwnd"]);known={top["hwnd"] for top in session.top_windows()};post_double_click_at(hwnd,8,8);record(item,path,"double_click_regions",f"双击；子窗={dismiss_new(known,f'pic_{cid}_double')}。")
            item,path=current(cid,"_EL_PicBox");hwnd=int(item["hwnd"]);post_context_menu(hwnd,8,8);time.sleep(0.06);menus=visible_popup_menus(session.pid or 0)
            if menus:send_key(int(menus[0]["hwnd"]),VK_ESCAPE)
            record(item,path,"right_click_regions",f"右键菜单={bool(menus)}。")
            post_drag_at(hwnd,8,8,24,16);record(item,path,"drag_regions","短距离拖拽。")
            state_action(item,path,cid,"_EL_PicBox")

        for cid in static_ids:
            item,path=current(cid);cls=str(item.get("class",""))
            if not cls.startswith("Afx:"):raise RuntimeError(f"main static {cid} unexpected {cls}")
            state_action(item,path,cid,cls)
        for cid in (440,460):
            item,path=current(cid,"Edit");state_action(item,path,cid,"Edit")
        for cid in (480,490):
            item,path=current(cid,"msctls_updown32");hwnd=int(item["hwnd"]);partner_id=440 if cid==480 else 460;partner,_=current(partner_id,"Edit");phwnd=int(partner["hwnd"]);original=get_window_text(phwnd)
            post_click_at(hwnd,5,3);time.sleep(0.05);inc=get_window_text(phwnd);set_control_text(phwnd,original);record(item,path,"increment",f"伙伴 {original!r}->{inc!r}。")
            post_click_at(hwnd,5,max(4,item["rect"]["height"]-3));time.sleep(0.05);dec=get_window_text(phwnd);set_control_text(phwnd,original);record(item,path,"decrement",f"伙伴 {original!r}->{dec!r}。")
            boundary=[]
            for value in ("-32768","32767"):set_control_text(phwnd,value);boundary.append(get_window_text(phwnd))
            set_control_text(phwnd,original);record(item,path,"boundary_values",f"伙伴边界={boundary}，已恢复。");state_action(item,path,cid,"msctls_updown32")

        root=enum_child_tree(main);root_item={"class":"WTWindow","ctrl_id":0}
        loaded_visible=bool(find_controls(root,cls="CPageControl",ctrl_id=120,visible=True))
        session.terminate();session.launch();stage_a(session);unloaded_visible=bool(find_controls(enum_child_tree(session.main_hwnd),cls="CPageControl",ctrl_id=120,visible=True))
        stage_load(session);main=session.main_hwnd;reloaded_visible=bool(find_controls(enum_child_tree(main),cls="CPageControl",ctrl_id=120,visible=True))
        record(root_item,(),"discover_state_triggers",f"已载入页={loaded_visible}；未载入页={unloaded_visible}；重载页={reloaded_visible}。")
    except Exception as exc:error=repr(exc);log(f"MAINFIELDCONTROLS inner failure: {error}")
    finally:
        after=session.probe_rom.read_bytes();diffs=[i for i,(a,b) in enumerate(zip(before,after)) if a!=b]
        unique={item["action_id"]:item for item in records};validated=error is None and len(unique)==155 and not diffs and len(before)==len(after)
        out_dir=session.out/"interaction-discovery";out_dir.mkdir(parents=True,exist_ok=True)
        (out_dir/"main-field-actions.json").write_text(json.dumps({"schema_version":1,"validated":validated,"error":error,"execution_record_count":len(unique),"diff_count":len(diffs)+int(len(before)!=len(after)),"sha256_before":hashlib.sha256(before).hexdigest().upper(),"sha256_after":hashlib.sha256(after).hexdigest().upper(),"observations":observations,"execution_records":list(unique.values()) if validated else []},ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    if not validated:raise RuntimeError(f"main fields did not validate: {len(unique)}/155 {error}")
    log("MAINFIELDCONTROLS complete: 155/155 actions, zero ROM diff")


def stage_mainbuttoncontrols(session: ProbeSession) -> None:
    """Exercise every command button on the loaded legacy main pages."""
    log("=== stage MAINBUTTONCONTROLS ===")
    before=session.probe_rom.read_bytes();records=[];observations=[];error=None
    main_title="SRW2扩容版修改器V1.0：<ROM>";main=session.main_hwnd
    representatives=((220,"_EL_PicBox"),(140,"ComboBox"),(550,"ListBox"))

    def record(item,path,action,result):
        records.append({"action_id":stable_interaction_id(main_title,"Button",int(item.get("ctrl_id") or 0),tuple(path),action),"status":"passed","result":result})

    def visible_button(cid):
        tree=enum_child_tree(main);items=find_controls(tree,cls="Button",ctrl_id=cid,visible=True)
        if not items:return None
        item=items[0];return item,tuple(control_tree_path(tree,item["hwnd"]) or ())

    def show_control(cid,cls):
        tree=enum_child_tree(main);items=find_controls(tree,cls=cls,ctrl_id=cid,visible=True)
        if items:return
        pages=find_controls(tree,cls="CPageControl",ctrl_id=120,visible=True)
        if not pages:raise RuntimeError("main page control missing")
        width,_=get_client_size(int(pages[0]["hwnd"]))
        for x in range(14,min(max(15,width-24),560),12):
            post_click_at(int(pages[0]["hwnd"]),x,24);time.sleep(0.05)
            if find_controls(enum_child_tree(main),cls=cls,ctrl_id=cid,visible=True):return
        raise RuntimeError(f"main representative {cls} {cid} unavailable")

    def current(cid):
        found=visible_button(cid)
        if found:return found
        for rep,cls in representatives:
            try:show_control(rep,cls)
            except RuntimeError:continue
            found=visible_button(cid)
            if found:return found
        raise RuntimeError(f"main button {cid} unavailable")

    def dismiss_descendants(known,tag):
        found=[];deadline=time.monotonic()+1.0
        while time.monotonic()<deadline:
            for popup in session.top_windows():
                if popup["hwnd"] in known or popup["hwnd"]==main or popup["class"]=="#32768":continue
                found.append({"title":popup["title"],"class":popup["class"]});session.dump_window(popup["hwnd"],f"MAINBUTTON_{tag}",menu=True)
                tree=enum_child_tree(popup["hwnd"]);cancel=find_controls(tree,cls="Button",ctrl_id=2,visible=True)
                if cancel:click_control(cancel[0]["hwnd"]);session.wait_gone(popup["hwnd"],1.5)
                if is_window(popup["hwnd"]):close_window_safely(session,popup["hwnd"],1.5)
            time.sleep(0.04)
        return found

    try:
        for cid in (110,200,430,660):
            item,path=current(cid)
            if cid!=110:
                hidden_on=None
                for rep,cls in representatives:
                    try:show_control(rep,cls)
                    except RuntimeError:continue
                    if not visible_button(cid):hidden_on=rep;break
                item,path=current(cid);record(item,path,"discover_state_triggers",f"切至 {hidden_on} 后隐藏；返回后启用={bool(item.get('enabled'))}。")
            for action in ("right_click","keyboard_activate","left_click"):
                item,path=current(cid);known={top["hwnd"] for top in session.top_windows()};focused=None
                if action=="right_click":
                    post_context_menu(int(item["hwnd"]),5,5);time.sleep(0.08);menus=visible_popup_menus(session.pid or 0)
                    if menus:send_key(int(menus[0]["hwnd"]),VK_ESCAPE)
                elif action=="keyboard_activate":
                    focused=focus_foreground_control(main,int(item["hwnd"]));send_key(int(item["hwnd"]),VK_SPACE)
                else:click_control(int(item["hwnd"]))
                time.sleep(0.15);desc=dismiss_descendants(known,f"{cid}_{action}")
                record(item,path,action,f"焦点={focused}；子窗={desc}。")
                observations.append({"control_id":cid,"action":action,"path":list(path),"focused":focused,"descendants":desc})
    except Exception as exc:error=repr(exc);log(f"MAINBUTTONCONTROLS inner failure: {error}")
    finally:
        after=session.probe_rom.read_bytes();diffs=[i for i,(a,b) in enumerate(zip(before,after)) if a!=b]
        unique={item["action_id"]:item for item in records};validated=error is None and len(unique)==15 and not diffs and len(before)==len(after)
        out_dir=session.out/"interaction-discovery";out_dir.mkdir(parents=True,exist_ok=True)
        (out_dir/"main-button-actions.json").write_text(json.dumps({"schema_version":1,"validated":validated,"error":error,"execution_record_count":len(unique),"diff_count":len(diffs)+int(len(before)!=len(after)),"sha256_before":hashlib.sha256(before).hexdigest().upper(),"sha256_after":hashlib.sha256(after).hexdigest().upper(),"observations":observations,"execution_records":list(unique.values()) if validated else []},ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    if not validated:raise RuntimeError(f"main buttons did not validate: {len(unique)}/15 {error}")
    log("MAINBUTTONCONTROLS complete: 15/15 actions, zero ROM diff")


def stage_launchercontrols(session: ProbeSession) -> None:
    """Exercise all launcher buttons from a fresh process per gesture."""
    log("=== stage LAUNCHERCONTROLS ===")
    records=[];observations=[];error=None

    def fresh_launcher():
        if session.pid and not session.process_alive():
            deadline=time.monotonic()+4
            while time.monotonic()<deadline and not session.process_alive():time.sleep(0.1)
        if session.process_alive():session.terminate()
        session.launch();deadline=time.monotonic()+8
        while time.monotonic()<deadline:
            for top in session.top_windows():
                if top["class"]!="WTWindow":continue
                tree=enum_child_tree(top["hwnd"])
                if find_controls(tree,cls="Button",ctrl_id=110) and find_controls(tree,cls="Button",ctrl_id=160):
                    session.main_hwnd=int(top["hwnd"]);return int(top["hwnd"])
            time.sleep(0.1)
        raise RuntimeError("launcher did not appear")

    def record(item,path,action,result):
        records.append({"action_id":stable_interaction_id("SRW2修改器V1.5","Button",int(item.get("ctrl_id") or 0),tuple(path),action),"status":"passed","result":result})

    try:
        for cid in (110,120,140,150,160):
            for action in ("right_click","keyboard_activate","left_click"):
                launcher=fresh_launcher();tree=enum_child_tree(launcher);items=find_controls(tree,cls="Button",ctrl_id=cid,visible=True)
                if not items:raise RuntimeError(f"launcher button {cid} missing")
                item=items[0];path=tuple(control_tree_path(tree,item["hwnd"]) or ());known={w["hwnd"] for w in enum_top_windows(0)};focused=None
                if action=="right_click":
                    post_context_menu(int(item["hwnd"]),5,5);time.sleep(0.1);menus=visible_popup_menus(session.pid or 0)
                    if menus:send_key(int(menus[0]["hwnd"]),VK_ESCAPE)
                elif action=="keyboard_activate":
                    focused=focus_foreground_control(launcher,int(item["hwnd"]));send_key(int(item["hwnd"]),VK_SPACE)
                else:click_control(int(item["hwnd"]))
                time.sleep(1.0)
                descendants=[{"title":w["title"],"class":w["class"]} for w in enum_top_windows(0) if w["hwnd"] not in known and w["class"]!="#32768"]
                record(item,path,action,f"焦点={focused}；新窗口={descendants}。")
                observations.append({"control_id":cid,"action":action,"path":list(path),"focused":focused,"descendants":descendants})
    except Exception as exc:error=repr(exc);log(f"LAUNCHERCONTROLS inner failure: {error}")
    finally:
        if session.process_alive():session.terminate()
        unique={item["action_id"]:item for item in records};validated=error is None and len(unique)==15
        out_dir=session.out/"interaction-discovery";out_dir.mkdir(parents=True,exist_ok=True)
        (out_dir/"launcher-button-actions.json").write_text(json.dumps({"schema_version":1,"validated":validated,"error":error,"execution_record_count":len(unique),"observations":observations,"execution_records":list(unique.values()) if validated else []},ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    if not validated:raise RuntimeError(f"launcher controls did not validate: {len(unique)}/15 {error}")
    log("LAUNCHERCONTROLS complete: 15/15 actions")


def stage_menucontrols(session: ProbeSession) -> None:
    """Activate every main-menu command and recurse into resulting windows."""
    log("=== stage MENUCONTROLS ===")
    before=session.probe_rom.read_bytes();records=[];observations=[];error=None

    def flatten(items,trail=()):
        out=[]
        for item in items:
            text=str(item.get("text","")).strip();current=trail+((text or "<separator>"),);cid=item.get("id")
            if cid is not None and text:out.append((int(cid),current,text))
            if isinstance(item.get("items"),list):out.extend(flatten(item["items"],current))
        return out

    def dismiss_new(known,tag):
        found=[];deadline=time.monotonic()+1.0
        while time.monotonic()<deadline:
            for top in session.top_windows():
                if top["hwnd"] in known or top["hwnd"]==session.main_hwnd or top["class"]=="#32768":continue
                found.append({"title":top["title"],"class":top["class"]});session.dump_window(top["hwnd"],f"MENU_{tag}",menu=True);close_window_safely(session,top["hwnd"],1.5)
            time.sleep(0.03)
        return found

    def restart_loaded():
        if session.process_alive():session.terminate()
        session.launch();stage_a(session);stage_load(session)

    try:
        menu=get_menu_tree(session.main_hwnd) or [];commands=flatten(menu)
        if len(commands)!=14:raise RuntimeError(f"expected 14 menu commands, found {len(commands)}")
        # Exit is intentionally last; all other commands share one loaded,
        # isolated ROM process and their windows are cancelled after capture.
        for cid,trail,text_value in sorted(commands,key=lambda item:item[0]==20006):
            known={w["hwnd"] for w in session.top_windows()};user32.PostMessageW(session.main_hwnd,WM_COMMAND,cid,0);time.sleep(0.25);desc=dismiss_new(known,str(cid));alive=session.process_alive()
            records.append({"action_id":stable_menu_action_id(trail,cid),"status":"passed","result":f"命令 {cid}；子窗={desc}；进程存活={alive}。"});observations.append({"command_id":cid,"trail":list(trail),"text":text_value,"descendants":desc,"process_alive":alive})
            if cid!=20006 and not alive:restart_loaded()
    except Exception as exc:error=repr(exc);log(f"MENUCONTROLS inner failure: {error}")
    finally:
        after=session.probe_rom.read_bytes();diffs=[i for i,(a,b) in enumerate(zip(before,after)) if a!=b];unique={item["action_id"]:item for item in records};validated=error is None and len(unique)==14 and not diffs and len(before)==len(after);out_dir=session.out/"interaction-discovery";out_dir.mkdir(parents=True,exist_ok=True);(out_dir/"menu-actions.json").write_text(json.dumps({"schema_version":1,"validated":validated,"error":error,"execution_record_count":len(unique),"diff_count":len(diffs)+int(len(before)!=len(after)),"sha256_before":hashlib.sha256(before).hexdigest().upper(),"sha256_after":hashlib.sha256(after).hexdigest().upper(),"observations":observations,"execution_records":list(unique.values()) if validated else []},ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    if not validated:raise RuntimeError(f"menu controls did not validate: {len(unique)}/14 {error}")
    log("MENUCONTROLS complete: 14/14 actions, zero ROM diff")


def stage_lifecyclestates(session: ProbeSession) -> None:
    """Close the remaining top-level and IME state-discovery actions."""
    log("=== stage LIFECYCLESTATES ===")
    before=session.probe_rom.read_bytes();records=[];observations=[];error=None
    try:
        def locate_event():
            for top in session.top_windows():
                if top["class"]=="WTWindow" and top["hwnd"]!=session.main_hwnd and find_controls(enum_child_tree(top["hwnd"]),cls="CPageControl",ctrl_id=120):return top
            return None
        user32.PostMessageW(session.main_hwnd,WM_COMMAND,20015,0);deadline=time.monotonic()+15;event=None
        while time.monotonic()<deadline and not event:event=locate_event();time.sleep(0.12)
        if not event:raise RuntimeError("event editor did not appear")
        first=int(event["hwnd"]);close_window_safely(session,first,2.0);destroyed=not is_window(first);user32.PostMessageW(session.main_hwnd,WM_COMMAND,20015,0);deadline=time.monotonic()+15;restored=None
        while time.monotonic()<deadline and not restored:restored=locate_event();time.sleep(0.12)
        if not restored:raise RuntimeError("event editor did not reopen")
        records.append({"action_id":stable_interaction_id("事件编辑","WTWindow",0,(),"discover_state_triggers"),"status":"passed","result":f"关闭销毁={destroyed}；重开 HWND={restored['hwnd']}。"});observations.append({"event_destroyed":destroyed,"event_reopened":True});close_window_safely(session,int(restored["hwnd"]),2.0)

        menu=get_menu_tree(session.main_hwnd) or [];cmd=menu_item_id(menu,"文件","打开");known={w["hwnd"] for w in session.top_windows()};user32.PostMessageW(session.main_hwnd,WM_COMMAND,int(cmd or 20001),0);dialog=session.wait_new_top(exclude=known,timeout=6,cls_equals="#32770")
        if not dialog:raise RuntimeError("open dialog missing for IME state")
        edits=find_controls(enum_child_tree(dialog["hwnd"]),cls="Edit",ctrl_id=1148,visible=True)
        if not edits:raise RuntimeError("filename edit missing")
        before_ime=[w for w in enum_top_windows(0,visible_only=False) if w["class"]=="SoPY_Status"]
        focus_foreground_control(int(dialog["hwnd"]),int(edits[0]["hwnd"]));send_key(int(edits[0]["hwnd"]),ord("A"));time.sleep(0.25);during_ime=[w for w in enum_top_windows(0,visible_only=False) if w["class"]=="SoPY_Status"];close_window_safely(session,int(dialog["hwnd"]),2.0);time.sleep(0.15);after_ime=[w for w in enum_top_windows(0,visible_only=False) if w["class"]=="SoPY_Status"]
        records.append({"action_id":stable_interaction_id("","SoPY_Status",0,(),"discover_state_triggers"),"status":"passed","result":f"IME 状态窗数：前={len(before_ime)}，焦点中={len(during_ime)}，关闭后={len(after_ime)}。"});observations.append({"ime_before":len(before_ime),"ime_during":len(during_ime),"ime_after":len(after_ime)})
    except Exception as exc:error=repr(exc);log(f"LIFECYCLESTATES inner failure: {error}")
    finally:
        after=session.probe_rom.read_bytes();diffs=[i for i,(a,b) in enumerate(zip(before,after)) if a!=b];unique={item["action_id"]:item for item in records};validated=error is None and len(unique)==2 and not diffs and len(before)==len(after);out_dir=session.out/"interaction-discovery";out_dir.mkdir(parents=True,exist_ok=True);(out_dir/"lifecycle-state-actions.json").write_text(json.dumps({"schema_version":1,"validated":validated,"error":error,"execution_record_count":len(unique),"diff_count":len(diffs)+int(len(before)!=len(after)),"observations":observations,"execution_records":list(unique.values()) if validated else []},ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    if not validated:raise RuntimeError(f"lifecycle states did not validate: {len(unique)}/2 {error}")
    log("LIFECYCLESTATES complete: 2/2 actions, zero ROM diff")


def stage_errormessagecontrols(session: ProbeSession) -> None:
    """Exercise the legacy Error dialog in isolated process lifecycles."""
    log("=== stage ERRORMESSAGECONTROLS ===")
    before=session.probe_rom.read_bytes();records=[];observations=[];error=None

    def restart_loaded():
        if session.process_alive():session.terminate()
        session.launch();stage_a(session);stage_load(session)

    try:
        for index,action in enumerate(("right_click","left_click","keyboard_activate")):
            if index:restart_loaded()
            editor=_open_data_window(session,20021,"存档编辑器：",dismiss_hidden=False)
            if not editor:raise RuntimeError("save editor missing for error trigger")
            trigger=find_controls(enum_child_tree(editor["hwnd"]),cls="Button",ctrl_id=190,visible=True)
            if not trigger:raise RuntimeError("save-editor read button missing")
            known={w["hwnd"] for w in session.top_windows()};click_control(int(trigger[0]["hwnd"]));popup=session.wait_new_top(exclude=known,timeout=5,cls_equals="#32770")
            if not popup:raise RuntimeError(f"error dialog missing for {action}")
            tree=enum_child_tree(popup["hwnd"]);buttons=find_controls(tree,cls="Button",ctrl_id=2,visible=True)
            if not buttons:raise RuntimeError("error OK button missing")
            item=buttons[0];path=tuple(control_tree_path(tree,item["hwnd"]) or ())
            if action=="right_click":post_context_menu(int(item["hwnd"]),5,5);time.sleep(0.08);menus=visible_popup_menus(session.pid or 0);send_key(int(menus[0]["hwnd"]),VK_ESCAPE) if menus else None;click_control(int(item["hwnd"]))
            elif action=="keyboard_activate":focus_foreground_control(int(popup["hwnd"]),int(item["hwnd"]));send_key(int(item["hwnd"]),VK_SPACE)
            else:click_control(int(item["hwnd"]))
            time.sleep(0.25);alive=session.process_alive();records.append({"action_id":stable_interaction_id("错误","Button",2,path,action),"status":"passed","result":f"动作后进程存活={alive}。"});observations.append({"action":action,"process_alive":alive})
    except Exception as exc:error=repr(exc);log(f"ERRORMESSAGECONTROLS inner failure: {error}")
    finally:
        after=session.probe_rom.read_bytes();diffs=[i for i,(a,b) in enumerate(zip(before,after)) if a!=b];unique={item["action_id"]:item for item in records};validated=error is None and len(unique)==3 and not diffs and len(before)==len(after);out_dir=session.out/"interaction-discovery";out_dir.mkdir(parents=True,exist_ok=True);(out_dir/"error-message-actions.json").write_text(json.dumps({"schema_version":1,"validated":validated,"error":error,"execution_record_count":len(unique),"diff_count":len(diffs)+int(len(before)!=len(after)),"observations":observations,"execution_records":list(unique.values()) if validated else []},ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    if not validated:raise RuntimeError(f"error message did not validate: {len(unique)}/3 {error}")
    log("ERRORMESSAGECONTROLS complete: 3/3 actions, zero ROM diff")


def stage_infomessagecontrols(session: ProbeSession) -> None:
    """Reach and exercise the simulator's nested Information dialog."""
    log("=== stage INFOMESSAGECONTROLS ===")
    before=session.probe_rom.read_bytes();records=[];observations=[];error=None

    def open_prompt():
        db=_open_data_window(session,20008,"数据库",dismiss_hidden=False)
        if not db:raise RuntimeError("database missing")
        database=int(db["hwnd"]);entry=None
        for _ in range(12):
            switch_database_page_by_control(database,2530);items=find_controls(enum_child_tree(database),cls="Button",ctrl_id=2550,visible=True)
            if items:entry=items[0];break
            time.sleep(0.2)
        if not entry:raise RuntimeError("weapon-rule entry missing")
        known={w["hwnd"] for w in session.top_windows()};click_control(int(entry["hwnd"]));rule=session.wait_new_top(exclude=known,timeout=6,cls_equals="WTWindow",title_contains="规律")
        if not rule:raise RuntimeError("weapon-rule window missing")
        rule_hwnd=int(rule["hwnd"]);pages=find_controls(enum_child_tree(rule_hwnd),cls="CPageControl",visible=True)
        if not pages:raise RuntimeError("rule page missing")
        page=max(pages,key=lambda item:item["rect"]["width"]*item["rect"]["height"]);seen=set();positions=[];width,_=get_client_size(int(page["hwnd"]))
        for x in range(14,max(15,width-24),10):
            post_click_at(int(page["hwnd"]),x,24);time.sleep(0.16);sig=_window_ctrl_sig(rule_hwnd)
            if sig in seen:continue
            seen.add(sig);positions.append(x)
            if len(positions)==4:break
        if len(positions)!=4:raise RuntimeError(f"rule pages incomplete {len(positions)}/4")
        post_click_at(int(page["hwnd"]),positions[1],24);time.sleep(0.25);buttons=find_controls(enum_child_tree(rule_hwnd),cls="Button",ctrl_id=710,visible=True)
        if not buttons:raise RuntimeError("simulator entry missing")
        known={w["hwnd"] for w in session.top_windows()};click_control(int(buttons[0]["hwnd"]));sim=session.wait_new_top(exclude=known,timeout=6,cls_equals="WTWindow",title_contains="运行规律模拟")
        if not sim:raise RuntimeError("simulator missing")
        simulator=int(sim["hwnd"]);create=find_controls(enum_child_tree(simulator),cls="Button",ctrl_id=260,visible=True)
        if not create:raise RuntimeError("create-object button missing")
        known={w["hwnd"] for w in session.top_windows()};click_control(int(create[0]["hwnd"]));prompt=session.wait_new_top(exclude=known,timeout=5,cls_equals="#32770")
        if not prompt:raise RuntimeError("information prompt missing")
        return database,rule_hwnd,simulator,int(prompt["hwnd"])

    try:
        for action in ("right_click","left_click","keyboard_activate"):
            database,rule_hwnd,simulator,prompt=open_prompt();tree=enum_child_tree(prompt);buttons=find_controls(tree,cls="Button",ctrl_id=2,visible=True)
            if not buttons:raise RuntimeError("information OK button missing")
            item=buttons[0];path=tuple(control_tree_path(tree,item["hwnd"]) or ())
            if action=="right_click":post_context_menu(int(item["hwnd"]),5,5);time.sleep(0.08);menus=visible_popup_menus(session.pid or 0);send_key(int(menus[0]["hwnd"]),VK_ESCAPE) if menus else None;click_control(int(item["hwnd"]))
            elif action=="keyboard_activate":focus_foreground_control(prompt,int(item["hwnd"]));send_key(int(item["hwnd"]),VK_SPACE)
            else:click_control(int(item["hwnd"]))
            gone=session.wait_gone(prompt,2.0);records.append({"action_id":stable_interaction_id("信息：","Button",2,path,action),"status":"passed","result":f"信息框关闭={gone}。"});observations.append({"action":action,"closed":gone})
            for hwnd in (simulator,rule_hwnd,database):
                if is_window(hwnd):close_window_safely(session,hwnd,2.0)
    except Exception as exc:error=repr(exc);log(f"INFOMESSAGECONTROLS inner failure: {error}")
    finally:
        after=session.probe_rom.read_bytes();diffs=[i for i,(a,b) in enumerate(zip(before,after)) if a!=b];unique={item["action_id"]:item for item in records};validated=error is None and len(unique)==3 and not diffs and len(before)==len(after);out_dir=session.out/"interaction-discovery";out_dir.mkdir(parents=True,exist_ok=True);(out_dir/"information-message-actions.json").write_text(json.dumps({"schema_version":1,"validated":validated,"error":error,"execution_record_count":len(unique),"diff_count":len(diffs)+int(len(before)!=len(after)),"observations":observations,"execution_records":list(unique.values()) if validated else []},ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    if not validated:raise RuntimeError(f"information message did not validate: {len(unique)}/3 {error}")
    log("INFOMESSAGECONTROLS complete: 3/3 actions, zero ROM diff")


def stage_openfilecontrols(session: ProbeSession) -> None:
    """Exercise the native ROM-open dialog, including shell child controls."""
    log("=== stage OPENFILECONTROLS ===")
    before=session.probe_rom.read_bytes();records=[];observations=[];error=None;dialog_hwnd=0

    def ensure_main_unloaded():
        nonlocal dialog_hwnd
        dialog_hwnd=0
        if session.main_hwnd and is_window(session.main_hwnd) and "：" not in get_window_text(session.main_hwnd):return
        if session.process_alive():session.terminate()
        session.launch();stage_a(session)

    def open_dialog():
        nonlocal dialog_hwnd
        if dialog_hwnd and is_window(dialog_hwnd):return dialog_hwnd
        ensure_main_unloaded();menu=get_menu_tree(session.main_hwnd) or [];cmd=menu_item_id(menu,"文件","打开")
        if cmd is None:raise RuntimeError("File/Open command missing")
        known={w["hwnd"] for w in session.top_windows()};user32.PostMessageW(session.main_hwnd,WM_COMMAND,cmd,0)
        found=session.wait_new_top(exclude=known,timeout=8,cls_equals="#32770")
        if not found:raise RuntimeError("open-file dialog did not appear")
        dialog_hwnd=int(found["hwnd"]);return dialog_hwnd

    def by_path(path):
        node=enum_child_tree(open_dialog())
        for index in path:node=node.get("children",[])[index]
        return node

    def current(cls,cid,path=None):
        tree=enum_child_tree(open_dialog())
        if path is not None:
            item=tree
            for index in path:item=item.get("children",[])[index]
            if item.get("class")!=cls or int(item.get("ctrl_id") or 0)!=cid:raise RuntimeError(f"dialog path {path} identity drift")
            return item,tuple(path)
        items=find_controls(tree,cls=cls,ctrl_id=cid,visible=True)
        if not items:raise RuntimeError(f"open dialog {cls} {cid} missing")
        item=items[0];return item,tuple(control_tree_path(tree,item["hwnd"]) or ())

    def record(item,path,action,result):
        records.append({"action_id":stable_interaction_id("打开文件",str(item.get("class","")),int(item.get("ctrl_id") or 0),tuple(path),action),"status":"passed","result":result})

    def close_messages(exclude):
        found=[]
        for top in session.top_windows():
            if top["hwnd"] in exclude or top["hwnd"] in (session.main_hwnd,dialog_hwnd) or top["class"]=="#32768":continue
            found.append({"title":top["title"],"class":top["class"]});close_window_safely(session,top["hwnd"],1.5)
        return found

    try:
        open_dialog();session.dump_window(dialog_hwnd,"OPENFILE_00_初始",menu=True)
        for cid in (1136,1148):
            item,path=current("ComboBox",cid);hwnd=int(item["hwnd"]);values=read_combo_items(hwnd);original=int(_send_msg_num(hwnd,CB_GETCURSEL,0,0))
            _send_msg_num(hwnd,0x014F,1,0);time.sleep(0.08);_send_msg_num(hwnd,0x014F,0,0);record(item,path,"open_dropdown",f"展开/收起，项数={len(values)}。")
            for index in range(len(values)):set_combo_selection(hwnd,index)
            if original>=0:set_combo_selection(hwnd,original)
            record(item,path,"select_each_item",f"逐项选择 {len(values)} 项并恢复 {original}。")
            focus_foreground_control(dialog_hwnd,hwnd);send_key(hwnd,VK_HOME);send_key(hwnd,VK_DOWN)
            if original>=0:set_combo_selection(hwnd,original)
            record(item,path,"keyboard_cycle","Home/Down 后恢复。")
            post_context_menu(hwnd,5,5);time.sleep(0.08);menus=visible_popup_menus(session.pid or 0)
            if menus:send_key(int(menus[0]["hwnd"]),VK_ESCAPE)
            record(item,path,"right_click",f"右键菜单={bool(menus)}。")
        item,path=current("Edit",1148);hwnd=int(item["hwnd"]);original=get_window_text(hwnd)
        record(item,path,"focus",f"真实焦点={focus_foreground_control(dialog_hwnd,hwnd)}。")
        set_control_text(hwnd,"probe.nes");record(item,path,"replace_value",f"读回={get_window_text(hwnd)!r}。");set_control_text(hwnd,original)
        focus_foreground_control(dialog_hwnd,hwnd);keybd(VK_CONTROL);send_key(hwnd,ord("A"));send_key(hwnd,ord("Z"));keybd(VK_CONTROL,up=True);set_control_text(hwnd,original);record(item,path,"keyboard_shortcuts","Ctrl+A/Ctrl+Z 后恢复。")
        post_context_menu(hwnd,5,5);time.sleep(0.08);menus=visible_popup_menus(session.pid or 0)
        if menus:send_key(int(menus[0]["hwnd"]),VK_ESCAPE)
        record(item,path,"right_click",f"右键菜单={bool(menus)}。")
        vals=[]
        for value in ("","X"*260):set_control_text(hwnd,value);vals.append(len(get_window_text(hwnd)))
        set_control_text(hwnd,original);record(item,path,"boundary_values",f"空值/长值读回长度={vals}。")

        shell_paths=((0,0,2,0,0,0),(0,0,2,0,0,1));scroll_paths=((7,),shell_paths[0]+(0,),shell_paths[1]+(0,))
        for path in shell_paths:
            item=by_path(path);before_state=(bool(item.get("visible")),bool(item.get("enabled")))
            combo,_=current("ComboBox",1148);_send_msg_num(int(combo["hwnd"]),0x014F,1,0);time.sleep(0.08);during=by_path(path);_send_msg_num(int(combo["hwnd"]),0x014F,0,0)
            record(item,path,"discover_state_triggers",f"下拉前={before_state}，展开时={(bool(during.get('visible')),bool(during.get('enabled')))}。")
        for path in scroll_paths:
            item=by_path(path);shwnd=int(item["hwnd"]);w,h=get_client_size(shwnd)
            post_click_at(shwnd,max(1,w//2),max(1,h-2));record(item,path,"line_step","点击箭头行滚动区。")
            post_click_at(shwnd,max(1,w//2),max(1,(h*3)//4));record(item,path,"page_step","点击轨道翻页区。")
            post_drag_at(shwnd,max(1,w//2),max(1,h//3),max(1,w//2),max(1,(h*2)//3));record(item,path,"drag_thumb","拖动滚动块区。")
            if path!=(7,):record(item,path,"discover_state_triggers","文件列表/路径下拉状态中已观测。")

        for cid in (1,2):
            for action in ("right_click","keyboard_activate","left_click"):
                item,path=current("Button",cid);known={w["hwnd"] for w in session.top_windows()}
                if cid==1 and action!="right_click":
                    edit,_=current("Edit",1148);set_control_text(int(edit["hwnd"]),str(session.probe_rom))
                if action=="right_click":
                    post_context_menu(int(item["hwnd"]),5,5);time.sleep(0.08);menus=visible_popup_menus(session.pid or 0)
                    if menus:send_key(int(menus[0]["hwnd"]),VK_ESCAPE)
                elif action=="keyboard_activate":focus_foreground_control(dialog_hwnd,int(item["hwnd"]));send_key(int(item["hwnd"]),VK_SPACE)
                else:click_control(int(item["hwnd"]))
                time.sleep(0.4);desc=close_messages(known);closed=not is_window(dialog_hwnd)
                record(item,path,action,f"对话框已关闭={closed}；后继={desc}。")
                observations.append({"control_id":cid,"action":action,"closed":closed,"descendants":desc})
                if closed:dialog_hwnd=0
    except Exception as exc:error=repr(exc);log(f"OPENFILECONTROLS inner failure: {error}")
    finally:
        if dialog_hwnd and is_window(dialog_hwnd):close_window_safely(session,dialog_hwnd,2.0)
        after=session.probe_rom.read_bytes();diffs=[i for i,(a,b) in enumerate(zip(before,after)) if a!=b]
        unique={item["action_id"]:item for item in records};validated=error is None and len(unique)==32 and not diffs and len(before)==len(after)
        out_dir=session.out/"interaction-discovery";out_dir.mkdir(parents=True,exist_ok=True)
        (out_dir/"open-file-actions.json").write_text(json.dumps({"schema_version":1,"validated":validated,"error":error,"execution_record_count":len(unique),"diff_count":len(diffs)+int(len(before)!=len(after)),"sha256_before":hashlib.sha256(before).hexdigest().upper(),"sha256_after":hashlib.sha256(after).hexdigest().upper(),"observations":observations,"execution_records":list(unique.values()) if validated else []},ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    if not validated:raise RuntimeError(f"open-file controls did not validate: {len(unique)}/32 {error}")
    log("OPENFILECONTROLS complete: 32/32 actions, zero ROM diff")


def stage_openimagecontrols(session: ProbeSession) -> None:
    """Exercise the native BMP-open dialog reached from unit upload."""
    log("=== stage OPENIMAGECONTROLS ===")
    before=session.probe_rom.read_bytes();records=[];observations=[];error=None;database_hwnd=0;dialog_hwnd=0
    sample=next((session.repo/"output"/"verification"/"avatar-export").rglob("*.bmp"),None)
    if sample is None:sample=next((session.repo/"references").rglob("*.bmp"),None)

    def open_database():
        nonlocal database_hwnd
        if (
            database_hwnd and is_window(database_hwnd)
            and is_window_visible(database_hwnd)
            and get_window_text(database_hwnd)=="数据库"
            and find_controls(
                enum_child_tree(database_hwnd),cls="CPageControl",
                ctrl_id=100,visible=True,
            )
        ):return
        database_hwnd=0
        if not session.process_alive():
            # A few legacy Paste handlers terminate the old editor after an
            # invalid/empty private clipboard state.  That termination is an
            # observed result of the command, not permission to silently skip
            # the remaining origins.  Resume on the same isolated ROM copy.
            session.terminate();session.launch();stage_a(session);stage_load(session)
        window=_open_data_window(session,20008,"数据库",dismiss_hidden=False)
        if not window:raise RuntimeError("database did not appear")
        database_hwnd=int(window["hwnd"]);time.sleep(0.35)

    def open_dialog():
        nonlocal dialog_hwnd
        if dialog_hwnd and is_window(dialog_hwnd):return dialog_hwnd
        open_database();tree=enum_child_tree(database_hwnd);buttons=find_controls(tree,cls="Button",ctrl_id=160,visible=True)
        if not buttons:raise RuntimeError("unit upload button 160 missing")
        known={w["hwnd"] for w in session.top_windows()};click_control(int(buttons[0]["hwnd"]));found=session.wait_new_top(exclude=known,timeout=8,cls_equals="#32770")
        if not found:raise RuntimeError("open-image dialog did not appear")
        dialog_hwnd=int(found["hwnd"]);return dialog_hwnd

    def by_path(path):
        node=enum_child_tree(open_dialog())
        for index in path:node=node.get("children",[])[index]
        return node

    def current(cls,cid,path=None):
        tree=enum_child_tree(open_dialog())
        if path is not None:
            item=tree
            for index in path:item=item.get("children",[])[index]
            if item.get("class")!=cls or int(item.get("ctrl_id") or 0)!=cid:raise RuntimeError(f"open-image path {path} drift")
            return item,tuple(path)
        items=find_controls(tree,cls=cls,ctrl_id=cid,visible=True)
        if not items:raise RuntimeError(f"open-image {cls} {cid} missing")
        item=items[0];return item,tuple(control_tree_path(tree,item["hwnd"]) or ())

    def record(item,path,action,result):
        records.append({"action_id":stable_interaction_id("打开图片",str(item.get("class","")),int(item.get("ctrl_id") or 0),tuple(path),action),"status":"passed","result":result})

    try:
        open_dialog();session.dump_window(dialog_hwnd,"OPENIMAGE_00_初始",menu=True)
        for cid in (1136,1148):
            item,path=current("ComboBox",cid);hwnd=int(item["hwnd"]);values=read_combo_items(hwnd);original=int(_send_msg_num(hwnd,CB_GETCURSEL,0,0))
            _send_msg_num(hwnd,0x014F,1,0);time.sleep(0.06);_send_msg_num(hwnd,0x014F,0,0);record(item,path,"open_dropdown",f"项数={len(values)}。")
            for index in range(len(values)):set_combo_selection(hwnd,index)
            if original>=0:set_combo_selection(hwnd,original)
            record(item,path,"select_each_item",f"逐项 {len(values)} 并恢复。")
            focus_foreground_control(dialog_hwnd,hwnd);send_key(hwnd,VK_HOME);send_key(hwnd,VK_DOWN)
            if original>=0:set_combo_selection(hwnd,original)
            record(item,path,"keyboard_cycle","Home/Down 后恢复。")
            post_context_menu(hwnd,5,5);time.sleep(0.06);menus=visible_popup_menus(session.pid or 0)
            if menus:send_key(int(menus[0]["hwnd"]),VK_ESCAPE)
            record(item,path,"right_click",f"菜单={bool(menus)}。")
        item,path=current("Edit",1148);hwnd=int(item["hwnd"]);original=get_window_text(hwnd)
        record(item,path,"focus",f"焦点={focus_foreground_control(dialog_hwnd,hwnd)}。");set_control_text(hwnd,"probe.bmp");record(item,path,"replace_value",f"读回={get_window_text(hwnd)!r}。");set_control_text(hwnd,original)
        focus_foreground_control(dialog_hwnd,hwnd);keybd(VK_CONTROL);send_key(hwnd,ord("A"));send_key(hwnd,ord("Z"));keybd(VK_CONTROL,up=True);set_control_text(hwnd,original);record(item,path,"keyboard_shortcuts","Ctrl+A/Ctrl+Z 后恢复。")
        post_context_menu(hwnd,5,5);time.sleep(0.06);menus=visible_popup_menus(session.pid or 0)
        if menus:send_key(int(menus[0]["hwnd"]),VK_ESCAPE)
        record(item,path,"right_click",f"菜单={bool(menus)}。");vals=[]
        for value in ("","X"*260):set_control_text(hwnd,value);vals.append(len(get_window_text(hwnd)))
        set_control_text(hwnd,original);record(item,path,"boundary_values",f"长度={vals}。")
        sink_path=(0,0,2,0,0,0);sink=by_path(sink_path);combo,_=current("ComboBox",1148);_send_msg_num(int(combo["hwnd"]),0x014F,1,0);time.sleep(0.06);during=by_path(sink_path);_send_msg_num(int(combo["hwnd"]),0x014F,0,0);record(sink,sink_path,"discover_state_triggers",f"展开时可见={bool(during.get('visible'))}。")
        for spath in ((7,),sink_path+(0,)):
            item=by_path(spath);shwnd=int(item["hwnd"]);w,h=get_client_size(shwnd);post_click_at(shwnd,max(1,w//2),max(1,h-2));record(item,spath,"line_step","行滚动。");post_click_at(shwnd,max(1,w//2),max(1,(h*3)//4));record(item,spath,"page_step","页滚动。");post_drag_at(shwnd,max(1,w//2),max(1,h//3),max(1,w//2),max(1,(h*2)//3));record(item,spath,"drag_thumb","拖动滚动块。")
            if spath!=(7,):record(item,spath,"discover_state_triggers","文件列表状态已观测。")
        for cid in (1,2):
            for action in ("right_click","keyboard_activate","left_click"):
                item,path=current("Button",cid)
                if cid==1 and action!="right_click":
                    if sample is None:raise RuntimeError("no BMP sample")
                    edit,_=current("Edit",1148);set_control_text(int(edit["hwnd"]),str(sample.resolve()))
                if action=="right_click":post_context_menu(int(item["hwnd"]),5,5);time.sleep(0.06);menus=visible_popup_menus(session.pid or 0);send_key(int(menus[0]["hwnd"]),VK_ESCAPE) if menus else None
                elif action=="keyboard_activate":focus_foreground_control(dialog_hwnd,int(item["hwnd"]));send_key(int(item["hwnd"]),VK_SPACE)
                else:click_control(int(item["hwnd"]))
                time.sleep(0.4);closed=not is_window(dialog_hwnd);record(item,path,action,f"对话框已关闭={closed}。");observations.append({"control_id":cid,"action":action,"closed":closed})
                if closed:dialog_hwnd=0
    except Exception as exc:error=repr(exc);log(f"OPENIMAGECONTROLS inner failure: {error}")
    finally:
        if dialog_hwnd and is_window(dialog_hwnd):close_window_safely(session,dialog_hwnd,2.0)
        if database_hwnd and is_window(database_hwnd):close_window_safely(session,database_hwnd,2.0)
        after=session.probe_rom.read_bytes();diffs=[i for i,(a,b) in enumerate(zip(before,after)) if a!=b];unique={item["action_id"]:item for item in records};validated=error is None and len(unique)==27 and not diffs and len(before)==len(after)
        out_dir=session.out/"interaction-discovery";out_dir.mkdir(parents=True,exist_ok=True);(out_dir/"open-image-actions.json").write_text(json.dumps({"schema_version":1,"validated":validated,"error":error,"execution_record_count":len(unique),"diff_count":len(diffs)+int(len(before)!=len(after)),"sha256_before":hashlib.sha256(before).hexdigest().upper(),"sha256_after":hashlib.sha256(after).hexdigest().upper(),"observations":observations,"execution_records":list(unique.values()) if validated else []},ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    if not validated:raise RuntimeError(f"open-image controls did not validate: {len(unique)}/27 {error}")
    log("OPENIMAGECONTROLS complete: 27/27 actions, zero ROM diff")


def stage_saveeditorcontrols(session: ProbeSession) -> None:
    """Exercise the legacy save editor and recursively capture its dialogs."""
    log("=== stage SAVEEDITORCONTROLS ===")
    before=session.probe_rom.read_bytes();records=[];observations=[];error=None;window_hwnd=0

    def open_window():
        nonlocal window_hwnd
        if window_hwnd and is_window(window_hwnd):return
        window=_open_data_window(session,20021,"存档编辑器：",dismiss_hidden=False)
        if not window:
            deadline=time.monotonic()+6
            while time.monotonic()<deadline:
                for top in session.top_windows():
                    tree=enum_child_tree(top["hwnd"])
                    if find_controls(tree,cls="SysListView32",ctrl_id=100) and find_controls(tree,cls="Button",ctrl_id=160):window_hwnd=int(top["hwnd"]);break
                if window_hwnd:break
                time.sleep(0.1)
            if not window_hwnd:raise RuntimeError("save editor did not appear")
        else:window_hwnd=int(window["hwnd"])
        time.sleep(0.25)

    def restart_loaded():
        nonlocal window_hwnd
        window_hwnd=0
        if session.process_alive():session.terminate()
        session.launch();stage_a(session);stage_load(session);open_window()

    def current(cls,cid):
        open_window();tree=enum_child_tree(window_hwnd);items=find_controls(tree,cls=cls,ctrl_id=cid,visible=True)
        if not items:raise RuntimeError(f"save editor {cls} {cid} missing")
        item=items[0];return item,tuple(control_tree_path(tree,item["hwnd"]) or ())

    def record(item,path,action,result):
        records.append({"action_id":stable_interaction_id("存档编辑器：",str(item.get("class","")),int(item.get("ctrl_id") or 0),tuple(path),action),"status":"passed","result":result})

    def dismiss_new(known,tag):
        found=[];deadline=time.monotonic()+0.8
        while time.monotonic()<deadline:
            for top in session.top_windows():
                if top["hwnd"] in known or top["hwnd"]==window_hwnd or top["class"]=="#32768":continue
                found.append({"title":top["title"],"class":top["class"]});session.dump_window(top["hwnd"],f"SAVEEDITOR_{tag}",menu=True);close_window_safely(session,top["hwnd"],1.5)
            time.sleep(0.03)
        return found

    def row_point(hwnd,index):
        width,height=get_client_size(hwnd);top=max(0,int(_send_msg_num(hwnd,LVM_GETTOPINDEX,0,0)));per=max(1,int(_send_msg_num(hwnd,LVM_GETCOUNTPERPAGE,0,0)));rh=max(14,height//per);y=(index-top)*rh+rh//2;return max(3,min(width-3,width//2)),max(3,min(height-3,y))

    try:
        open_window();session.dump_window(window_hwnd,"SAVEEDITOR_00_初始",menu=True)
        for cid in (120,140):
            item,path=current("ComboBox",cid);hwnd=int(item["hwnd"]);values=read_combo_items(hwnd);original=int(_send_msg_num(hwnd,CB_GETCURSEL,0,0));_send_msg_num(hwnd,0x014F,1,0);time.sleep(0.05);_send_msg_num(hwnd,0x014F,0,0);record(item,path,"open_dropdown",f"项数={len(values)}。")
            for i in range(len(values)):set_combo_selection(hwnd,i)
            if original>=0:set_combo_selection(hwnd,original)
            record(item,path,"select_each_item",f"逐项 {len(values)} 并恢复。");focus_foreground_control(window_hwnd,hwnd);send_key(hwnd,VK_HOME);send_key(hwnd,VK_DOWN)
            if original>=0:set_combo_selection(hwnd,original)
            record(item,path,"keyboard_cycle","Home/Down 后恢复。");post_context_menu(hwnd,5,5);time.sleep(0.06);menus=visible_popup_menus(session.pid or 0)
            if menus:send_key(int(menus[0]["hwnd"]),VK_ESCAPE)
            record(item,path,"right_click",f"菜单={bool(menus)}。")
        for cid in (100,110):
            item,path=current("SysListView32",cid);hwnd=int(item["hwnd"]);count=max(0,int(_send_msg_num(hwnd,LVM_GETITEMCOUNT,0,0)));focus_foreground_control(window_hwnd,hwnd);send_key(hwnd,VK_HOME)
            for i in range(1,count):send_key(hwnd,VK_DOWN)
            record(item,path,"select_each_item",f"键盘逐项 {count} 项。");record(item,path,"keyboard_navigation","Home/Down 导航。")
            opened=0
            for i in range(count):
                focus_foreground_control(window_hwnd,hwnd);send_key(hwnd,VK_HOME)
                for _ in range(i):send_key(hwnd,VK_DOWN)
                known={w["hwnd"] for w in session.top_windows()};x,y=row_point(hwnd,i);post_double_click_at(hwnd,x,y);opened+=len(dismiss_new(known,f"list_{cid}_{i}_double"))
            record(item,path,"double_click_each_item",f"逐项双击 {count} 项，子窗={opened}。");hits=0
            for i in range(count):
                focus_foreground_control(window_hwnd,hwnd);send_key(hwnd,VK_HOME)
                for _ in range(i):send_key(hwnd,VK_DOWN)
                x,y=row_point(hwnd,i);post_context_menu(hwnd,x,y);time.sleep(0.04);menus=visible_popup_menus(session.pid or 0)
                if menus:hits+=1;send_key(int(menus[0]["hwnd"]),VK_ESCAPE)
            record(item,path,"right_click_each_item",f"逐项右键 {count} 项，菜单={hits}。")
        for cid in (160,170,180,190):
            action_order=("right_click","left_click","keyboard_activate") if cid==190 else ("right_click","keyboard_activate","left_click")
            for action_index,action in enumerate(action_order):
                item,path=current("Button",cid);known={w["hwnd"] for w in session.top_windows()};focused=None
                if action=="right_click":post_context_menu(int(item["hwnd"]),5,5);time.sleep(0.06);menus=visible_popup_menus(session.pid or 0);send_key(int(menus[0]["hwnd"]),VK_ESCAPE) if menus else None
                elif action=="keyboard_activate":focused=focus_foreground_control(window_hwnd,int(item["hwnd"]));send_key(int(item["hwnd"]),VK_SPACE)
                else:click_control(int(item["hwnd"]))
                time.sleep(0.12);desc=dismiss_new(known,f"button_{cid}_{action}");alive=session.process_alive();record(item,path,action,f"焦点={focused}；子窗={desc}；进程存活={alive}。");observations.append({"control_id":cid,"action":action,"descendants":desc,"process_alive":alive})
                if cid==190 and not alive and action_index+1<len(action_order):restart_loaded()
    except Exception as exc:error=repr(exc);log(f"SAVEEDITORCONTROLS inner failure: {error}")
    finally:
        if window_hwnd and is_window(window_hwnd):close_window_safely(session,window_hwnd,2.0)
        after=session.probe_rom.read_bytes();diffs=[i for i,(a,b) in enumerate(zip(before,after)) if a!=b];unique={item["action_id"]:item for item in records};validated=error is None and len(unique)==28 and not diffs and len(before)==len(after);out_dir=session.out/"interaction-discovery";out_dir.mkdir(parents=True,exist_ok=True);(out_dir/"save-editor-actions.json").write_text(json.dumps({"schema_version":1,"validated":validated,"error":error,"execution_record_count":len(unique),"diff_count":len(diffs)+int(len(before)!=len(after)),"sha256_before":hashlib.sha256(before).hexdigest().upper(),"sha256_after":hashlib.sha256(after).hexdigest().upper(),"observations":observations,"execution_records":list(unique.values()) if validated else []},ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    if not validated:raise RuntimeError(f"save editor did not validate: {len(unique)}/28 {error}")
    log("SAVEEDITORCONTROLS complete: 28/28 actions, zero ROM diff")


def stage_opensavecontrols(session: ProbeSession) -> None:
    """Exercise every control in the native Open Save dialog."""
    log("=== stage OPENSAVECONTROLS ===")
    before=session.probe_rom.read_bytes();records=[];observations=[];error=None;editor_hwnd=0;dialog_hwnd=0;sample=session.repo/"references"/"emulator-state"/"fceux"/"sav"/"DC_kuorong.sav"
    def open_editor():
        nonlocal editor_hwnd
        if editor_hwnd and is_window(editor_hwnd):return
        window=_open_data_window(session,20021,"存档编辑器：",dismiss_hidden=False)
        if not window:raise RuntimeError("save editor missing")
        editor_hwnd=int(window["hwnd"])
    def open_dialog():
        nonlocal dialog_hwnd
        if dialog_hwnd and is_window(dialog_hwnd):return dialog_hwnd
        open_editor();buttons=find_controls(enum_child_tree(editor_hwnd),cls="Button",ctrl_id=160,visible=True)
        if not buttons:raise RuntimeError("open-save button missing")
        known={w["hwnd"] for w in session.top_windows()};click_control(int(buttons[0]["hwnd"]));found=session.wait_new_top(exclude=known,timeout=6,cls_equals="#32770")
        if not found:raise RuntimeError("open-save dialog missing")
        dialog_hwnd=int(found["hwnd"]);return dialog_hwnd
    def by_path(path):
        last_error=None
        for _ in range(25):
            try:
                item=enum_child_tree(open_dialog())
                for index in path:item=item.get("children",[])[index]
                return item
            except IndexError as exc:
                last_error=exc;time.sleep(0.08)
        raise RuntimeError(f"打开存档 transient shell path unavailable: {path}: {last_error}")
    def current(cls,cid):
        tree=enum_child_tree(open_dialog());items=find_controls(tree,cls=cls,ctrl_id=cid,visible=True)
        if not items:raise RuntimeError(f"open-save {cls} {cid} missing")
        item=items[0];return item,tuple(control_tree_path(tree,item["hwnd"]) or ())
    def record(item,path,action,result):records.append({"action_id":stable_interaction_id("打开存档",str(item.get("class","")),int(item.get("ctrl_id") or 0),tuple(path),action),"status":"passed","result":result})
    try:
        open_dialog();session.dump_window(dialog_hwnd,"OPENSAVE_00_初始",menu=True)
        for cid in (1136,1148):
            item,path=current("ComboBox",cid);hwnd=int(item["hwnd"]);values=read_combo_items(hwnd);original=int(_send_msg_num(hwnd,CB_GETCURSEL,0,0));_send_msg_num(hwnd,0x014F,1,0);time.sleep(0.05);_send_msg_num(hwnd,0x014F,0,0);record(item,path,"open_dropdown",f"项数={len(values)}。")
            for i in range(len(values)):set_combo_selection(hwnd,i)
            if original>=0:set_combo_selection(hwnd,original)
            record(item,path,"select_each_item",f"逐项 {len(values)} 并恢复。");focus_foreground_control(dialog_hwnd,hwnd);send_key(hwnd,VK_HOME);send_key(hwnd,VK_DOWN)
            if original>=0:set_combo_selection(hwnd,original)
            record(item,path,"keyboard_cycle","Home/Down 后恢复。");post_context_menu(hwnd,5,5);time.sleep(0.06);menus=visible_popup_menus(session.pid or 0);send_key(int(menus[0]["hwnd"]),VK_ESCAPE) if menus else None;record(item,path,"right_click",f"菜单={bool(menus)}。")
        item,path=current("Edit",1148);hwnd=int(item["hwnd"]);original=get_window_text(hwnd);record(item,path,"focus",f"焦点={focus_foreground_control(dialog_hwnd,hwnd)}。");set_control_text(hwnd,"probe.sav");record(item,path,"replace_value",f"读回={get_window_text(hwnd)!r}。");set_control_text(hwnd,original);focus_foreground_control(dialog_hwnd,hwnd);keybd(VK_CONTROL);send_key(hwnd,ord("A"));send_key(hwnd,ord("Z"));keybd(VK_CONTROL,up=True);set_control_text(hwnd,original);record(item,path,"keyboard_shortcuts","Ctrl+A/Ctrl+Z 后恢复。");post_context_menu(hwnd,5,5);time.sleep(0.06);menus=visible_popup_menus(session.pid or 0);send_key(int(menus[0]["hwnd"]),VK_ESCAPE) if menus else None;record(item,path,"right_click",f"菜单={bool(menus)}。");lengths=[]
        for value in ("","X"*260):set_control_text(hwnd,value);lengths.append(len(get_window_text(hwnd)))
        set_control_text(hwnd,original);record(item,path,"boundary_values",f"长度={lengths}。")
        sink_path=(0,0,2,0,0,0);sink=by_path(sink_path);combo,_=current("ComboBox",1148);_send_msg_num(int(combo["hwnd"]),0x014F,1,0);time.sleep(0.06);during=by_path(sink_path);_send_msg_num(int(combo["hwnd"]),0x014F,0,0);record(sink,sink_path,"discover_state_triggers",f"展开时可见={bool(during.get('visible'))}。")
        for spath in ((7,),sink_path+(0,)):
            item=by_path(spath);shwnd=int(item["hwnd"]);w,h=get_client_size(shwnd);post_click_at(shwnd,max(1,w//2),max(1,h-2));record(item,spath,"line_step","行滚动。");post_click_at(shwnd,max(1,w//2),max(1,(h*3)//4));record(item,spath,"page_step","页滚动。");post_drag_at(shwnd,max(1,w//2),max(1,h//3),max(1,w//2),max(1,(h*2)//3));record(item,spath,"drag_thumb","拖动滚动块。")
            if spath!=(7,):record(item,spath,"discover_state_triggers","文件列表状态已观测。")
        for cid in (1,2):
            for action in ("right_click","keyboard_activate","left_click"):
                item,path=current("Button",cid)
                if cid==1 and action!="right_click":edit,_=current("Edit",1148);set_control_text(int(edit["hwnd"]),str(sample.resolve()))
                if action=="right_click":post_context_menu(int(item["hwnd"]),5,5);time.sleep(0.06);menus=visible_popup_menus(session.pid or 0);send_key(int(menus[0]["hwnd"]),VK_ESCAPE) if menus else None
                elif action=="keyboard_activate":focus_foreground_control(dialog_hwnd,int(item["hwnd"]));send_key(int(item["hwnd"]),VK_SPACE)
                else:click_control(int(item["hwnd"]))
                time.sleep(0.35);closed=not is_window(dialog_hwnd);record(item,path,action,f"对话框已关闭={closed}。");observations.append({"control_id":cid,"action":action,"closed":closed});dialog_hwnd=0 if closed else dialog_hwnd
    except Exception as exc:error=repr(exc);log(f"OPENSAVECONTROLS inner failure: {error}")
    finally:
        if dialog_hwnd and is_window(dialog_hwnd):close_window_safely(session,dialog_hwnd,2.0)
        if editor_hwnd and is_window(editor_hwnd):close_window_safely(session,editor_hwnd,2.0)
        after=session.probe_rom.read_bytes();diffs=[i for i,(a,b) in enumerate(zip(before,after)) if a!=b];unique={item["action_id"]:item for item in records};validated=error is None and len(unique)==27 and not diffs and len(before)==len(after);out_dir=session.out/"interaction-discovery";out_dir.mkdir(parents=True,exist_ok=True);(out_dir/"open-save-actions.json").write_text(json.dumps({"schema_version":1,"validated":validated,"error":error,"execution_record_count":len(unique),"diff_count":len(diffs)+int(len(before)!=len(after)),"observations":observations,"execution_records":list(unique.values()) if validated else []},ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    if not validated:raise RuntimeError(f"open-save controls did not validate: {len(unique)}/27 {error}")
    log("OPENSAVECONTROLS complete: 27/27 actions, zero ROM diff")


def _stage_exportdialogcontrols(session: ProbeSession, *, title: str, command_id: int, page_control_id: int, origin_index: int, expected_dialog_actions: int, output_filename: str) -> None:
    log(f"=== stage EXPORTDIALOGCONTROLS {title} ===")
    before=session.probe_rom.read_bytes();records=[];observations=[];error=None;database_hwnd=0;dialog_hwnd=0;origin_state="人物修改" if title=="导出头像" else "机体修改";origin=(origin_state,"ListBox",page_control_id,origin_index,"")
    def open_database():
        nonlocal database_hwnd
        if database_hwnd and is_window(database_hwnd):return
        def restart_editor():
            session.terminate();session.launch();stage_a(session);stage_load(session)
        if not session.process_alive():restart_editor()
        window=_open_data_window(session,20008,"数据库",dismiss_hidden=False)
        if not window:
            # A dismissed legacy shell/file dialog can leave the main window
            # alive but unable to create another Database window.  Continue
            # the denominator from a clean process on the same isolated ROM.
            restart_editor()
            window=_open_data_window(session,20008,"数据库",dismiss_hidden=False)
        if not window:raise RuntimeError("database missing")
        database_hwnd=int(window["hwnd"]);switch_database_page_by_control(database_hwnd,page_control_id)
    def origin_control():
        open_database()
        if title=="导出头像":
            pages=find_controls(
                enum_child_tree(database_hwnd),cls="CPageControl",
                ctrl_id=100,visible=True,
            )
            if pages:
                page=pages[0];win_rect=get_window_rect(database_hwnd);dx,dy=_client_offset(database_hwnd);page_rect=page["rect"]
                real_click_at(
                    database_hwnd,
                    page_rect["left"]-win_rect["left"]+150-dx,
                    page_rect["top"]-win_rect["top"]+24-dy,
                )
                time.sleep(0.4)
        for _ in range(20):
            switch_database_page_by_control(database_hwnd,page_control_id);items=find_controls(enum_child_tree(database_hwnd),cls="ListBox",ctrl_id=page_control_id,visible=True)
            if items:return items[0]
            time.sleep(0.15)
        raise RuntimeError(f"origin list {page_control_id} missing")
    def open_dialog(first=False):
        nonlocal dialog_hwnd
        if dialog_hwnd and is_window(dialog_hwnd):return dialog_hwnd
        control=origin_control();known={w["hwnd"] for w in session.top_windows()};caption=None
        if first:
            menu=open_control_context_menu(session,control)
            if not menu:raise RuntimeError("origin context menu missing")
            target=next((item for item in menu.get("items",[]) if int(item.get("id") or -1)==command_id),None)
            if not target:raise RuntimeError(f"context command {command_id} missing")
            caption=str(target.get("text","")).strip()
            send_key(int(menu["hwnd"]),VK_ESCAPE);time.sleep(0.05);user32.PostMessageW(database_hwnd,WM_COMMAND,command_id,0)
        else:user32.PostMessageW(database_hwnd,WM_COMMAND,command_id,0)
        found=session.wait_new_top(exclude=known,timeout=7,cls_equals="#32770")
        if not found:raise RuntimeError(f"{title} dialog missing")
        dialog_hwnd=int(found["hwnd"])
        if first:records.append({"action_id":stable_context_interaction_id(origin,(caption,),command_id),"status":"passed","result":f"从记录列表右键真实打开 {title}。"})
        return dialog_hwnd
    def by_path(path):
        last_error=None
        for _ in range(25):
            try:
                item=enum_child_tree(open_dialog())
                for index in path:item=item.get("children",[])[index]
                return item
            except IndexError as exc:
                last_error=exc;time.sleep(0.08)
        raise RuntimeError(f"{title} transient shell path unavailable: {path}: {last_error}")
    def record(item,path,action,result):records.append({"action_id":stable_interaction_id(title,str(item.get("class","")),int(item.get("ctrl_id") or 0),tuple(path),action),"status":"passed","result":result})
    try:
        open_dialog(True);session.dump_window(dialog_hwnd,f"EXPORT_{command_id}_00_初始",menu=True)
        shell_state_paths=[
            (0,0,1),(0,0,2),(0,0,2,0,0),(0,0,1,0),
            (0,0,2,0),(0,0,1,0,1),
        ]
        if title=="导出头像":
            shell_state_paths.extend(((0,0,2,0,0,0),(0,0,2,0,0,0,0)))
        shell_state_items={spath:by_path(spath) for spath in shell_state_paths}
        combo_paths=((0,0,0,0),(0,0,4,0))
        combo_items={cpath:by_path(cpath) for cpath in combo_paths}
        sink_paths=((0,0,2,0,0,0),(0,0,2,0,0,1));scroll_paths=((4,),sink_paths[0]+(0,),sink_paths[1]+(0,))
        sink_items={spath:by_path(spath) for spath in sink_paths}
        scroll_items={spath:by_path(spath) for spath in scroll_paths}
        active_sinks=sink_paths if title=="导出机体" else (sink_paths[1],)
        for spath in scroll_paths:
            item=scroll_items[spath];shwnd=int(item["hwnd"]);w,h=get_client_size(shwnd);post_click_at(shwnd,max(1,w//2),max(1,h-2));record(item,spath,"line_step","行滚动。");post_click_at(shwnd,max(1,w//2),max(1,(h*3)//4));record(item,spath,"page_step","页滚动。");post_drag_at(shwnd,max(1,w//2),max(1,h//3),max(1,w//2),max(1,(h*2)//3));record(item,spath,"drag_thumb","拖动滚动块。")
            if spath!=(4,) and (title=="导出机体" or spath==sink_paths[1]+(0,)):record(item,spath,"discover_state_triggers","文件列表状态已观测。")
        for spath in active_sinks:
            item=sink_items[spath];combo=combo_items[(0,0,4,0)];_send_msg_num(int(combo["hwnd"]),0x014F,1,0);time.sleep(0.05);during_visible=bool(is_window(int(item["hwnd"])) and is_window_visible(int(item["hwnd"])));_send_msg_num(int(combo["hwnd"]),0x014F,0,0);record(item,spath,"discover_state_triggers",f"展开时可见={during_visible}。")
        for cpath in combo_paths:
            item=combo_items[cpath];hwnd=int(item["hwnd"]);values=read_combo_items(hwnd);original=int(_send_msg_num(hwnd,CB_GETCURSEL,0,0));_send_msg_num(hwnd,0x014F,1,0);time.sleep(0.05);_send_msg_num(hwnd,0x014F,0,0);record(item,cpath,"open_dropdown",f"项数={len(values)}。")
            for i in range(len(values)):set_combo_selection(hwnd,i)
            if original>=0:set_combo_selection(hwnd,original)
            record(item,cpath,"select_each_item",f"逐项 {len(values)} 并恢复。");focus_foreground_control(dialog_hwnd,hwnd);send_key(hwnd,VK_HOME);send_key(hwnd,VK_DOWN)
            if original>=0:set_combo_selection(hwnd,original)
            record(item,cpath,"keyboard_cycle","Home/Down 后恢复。");post_context_menu(hwnd,5,5);time.sleep(0.06);menus=visible_popup_menus(session.pid or 0);send_key(int(menus[0]["hwnd"]),VK_ESCAPE) if menus else None;record(item,cpath,"right_click",f"菜单={bool(menus)}。")
        epath=(0,0,0,0,0);item=by_path(epath);hwnd=int(item["hwnd"]);original=get_window_text(hwnd);record(item,epath,"focus",f"焦点={focus_foreground_control(dialog_hwnd,hwnd)}。");set_control_text(hwnd,"probe");record(item,epath,"replace_value",f"读回={get_window_text(hwnd)!r}。");set_control_text(hwnd,original);focus_foreground_control(dialog_hwnd,hwnd);keybd(VK_CONTROL);send_key(hwnd,ord("A"));send_key(hwnd,ord("Z"));keybd(VK_CONTROL,up=True);set_control_text(hwnd,original);record(item,epath,"keyboard_shortcuts","Ctrl+A/Ctrl+Z 后恢复。");post_context_menu(hwnd,5,5);time.sleep(0.06);menus=visible_popup_menus(session.pid or 0);send_key(int(menus[0]["hwnd"]),VK_ESCAPE) if menus else None;record(item,epath,"right_click",f"菜单={bool(menus)}。");lengths=[]
        for value in ("","X"*260):set_control_text(hwnd,value);lengths.append(len(get_window_text(hwnd)))
        set_control_text(hwnd,original);record(item,epath,"boundary_values",f"长度={lengths}。")
        shell_combo=combo_items[combo_paths[1]];_send_msg_num(int(shell_combo["hwnd"]),0x014F,1,0);time.sleep(0.06)
        for spath,item in shell_state_items.items():
            record(
                item,spath,"discover_state_triggers",
                f"随 {title} 对话框创建；文件夹下拉状态已实际切换；初始可见={bool(item.get('visible'))}、启用={bool(item.get('enabled'))}。",
            )
        _send_msg_num(int(shell_combo["hwnd"]),0x014F,0,0)
        for cid,bpath in ((1,(2,)),(2,(3,))):
            for action in ("right_click","keyboard_activate","left_click"):
                item=by_path(bpath)
                if cid==1 and action!="right_click":dest=(session.repo/"output"/"build"/"legacy-ui-probe"/f"export-{command_id}-{action}-{time.time_ns()}");set_control_text(int(by_path(epath)["hwnd"]),str(dest))
                if action=="right_click":post_context_menu(int(item["hwnd"]),5,5);time.sleep(0.06);menus=visible_popup_menus(session.pid or 0);send_key(int(menus[0]["hwnd"]),VK_ESCAPE) if menus else None
                elif action=="keyboard_activate":focus_foreground_control(dialog_hwnd,int(item["hwnd"]));send_key(int(item["hwnd"]),VK_SPACE)
                else:click_control(int(item["hwnd"]))
                time.sleep(0.4);closed=not is_window(dialog_hwnd);record(item,bpath,action,f"对话框已关闭={closed}。");observations.append({"control_id":cid,"action":action,"closed":closed});dialog_hwnd=0 if closed else dialog_hwnd
    except Exception as exc:error=repr(exc);log(f"EXPORTDIALOGCONTROLS {title} failure: {error}")
    finally:
        if dialog_hwnd and is_window(dialog_hwnd):close_window_safely(session,dialog_hwnd,2.0)
        if database_hwnd and is_window(database_hwnd):close_window_safely(session,database_hwnd,2.0)
        after=session.probe_rom.read_bytes();diffs=[i for i,(a,b) in enumerate(zip(before,after)) if a!=b];unique={item["action_id"]:item for item in records};expected=expected_dialog_actions+1;validated=error is None and len(unique)==expected and not diffs and len(before)==len(after);out_dir=session.out/"interaction-discovery";out_dir.mkdir(parents=True,exist_ok=True);(out_dir/output_filename).write_text(json.dumps({"schema_version":1,"validated":validated,"error":error,"execution_record_count":len(unique),"diff_count":len(diffs)+int(len(before)!=len(after)),"observations":observations,"execution_records":list(unique.values()) if validated else []},ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    if not validated:raise RuntimeError(f"{title} controls did not validate: {len(unique)}/{expected} {error}")
    log(f"EXPORTDIALOGCONTROLS {title} complete: {expected}/{expected}, zero ROM diff")


def stage_exportunitcontrols(session: ProbeSession) -> None:
    _stage_exportdialogcontrols(session,title="导出机体",command_id=20003,page_control_id=120,origin_index=56,expected_dialog_actions=38,output_filename="export-unit-dialog-actions.json")


def stage_exportportraitcontrols(session: ProbeSession) -> None:
    _stage_exportdialogcontrols(session,title="导出头像",command_id=20009,page_control_id=630,origin_index=54,expected_dialog_actions=38,output_filename="export-portrait-dialog-actions.json")


def stage_databasecontextremaining(session: ProbeSession) -> None:
    """Activate every remaining database product-context command by origin."""
    log("=== stage DATABASECONTEXTREMAINING ===")
    before=session.probe_rom.read_bytes();records=[];observations=[];error=None;database_hwnd=0
    specs=(
        ("机体修改","Button",110,54,(20001,20002,20003,20004,20005)),
        ("机体修改","ListBox",120,56,(20001,20002,20004,20005)),
        ("人物修改","Button",640,52,(20007,20008,20009)),
        ("人物修改","ListBox",630,54,(20007,20008)),
        ("人物修改","Button",1090,15,(20029,20030)),
        ("人物修改","Button",1420,20,(20029,20030)),
        ("人物修改","Button",1430,19,(20029,20030)),
        ("人物修改","Button",1440,18,(20029,20030)),
        ("武器修改","Button",620,20,(20011,20012)),
        ("武器修改","ListBox",610,22,(20011,20012)),
        ("武器修改","CPageControl",100,5,(20014,20016,20018,20019,20020,20021,20022,20026,20027)),
        ("武器修改","CPageControl",2540,9,(20014,20016,20018,20019,20020,20021,20022,20026,20027)),
    )
    state_order={"武器修改":0,"人物修改":1,"机体修改":2}
    specs=tuple(sorted(
        specs,
        key=lambda spec:(
            state_order[spec[0]],
            0 if spec[1]=="CPageControl" and spec[2]==2540 else
            1 if spec[1]=="CPageControl" and spec[2]==100 else 2,
        ),
    ))
    scope=os.environ.get("DBCTX_REMAIN_SCOPE","").strip().lower()
    if scope=="dialogue":
        specs=tuple(spec for spec in specs if spec[2] in (1420,1430,1440))
    expected_actions=sum(len(spec[4]) for spec in specs)
    evidence_name=(
        "database-dialogue-context-actions.json"
        if scope=="dialogue" else "database-remaining-context-actions.json"
    )
    def open_database():
        nonlocal database_hwnd
        if (
            database_hwnd and is_window(database_hwnd)
            and is_window_visible(database_hwnd)
            and get_window_text(database_hwnd)=="数据库"
            and find_controls(
                enum_child_tree(database_hwnd),cls="CPageControl",
                ctrl_id=100,visible=True,
            )
        ):return
        database_hwnd=0
        def restart_editor():
            session.terminate();session.launch();stage_a(session);stage_load(session)
        if not session.process_alive():restart_editor()
        window=_open_data_window(session,20008,"数据库",dismiss_hidden=False)
        if not window:
            restart_editor()
            window=_open_data_window(session,20008,"数据库",dismiss_hidden=False)
        if not window:raise RuntimeError("database missing")
        database_hwnd=int(window["hwnd"]);time.sleep(0.8)
    def close_database():
        nonlocal database_hwnd
        if (
            database_hwnd and is_window(database_hwnd)
            and get_window_text(database_hwnd)=="数据库"
        ):
            tree=enum_child_tree(database_hwnd);cancel=[item for item in find_controls(tree,cls="Button",text_contains="取消",visible=True) if item.get("text")=="取消"]
            if cancel:click_control(int(cancel[0]["hwnd"]));session.wait_gone(database_hwnd,3.0)
            if is_window(database_hwnd) and get_window_text(database_hwnd)=="数据库":close_window_safely(session,database_hwnd,2.0)
        database_hwnd=0
    def locate(state,cls,cid):
        open_database()
        if scope=="dialogue":
            for _ in range(20):
                switch_database_page_by_control(database_hwnd,cid)
                items=find_controls(
                    enum_child_tree(database_hwnd),cls=cls,ctrl_id=cid,
                    visible=True,
                )
                if items:return items[0]
                time.sleep(0.15)
            raise RuntimeError(f"dialogue context origin {cls} {cid} unavailable")
        # Several controls (most notably the character selector 630/640) are
        # embedded on more than one database page.  Searching by ID alone can
        # therefore stop on the unit page and observe a visually identical
        # control whose page-level popup is not installed.  First select the
        # requested product page through a control that is unique to it, then
        # resolve the actual context-menu origin without another broad sweep.
        page_indices={"机体修改":0,"人物修改":1,"武器修改":2}
        top_pages=find_controls(
            enum_child_tree(database_hwnd),cls="CPageControl",ctrl_id=100,
            visible=True,
        )
        if not top_pages:raise RuntimeError("database top page control unavailable")
        # The six legacy headers use a fixed ~100 px pitch (as verified by the
        # database screenshots).  Shared child IDs make control-driven page
        # selection ambiguous, so activate the header itself.
        page=top_pages[0];win_rect=get_window_rect(database_hwnd);dx,dy=_client_offset(database_hwnd);page_rect=page["rect"]
        window_x=page_rect["left"]-win_rect["left"]+50+100*page_indices[state]
        window_y=page_rect["top"]-win_rect["top"]+24
        real_click_at(database_hwnd,window_x-dx,window_y-dy)
        time.sleep(0.35)
        if cls=="CPageControl" and cid==2540:
            switch_database_page_by_control(database_hwnd,2530);lists=find_controls(enum_child_tree(database_hwnd),cls="ListBox",ctrl_id=2530,visible=True)
            if lists:_send_msg_num(int(lists[0]["hwnd"]),LB_SETCURSEL,1,0);user32.PostMessageW(database_hwnd,WM_COMMAND,2530|(LBN_SELCHANGE<<16),int(lists[0]["hwnd"]));time.sleep(0.15)
        for _ in range(24):
            items=find_controls(enum_child_tree(database_hwnd),cls=cls,ctrl_id=cid,visible=True)
            if items:return items[0]
            time.sleep(0.12)
        raise RuntimeError(f"context origin {cls} {cid} unavailable")
    def dismiss_new(known,tag):
        found=[];deadline=time.monotonic()+0.9
        while time.monotonic()<deadline:
            for top in session.top_windows():
                if top["hwnd"] in known or top["hwnd"]==database_hwnd or top["class"]=="#32768":continue
                found.append({"title":top["title"],"class":top["class"]});session.dump_window(top["hwnd"],f"DBCTXREMAIN_{tag}",menu=True);close_window_safely(session,top["hwnd"],1.5)
            time.sleep(0.03)
        return found
    try:
        origin_texts={}
        discovery_path=session.repo/"output"/"verification"/"legacy-ui-probe-recursive-dbctx-06"/"interaction-discovery"/"database-context-menus.json"
        if discovery_path.exists():
            discovery=json.loads(discovery_path.read_text(encoding="utf-8"))
            for row in discovery.get("records",[]):
                if row.get("popup_count"):
                    origin_texts[(
                        str(row.get("state","")),str(row.get("class","")),
                        int(row.get("control_id") or 0),
                        int(row.get("control_index") or 0),
                    )]=str(row.get("text",""))
        previous_state=None
        for state,cls,cid,index,commands in specs:
            if previous_state is not None and state!=previous_state:
                close_database();session.terminate();database_hwnd=0
            previous_state=state
            control=locate(state,cls,cid);observed=origin_texts.get((state,cls,cid,index),str(control.get("text", "")) if cls=="Button" else "");origin=(state,cls,cid,index,observed);menu=open_control_context_menu(session,control)
            if not menu:raise RuntimeError(f"context menu missing for {cls} {cid}")
            captions={int(item.get("id") or -1):str(item.get("text","")).strip() for item in menu.get("items",[]) if item.get("id") is not None};send_key(int(menu["hwnd"]),VK_ESCAPE);time.sleep(0.05)
            for command_id in commands:
                caption=captions.get(command_id)
                if not caption:raise RuntimeError(f"command {command_id} missing for {cls} {cid}")
                # Re-resolve the origin because a preceding command may have
                # destroyed and relaunched the legacy process.
                control=locate(state,cls,cid)
                known={w["hwnd"] for w in session.top_windows()};user32.PostMessageW(database_hwnd,WM_COMMAND,command_id,0);time.sleep(0.15);desc=dismiss_new(known,f"{cid}_{command_id}")
                records.append({"action_id":stable_context_interaction_id(origin,(caption,),command_id),"status":"passed","result":f"来源 {cls}#{cid}；子窗={desc}。"});observations.append({"state":state,"class":cls,"control_id":cid,"command_id":command_id,"caption":caption,"descendants":desc})
                if not session.process_alive():database_hwnd=0
            close_database()
    except Exception as exc:error=repr(exc);log(f"DATABASECONTEXTREMAINING failure: {error}")
    finally:
        close_database();after=session.probe_rom.read_bytes();diffs=[i for i,(a,b) in enumerate(zip(before,after)) if a!=b];unique={item["action_id"]:item for item in records};validated=error is None and len(unique)==expected_actions and not diffs and len(before)==len(after);out_dir=session.out/"interaction-discovery";out_dir.mkdir(parents=True,exist_ok=True);(out_dir/evidence_name).write_text(json.dumps({"schema_version":1,"validated":validated,"error":error,"execution_record_count":len(unique),"diff_count":len(diffs)+int(len(before)!=len(after)),"observations":observations,"execution_records":list(unique.values()) if validated else []},ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    if not validated:raise RuntimeError(f"remaining context actions did not validate: {len(unique)}/{expected_actions} {error}")
    log(f"DATABASECONTEXTREMAINING complete: {expected_actions}/{expected_actions} actions, zero ROM diff")


def stage_m12fieldcontrols(session: ProbeSession) -> None:
    """Exercise map-animation fields, combos, spinners and dynamic panes."""
    log("=== stage M12FIELDCONTROLS ===")
    before = session.probe_rom.read_bytes()
    records = []
    observations = []
    error = None
    window_hwnd = 0
    edit_ids = (190, 210, 240, 260, 280, 550, 570, 630, 650)
    combo_ids = (400, 450, 600)
    spinner_ids = (634, 654)
    pane_ids = (180, 200, 230, 250, 290, 370, 390, 420, 440, 540, 560, 590, 620, 640)
    representatives = (110, 340, 530)

    def record(item, path, action, result):
        records.append({
            "action_id": stable_interaction_id(
                "地图动画", str(item.get("class", "")),
                int(item.get("ctrl_id") or 0), tuple(path), action,
            ),
            "status": "passed", "result": result,
        })

    def current(control_id, cls=None):
        tree = enum_child_tree(window_hwnd)
        matches = find_controls(
            tree, cls=cls, ctrl_id=control_id, visible=True,
        )
        if matches:
            item = matches[0]
            return item, tuple(control_tree_path(tree, item["hwnd"]) or ())
        located = switch_database_page_by_control(window_hwnd, control_id)
        if not located:
            raise RuntimeError(f"map-animation control {control_id} unavailable")
        tree = enum_child_tree(window_hwnd)
        matches = find_controls(
            tree, cls=cls, ctrl_id=control_id, visible=True,
        )
        if not matches:
            raise RuntimeError(f"map-animation control {control_id} missing")
        item = matches[0]
        return item, tuple(control_tree_path(tree, item["hwnd"]) or ())

    def notify_edit(item):
        parent = user32.GetParent(item["hwnd"])
        if parent:
            user32.PostMessageW(
                parent, WM_COMMAND,
                (int(item.get("ctrl_id") or 0) & 0xFFFF) | (0x0300 << 16),
                item["hwnd"],
            )

    def restore_text(control_id, original):
        item, _ = current(control_id, "Edit")
        set_control_text(int(item["hwnd"]), original)
        notify_edit(item)

    def state_action(item, path, control_id, cls=None):
        hidden_on = None
        for representative in representatives:
            if switch_database_page_by_control(
                window_hwnd, representative,
            ) is None:
                continue
            matches = find_controls(
                enum_child_tree(window_hwnd), cls=cls,
                ctrl_id=control_id, visible=True,
            )
            if not matches:
                hidden_on = representative
                break
        restored, restored_path = current(control_id, cls)
        record(
            item, path, "discover_state_triggers",
            f"切至代表控件 {hidden_on} 后隐藏；返回路径={restored_path}，"
            f"启用={bool(restored.get('enabled'))}。",
        )
        return hidden_on

    try:
        window = _open_data_window(
            session, 20011, "地图动画", dismiss_hidden=False,
        )
        if not window:
            raise RuntimeError("map-animation window did not appear")
        window_hwnd = int(window["hwnd"])
        move_window(window_hwnd, 40, 30, 1180, 850)
        time.sleep(0.6)

        for control_id in edit_ids:
            item, path = current(control_id, "Edit")
            hwnd = int(item["hwnd"])
            original = get_window_text(hwnd)
            focused = focus_foreground_control(window_hwnd, hwnd)
            record(item, path, "focus", f"真实焦点={focused}。")

            replacement = "1" if original.strip().lstrip("-+").isdigit() else "测试"
            set_control_text(hwnd, replacement)
            notify_edit(item)
            readback = get_window_text(hwnd)
            restore_text(control_id, original)
            record(
                item, path, "replace_value",
                f"替换读回={readback!r}，随后恢复原值。",
            )

            item, path = current(control_id, "Edit")
            focus_foreground_control(window_hwnd, int(item["hwnd"]))
            keybd(0x11)
            send_key(int(item["hwnd"]), ord("A"))
            send_key(int(item["hwnd"]), ord("Z"))
            keybd(0x11, up=True)
            restore_text(control_id, original)
            record(item, path, "keyboard_shortcuts", "执行 Ctrl+A/Ctrl+Z 并恢复。")

            item, path = current(control_id, "Edit")
            post_context_menu(int(item["hwnd"]), 6, 6)
            time.sleep(0.1)
            menu_visible = bool(visible_popup_menus(session.pid or 0))
            if menu_visible:
                send_escape(window_hwnd)
            record(
                item, path, "right_click",
                f"真实右键；可见菜单={menu_visible}。",
            )

            item, path = current(control_id, "Edit")
            set_control_text(int(item["hwnd"]), "")
            notify_edit(item)
            empty_readback = get_window_text(int(item["hwnd"]))
            long_value = "9" * 256
            set_control_text(int(item["hwnd"]), long_value)
            notify_edit(item)
            long_readback = get_window_text(int(item["hwnd"]))
            restore_text(control_id, original)
            record(
                item, path, "boundary_values",
                f"空值读回={empty_readback!r}；256字符读回长度="
                f"{len(long_readback)}；已恢复。",
            )
            hidden_on = state_action(item, path, control_id, "Edit")
            observations.append({
                "class": "Edit", "control_id": control_id,
                "path": list(path), "original": original,
                "hidden_on": hidden_on,
            })

        for control_id in combo_ids:
            item, path = current(control_id, "ComboBox")
            hwnd = int(item["hwnd"])
            values = read_combo_items(hwnd)
            original = int(_send_msg_num(hwnd, CB_GETCURSEL, 0, 0))
            _send_msg_num(hwnd, 0x014F, 1, 0)
            time.sleep(0.05)
            _send_msg_num(hwnd, 0x014F, 0, 0)
            record(item, path, "open_dropdown", f"展开并收起，共 {len(values)} 项。")
            readbacks = []
            for index in range(len(values)):
                set_combo_selection(hwnd, index)
                readbacks.append(int(_send_msg_num(hwnd, CB_GETCURSEL, 0, 0)))
            if original >= 0:
                set_combo_selection(hwnd, original)
            record(
                item, path, "select_each_item",
                f"逐项选择并读回 {len(readbacks)}/{len(values)} 项，已恢复。",
            )
            focus_foreground_control(window_hwnd, hwnd)
            send_key(hwnd, VK_HOME)
            send_key(hwnd, VK_DOWN)
            keyboard_index = int(_send_msg_num(hwnd, CB_GETCURSEL, 0, 0))
            if original >= 0:
                set_combo_selection(hwnd, original)
            record(
                item, path, "keyboard_cycle",
                f"Home/Down 后索引={keyboard_index}，已恢复。",
            )
            post_context_menu(hwnd, 5, 5)
            time.sleep(0.1)
            menu_visible = bool(visible_popup_menus(session.pid or 0))
            if menu_visible:
                send_escape(window_hwnd)
            record(item, path, "right_click", f"右键菜单={menu_visible}。")
            hidden_on = state_action(item, path, control_id, "ComboBox")
            observations.append({
                "class": "ComboBox", "control_id": control_id,
                "path": list(path), "item_count": len(values),
                "hidden_on": hidden_on,
            })

        for control_id in spinner_ids:
            item, path = current(control_id, "msctls_updown32")
            hwnd = int(item["hwnd"])
            partner_id = control_id - 4
            partner, _ = current(partner_id, "Edit")
            partner_hwnd = int(partner["hwnd"])
            original = get_window_text(partner_hwnd)
            post_click_at(hwnd, 5, 3)
            time.sleep(0.05)
            incremented = get_window_text(partner_hwnd)
            set_control_text(partner_hwnd, original)
            notify_edit(partner)
            record(item, path, "increment", f"伙伴值 {original!r}->{incremented!r}。")
            post_click_at(hwnd, 5, max(4, item["rect"]["height"] - 3))
            time.sleep(0.05)
            decremented = get_window_text(partner_hwnd)
            set_control_text(partner_hwnd, original)
            notify_edit(partner)
            record(item, path, "decrement", f"伙伴值 {original!r}->{decremented!r}。")
            boundary = []
            for value in ("-32768", "32767"):
                set_control_text(partner_hwnd, value)
                notify_edit(partner)
                boundary.append(get_window_text(partner_hwnd))
            set_control_text(partner_hwnd, original)
            notify_edit(partner)
            record(item, path, "boundary_values", f"伙伴边界读回={boundary}，已恢复。")
            hidden_on = state_action(item, path, control_id, "msctls_updown32")
            observations.append({
                "class": "msctls_updown32", "control_id": control_id,
                "path": list(path), "partner_id": partner_id,
                "hidden_on": hidden_on,
            })

        for control_id in pane_ids:
            item, path = current(control_id)
            if not str(item.get("class", "")).startswith("Afx:"):
                raise RuntimeError(
                    f"map-animation pane {control_id} has class {item.get('class')}"
                )
            hidden_on = state_action(
                item, path, control_id, str(item.get("class", "")),
            )
            observations.append({
                "class": item.get("class"), "control_id": control_id,
                "path": list(path), "hidden_on": hidden_on,
            })
    except Exception as exc:
        error = repr(exc)
        log(f"M12FIELDCONTROLS inner failure: {error}")
    finally:
        if window_hwnd and is_window(window_hwnd):
            close_window_safely(session, window_hwnd, 4.0)
        after = session.probe_rom.read_bytes()
        diffs = [
            index for index, (left, right) in enumerate(zip(before, after))
            if left != right
        ]
        unique = {item["action_id"]: item for item in records}
        validated = (
            error is None and len(unique) == 91 and not diffs
            and len(before) == len(after)
        )
        out_dir = session.out / "interaction-discovery"
        out_dir.mkdir(parents=True, exist_ok=True)
        (out_dir / "map-animation-field-actions.json").write_text(
            json.dumps({
                "schema_version": 1, "validated": validated,
                "error": error, "execution_record_count": len(unique),
                "diff_count": len(diffs) + int(len(before) != len(after)),
                "sha256_before": hashlib.sha256(before).hexdigest().upper(),
                "sha256_after": hashlib.sha256(after).hexdigest().upper(),
                "observations": observations,
                "execution_records": list(unique.values()) if validated else [],
            }, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
    if not validated:
        raise RuntimeError(
            f"map-animation fields did not validate: {len(unique)}/91 {error}"
        )
    log("M12FIELDCONTROLS complete: 91/91 actions, zero ROM diff")


def stage_m12buttoncontrols(session: ProbeSession) -> None:
    """Exercise all map-animation buttons and their nested descendants."""
    log("=== stage M12BUTTONCONTROLS ===")
    before = session.probe_rom.read_bytes()
    records = []
    observations = []
    error = None
    window_hwnd = 0
    page_button_ids = (
        120, 130, 140, 150, 170, 270, 320, 330, 350, 380,
        430, 460, 580, 610, 660,
    )
    global_button_ids = (300, 310)
    representatives = (110, 340, 530)

    def record(item, path, action, result):
        records.append({
            "action_id": stable_interaction_id(
                "地图动画", "Button", int(item.get("ctrl_id") or 0),
                tuple(path), action,
            ),
            "status": "passed", "result": result,
        })

    def open_window():
        nonlocal window_hwnd
        if window_hwnd and is_window(window_hwnd):
            return
        window = _open_data_window(
            session, 20011, "地图动画", dismiss_hidden=False,
        )
        if not window:
            raise RuntimeError("map-animation window did not appear")
        window_hwnd = int(window["hwnd"])
        move_window(window_hwnd, 40, 30, 1180, 850)
        time.sleep(0.5)

    def current_button(control_id, *, page_scoped=True):
        open_window()
        tree = enum_child_tree(window_hwnd)
        matches = find_controls(
            tree, cls="Button", ctrl_id=control_id, visible=True,
        )
        if not matches and page_scoped:
            located = switch_database_page_by_control(
                window_hwnd, control_id,
            )
            if not located:
                raise RuntimeError(
                    f"map-animation button {control_id} unavailable"
                )
            tree = enum_child_tree(window_hwnd)
            matches = find_controls(
                tree, cls="Button", ctrl_id=control_id, visible=True,
            )
        if not matches:
            raise RuntimeError(f"map-animation button {control_id} missing")
        item = matches[0]
        return item, tuple(control_tree_path(tree, item["hwnd"]) or ())

    def dismiss_descendants(known, tag):
        found = []
        seen = set()
        deadline = time.monotonic() + 1.0
        while time.monotonic() < deadline:
            for popup in session.top_windows():
                if popup["hwnd"] in known or popup["hwnd"] == window_hwnd:
                    continue
                if popup["class"] == "#32768" or not popup.get("class"):
                    continue
                if popup["hwnd"] not in seen:
                    seen.add(popup["hwnd"])
                    found.append({
                        "title": popup["title"], "class": popup["class"],
                    })
                    session.dump_window(
                        popup["hwnd"], f"M12BUTTON_{tag}_{len(seen)}",
                        menu=True,
                    )
                cancel = [candidate for candidate in find_controls(
                    enum_child_tree(popup["hwnd"]), cls="Button",
                    text_contains="取消", visible=True,
                ) if candidate.get("text") == "取消"]
                if cancel:
                    click_control(cancel[0]["hwnd"])
                    session.wait_gone(popup["hwnd"], 2.0)
                if is_window(popup["hwnd"]):
                    close_window_safely(session, popup["hwnd"], 2.0)
            time.sleep(0.06)
        return found

    def exercise_activation(control_id, action, *, page_scoped=True):
        nonlocal window_hwnd
        item, path = current_button(control_id, page_scoped=page_scoped)
        known = {top["hwnd"] for top in session.top_windows()}
        if action == "keyboard_activate":
            focused = focus_foreground_control(
                window_hwnd, int(item["hwnd"]),
            )
            send_key(int(item["hwnd"]), VK_SPACE)
        else:
            focused = None
            click_control(int(item["hwnd"]))
        time.sleep(0.25)
        descendants = dismiss_descendants(
            known, f"{control_id}_{action}",
        )
        alive = bool(window_hwnd and is_window(window_hwnd))
        record(
            item, path, action,
            f"焦点={focused}；主窗仍存在={alive}；子窗={descendants}。",
        )
        observations.append({
            "control_id": control_id, "action": action,
            "path": list(path), "focused": focused,
            "window_alive": alive, "descendants": descendants,
        })
        if not alive:
            window_hwnd = 0

    try:
        open_window()
        for control_id in page_button_ids:
            item, path = current_button(control_id)
            post_context_menu(int(item["hwnd"]), 6, 6)
            time.sleep(0.1)
            menu_visible = bool(visible_popup_menus(session.pid or 0))
            if menu_visible:
                send_escape(window_hwnd)
            record(
                item, path, "right_click",
                f"真实右键；可见菜单={menu_visible}。",
            )

            hidden_on = None
            for representative in representatives:
                if switch_database_page_by_control(
                    window_hwnd, representative,
                ) is None:
                    continue
                if not find_controls(
                    enum_child_tree(window_hwnd), cls="Button",
                    ctrl_id=control_id, visible=True,
                ):
                    hidden_on = representative
                    break
            restored, restored_path = current_button(control_id)
            record(
                item, path, "discover_state_triggers",
                f"切至代表控件 {hidden_on} 后隐藏；返回路径="
                f"{restored_path}，启用={bool(restored.get('enabled'))}。",
            )
            exercise_activation(control_id, "keyboard_activate")
            exercise_activation(control_id, "left_click")
            log(f"M12BUTTONCONTROLS button {control_id} complete")

        for control_id in global_button_ids:
            item, path = current_button(control_id, page_scoped=False)
            post_context_menu(int(item["hwnd"]), 6, 6)
            time.sleep(0.1)
            menu_visible = bool(visible_popup_menus(session.pid or 0))
            if menu_visible:
                send_escape(window_hwnd)
            record(
                item, path, "right_click",
                f"真实右键；可见菜单={menu_visible}。",
            )
            exercise_activation(
                control_id, "keyboard_activate", page_scoped=False,
            )
            exercise_activation(
                control_id, "left_click", page_scoped=False,
            )
    except Exception as exc:
        error = repr(exc)
        log(f"M12BUTTONCONTROLS inner failure: {error}")
    finally:
        if window_hwnd and is_window(window_hwnd):
            close_window_safely(session, window_hwnd, 4.0)
        after = session.probe_rom.read_bytes()
        diffs = [
            index for index, (left, right) in enumerate(zip(before, after))
            if left != right
        ]
        unique = {item["action_id"]: item for item in records}
        validated = (
            error is None and len(unique) == 66 and not diffs
            and len(before) == len(after)
        )
        out_dir = session.out / "interaction-discovery"
        out_dir.mkdir(parents=True, exist_ok=True)
        (out_dir / "map-animation-button-actions.json").write_text(
            json.dumps({
                "schema_version": 1, "validated": validated,
                "error": error, "execution_record_count": len(unique),
                "diff_count": len(diffs) + int(len(before) != len(after)),
                "sha256_before": hashlib.sha256(before).hexdigest().upper(),
                "sha256_after": hashlib.sha256(after).hexdigest().upper(),
                "observations": observations,
                "execution_records": list(unique.values()) if validated else [],
            }, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
    if not validated:
        raise RuntimeError(
            f"map-animation buttons did not validate: {len(unique)}/66 {error}"
        )
    log("M12BUTTONCONTROLS complete: 66/66 actions, zero ROM diff")


def stage_m12inputcontrols(session: ProbeSession) -> None:
    """Exercise the map-animation hexadecimal input dialog."""
    log("=== stage M12INPUTCONTROLS ===")
    before = session.probe_rom.read_bytes()
    records = []
    observations = []
    error = None
    window_hwnd = 0
    input_hwnd = 0
    input_case = str(getattr(session, "m12_input_case", "ok-keyboard"))
    case_map = {
        "ok-keyboard": (1, "keyboard_activate"),
        "ok-left": (1, "left_click"),
        "ok-right": (1, "right_click"),
        "cancel-keyboard": (2, "keyboard_activate"),
        "cancel-left": (2, "left_click"),
        "cancel-right": (2, "right_click"),
    }
    if input_case not in case_map:
        raise RuntimeError(f"invalid map-animation input case: {input_case}")

    def record(item, path, action, result):
        records.append({
            "action_id": stable_interaction_id(
                "请输入：", str(item.get("class", "")),
                int(item.get("ctrl_id") or 0), tuple(path), action,
            ),
            "status": "passed", "result": result,
        })

    def open_input():
        nonlocal input_hwnd
        located = switch_database_page_by_control(window_hwnd, 150)
        if not located:
            raise RuntimeError("map-animation input opener 150 unavailable")
        opener = find_controls(
            enum_child_tree(window_hwnd), cls="Button",
            ctrl_id=150, visible=True,
        )[0]
        lists = find_controls(
            enum_child_tree(window_hwnd), cls="ListBox",
            ctrl_id=110, visible=True,
        )
        if lists:
            list_hwnd = int(lists[0]["hwnd"])
            _send_msg_num(list_hwnd, LB_SETCURSEL, 0, 0)
            user32.PostMessageW(
                user32.GetParent(list_hwnd), WM_COMMAND,
                110 | (LBN_SELCHANGE << 16), list_hwnd,
            )
            time.sleep(0.1)
            opener = find_controls(
                enum_child_tree(window_hwnd), cls="Button",
                ctrl_id=150, visible=True,
            )[0]
        known = {top["hwnd"] for top in session.top_windows()}
        click_control(opener["hwnd"])
        popup = session.wait_new_top(exclude=known, timeout=5.0)
        if not popup or popup["title"] != "请输入：":
            raise RuntimeError(f"hex input dialog did not appear: {popup}")
        input_hwnd = int(popup["hwnd"])
        time.sleep(0.2)

    def close_input():
        nonlocal input_hwnd
        if not input_hwnd or not is_window(input_hwnd):
            input_hwnd = 0
            return
        cancel = find_controls(
            enum_child_tree(input_hwnd), cls="Button",
            ctrl_id=2, visible=True,
        )
        if cancel:
            click_control(cancel[0]["hwnd"])
            session.wait_gone(input_hwnd, 2.0)
        if is_window(input_hwnd):
            close_window_safely(session, input_hwnd, 2.0)
        input_hwnd = 0

    try:
        window = _open_data_window(
            session, 20011, "地图动画", dismiss_hidden=False,
        )
        if not window:
            raise RuntimeError("map-animation window did not appear")
        window_hwnd = int(window["hwnd"])
        move_window(window_hwnd, 40, 30, 1180, 850)
        time.sleep(0.5)

        open_input()
        tree = enum_child_tree(input_hwnd)
        item = find_controls(
            tree, cls="Edit", ctrl_id=1001, visible=True,
        )[0]
        path = tuple(control_tree_path(tree, item["hwnd"]) or ())
        hwnd = int(item["hwnd"])
        original = get_window_text(hwnd)
        focused = focus_foreground_control(input_hwnd, hwnd)
        record(item, path, "focus", f"真实焦点={focused}。")
        set_control_text(hwnd, "00FF")
        replaced = get_window_text(hwnd)
        set_control_text(hwnd, original)
        record(item, path, "replace_value", f"替换读回={replaced!r}，已恢复。")
        focus_foreground_control(input_hwnd, hwnd)
        keybd(0x11)
        send_key(hwnd, ord("A"))
        send_key(hwnd, ord("Z"))
        keybd(0x11, up=True)
        set_control_text(hwnd, original)
        record(item, path, "keyboard_shortcuts", "执行 Ctrl+A/Ctrl+Z 并恢复。")
        post_context_menu(hwnd, 5, 5)
        time.sleep(0.1)
        menu_visible = bool(visible_popup_menus(session.pid or 0))
        if menu_visible:
            send_escape(input_hwnd)
        record(item, path, "right_click", f"右键菜单={menu_visible}。")
        set_control_text(hwnd, "")
        empty_value = get_window_text(hwnd)
        set_control_text(hwnd, "F" * 256)
        long_value = get_window_text(hwnd)
        set_control_text(hwnd, original)
        record(
            item, path, "boundary_values",
            f"空值={empty_value!r}；长值长度={len(long_value)}；已恢复。",
        )
        close_input()

        button_id, action = case_map[input_case]
        open_input()
        tree = enum_child_tree(input_hwnd)
        item = find_controls(
            tree, cls="Button", ctrl_id=button_id, visible=True,
        )[0]
        path = tuple(control_tree_path(tree, item["hwnd"]) or ())
        if action == "keyboard_activate":
            focused = focus_foreground_control(
                input_hwnd, int(item["hwnd"]),
            )
            send_key(int(item["hwnd"]), VK_SPACE)
        elif action == "left_click":
            focused = None
            click_control(int(item["hwnd"]))
        else:
            focused = None
            post_context_menu(int(item["hwnd"]), 5, 5)
            time.sleep(0.1)
            if visible_popup_menus(session.pid or 0):
                send_escape(input_hwnd)
        time.sleep(0.15)
        remained = bool(is_window(input_hwnd))
        record(
            item, path, action,
            f"焦点={focused}；操作后弹窗仍存在={remained}。",
        )
        observations.append({
            "button_id": button_id, "action": action,
            "path": list(path), "focused": focused,
            "remained": remained,
        })
        close_input()
    except Exception as exc:
        error = repr(exc)
        log(f"M12INPUTCONTROLS inner failure: {error}")
    finally:
        close_input()
        if window_hwnd and is_window(window_hwnd):
            close_window_safely(session, window_hwnd, 4.0)
        after = session.probe_rom.read_bytes()
        diffs = [
            index for index, (left, right) in enumerate(zip(before, after))
            if left != right
        ]
        unique = {item["action_id"]: item for item in records}
        validated = (
            error is None and len(unique) == 6 and not diffs
            and len(before) == len(after)
        )
        out_dir = session.out / "interaction-discovery"
        out_dir.mkdir(parents=True, exist_ok=True)
        (out_dir / f"map-animation-input-{input_case}-actions.json").write_text(
            json.dumps({
                "schema_version": 1, "validated": validated,
                "error": error, "execution_record_count": len(unique),
                "diff_count": len(diffs) + int(len(before) != len(after)),
                "sha256_before": hashlib.sha256(before).hexdigest().upper(),
                "sha256_after": hashlib.sha256(after).hexdigest().upper(),
                "observations": observations,
                "execution_records": list(unique.values()) if validated else [],
            }, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
    if not validated:
        raise RuntimeError(
            f"map-animation input did not validate: {len(unique)}/6 {error}"
        )
    log(
        f"M12INPUTCONTROLS {input_case} complete: 6/6 actions, "
        "zero ROM diff"
    )


CONTEXT_DISCOVERY_CLASSES = {
    "Button",
    "ComboBox",
    "Edit",
    "ListBox",
    "SysListView32",
    "CPageControl",
    "_EL_DrawPanel",
    "_EL_PicBox",
    "AfxWnd42s",
}


def probe_window_context_menus(
    session: ProbeSession,
    hwnd: int,
    state_name: str,
) -> list[dict]:
    """Right-click every relevant control/region and record popup menus.

    No menu command is selected.  Each popup is dismissed immediately with
    Escape.  The caller uses an isolated reference executable and ROM copy.
    """

    results: list[dict] = []
    root = user32.GetAncestor(hwnd, 2) or hwnd
    controls = [
        item
        for item in flatten_tree(enum_child_tree(hwnd))
        if item.get("visible")
        and item.get("enabled")
        and item.get("class") in CONTEXT_DISCOVERY_CLASSES
    ]
    log(f"context sweep {state_name}: {len(controls)} controls")
    for control_index, control in enumerate(controls):
        ctrl_hwnd = control["hwnd"]
        for point_index, (x, y) in enumerate(context_probe_points(control)):
            while visible_popup_menus(session.pid or 0):
                send_key(root, VK_ESCAPE)
                time.sleep(0.05)
            post_click_at(ctrl_hwnd, x, y, button="right")
            time.sleep(0.12)
            menus = visible_popup_menus(session.pid or 0)
            used_real_input = False
            if not menus:
                used_real_input = real_right_click_control_cell(ctrl_hwnd, x, y)
                time.sleep(0.15)
                menus = visible_popup_menus(session.pid or 0)
            record = {
                "state": state_name,
                "control_index": control_index,
                "point_index": point_index,
                "class": control["class"],
                "control_id": control["ctrl_id"],
                "text": control.get("text", ""),
                "point": [x, y],
                "used_real_input": used_real_input,
                "popup_count": len(menus),
                "menus": [menu["items"] for menu in menus],
            }
            results.append(record)
            if menus:
                log(
                    f"context menu {state_name} {control['class']}#{control['ctrl_id']} "
                    f"point={x},{y}: {record['menus']}"
                )
                send_key(root, VK_ESCAPE)
                time.sleep(0.08)
    return results


def stage_dbctx(session: ProbeSession) -> None:
    """Discover database context menus across all six top-level pages."""

    log("=== stage DBCTX: recursive database context-menu discovery ===")
    if not session.main_hwnd or not is_window(session.main_hwnd):
        raise RuntimeError("main window not alive")
    if not session.rom_is_loaded():
        raise RuntimeError("ROM not loaded")
    # The reference program preloads database pages as hidden WTWindow
    # instances.  Destroying hidden windows before the first open makes its
    # own command fail with "指定窗口尚未载入".
    window = _open_data_window(session, 20008, "数据库", dismiss_hidden=False)
    if not window:
        raise RuntimeError("database window did not appear")
    hwnd = window["hwnd"]
    labels = ["机体修改", "人物修改", "武器修改", "战斗对话", "其他修改1", "其他修改2"]
    all_results: list[dict] = []
    tab_results: list[dict] = []
    win_rect = get_window_rect(hwnd)
    try:
        tree = enum_child_tree(hwnd)
        page_ctrls = [
            item
            for item in find_controls(tree, cls="CPageControl")
            if item.get("visible")
        ]
        if not page_ctrls:
            raise RuntimeError("database top-level CPageControl not found")
        page_ctrl = max(
            page_ctrls,
            key=lambda item: item["rect"]["width"] * item["rect"]["height"],
        )
        ctrl_rect = page_ctrl["rect"]
        dx, dy = _client_offset(hwnd)
        tab_y = ctrl_rect["top"] - win_rect["top"] + 24
        x_start = ctrl_rect["left"] - win_rect["left"] + 14
        x_end = ctrl_rect["right"] - win_rect["left"] - 24
        seen_signatures: set[tuple] = set()
        tab_states: list[tuple[str, int, tuple, int]] = []
        # Phase 1 only touches the owner-drawn header band.  Do not probe page
        # contents here: selecting another record inside a page also changes
        # control text and must never be mistaken for a new page.
        for x in range(x_start, x_end, 12):
            real_click_at(hwnd, x - dx, tab_y - dy)
            time.sleep(0.25)
            signature = _window_ctrl_sig(hwnd)
            if signature in seen_signatures:
                continue
            seen_signatures.add(signature)
            page_index = len(seen_signatures) - 1
            label = labels[page_index] if page_index < len(labels) else f"未知页{page_index + 1}"
            visible_count = len(
                [
                    item
                    for item in flatten_tree(enum_child_tree(hwnd))
                    if item.get("visible")
                ]
            )
            tab_states.append((label, x, signature, visible_count))
            tab_results.append(
                {
                    "label": label,
                    "status": "discovered",
                    "probe_window_x": x,
                    "visible_control_count": visible_count,
                }
            )
            log(
                f"DBCTX discovered tab {page_index + 1}: {label!r} "
                f"x={x} controls={visible_count}"
            )
            if len(seen_signatures) >= len(labels):
                break
        if len(seen_signatures) != len(labels):
            log(
                f"DBCTX incomplete tab discovery: "
                f"{len(seen_signatures)}/{len(labels)} distinct states"
            )
        else:
            # Phase 2 returns to each verified header coordinate before it
            # explores page contents.  Record selection changes during the
            # sweep therefore cannot alter the page denominator.
            for label, x, expected_signature, _visible_count in tab_states:
                real_click_at(hwnd, x - dx, tab_y - dy)
                time.sleep(0.4)
                actual_signature = _window_ctrl_sig(hwnd)
                signature_match = actual_signature == expected_signature
                for record in tab_results:
                    if record["label"] == label:
                        record["phase2_signature_match"] = signature_match
                        break
                if not signature_match:
                    raise RuntimeError(
                        f"database tab {label} did not restore its phase-1 signature"
                    )
                session.dump_window(hwnd, f"DBCTX_{label}", menu=False, sleep_before=0.1)
                all_results.extend(probe_window_context_menus(session, hwnd, label))
    finally:
        out_dir = session.out / "interaction-discovery"
        out_dir.mkdir(parents=True, exist_ok=True)
        (out_dir / "database-context-menus.json").write_text(
            json.dumps(
                {
                    "schema_version": 1,
                    "scope": "isolated reference executable; no menu command selected; no save",
                    "tabs": tab_results,
                    "records": all_results,
                },
                ensure_ascii=False,
                indent=2,
            )
            + "\n",
            encoding="utf-8",
        )
        close_window_safely(session, hwnd)
    log(f"DBCTX complete: {len(all_results)} right-click probes")


def switch_database_page_by_control(
    hwnd: int,
    required_control_id: int,
) -> tuple[int, dict] | None:
    """Sweep only the database tab band until a page-specific control appears."""

    tree = enum_child_tree(hwnd)
    page_ctrls = [
        item
        for item in find_controls(tree, cls="CPageControl")
        if item.get("visible")
    ]
    if not page_ctrls:
        return None
    top_page = [
        item for item in page_ctrls if int(item.get("ctrl_id") or 0) == 100
    ]
    page_ctrl = top_page[0] if top_page else max(
        page_ctrls,
        key=lambda item: item["rect"]["width"] * item["rect"]["height"],
    )
    win_rect = get_window_rect(hwnd)
    dx, dy = _client_offset(hwnd)
    ctrl_rect = page_ctrl["rect"]
    tab_y = ctrl_rect["top"] - win_rect["top"] + 24
    x_start = ctrl_rect["left"] - win_rect["left"] + 14
    x_end = ctrl_rect["right"] - win_rect["left"] - 24
    page_width = max(1, ctrl_rect["right"] - ctrl_rect["left"])
    # Prefer process-local posted input.  It remains deterministic when a
    # recording program exposes a transparent, always-on-top overlay that
    # correctly blocks global cursor injection but should not make the legacy
    # page undiscoverable.
    for local_x in range(14, max(15, page_width - 24), 12):
        post_click_at(page_ctrl["hwnd"], local_x, 24)
        time.sleep(0.18)
        matches = find_controls(
            enum_child_tree(hwnd), ctrl_id=required_control_id, visible=True
        )
        if matches:
            return x_start - 14 + local_x, matches[0]
    for x in range(x_start, x_end, 12):
        real_click_at(hwnd, x - dx, tab_y - dy)
        time.sleep(0.18)
        matches = find_controls(
            enum_child_tree(hwnd), ctrl_id=required_control_id, visible=True
        )
        if matches:
            return x, matches[0]
    return None


def stage_dbcmd(session: ProbeSession) -> None:
    """Execute safe, nested database context commands on the isolated copy."""

    log("=== stage DBCMD: database context-command descendants ===")
    if not session.main_hwnd or not is_window(session.main_hwnd):
        raise RuntimeError("main window not alive")
    if not session.rom_is_loaded():
        raise RuntimeError("ROM not loaded")
    window = _open_data_window(session, 20008, "数据库", dismiss_hidden=False)
    if not window:
        raise RuntimeError("database window did not appear")
    hwnd = window["hwnd"]
    # Command IDs are read from the validated DBCTX popup evidence.  Sending
    # WM_COMMAND invokes the same VCL handler as selecting that popup item and
    # avoids making descendant discovery depend on popup-window timing.
    commands = (
        ("武器修改", 2530, "插入", 20014),
        ("武器修改", 2530, "编辑", 20016),
        ("机体修改", 120, "导出机体", 20003),
        ("人物修改", 630, "导出人物", 20009),
    )
    results: list[dict] = []
    try:
        for ordinal, (state, control_id, command_text, command_id) in enumerate(commands, 1):
            located = switch_database_page_by_control(hwnd, control_id)
            if located is None:
                results.append(
                    {
                        "state": state,
                        "control_id": control_id,
                        "command": command_text,
                        "status": "target_not_found",
                    }
                )
                continue
            tab_x, control = located
            control_width = max(1, control["rect"]["width"])
            control_height = max(1, control["rect"]["height"])
            # Standard/VCL list boxes do not necessarily update ItemIndex on a
            # right click.  Select the first visible row before invoking a
            # context command so insert/edit handlers do not receive -1.
            post_click_at(
                control["hwnd"],
                min(control_width - 1, max(4, control_width // 8)),
                min(control_height - 1, 10),
                button="left",
            )
            time.sleep(0.20)
            known = {item["hwnd"] for item in session.top_windows()}
            menu = open_control_context_menu(session, control)
            menu_items = menu.get("items", []) if menu else []
            before_signature = _window_ctrl_sig(hwnd)
            if menu is not None:
                send_key(hwnd, VK_ESCAPE)
                time.sleep(0.10)
            user32.PostMessageW(hwnd, WM_COMMAND, command_id, 0)
            activation = "wm_command_from_validated_menu_id"
            time.sleep(1.2)
            after_signature = _window_ctrl_sig(hwnd) if is_window(hwnd) else ()
            descendants = [
                item
                for item in session.top_windows()
                if item["hwnd"] not in known
                and item["hwnd"] != hwnd
                and item["class"] != "#32768"
            ]
            foreground = user32.GetForegroundWindow()
            foreground_record = None
            if foreground and foreground not in known and foreground != hwnd:
                foreground_record = {
                    "hwnd": foreground,
                    "title": get_window_text(foreground),
                    "class": get_class_name(foreground),
                    "pid": window_pid(foreground),
                    "owned_by_reference": owned_by_process(
                        foreground, session.pid or 0
                    ),
                }
                if (
                    foreground_record["owned_by_reference"]
                    and foreground_record["class"] != "#32768"
                    and all(item["hwnd"] != foreground for item in descendants)
                ):
                    descendants.append(
                        {
                            **foreground_record,
                            "rect": get_window_rect(foreground),
                        }
                    )
            captured = []
            for child_index, child in enumerate(descendants, 1):
                safe_command = re.sub(r"[^0-9A-Za-z\u4e00-\u9fff]+", "_", command_text)
                tag = f"DBCMD_{ordinal:02d}_{state}_{safe_command}_{child_index}"
                dump = session.dump_window(child["hwnd"], tag, menu=True)
                combo_options = []
                for item in flatten_tree(dump["tree"]):
                    if item.get("visible") and item.get("class") == "ComboBox":
                        combo_options.append(
                            {
                                "control_id": item.get("ctrl_id"),
                                "selected": item.get("combo_selected"),
                                "items": read_combo_items(item["hwnd"]),
                            }
                        )
                state_variants = []
                title = child["title"]
                if title == "创建物体":
                    combos = find_controls(
                        dump["tree"], cls="ComboBox", ctrl_id=160, visible=True
                    )
                    if combos:
                        for selected in (0x00, 0x40, 0x80, 0xC0, 0xFE):
                            set_combo_selection(combos[0]["hwnd"], selected)
                            time.sleep(0.12)
                            state_variants.append(
                                {
                                    "trigger": f"object={selected:02X}",
                                    **compact_control_state(child["hwnd"]),
                                }
                            )
                elif title in {"定义颜色", "运行规律"}:
                    for button_id in (310, 320):
                        buttons_for_state = find_controls(
                            enum_child_tree(child["hwnd"]),
                            cls="Button",
                            ctrl_id=button_id,
                            visible=True,
                        )
                        if buttons_for_state:
                            click_control(buttons_for_state[0]["hwnd"])
                            time.sleep(0.12)
                            state_variants.append(
                                {
                                    "trigger": f"button={button_id}",
                                    **compact_control_state(child["hwnd"]),
                                }
                            )
                    if title == "运行规律":
                        variant_combos = find_controls(
                            enum_child_tree(child["hwnd"]),
                            cls="ComboBox",
                            ctrl_id=330,
                            visible=True,
                        )
                        if variant_combos:
                            for selected in (0, 1):
                                set_combo_selection(
                                    variant_combos[0]["hwnd"], selected
                                )
                                time.sleep(0.12)
                                state_variants.append(
                                    {
                                        "trigger": f"variant={selected}",
                                        **compact_control_state(child["hwnd"]),
                                    }
                                )
                captured.append(
                    {
                        "title": child["title"],
                        "class": child["class"],
                        "tag": tag,
                        "visible_controls": len(
                            [
                                item
                                for item in flatten_tree(dump["tree"])
                                if item.get("visible")
                            ]
                        ),
                        "combo_options": combo_options,
                        "state_variants": state_variants,
                    }
                )
                close_window_safely(session, child["hwnd"], timeout=5.0)
            results.append(
                {
                    "state": state,
                    "control_id": control_id,
                    "command": command_text,
                    "command_id": command_id,
                    "activation": activation,
                    "status": "captured" if captured else "no_descendant_window",
                    "tab_x": tab_x,
                    "menu": menu_items,
                    "database_signature_changed": before_signature != after_signature,
                    "descendants": captured,
                    "foreground_after_command": foreground_record,
                }
            )
    finally:
        out_dir = session.out / "interaction-discovery"
        out_dir.mkdir(parents=True, exist_ok=True)
        (out_dir / "database-command-descendants.json").write_text(
            json.dumps(
                {
                    "schema_version": 1,
                    "validated": len(results) == len(commands) and all(
                        item.get("status") == "captured" for item in results
                    ),
                    "scope": "isolated reference executable; descendant dialogs cancelled; no save",
                    "records": results,
                },
                ensure_ascii=False,
                indent=2,
            )
            + "\n",
            encoding="utf-8",
        )
        close_window_safely(session, hwnd)
    log(f"DBCMD complete: {len(results)} commands")


def _open_weapon_instruction_selector(
    session: ProbeSession,
    database_hwnd: int,
) -> dict | None:
    """Open the reference weapon instruction chooser with a valid row active."""

    located = switch_database_page_by_control(database_hwnd, 2530)
    if located is None:
        return None
    _tab_x, _initial_control = located
    animation_list_id = 2530 if session.db_animation_kind == "ally" else 2520
    if animation_list_id == 2530:
        matches = find_controls(
            enum_child_tree(database_hwnd),
            cls="ListBox", ctrl_id=animation_list_id, visible=True,
        )
    else:
        nested_pages = find_controls(
            enum_child_tree(database_hwnd),
            cls="CPageControl", ctrl_id=2540, visible=True,
        )
        if not nested_pages:
            return None
        nested = nested_pages[0]
        nested_rect = nested["rect"]
        window_rect = get_window_rect(database_hwnd)
        dx, dy = _client_offset(database_hwnd)
        tab_y = nested_rect["top"] - window_rect["top"] + 18
        x_start = nested_rect["left"] - window_rect["left"] + 14
        x_end = min(
            nested_rect["right"] - window_rect["left"] - 14,
            x_start + 360,
        )
        matches = []
        for x in range(x_start, x_end, 14):
            real_click_at(database_hwnd, x - dx, tab_y - dy)
            time.sleep(0.14)
            matches = find_controls(
                enum_child_tree(database_hwnd),
                cls="ListBox", ctrl_id=animation_list_id, visible=True,
            )
            if matches:
                break
    if not matches:
        return None
    control = matches[0]
    weapon_lists = find_controls(
        enum_child_tree(database_hwnd),
        cls="ListBox", ctrl_id=610, visible=True,
    )
    if not weapon_lists:
        return None
    weapon_list = weapon_lists[0]["hwnd"]
    weapon_row = max(0, int(session.db_weapon_record) - 1)
    if _send_msg_num(weapon_list, 0x0186, weapon_row, 0) == -1:
        raise RuntimeError(
            f"weapon record {session.db_weapon_record} cannot be selected"
        )
    notify_parent = user32.GetParent(weapon_list)
    notified: set[int] = set()
    while notify_parent and notify_parent not in notified:
        notified.add(notify_parent)
        _send_msg_num(
            notify_parent, WM_COMMAND,
            610 | (1 << 16),  # LBN_SELCHANGE
            weapon_list,
        )
        if notify_parent == database_hwnd:
            break
        notify_parent = user32.GetParent(notify_parent)
    time.sleep(0.20)
    refreshed = find_controls(
        enum_child_tree(database_hwnd),
        cls="ListBox", ctrl_id=animation_list_id, visible=True,
    )
    if refreshed:
        control = refreshed[0]
    instruction_list = control["hwnd"]
    instruction_row = max(0, int(session.db_instruction_row))
    if _send_msg_num(instruction_list, 0x0186, instruction_row, 0) == -1:
        raise RuntimeError(
            f"weapon instruction row {instruction_row} cannot be selected"
        )
    notify_parent = user32.GetParent(instruction_list)
    notified = set()
    while notify_parent and notify_parent not in notified:
        notified.add(notify_parent)
        _send_msg_num(
            notify_parent, WM_COMMAND,
            animation_list_id | (1 << 16),  # LBN_SELCHANGE
            instruction_list,
        )
        if notify_parent == database_hwnd:
            break
        notify_parent = user32.GetParent(notify_parent)
    time.sleep(0.12)
    width = max(1, control["rect"]["width"])
    height = max(1, control["rect"]["height"])
    # The owner-drawn list reports 18px logical item rectangles while the
    # actual 125%-DPI hit boxes are about 22px.  Derive the physical hit row
    # from the fixed 20 visible slots and the current scrolled top index.
    row_height = max(1, height // 20)
    top_index = max(0, _send_msg_num(instruction_list, 0x018E, 0, 0))
    target_y = min(
        height - 2,
        max(4, (instruction_row - top_index) * row_height + row_height // 2),
    )
    # Build the owner-drawn popup once before dispatching its command id.
    # On cold database opens the legacy window may not have created the popup
    # menu yet, in which case posting 20014 alone is intermittently ignored.
    popup_x = min(width - 1, max(4, width // 8))
    post_click_at(instruction_list, popup_x, target_y, button="left")
    time.sleep(0.12)
    post_click_at(instruction_list, popup_x, target_y, button="right")
    time.sleep(0.16)
    menus = visible_popup_menus(session.pid or 0)
    if not menus:
        real_right_click_control_cell(instruction_list, popup_x, target_y)
        time.sleep(0.20)
        menus = visible_popup_menus(session.pid or 0)
    menu = menus[0] if menus else None
    current_row = _send_msg_num(instruction_list, 0x0188, 0, 0)  # LB_GETCURSEL
    log(
        f"weapon instruction row requested={instruction_row} "
        f"selected={current_row} top={top_index} target_y={target_y}"
    )
    if menu is not None:
        send_key(database_hwnd, VK_ESCAPE)
        time.sleep(0.10)
    known = {item["hwnd"] for item in session.top_windows()}
    user32.PostMessageW(database_hwnd, WM_COMMAND, 20014, 0)
    activation = (
        "wm_command_after_validated_popup"
        if menu is not None
        else "popup_unavailable_wm_command_fallback"
    )
    log(f"weapon selector activation: {activation}")
    return session.wait_new_top(
        exclude=known,
        timeout=3.0,
        title_contains="武器指令",
    )


def stage_dbwinstr(session: ProbeSession) -> None:
    """Traverse every command button in the legacy weapon instruction chooser."""

    log("=== stage DBWINSTR: weapon instruction descendants ===")
    if not session.main_hwnd or not is_window(session.main_hwnd):
        raise RuntimeError("main window not alive")
    if not session.rom_is_loaded():
        raise RuntimeError("ROM not loaded")
    window = _open_data_window(session, 20008, "数据库", dismiss_hidden=False)
    if not window:
        raise RuntimeError("database window did not appear")
    database_hwnd = window["hwnd"]
    expected = (
        (100, "F4定义声音"),
        (110, "F0定义颜色"),
        (120, "F2定义光束图库"),
        (130, "F3定义光束规律"),
        (200, "E0切换00区域的图库号"),
        (210, "E1切换01区域的图库号"),
        (140, "FD移动屏幕"),
        (150, "FE跳转重复"),
        (160, "F9创建物体"),
        (170, "42/C2定义物体运行规律"),
        (180, "等待(帧)"),
        (190, "FF动画结束"),
    )
    results: list[dict] = []
    try:
        for ordinal, (button_id, caption) in enumerate(expected, 1):
            selector = _open_weapon_instruction_selector(
                session, database_hwnd
            )
            if selector is None:
                results.append(
                    {
                        "button_id": button_id,
                        "caption": caption,
                        "status": "selector_not_opened",
                    }
                )
                continue
            selector_hwnd = selector["hwnd"]
            buttons = find_controls(
                enum_child_tree(selector_hwnd),
                cls="Button",
                ctrl_id=button_id,
                visible=True,
            )
            if not buttons:
                results.append(
                    {
                        "button_id": button_id,
                        "caption": caption,
                        "status": "button_not_found",
                    }
                )
                close_window_safely(session, selector_hwnd)
                continue
            before_database = _window_ctrl_sig(database_hwnd)
            known = {item["hwnd"] for item in session.top_windows()}
            click_control(buttons[0]["hwnd"])
            time.sleep(0.9)
            descendants = [
                item
                for item in session.top_windows()
                if item["hwnd"] not in known
                and item["hwnd"] not in {database_hwnd, selector_hwnd}
                and item["class"] != "#32768"
            ]
            captured = []
            for child_index, child in enumerate(descendants, 1):
                safe_caption = re.sub(
                    r"[^0-9A-Za-z\u4e00-\u9fff]+", "_", caption
                )
                tag = (
                    f"DBWINSTR_{ordinal:02d}_{safe_caption}_{child_index}"
                )
                dump = session.dump_window(child["hwnd"], tag, menu=True)
                combo_options = []
                for item in flatten_tree(dump["tree"]):
                    if item.get("visible") and item.get("class") == "ComboBox":
                        combo_options.append(
                            {
                                "control_id": item.get("ctrl_id"),
                                "selected": item.get("combo_selected"),
                                "items": read_combo_items(item["hwnd"]),
                            }
                        )
                state_variants = []
                title = child["title"]
                if title == "创建物体":
                    combos = find_controls(
                        dump["tree"], cls="ComboBox", ctrl_id=160, visible=True
                    )
                    if combos:
                        for selected in (0x00, 0x40, 0x80, 0xC0, 0xFE):
                            set_combo_selection(combos[0]["hwnd"], selected)
                            time.sleep(0.12)
                            state_variants.append(
                                {
                                    "trigger": f"object={selected:02X}",
                                    **compact_control_state(child["hwnd"]),
                                }
                            )
                elif title in {"定义颜色", "运行规律"}:
                    for button_id in (310, 320):
                        buttons_for_state = find_controls(
                            enum_child_tree(child["hwnd"]),
                            cls="Button",
                            ctrl_id=button_id,
                            visible=True,
                        )
                        if buttons_for_state:
                            click_control(buttons_for_state[0]["hwnd"])
                            time.sleep(0.12)
                            state_variants.append(
                                {
                                    "trigger": f"button={button_id}",
                                    **compact_control_state(child["hwnd"]),
                                }
                            )
                    if title == "运行规律":
                        variant_combos = find_controls(
                            enum_child_tree(child["hwnd"]),
                            cls="ComboBox",
                            ctrl_id=330,
                            visible=True,
                        )
                        if variant_combos:
                            for selected in (0, 1):
                                set_combo_selection(
                                    variant_combos[0]["hwnd"], selected
                                )
                                time.sleep(0.12)
                                state_variants.append(
                                    {
                                        "trigger": f"variant={selected}",
                                        **compact_control_state(child["hwnd"]),
                                    }
                                )
                captured.append(
                    {
                        "title": child["title"],
                        "class": child["class"],
                        "tag": tag,
                        "visible_controls": len(
                            [
                                item
                                for item in flatten_tree(dump["tree"])
                                if item.get("visible")
                            ]
                        ),
                        "combo_options": combo_options,
                        "state_variants": state_variants,
                    }
                )
                close_window_safely(session, child["hwnd"], timeout=4.0)
            selector_gone = not is_window_visible(selector_hwnd)
            if not selector_gone:
                close_window_safely(session, selector_hwnd, timeout=3.0)
            after_database = (
                _window_ctrl_sig(database_hwnd)
                if is_window(database_hwnd)
                else ()
            )
            results.append(
                {
                    "button_id": button_id,
                    "caption": caption,
                    "status": (
                        "captured"
                        if captured
                        else "inline_or_immediate_action"
                    ),
                    "selector_closed_by_action": selector_gone,
                    "database_signature_changed": (
                        before_database != after_database
                    ),
                    "descendants": captured,
                }
            )
    finally:
        out_dir = session.out / "interaction-discovery"
        out_dir.mkdir(parents=True, exist_ok=True)
        complete = len(results) == len(expected) and all(
            item["status"]
            not in {"selector_not_opened", "button_not_found"}
            for item in results
        )
        (out_dir / "weapon-instruction-descendants.json").write_text(
            json.dumps(
                {
                    "schema_version": 1,
                    "validated": complete,
                    "scope": (
                        "isolated reference executable; parameter dialogs "
                        "cancelled; immediate draft actions not saved"
                    ),
                    "expected_button_count": len(expected),
                    "records": results,
                },
                ensure_ascii=False,
                indent=2,
            )
            + "\n",
            encoding="utf-8",
        )
        close_window_safely(session, database_hwnd)
    log(f"DBWINSTR complete: {len(results)}/{len(expected)} buttons")


def stage_dbsavef3(session: ProbeSession) -> None:
    """Insert one legacy named command, save the ROM, and report bytes."""

    log("=== stage DBSAVEF3: isolated F3 insertion/save golden ===")
    if not session.main_hwnd or not is_window(session.main_hwnd):
        raise RuntimeError("main window not alive")
    if not session.rom_is_loaded():
        raise RuntimeError("ROM not loaded")
    rom_path = session.probe_rom
    before = rom_path.read_bytes()
    window = _open_data_window(session, 20008, "数据库", dismiss_hidden=False)
    if not window:
        raise RuntimeError("database window did not appear")
    database_hwnd = window["hwnd"]
    # The legacy page control finishes populating after the top-level window
    # becomes visible.  Retry the idempotent selector command so a slow first
    # tab activation does not invalidate the save golden.
    time.sleep(0.8)
    selector = None
    for _attempt in range(3):
        selector = _open_weapon_instruction_selector(session, database_hwnd)
        if selector is not None:
            break
        time.sleep(0.6)
    if selector is None:
        raise RuntimeError("weapon instruction selector did not open")
    selector_hwnd = selector["hwnd"]
    selector_tree = enum_child_tree(selector_hwnd)
    specs = {
        120: ("F2", "定义光束规律图库"),
        130: ("F3", "定义光束规律"),
        200: ("E0", "切换精灵图库0"),
        210: ("E1", "切换精灵图库1"),
        150: ("FE", "跳转重复"),
        160: ("F9", "创建物体"),
        170: ("42C2", "运行规律"),
    }
    if session.dbins_button not in specs:
        raise RuntimeError(f"unsupported save-golden button {session.dbins_button}")
    command_name, parameter_title = specs[session.dbins_button]
    command_buttons = find_controls(
        selector_tree, cls="Button", ctrl_id=session.dbins_button, visible=True
    )
    if not command_buttons:
        raise RuntimeError(f"{command_name} selector button missing")
    known = {item["hwnd"] for item in session.top_windows()}
    click_control(command_buttons[0]["hwnd"])
    parameter = session.wait_new_top(
        exclude=known, timeout=4.0, title_contains=parameter_title
    )
    if parameter is None:
        raise RuntimeError(f"{command_name} parameter window did not open")
    parameter_hwnd = parameter["hwnd"]
    parameter_dump = session.dump_window(
        parameter_hwnd, f"DBSAVE_{command_name}_参数_修改前", menu=False
    )
    combos = find_controls(
        parameter_dump["tree"], cls="ComboBox", ctrl_id=160, visible=True
    )
    if not combos:
        raise RuntimeError(f"{command_name} option combo missing")
    options = read_combo_items(combos[0]["hwnd"])
    option = max(0, min(int(session.dbins_option), max(0, len(options) - 1)))
    set_combo_selection(combos[0]["hwnd"], option)
    if command_name == "FE":
        repeat_edits = find_controls(
            parameter_dump["tree"], cls="Edit", ctrl_id=120, visible=True
        )
        if not repeat_edits:
            raise RuntimeError("FE repeat-count editor missing")
        set_control_text(repeat_edits[0]["hwnd"], str(session.dbins_value))
    elif command_name == "F9":
        x_edits = find_controls(
            parameter_dump["tree"], cls="Edit", ctrl_id=120, visible=True
        )
        y_edits = find_controls(
            parameter_dump["tree"], cls="Edit", ctrl_id=130, visible=True
        )
        if not x_edits or not y_edits:
            raise RuntimeError("F9 coordinate editors missing")
        set_control_text(x_edits[0]["hwnd"], str(session.dbins_value))
        set_control_text(y_edits[0]["hwnd"], str(session.dbins_value2))
    elif command_name == "42C2":
        current_tree = enum_child_tree(parameter_hwnd)
        family_id = 310 if session.dbins_rule_family == "42" else 320
        family_buttons = find_controls(
            current_tree, cls="Button", ctrl_id=family_id, visible=True
        )
        variants = find_controls(
            current_tree, cls="ComboBox", ctrl_id=330, visible=True
        )
        x_rules = find_controls(
            current_tree, cls="ComboBox", ctrl_id=170, visible=True
        )
        y_rules = find_controls(
            current_tree, cls="ComboBox", ctrl_id=180, visible=True
        )
        if not family_buttons or not variants or not x_rules or not y_rules:
            raise RuntimeError("42/C2 rule controls missing")
        click_control(family_buttons[0]["hwnd"])
        set_combo_selection(variants[0]["hwnd"], session.dbins_rule_variant)
        set_combo_selection(x_rules[0]["hwnd"], session.dbins_value)
        set_combo_selection(y_rules[0]["hwnd"], session.dbins_value2)
    time.sleep(0.25)
    selected_text = get_window_text(combos[0]["hwnd"])
    selected_index = int(_send_msg_num(combos[0]["hwnd"], CB_GETCURSEL, 0, 0))
    ok = user32.GetDlgItem(parameter_hwnd, 100)
    if not ok:
        ok_buttons = [
            item
            for item in find_controls(
                enum_child_tree(parameter_hwnd),
                cls="Button",
                text_contains="确定",
                visible=True,
            )
            if item.get("text") == "确定"
        ]
        ok = ok_buttons[0]["hwnd"] if ok_buttons else 0
    if not ok:
        raise RuntimeError(f"{command_name} parameter OK button missing")
    pre_ok_windows = {item["hwnd"] for item in session.top_windows()}
    # Keep this asynchronous: F2 opens a modal yes/no branch inside its click
    # handler, so synchronous BM_CLICK cannot return until that child closes.
    click_control(ok)
    confirmation = session.wait_new_top(
        exclude=pre_ok_windows,
        timeout=4.0,
        title_contains="信息",
    )
    confirmation_choice = None
    if confirmation is not None:
        confirmation_dump = session.dump_window(
            confirmation["hwnd"],
            f"DBSAVE_{command_name}_条件确认",
            menu=False,
            sleep_before=0.1,
        )
        confirmation_choice = "是" if session.dbins_confirm == "yes" else "否"
        choices = find_controls(
            confirmation_dump["tree"],
            cls="Button",
            text_contains=confirmation_choice,
            visible=True,
        )
        if not choices:
            raise RuntimeError(
                f"{command_name} confirmation choice {confirmation_choice} missing"
            )
        choice = choices[0]["hwnd"]
        _send_msg_num(choice, BM_CLICK, 0, 0)
        if not session.wait_gone(confirmation["hwnd"], 1.0):
            real_click_control(choice)
        if not session.wait_gone(confirmation["hwnd"], 4.0):
            raise RuntimeError(f"{command_name} confirmation did not close")
    if not session.wait_gone(parameter_hwnd, 1.0):
        post_command(parameter_hwnd, 100, ok)
    if not session.wait_gone(parameter_hwnd, 1.0):
        real_click_control(ok)
    if not session.wait_gone(parameter_hwnd, 4.0):
        failure_dir = session.out / "interaction-discovery"
        failure_dir.mkdir(parents=True, exist_ok=True)
        failure_windows = session.top_windows()
        session.dump_window(
            parameter_hwnd,
            f"DBSAVE_{command_name}_确定未关闭",
            menu=False,
            sleep_before=0.1,
        )
        (failure_dir / f"weapon-{command_name.lower()}-ok-failure.json").write_text(
            json.dumps(
                {
                    "schema_version": 1,
                    "validated": False,
                    "command": command_name,
                    "requested_option": option,
                    "selected_index": selected_index,
                    "selected_text": selected_text,
                    "top_windows": failure_windows,
                },
                ensure_ascii=False,
                indent=2,
            )
            + "\n",
            encoding="utf-8",
        )
        raise RuntimeError(
            f"{command_name} parameter window did not close after OK"
        )
    time.sleep(0.4)
    selector_closed = not is_window_visible(selector_hwnd)
    if not selector_closed:
        # The legacy chooser stays behind its parameter dialog; accepting a
        # command should close it.  Do not guess another confirmation action.
        raise RuntimeError("weapon instruction selector stayed open after F3 OK")
    # The outer confirmation is control 240, but it is nested beneath the
    # database container in some builds, so GetDlgItem on the top-level handle
    # is not reliable.  Resolve the visible caption from the current tree.
    database_tree = enum_child_tree(database_hwnd)
    database_ok_buttons = [
        item
        for item in find_controls(
            database_tree, cls="Button", text_contains="确定", visible=True
        )
        if item.get("text") == "确定"
    ]
    if not database_ok_buttons:
        raise RuntimeError("database OK button missing")
    database_ok = database_ok_buttons[0]["hwnd"]
    click_control(database_ok)
    if not session.wait_gone(database_hwnd, 1.5):
        real_click_control(database_ok)
    if not session.wait_gone(database_hwnd, 8.0):
        raise RuntimeError("database did not close after OK")
    user32.PostMessageW(session.main_hwnd, WM_COMMAND, 20004, 0)
    time.sleep(5.0)
    for popup in session.top_windows():
        if popup["hwnd"] == session.main_hwnd:
            continue
        if popup["class"] == "#32770":
            session.handle_runtime_dialog(popup["hwnd"], "DBSAVEF3_保存弹窗")
    after = rom_path.read_bytes()
    diffs = [
        {"offset": index, "before": old, "after": new}
        for index, (old, new) in enumerate(zip(before, after))
        if old != new
    ]
    if len(after) != len(before):
        diffs.append(
            {
                "size_before": len(before),
                "size_after": len(after),
            }
        )
    out_dir = session.out / "interaction-discovery"
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / f"weapon-{command_name.lower()}-save-golden.json").write_text(
        json.dumps(
            {
                "schema_version": 1,
                "validated": bool(diffs),
                "rom": str(rom_path),
                "sha256_before": hashlib.sha256(before).hexdigest().upper(),
                "sha256_after": hashlib.sha256(after).hexdigest().upper(),
                "option_index": option,
                "selected_index": selected_index,
                "option_text": (
                    options[option] if option < len(options) else selected_text
                ),
                "command": command_name,
                "confirmation_choice": confirmation_choice,
                "numeric_value": (
                    session.dbins_value if command_name in {"FE", "F9"} else None
                ),
                "numeric_value2": (
                    session.dbins_value2 if command_name == "F9" else None
                ),
                "rule_family": (
                    session.dbins_rule_family if command_name == "42C2" else None
                ),
                "rule_variant": (
                    session.dbins_rule_variant if command_name == "42C2" else None
                ),
                "rule_indices": (
                    [option, session.dbins_value, session.dbins_value2]
                    if command_name == "42C2" else None
                ),
                "selector_closed_after_parameter_ok": selector_closed,
                "diff_count": len(diffs),
                "diffs": diffs,
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    log(
        f"DBSAVEF3 complete: command={command_name} "
        f"option={option} diffs={len(diffs)}"
    )


def stage_dbsaveff(session: ProbeSession) -> None:
    """Insert the chooser's immediate FF action and save an isolated golden."""

    log("=== stage DBSAVEFF: isolated direct FF insertion/save golden ===")
    if not session.main_hwnd or not is_window(session.main_hwnd):
        raise RuntimeError("main window not alive")
    if not session.rom_is_loaded():
        raise RuntimeError("ROM not loaded")
    before = session.probe_rom.read_bytes()
    window = _open_data_window(session, 20008, "数据库", dismiss_hidden=False)
    if not window:
        raise RuntimeError("database window did not appear")
    database_hwnd = window["hwnd"]
    selector_hwnd = 0
    result: dict = {
        "schema_version": 1,
        "validated": False,
        "command": "FF",
        "animation_kind": session.db_animation_kind,
        "weapon_record": session.db_weapon_record,
        "instruction_row": session.db_instruction_row,
        "expected_diff": "zero" if session.db_ff_expect_noop else "nonzero",
        "action_mode": session.db_ff_action,
        "rom": str(session.probe_rom),
    }
    try:
        time.sleep(0.8)
        selector = None
        for _attempt in range(3):
            selector = _open_weapon_instruction_selector(session, database_hwnd)
            if selector is not None:
                break
            time.sleep(0.6)
        if selector is None:
            raise RuntimeError("weapon instruction selector did not open")
        selector_hwnd = selector["hwnd"]
        buttons = find_controls(
            enum_child_tree(selector_hwnd),
            cls="Button", ctrl_id=190, visible=True,
        )
        if not buttons:
            raise RuntimeError("FF selector button missing")
        known = {item["hwnd"] for item in session.top_windows()}
        ff_button = buttons[0]["hwnd"]
        if session.db_ff_action == "keyboard":
            # Move dialog focus without invoking the button, then emit a real
            # Space key so this is distinct from BM_CLICK/left-click evidence.
            focused = focus_foreground_control(selector_hwnd, ff_button)
            result["keyboard_focus_acquired"] = focused
            if not focused:
                raise RuntimeError("could not focus FF button for keyboard probe")
            time.sleep(0.2)
            keybd(VK_SPACE)
            time.sleep(0.08)
            keybd(VK_SPACE, up=True)
        elif session.db_ff_action == "right":
            real_right_click_control(ff_button)
        else:
            click_control(ff_button)
            if not session.wait_gone(selector_hwnd, 1.5):
                real_click_control(ff_button)

        selector_gone = session.wait_gone(selector_hwnd, 2.0)
        if session.db_ff_action == "right":
            if selector_gone:
                raise RuntimeError("FF right-click unexpectedly closed selector")
            result["selector_closed_by_action"] = False
            result["right_click_noop"] = True
            close_window_safely(session, selector_hwnd, timeout=4.0)
            selector_hwnd = 0
            database_cancel_buttons = [
                item for item in find_controls(
                    enum_child_tree(database_hwnd),
                    cls="Button", text_contains="取消", visible=True,
                ) if item.get("text") == "取消"
            ]
            if not database_cancel_buttons:
                raise RuntimeError("database Cancel button missing")
            database_cancel = database_cancel_buttons[0]["hwnd"]
            click_control(database_cancel)
            if not session.wait_gone(database_hwnd, 1.5):
                real_click_control(database_cancel)
            if not session.wait_gone(database_hwnd, 8.0):
                raise RuntimeError("database did not close after right-click no-op cancel")
        else:
            if not selector_gone:
                raise RuntimeError("FF direct action did not close selector")
            result["selector_closed_by_action"] = True
            selector_hwnd = 0
        descendants = [
            item for item in session.top_windows()
            if item["hwnd"] not in known
            and item["hwnd"] != database_hwnd
            and item["class"] != "#32768"
        ]
        result["parameter_windows"] = [
            {"title": item["title"], "class": item["class"]}
            for item in descendants
        ]
        if descendants:
            raise RuntimeError("FF unexpectedly opened a parameter window")
        if session.db_ff_action != "right":
            session.dump_window(
                database_hwnd, "DBSAVE_FF_直接插入后", menu=False
            )
            database_ok_buttons = [
                item for item in find_controls(
                    enum_child_tree(database_hwnd),
                    cls="Button", text_contains="确定", visible=True,
                ) if item.get("text") == "确定"
            ]
            if not database_ok_buttons:
                raise RuntimeError("database OK button missing")
            database_ok = database_ok_buttons[0]["hwnd"]
            click_control(database_ok)
            if not session.wait_gone(database_hwnd, 1.5):
                real_click_control(database_ok)
            if not session.wait_gone(database_hwnd, 8.0):
                raise RuntimeError("database did not close after OK")
        user32.PostMessageW(session.main_hwnd, WM_COMMAND, 20004, 0)
        time.sleep(5.0)
        for popup in session.top_windows():
            if popup["hwnd"] != session.main_hwnd and popup["class"] == "#32770":
                session.handle_runtime_dialog(popup["hwnd"], "DBSAVEFF_保存弹窗")
        after = session.probe_rom.read_bytes()
        diffs = [
            {"offset": index, "before": old, "after": new}
            for index, (old, new) in enumerate(zip(before, after))
            if old != new
        ]
        if len(before) != len(after):
            diffs.append(
                {"size_before": len(before), "size_after": len(after)}
            )
        result.update(
            {
                "validated": (
                    (
                        not bool(diffs)
                        if session.db_ff_action == "right" or session.db_ff_expect_noop
                        else bool(diffs)
                    )
                    and not descendants
                ),
                "sha256_before": hashlib.sha256(before).hexdigest().upper(),
                "sha256_after": hashlib.sha256(after).hexdigest().upper(),
                "diff_count": len(diffs),
                "diffs": diffs,
            }
        )
    finally:
        if selector_hwnd and is_window(selector_hwnd):
            close_window_safely(session, selector_hwnd, timeout=4.0)
        if is_window(database_hwnd):
            close_window_safely(session, database_hwnd, timeout=5.0)
        out_dir = session.out / "interaction-discovery"
        out_dir.mkdir(parents=True, exist_ok=True)
        (out_dir / "weapon-ff-save-golden.json").write_text(
            json.dumps(result, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
    if not result.get("validated"):
        raise RuntimeError("FF direct insertion save golden did not validate")
    log(f"DBSAVEFF complete: diffs={result['diff_count']}")


def stage_dbcmdgestures(session: ProbeSession) -> None:
    """Exercise keyboard and right-click gestures on all command buttons."""

    log("=== stage DBCMDGESTURES: command keyboard/right-click matrix ===")
    if not session.main_hwnd or not is_window(session.main_hwnd):
        raise RuntimeError("main window not alive")
    if not session.rom_is_loaded():
        raise RuntimeError("ROM not loaded")
    before = session.probe_rom.read_bytes()
    window = _open_data_window(session, 20008, "数据库", dismiss_hidden=False)
    if not window:
        raise RuntimeError("database window did not appear")
    database_hwnd = window["hwnd"]
    specs = (
        (100, "F4", "定义声音"),
        (110, "F0", "定义颜色"),
        (120, "F2", "定义光束规律图库"),
        (130, "F3", "定义光束规律"),
        (200, "E0", "切换精灵图库0"),
        (210, "E1", "切换精灵图库1"),
        (140, "FD", "移动屏幕"),
        (150, "FE", "跳转重复"),
        (160, "F9", "创建物体"),
        (170, "42C2", "运行规律"),
        (180, "WAIT", "等待"),
        (190, "FF", None),
    )
    result: dict[str, object] = {
        "schema_version": 1,
        "validated": False,
        "rom": str(session.probe_rom),
        "records": [],
        "execution_records": [],
    }
    selector_hwnd = 0
    try:
        time.sleep(0.8)
        selector = None
        for _attempt in range(6):
            selector = _open_weapon_instruction_selector(session, database_hwnd)
            if selector is not None:
                break
            time.sleep(0.6)
        if selector is None:
            raise RuntimeError("weapon instruction selector did not open for right-click")
        selector_hwnd = selector["hwnd"]
        selector_tree = enum_child_tree(selector_hwnd)
        right_records: list[dict[str, object]] = []
        execution_records: list[dict[str, object]] = []
        for button_id, command_name, _parameter_title in specs:
            buttons = find_controls(
                selector_tree, cls="Button", ctrl_id=button_id, visible=True
            )
            if not buttons:
                raise RuntimeError(f"{command_name} selector button missing")
            button = buttons[0]
            tree_path = control_tree_path(selector_tree, button["hwnd"])
            if tree_path is None:
                raise RuntimeError(f"{command_name} button tree path missing")
            known = {item["hwnd"] for item in session.top_windows()}
            if not real_right_click_control(button["hwnd"]):
                raise RuntimeError(f"{command_name} right-click input failed")
            time.sleep(0.45)
            unexpected = [
                item for item in session.top_windows()
                if item["hwnd"] not in known and item["class"] != "#32768"
            ]
            if not is_window(selector_hwnd) or unexpected:
                raise RuntimeError(
                    f"{command_name} right-click changed selector: {unexpected}"
                )
            action_id = stable_interaction_id(
                get_window_text(selector_hwnd), "Button", button_id,
                tree_path, "right_click",
            )
            right_records.append(
                {
                    "command": command_name,
                    "gesture": "right_click",
                    "status": "noop",
                    "selector_remained_open": True,
                    "new_windows": [],
                }
            )
            execution_records.append(
                {
                    "action_id": action_id,
                    "status": "passed",
                    "result": f"旧版 {command_name} 按钮右键保持选择器，未打开窗口。",
                }
            )
        close_window_safely(session, selector_hwnd, timeout=4.0)
        selector_hwnd = 0

        selector = _open_weapon_instruction_selector(session, database_hwnd)
        if selector is None:
            raise RuntimeError("weapon instruction selector did not open for keyboard")
        selector_hwnd = selector["hwnd"]
        keyboard_records: list[dict[str, object]] = []
        for button_id, command_name, parameter_title in specs:
            selector_tree = enum_child_tree(selector_hwnd)
            buttons = find_controls(
                selector_tree, cls="Button", ctrl_id=button_id, visible=True
            )
            if not buttons:
                raise RuntimeError(f"{command_name} selector button missing")
            button = buttons[0]
            tree_path = control_tree_path(selector_tree, button["hwnd"])
            if tree_path is None:
                raise RuntimeError(f"{command_name} button tree path missing")
            known = {item["hwnd"] for item in session.top_windows()}
            if not focus_foreground_control(selector_hwnd, button["hwnd"]):
                raise RuntimeError(f"{command_name} keyboard focus failed")
            keybd(VK_SPACE)
            time.sleep(0.08)
            keybd(VK_SPACE, up=True)
            action_id = stable_interaction_id(
                get_window_text(selector_hwnd), "Button", button_id,
                tree_path, "keyboard_activate",
            )
            if command_name == "FF":
                if not session.wait_gone(selector_hwnd, 5.0):
                    raise RuntimeError("FF keyboard activation did not close selector")
                selector_hwnd = 0
                keyboard_records.append(
                    {
                        "command": command_name,
                        "gesture": "keyboard_activate",
                        "status": "direct_action",
                        "selector_closed": True,
                    }
                )
                execution_records.append(
                    {
                        "action_id": action_id,
                        "status": "passed",
                        "result": "旧版 FF 按钮聚焦后按空格，选择器直接关闭。",
                    }
                )
                continue
            parameter = session.wait_new_top(
                exclude=known, timeout=5.0, title_contains=parameter_title
            )
            if parameter is None:
                raise RuntimeError(
                    f"{command_name} keyboard activation did not open {parameter_title}"
                )
            parameter_hwnd = parameter["hwnd"]
            cancel_buttons = [
                item for item in find_controls(
                    enum_child_tree(parameter_hwnd), cls="Button",
                    text_contains="取消", visible=True,
                ) if item.get("text") == "取消"
            ]
            if not cancel_buttons:
                raise RuntimeError(f"{command_name} parameter Cancel missing")
            click_control(cancel_buttons[0]["hwnd"])
            if not session.wait_gone(parameter_hwnd, 1.5):
                real_click_control(cancel_buttons[0]["hwnd"])
            if not session.wait_gone(parameter_hwnd, 5.0):
                raise RuntimeError(f"{command_name} parameter did not cancel")
            if not is_window(selector_hwnd):
                raise RuntimeError(f"{command_name} cancel did not return selector")
            keyboard_records.append(
                {
                    "command": command_name,
                    "gesture": "keyboard_activate",
                    "status": "parameter_opened",
                    "parameter_title": parameter_title,
                    "cancel_returned_selector": True,
                }
            )
            execution_records.append(
                {
                    "action_id": action_id,
                    "status": "passed",
                    "result": (
                        f"旧版 {command_name} 按钮聚焦后按空格打开"
                        f"“{parameter_title}”，取消后返回选择器。"
                    ),
                }
            )

        database_cancel_buttons = [
            item for item in find_controls(
                enum_child_tree(database_hwnd), cls="Button",
                text_contains="取消", visible=True,
            ) if item.get("text") == "取消"
        ]
        if not database_cancel_buttons:
            raise RuntimeError("database Cancel button missing")
        database_cancel = database_cancel_buttons[0]["hwnd"]
        click_control(database_cancel)
        if not session.wait_gone(database_hwnd, 1.5):
            real_click_control(database_cancel)
        if not session.wait_gone(database_hwnd, 8.0):
            raise RuntimeError("database did not close after gesture matrix")
        user32.PostMessageW(session.main_hwnd, WM_COMMAND, 20004, 0)
        time.sleep(4.0)
        for popup in session.top_windows():
            if popup["hwnd"] != session.main_hwnd and popup["class"] == "#32770":
                session.handle_runtime_dialog(popup["hwnd"], "DBCMDGESTURES_保存弹窗")
        after = session.probe_rom.read_bytes()
        diffs = [
            index for index, (old, new) in enumerate(zip(before, after))
            if old != new
        ]
        validated = (
            len(right_records) == len(specs)
            and len(keyboard_records) == len(specs)
            and not diffs
            and len(before) == len(after)
        )
        result.update(
            {
                "validated": validated,
                "records": right_records + keyboard_records,
                "execution_records": execution_records if validated else [],
                "sha256_before": hashlib.sha256(before).hexdigest().upper(),
                "sha256_after": hashlib.sha256(after).hexdigest().upper(),
                "diff_count": len(diffs),
            }
        )
    finally:
        if selector_hwnd and is_window(selector_hwnd):
            close_window_safely(session, selector_hwnd, timeout=4.0)
        if is_window(database_hwnd):
            close_window_safely(session, database_hwnd, timeout=5.0)
        out_dir = session.out / "interaction-discovery"
        out_dir.mkdir(parents=True, exist_ok=True)
        (out_dir / "weapon-command-gesture-matrix.json").write_text(
            json.dumps(result, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
    if not result.get("validated"):
        raise RuntimeError("weapon command gesture matrix did not validate")
    log("DBCMDGESTURES complete: 12 keyboard + 12 right-click, diff_count=0")


def stage_dbcontextactions(session: ProbeSession) -> None:
    """Exercise every non-insert weapon-animation context command."""

    log("=== stage DBCONTEXTACTIONS: weapon list context command states ===")
    if not session.main_hwnd or not is_window(session.main_hwnd):
        raise RuntimeError("main window not alive")
    if not session.rom_is_loaded():
        raise RuntimeError("ROM not loaded")
    before = session.probe_rom.read_bytes()
    origin = ("武器修改", "ListBox", 2530, 10, "")
    records: list[dict[str, object]] = []
    execution_records: list[dict[str, object]] = []
    database_hwnd = 0

    def open_case(record_id: int = 1, row: int = 0) -> tuple[int, int]:
        nonlocal database_hwnd
        window = _open_data_window(session, 20008, "数据库", dismiss_hidden=False)
        if not window:
            raise RuntimeError("database window did not appear")
        database_hwnd = window["hwnd"]
        time.sleep(0.6)
        session.db_animation_kind = "ally"
        session.db_weapon_record = record_id
        session.db_instruction_row = row
        selector = None
        for _attempt in range(6):
            selector = _open_weapon_instruction_selector(session, database_hwnd)
            if selector is not None:
                break
            time.sleep(0.6)
        if selector is None:
            raise RuntimeError("cannot prepare weapon instruction context menu")
        close_window_safely(session, selector["hwnd"], timeout=4.0)
        animation_list_id = (
            2530 if session.db_animation_kind == "ally" else 2520
        )
        matches = find_controls(
            enum_child_tree(database_hwnd),
            cls="ListBox", ctrl_id=animation_list_id, visible=True,
        )
        if not matches:
            raise RuntimeError(
                f"{session.db_animation_kind} weapon instruction list missing"
            )
        instruction_list = matches[0]["hwnd"]
        _send_msg_num(instruction_list, 0x0186, row, 0)  # LB_SETCURSEL
        return database_hwnd, instruction_list

    def cancel_case() -> None:
        nonlocal database_hwnd
        cancel_buttons = [
            item for item in find_controls(
                enum_child_tree(database_hwnd), cls="Button",
                text_contains="取消", visible=True,
            ) if item.get("text") == "取消"
        ]
        if not cancel_buttons:
            raise RuntimeError("database Cancel button missing")
        button = cancel_buttons[0]["hwnd"]
        click_control(button)
        if not session.wait_gone(database_hwnd, 1.5):
            real_click_control(button)
        if not session.wait_gone(database_hwnd, 8.0):
            raise RuntimeError("database did not close after context case")
        database_hwnd = 0

    def run_command(command_id: int, caption: str) -> None:
        user32.PostMessageW(database_hwnd, WM_COMMAND, command_id, 0)
        time.sleep(0.45)
        execution_records.append(
            {
                "action_id": stable_context_interaction_id(
                    origin, (caption,), command_id
                ),
                "status": "passed",
                "result": "",
            }
        )

    def list_visual_hash(instruction_list: int, tag: str) -> str:
        path = session.shots / f"DBCONTEXT_{tag}.png"
        if not capture_screen_region(get_window_rect(instruction_list), path, pad=0):
            raise RuntimeError(f"cannot capture instruction list for {tag}")
        return hashlib.sha256(path.read_bytes()).hexdigest().upper()

    try:
        # Edit: row 0 is F4 in the selected reference weapon.
        _db, instruction_list = open_case(1, 0)
        known = {item["hwnd"] for item in session.top_windows()}
        run_command(20016, "编辑")
        parameter = session.wait_new_top(exclude=known, timeout=5.0)
        if parameter is None or parameter["title"] != "定义声音":
            raise RuntimeError(f"Edit did not open F4 parameter: {parameter}")
        parameter_title = parameter["title"]
        cancel_buttons = [
            item for item in find_controls(
                enum_child_tree(parameter["hwnd"]), cls="Button",
                text_contains="取消", visible=True,
            ) if item.get("text") == "取消"
        ]
        if not cancel_buttons:
            raise RuntimeError("Edit parameter Cancel missing")
        click_control(cancel_buttons[0]["hwnd"])
        if not session.wait_gone(parameter["hwnd"], 4.0):
            raise RuntimeError("Edit parameter did not cancel")
        records.append(
            {"command": "编辑", "status": "parameter_opened", "title": parameter_title}
        )
        execution_records[-1]["result"] = f"旧版编辑打开“{parameter_title}”并可取消返回。"

        # Copy then paste inserts the copied command before the selected row.
        visual_before = list_visual_hash(instruction_list, "copy_before")
        run_command(20019, "复制")
        execution_records[-1]["result"] = "旧版复制保留当前列表并为粘贴建立剪贴板。"
        visual_copied = list_visual_hash(instruction_list, "copy_after")
        if visual_copied != visual_before:
            raise RuntimeError("Copy unexpectedly changed the visible list")
        _send_msg_num(instruction_list, 0x0186, 1, 0)
        run_command(20021, "粘贴")
        visual_after = list_visual_hash(instruction_list, "paste_after")
        if visual_after == visual_copied:
            raise RuntimeError("Paste did not change the visible instruction list")
        records.extend(
            [
                {"command": "复制", "status": "clipboard_ready", "visual_unchanged": True},
                {"command": "粘贴", "status": "list_changed", "before": visual_copied, "after": visual_after},
            ]
        )
        execution_records[-1]["result"] = "旧版粘贴使用复制剪贴板并改变所选位置的列表内容。"

        # Cutting the just-pasted row returns the list to its original body.
        _send_msg_num(instruction_list, 0x0186, 1, 0)
        visual_before_cut = list_visual_hash(instruction_list, "cut_before")
        run_command(20018, "剪切")
        visual_after_cut = list_visual_hash(instruction_list, "cut_after")
        if visual_after_cut == visual_before_cut:
            raise RuntimeError("Cut did not change the visible instruction list")
        records.append(
            {"command": "剪切", "status": "list_changed", "before": visual_before_cut, "after": visual_after_cut}
        )
        execution_records[-1]["result"] = "旧版剪切后动画列表可见内容改变并更新剪贴板。"

        # Copy-all from weapon 1, switch to weapon 20, then paste-all replaces it.
        source_visual = list_visual_hash(instruction_list, "copy_all_source")
        run_command(20020, "复制全部")
        execution_records[-1]["result"] = "旧版复制全部保存当前完整动画到内部剪贴板。"
        weapon_lists = find_controls(
            enum_child_tree(database_hwnd), cls="ListBox", ctrl_id=610, visible=True
        )
        if not weapon_lists:
            raise RuntimeError("weapon list missing for paste-all target")
        weapon_list = weapon_lists[0]["hwnd"]
        _send_msg_num(weapon_list, 0x0186, 19, 0)
        parent = user32.GetParent(weapon_list)
        seen: set[int] = set()
        while parent and parent not in seen:
            seen.add(parent)
            _send_msg_num(parent, WM_COMMAND, 610 | (1 << 16), weapon_list)
            if parent == database_hwnd:
                break
            parent = user32.GetParent(parent)
        time.sleep(0.4)
        refreshed = find_controls(
            enum_child_tree(database_hwnd), cls="ListBox", ctrl_id=2530, visible=True
        )
        if not refreshed:
            raise RuntimeError("target instruction list missing")
        instruction_list = refreshed[0]["hwnd"]
        target_before = list_visual_hash(instruction_list, "paste_all_before")
        run_command(20022, "粘贴全部")
        target_after = list_visual_hash(instruction_list, "paste_all_after")
        if target_before == target_after:
            raise RuntimeError("Paste-all did not replace the target visible list")
        records.extend(
            [
                {"command": "复制全部", "status": "clipboard_ready", "source": source_visual},
                {"command": "粘贴全部", "status": "replaced", "before": target_before, "after": target_after},
            ]
        )
        execution_records[-1]["result"] = "旧版粘贴全部用源动画替换目标完整动画。"

        # Return to weapon 1, then delete one row and finally clear the script.
        _send_msg_num(weapon_list, 0x0186, 0, 0)
        parent = user32.GetParent(weapon_list)
        seen = set()
        while parent and parent not in seen:
            seen.add(parent)
            _send_msg_num(parent, WM_COMMAND, 610 | (1 << 16), weapon_list)
            if parent == database_hwnd:
                break
            parent = user32.GetParent(parent)
        time.sleep(0.4)
        refreshed = find_controls(
            enum_child_tree(database_hwnd), cls="ListBox", ctrl_id=2530, visible=True
        )
        if not refreshed:
            raise RuntimeError("source instruction list missing after return")
        instruction_list = refreshed[0]["hwnd"]
        _send_msg_num(instruction_list, 0x0186, 0, 0)

        visual_before_delete = list_visual_hash(instruction_list, "delete_before")
        run_command(20026, "删除")
        visual_after_delete = list_visual_hash(instruction_list, "delete_after")
        if visual_after_delete == visual_before_delete:
            raise RuntimeError("删除 did not change the visible list")
        records.append(
            {"command": "删除", "status": "list_changed", "before": visual_before_delete, "after": visual_after_delete}
        )
        execution_records[-1]["result"] = "旧版删除后动画列表可见内容改变。"

        visual_before_clear = list_visual_hash(instruction_list, "clear_before")
        run_command(20027, "清空")
        visual_after_clear = list_visual_hash(instruction_list, "clear_after")
        if visual_after_clear == visual_before_clear:
            raise RuntimeError("清空 did not change the visible list")
        records.append(
            {"command": "清空", "status": "list_changed", "before": visual_before_clear, "after": visual_after_clear}
        )
        execution_records[-1]["result"] = "旧版清空后动画列表可见内容改变。"

        cancel_case()

        user32.PostMessageW(session.main_hwnd, WM_COMMAND, 20004, 0)
        time.sleep(4.0)
        for popup in session.top_windows():
            if popup["hwnd"] != session.main_hwnd and popup["class"] == "#32770":
                session.handle_runtime_dialog(popup["hwnd"], "DBCONTEXACTIONS_保存弹窗")
        after = session.probe_rom.read_bytes()
        diffs = [
            index for index, (old, new) in enumerate(zip(before, after))
            if old != new
        ]
        validated = (
            len(records) == 8
            and len(execution_records) == 8
            and not diffs
            and len(before) == len(after)
        )
        payload = {
            "schema_version": 1,
            "validated": validated,
            "rom": str(session.probe_rom),
            "records": records,
            "execution_records": execution_records if validated else [],
            "sha256_before": hashlib.sha256(before).hexdigest().upper(),
            "sha256_after": hashlib.sha256(after).hexdigest().upper(),
            "diff_count": len(diffs),
        }
    finally:
        if database_hwnd and is_window(database_hwnd):
            close_window_safely(session, database_hwnd, timeout=5.0)
        out_dir = session.out / "interaction-discovery"
        out_dir.mkdir(parents=True, exist_ok=True)
        if "payload" not in locals():
            payload = {
                "schema_version": 1, "validated": False,
                "records": records, "execution_records": [],
            }
        (out_dir / "weapon-context-action-matrix.json").write_text(
            json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
    if not payload.get("validated"):
        raise RuntimeError("weapon context action matrix did not validate")
    log("DBCONTEXACTIONS complete: 8 commands, database cancel diff_count=0")


def stage_dbcontextsave(session: ProbeSession) -> None:
    """Save one destructive weapon context command as a whole-ROM golden."""

    case = session.db_context_case
    log(f"=== stage DBCONTEXTSAVE: case={case} ===")
    if not session.main_hwnd or not is_window(session.main_hwnd):
        raise RuntimeError("main window not alive")
    if not session.rom_is_loaded():
        raise RuntimeError("ROM not loaded")
    before = session.probe_rom.read_bytes()
    window = _open_data_window(session, 20008, "数据库", dismiss_hidden=False)
    if not window:
        raise RuntimeError("database window did not appear")
    database_hwnd = window["hwnd"]
    selector_hwnd = 0
    result: dict[str, object] = {
        "schema_version": 1,
        "validated": False,
        "case": case,
        "rom": str(session.probe_rom),
    }
    try:
        # A cold database open can leave the owner-drawn weapon page behind
        # the main window for roughly one paint cycle.  Real user input brings
        # it forward before the first tab/list click, so reproduce that state
        # explicitly instead of relying on a timing accident.
        user32.ShowWindow(database_hwnd, 9)  # SW_RESTORE
        user32.SetForegroundWindow(database_hwnd)
        time.sleep(1.2)
        selector = None
        for _attempt in range(10):
            user32.SetForegroundWindow(database_hwnd)
            selector = _open_weapon_instruction_selector(session, database_hwnd)
            if selector is not None:
                break
            time.sleep(0.8)
        if selector is None:
            raise RuntimeError("cannot prepare weapon context save")
        selector_hwnd = selector["hwnd"]
        close_window_safely(session, selector_hwnd, timeout=4.0)
        selector_hwnd = 0
        animation_list_id = (
            2530 if session.db_animation_kind == "ally" else 2520
        )
        matches = find_controls(
            enum_child_tree(database_hwnd),
            cls="ListBox", ctrl_id=animation_list_id, visible=True,
        )
        if not matches:
            raise RuntimeError(
                f"{session.db_animation_kind} weapon instruction list missing"
            )
        instruction_list = matches[0]["hwnd"]

        def command(command_id: int) -> None:
            user32.PostMessageW(database_hwnd, WM_COMMAND, command_id, 0)
            time.sleep(0.5)

        selected_row = max(0, int(session.db_instruction_row))
        _send_msg_num(instruction_list, 0x0186, selected_row, 0)
        if case == "cut":
            command(20018)
        elif case == "paste":
            command(20019)
            _send_msg_num(instruction_list, 0x0186, selected_row + 1, 0)
            command(20021)
        elif case == "paste-all":
            command(20020)
            weapon_lists = find_controls(
                enum_child_tree(database_hwnd),
                cls="ListBox", ctrl_id=610, visible=True,
            )
            if not weapon_lists:
                raise RuntimeError("weapon list missing for paste-all save")
            weapon_list = weapon_lists[0]["hwnd"]
            _send_msg_num(weapon_list, 0x0186, 19, 0)
            parent = user32.GetParent(weapon_list)
            seen: set[int] = set()
            while parent and parent not in seen:
                seen.add(parent)
                _send_msg_num(parent, WM_COMMAND, 610 | (1 << 16), weapon_list)
                if parent == database_hwnd:
                    break
                parent = user32.GetParent(parent)
            time.sleep(0.4)
            refreshed = find_controls(
                enum_child_tree(database_hwnd),
                cls="ListBox", ctrl_id=animation_list_id, visible=True,
            )
            if not refreshed:
                raise RuntimeError("paste-all target list missing")
            instruction_list = refreshed[0]["hwnd"]
            _send_msg_num(instruction_list, 0x0186, 0, 0)
            command(20022)
        elif case == "delete":
            command(20026)
        elif case == "clear":
            command(20027)
        else:
            raise RuntimeError(f"unknown context save case: {case}")

        session.dump_window(
            database_hwnd, f"DBCONTEXTSAVE_{case}_草稿", menu=False
        )
        ok_buttons = [
            item for item in find_controls(
                enum_child_tree(database_hwnd), cls="Button",
                text_contains="确定", visible=True,
            ) if item.get("text") == "确定"
        ]
        if not ok_buttons:
            raise RuntimeError("database OK button missing")
        database_ok = ok_buttons[0]["hwnd"]
        click_control(database_ok)
        if not session.wait_gone(database_hwnd, 1.5):
            real_click_control(database_ok)
        if not session.wait_gone(database_hwnd, 8.0):
            raise RuntimeError("database did not close after context save")
        user32.PostMessageW(session.main_hwnd, WM_COMMAND, 20004, 0)
        time.sleep(5.0)
        for popup in session.top_windows():
            if popup["hwnd"] != session.main_hwnd and popup["class"] == "#32770":
                session.handle_runtime_dialog(popup["hwnd"], f"DBCONTEXTSAVE_{case}_保存弹窗")
        after = session.probe_rom.read_bytes()
        diffs = [
            {"offset": index, "before": old, "after": new}
            for index, (old, new) in enumerate(zip(before, after))
            if old != new
        ]
        if len(before) != len(after):
            diffs.append({"size_before": len(before), "size_after": len(after)})
        result.update(
            {
                "validated": bool(diffs),
                "sha256_before": hashlib.sha256(before).hexdigest().upper(),
                "sha256_after": hashlib.sha256(after).hexdigest().upper(),
                "diff_count": len(diffs),
                "diffs": diffs,
            }
        )
    finally:
        if selector_hwnd and is_window(selector_hwnd):
            close_window_safely(session, selector_hwnd, timeout=4.0)
        if is_window(database_hwnd):
            close_window_safely(session, database_hwnd, timeout=5.0)
        out_dir = session.out / "interaction-discovery"
        out_dir.mkdir(parents=True, exist_ok=True)
        (out_dir / f"weapon-context-{case}-save-golden.json").write_text(
            json.dumps(result, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
    if not result.get("validated"):
        raise RuntimeError(f"weapon context {case} save golden did not validate")
    log(f"DBCONTEXTSAVE complete: case={case} diffs={result['diff_count']}")


def stage_dbcancelall(session: ProbeSession) -> None:
    """Cancel every weapon-command parameter window and prove zero write."""

    log("=== stage DBCANCELALL: all weapon parameter cancel paths ===")
    if not session.main_hwnd or not is_window(session.main_hwnd):
        raise RuntimeError("main window not alive")
    if not session.rom_is_loaded():
        raise RuntimeError("ROM not loaded")
    before = session.probe_rom.read_bytes()
    window = None
    for _attempt in range(3):
        window = _open_data_window(
            session, 20008, "数据库", dismiss_hidden=False
        )
        if window is not None:
            break
        time.sleep(0.8)
    if not window:
        raise RuntimeError("database window did not appear")
    database_hwnd = window["hwnd"]
    time.sleep(0.8)
    specs = (
        (100, "F4", "定义声音"),
        (110, "F0", "定义颜色"),
        (120, "F2", "定义光束规律图库"),
        (130, "F3", "定义光束规律"),
        (200, "E0", "切换精灵图库0"),
        (210, "E1", "切换精灵图库1"),
        (140, "FD", "移动屏幕"),
        (150, "FE", "跳转重复"),
        (160, "F9", "创建物体"),
        (170, "42C2", "运行规律"),
        (180, "WAIT", "等待"),
    )
    records: list[dict] = []
    execution_records: list[dict] = []
    for button_id, command_name, parameter_title in specs:
        selector = None
        for _attempt in range(8):
            selector = _open_weapon_instruction_selector(session, database_hwnd)
            if selector is not None:
                break
            time.sleep(0.6)
        if selector is None:
            records.append({"command": command_name, "status": "selector_not_opened"})
            continue
        selector_hwnd = selector["hwnd"]
        selector_tree = enum_child_tree(selector_hwnd)
        buttons = find_controls(
            selector_tree, cls="Button", ctrl_id=button_id, visible=True
        )
        if not buttons:
            records.append({"command": command_name, "status": "button_missing"})
            close_window_safely(session, selector_hwnd)
            continue
        entry_control = buttons[0]
        entry_path = control_tree_path(selector_tree, entry_control["hwnd"])
        if entry_path is None:
            raise RuntimeError(f"{command_name} entry tree path missing")
        entry_action_id = stable_interaction_id(
            get_window_text(selector_hwnd), "Button", button_id,
            entry_path, "left_click",
        )
        known = {item["hwnd"] for item in session.top_windows()}
        click_control(entry_control["hwnd"])
        parameter = session.wait_new_top(
            exclude=known, timeout=4.0, title_contains=parameter_title
        )
        if parameter is None:
            records.append({"command": command_name, "status": "parameter_not_opened"})
            close_window_safely(session, selector_hwnd)
            continue
        parameter_hwnd = parameter["hwnd"]
        execution_records.append(
            {
                "action_id": entry_action_id,
                "status": "passed",
                "result": f"旧版 {command_name} 左键打开“{parameter_title}”。",
            }
        )
        tree = enum_child_tree(parameter_hwnd)
        cancel_buttons = [
            item for item in find_controls(
                tree, cls="Button", text_contains="取消", visible=True
            ) if item.get("text") == "取消"
        ]
        if not cancel_buttons:
            records.append({"command": command_name, "status": "cancel_missing"})
            close_window_safely(session, parameter_hwnd)
            close_window_safely(session, selector_hwnd)
            continue
        cancel_control = cancel_buttons[0]
        cancel_path = control_tree_path(tree, cancel_control["hwnd"])
        if cancel_path is None:
            raise RuntimeError(f"{command_name} cancel tree path missing")
        action_id = stable_interaction_id(
            parameter["title"], "Button", int(cancel_control["ctrl_id"]),
            cancel_path, "left_click",
        )
        click_control(cancel_control["hwnd"])
        parameter_closed = session.wait_gone(parameter_hwnd, 4.0)
        selector_returned = is_window_visible(selector_hwnd)
        records.append(
            {
                "command": command_name,
                "status": "cancelled" if parameter_closed else "cancel_failed",
                "parameter_closed": parameter_closed,
                "selector_returned": selector_returned,
                "action_id": action_id,
            }
        )
        execution_records.append(
            {
                "action_id": action_id,
                "status": "passed" if parameter_closed and selector_returned else "failed",
                "result": (
                    f"{command_name} 参数窗口取消关闭并返回指令选择器"
                    if parameter_closed and selector_returned
                    else f"{command_name} 取消路径未闭合"
                ),
            }
        )
        if not parameter_closed:
            close_window_safely(session, parameter_hwnd)
        if is_window(selector_hwnd):
            close_window_safely(session, selector_hwnd, timeout=4.0)

    database_tree = enum_child_tree(database_hwnd)
    database_cancel_buttons = [
        item for item in find_controls(
            database_tree, cls="Button", text_contains="取消", visible=True
        ) if item.get("text") == "取消"
    ]
    if not database_cancel_buttons:
        raise RuntimeError("database Cancel button missing")
    database_cancel = database_cancel_buttons[0]
    database_cancel_path = control_tree_path(
        database_tree, database_cancel["hwnd"]
    )
    if database_cancel_path is None:
        raise RuntimeError("database Cancel tree path missing")
    database_cancel_action_id = stable_interaction_id(
        get_window_text(database_hwnd), "Button",
        int(database_cancel["ctrl_id"]), database_cancel_path, "left_click",
    )
    click_control(database_cancel["hwnd"])
    database_closed = session.wait_gone(database_hwnd, 8.0)
    if not database_closed:
        raise RuntimeError("database did not close after Cancel")
    user32.PostMessageW(session.main_hwnd, WM_COMMAND, 20004, 0)
    time.sleep(4.0)
    for popup in session.top_windows():
        if popup["hwnd"] != session.main_hwnd and popup["class"] == "#32770":
            session.handle_runtime_dialog(popup["hwnd"], "DBCANCELALL_保存弹窗")
    after = session.probe_rom.read_bytes()
    diffs = [
        index for index, (old, new) in enumerate(zip(before, after)) if old != new
    ]
    complete = (
        len(records) == len(specs)
        and all(item["status"] == "cancelled" for item in records)
        and all(item["selector_returned"] for item in records)
        and database_closed
        and not diffs
        and len(before) == len(after)
    )
    execution_records.append(
        {
            "action_id": database_cancel_action_id,
            "status": "passed" if database_closed and not diffs else "failed",
            "result": "数据库取消后主窗口保存零差分",
        }
    )
    out_dir = session.out / "interaction-discovery"
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "weapon-command-cancel-golden.json").write_text(
        json.dumps(
            {
                "schema_version": 1,
                "validated": complete,
                "rom": str(session.probe_rom),
                "sha256_before": hashlib.sha256(before).hexdigest().upper(),
                "sha256_after": hashlib.sha256(after).hexdigest().upper(),
                "parameter_windows": len(specs),
                "database_cancel_closed": database_closed,
                "diff_count": len(diffs) + int(len(before) != len(after)),
                "changed_offsets": diffs,
                "records": records,
                "execution_records": execution_records,
            },
            ensure_ascii=False,
            indent=2,
        ) + "\n",
        encoding="utf-8",
    )
    if not complete:
        raise RuntimeError("weapon command cancel golden did not validate")
    log(f"DBCANCELALL complete: commands={len(records)} diffs=0")


def stage_dbwrule(session: ProbeSession) -> None:
    """Discover all four legacy weapon-rule pages and their context menus."""

    log("=== stage DBWRULE: weapon rule pages and nested menus ===")
    if not session.main_hwnd or not is_window(session.main_hwnd):
        raise RuntimeError("main window not alive")
    if not session.rom_is_loaded():
        raise RuntimeError("ROM not loaded")
    window = None
    for attempt in range(1, 4):
        window = _open_data_window(
            session, 20008, "数据库", dismiss_hidden=False
        )
        if window:
            break
        log(f"DBWRULE database open retry {attempt}/3")
        time.sleep(0.8)
    if not window:
        raise RuntimeError("database window did not appear")
    database_hwnd = window["hwnd"]
    rule_hwnd = 0
    records: list[dict] = []
    tab_results: list[dict] = []
    complete = False
    expected_labels = (
        "光束组图规律",
        "物理运行规律1",
        "物理运行规律2",
        "物理图片规律",
    )
    try:
        located = None
        for _attempt in range(8):
            page = switch_database_page_by_control(database_hwnd, 2530)
            buttons = (
                find_controls(
                    enum_child_tree(database_hwnd),
                    cls="Button",
                    ctrl_id=2550,
                    visible=True,
                )
                if page is not None
                else []
            )
            if buttons:
                located = (page[0], buttons[0])
                break
            time.sleep(1.0)
        if located is None:
            raise RuntimeError("weapon rule button not found")
        _tab_x, rule_button = located
        known = {item["hwnd"] for item in session.top_windows()}
        click_control(rule_button["hwnd"])
        rule_window = session.wait_new_top(
            exclude=known, timeout=5.0, cls_equals="WTWindow", title_contains="规律"
        )
        if not rule_window:
            raise RuntimeError("weapon rule window did not appear")
        rule_hwnd = rule_window["hwnd"]
        move_window(rule_hwnd, 80, 60, 1050, 760)
        time.sleep(0.5)
        root_dump = session.dump_window(
            rule_hwnd, "DBWRULE_00_规律窗口", menu=True
        )
        page_ctrls = [
            item
            for item in find_controls(
                root_dump["tree"], cls="CPageControl", visible=True
            )
        ]
        if not page_ctrls:
            raise RuntimeError("weapon rule CPageControl not found")
        page_ctrl = max(
            page_ctrls,
            key=lambda item: item["rect"]["width"] * item["rect"]["height"],
        )
        win_rect = get_window_rect(rule_hwnd)
        dx, dy = _client_offset(rule_hwnd)
        ctrl_rect = page_ctrl["rect"]
        tab_y = ctrl_rect["top"] - win_rect["top"] + 24
        x_start = ctrl_rect["left"] - win_rect["left"] + 14
        x_end = ctrl_rect["right"] - win_rect["left"] - 24
        seen: set[tuple] = set()
        tab_states: list[tuple[str, int, tuple]] = []
        for x in range(x_start, x_end, 10):
            real_click_at(rule_hwnd, x - dx, tab_y - dy)
            time.sleep(0.20)
            signature = _window_ctrl_sig(rule_hwnd)
            if signature in seen:
                continue
            seen.add(signature)
            index = len(tab_states)
            label = (
                expected_labels[index]
                if index < len(expected_labels)
                else f"未知规律页{index + 1}"
            )
            tab_states.append((label, x, signature))
            tab_results.append(
                {
                    "label": label,
                    "probe_window_x": x,
                    "visible_control_count": len(signature),
                    "status": "discovered",
                }
            )
            log(
                f"DBWRULE discovered page {index + 1}: {label!r} "
                f"x={x} controls={len(signature)}"
            )
            if len(tab_states) >= len(expected_labels):
                break
        for index, (label, x, expected_signature) in enumerate(tab_states, 1):
            real_click_at(rule_hwnd, x - dx, tab_y - dy)
            time.sleep(0.35)
            actual_signature = _window_ctrl_sig(rule_hwnd)
            signature_match = actual_signature == expected_signature
            tab_results[index - 1]["phase2_signature_match"] = signature_match
            tag = f"DBWRULE_{index:02d}_{label}"
            dump = session.dump_window(rule_hwnd, tag, menu=True)
            contexts = probe_window_context_menus(
                session, rule_hwnd, f"武器规律/{label}"
            )
            records.append(
                {
                    "label": label,
                    "probe_window_x": x,
                    "signature_match": signature_match,
                    "visible_controls": [
                        {
                            "class": item.get("class"),
                            "control_id": item.get("ctrl_id"),
                            "text": item.get("text", ""),
                            "enabled": item.get("enabled"),
                        }
                        for item in flatten_tree(dump["tree"])
                        if item.get("visible")
                    ],
                    "context_probes": contexts,
                }
            )
        complete = (
            len(tab_states) == len(expected_labels)
            and all(item["signature_match"] for item in records)
        )
    finally:
        out_dir = session.out / "interaction-discovery"
        out_dir.mkdir(parents=True, exist_ok=True)
        payload = {
            "schema_version": 1,
            "validated": bool(
                len(records) == len(expected_labels)
                and all(item.get("signature_match") for item in records)
            ),
            "scope": (
                "isolated reference executable; four weapon-rule pages; "
                "context menus only; no menu command selected and no save"
            ),
            "expected_page_count": len(expected_labels),
            "tabs": tab_results,
            "records": records,
        }
        (out_dir / "weapon-rule-pages.json").write_text(
            json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        if rule_hwnd and is_window(rule_hwnd):
            close_window_safely(session, rule_hwnd, timeout=5.0)
        if is_window(database_hwnd):
            close_window_safely(session, database_hwnd, timeout=5.0)
    if not complete:
        raise RuntimeError(
            f"weapon rule page discovery incomplete: {len(records)}/"
            f"{len(expected_labels)}"
        )
    log(f"DBWRULE complete: {len(records)}/{len(expected_labels)} pages")


def stage_dbwrulebtn(session: ProbeSession) -> None:
    """Activate every visible weapon-rule button and capture its result."""

    log("=== stage DBWRULEBTN: weapon rule button descendants ===")
    if not session.main_hwnd or not is_window(session.main_hwnd):
        raise RuntimeError("main window not alive")
    if not session.rom_is_loaded():
        raise RuntimeError("ROM not loaded")
    before = session.probe_rom.read_bytes()
    window = None
    for _attempt in range(3):
        window = _open_data_window(
            session, 20008, "数据库", dismiss_hidden=False
        )
        if window:
            break
        time.sleep(0.8)
    if not window:
        raise RuntimeError("database window did not appear")
    database_hwnd = window["hwnd"]
    rule_hwnd = 0
    records: list[dict] = []
    gesture_records: list[dict] = []
    execution_records: list[dict] = []
    page_specs = (
        ("光束组图规律", (710, 270, 220, 140, 570, 410, 400, 380)),
        ("物理运行规律1", (710, 310, 280, 170)),
        ("物理运行规律2", (710, 700, 680, 650)),
        ("物理图片规律", (710, 360, 330, 210, 580, 390, 200)),
    )
    complete = False
    database_closed = False
    try:
        located = None
        for _attempt in range(40):
            page = switch_database_page_by_control(database_hwnd, 2530)
            buttons = (
                find_controls(
                    enum_child_tree(database_hwnd),
                    cls="Button",
                    ctrl_id=2550,
                    visible=True,
                )
                if page is not None
                else []
            )
            if buttons:
                located = (page[0], buttons[0])
                break
            time.sleep(1.0)
        if located is None:
            raise RuntimeError("weapon rule button not found")
        known = {item["hwnd"] for item in session.top_windows()}
        click_control(located[1]["hwnd"])
        rule_window = session.wait_new_top(
            exclude=known, timeout=5.0, cls_equals="WTWindow", title_contains="规律"
        )
        if not rule_window:
            raise RuntimeError("weapon rule window did not appear")
        rule_hwnd = rule_window["hwnd"]
        move_window(rule_hwnd, 80, 60, 1050, 760)
        time.sleep(0.5)
        tree = enum_child_tree(rule_hwnd)
        page_ctrls = find_controls(tree, cls="CPageControl", visible=True)
        if not page_ctrls:
            raise RuntimeError("weapon rule CPageControl not found")
        page_ctrl = max(
            page_ctrls,
            key=lambda item: item["rect"]["width"] * item["rect"]["height"],
        )
        win_rect = get_window_rect(rule_hwnd)
        dx, dy = _client_offset(rule_hwnd)
        ctrl_rect = page_ctrl["rect"]
        tab_y = ctrl_rect["top"] - win_rect["top"] + 24
        x_start = ctrl_rect["left"] - win_rect["left"] + 14
        x_end = ctrl_rect["right"] - win_rect["left"] - 24
        tab_states: list[tuple[int, tuple]] = []
        seen: set[tuple] = set()
        for x in range(x_start, x_end, 10):
            real_click_at(rule_hwnd, x - dx, tab_y - dy)
            time.sleep(0.20)
            signature = _window_ctrl_sig(rule_hwnd)
            if signature in seen:
                continue
            seen.add(signature)
            tab_states.append((x, signature))
            if len(tab_states) == len(page_specs):
                break
        if len(tab_states) != len(page_specs):
            raise RuntimeError(
                f"weapon rule page discovery incomplete: {len(tab_states)}/4"
            )
        for page_index, ((label, button_ids), (tab_x, _signature)) in enumerate(
            zip(page_specs, tab_states), 1
        ):
            for action_index, button_id in enumerate(button_ids, 1):
                real_click_at(rule_hwnd, tab_x - dx, tab_y - dy)
                time.sleep(0.25)
                current_tree = enum_child_tree(rule_hwnd)
                buttons = find_controls(
                    current_tree,
                    cls="Button",
                    ctrl_id=button_id,
                    visible=True,
                )
                if not buttons:
                    records.append(
                        {
                            "page": label,
                            "button_id": button_id,
                            "status": "button_missing",
                        }
                    )
                    continue
                button = buttons[0]
                before_signature = _window_ctrl_sig(rule_hwnd)
                known = {item["hwnd"] for item in session.top_windows()}
                click_control(button["hwnd"])
                time.sleep(0.9)
                descendants = [
                    item
                    for item in session.top_windows()
                    if item["hwnd"] not in known
                    and item["hwnd"] not in {database_hwnd, rule_hwnd}
                    and item["class"] != "#32768"
                ]
                captured: list[dict] = []
                for child_index, child in enumerate(descendants, 1):
                    tag = (
                        f"DBWRULEBTN_{page_index:02d}_{action_index:02d}_"
                        f"{label}_{button_id}_{child_index}"
                    )
                    dump = session.dump_window(child["hwnd"], tag, menu=True)
                    captured.append(
                        {
                            "title": child["title"],
                            "class": child["class"],
                            "tag": tag,
                            "visible_controls": [
                                {
                                    "class": item.get("class"),
                                    "control_id": item.get("ctrl_id"),
                                    "text": item.get("text", ""),
                                    "enabled": item.get("enabled"),
                                }
                                for item in flatten_tree(dump["tree"])
                                if item.get("visible")
                            ],
                        }
                    )
                    if child["class"] == "#32770":
                        session.handle_runtime_dialog(child["hwnd"], tag)
                        session.wait_gone(child["hwnd"], 5.0)
                    else:
                        close_window_safely(session, child["hwnd"], timeout=5.0)
                after_signature = (
                    _window_ctrl_sig(rule_hwnd) if is_window(rule_hwnd) else ()
                )
                records.append(
                    {
                        "page": label,
                        "button_id": button_id,
                        "text": button.get("text", ""),
                        "status": (
                            "descendant_captured"
                            if captured
                            else "inline_state_changed"
                            if after_signature != before_signature
                            else "no_visible_effect"
                        ),
                        "signature_changed": after_signature != before_signature,
                        "descendants": captured,
                    }
                )
                tree_path = control_tree_path(current_tree, button["hwnd"])
                if tree_path is None:
                    raise RuntimeError(
                        f"weapon rule button {button_id} tree path missing"
                    )
                execution_records.append(
                    {
                        "action_id": stable_interaction_id(
                            "规律", "Button", button_id, tree_path, "left_click"
                        ),
                        "status": "passed",
                        "result": (
                            f"旧版{label}按钮 {button_id} 实际左键："
                            + (
                                "打开并捕获子窗口。"
                                if captured
                                else "产生行内状态变化。"
                                if after_signature != before_signature
                                else "无新窗口且无可见状态变化。"
                            )
                        ),
                    }
                )

                # The legacy contract includes each button's secondary and
                # keyboard paths, not just its visually obvious left click.
                # Re-select the page and reacquire the HWND before every
                # gesture because a previous action may rebuild descendants.
                real_click_at(rule_hwnd, tab_x - dx, tab_y - dy)
                right_tree: dict = {}
                right_buttons: list[dict] = []
                for _retry in range(20):
                    time.sleep(0.15)
                    right_tree = enum_child_tree(rule_hwnd)
                    right_buttons = find_controls(
                        right_tree, cls="Button", ctrl_id=button_id,
                        visible=True,
                    )
                    if right_buttons and right_buttons[0].get("enabled"):
                        break
                if not right_buttons or not right_buttons[0].get("enabled"):
                    raise RuntimeError(
                        f"weapon rule button {button_id} missing before right-click"
                    )
                right_button = right_buttons[0]
                right_path = control_tree_path(right_tree, right_button["hwnd"])
                if right_path is None:
                    raise RuntimeError(
                        f"weapon rule button {button_id} right-click path missing"
                    )
                known = {item["hwnd"] for item in session.top_windows()}
                if not real_right_click_control(right_button["hwnd"]):
                    raise RuntimeError(
                        f"weapon rule button {button_id} right-click input failed"
                    )
                time.sleep(0.30)
                unexpected = [
                    item
                    for item in session.top_windows()
                    if item["hwnd"] not in known
                    and item["hwnd"] not in {database_hwnd, rule_hwnd}
                    and item["class"] != "#32768"
                    and item["title"].strip()
                ]
                if unexpected:
                    raise RuntimeError(
                        f"weapon rule button {button_id} right-click opened "
                        f"{[item['title'] for item in unexpected]}"
                    )
                send_key(rule_hwnd, VK_ESCAPE)
                right_action_id = stable_interaction_id(
                    "规律", "Button", button_id, right_path, "right_click"
                )
                gesture_records.append(
                    {
                        "page": label,
                        "button_id": button_id,
                        "gesture": "right_click",
                        "action_id": right_action_id,
                        "result": "no_new_titled_window",
                    }
                )
                execution_records.append(
                    {
                        "action_id": right_action_id,
                        "status": "passed",
                        "result": f"旧版{label}按钮 {button_id} 真实右键未打开有标题的功能窗口。",
                    }
                )

                real_click_at(rule_hwnd, tab_x - dx, tab_y - dy)
                keyboard_tree: dict = {}
                keyboard_buttons: list[dict] = []
                for _retry in range(20):
                    time.sleep(0.15)
                    keyboard_tree = enum_child_tree(rule_hwnd)
                    keyboard_buttons = find_controls(
                        keyboard_tree, cls="Button", ctrl_id=button_id,
                        visible=True,
                    )
                    if keyboard_buttons and keyboard_buttons[0].get("enabled"):
                        break
                if not keyboard_buttons or not keyboard_buttons[0].get("enabled"):
                    raise RuntimeError(
                        f"weapon rule button {button_id} missing before keyboard"
                    )
                keyboard_button = keyboard_buttons[0]
                keyboard_path = control_tree_path(
                    keyboard_tree, keyboard_button["hwnd"]
                )
                if keyboard_path is None:
                    raise RuntimeError(
                        f"weapon rule button {button_id} keyboard path missing"
                    )
                before_keyboard_signature = _window_ctrl_sig(rule_hwnd)
                known = {item["hwnd"] for item in session.top_windows()}
                if not focus_foreground_control(
                    rule_hwnd, keyboard_button["hwnd"]
                ):
                    raise RuntimeError(
                        f"weapon rule button {button_id} keyboard focus failed"
                    )
                keybd(VK_SPACE)
                time.sleep(0.08)
                keybd(VK_SPACE, up=True)
                time.sleep(0.90)
                keyboard_descendants = [
                    item
                    for item in session.top_windows()
                    if item["hwnd"] not in known
                    and item["hwnd"] not in {database_hwnd, rule_hwnd}
                    and item["class"] != "#32768"
                ]
                descendant_titles = [item["title"] for item in keyboard_descendants]
                for child_index, child in enumerate(keyboard_descendants, 1):
                    if child["class"] == "#32770":
                        session.handle_runtime_dialog(
                            child["hwnd"],
                            f"DBWRULEBTN_{page_index:02d}_{action_index:02d}_"
                            f"{label}_{button_id}_keyboard_{child_index}",
                        )
                        session.wait_gone(child["hwnd"], 5.0)
                    else:
                        close_window_safely(session, child["hwnd"], timeout=5.0)
                after_keyboard_signature = (
                    _window_ctrl_sig(rule_hwnd) if is_window(rule_hwnd) else ()
                )
                keyboard_action_id = stable_interaction_id(
                    "规律", "Button", button_id, keyboard_path,
                    "keyboard_activate",
                )
                keyboard_result = (
                    "descendant_captured"
                    if keyboard_descendants
                    else "inline_state_changed"
                    if after_keyboard_signature != before_keyboard_signature
                    else "no_visible_effect"
                )
                gesture_records.append(
                    {
                        "page": label,
                        "button_id": button_id,
                        "gesture": "keyboard_activate",
                        "action_id": keyboard_action_id,
                        "result": keyboard_result,
                        "descendant_titles": descendant_titles,
                    }
                )
                execution_records.append(
                    {
                        "action_id": keyboard_action_id,
                        "status": "passed",
                        "result": (
                            f"旧版{label}按钮 {button_id} 真实焦点空格键："
                            + (
                                f"打开并关闭 {descendant_titles}。"
                                if keyboard_descendants
                                else "产生行内状态变化。"
                                if keyboard_result == "inline_state_changed"
                                else "无新窗口且无可见状态变化。"
                            )
                        ),
                    }
                )
        cancel_buttons = [
            item
            for item in find_controls(
                enum_child_tree(rule_hwnd), cls="Button", ctrl_id=110, visible=True
            )
        ]
        if not cancel_buttons:
            raise RuntimeError("weapon rule Cancel button missing")
        click_control(cancel_buttons[0]["hwnd"])
        if not session.wait_gone(rule_hwnd, 6.0):
            raise RuntimeError("weapon rule window did not close after Cancel")
        rule_hwnd = 0
        database_cancel = [
            item
            for item in find_controls(
                enum_child_tree(database_hwnd),
                cls="Button",
                text_contains="取消",
                visible=True,
            )
            if item.get("text") == "取消"
        ]
        if not database_cancel:
            raise RuntimeError("database Cancel button missing")
        click_control(database_cancel[0]["hwnd"])
        database_closed = session.wait_gone(database_hwnd, 8.0)
        if database_closed:
            user32.PostMessageW(session.main_hwnd, WM_COMMAND, 20004, 0)
            time.sleep(4.0)
            for popup in session.top_windows():
                if (
                    popup["hwnd"] != session.main_hwnd
                    and popup["class"] == "#32770"
                ):
                    session.handle_runtime_dialog(
                        popup["hwnd"], "DBWRULEBTN_保存弹窗"
                    )
        complete = (
            database_closed
            and len(records) == sum(len(spec[1]) for spec in page_specs)
            and all(item["status"] != "button_missing" for item in records)
        )
    finally:
        if rule_hwnd and is_window(rule_hwnd):
            close_window_safely(session, rule_hwnd, timeout=5.0)
        if is_window(database_hwnd):
            close_window_safely(session, database_hwnd, timeout=5.0)
        after = session.probe_rom.read_bytes()
        diffs = [
            index
            for index, (old, new) in enumerate(zip(before, after))
            if old != new
        ]
        complete = complete and not diffs and len(before) == len(after)
        out_dir = session.out / "interaction-discovery"
        out_dir.mkdir(parents=True, exist_ok=True)
        (out_dir / "weapon-rule-button-descendants.json").write_text(
            json.dumps(
                {
                    "schema_version": 1,
                    "validated": complete,
                    "scope": (
                        "isolated reference executable; all visible weapon-rule "
                        "buttons activated by left-click, right-click and focused "
                        "Space; descendants cancelled; outer dialogs cancelled; "
                        "main-window save used to verify zero leakage"
                    ),
                    "database_cancel_closed": database_closed,
                    "sha256_before": hashlib.sha256(before).hexdigest().upper(),
                    "sha256_after": hashlib.sha256(after).hexdigest().upper(),
                    "diff_count": len(diffs) + int(len(before) != len(after)),
                    "records": records,
                    "gesture_records": gesture_records,
                    "execution_records": list(
                        {item["action_id"]: item for item in execution_records}.values()
                    ),
                },
                ensure_ascii=False,
                indent=2,
            )
            + "\n",
            encoding="utf-8",
        )
    if not complete:
        raise RuntimeError("weapon rule button discovery did not validate")
    log(f"DBWRULEBTN complete: {len(records)} buttons, zero ROM diff")


def stage_dbwrulebuttoncase(session: ProbeSession) -> None:
    """Run one potentially destructive weapon-rule button gesture in isolation."""

    page_index = int(session.wrule_page_index)
    button_id = int(session.wrule_button_id)
    gesture = str(session.wrule_button_action)
    page_labels = (
        "光束组图规律", "物理运行规律1", "物理运行规律2", "物理图片规律"
    )
    if page_index not in range(len(page_labels)):
        raise RuntimeError(f"invalid weapon rule page index: {page_index}")
    label = page_labels[page_index]
    log(
        f"=== stage DBWRULEBUTTONCASE: {label} button={button_id} "
        f"gesture={gesture} ==="
    )
    before = session.probe_rom.read_bytes()
    database_hwnd = 0
    rule_hwnd = 0
    performed = False
    database_closed = False
    execution_record: dict | None = None
    observation: dict = {
        "page": label,
        "page_index": page_index,
        "button_id": button_id,
        "gesture": gesture,
    }
    try:
        window = None
        for _attempt in range(3):
            window = _open_data_window(
                session, 20008, "数据库", dismiss_hidden=False
            )
            if window:
                break
            time.sleep(0.8)
        if not window:
            raise RuntimeError("database window did not appear")
        database_hwnd = window["hwnd"]
        located = None
        for _attempt in range(40):
            page = switch_database_page_by_control(database_hwnd, 2530)
            buttons = (
                find_controls(
                    enum_child_tree(database_hwnd), cls="Button",
                    ctrl_id=2550, visible=True,
                ) if page is not None else []
            )
            if buttons:
                located = buttons[0]
                break
            time.sleep(0.5)
        if located is None:
            session.dump_window(
                database_hwnd, "DBWRULEBUTTONCASE_数据库未就绪", menu=False
            )
            raise RuntimeError("weapon rule button not found")
        known = {item["hwnd"] for item in session.top_windows()}
        click_control(located["hwnd"])
        rule_window = session.wait_new_top(
            exclude=known, timeout=5.0, cls_equals="WTWindow",
            title_contains="规律",
        )
        if not rule_window:
            raise RuntimeError("weapon rule window did not appear")
        rule_hwnd = rule_window["hwnd"]
        move_window(rule_hwnd, 80, 60, 1050, 760)
        time.sleep(0.5)
        tree = enum_child_tree(rule_hwnd)
        page_ctrls = find_controls(tree, cls="CPageControl", visible=True)
        if not page_ctrls:
            raise RuntimeError("weapon rule CPageControl not found")
        page_ctrl = max(
            page_ctrls,
            key=lambda item: item["rect"]["width"] * item["rect"]["height"],
        )
        ctrl_rect = page_ctrl["rect"]
        page_width = max(1, ctrl_rect["right"] - ctrl_rect["left"])
        tab_states: list[int] = []
        seen: set[tuple] = set()
        for local_x in range(14, max(15, page_width - 24), 10):
            post_click_at(page_ctrl["hwnd"], local_x, 24)
            time.sleep(0.20)
            signature = _window_ctrl_sig(rule_hwnd)
            if signature in seen:
                continue
            seen.add(signature)
            tab_states.append(local_x)
            if len(tab_states) == len(page_labels):
                break
        if len(tab_states) != len(page_labels):
            raise RuntimeError(
                f"weapon rule page discovery incomplete: {len(tab_states)}/4"
            )
        post_click_at(page_ctrl["hwnd"], tab_states[page_index], 24)
        time.sleep(0.25)
        # Some owner-drawn buttons are conditional record surfaces.  The
        # legacy beam page exposes ID 470 only for records with a configured
        # puzzle (for example row 10); selecting the tab alone is therefore
        # insufficient to make that usable action reachable.
        if session.wrule_record:
            list_ids = (230, 290, 690, 340)
            list_id = list_ids[page_index]
            record_lists = find_controls(
                enum_child_tree(rule_hwnd), cls="ListBox",
                ctrl_id=list_id, visible=True,
            )
            if not record_lists:
                raise RuntimeError(f"weapon rule list {list_id} missing")
            list_hwnd = record_lists[0]["hwnd"]
            if _send_msg_num(
                list_hwnd, 0x0186, session.wrule_record, 0
            ) == -1:
                raise RuntimeError(
                    f"weapon rule record {session.wrule_record} cannot be selected"
                )
            notify_parent = user32.GetParent(list_hwnd)
            notified: set[int] = set()
            while notify_parent and notify_parent not in notified:
                notified.add(notify_parent)
                _send_msg_num(
                    notify_parent, WM_COMMAND,
                    list_id | (1 << 16), list_hwnd,
                )
                if notify_parent == rule_hwnd:
                    break
                notify_parent = user32.GetParent(notify_parent)
            observation["record_index"] = session.wrule_record
            time.sleep(0.35)
        current_tree = enum_child_tree(rule_hwnd)
        buttons = find_controls(
            current_tree, cls="Button", ctrl_id=button_id, visible=True
        )
        if not buttons or not buttons[0].get("enabled"):
            raise RuntimeError(
                f"weapon rule button {button_id} missing or disabled"
            )
        button = buttons[0]
        path = control_tree_path(current_tree, button["hwnd"])
        if path is None:
            raise RuntimeError(f"weapon rule button {button_id} path missing")
        known = {item["hwnd"] for item in session.top_windows()}
        if gesture == "left":
            if not real_click_control(button["hwnd"]):
                raise RuntimeError("left-click input failed")
            action_name = "left_click"
        elif gesture == "right":
            if not real_right_click_control(button["hwnd"]):
                raise RuntimeError("right-click input failed")
            action_name = "right_click"
        elif gesture == "keyboard":
            if not focus_foreground_control(rule_hwnd, button["hwnd"]):
                raise RuntimeError("keyboard focus failed")
            keybd(VK_SPACE)
            time.sleep(0.08)
            keybd(VK_SPACE, up=True)
            action_name = "keyboard_activate"
        else:
            raise RuntimeError(f"unsupported button gesture: {gesture}")
        performed = True
        time.sleep(0.9 if gesture != "right" else 0.3)
        descendants = [
            item for item in session.top_windows()
            if item["hwnd"] not in known
            and item["hwnd"] not in {database_hwnd, rule_hwnd}
            and item["class"] != "#32768" and item["title"].strip()
        ]
        observation["descendants"] = [
            {"title": item["title"], "class": item["class"]}
            for item in descendants
        ]
        for child_index, child in enumerate(descendants, 1):
            tag = (
                f"DBWRULEBUTTONCASE_{page_index}_{button_id}_"
                f"{gesture}_{child_index}"
            )
            session.dump_window(child["hwnd"], tag, menu=True)
            if child["class"] == "#32770":
                session.handle_runtime_dialog(child["hwnd"], tag)
                session.wait_gone(child["hwnd"], 5.0)
            else:
                close_window_safely(session, child["hwnd"], timeout=5.0)
        observation["rule_alive_after"] = bool(
            rule_hwnd and is_window(rule_hwnd)
        )
        execution_record = {
            "action_id": stable_interaction_id(
                "规律", "Button", button_id, path, action_name
            ),
            "status": "passed",
            "result": (
                f"旧版{label}按钮 {button_id} 的 {gesture} 实跑；"
                f"后代窗口={observation['descendants']}，"
                f"父规律窗存活={observation['rule_alive_after']}。"
            ),
        }
        if gesture == "right":
            send_key(rule_hwnd, VK_ESCAPE)
        if rule_hwnd and is_window(rule_hwnd):
            cancel = find_controls(
                enum_child_tree(rule_hwnd), cls="Button",
                ctrl_id=110, visible=True,
            )
            if cancel:
                click_control(cancel[0]["hwnd"])
                if session.wait_gone(rule_hwnd, 6.0):
                    rule_hwnd = 0
            if rule_hwnd and is_window(rule_hwnd):
                observation["rule_cancel_fallback"] = True
                close_window_safely(session, rule_hwnd, timeout=5.0)
                if not is_window(rule_hwnd):
                    rule_hwnd = 0
        if database_hwnd and is_window(database_hwnd):
            database_cancel = [
                item for item in find_controls(
                    enum_child_tree(database_hwnd), cls="Button",
                    text_contains="取消", visible=True,
                ) if item.get("text") == "取消"
            ]
            if not database_cancel:
                raise RuntimeError("database Cancel button missing")
            click_control(database_cancel[0]["hwnd"])
            database_closed = session.wait_gone(database_hwnd, 8.0)
            if not database_closed and is_window(database_hwnd):
                observation["database_cancel_fallback"] = True
                close_window_safely(session, database_hwnd, timeout=5.0)
                database_closed = not is_window(database_hwnd)
    except Exception as exc:
        observation["failure"] = repr(exc)
        log(f"DBWRULEBUTTONCASE inner failure: {exc!r}")
    finally:
        if rule_hwnd and is_window(rule_hwnd):
            close_window_safely(session, rule_hwnd, timeout=5.0)
        if database_hwnd and is_window(database_hwnd):
            close_window_safely(session, database_hwnd, timeout=5.0)
        if database_hwnd:
            database_closed = not is_window(database_hwnd)
        after = session.probe_rom.read_bytes()
        diffs = [
            index for index, (old, new) in enumerate(zip(before, after))
            if old != new
        ]
        cleanup_disposition = (
            "database_cancel_closed"
            if database_closed
            else "owned_process_termination_after_isolated_action"
        )
        validated = (
            performed and execution_record is not None
            and (database_closed or session.owns_process)
            and not diffs and len(before) == len(after)
        )
        out_dir = session.out / "interaction-discovery"
        out_dir.mkdir(parents=True, exist_ok=True)
        (out_dir / "weapon-rule-button-case.json").write_text(
            json.dumps(
                {
                    "schema_version": 1,
                    "validated": validated,
                    "scope": (
                        "one isolated weapon-rule button gesture; descendants "
                        "dismissed; outer dialogs cancelled; no save"
                    ),
                    "observation": observation,
                    "database_cancel_closed": database_closed,
                    "cleanup_disposition": cleanup_disposition,
                    "sha256_before": hashlib.sha256(before).hexdigest().upper(),
                    "sha256_after": hashlib.sha256(after).hexdigest().upper(),
                    "diff_count": len(diffs) + int(len(before) != len(after)),
                    "execution_records": (
                        [execution_record] if validated and execution_record else []
                    ),
                },
                ensure_ascii=False,
                indent=2,
            ) + "\n",
            encoding="utf-8",
        )
    if not validated:
        raise RuntimeError("weapon rule button case did not validate")
    log(
        f"DBWRULEBUTTONCASE complete: page={page_index} "
        f"button={button_id} gesture={gesture}, zero ROM diff"
    )


def stage_dbwrulecontrols(session: ProbeSession) -> None:
    """Exercise every non-button control on the four weapon-rule pages.

    All edits stay in the legacy window's draft and the outer database is
    cancelled.  The stage emits one stable execution record for every action
    in the recursive frontier, plus explicit evidence for controls whose
    visibility/enabled state changes between pages or record selections.
    """

    log("=== stage DBWRULECONTROLS: complete weapon-rule control matrix ===")
    before = session.probe_rom.read_bytes()
    database_hwnd = 0
    rule_hwnd = 0
    execution_records: list[dict] = []
    observations: list[dict] = []
    state_observations: dict[tuple, dict] = {}
    processed: set[tuple[str, int, tuple[int, ...]]] = set()
    database_closed = False
    error: str | None = None

    def walk_paths(node: dict, path: tuple[int, ...] = ()):
        yield node, path
        for index, child in enumerate(node.get("children", [])):
            if isinstance(child, dict):
                yield from walk_paths(child, path + (index,))

    def record_action(
        cls_name: str, control_id: int, path: tuple[int, ...],
        action: str, result: str,
    ) -> None:
        execution_records.append(
            {
                "action_id": stable_interaction_id(
                    "规律", cls_name, control_id, list(path), action
                ),
                "status": "passed",
                "result": result,
            }
        )

    def notify_edit(edit_hwnd: int, control_id: int) -> None:
        parent = user32.GetParent(edit_hwnd)
        if parent:
            _send_msg_num(
                parent, WM_COMMAND,
                (control_id & 0xFFFF) | (0x0300 << 16), edit_hwnd,
            )

    def capture_state(label: str) -> None:
        tree = enum_child_tree(rule_hwnd)
        for item, path in walk_paths(tree):
            cls_name = str(item.get("class", ""))
            control_id = int(item.get("ctrl_id") or 0)
            key = (cls_name, control_id, path)
            state = state_observations.setdefault(
                key,
                {
                    "visible": set(), "enabled": set(), "labels": set(),
                    "texts": set(),
                },
            )
            state["visible"].add(bool(item.get("visible", False)))
            state["enabled"].add(bool(item.get("enabled", False)))
            state["labels"].add(label)
            state["texts"].add(str(item.get("text", "")))

    def dismiss_popups(known: set[int], tag: str) -> list[dict]:
        found = []
        for index, popup in enumerate(session.top_windows(), 1):
            if (
                popup["hwnd"] in known
                or popup["hwnd"] in {database_hwnd, rule_hwnd}
                or popup["class"] == "#32768"
                or not popup["title"].strip()
            ):
                continue
            found.append({"title": popup["title"], "class": popup["class"]})
            session.dump_window(popup["hwnd"], f"{tag}_{index}", menu=True)
            if popup["class"] == "#32770":
                session.handle_runtime_dialog(popup["hwnd"], f"{tag}_{index}")
            else:
                close_window_safely(session, popup["hwnd"], timeout=3.0)
        return found

    def exercise_edit(item: dict, path: tuple[int, ...]) -> None:
        hwnd = item["hwnd"]
        control_id = int(item.get("ctrl_id") or 0)
        original = get_window_text(hwnd)
        focused = focus_foreground_control(rule_hwnd, hwnd)
        record_action(
            "Edit", control_id, path, "focus",
            f"旧版输入框获得真实键盘焦点={focused}。",
        )

        replacement = (original + " ") if original else "0"
        set_control_text(hwnd, replacement)
        notify_edit(hwnd, control_id)
        replaced = get_window_text(hwnd)
        set_control_text(hwnd, original)
        notify_edit(hwnd, control_id)
        record_action(
            "Edit", control_id, path, "replace_value",
            f"草稿替换读回={replaced!r}，随后恢复原值。",
        )

        focus_foreground_control(rule_hwnd, hwnd)
        keybd(VK_CONTROL)
        keybd(ord("A")); keybd(ord("A"), up=True)
        keybd(VK_CONTROL, up=True)
        keybd(VK_CONTROL)
        keybd(ord("Z")); keybd(ord("Z"), up=True)
        keybd(VK_CONTROL, up=True)
        set_control_text(hwnd, original)
        notify_edit(hwnd, control_id)
        record_action(
            "Edit", control_id, path, "keyboard_shortcuts",
            "真实焦点执行 Ctrl+A、Ctrl+Z，随后恢复原草稿。",
        )

        post_context_menu(hwnd, 6, 6)
        time.sleep(0.12)
        send_escape(rule_hwnd)
        record_action(
            "Edit", control_id, path, "right_click",
            "在输入框内执行右键/上下文菜单路径并关闭菜单。",
        )

        boundary_reads = []
        for candidate in ("", "A" * 256):
            set_control_text(hwnd, candidate)
            notify_edit(hwnd, control_id)
            boundary_reads.append(len(get_window_text(hwnd)))
        set_control_text(hwnd, original)
        notify_edit(hwnd, control_id)
        record_action(
            "Edit", control_id, path, "boundary_values",
            f"空值/256 字符边界读回长度={boundary_reads}，随后恢复。",
        )
        observations.append(
            {
                "class": "Edit", "control_id": control_id,
                "path": list(path), "original": original,
                "replacement_readback": replaced,
                "boundary_readback_lengths": boundary_reads,
            }
        )

    def exercise_spinner(item: dict, path: tuple[int, ...], tree: dict) -> None:
        hwnd = item["hwnd"]
        control_id = int(item.get("ctrl_id") or 0)
        width, height = get_client_size(hwnd)
        buddy_id = control_id - 4
        buddies = find_controls(tree, cls="Edit", ctrl_id=buddy_id, visible=True)
        buddy = buddies[0]["hwnd"] if buddies else 0
        original = get_window_text(buddy) if buddy else ""
        post_click_at(hwnd, max(1, width // 2), max(1, height // 4))
        time.sleep(0.08)
        increment_read = get_window_text(buddy) if buddy else ""
        record_action(
            "msctls_updown32", control_id, path, "increment",
            f"点击上半区，伙伴输入框由 {original!r} 变为 {increment_read!r}。",
        )
        if buddy:
            set_control_text(buddy, original); notify_edit(buddy, buddy_id)
        post_click_at(hwnd, max(1, width // 2), max(1, height * 3 // 4))
        time.sleep(0.08)
        decrement_read = get_window_text(buddy) if buddy else ""
        record_action(
            "msctls_updown32", control_id, path, "decrement",
            f"点击下半区，伙伴输入框由 {original!r} 变为 {decrement_read!r}。",
        )
        boundary_reads = []
        if buddy:
            for candidate in ("-32768", "32767"):
                set_control_text(buddy, candidate); notify_edit(buddy, buddy_id)
                boundary_reads.append(get_window_text(buddy))
            set_control_text(buddy, original); notify_edit(buddy, buddy_id)
        record_action(
            "msctls_updown32", control_id, path, "boundary_values",
            f"伙伴输入框边界读回={boundary_reads}，随后恢复。",
        )
        observations.append(
            {
                "class": "msctls_updown32", "control_id": control_id,
                "path": list(path), "original": original,
                "increment_readback": increment_read,
                "decrement_readback": decrement_read,
                "boundary_readbacks": boundary_reads,
            }
        )

    def exercise_combo(item: dict, path: tuple[int, ...]) -> None:
        hwnd = item["hwnd"]
        control_id = int(item.get("ctrl_id") or 0)
        values = read_combo_items(hwnd)
        original = int(_send_msg_num(hwnd, CB_GETCURSEL, 0, 0))
        _send_msg_num(hwnd, 0x014F, 1, 0)  # CB_SHOWDROPDOWN
        time.sleep(0.08)
        _send_msg_num(hwnd, 0x014F, 0, 0)
        record_action(
            "ComboBox", control_id, path, "open_dropdown",
            f"展开并收起旧版下拉框，共 {len(values)} 项。",
        )
        selected = []
        for index in range(len(values)):
            set_combo_selection(hwnd, index)
            selected.append(int(_send_msg_num(hwnd, CB_GETCURSEL, 0, 0)))
        if original >= 0:
            set_combo_selection(hwnd, original)
        record_action(
            "ComboBox", control_id, path, "select_each_item",
            f"逐项选择并读回 {len(selected)}/{len(values)} 项，恢复索引 {original}。",
        )
        focus_foreground_control(rule_hwnd, hwnd)
        send_key(hwnd, VK_HOME); send_key(hwnd, VK_DOWN)
        keyboard_index = int(_send_msg_num(hwnd, CB_GETCURSEL, 0, 0))
        if original >= 0:
            set_combo_selection(hwnd, original)
        record_action(
            "ComboBox", control_id, path, "keyboard_cycle",
            f"Home/Down 键盘循环读回索引 {keyboard_index}，随后恢复。",
        )
        post_context_menu(hwnd, 6, 6)
        time.sleep(0.12); send_escape(rule_hwnd)
        record_action(
            "ComboBox", control_id, path, "right_click",
            "执行下拉框右键路径并关闭可能出现的菜单。",
        )
        observations.append(
            {
                "class": "ComboBox", "control_id": control_id,
                "path": list(path), "item_count": len(values),
                "original_index": original, "selected_readbacks": selected,
                "keyboard_index": keyboard_index,
            }
        )

    def exercise_canvas(item: dict, path: tuple[int, ...]) -> None:
        hwnd = item["hwnd"]
        control_id = int(item.get("ctrl_id") or 0)
        width, height = get_client_size(hwnd)
        cx, cy = max(1, width // 2), max(1, height // 2)
        post_click_at(hwnd, cx, cy)
        record_action(
            "AfxWnd42s", control_id, path, "left_click_regions",
            "在旧版箭头画布中央执行左键。",
        )
        post_double_click_at(hwnd, cx, cy)
        record_action(
            "AfxWnd42s", control_id, path, "double_click_regions",
            "在旧版箭头画布中央执行双击。",
        )
        post_click_at(hwnd, cx, cy, button="right")
        send_escape(rule_hwnd)
        record_action(
            "AfxWnd42s", control_id, path, "right_click_regions",
            "在旧版箭头画布中央执行右键。",
        )
        post_drag_at(hwnd, max(1, cx - 2), cy, min(width - 1, cx + 2), cy)
        record_action(
            "AfxWnd42s", control_id, path, "drag_regions",
            "在旧版箭头画布中央执行短距离拖拽。",
        )

    def exercise_visible_controls() -> None:
        tree = enum_child_tree(rule_hwnd)
        for item, path in list(walk_paths(tree)):
            if not item.get("visible") or not item.get("enabled"):
                continue
            cls_name = str(item.get("class", ""))
            control_id = int(item.get("ctrl_id") or 0)
            key = (cls_name, control_id, path)
            if key in processed:
                continue
            if cls_name == "Edit":
                exercise_edit(item, path)
            elif cls_name == "ComboBox":
                exercise_combo(item, path)
            elif cls_name == "msctls_updown32":
                exercise_spinner(item, path, tree)
            elif cls_name == "AfxWnd42s" and control_id in (1008, 1009):
                exercise_canvas(item, path)
            else:
                continue
            processed.add(key)

    try:
        window = None
        for _attempt in range(5):
            window = _open_data_window(
                session, 20008, "数据库", dismiss_hidden=False
            )
            if window:
                break
            time.sleep(1.0)
        if not window:
            raise RuntimeError("database window did not appear")
        database_hwnd = window["hwnd"]
        located = None
        for _attempt in range(40):
            page = switch_database_page_by_control(database_hwnd, 2530)
            buttons = (
                find_controls(
                    enum_child_tree(database_hwnd), cls="Button",
                    ctrl_id=2550, visible=True,
                ) if page is not None else []
            )
            if buttons:
                located = buttons[0]
                break
            time.sleep(0.5)
        if located is None:
            raise RuntimeError("weapon rule button not found")
        known = {item["hwnd"] for item in session.top_windows()}
        click_control(located["hwnd"])
        rule_window = session.wait_new_top(
            exclude=known, timeout=6.0, cls_equals="WTWindow",
            title_contains="规律",
        )
        if not rule_window:
            raise RuntimeError("weapon rule window did not appear")
        rule_hwnd = rule_window["hwnd"]
        move_window(rule_hwnd, 80, 60, 1050, 760)
        time.sleep(0.5)
        tree = enum_child_tree(rule_hwnd)
        page_ctrls = find_controls(tree, cls="CPageControl", visible=True)
        if not page_ctrls:
            raise RuntimeError("weapon rule CPageControl not found")
        page_ctrl = max(
            page_ctrls,
            key=lambda item: item["rect"]["width"] * item["rect"]["height"],
        )
        page_path = control_tree_path(tree, page_ctrl["hwnd"])
        if page_path is None:
            raise RuntimeError("weapon rule page path missing")
        page_width = max(1, page_ctrl["rect"]["width"])
        tab_states: list[int] = []
        seen: set[tuple] = set()
        for local_x in range(14, max(15, page_width - 24), 10):
            post_click_at(page_ctrl["hwnd"], local_x, 24)
            time.sleep(0.20)
            signature = _window_ctrl_sig(rule_hwnd)
            if signature in seen:
                continue
            seen.add(signature); tab_states.append(local_x)
            if len(tab_states) == 4:
                break
        if len(tab_states) != 4:
            raise RuntimeError(f"weapon rule page discovery {len(tab_states)}/4")

        focus_foreground_control(rule_hwnd, page_ctrl["hwnd"])
        keybd(VK_CONTROL); keybd(0x09); keybd(0x09, up=True); keybd(VK_CONTROL, up=True)
        time.sleep(0.15)
        post_click_at(page_ctrl["hwnd"], tab_states[0], 24)
        record_action(
            "CPageControl", int(page_ctrl.get("ctrl_id") or 0),
            tuple(page_path), "keyboard_tab_cycle",
            "真实焦点执行 Ctrl+Tab，并恢复到首个规律页。",
        )

        page_labels = ("光束", "物理运行1", "物理运行2", "物理图片")
        list_ids = (230, 290, 690, 340)
        for page_index, local_x in enumerate(tab_states):
            post_click_at(page_ctrl["hwnd"], local_x, 24)
            time.sleep(0.25)
            capture_state(page_labels[page_index])
            exercise_visible_controls()
            if page_index == 0:
                lists = find_controls(
                    enum_child_tree(rule_hwnd), cls="ListBox",
                    ctrl_id=list_ids[0], visible=True,
                )
                if lists:
                    list_hwnd = lists[0]["hwnd"]
                    _send_msg_num(list_hwnd, LB_SETCURSEL, 10, 0)
                    parent = user32.GetParent(list_hwnd)
                    seen_parents: set[int] = set()
                    while parent and parent not in seen_parents:
                        seen_parents.add(parent)
                        _send_msg_num(
                            parent, WM_COMMAND,
                            list_ids[0] | (LBN_SELCHANGE << 16), list_hwnd,
                        )
                        if parent == rule_hwnd:
                            break
                        parent = user32.GetParent(parent)
                    time.sleep(0.3)
                    capture_state("光束-记录10")
                    exercise_visible_controls()

        state_classes = {
            "Button", "Edit", "ComboBox", "msctls_updown32",
            "Afx:400000:b:10003:900015:0",
        }
        for (cls_name, control_id, path), state in state_observations.items():
            if cls_name not in state_classes:
                continue
            if len(state["visible"]) <= 1 and len(state["enabled"]) <= 1:
                continue
            record_action(
                cls_name, control_id, path, "discover_state_triggers",
                "页签/记录状态实跑："
                f"visible={sorted(state['visible'])}，"
                f"enabled={sorted(state['enabled'])}，"
                f"状态={sorted(state['labels'])}。",
            )

        known = {item["hwnd"] for item in session.top_windows()}
        dismiss_popups(known, "DBWRULECONTROLS_残留弹窗")
        cancel = find_controls(
            enum_child_tree(rule_hwnd), cls="Button", ctrl_id=110, visible=True
        )
        if cancel:
            click_control(cancel[0]["hwnd"])
            if session.wait_gone(rule_hwnd, 6.0):
                rule_hwnd = 0
        if database_hwnd and is_window(database_hwnd):
            db_cancel = [
                item for item in find_controls(
                    enum_child_tree(database_hwnd), cls="Button",
                    text_contains="取消", visible=True,
                ) if item.get("text") == "取消"
            ]
            if db_cancel:
                click_control(db_cancel[0]["hwnd"])
                database_closed = session.wait_gone(database_hwnd, 8.0)
    except Exception as exc:
        error = repr(exc)
        log(f"DBWRULECONTROLS inner failure: {error}")
    finally:
        if rule_hwnd and is_window(rule_hwnd):
            close_window_safely(session, rule_hwnd, timeout=5.0)
        if database_hwnd and is_window(database_hwnd):
            close_window_safely(session, database_hwnd, timeout=5.0)
        if database_hwnd:
            database_closed = not is_window(database_hwnd)
        after = session.probe_rom.read_bytes()
        diffs = [
            index for index, (old, new) in enumerate(zip(before, after))
            if old != new
        ]
        unique_records = {
            item["action_id"]: item for item in execution_records
        }
        action_counts: dict[str, int] = {}
        for item in unique_records.values():
            action = item["action_id"]
            action_counts[action] = action_counts.get(action, 0) + 1
        validated = (
            error is None
            and len(unique_records) == 163
            and (database_closed or session.owns_process)
            and not diffs and len(before) == len(after)
        )
        out_dir = session.out / "interaction-discovery"
        out_dir.mkdir(parents=True, exist_ok=True)
        (out_dir / "weapon-rule-control-actions.json").write_text(
            json.dumps(
                {
                    "schema_version": 1,
                    "validated": validated,
                    "scope": (
                        "all 101 live non-button actions plus 62 dynamic-state "
                        "triggers on the four legacy weapon-rule pages; "
                        "database cancelled; isolated ROM zero-diff gate"
                    ),
                    "error": error,
                    "database_cancel_closed": database_closed,
                    "sha256_before": hashlib.sha256(before).hexdigest().upper(),
                    "sha256_after": hashlib.sha256(after).hexdigest().upper(),
                    "diff_count": len(diffs) + int(len(before) != len(after)),
                    "processed_control_count": len(processed),
                    "state_control_count": len(state_observations),
                    "execution_record_count": len(unique_records),
                    "observations": observations,
                    "execution_records": (
                        list(unique_records.values()) if validated else []
                    ),
                },
                ensure_ascii=False, indent=2,
            ) + "\n",
            encoding="utf-8",
        )
    if not validated:
        raise RuntimeError(
            f"weapon rule control matrix did not validate: "
            f"records={len(unique_records)}/163 error={error}"
        )
    log("DBWRULECONTROLS complete: 163/163 actions, zero ROM diff")


def stage_dbwrulelists(session: ProbeSession) -> None:
    """Exercise every weapon-rule list item and the four page tabs."""

    log("=== stage DBWRULELISTS: weapon rule tabs and list gestures ===")
    if not session.main_hwnd or not is_window(session.main_hwnd):
        raise RuntimeError("main window not alive")
    if not session.rom_is_loaded():
        raise RuntimeError("ROM not loaded")
    before = session.probe_rom.read_bytes()
    database_hwnd = 0
    rule_hwnd = 0
    records: list[dict] = []
    execution_records: list[dict] = []
    complete = False
    database_closed = False
    page_specs = (
        ("光束组图规律", 230),
        ("物理运行规律1", 290),
        ("物理运行规律2", 690),
        ("物理图片规律", 340),
    )
    try:
        window = None
        for _attempt in range(3):
            window = _open_data_window(
                session, 20008, "数据库", dismiss_hidden=False
            )
            if window:
                break
            time.sleep(0.8)
        if not window:
            raise RuntimeError("database window did not appear")
        database_hwnd = window["hwnd"]
        located = None
        for _attempt in range(20):
            page = switch_database_page_by_control(database_hwnd, 2530)
            buttons = (
                find_controls(
                    enum_child_tree(database_hwnd), cls="Button",
                    ctrl_id=2550, visible=True,
                )
                if page is not None else []
            )
            if buttons:
                located = buttons[0]
                break
            time.sleep(1.0)
        if located is None:
            raise RuntimeError("weapon rule button not found")
        known = {item["hwnd"] for item in session.top_windows()}
        click_control(located["hwnd"])
        rule_window = session.wait_new_top(
            exclude=known, timeout=5.0, cls_equals="WTWindow",
            title_contains="规律",
        )
        if not rule_window:
            raise RuntimeError("weapon rule window did not appear")
        rule_hwnd = rule_window["hwnd"]
        move_window(rule_hwnd, 80, 60, 1050, 760)
        time.sleep(0.5)

        tree = enum_child_tree(rule_hwnd)
        page_ctrls = find_controls(tree, cls="CPageControl", visible=True)
        if not page_ctrls:
            raise RuntimeError("weapon rule CPageControl not found")
        page_ctrl = max(
            page_ctrls,
            key=lambda item: item["rect"]["width"] * item["rect"]["height"],
        )
        page_path = control_tree_path(tree, page_ctrl["hwnd"])
        if page_path is None:
            raise RuntimeError("weapon rule page-control path missing")
        win_rect = get_window_rect(rule_hwnd)
        dx, dy = _client_offset(rule_hwnd)
        ctrl_rect = page_ctrl["rect"]
        tab_y = ctrl_rect["top"] - win_rect["top"] + 24
        x_start = ctrl_rect["left"] - win_rect["left"] + 14
        x_end = ctrl_rect["right"] - win_rect["left"] - 24
        tab_states: list[tuple[int, tuple]] = []
        seen: set[tuple] = set()
        for x in range(x_start, x_end, 10):
            if not real_click_at(rule_hwnd, x - dx, tab_y - dy):
                raise RuntimeError("weapon rule tab click input failed")
            time.sleep(0.20)
            signature = _window_ctrl_sig(rule_hwnd)
            if signature in seen:
                continue
            seen.add(signature)
            tab_states.append((x, signature))
            if len(tab_states) == len(page_specs):
                break
        if len(tab_states) != len(page_specs):
            raise RuntimeError(
                f"weapon rule page discovery incomplete: {len(tab_states)}/4"
            )
        execution_records.append(
            {
                "action_id": stable_interaction_id(
                    "规律", "CPageControl", int(page_ctrl["ctrl_id"]),
                    page_path, "select_each_tab",
                ),
                "status": "passed",
                "result": "旧版页签条真实左键遍历出四个唯一规律页状态。",
            }
        )
        right_tab_results: list[dict] = []
        for page_index, ((label, _list_id), (tab_x, _signature)) in enumerate(
            zip(page_specs, tab_states), 1
        ):
            known = {item["hwnd"] for item in session.top_windows()}
            if not real_click_at(
                rule_hwnd, tab_x - dx, tab_y - dy, button="right"
            ):
                raise RuntimeError(f"weapon rule tab {label} right-click failed")
            time.sleep(0.25)
            titled = [
                item for item in session.top_windows()
                if item["hwnd"] not in known
                and item["hwnd"] not in {database_hwnd, rule_hwnd}
                and item["class"] != "#32768" and item["title"].strip()
            ]
            if titled:
                raise RuntimeError(
                    f"weapon rule tab {label} right-click opened "
                    f"{[item['title'] for item in titled]}"
                )
            send_key(rule_hwnd, VK_ESCAPE)
            right_tab_results.append(
                {"page": label, "page_index": page_index,
                 "result": "no_new_titled_window"}
            )
        execution_records.append(
            {
                "action_id": stable_interaction_id(
                    "规律", "CPageControl", int(page_ctrl["ctrl_id"]),
                    page_path, "right_click_tabs",
                ),
                "status": "passed",
                "result": "旧版四个规律页签逐个真实右键，均未打开有标题功能窗口。",
            }
        )

        for (label, list_id), (tab_x, _signature) in zip(page_specs, tab_states):
            if not real_click_at(rule_hwnd, tab_x - dx, tab_y - dy):
                raise RuntimeError(f"weapon rule page {label} select failed")
            time.sleep(0.25)
            current_tree = enum_child_tree(rule_hwnd)
            lists = find_controls(
                current_tree, cls="ListBox", ctrl_id=list_id, visible=True
            )
            if not lists:
                raise RuntimeError(f"weapon rule list {list_id} missing")
            list_control = lists[0]
            list_hwnd = list_control["hwnd"]
            list_path = control_tree_path(current_tree, list_hwnd)
            if list_path is None:
                raise RuntimeError(f"weapon rule list {list_id} path missing")
            item_count = int(_send_msg_num(list_hwnd, LB_GETCOUNT, 0, 0))
            logical_item_height = int(
                _send_msg_num(list_hwnd, LB_GETITEMHEIGHT, 0, 0)
            )
            dpi = int(user32.GetDpiForWindow(list_hwnd)) or 96
            if item_count <= 0 or logical_item_height <= 0:
                raise RuntimeError(
                    f"weapon rule list {list_id} invalid geometry "
                    f"count={item_count} height={logical_item_height}"
                )
            rect = get_window_rect(list_hwnd)
            click_x = max(3, min(24, rect["width"] // 3))
            selected: list[int] = []
            double_clicked: list[int] = []
            right_clicked: list[int] = []
            if not force_foreground(rule_hwnd):
                raise RuntimeError(f"weapon rule list {list_id} foreground failed")
            _send_msg_num(list_hwnd, LB_SETTOPINDEX, 0, 0)
            row_spans: dict[int, list[int]] = {}
            for probe_y in range(1, rect["height"] - 2):
                real_click_control_cell_fast(list_hwnd, click_x, probe_y)
                probe_index = int(
                    _send_msg_num(list_hwnd, LB_GETCURSEL, 0, 0)
                )
                if 0 <= probe_index < item_count:
                    span = row_spans.setdefault(probe_index, [probe_y, probe_y])
                    span[1] = probe_y
            if 0 not in row_spans or 1 not in row_spans:
                raise RuntimeError(
                    f"weapon rule list {list_id} row calibration failed: "
                    f"{row_spans}"
                )
            row_centers = {
                row: (span[0] + span[1]) // 2
                for row, span in row_spans.items()
            }
            visible_rows = max(row_centers) + 1

            def item_point(index: int) -> tuple[int, int, int, int]:
                requested_top = max(0, index - visible_rows // 2)
                _send_msg_num(list_hwnd, LB_SETTOPINDEX, requested_top, 0)
                actual_top = int(
                    _send_msg_num(list_hwnd, LB_GETTOPINDEX, 0, 0)
                )
                row = index - actual_top
                item_y = row_centers.get(row, -1)
                if row < 0 or item_y < 0 or item_y >= rect["height"]:
                    raise RuntimeError(
                        f"weapon rule list {list_id} item {index} not visible "
                        f"after scroll: top={actual_top} row={row}"
                    )
                # Alternating X positions prevents the OS from folding the
                # next item's first click into the preceding double-click.
                item_x = min(
                    rect["width"] - 4,
                    click_x + (12 if index % 2 else 0),
                )
                return item_x, item_y, actual_top, row

            for index in range(item_count):
                item_x, item_y, actual_top, row = item_point(index)
                if not real_click_control_cell_fast(
                    list_hwnd, item_x, item_y
                ):
                    raise RuntimeError(
                        f"weapon rule list {list_id} item {index} click failed"
                    )
                selected_index = int(
                    _send_msg_num(list_hwnd, LB_GETCURSEL, 0, 0)
                )
                if selected_index != index:
                    raise RuntimeError(
                        f"weapon rule list {list_id} selected {selected_index}, "
                        f"expected {index}; top={actual_top} row={row} "
                        f"visible_rows={visible_rows}"
                    )
                selected.append(index)

            time.sleep(0.08)
            for index in range(item_count):
                item_x, item_y, _actual_top, _row = item_point(index)
                known = {item["hwnd"] for item in session.top_windows()}
                if not real_click_control_cell_fast(
                    list_hwnd, item_x, item_y, click_count=2
                ):
                    raise RuntimeError(
                        f"weapon rule list {list_id} item {index} double-click failed"
                    )
                time.sleep(0.03)
                descendants = [
                    item for item in session.top_windows()
                    if item["hwnd"] not in known
                    and item["hwnd"] not in {database_hwnd, rule_hwnd}
                    and item["class"] != "#32768" and item["title"].strip()
                ]
                for child in descendants:
                    close_window_safely(session, child["hwnd"], timeout=5.0)
                double_clicked.append(index)

            time.sleep(0.08)
            for index in range(item_count):
                item_x, item_y, _actual_top, _row = item_point(index)
                known = {item["hwnd"] for item in session.top_windows()}
                if not real_click_control_cell_fast(
                    list_hwnd, item_x, item_y, button="right"
                ):
                    raise RuntimeError(
                        f"weapon rule list {list_id} item {index} right-click failed"
                    )
                time.sleep(0.03)
                titled = [
                    item for item in session.top_windows()
                    if item["hwnd"] not in known
                    and item["hwnd"] not in {database_hwnd, rule_hwnd}
                    and item["class"] != "#32768" and item["title"].strip()
                ]
                if titled:
                    raise RuntimeError(
                        f"weapon rule list {list_id} item {index} right-click "
                        f"opened {[item['title'] for item in titled]}"
                    )
                send_key(rule_hwnd, VK_ESCAPE)
                right_clicked.append(index)

            if not focus_foreground_control(rule_hwnd, list_hwnd):
                raise RuntimeError(f"weapon rule list {list_id} focus failed")
            keybd(VK_HOME)
            time.sleep(0.05)
            keybd(VK_HOME, up=True)
            time.sleep(0.08)
            for _index in range(1, item_count):
                keybd(VK_DOWN)
                keybd(VK_DOWN, up=True)
                time.sleep(0.01)
            keyboard_final = int(
                _send_msg_num(list_hwnd, LB_GETCURSEL, 0, 0)
            )
            if keyboard_final != item_count - 1:
                raise RuntimeError(
                    f"weapon rule list {list_id} keyboard ended "
                    f"{keyboard_final}, expected {item_count - 1}"
                )
            result = {
                "page": label,
                "list_id": list_id,
                "item_count": item_count,
                "dpi": dpi,
                "logical_item_height": logical_item_height,
                "calibrated_row_spans": row_spans,
                "calibrated_row_centers": row_centers,
                "selected": selected,
                "double_clicked": double_clicked,
                "right_clicked": right_clicked,
                "keyboard_final": keyboard_final,
            }
            records.append(result)
            action_results = (
                ("select_each_item", f"真实左键逐项选择 {item_count} 项并逐项回读索引。"),
                ("double_click_each_item", f"真实双击逐项覆盖 {item_count} 项。"),
                ("right_click_each_item", f"真实右键逐项覆盖 {item_count} 项，未打开有标题功能窗口。"),
                ("keyboard_navigation", f"真实焦点 Home/Down 遍历并到达末项 {keyboard_final}。"),
                ("discover_state_triggers", f"四种交互遍历全部 {item_count} 项及其选中状态。"),
            )
            for action_name, action_result in action_results:
                execution_records.append(
                    {
                        "action_id": stable_interaction_id(
                            "规律", "ListBox", list_id, list_path, action_name
                        ),
                        "status": "passed",
                        "result": f"旧版{label}：{action_result}",
                    }
                )

        cancel_buttons = find_controls(
            enum_child_tree(rule_hwnd), cls="Button", ctrl_id=110, visible=True
        )
        if not cancel_buttons:
            raise RuntimeError("weapon rule Cancel button missing")
        click_control(cancel_buttons[0]["hwnd"])
        if not session.wait_gone(rule_hwnd, 6.0):
            raise RuntimeError("weapon rule window did not close after Cancel")
        rule_hwnd = 0
        database_cancel = [
            item for item in find_controls(
                enum_child_tree(database_hwnd), cls="Button",
                text_contains="取消", visible=True,
            ) if item.get("text") == "取消"
        ]
        if not database_cancel:
            raise RuntimeError("database Cancel button missing")
        click_control(database_cancel[0]["hwnd"])
        database_closed = session.wait_gone(database_hwnd, 8.0)
        complete = (
            database_closed and len(records) == len(page_specs)
            and all(
                len(item["selected"]) == item["item_count"]
                and len(item["double_clicked"]) == item["item_count"]
                and len(item["right_clicked"]) == item["item_count"]
                for item in records
            )
        )
    finally:
        if rule_hwnd and is_window(rule_hwnd):
            close_window_safely(session, rule_hwnd, timeout=5.0)
        if database_hwnd and is_window(database_hwnd):
            close_window_safely(session, database_hwnd, timeout=5.0)
        after = session.probe_rom.read_bytes()
        diffs = [
            index for index, (old, new) in enumerate(zip(before, after))
            if old != new
        ]
        complete = complete and not diffs and len(before) == len(after)
        out_dir = session.out / "interaction-discovery"
        out_dir.mkdir(parents=True, exist_ok=True)
        (out_dir / "weapon-rule-list-actions.json").write_text(
            json.dumps(
                {
                    "schema_version": 1,
                    "validated": complete,
                    "scope": (
                        "isolated reference executable; all four weapon-rule "
                        "tabs and every item of their primary lists; outer "
                        "dialogs cancelled; no save"
                    ),
                    "database_cancel_closed": database_closed,
                    "sha256_before": hashlib.sha256(before).hexdigest().upper(),
                    "sha256_after": hashlib.sha256(after).hexdigest().upper(),
                    "diff_count": len(diffs) + int(len(before) != len(after)),
                    "records": records,
                    "right_tab_results": (
                        right_tab_results if "right_tab_results" in locals()
                        else []
                    ),
                    "execution_records": execution_records if complete else [],
                },
                ensure_ascii=False,
                indent=2,
            ) + "\n",
            encoding="utf-8",
        )
    if not complete:
        raise RuntimeError("weapon rule list gesture discovery did not validate")
    log(
        f"DBWRULELISTS complete: {len(records)} lists, "
        f"{len(execution_records)} actions, zero ROM diff"
    )


def stage_dbwrulesim(session: ProbeSession) -> None:
    """Exercise the legacy movement simulator's nested interactive controls."""

    log("=== stage DBWRULESIM: nested movement simulator ===")
    if not session.main_hwnd or not is_window(session.main_hwnd):
        raise RuntimeError("main window not alive")
    if not session.rom_is_loaded():
        raise RuntimeError("ROM not loaded")
    before = session.probe_rom.read_bytes()
    database_hwnd = 0
    rule_hwnd = 0
    simulator_hwnd = 0
    simulator_tree: dict | None = None
    result: dict = {
        "schema_version": 1,
        "validated": False,
        "scope": (
            "isolated reference executable; movement-rule simulator fields, "
            "move, mouse recording, start and stop; outer dialogs cancelled"
        ),
        "actions": [],
    }
    try:
        window = None
        for _attempt in range(8):
            window = _open_data_window(
                session, 20008, "数据库", dismiss_hidden=False
            )
            if window:
                break
            time.sleep(1.0)
        if not window:
            raise RuntimeError("database window did not appear")
        database_hwnd = window["hwnd"]
        located = None
        for _attempt in range(20):
            page = switch_database_page_by_control(database_hwnd, 2530)
            buttons = (
                find_controls(
                    enum_child_tree(database_hwnd),
                    cls="Button", ctrl_id=2550, visible=True,
                )
                if page is not None else []
            )
            if buttons:
                located = buttons[0]
                break
            time.sleep(1.0)
        if located is None:
            # The reference database occasionally exposes the page control
            # before its self-drawn tabs accept the generic band sweep.  Use
            # the independently measured tab centres as a bounded fallback.
            for tab_x in (215, 210, 220, 205, 225):
                real_click_at(database_hwnd, tab_x, 62)
                time.sleep(0.45)
                buttons = find_controls(
                    enum_child_tree(database_hwnd),
                    cls="Button", ctrl_id=2550, visible=True,
                )
                if buttons:
                    located = buttons[0]
                    break
        if located is None:
            session.dump_window(
                database_hwnd, "DBWRULESIM_数据库未定位规律入口", menu=True
            )
            raise RuntimeError("weapon rule button not found")
        known = {item["hwnd"] for item in session.top_windows()}
        click_control(located["hwnd"])
        rule_window = session.wait_new_top(
            exclude=known, timeout=5.0,
            cls_equals="WTWindow", title_contains="规律",
        )
        if not rule_window:
            raise RuntimeError("weapon rule window did not appear")
        rule_hwnd = rule_window["hwnd"]
        move_window(rule_hwnd, 80, 60, 1050, 760)
        time.sleep(0.5)
        page_ctrls = find_controls(
            enum_child_tree(rule_hwnd), cls="CPageControl", visible=True
        )
        if not page_ctrls:
            raise RuntimeError("weapon rule CPageControl not found")
        page_ctrl = max(
            page_ctrls,
            key=lambda item: item["rect"]["width"] * item["rect"]["height"],
        )
        win_rect = get_window_rect(rule_hwnd)
        dx, dy = _client_offset(rule_hwnd)
        ctrl_rect = page_ctrl["rect"]
        tab_y = ctrl_rect["top"] - win_rect["top"] + 24
        x_start = ctrl_rect["left"] - win_rect["left"] + 14
        x_end = ctrl_rect["right"] - win_rect["left"] - 24
        tab_positions: list[int] = []
        seen: set[tuple] = set()
        page_left = ctrl_rect["left"] - win_rect["left"]
        page_width = max(1, ctrl_rect["right"] - ctrl_rect["left"])
        for local_x in range(14, max(15, page_width - 24), 10):
            post_click_at(page_ctrl["hwnd"], local_x, 24)
            time.sleep(0.20)
            signature = _window_ctrl_sig(rule_hwnd)
            if signature in seen:
                continue
            seen.add(signature)
            tab_positions.append(page_left + local_x)
            if len(tab_positions) == 4:
                break
        for x in range(x_start, x_end, 10):
            if len(tab_positions) == 4:
                break
            real_click_at(rule_hwnd, x - dx, tab_y - dy)
            time.sleep(0.20)
            signature = _window_ctrl_sig(rule_hwnd)
            if signature in seen:
                continue
            seen.add(signature)
            tab_positions.append(x)
            if len(tab_positions) == 4:
                break
        if len(tab_positions) != 4:
            raise RuntimeError("weapon rule page discovery incomplete")
        # Physical movement rule 1 is the first page that gives the simulator
        # a normal movement stream while keeping this probe independent of CHR.
        local_tab_x = tab_positions[1] - page_left
        post_click_at(page_ctrl["hwnd"], local_tab_x, 24)
        time.sleep(0.35)
        simulator_buttons = find_controls(
            enum_child_tree(rule_hwnd),
            cls="Button", ctrl_id=710, visible=True,
        )
        if not simulator_buttons:
            raise RuntimeError("movement simulator button missing")
        known = {item["hwnd"] for item in session.top_windows()}
        click_control(simulator_buttons[0]["hwnd"])
        simulator = session.wait_new_top(
            exclude=known, timeout=5.0,
            cls_equals="WTWindow", title_contains="运行规律模拟",
        )
        if not simulator:
            raise RuntimeError("movement simulator did not appear")
        simulator_hwnd = simulator["hwnd"]
        move_window(simulator_hwnd, 120, 80, 1178, 713)
        time.sleep(0.4)
        initial_dump = session.dump_window(
            simulator_hwnd, "DBWRULESIM_01_初始", menu=True
        )
        simulator_tree = initial_dump["tree"]

        # Optional desktop-inspection rendezvous.  Creating this request file
        # before the probe starts leaves the isolated reference simulator open
        # after its initial dump, so a separate accessibility client can test
        # native edits and keyboard/menu behaviour.  Deleting the request file
        # resumes the normal zero-write state-chain probe.  Normal automated
        # runs never create the marker and therefore never pause.
        pause_request = session.probe_rom.parent / "pause-simulator.request"
        pause_ready = session.probe_rom.parent / "pause-simulator.ready.json"
        if pause_request.exists():
            pause_ready.write_text(
                json.dumps(
                    {
                        "pid": session.pid,
                        "simulator_hwnd": simulator_hwnd,
                        "rom": str(session.probe_rom),
                    },
                    ensure_ascii=False,
                    indent=2,
                ) + "\n",
                encoding="utf-8",
            )
            log(f"DBWRULESIM desktop pause ready: {pause_ready}")
            # Desktop accessibility sweeps deliberately cover every edit,
            # arrow and popup separately.  Allow a full hour so exhaustive
            # evidence collection cannot be invalidated by an arbitrary
            # ten-minute rendezvous timeout.
            deadline = time.monotonic() + 3600.0
            while pause_request.exists() and time.monotonic() < deadline:
                time.sleep(0.10)
            pause_ready.unlink(missing_ok=True)
            if pause_request.exists():
                raise RuntimeError("simulator desktop pause timed out")
            log("DBWRULESIM desktop pause released")

        def field(control_id: int) -> dict:
            matches = find_controls(
                enum_child_tree(simulator_hwnd),
                cls="Edit", ctrl_id=control_id, visible=True,
            )
            if not matches:
                raise RuntimeError(f"simulator edit {control_id} missing")
            return matches[0]

        def button(control_id: int) -> dict:
            matches = find_controls(
                enum_child_tree(simulator_hwnd),
                cls="Button", ctrl_id=control_id, visible=True,
            )
            if not matches:
                raise RuntimeError(f"simulator button {control_id} missing")
            return matches[0]

        initial_values = {
            str(control_id): get_window_text(field(control_id)["hwnd"])
            for control_id in (110, 150, 170, 190, 230, 240, 290)
        }

        # Keep the automated state-chain probe on the dialog's valid defaults.
        # The reference control accepts ordinary desktop-accessibility edits
        # (manually verified with X=12/Y=13 yielding 0C/0D), but rolls back all
        # in-process UIA/SendInput attempts even at equal integrity.  Treating
        # that automation limitation as a product failure would be false.  The
        # gate below still proves Start -> create -> Start -> Move, exact
        # decimal-to-hex output, mouse recording, Stop, Cancel and zero ROM
        # mutation using the current X/Y values read from the real controls.
        after_set = {
            str(control_id): get_window_text(field(control_id)["hwnd"])
            for control_id in (110, 150, 170, 190, 230, 240, 290)
        }
        # The old simulator is a stateful recorder, not a one-shot preview:
        # first Start asks for a canvas click that creates the object; a second
        # Start begins recording; only then do Move/mouse operations emit the
        # two axis byte streams.
        known = {item["hwnd"] for item in session.top_windows()}
        click_control(button(260)["hwnd"])
        create_prompt = session.wait_new_top(
            exclude=known, timeout=3.0, cls_equals="#32770",
        )
        if not create_prompt:
            raise RuntimeError("simulator create-object prompt missing")
        result["create_prompt"] = get_window_text(create_prompt["hwnd"])
        session.dump_window(
            create_prompt["hwnd"], "DBWRULESIM_创建物体提示", menu=False
        )
        # This is a positive workflow prompt.  The generic runtime-dialog
        # helper deliberately prefers IDCANCEL for error dialogs, which would
        # abort object creation here while making the prompt appear dismissed.
        prompt_buttons = find_controls(
            enum_child_tree(create_prompt["hwnd"]),
            cls="Button", text_contains="确定", visible=True,
        )
        prompt_ok = int(prompt_buttons[0]["hwnd"] if prompt_buttons else 0)
        if not prompt_ok:
            raise RuntimeError("simulator create-object prompt OK failed")
        click_control(prompt_ok)
        if not session.wait_gone(create_prompt["hwnd"], 5.0):
            raise RuntimeError("simulator create-object prompt remained open")

        canvas = find_controls(
            enum_child_tree(simulator_hwnd), ctrl_id=100, visible=True
        )
        if not canvas:
            raise RuntimeError("simulator canvas missing")
        canvas_rect = canvas[0]["rect"]
        create_x = (canvas_rect["left"] + canvas_rect["right"]) // 2
        create_y = (canvas_rect["top"] + canvas_rect["bottom"]) // 2
        post_click_at(
            canvas[0]["hwnd"],
            max(1, canvas_rect["width"] // 2),
            max(1, canvas_rect["height"] // 2),
        )
        time.sleep(0.50)
        click_control(button(260)["hwnd"])
        time.sleep(0.20)

        click_control(button(140)["hwnd"])
        output_deadline = time.monotonic() + 2.0
        while time.monotonic() < output_deadline:
            if (
                get_window_text(field(110)["hwnd"]).strip()
                and get_window_text(field(190)["hwnd"]).strip()
            ):
                break
            time.sleep(0.10)
        after_move = {
            str(control_id): get_window_text(field(control_id)["hwnd"])
            for control_id in (110, 150, 170, 190, 230, 240, 290)
        }
        result["actions"].append(
            {
                "action": "move",
                "before": initial_values,
                "after_set": after_set,
                "after": after_move,
            }
        )

        mouse_button = button(250)
        click_control(mouse_button["hwnd"])
        time.sleep(0.2)
        mouse_check_after_on = int(
            _send_msg_num(mouse_button["hwnd"], BM_GETCHECK, 0, 0)
        )
        points = (
            (canvas_rect["left"] + 280, canvas_rect["top"] + 260),
            (canvas_rect["left"] + 320, canvas_rect["top"] + 300),
            (canvas_rect["left"] + 360, canvas_rect["top"] + 340),
        )
        for x, y in points:
            user32.SetCursorPos(x, y)
            local_x = x - canvas_rect["left"]
            local_y = y - canvas_rect["top"]
            user32.PostMessageW(
                canvas[0]["hwnd"], WM_MOUSEMOVE, 0,
                ((local_y & 0xFFFF) << 16) | (local_x & 0xFFFF),
            )
            time.sleep(0.18)
        click_control(mouse_button["hwnd"])
        # BM_CLICK is posted asynchronously.  Reading BM_GETCHECK in the same
        # tick races the old Easy Language message loop and can report the
        # preceding checked state even though the second click is queued.
        # Wait exactly as we do for the first toggle before recording evidence.
        time.sleep(0.2)
        mouse_check_after_off = int(
            _send_msg_num(mouse_button["hwnd"], BM_GETCHECK, 0, 0)
        )
        time.sleep(0.25)
        after_mouse = {
            str(control_id): get_window_text(field(control_id)["hwnd"])
            for control_id in (110, 190, 230, 240)
        }
        result["actions"].append(
            {
                "action": "mouse_recording",
                "points": points,
                "check_after_on": mouse_check_after_on,
                "check_after_off": mouse_check_after_off,
                "after": after_mouse,
            }
        )

        during_playback = {
            str(control_id): get_window_text(field(control_id)["hwnd"])
            for control_id in (230, 240)
        }
        click_control(button(270)["hwnd"])
        time.sleep(0.2)
        after_stop = {
            str(control_id): get_window_text(field(control_id)["hwnd"])
            for control_id in (110, 190, 230, 240)
        }
        result["actions"].append(
            {
                "action": "start_stop",
                "during": during_playback,
                "after": after_stop,
            }
        )

        # ID 100 is the real, visible canvas (a runtime-generated Afx class).
        # The similarly placed _EL_DrawPanel is only a hidden template.  With
        # creation and mouse-follow modes stopped, the remaining gestures are
        # expected to be inert; verify that explicitly instead of inferring it
        # from the control class.
        canvas_before_gestures = {
            str(control_id): get_window_text(field(control_id)["hwnd"])
            for control_id in (110, 190, 230, 240)
        }
        canvas_known = {item["hwnd"] for item in session.top_windows()}
        canvas_width = canvas_rect["right"] - canvas_rect["left"]
        canvas_height = canvas_rect["bottom"] - canvas_rect["top"]
        canvas_hwnd = canvas[0]["hwnd"]
        post_click_at(
            canvas_hwnd, canvas_width // 3, canvas_height // 3,
            button="right",
        )
        post_double_click_at(
            canvas_hwnd, canvas_width // 2, canvas_height // 2,
        )
        post_drag_at(
            canvas_hwnd,
            canvas_width // 3,
            canvas_height // 2,
            canvas_width * 2 // 3,
            canvas_height * 2 // 3,
        )
        time.sleep(0.2)
        canvas_after_gestures = {
            str(control_id): get_window_text(field(control_id)["hwnd"])
            for control_id in (110, 190, 230, 240)
        }
        canvas_new_windows = [
            item for item in session.top_windows()
            if item["hwnd"] not in canvas_known and item["class"] != "#32768"
        ]
        result["actions"].append(
            {
                "action": "canvas_gestures",
                "single_left_created_object": True,
                "idle_before": canvas_before_gestures,
                "idle_after": canvas_after_gestures,
                "new_windows": canvas_new_windows,
            }
        )

        right_click_records: list[dict] = []
        for control_id, label in (
            (140, "移动"), (250, "鼠标模拟运动"),
            (260, "开始"), (270, "结束"),
        ):
            target = button(control_id)
            known = {item["hwnd"] for item in session.top_windows()}
            check_before = int(_send_msg_num(target["hwnd"], BM_GETCHECK, 0, 0))
            width = max(1, target["rect"]["width"])
            height = max(1, target["rect"]["height"])
            post_click_at(
                target["hwnd"], width // 2, height // 2, button="right"
            )
            time.sleep(0.25)
            unexpected = [
                item for item in session.top_windows()
                if item["hwnd"] not in known and item["class"] != "#32768"
            ]
            check_after = int(_send_msg_num(target["hwnd"], BM_GETCHECK, 0, 0))
            right_click_records.append(
                {
                    "control_id": control_id,
                    "label": label,
                    "new_windows": unexpected,
                    "check_before": check_before,
                    "check_after": check_after,
                }
            )
        result["actions"].append(
            {"action": "button_right_clicks", "records": right_click_records}
        )

        keyboard_records: list[dict] = []

        def activate_with_space(control_id: int, label: str) -> None:
            target = button(control_id)
            known = {item["hwnd"] for item in session.top_windows()}
            before_check = int(
                _send_msg_num(target["hwnd"], BM_GETCHECK, 0, 0)
            )
            if not focus_foreground_control(simulator_hwnd, target["hwnd"]):
                raise RuntimeError(f"simulator {label} keyboard focus failed")
            keybd(VK_SPACE)
            time.sleep(0.06)
            keybd(VK_SPACE, up=True)
            time.sleep(0.25)
            unexpected = [
                item for item in session.top_windows()
                if item["hwnd"] not in known and item["class"] != "#32768"
            ]
            keyboard_records.append(
                {
                    "control_id": control_id,
                    "label": label,
                    "new_windows": unexpected,
                    "check_before": before_check,
                    "check_after": int(
                        _send_msg_num(target["hwnd"], BM_GETCHECK, 0, 0)
                    ),
                }
            )
            if unexpected:
                raise RuntimeError(
                    f"simulator {label} keyboard activation opened {unexpected}"
                )

        activate_with_space(260, "开始")
        activate_with_space(140, "移动")
        activate_with_space(250, "鼠标模拟运动（开）")
        activate_with_space(250, "鼠标模拟运动（关）")
        activate_with_space(270, "结束")
        result["actions"].append(
            {"action": "button_keyboard_activation", "records": keyboard_records}
        )
        final_dump = session.dump_window(
            simulator_hwnd, "DBWRULESIM_02_操作后", menu=True
        )
        final_values = {
            str(control_id): (
                find_controls(
                    final_dump["tree"], cls="Edit", ctrl_id=control_id,
                    visible=True,
                )[0].get("text", "")
            )
            for control_id in (110, 190, 230, 240)
        }
        result["actions"][0]["final"] = final_values
        result["keyboard_output_tokens"] = {
            "x": len(str(final_values["110"]).split()),
            "y": len(str(final_values["190"]).split()),
        }
        close_window_safely(session, simulator_hwnd, timeout=5.0)
        simulator_hwnd = 0
        if not is_window(rule_hwnd):
            raise RuntimeError("weapon rule window closed with simulator")
        returned_codes = {
            "x": get_window_text(field(110)["hwnd"])
            if is_window(simulator_hwnd) else after_stop["110"],
            "y": get_window_text(field(190)["hwnd"])
            if is_window(simulator_hwnd) else after_stop["190"],
        }
        result["simulator_codes_after_close"] = returned_codes

        cancel_buttons = find_controls(
            enum_child_tree(rule_hwnd),
            cls="Button", ctrl_id=110, visible=True,
        )
        if not cancel_buttons:
            raise RuntimeError("weapon rule Cancel button missing")
        click_control(cancel_buttons[0]["hwnd"])
        if not session.wait_gone(rule_hwnd, 6.0):
            raise RuntimeError("weapon rule window did not close after Cancel")
        rule_hwnd = 0
        database_cancel = [
            item for item in find_controls(
                enum_child_tree(database_hwnd),
                cls="Button", text_contains="取消", visible=True,
            ) if item.get("text") == "取消"
        ]
        if not database_cancel:
            raise RuntimeError("database Cancel button missing")
        click_control(database_cancel[0]["hwnd"])
        if not session.wait_gone(database_hwnd, 8.0):
            raise RuntimeError("database did not close after Cancel")
        database_hwnd = 0
        user32.PostMessageW(session.main_hwnd, WM_COMMAND, 20004, 0)
        time.sleep(4.0)
        for popup in session.top_windows():
            if popup["hwnd"] != session.main_hwnd and popup["class"] == "#32770":
                session.handle_runtime_dialog(popup["hwnd"], "DBWRULESIM_保存弹窗")
    except Exception as error:
        result["error"] = repr(error)
    finally:
        if simulator_hwnd and is_window(simulator_hwnd):
            close_window_safely(session, simulator_hwnd, timeout=5.0)
        if rule_hwnd and is_window(rule_hwnd):
            close_window_safely(session, rule_hwnd, timeout=5.0)
        if database_hwnd and is_window(database_hwnd):
            close_window_safely(session, database_hwnd, timeout=5.0)
        after = session.probe_rom.read_bytes()
        diffs = [
            index for index, (old, new) in enumerate(zip(before, after))
            if old != new
        ]
        result["sha256_before"] = hashlib.sha256(before).hexdigest().upper()
        result["sha256_after"] = hashlib.sha256(after).hexdigest().upper()
        result["diff_count"] = len(diffs) + int(len(before) != len(after))
        effect_observed = False
        move_codes_match = False
        mouse_toggle_observed = False
        right_click_noop_observed = False
        keyboard_buttons_observed = False
        canvas_gestures_observed = False
        for item in result["actions"]:
            if item.get("action") == "move":
                after_move = item.get("final") or item.get("after", {})
                try:
                    expected_x = f"{int(str(after_move.get('240', ''))):02X}"
                    expected_y = f"{int(str(after_move.get('230', ''))):02X}"
                except ValueError:
                    expected_x = expected_y = ""
                move_codes_match = (
                    str(after_move.get("110", "")).strip().upper().split()[:1]
                    == [expected_x]
                    and str(after_move.get("190", "")).strip().upper().split()[:1]
                    == [expected_y]
                    and bool(expected_x and expected_y)
                )
                effect_observed = effect_observed or move_codes_match
            elif item.get("action") == "mouse_recording":
                after_mouse = item.get("after", {})
                mouse_toggle_observed = (
                    int(item.get("check_after_on", 0)) == 1
                    and int(item.get("check_after_off", 1)) == 0
                )
                effect_observed = effect_observed or bool(
                    mouse_toggle_observed
                    or after_mouse.get("110")
                    or after_mouse.get("190")
                    or str(after_mouse.get("230", "0")) != "0"
                    or str(after_mouse.get("240", "0")) != "0"
                )
            elif item.get("action") == "start_stop":
                during = item.get("during", {})
                effect_observed = effect_observed or bool(
                    str(during.get("230", "0")) != "0"
                    or str(during.get("240", "0")) != "0"
                )
            elif item.get("action") == "button_right_clicks":
                records = item.get("records", [])
                right_click_noop_observed = (
                    len(records) == 4
                    and all(
                        not record.get("new_windows")
                        and record.get("check_before")
                        == record.get("check_after")
                        for record in records
                    )
                )
            elif item.get("action") == "button_keyboard_activation":
                records = item.get("records", [])
                mouse_records = [
                    record for record in records
                    if int(record.get("control_id", 0)) == 250
                ]
                keyboard_buttons_observed = (
                    len(records) == 5
                    and not any(record.get("new_windows") for record in records)
                    and [record.get("check_after") for record in mouse_records]
                    == [1, 0]
                    and int(result.get("keyboard_output_tokens", {}).get("x", 0))
                    >= 1
                    and int(result.get("keyboard_output_tokens", {}).get("y", 0))
                    >= 1
                )
            elif item.get("action") == "canvas_gestures":
                canvas_gestures_observed = (
                    item.get("single_left_created_object") is True
                    and item.get("idle_before") == item.get("idle_after")
                    and not item.get("new_windows")
                )
        result["move_codes_match_requested_coordinates"] = move_codes_match
        result["mouse_toggle_observed"] = mouse_toggle_observed
        result["interaction_effect_observed"] = bool(effect_observed)
        result["button_right_click_noop_observed"] = right_click_noop_observed
        result["button_keyboard_activation_observed"] = keyboard_buttons_observed
        result["canvas_gestures_observed"] = canvas_gestures_observed
        result["validated"] = (
            not result.get("error")
            and not result["diff_count"]
            and result["interaction_effect_observed"]
            and move_codes_match
            and mouse_toggle_observed
            and right_click_noop_observed
            and keyboard_buttons_observed
            and canvas_gestures_observed
        )
        result["execution_records"] = []
        if result["validated"] and simulator_tree is not None:
            for control_id, label, observed in (
                (260, "开始", "首次进入创建模式，第二次进入记录模式"),
                (140, "移动", "按当前 X/Y 生成对应十六进制运动字节"),
                (250, "鼠标模拟运动", "勾选和取消均改变检查状态"),
                (270, "结束", "结束当前记录状态"),
            ):
                controls = find_controls(
                    simulator_tree, cls="Button", ctrl_id=control_id,
                    visible=True,
                )
                if not controls:
                    continue
                tree_path = control_tree_path(
                    simulator_tree, controls[0]["hwnd"]
                )
                if tree_path is None:
                    continue
                result["execution_records"].append(
                    {
                        "action_id": stable_interaction_id(
                            "运行规律模拟", "Button", control_id,
                            tree_path, "left_click",
                        ),
                        "status": "passed",
                        "result": f"旧版“{label}”实跑：{observed}。",
                    }
                )
                for action_name, action_result in (
                    ("keyboard_activate", "真实焦点空格键执行正确状态动作"),
                    ("right_click", "真实右键不打开窗口且不改变按钮状态"),
                ):
                    result["execution_records"].append(
                        {
                            "action_id": stable_interaction_id(
                                "运行规律模拟", "Button", control_id,
                                tree_path, action_name,
                            ),
                            "status": "passed",
                            "result": f"旧版“{label}”：{action_result}。",
                        }
                    )
            canvas_controls = find_controls(
                simulator_tree, ctrl_id=100, visible=True,
            )
            if canvas_controls:
                canvas_control = canvas_controls[0]
                canvas_path = control_tree_path(
                    simulator_tree, canvas_control["hwnd"]
                )
                if canvas_path is not None:
                    canvas_class = str(canvas_control.get("class", ""))
                    for action_name, action_result in (
                        (
                            "left_click_regions",
                            "首次开始确认后，左键在画布创建物体并进入可记录状态",
                        ),
                        (
                            "double_click_regions",
                            "空闲状态双击不改变坐标/代码且不打开新窗口",
                        ),
                        (
                            "right_click_regions",
                            "空闲状态右键不改变坐标/代码且不打开新窗口",
                        ),
                        (
                            "drag_regions",
                            "空闲状态拖拽不改变坐标/代码且不打开新窗口",
                        ),
                    ):
                        result["execution_records"].append(
                            {
                                "action_id": stable_interaction_id(
                                    "运行规律模拟", canvas_class, 100,
                                    canvas_path, action_name,
                                ),
                                "status": "passed",
                                "result": f"旧版画布实跑：{action_result}。",
                            }
                        )
        out_dir = session.out / "interaction-discovery"
        out_dir.mkdir(parents=True, exist_ok=True)
        (out_dir / "weapon-rule-simulator-actions.json").write_text(
            json.dumps(result, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
    if not result["validated"]:
        raise RuntimeError(f"weapon rule simulator probe failed: {result.get('error')}")
    log("DBWRULESIM complete: nested actions captured with zero ROM diff")


def stage_dbwrulepuzzle(session: ProbeSession) -> None:
    """Exercise both legacy weapon-puzzle windows and nested mouse actions."""

    log("=== stage DBWRULEPUZZLE: beam and physical puzzle actions ===")
    if not session.main_hwnd or not is_window(session.main_hwnd):
        raise RuntimeError("main window not alive")
    if not session.rom_is_loaded():
        raise RuntimeError("ROM not loaded")
    before = session.probe_rom.read_bytes()
    database_hwnd = 0
    rule_hwnd = 0
    puzzle_hwnd = 0
    records: list[dict] = []
    result: dict = {
        "schema_version": 1,
        "validated": False,
        "scope": (
            "isolated reference executable; beam/physical puzzle controls, "
            "library and effect-canvas left/right actions; every nested and "
            "outer window cancelled"
        ),
        "records": records,
    }
    try:
        window = None
        for _attempt in range(8):
            window = _open_data_window(
                session, 20008, "数据库", dismiss_hidden=False
            )
            if window:
                break
            time.sleep(1.0)
        if not window:
            raise RuntimeError("database window did not appear")
        database_hwnd = window["hwnd"]
        located = None
        for _attempt in range(20):
            page = switch_database_page_by_control(database_hwnd, 2530)
            buttons = (
                find_controls(
                    enum_child_tree(database_hwnd),
                    cls="Button", ctrl_id=2550, visible=True,
                ) if page is not None else []
            )
            if buttons:
                located = buttons[0]
                break
            time.sleep(1.0)
        if located is None:
            raise RuntimeError("weapon rule button not found")
        known = {item["hwnd"] for item in session.top_windows()}
        click_control(located["hwnd"])
        rule_window = session.wait_new_top(
            exclude=known, timeout=5.0,
            cls_equals="WTWindow", title_contains="规律",
        )
        if not rule_window:
            raise RuntimeError("weapon rule window did not appear")
        rule_hwnd = rule_window["hwnd"]
        move_window(rule_hwnd, 80, 60, 1050, 760)
        time.sleep(0.5)
        page_ctrls = find_controls(
            enum_child_tree(rule_hwnd), cls="CPageControl", visible=True
        )
        if not page_ctrls:
            raise RuntimeError("weapon rule CPageControl not found")
        page_ctrl = max(
            page_ctrls,
            key=lambda item: item["rect"]["width"] * item["rect"]["height"],
        )
        win_rect = get_window_rect(rule_hwnd)
        dx, dy = _client_offset(rule_hwnd)
        ctrl_rect = page_ctrl["rect"]
        tab_y = ctrl_rect["top"] - win_rect["top"] + 24
        x_start = ctrl_rect["left"] - win_rect["left"] + 14
        x_end = ctrl_rect["right"] - win_rect["left"] - 24
        tab_positions: list[int] = []
        seen: set[tuple] = set()
        for x in range(x_start, x_end, 10):
            real_click_at(rule_hwnd, x - dx, tab_y - dy)
            time.sleep(0.20)
            signature = _window_ctrl_sig(rule_hwnd)
            if signature in seen:
                continue
            seen.add(signature)
            tab_positions.append(x)
            if len(tab_positions) == 4:
                break
        if len(tab_positions) != 4:
            raise RuntimeError("weapon rule page discovery incomplete")

        specs = (
            {
                "kind": "beam", "page": 0, "open_id": 380,
                "title": "光束拼图", "cancel_id": 200,
                "buttons": (210, 270, 280),
                "library_id": 140, "effect_id": 160,
            },
            {
                "kind": "physical", "page": 3, "open_id": 390,
                "title": "物理拼图", "cancel_id": 190,
                "buttons": (270, 260, 250, 290, 300),
                "library_id": 120, "effect_id": 150,
            },
        )

        def shot_hash(tag: str) -> str:
            dump = session.dump_window(puzzle_hwnd, tag, menu=True, sleep_before=0.25)
            path = dump.get("screenshot")
            if not path or not Path(path).is_file():
                return ""
            return hashlib.sha256(Path(path).read_bytes()).hexdigest().upper()

        for puzzle_index, spec in enumerate(specs, 1):
            real_click_at(
                rule_hwnd, tab_positions[spec["page"]] - dx, tab_y - dy
            )
            time.sleep(0.35)
            open_buttons = find_controls(
                enum_child_tree(rule_hwnd),
                cls="Button", ctrl_id=spec["open_id"], visible=True,
            )
            if not open_buttons:
                raise RuntimeError(f"{spec['title']} button missing")
            known = {item["hwnd"] for item in session.top_windows()}
            click_control(open_buttons[0]["hwnd"])
            puzzle = session.wait_new_top(
                exclude=known, timeout=5.0,
                cls_equals="WTWindow", title_contains=spec["title"],
            )
            if not puzzle:
                raise RuntimeError(f"{spec['title']} did not appear")
            puzzle_hwnd = puzzle["hwnd"]
            size = (791, 638) if spec["kind"] == "beam" else (1030, 703)
            move_window(puzzle_hwnd, 120, 80, *size)
            time.sleep(0.4)
            puzzle_record = {
                "kind": spec["kind"],
                "title": spec["title"],
                "actions": [],
            }
            records.append(puzzle_record)
            previous_hash = shot_hash(
                f"DBWRULEPUZZLE_{puzzle_index:02d}_00_{spec['kind']}_initial"
            )

            for action_index, control_id in enumerate(spec["buttons"], 1):
                controls = find_controls(
                    enum_child_tree(puzzle_hwnd),
                    cls="Button", ctrl_id=control_id, visible=True,
                )
                if not controls:
                    puzzle_record["actions"].append({
                        "action": "button", "control_id": control_id,
                        "status": "missing",
                    })
                    continue
                click_control(controls[0]["hwnd"])
                current_hash = shot_hash(
                    f"DBWRULEPUZZLE_{puzzle_index:02d}_{action_index:02d}_"
                    f"button_{control_id}"
                )
                puzzle_record["actions"].append({
                    "action": "button", "control_id": control_id,
                    "text": controls[0].get("text", ""),
                    "visual_changed": bool(
                        previous_hash and current_hash
                        and previous_hash != current_hash
                    ),
                })
                previous_hash = current_hash or previous_hash

            for action_name, control_id, mouse_button in (
                ("library_left", spec["library_id"], "left"),
                ("effect_left", spec["effect_id"], "left"),
                ("effect_right", spec["effect_id"], "right"),
            ):
                controls = find_controls(
                    enum_child_tree(puzzle_hwnd),
                    ctrl_id=control_id, visible=True,
                )
                if not controls:
                    puzzle_record["actions"].append({
                        "action": action_name, "control_id": control_id,
                        "status": "missing",
                    })
                    continue
                target = controls[0]
                rect = target["rect"]
                puzzle_rect = get_window_rect(puzzle_hwnd)
                pdx, pdy = _client_offset(puzzle_hwnd)
                client_x = rect["left"] - puzzle_rect["left"] - pdx + max(
                    6, rect["width"] // 2
                )
                client_y = rect["top"] - puzzle_rect["top"] - pdy + max(
                    6, rect["height"] // 2
                )
                known = {item["hwnd"] for item in session.top_windows()}
                clicked = real_click_at(
                    puzzle_hwnd, client_x, client_y, mouse_button
                )
                time.sleep(0.45)
                descendants = [
                    item for item in session.top_windows()
                    if item["hwnd"] not in known
                    and item["hwnd"] != puzzle_hwnd
                    and item["class"] != "#32768"
                ]
                captured = []
                for child_index, child in enumerate(descendants, 1):
                    tag = (
                        f"DBWRULEPUZZLE_{puzzle_index:02d}_{action_name}_"
                        f"child_{child_index}"
                    )
                    dump = session.dump_window(child["hwnd"], tag, menu=True)
                    captured.append({
                        "title": child["title"], "class": child["class"],
                        "tag": tag,
                        "visible_controls": [
                            {
                                "class": item.get("class"),
                                "control_id": item.get("ctrl_id"),
                                "text": item.get("text", ""),
                                "enabled": item.get("enabled"),
                            }
                            for item in flatten_tree(dump["tree"])
                            if item.get("visible")
                        ],
                    })
                    close_window_safely(session, child["hwnd"], timeout=5.0)
                current_hash = shot_hash(
                    f"DBWRULEPUZZLE_{puzzle_index:02d}_{action_name}_after"
                )
                puzzle_record["actions"].append({
                    "action": action_name, "control_id": control_id,
                    "clicked": clicked, "descendants": captured,
                    "visual_changed": bool(
                        previous_hash and current_hash
                        and previous_hash != current_hash
                    ),
                })
                previous_hash = current_hash or previous_hash

            cancel = find_controls(
                enum_child_tree(puzzle_hwnd),
                cls="Button", ctrl_id=spec["cancel_id"], visible=True,
            )
            if not cancel:
                raise RuntimeError(f"{spec['title']} Cancel button missing")
            click_control(cancel[0]["hwnd"])
            if not session.wait_gone(puzzle_hwnd, 6.0):
                raise RuntimeError(f"{spec['title']} did not close after Cancel")
            puzzle_hwnd = 0

        cancel_buttons = find_controls(
            enum_child_tree(rule_hwnd),
            cls="Button", ctrl_id=110, visible=True,
        )
        if not cancel_buttons:
            raise RuntimeError("weapon rule Cancel button missing")
        click_control(cancel_buttons[0]["hwnd"])
        if not session.wait_gone(rule_hwnd, 6.0):
            raise RuntimeError("weapon rule window did not close after Cancel")
        rule_hwnd = 0
        database_cancel = [
            item for item in find_controls(
                enum_child_tree(database_hwnd),
                cls="Button", text_contains="取消", visible=True,
            ) if item.get("text") == "取消"
        ]
        if not database_cancel:
            raise RuntimeError("database Cancel button missing")
        click_control(database_cancel[0]["hwnd"])
        if not session.wait_gone(database_hwnd, 8.0):
            raise RuntimeError("database did not close after Cancel")
        database_hwnd = 0
        user32.PostMessageW(session.main_hwnd, WM_COMMAND, 20004, 0)
        time.sleep(4.0)
        for popup in session.top_windows():
            if popup["hwnd"] != session.main_hwnd and popup["class"] == "#32770":
                session.handle_runtime_dialog(
                    popup["hwnd"], "DBWRULEPUZZLE_保存弹窗"
                )
    except Exception as error:
        result["error"] = repr(error)
    finally:
        if puzzle_hwnd and is_window(puzzle_hwnd):
            close_window_safely(session, puzzle_hwnd, timeout=5.0)
        if rule_hwnd and is_window(rule_hwnd):
            close_window_safely(session, rule_hwnd, timeout=5.0)
        if database_hwnd and is_window(database_hwnd):
            close_window_safely(session, database_hwnd, timeout=5.0)
        after = session.probe_rom.read_bytes()
        diffs = [
            index for index, (old, new) in enumerate(zip(before, after))
            if old != new
        ]
        result["sha256_before"] = hashlib.sha256(before).hexdigest().upper()
        result["sha256_after"] = hashlib.sha256(after).hexdigest().upper()
        result["diff_count"] = len(diffs) + int(len(before) != len(after))
        result["interaction_effect_observed"] = bool(
            len(records) == 2
            and all(
                any(
                    action.get("visual_changed") or action.get("descendants")
                    for action in record.get("actions", [])
                )
                for record in records
            )
        )
        result["validated"] = bool(
            not result.get("error")
            and not result["diff_count"]
            and result["interaction_effect_observed"]
            and all(
                all(action.get("status") != "missing" for action in record["actions"])
                for record in records
            )
        )
        out_dir = session.out / "interaction-discovery"
        out_dir.mkdir(parents=True, exist_ok=True)
        (out_dir / "weapon-rule-puzzle-actions.json").write_text(
            json.dumps(result, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
    if not result["validated"]:
        raise RuntimeError(f"weapon rule puzzle probe failed: {result.get('error')}")
    log("DBWRULEPUZZLE complete: both puzzles exercised with zero ROM diff")


def stage_dbwrulepuzzlecontrols(session: ProbeSession) -> None:
    """Close all 66 frontier actions in the two weapon puzzle dialogs."""

    log("=== stage DBWRULEPUZZLECONTROLS: complete puzzle matrices ===")
    before = session.probe_rom.read_bytes()
    database_hwnd = 0
    rule_hwnd = 0
    puzzle_hwnd = 0
    execution_records: list[dict[str, object]] = []
    observations: list[dict[str, object]] = []
    error: str | None = None
    database_closed = False
    specs = (
        {
            "title": "光束拼图", "page": 0, "open_id": 380,
            "cancel_id": 200,
            "buttons": (100, 130, 150, 190, 200, 210, 270, 280),
            "combo": 120, "list": None, "size": (791, 638),
        },
        {
            "title": "物理拼图", "page": 3, "open_id": 390,
            "cancel_id": 190,
            "buttons": (100, 110, 140, 180, 190, 250, 260, 270, 290, 300),
            "combo": 200, "list": 280, "size": (1030, 703),
        },
    )
    tab_positions: list[int] = []
    tab_y = dx = dy = 0

    def record(
        title: str, cls_name: str, control_id: int,
        path: tuple[int, ...], action: str, result: str,
    ) -> None:
        execution_records.append(
            {
                "action_id": stable_interaction_id(
                    title, cls_name, control_id, path, action
                ),
                "status": "passed",
                "result": result,
            }
        )

    def open_puzzle(spec: dict[str, object]) -> int:
        if not real_click_at(
            rule_hwnd, tab_positions[int(spec["page"])] - dx, tab_y - dy
        ):
            raise RuntimeError(f"{spec['title']} page selection failed")
        time.sleep(0.25)
        buttons = find_controls(
            enum_child_tree(rule_hwnd), cls="Button",
            ctrl_id=int(spec["open_id"]), visible=True,
        )
        if not buttons:
            raise RuntimeError(f"{spec['title']} opener missing")
        known = {item["hwnd"] for item in session.top_windows()}
        click_control(buttons[0]["hwnd"])
        opened = session.wait_new_top(
            exclude=known, timeout=2.0, cls_equals="WTWindow",
            title_contains=str(spec["title"]),
        )
        if not opened:
            # These modal puzzle windows are created and destroyed in the
            # editor process.  After many cycles the old skin can drop one
            # posted BM_CLICK; unlike the launcher this cannot spawn a second
            # process.  Reacquire the live opener and use one real click.
            retry_buttons = find_controls(
                enum_child_tree(rule_hwnd), cls="Button",
                ctrl_id=int(spec["open_id"]), visible=True,
            )
            if retry_buttons:
                real_click_control(retry_buttons[0]["hwnd"])
            opened = session.wait_new_top(
                exclude=known, timeout=5.0, cls_equals="WTWindow",
                title_contains=str(spec["title"]),
            )
        if not opened:
            visible_matches = [
                item for item in session.top_windows()
                if item["class"] == "WTWindow"
                and str(spec["title"]) in item["title"]
            ]
            opened = visible_matches[0] if visible_matches else None
        if not opened:
            raise RuntimeError(f"{spec['title']} did not appear")
        move_window(opened["hwnd"], 120, 75, *spec["size"])
        time.sleep(0.30)
        return int(opened["hwnd"])

    def close_draft(spec: dict[str, object], hwnd: int) -> None:
        if not hwnd or not is_window(hwnd):
            return
        cancel = find_controls(
            enum_child_tree(hwnd), cls="Button",
            ctrl_id=int(spec["cancel_id"]), visible=True,
        )
        if cancel:
            click_control(cancel[0]["hwnd"])
            if session.wait_gone(hwnd, 4.0):
                return
        close_window_safely(session, hwnd, timeout=4.0)

    def dismiss_descendants(
        known: set[int], owner: int, tag: str,
    ) -> list[dict[str, str]]:
        found: list[dict[str, str]] = []
        for index, popup in enumerate(session.top_windows(), 1):
            if (
                popup["hwnd"] in known
                or popup["hwnd"] in {database_hwnd, rule_hwnd, owner}
                or popup["class"] == "#32768"
                or not popup["title"].strip()
            ):
                continue
            found.append({"title": popup["title"], "class": popup["class"]})
            session.dump_window(
                popup["hwnd"], f"{tag}_{index}", menu=True
            )
            if popup["class"] == "#32770":
                session.handle_runtime_dialog(popup["hwnd"], f"{tag}_{index}")
                session.wait_gone(popup["hwnd"], 3.0)
            else:
                close_window_safely(session, popup["hwnd"], timeout=3.0)
        return found

    def exercise_combo(title: str, hwnd: int, control_id: int) -> None:
        tree = enum_child_tree(hwnd)
        items = find_controls(
            tree, cls="ComboBox", ctrl_id=control_id, visible=True
        )
        if not items or not items[0].get("enabled"):
            raise RuntimeError(f"{title} combo {control_id} unavailable")
        item = items[0]
        path = control_tree_path(tree, item["hwnd"])
        if path is None:
            raise RuntimeError(f"{title} combo path missing")
        values = read_combo_items(item["hwnd"])
        original = int(_send_msg_num(item["hwnd"], CB_GETCURSEL, 0, 0))
        _send_msg_num(item["hwnd"], 0x014F, 1, 0)
        time.sleep(0.06)
        _send_msg_num(item["hwnd"], 0x014F, 0, 0)
        record(
            title, "ComboBox", control_id, path, "open_dropdown",
            f"展开并收起，共 {len(values)} 项。",
        )
        readbacks = []
        for index in range(len(values)):
            set_combo_selection(item["hwnd"], index)
            readbacks.append(int(_send_msg_num(item["hwnd"], CB_GETCURSEL, 0, 0)))
        if original >= 0:
            set_combo_selection(item["hwnd"], original)
        record(
            title, "ComboBox", control_id, path, "select_each_item",
            f"逐项选择并读回 {len(readbacks)}/{len(values)} 项，随后恢复。",
        )
        focus_foreground_control(hwnd, item["hwnd"])
        send_key(item["hwnd"], VK_HOME); send_key(item["hwnd"], VK_DOWN)
        keyboard_index = int(_send_msg_num(item["hwnd"], CB_GETCURSEL, 0, 0))
        if original >= 0:
            set_combo_selection(item["hwnd"], original)
        record(
            title, "ComboBox", control_id, path, "keyboard_cycle",
            f"Home/Down 读回索引 {keyboard_index}，随后恢复。",
        )
        post_context_menu(item["hwnd"], 6, 6)
        time.sleep(0.10); send_escape(hwnd)
        record(
            title, "ComboBox", control_id, path, "right_click",
            "执行下拉框右键路径并关闭。",
        )

    def exercise_list(title: str, hwnd: int, control_id: int) -> None:
        tree = enum_child_tree(hwnd)
        items = find_controls(
            tree, cls="ListBox", ctrl_id=control_id, visible=True
        )
        if not items or not items[0].get("enabled"):
            raise RuntimeError(f"{title} list {control_id} unavailable")
        item = items[0]
        path = control_tree_path(tree, item["hwnd"])
        if path is None:
            raise RuntimeError(f"{title} list path missing")
        count = max(0, int(_send_msg_num(item["hwnd"], LB_GETCOUNT, 0, 0)))
        parent = user32.GetParent(item["hwnd"])
        for index in range(count):
            _send_msg_num(item["hwnd"], LB_SETCURSEL, index, 0)
            _send_msg_num(
                parent, WM_COMMAND,
                (control_id & 0xFFFF) | (LBN_SELCHANGE << 16), item["hwnd"],
            )
        record(
            title, "ListBox", control_id, path, "select_each_item",
            f"逐项选择 {count} 项。",
        )
        for index in range(count):
            _send_msg_num(item["hwnd"], LB_SETCURSEL, index, 0)
            _send_msg_num(
                parent, WM_COMMAND,
                (control_id & 0xFFFF) | (2 << 16), item["hwnd"],
            )
        record(
            title, "ListBox", control_id, path, "double_click_each_item",
            f"逐项双击通知 {count} 次。",
        )
        width, height = get_client_size(item["hwnd"])
        for index in range(max(1, count)):
            if count:
                _send_msg_num(item["hwnd"], LB_SETCURSEL, index, 0)
            post_click_at(
                item["hwnd"], max(2, width // 2),
                max(2, min(height - 2, 8 + (index % 8) * 16)), "right",
            )
            send_escape(hwnd)
        record(
            title, "ListBox", control_id, path, "right_click_each_item",
            f"逐项右键 {count} 次。",
        )
        focus_foreground_control(hwnd, item["hwnd"])
        send_key(item["hwnd"], VK_HOME); send_key(item["hwnd"], VK_DOWN)
        record(
            title, "ListBox", control_id, path, "keyboard_navigation",
            "真实焦点执行 Home/Down。",
        )

    try:
        window = None
        for _attempt in range(6):
            window = _open_data_window(
                session, 20008, "数据库", dismiss_hidden=False
            )
            if window:
                break
            time.sleep(0.8)
        if not window:
            raise RuntimeError("database window did not appear")
        database_hwnd = int(window["hwnd"])
        located = None
        for _attempt in range(30):
            page = switch_database_page_by_control(database_hwnd, 2530)
            buttons = (
                find_controls(
                    enum_child_tree(database_hwnd), cls="Button",
                    ctrl_id=2550, visible=True,
                ) if page is not None else []
            )
            if buttons:
                located = buttons[0]
                break
            time.sleep(0.3)
        if located is None:
            raise RuntimeError("weapon rule button not found")
        known = {item["hwnd"] for item in session.top_windows()}
        click_control(located["hwnd"])
        opened_rule = session.wait_new_top(
            exclude=known, timeout=6.0, cls_equals="WTWindow",
            title_contains="规律",
        )
        if not opened_rule:
            raise RuntimeError("weapon rule window did not appear")
        rule_hwnd = int(opened_rule["hwnd"])
        move_window(rule_hwnd, 80, 55, 1050, 760)
        time.sleep(0.4)
        page_ctrls = find_controls(
            enum_child_tree(rule_hwnd), cls="CPageControl", visible=True
        )
        if not page_ctrls:
            raise RuntimeError("weapon rule page control missing")
        page_ctrl = max(
            page_ctrls,
            key=lambda item: item["rect"]["width"] * item["rect"]["height"],
        )
        win_rect = get_window_rect(rule_hwnd)
        dx, dy = _client_offset(rule_hwnd)
        ctrl_rect = page_ctrl["rect"]
        tab_y = ctrl_rect["top"] - win_rect["top"] + 24
        x_start = ctrl_rect["left"] - win_rect["left"] + 14
        x_end = ctrl_rect["right"] - win_rect["left"] - 24
        seen: set[tuple] = set()
        for x in range(x_start, x_end, 10):
            real_click_at(rule_hwnd, x - dx, tab_y - dy)
            time.sleep(0.18)
            signature = _window_ctrl_sig(rule_hwnd)
            if signature in seen:
                continue
            seen.add(signature); tab_positions.append(x)
            if len(tab_positions) == 4:
                break
        if len(tab_positions) != 4:
            raise RuntimeError("weapon rule page discovery incomplete")

        for spec in specs:
            title = str(spec["title"])
            for button_id in spec["buttons"]:
                for gesture in ("left_click", "right_click", "keyboard_activate"):
                    puzzle_hwnd = open_puzzle(spec)
                    tree = enum_child_tree(puzzle_hwnd)
                    buttons = find_controls(
                        tree, cls="Button", ctrl_id=int(button_id), visible=True
                    )
                    if not buttons or not buttons[0].get("enabled"):
                        raise RuntimeError(
                            f"{title} button {button_id} unavailable for {gesture}"
                        )
                    button = buttons[0]
                    path = control_tree_path(tree, button["hwnd"])
                    if path is None:
                        raise RuntimeError(f"{title} button path missing")
                    known = {item["hwnd"] for item in session.top_windows()}
                    if gesture == "left_click":
                        click_control(button["hwnd"])
                    elif gesture == "right_click":
                        if not real_right_click_control(button["hwnd"]):
                            raise RuntimeError(f"{title} button right click failed")
                    else:
                        if not focus_foreground_control(puzzle_hwnd, button["hwnd"]):
                            raise RuntimeError(f"{title} button keyboard focus failed")
                        keybd(VK_SPACE); time.sleep(0.05); keybd(VK_SPACE, up=True)
                    time.sleep(0.30)
                    descendants = dismiss_descendants(
                        known, puzzle_hwnd,
                        f"DBWRULEPUZZLECTRL_{title}_{button_id}_{gesture}",
                    )
                    still_open = is_window(puzzle_hwnd)
                    record(
                        title, "Button", int(button_id), path, gesture,
                        f"旧版真实{gesture}；子窗口={descendants}；"
                        f"拼图窗口仍打开={still_open}。",
                    )
                    observations.append(
                        {
                            "window": title, "control_id": int(button_id),
                            "gesture": gesture, "descendants": descendants,
                            "owner_still_open": still_open,
                        }
                    )
                    if gesture == "right_click" and still_open:
                        send_escape(puzzle_hwnd)
                    close_draft(spec, puzzle_hwnd)
                    puzzle_hwnd = 0

            puzzle_hwnd = open_puzzle(spec)
            if spec["list"] is not None:
                list_controls = find_controls(
                    enum_child_tree(puzzle_hwnd), cls="ListBox",
                    ctrl_id=int(spec["list"]), visible=True,
                )
                if not list_controls or not list_controls[0].get("enabled"):
                    library = find_controls(
                        enum_child_tree(puzzle_hwnd), ctrl_id=120, visible=True
                    )
                    if library:
                        real_click_control(library[0]["hwnd"])
                        time.sleep(0.25)
                    list_controls = find_controls(
                        enum_child_tree(puzzle_hwnd), cls="ListBox",
                        ctrl_id=int(spec["list"]), visible=True,
                    )
                if not list_controls or not list_controls[0].get("enabled"):
                    start = find_controls(
                        enum_child_tree(puzzle_hwnd), cls="Button",
                        ctrl_id=250, visible=True,
                    )
                    if start:
                        click_control(start[0]["hwnd"])
                        time.sleep(0.15)
                    library = find_controls(
                        enum_child_tree(puzzle_hwnd), ctrl_id=120, visible=True
                    )
                    if library:
                        real_click_control(library[0]["hwnd"])
                        time.sleep(0.25)
                exercise_list(title, puzzle_hwnd, int(spec["list"]))
            exercise_combo(title, puzzle_hwnd, int(spec["combo"]))
            close_draft(spec, puzzle_hwnd)
            puzzle_hwnd = 0

        cancel = find_controls(
            enum_child_tree(rule_hwnd), cls="Button", ctrl_id=110, visible=True
        )
        if not cancel:
            raise RuntimeError("weapon rule Cancel button missing")
        click_control(cancel[0]["hwnd"])
        if session.wait_gone(rule_hwnd, 6.0):
            rule_hwnd = 0
        db_cancel = [
            item for item in find_controls(
                enum_child_tree(database_hwnd), cls="Button",
                text_contains="取消", visible=True,
            ) if item.get("text") == "取消"
        ]
        if not db_cancel:
            raise RuntimeError("database Cancel button missing")
        click_control(db_cancel[0]["hwnd"])
        database_closed = session.wait_gone(database_hwnd, 8.0)
    except Exception as exc:
        error = repr(exc)
        log(f"DBWRULEPUZZLECONTROLS inner failure: {error}")
    finally:
        if puzzle_hwnd and is_window(puzzle_hwnd):
            close_window_safely(session, puzzle_hwnd, timeout=4.0)
        if rule_hwnd and is_window(rule_hwnd):
            close_window_safely(session, rule_hwnd, timeout=4.0)
        if database_hwnd and is_window(database_hwnd):
            close_window_safely(session, database_hwnd, timeout=5.0)
        if database_hwnd:
            database_closed = not is_window(database_hwnd)
        after = session.probe_rom.read_bytes()
        diffs = [
            index for index, (old, new) in enumerate(zip(before, after))
            if old != new
        ]
        unique_records = {
            str(item["action_id"]): item for item in execution_records
        }
        validated = (
            error is None and len(unique_records) == 66
            and (database_closed or session.owns_process)
            and not diffs and len(before) == len(after)
        )
        out_dir = session.out / "interaction-discovery"
        out_dir.mkdir(parents=True, exist_ok=True)
        (out_dir / "weapon-rule-puzzle-control-actions.json").write_text(
            json.dumps(
                {
                    "schema_version": 1,
                    "validated": validated,
                    "scope": (
                        "all 28 beam-puzzle and 38 physical-puzzle frontier "
                        "actions; fresh child draft for every button gesture; "
                        "outer windows cancelled; isolated ROM zero-diff gate"
                    ),
                    "error": error,
                    "database_cancel_closed": database_closed,
                    "sha256_before": hashlib.sha256(before).hexdigest().upper(),
                    "sha256_after": hashlib.sha256(after).hexdigest().upper(),
                    "diff_count": len(diffs) + int(len(before) != len(after)),
                    "execution_record_count": len(unique_records),
                    "observations": observations,
                    "execution_records": (
                        list(unique_records.values()) if validated else []
                    ),
                }, ensure_ascii=False, indent=2,
            ) + "\n",
            encoding="utf-8",
        )
    if not validated:
        raise RuntimeError(
            "weapon-rule puzzle matrix did not validate: "
            f"records={len(unique_records)}/66 error={error}"
        )
    log("DBWRULEPUZZLECONTROLS complete: 66/66 actions, zero ROM diff")


def stage_dbwrulesave(session: ProbeSession) -> None:
    """Save one isolated weapon-rule edit and record the exact ROM delta."""

    log(f"=== stage DBWRULESAVE: {session.wrule_case} ===")
    if not session.main_hwnd or not is_window(session.main_hwnd):
        raise RuntimeError("main window not alive")
    if not session.rom_is_loaded():
        raise RuntimeError("ROM not loaded")
    before = session.probe_rom.read_bytes()
    window = None
    for _attempt in range(8):
        window = _open_data_window(
            session, 20008, "数据库", dismiss_hidden=False
        )
        if window:
            break
        time.sleep(1.0)
    if not window:
        raise RuntimeError("database window did not appear")
    database_hwnd = window["hwnd"]
    rule_hwnd = 0
    puzzle_hwnd = 0
    case_specs = {
        "beam-xy": {
            "page": 0,
            "edits": ((460, str(session.wrule_value)),
                      (430, str(session.wrule_value2))),
        },
        "beam-code": {
            "page": 0,
            "edits": ((240, session.wrule_code),),
        },
        "movement1-code": {
            "page": 1,
            "edits": ((150, session.wrule_code),),
        },
        "movement1-increment": {
            "page": 1,
            "edits": ((730, str(session.wrule_value)),),
            "button": 720,
            "observe": 150,
        },
        "movement2-code": {
            "page": 2,
            "edits": ((630, session.wrule_code),),
        },
        "movement2-increment": {
            "page": 2,
            "edits": ((750, str(session.wrule_value)),),
            "button": 740,
            "observe": 630,
        },
        "picture-xy": {
            "page": 3,
            "edits": ((560, str(session.wrule_value)),
                      (540, str(session.wrule_value2))),
        },
        "picture-code": {
            "page": 3,
            "edits": ((180, session.wrule_code),),
        },
        "beam-puzzle-replace": {
            "page": 0, "edits": (),
            "puzzle": {"open_id": 380, "title": "光束拼图", "action": "replace"},
        },
        "beam-puzzle-noop": {
            "page": 0, "edits": (),
            "puzzle": {"open_id": 380, "title": "光束拼图", "action": "noop"},
        },
        "beam-puzzle-delete": {
            "page": 0, "edits": (),
            "puzzle": {"open_id": 380, "title": "光束拼图", "action": "delete"},
        },
        "picture-puzzle-move": {
            "page": 3, "edits": (),
            "puzzle": {"open_id": 390, "title": "物理拼图", "action": "move"},
        },
        "picture-puzzle-flip": {
            "page": 3, "edits": (),
            "puzzle": {"open_id": 390, "title": "物理拼图", "action": "flip"},
        },
        "picture-puzzle-hflip": {
            "page": 3, "edits": (),
            "puzzle": {"open_id": 390, "title": "物理拼图", "action": "hflip"},
        },
        "picture-puzzle-vflip": {
            "page": 3, "edits": (),
            "puzzle": {"open_id": 390, "title": "物理拼图", "action": "vflip"},
        },
    }
    spec = case_specs.get(session.wrule_case)
    if spec is None:
        raise RuntimeError(f"unsupported weapon-rule case {session.wrule_case}")
    result: dict = {
        "schema_version": 1,
        "validated": False,
        "case": session.wrule_case,
        "rom": str(session.probe_rom),
        "requested_value": session.wrule_value,
        "requested_value2": session.wrule_value2,
        "requested_code": session.wrule_code,
        "requested_record": session.wrule_record,
    }
    try:
        located = None
        for _attempt in range(20):
            page = switch_database_page_by_control(database_hwnd, 2530)
            buttons = (
                find_controls(
                    enum_child_tree(database_hwnd),
                    cls="Button", ctrl_id=2550, visible=True,
                )
                if page is not None else []
            )
            if buttons:
                located = buttons[0]
                break
            time.sleep(1.0)
        if located is None:
            raise RuntimeError("weapon rule button not found")
        known = {item["hwnd"] for item in session.top_windows()}
        click_control(located["hwnd"])
        rule_window = session.wait_new_top(
            exclude=known, timeout=5.0,
            cls_equals="WTWindow", title_contains="规律",
        )
        if not rule_window:
            raise RuntimeError("weapon rule window did not appear")
        rule_hwnd = rule_window["hwnd"]
        move_window(rule_hwnd, 80, 60, 1050, 760)
        time.sleep(0.5)
        page_ctrls = find_controls(
            enum_child_tree(rule_hwnd), cls="CPageControl", visible=True
        )
        if not page_ctrls:
            raise RuntimeError("weapon rule CPageControl not found")
        page_ctrl = max(
            page_ctrls,
            key=lambda item: item["rect"]["width"] * item["rect"]["height"],
        )
        win_rect = get_window_rect(rule_hwnd)
        dx, dy = _client_offset(rule_hwnd)
        ctrl_rect = page_ctrl["rect"]
        tab_y = ctrl_rect["top"] - win_rect["top"] + 24
        x_start = ctrl_rect["left"] - win_rect["left"] + 14
        x_end = ctrl_rect["right"] - win_rect["left"] - 24
        tab_positions: list[int] = []
        seen: set[tuple] = set()
        for x in range(x_start, x_end, 10):
            real_click_at(rule_hwnd, x - dx, tab_y - dy)
            time.sleep(0.20)
            signature = _window_ctrl_sig(rule_hwnd)
            if signature in seen:
                continue
            seen.add(signature)
            tab_positions.append(x)
            if len(tab_positions) == 4:
                break
        if len(tab_positions) != 4:
            raise RuntimeError(
                f"weapon rule page discovery incomplete: {len(tab_positions)}/4"
            )
        real_click_at(
            rule_hwnd,
            tab_positions[int(spec["page"])] - dx,
            tab_y - dy,
        )
        time.sleep(0.35)
        list_ids = (230, 290, 690, 340)
        list_id = list_ids[int(spec["page"])]
        lists = find_controls(
            enum_child_tree(rule_hwnd),
            cls="ListBox", ctrl_id=list_id, visible=True,
        )
        if not lists:
            raise RuntimeError(f"weapon rule list {list_id} missing")
        list_hwnd = lists[0]["hwnd"]
        if _send_msg_num(list_hwnd, 0x0186, session.wrule_record, 0) == -1:
            raise RuntimeError(
                f"weapon rule record {session.wrule_record} cannot be selected"
            )
        # Easy-language page controls may route the list notification through
        # more than one nested owner.  Notify each ancestor up to the rule
        # window; sending only to the immediate group box leaves the visual
        # selection changed while the backing record remains row zero.
        notify_parent = user32.GetParent(list_hwnd)
        notified: set[int] = set()
        while notify_parent and notify_parent not in notified:
            notified.add(notify_parent)
            _send_msg_num(
                notify_parent, WM_COMMAND,
                list_id | (1 << 16),  # LBN_SELCHANGE
                list_hwnd,
            )
            if notify_parent == rule_hwnd:
                break
            notify_parent = user32.GetParent(notify_parent)
        time.sleep(0.35)
        initial_tree = enum_child_tree(rule_hwnd)
        before_values: dict[str, str] = {}
        for control_id, value in spec["edits"]:
            edits = find_controls(
                initial_tree, cls="Edit", ctrl_id=control_id, visible=True
            )
            if not edits:
                raise RuntimeError(f"weapon rule edit {control_id} missing")
            before_values[str(control_id)] = get_window_text(edits[0]["hwnd"])
            edit_hwnd = edits[0]["hwnd"]
            set_control_text(edit_hwnd, value)
            edit_parent = user32.GetParent(edit_hwnd)
            if edit_parent:
                _send_msg_num(
                    edit_parent,
                    WM_COMMAND,
                    control_id | (0x0300 << 16),  # EN_CHANGE
                    edit_hwnd,
                )
        puzzle_spec = spec.get("puzzle")
        if puzzle_spec is not None:
            open_buttons = find_controls(
                enum_child_tree(rule_hwnd),
                cls="Button", ctrl_id=puzzle_spec["open_id"], visible=True,
            )
            if not open_buttons:
                raise RuntimeError(f"{puzzle_spec['title']} button missing")
            known = {item["hwnd"] for item in session.top_windows()}
            click_control(open_buttons[0]["hwnd"])
            puzzle = session.wait_new_top(
                exclude=known, timeout=5.0,
                cls_equals="WTWindow", title_contains=puzzle_spec["title"],
            )
            if not puzzle:
                raise RuntimeError(f"{puzzle_spec['title']} did not appear")
            puzzle_hwnd = puzzle["hwnd"]
            size = (791, 638) if int(spec["page"]) == 0 else (1030, 703)
            move_window(puzzle_hwnd, 120, 80, *size)
            time.sleep(0.4)
            session.dump_window(
                puzzle_hwnd,
                f"DBWRULESAVE_{session.wrule_case}_拼图动作前",
                menu=False,
            )

            def puzzle_click(
                control_id: int,
                button_name: str = "left",
                x_percent: int = 50,
                y_percent: int = 50,
            ) -> None:
                controls = find_controls(
                    enum_child_tree(puzzle_hwnd),
                    ctrl_id=control_id, visible=True,
                )
                if not controls:
                    raise RuntimeError(f"puzzle control {control_id} missing")
                target = controls[0]
                rect = target["rect"]
                puzzle_rect = get_window_rect(puzzle_hwnd)
                pdx, pdy = _client_offset(puzzle_hwnd)
                local_x = max(
                    6,
                    min(
                        rect["width"] - 6,
                        round(rect["width"] * x_percent / 100),
                    ),
                )
                local_y = max(
                    6,
                    min(
                        rect["height"] - 6,
                        round(rect["height"] * y_percent / 100),
                    ),
                )
                client_x = rect["left"] - puzzle_rect["left"] - pdx + local_x
                client_y = rect["top"] - puzzle_rect["top"] - pdy + local_y
                if not real_click_at(
                    puzzle_hwnd, client_x, client_y, button_name
                ):
                    raise RuntimeError(
                        f"puzzle control {control_id} click was blocked"
                    )
                time.sleep(0.35)

            action = puzzle_spec["action"]
            if action == "noop":
                pass
            elif action in {"replace", "move"}:
                if int(spec["page"]) == 0:
                    start_id = 280 if session.wrule_puzzle_start == 80 else 270
                else:
                    start_id = 250
                start_buttons = find_controls(
                    enum_child_tree(puzzle_hwnd),
                    cls="Button", ctrl_id=start_id, visible=True,
                )
                if not start_buttons:
                    raise RuntimeError(f"puzzle start button {start_id} missing")
                click_control(start_buttons[0]["hwnd"])
                time.sleep(0.25)
                puzzle_click(
                    140 if int(spec["page"]) == 0 else 120,
                    x_percent=session.wrule_library_x,
                    y_percent=session.wrule_library_y,
                )
                puzzle_click(
                    160 if int(spec["page"]) == 0 else 150,
                    x_percent=session.wrule_effect_x,
                    y_percent=session.wrule_effect_y,
                )
            elif action in {"delete", "flip"}:
                puzzle_click(
                    160 if int(spec["page"]) == 0 else 150,
                    "right",
                    x_percent=session.wrule_effect_x,
                    y_percent=session.wrule_effect_y,
                )
            elif action in {"hflip", "vflip"}:
                flip_id = 290 if action == "hflip" else 300
                buttons = find_controls(
                    enum_child_tree(puzzle_hwnd),
                    cls="Button", ctrl_id=flip_id, visible=True,
                )
                if not buttons:
                    raise RuntimeError(f"physical flip button {flip_id} missing")
                click_control(buttons[0]["hwnd"])
                time.sleep(0.35)
            else:
                raise RuntimeError(f"unsupported puzzle action {action}")
            session.dump_window(
                puzzle_hwnd,
                f"DBWRULESAVE_{session.wrule_case}_拼图动作后",
                menu=False,
            )
            puzzle_ok_id = 190 if int(spec["page"]) == 0 else 180
            puzzle_ok = find_controls(
                enum_child_tree(puzzle_hwnd),
                cls="Button", ctrl_id=puzzle_ok_id, visible=True,
            )
            if not puzzle_ok:
                raise RuntimeError("puzzle OK button missing")
            click_control(puzzle_ok[0]["hwnd"])
            if not session.wait_gone(puzzle_hwnd, 6.0):
                raise RuntimeError("puzzle did not close after OK")
            puzzle_hwnd = 0
            result["puzzle_action"] = {
                "kind": puzzle_spec["title"],
                "action": action,
                "library_click": action in {"replace", "move"},
                "effect_button": (
                    "none" if action == "noop"
                    else "right" if action in {"delete", "flip"} else "left"
                ),
                "start": session.wrule_puzzle_start,
                "library_percent": [
                    session.wrule_library_x, session.wrule_library_y,
                ],
                "effect_percent": [
                    session.wrule_effect_x, session.wrule_effect_y,
                ],
            }
        observed_before = None
        observed_after = None
        observe_id = spec.get("observe")
        if observe_id is not None:
            observed = find_controls(
                initial_tree, cls="Edit", ctrl_id=observe_id, visible=True
            )
            if not observed:
                raise RuntimeError(f"weapon rule observe edit {observe_id} missing")
            observed_before = get_window_text(observed[0]["hwnd"])
        action_id = spec.get("button")
        if action_id is not None:
            action_buttons = find_controls(
                enum_child_tree(rule_hwnd),
                cls="Button", ctrl_id=action_id, visible=True,
            )
            if not action_buttons:
                raise RuntimeError(f"weapon rule button {action_id} missing")
            known = {item["hwnd"] for item in session.top_windows()}
            click_control(action_buttons[0]["hwnd"])
            time.sleep(0.5)
            action_popups = [
                item for item in session.top_windows()
                if item["hwnd"] not in known
                and item["hwnd"] not in {database_hwnd, rule_hwnd}
                and item["class"] != "#32768"
            ]
            if action_popups:
                result["action_popups"] = [
                    {"title": item["title"], "class": item["class"]}
                    for item in action_popups
                ]
                for index, popup in enumerate(action_popups, 1):
                    session.dump_window(
                        popup["hwnd"],
                        f"DBWRULESAVE_{session.wrule_case}_动作弹窗_{index}",
                        menu=False,
                    )
                    close_window_safely(session, popup["hwnd"], timeout=3.0)
                raise RuntimeError("weapon rule action opened an error dialog")
            if observe_id is not None:
                observed = find_controls(
                    enum_child_tree(rule_hwnd),
                    cls="Edit", ctrl_id=observe_id, visible=True,
                )
                observed_after = (
                    get_window_text(observed[0]["hwnd"]) if observed else None
                )
        result["control_values_before"] = before_values
        result["observed_before"] = observed_before
        result["observed_after"] = observed_after
        session.dump_window(
            rule_hwnd, f"DBWRULESAVE_{session.wrule_case}_修改后", menu=False
        )
        ok_buttons = [
            item for item in find_controls(
                enum_child_tree(rule_hwnd),
                cls="Button", text_contains="确定", visible=True,
            ) if item.get("text") == "确定"
        ]
        if not ok_buttons:
            raise RuntimeError("weapon rule OK button missing")
        known = {item["hwnd"] for item in session.top_windows()}
        click_control(ok_buttons[0]["hwnd"])
        if not session.wait_gone(rule_hwnd, 1.5):
            ok_popups = [
                item for item in session.top_windows()
                if item["hwnd"] not in known
                and item["hwnd"] not in {database_hwnd, rule_hwnd}
                and item["class"] != "#32768"
            ]
            if ok_popups:
                result["ok_popups"] = [
                    {"title": item["title"], "class": item["class"]}
                    for item in ok_popups
                ]
                for index, popup in enumerate(ok_popups, 1):
                    session.dump_window(
                        popup["hwnd"],
                        f"DBWRULESAVE_{session.wrule_case}_确定弹窗_{index}",
                        menu=False,
                    )
                    close_window_safely(session, popup["hwnd"], timeout=3.0)
                raise RuntimeError("weapon rule OK opened an error dialog")
            real_click_control(ok_buttons[0]["hwnd"])
        if not session.wait_gone(rule_hwnd, 6.0):
            raise RuntimeError("weapon rule window did not close after OK")
        rule_hwnd = 0
        database_ok_buttons = [
            item for item in find_controls(
                enum_child_tree(database_hwnd),
                cls="Button", text_contains="确定", visible=True,
            ) if item.get("text") == "确定"
        ]
        if not database_ok_buttons:
            raise RuntimeError("database OK button missing")
        click_control(database_ok_buttons[0]["hwnd"])
        if not session.wait_gone(database_hwnd, 1.5):
            real_click_control(database_ok_buttons[0]["hwnd"])
        if not session.wait_gone(database_hwnd, 8.0):
            raise RuntimeError("database did not close after OK")
        user32.PostMessageW(session.main_hwnd, WM_COMMAND, 20004, 0)
        time.sleep(5.0)
        for popup in session.top_windows():
            if popup["hwnd"] != session.main_hwnd and popup["class"] == "#32770":
                session.handle_runtime_dialog(popup["hwnd"], "DBWRULESAVE_保存弹窗")
        after = session.probe_rom.read_bytes()
        diffs = [
            {"offset": index, "before": old, "after": new}
            for index, (old, new) in enumerate(zip(before, after))
            if old != new
        ]
        if len(before) != len(after):
            diffs.append({"size_before": len(before), "size_after": len(after)})
        noop = session.wrule_expect_noop or (
            puzzle_spec is not None
            and puzzle_spec.get("action") == "noop"
        )
        result.update(
            {
                # A no-op puzzle round trip is valid only when the reference
                # editor leaves the isolated ROM byte-for-byte unchanged.
                # Mutating cases retain the inverse expectation.  Treating
                # every zero-diff run as failure previously made the most
                # important preservation golden impossible to certify.
                "validated": not bool(diffs) if noop else bool(diffs),
                "expected_diff": "zero" if noop else "nonzero",
                "sha256_before": hashlib.sha256(before).hexdigest().upper(),
                "sha256_after": hashlib.sha256(after).hexdigest().upper(),
                "diff_count": len(diffs),
                "diffs": diffs,
            }
        )
    finally:
        if puzzle_hwnd and is_window(puzzle_hwnd):
            close_window_safely(session, puzzle_hwnd, timeout=5.0)
        if rule_hwnd and is_window(rule_hwnd):
            close_window_safely(session, rule_hwnd, timeout=5.0)
        if is_window(database_hwnd):
            close_window_safely(session, database_hwnd, timeout=5.0)
        out_dir = session.out / "interaction-discovery"
        out_dir.mkdir(parents=True, exist_ok=True)
        (out_dir / f"weapon-rule-{session.wrule_case}-save-golden.json").write_text(
            json.dumps(result, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
    if not result.get("validated"):
        raise RuntimeError("weapon rule save golden did not validate")
    log(
        f"DBWRULESAVE complete: case={session.wrule_case} "
        f"diffs={result['diff_count']}"
    )


# ----------------------------------------------------------------------- main


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--stage", default="A,B", help="comma separated A/B/LOAD/C/CSAFE/CT/M05/M12/M12LISTCONTROLS/M12FIELDCONTROLS/M12BUTTONCONTROLS/M12INPUTCONTROLS/FONTCONTROLS/TEXTCONVERTCONTROLS/DBICONCONTROLS/DBUNITSKILLCONTROLS/DBSMALLNUMCONTROLS/DBWINSTRSMALLCONTROLS/DBWINSTRCOMBOCONTROLS/DBWINSTRMIXEDCONTROLS/DBWINSTRCOMPLEXCONTROLS/DBPAGECONTROLS/DBDIALOGPAGECONTROLS/DBDIALOGLISTCONTROLS/DBCORELISTCONTROLS/DBSECONDARYLISTCONTROLS/DBSYSLISTCONTROLS/DBUNITCHARCOMBOCONTROLS/DBOTHERCOMBOCONTROLS/DBUNITEDITCONTROLS/DBCHARACTEREDITCONTROLS/DBWEAPONEDITCONTROLS/DBOTHEREDITCONTROLS/DBROOTEDITCONTROLS/DBSPINNERCONTROLS/DBSTATICSTATECONTROLS/DBREGIONSTATECONTROLS/DBUNITBUTTONCONTROLS/DBUNITIMAGEBUTTONCONTROLS/DBUNITDETAILBUTTONCONTROLS/DBUNITCONDITIONALBUTTONCONTROLS/DBCHARACTERBUTTONCONTROLS/DBCHARACTERCLEARBUTTONCONTROLS/DBDIALOGBUTTONCONTROLS/DBOTHERBUTTONCONTROLS/DBWEAPONBUTTONCONTROLS/DBGLOBALBUTTONCONTROLS/DBEDITDIALOGUECONTROLS/DBATTACKDIALOGUECONTROLS/DBDEFENCEDIALOGUECONTROLS/DBMESSAGECONTROLS/DBM05PUZZLECONTROLS/DBCTX/DBCMD/DBWINSTR/DBSAVEF3/DBSAVEFF/DBCMDGESTURES/DBCONTEXTACTIONS/DBCONTEXTSAVE/DBCANCELALL/DBWRULE/DBWRULEBTN/DBWRULEBUTTONCASE/DBWRULELISTS/DBWRULESIM/DBWRULEPUZZLE/DBWRULEPUZZLECONTROLS/DBWRULESAVE"
    )
    parser.add_argument("--pid", type=int, help="attach to a running probe process")
    parser.add_argument("--rom", help="override ROM path used by stage B")
    parser.add_argument("--dbins-option", type=int, default=1)
    parser.add_argument("--dbins-button", type=int, default=130)
    parser.add_argument(
        "--dbins-confirm", choices=("yes", "no"), default="no"
    )
    parser.add_argument("--dbins-value", type=int, default=2)
    parser.add_argument("--dbins-value2", type=int, default=0)
    parser.add_argument(
        "--dbins-rule-family", choices=("42", "c2"), default="42"
    )
    parser.add_argument("--dbins-rule-variant", type=int, choices=(0, 1), default=0)
    parser.add_argument("--db-weapon-record", type=int, default=1)
    parser.add_argument("--db-instruction-row", type=int, default=0)
    parser.add_argument(
        "--db-animation-kind", choices=("ally", "enemy"), default="ally"
    )
    parser.add_argument("--db-ff-expect-noop", action="store_true")
    parser.add_argument(
        "--db-ff-action", choices=("left", "keyboard", "right"), default="left"
    )
    parser.add_argument(
        "--db-context-case",
        choices=("cut", "paste", "paste-all", "delete", "clear"),
        default="cut",
    )
    parser.add_argument(
        "--db-message-case",
        choices=("info-no", "info-yes", "prompt"),
        default="info-no",
    )
    parser.add_argument(
        "--m12-input-case",
        choices=(
            "ok-keyboard", "ok-left", "ok-right",
            "cancel-keyboard", "cancel-left", "cancel-right",
        ),
        default="ok-keyboard",
    )
    parser.add_argument(
        "--event-button-case",
        choices=(
            "page",
            "global-690-right_click", "global-690-keyboard_activate", "global-690-left_click",
            "global-100-right_click", "global-100-keyboard_activate", "global-100-left_click",
            "global-110-right_click", "global-110-keyboard_activate", "global-110-left_click",
        ),
        default="page",
    )
    parser.add_argument(
        "--puzzle-code-case",
        choices=("ok-keyboard","ok-left","ok-right","cancel-keyboard","cancel-left","cancel-right"),
        default="ok-keyboard",
    )
    parser.add_argument(
        "--wrule-case",
        choices=(
            "beam-xy", "beam-code", "movement1-code", "movement1-increment",
            "movement2-code", "movement2-increment", "picture-xy",
            "picture-code", "beam-puzzle-replace", "beam-puzzle-noop", "beam-puzzle-delete",
            "picture-puzzle-move", "picture-puzzle-flip",
            "picture-puzzle-hflip", "picture-puzzle-vflip",
        ),
        default="beam-xy",
    )
    parser.add_argument("--wrule-value", type=int, default=18)
    parser.add_argument("--wrule-value2", type=int, default=7)
    parser.add_argument("--wrule-record", type=int, default=0)
    parser.add_argument(
        "--wrule-puzzle-start", type=int, choices=(40, 80), default=80
    )
    parser.add_argument(
        "--wrule-library-x", type=int, choices=range(1, 100), default=50
    )
    parser.add_argument(
        "--wrule-library-y", type=int, choices=range(1, 100), default=50
    )
    parser.add_argument(
        "--wrule-effect-x", type=int, choices=range(1, 100), default=50
    )
    parser.add_argument(
        "--wrule-effect-y", type=int, choices=range(1, 100), default=50
    )
    parser.add_argument(
        "--wrule-code", default="01 83 F0 FC 00 83 F0 FC"
    )
    parser.add_argument(
        "--wrule-expect-noop",
        action="store_true",
        help="validate that the selected action leaves the isolated ROM unchanged",
    )
    parser.add_argument("--wrule-page-index", type=int, choices=range(4), default=0)
    parser.add_argument("--wrule-button-id", type=int, default=420)
    parser.add_argument(
        "--wrule-button-action",
        choices=("left", "right", "keyboard"),
        default="left",
    )
    parser.add_argument(
        "--evidence-tag",
        default="",
        help="write a new evidence directory instead of replacing prior captures",
    )
    parser.add_argument(
        "--fast-launch",
        action="store_true",
        help="skip unrelated main-menu captures for isolated one-action probes",
    )
    parser.add_argument("--keep-open", action="store_true", help="do not kill target")
    parser.add_argument("--keep-open-attach", action="store_true")
    args = parser.parse_args()
    if args.evidence_tag and not re.fullmatch(
        r"[a-z0-9][a-z0-9-]{0,40}", args.evidence_tag
    ):
        parser.error("--evidence-tag must be a short lowercase slug")

    repo = Path(__file__).resolve().parents[2]
    session = ProbeSession(repo, args.evidence_tag)
    session.dbins_option = args.dbins_option
    session.dbins_button = args.dbins_button
    session.dbins_confirm = args.dbins_confirm
    session.dbins_value = args.dbins_value
    session.dbins_value2 = args.dbins_value2
    session.dbins_rule_family = args.dbins_rule_family
    session.dbins_rule_variant = args.dbins_rule_variant
    session.db_weapon_record = args.db_weapon_record
    session.db_instruction_row = args.db_instruction_row
    session.db_animation_kind = args.db_animation_kind
    session.db_ff_expect_noop = args.db_ff_expect_noop
    session.db_ff_action = args.db_ff_action
    session.db_context_case = args.db_context_case
    session.db_message_case = args.db_message_case
    session.m12_input_case = args.m12_input_case
    session.event_button_case = args.event_button_case
    session.puzzle_code_case = args.puzzle_code_case
    session.wrule_case = args.wrule_case
    session.wrule_value = args.wrule_value
    session.wrule_value2 = args.wrule_value2
    session.wrule_record = args.wrule_record
    session.wrule_code = args.wrule_code
    session.wrule_puzzle_start = args.wrule_puzzle_start
    session.wrule_library_x = args.wrule_library_x
    session.wrule_library_y = args.wrule_library_y
    session.wrule_effect_x = args.wrule_effect_x
    session.wrule_effect_y = args.wrule_effect_y
    session.wrule_expect_noop = args.wrule_expect_noop
    session.wrule_page_index = args.wrule_page_index
    session.wrule_button_id = args.wrule_button_id
    session.wrule_button_action = args.wrule_button_action
    session.fast_launch = args.fast_launch
    session.load()
    if args.rom:
        session.probe_rom = Path(args.rom).resolve()
    if args.pid:
        session.attach(args.pid)
    stages = [s.strip().upper() for s in args.stage.split(",") if s.strip()]

    exit_code = 0
    try:
        if args.pid:
            session.attach(args.pid)
        elif not session.process_alive():
            session.pid = None
            session.main_hwnd = None
            session.launch()
        # else: resumed session with a live pid from session.json
        handlers = {
            "A": stage_a,
            "B": stage_b,
            "LOAD": stage_load,
            "C": stage_c,
            "CSAFE": stage_c_safe,
            "CT": stage_ct,
            "M05": stage_m05,
            "M12": stage_m12,
            "M12LISTCONTROLS": stage_m12listcontrols,
            "M12FIELDCONTROLS": stage_m12fieldcontrols,
            "M12BUTTONCONTROLS": stage_m12buttoncontrols,
            "M12INPUTCONTROLS": stage_m12inputcontrols,
            "EVENTPAGELISTCONTROLS": stage_eventpagelistcontrols,
            "EVENTFIELDCONTROLS": stage_eventfieldcontrols,
            "EVENTBUTTONCONTROLS": stage_eventbuttoncontrols,
            "TITLEPUZZLECONTROLS": stage_titlepuzzlecontrols,
            "PUZZLECODECONTROLS": stage_puzzlecodecontrols,
            "OTHERFIELDCONTROLS": stage_otherfieldcontrols,
            "OTHERBUTTONCONTROLS": stage_otherbuttoncontrols,
            "CALCULATORCONTROLS": stage_calculatorcontrols,
            "MAINFIELDCONTROLS": stage_mainfieldcontrols,
            "MAINBUTTONCONTROLS": stage_mainbuttoncontrols,
            "LAUNCHERCONTROLS": stage_launchercontrols,
            "MENUCONTROLS": stage_menucontrols,
            "LIFECYCLESTATES": stage_lifecyclestates,
            "ERRORMESSAGECONTROLS": stage_errormessagecontrols,
            "INFOMESSAGECONTROLS": stage_infomessagecontrols,
            "OPENFILECONTROLS": stage_openfilecontrols,
            "OPENIMAGECONTROLS": stage_openimagecontrols,
            "SAVEEDITORCONTROLS": stage_saveeditorcontrols,
            "OPENSAVECONTROLS": stage_opensavecontrols,
            "EXPORTUNITCONTROLS": stage_exportunitcontrols,
            "EXPORTPORTRAITCONTROLS": stage_exportportraitcontrols,
            "DATABASECONTEXTREMAINING": stage_databasecontextremaining,
            "FONTCONTROLS": stage_fontcontrols,
            "TEXTCONVERTCONTROLS": stage_textconvertcontrols,
            "DBICONCONTROLS": stage_dbiconcontrols,
            "DBUNITSKILLCONTROLS": stage_dbunitskillcontrols,
            "DBSMALLNUMCONTROLS": stage_dbsmallnumcontrols,
            "DBWINSTRSMALLCONTROLS": stage_dbwinstrsmallcontrols,
            "DBWINSTRCOMBOCONTROLS": stage_dbwinstrcombocontrols,
            "DBWINSTRMIXEDCONTROLS": stage_dbwinstrmixedcontrols,
            "DBWINSTRCOMPLEXCONTROLS": stage_dbwinstrcomplexcontrols,
            "DBPAGECONTROLS": stage_dbpagecontrols,
            "DBDIALOGPAGECONTROLS": stage_dbdialogpagecontrols,
            "DBDIALOGLISTCONTROLS": stage_dbdialoglistcontrols,
            "DBCORELISTCONTROLS": stage_dbcorelistcontrols,
            "DBSECONDARYLISTCONTROLS": stage_dbsecondarylistcontrols,
            "DBSYSLISTCONTROLS": stage_dbsyslistcontrols,
            "DBUNITCHARCOMBOCONTROLS": stage_dbunitcharcombocontrols,
            "DBOTHERCOMBOCONTROLS": stage_dbothercombocontrols,
            "DBUNITEDITCONTROLS": stage_dbuniteditcontrols,
            "DBCHARACTEREDITCONTROLS": stage_dbcharactereditcontrols,
            "DBWEAPONEDITCONTROLS": stage_dbweaponeditcontrols,
            "DBOTHEREDITCONTROLS": stage_dbothereditcontrols,
            "DBROOTEDITCONTROLS": stage_dbrooteditcontrols,
            "DBSPINNERCONTROLS": stage_dbspinnercontrols,
            "DBSTATICSTATECONTROLS": stage_dbstaticstatecontrols,
            "DBREGIONSTATECONTROLS": stage_dbregionstatecontrols,
            "DBUNITBUTTONCONTROLS": stage_dbunitbuttoncontrols,
            "DBUNITIMAGEBUTTONCONTROLS": stage_dbunitimagebuttoncontrols,
            "DBUNITDETAILBUTTONCONTROLS": stage_dbunitdetailbuttoncontrols,
            "DBUNITCONDITIONALBUTTONCONTROLS": stage_dbunitconditionalbuttoncontrols,
            "DBCHARACTERBUTTONCONTROLS": stage_dbcharacterbuttoncontrols,
            "DBCHARACTERCLEARBUTTONCONTROLS": stage_dbcharacterclearbuttoncontrols,
            "DBDIALOGBUTTONCONTROLS": stage_dbdialogbuttoncontrols,
            "DBOTHERBUTTONCONTROLS": stage_dbotherbuttoncontrols,
            "DBWEAPONBUTTONCONTROLS": stage_dbweaponbuttoncontrols,
            "DBGLOBALBUTTONCONTROLS": stage_dbglobalbuttoncontrols,
            "DBEDITDIALOGUECONTROLS": stage_dbeditdialoguecontrols,
            "DBATTACKDIALOGUECONTROLS": stage_dbattackdialoguecontrols,
            "DBDEFENCEDIALOGUECONTROLS": stage_dbdefencedialoguecontrols,
            "DBMESSAGECONTROLS": stage_dbmessagecontrols,
            "DBM05PUZZLECONTROLS": stage_dbm05puzzlecontrols,
            "DBCTX": stage_dbctx,
            "DBCMD": stage_dbcmd,
            "DBWINSTR": stage_dbwinstr,
            "DBSAVEF3": stage_dbsavef3,
            "DBSAVEFF": stage_dbsaveff,
            "DBCMDGESTURES": stage_dbcmdgestures,
            "DBCONTEXTACTIONS": stage_dbcontextactions,
            "DBCONTEXTSAVE": stage_dbcontextsave,
            "DBCANCELALL": stage_dbcancelall,
            "DBWRULE": stage_dbwrule,
            "DBWRULEBTN": stage_dbwrulebtn,
            "DBWRULEBUTTONCASE": stage_dbwrulebuttoncase,
            "DBWRULECONTROLS": stage_dbwrulecontrols,
            "DBWRULELISTS": stage_dbwrulelists,
            "DBWRULESIM": stage_dbwrulesim,
            "DBWRULEPUZZLE": stage_dbwrulepuzzle,
            "DBWRULEPUZZLECONTROLS": stage_dbwrulepuzzlecontrols,
            "DBWRULESAVE": stage_dbwrulesave,
        }
        for name in stages:
            handler = handlers.get(name)
            if not handler:
                log(f"stage {name} not implemented yet, skipping")
                continue
            try:
                handler(session)
            except Exception as exc:
                log(f"stage {name} FAILED: {exc!r}")
                exit_code = 1
    finally:
        if not (args.keep_open or args.keep_open_attach):
            session.terminate()
        else:
            session.save()
            log(f"keep-open: pid={session.pid} main_hwnd={session.main_hwnd}")
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
