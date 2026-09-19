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
import json
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
WM_LBUTTONUP = 0x0202
WM_RBUTTONDOWN = 0x0204
WM_RBUTTONUP = 0x0205
BM_CLICK = 0x00F5
BN_CLICKED = 0
MK_LBUTTON = 0x0001
VK_ESCAPE = 0x1B
VK_RETURN = 0x0D
VK_MENU = 0x12
GW_CHILD = 5
GW_HWNDNEXT = 2
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
LVM_GETITEMCOUNT = 0x1004
LVM_GETSELECTEDCOUNT = 0x1030
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


def click_control_via_command(item: dict) -> None:
    hwnd = item["hwnd"]
    parent = user32.GetParent(hwnd)
    if parent:
        post_command(parent, item["ctrl_id"], hwnd)
    else:
        click_control(hwnd)


def set_control_text(hwnd: int, text: str) -> None:
    _send_msg_text(hwnd, WM_SETTEXT, 0, text)


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
        user32.PostMessageW(hwnd, WM_CONTEXTMENU, hwnd, lparam)


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
        self.owns_process = False
        self.main_hwnd: int | None = None
        self.known_top: set[int] = set()
        self.probe_rom = self.work / "probe.nes"  # DC_kuorong copy + probe.cdl
        self.probe_rom_fallback = self.work / "测试.nes"  # legacy modifier's own test ROM
        self.probe_sav = self.work / "probe.sav"

    # -- lifecycle ------------------------------------------------------

    def launch(self) -> None:
        exe = self.work / "SRW2_patched.exe"
        if not exe.exists():
            raise FileNotFoundError(exe)
        proc = subprocess.Popen(
            [str(exe)], cwd=str(self.work), creationflags=subprocess.CREATE_NEW_PROCESS_GROUP
        )
        self.pid = proc.pid
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
        if self.pid:
            if not self.owns_process and not self.process_alive():
                log(f"stale/unverified pid={self.pid}; skip termination")
                self.pid = None
                return
            subprocess.run(
                ["taskkill", "/PID", str(self.pid), "/T", "/F"],
                capture_output=True,
                check=False,
            )
            log(f"terminated pid={self.pid}")
            self.pid = None

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

    def handle_runtime_dialog(self, popup_hwnd: int, tag: str) -> None:
        """Dump and dismiss a runtime-error/message dialog; capture evidence."""
        self.dump_window(popup_hwnd, tag, menu=False)
        log(f"runtime dialog: {get_window_text(popup_hwnd)!r}")
        ok = user32.GetDlgItem(popup_hwnd, 2) or user32.GetDlgItem(popup_hwnd, 1)
        if ok:
            click_control(ok)
        else:
            user32.PostMessageW(popup_hwnd, WM_CLOSE, 0, 0)
        self.wait_gone(popup_hwnd, 5.0)

    def wait_rom_load(self, settle: float = 6.0) -> bool:
        """Wait until 数据 menu appears, dismissing runtime dialogs meanwhile."""
        deadline = time.monotonic() + 25.0
        settle_until = time.monotonic() + settle
        dialog_index = 0
        while time.monotonic() < deadline:
            if self.rom_is_loaded():
                # give late dialogs a chance during the settle window
                if time.monotonic() < settle_until:
                    time.sleep(0.5)
                    continue
                return True
            if not self.process_alive():
                log("target process died during ROM load")
                return False
            for window in self.top_windows():
                if window["class"] == "#32770" and window["hwnd"] not in self.known_top:
                    dialog_index += 1
                    self.handle_runtime_dialog(
                        window["hwnd"], f"B98_载入后弹窗{dialog_index}"
                    )
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
    already_main = windows[0]["title"].startswith("SRW2扩容版修改器")
    if already_main:
        log("launcher already dismissed (attached session); skipping launcher dump")
        session.main_hwnd = windows[0]["hwnd"]
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
        click_control(enter_hwnd)
        main_window = None
        deadline = time.monotonic() + 20.0
        real_click_retried = False
        while time.monotonic() < deadline:
            for window in session.top_windows():
                if window["hwnd"] == launcher["hwnd"]:
                    continue
                if window["title"].startswith("SRW2扩容版修改器"):
                    main_window = window
                    break
            if main_window:
                break
            if not real_click_retried and time.monotonic() + 15.0 >= deadline:
                button_rect = get_window_rect(enter_hwnd)
                launcher_rect = get_window_rect(launcher["hwnd"])
                client_x, client_y = _client_offset(launcher["hwnd"])
                real_click_at(
                    launcher["hwnd"],
                    (button_rect["left"] + button_rect["right"]) // 2
                    - launcher_rect["left"] - client_x,
                    (button_rect["top"] + button_rect["bottom"]) // 2
                    - launcher_rect["top"] - client_y,
                )
                real_click_retried = True
            time.sleep(0.4)
        if not main_window:
            raise RuntimeError("main window did not appear after entering")
        session.main_hwnd = main_window["hwnd"]
        session.save()
        log(f"main window hwnd={session.main_hwnd} title={main_window['title']!r}")
    move_window(session.main_hwnd, 30, 30, 1200, 850)
    time.sleep(0.6)
    session.dump_window(session.main_hwnd, "A02_主窗口_未载入ROM")
    _shoot_open_menus(session, "A03")


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


def stage_c(session: ProbeSession) -> None:
    log("=== stage C: 数据 menu windows ===")
    if not session.main_hwnd or not is_window(session.main_hwnd):
        raise RuntimeError("main window not alive; run stage A/B first")
    if not session.rom_is_loaded():
        raise RuntimeError("ROM not loaded; run stage B first")
    for index, (label, cmd_id, tabs) in enumerate(STAGE_C_WINDOWS, start=1):
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
    window = _open_data_window(session, 20008, "数据库")
    if not window:
        raise RuntimeError("database window did not appear")
    try:
        session.dump_window(window["hwnd"], "M05_数据库_机体修改")
    finally:
        close_window_safely(session, window["hwnd"])


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


def _open_data_window(session: "ProbeSession", cmd_id: int, label: str):
    if not session.process_alive():
        log(f"{label}: target process is dead")
        return None
    dismiss_blocking_popups(session)
    session.snapshot_known()
    user32.PostMessageW(session.main_hwnd, WM_COMMAND, cmd_id, 0)
    window = session.wait_new_top(timeout=10.0, cls_equals="WTWindow")
    if not window:
        # late error dialogs can appear after the timeout; give them a chance
        time.sleep(4.0)
        if session.process_alive():
            dismiss_blocking_popups(session)
        log(f"{label}: window did not appear (cmd {cmd_id})")
        return None
    log(f"{label}: hwnd={window['hwnd']} title={window['title']!r}")
    return window


def dismiss_blocking_popups(session: "ProbeSession", prefix: str = "DIAG") -> int:
    """Dump and close any non-main top-level window blocking the main window."""
    if not session.pid:
        return 0
    closed = 0
    index = 0
    for window in session.top_windows():
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

    window = _open_data_window(session, 20011, "地图动画")
    if not window:
        raise RuntimeError("map-animation window did not appear")
    try:
        sweep_tabs(session, window["hwnd"], "M12_地图动画")
    finally:
        close_window_safely(session, window["hwnd"])


# ----------------------------------------------------------------------- main


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--stage", default="A,B", help="comma separated A/B/C/CT/M05/M12"
    )
    parser.add_argument("--pid", type=int, help="attach to a running probe process")
    parser.add_argument("--rom", help="override ROM path used by stage B")
    parser.add_argument(
        "--evidence-tag",
        default="",
        help="write a new evidence directory instead of replacing prior captures",
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
            "C": stage_c,
            "CT": stage_ct,
            "M05": stage_m05,
            "M12": stage_m12,
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
