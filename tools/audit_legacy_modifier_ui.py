"""Inventory the isolated legacy modifier UI for differential verification.

This helper is intentionally read-only with respect to the reference executable.
It writes its report to output/build/legacy-diff-audit and closes the inspected app.
"""

from __future__ import annotations

import argparse
import json
import threading
import time
import traceback
from pathlib import Path

from pywinauto import Desktop
from pywinauto.application import Application
from pywinauto.controls.win32_controls import ComboBoxWrapper
import win32api
import win32con
import win32gui


_ACTIVE_PID: int | None = None


def _control_record(control) -> dict[str, object]:
    record: dict[str, object] = {}
    for name, getter in (
        ("text", control.window_text),
        ("class", control.class_name),
        ("control_id", control.control_id),
        ("rectangle", lambda: str(control.rectangle())),
        ("visible", control.is_visible),
        ("enabled", control.is_enabled),
    ):
        try:
            record[name] = getter()
        except Exception as exc:  # Legacy controls are not uniformly introspectable.
            record[name] = f"<{type(exc).__name__}: {exc}>"
    if record.get("class") == "SysListView32" and record.get("visible"):
        try:
            try:
                column_count = control.column_count()
            except Exception:
                column_count = 1
            record["items"] = [
                [
                    control.get_item(row, column).text()
                    for column in range(max(1, column_count))
                ]
                for row in range(control.item_count())
            ]
        except Exception as exc:
            record["items_error"] = f"{type(exc).__name__}: {exc}"
    if record.get("class") == "ComboBox" and record.get("visible"):
        try:
            combo = ComboBoxWrapper(control.element_info)
            record["items"] = combo.texts()[1:]
            record["selected_index"] = combo.selected_index()
        except Exception as exc:
            try:
                record["selected_index"] = control.current_selection()
                record["items"] = [
                    control.item_text(index) for index in range(control.item_count())
                ]
            except Exception as fallback_exc:
                record["items_error"] = (
                    f"{type(exc).__name__}: {exc}; "
                    f"{type(fallback_exc).__name__}: {fallback_exc}"
                )
    return record


def _menu_records(menu) -> list[dict[str, object]]:
    records = []
    for item in menu.items():
        try:
            text = item.text()
        except Exception as exc:
            text = f"<{type(exc).__name__}: {exc}>"
        record = {"text": text}
        try:
            record["id"] = item.id()
        except Exception:
            pass
        try:
            submenu = item.sub_menu()
            if submenu is not None:
                record["items"] = _menu_records(submenu)
        except Exception:
            pass
        records.append(record)
    return records


def _main_editor_window(
    app: Application, timeout: float = 15.0, require_data_menu: bool = False
):
    """Reacquire the editor window after the landing form destroys its HWND."""
    deadline = time.monotonic() + timeout
    last_error: Exception | None = None
    fallback = None
    while time.monotonic() < deadline:
        try:
            for window in Desktop(backend="win32").windows():
                try:
                    if window.is_visible() and window.window_text().startswith(
                        "SRW2扩容版修改器"
                    ):
                        if not require_data_menu:
                            return window
                        fallback = window
                        try:
                            top_items = [item.text() for item in window.menu().items()]
                            if any(text.startswith("数据") for text in top_items):
                                return window
                        except Exception as exc:
                            last_error = exc
                except Exception as exc:
                    last_error = exc
        except Exception as exc:
            last_error = exc
        time.sleep(0.25)
    if fallback is not None:
        return fallback
    if last_error is not None:
        raise RuntimeError("Unable to reacquire the legacy editor window") from last_error
    raise RuntimeError("Unable to reacquire the legacy editor window")


def _position_window(app: Application):
    """Position a freshly acquired wrapper, retrying once on a stale handle."""
    for attempt in range(2):
        window = _main_editor_window(app)
        try:
            window.restore()
            window.move_window(x=30, y=30, width=1200, height=850, repaint=True)
            window.set_focus()
            return window
        except OSError:
            if attempt:
                raise
            time.sleep(0.5)
    raise RuntimeError("Unable to position the legacy editor window")


def main() -> int:
    global _ACTIVE_PID
    parser = argparse.ArgumentParser()
    parser.add_argument("--pid", type=int)
    parser.add_argument("--launch", action="store_true")
    parser.add_argument("--enter", action="store_true")
    parser.add_argument("--open-rom", action="store_true")
    parser.add_argument("--rom")
    parser.add_argument("--open-save")
    parser.add_argument("--select-combo", action="append", default=[])
    parser.add_argument("--menu-path")
    parser.add_argument("--database-tab", type=int)
    parser.add_argument("--set-edit", action="append", default=[])
    parser.add_argument("--click-control", type=int, action="append", default=[])
    parser.add_argument("--post-click-control", type=int, action="append", default=[])
    parser.add_argument("--async-click-control", type=int, action="append", default=[])
    parser.add_argument("--raw-click-control", type=int, action="append", default=[])
    parser.add_argument("--window-click")
    parser.add_argument("--list-double-click")
    parser.add_argument("--save", action="store_true")
    parser.add_argument("--wait", type=float, default=3.0)
    parser.add_argument("--keep-open", action="store_true")
    args = parser.parse_args()

    repo = Path(__file__).resolve().parents[1]
    audit_dir = repo / "output" / "build" / "legacy-diff-audit"
    output = audit_dir / "ui-inventory.json"
    pid_output = audit_dir / "ui-audit-pid.txt"
    app = None
    if args.launch:
        app = Application(backend="win32").start(
            str(audit_dir / "SRW2_patched.exe"),
            work_dir=str(audit_dir),
            timeout=30,
        )
        args.pid = app.process
        _ACTIVE_PID = args.pid
        pid_output.write_text(str(args.pid), encoding="ascii")
    elif args.pid is not None:
        app = Application(backend="win32").connect(process=args.pid, timeout=15)
        _ACTIVE_PID = args.pid

    if app is not None:
        time.sleep(args.wait)
        main_window = app.top_window()
        main_window.restore()
        main_window.move_window(x=30, y=30, width=1200, height=850, repaint=True)
        main_window.set_focus()
        if args.enter:
            buttons = [
                control
                for control in main_window.descendants(class_name="Button")
                if control.window_text() == "进入修改器"
            ]
            if not buttons:
                raise RuntimeError("Landing window has no enter button")
            buttons[0].click()
            time.sleep(args.wait)
            app = Application(backend="win32").connect(process=args.pid, timeout=15)
            main_window = _main_editor_window(app)
            args.pid = main_window.process_id()
            _ACTIVE_PID = args.pid
            pid_output.write_text(str(args.pid), encoding="ascii")
            app = Application(backend="win32").connect(process=args.pid, timeout=15)
            main_window = _position_window(app)
        if args.open_rom:
            main_window = _main_editor_window(app)
            visible_open_dialogs = [
                window
                for window in Desktop(backend="win32").windows()
                if window.process_id() == args.pid
                and window.is_visible()
                and window.window_text().startswith("打开")
            ]
            if not visible_open_dialogs:
                try:
                    main_window.menu_select("文件->打开")
                except Exception:
                    main_window.type_keys("%f")
                    time.sleep(0.5)
                    main_window.type_keys("o")
            dialog = Desktop(backend="win32").window(
                process=args.pid, title_re="打开.*"
            )
            dialog.wait("visible enabled", timeout=15)
            edits = [
                edit
                for edit in dialog.descendants(class_name="Edit")
                if edit.is_visible() and edit.is_enabled()
            ]
            if not edits:
                raise RuntimeError("Open dialog has no filename field")
            rom_path = Path(args.rom) if args.rom else audit_dir / "audit.nes"
            edits[-1].set_edit_text(str(rom_path))
            dialog.type_keys("{ENTER}")
            time.sleep(args.wait)
        if args.menu_path:
            main_window = _main_editor_window(app, require_data_menu=True)
            main_window.menu_select(args.menu_path)
            time.sleep(args.wait)
        if args.database_tab is not None:
            database = next(
                window
                for window in app.windows()
                if window.is_visible() and window.window_text() == "数据库"
            )
            tab_centers = (45, 130, 215, 300, 390, 485)
            database.click_input(coords=(tab_centers[args.database_tab], 62))
            time.sleep(args.wait)
        if args.open_save:
            save_window = next(
                window
                for window in app.windows()
                if window.is_visible() and window.window_text().startswith("存档编辑器")
            )
            open_button = next(
                item for item in save_window.descendants() if item.control_id() == 160
            )
            open_button.click()
            file_dialog = Desktop(backend="win32").window(
                process=args.pid, title_re="打开.*"
            )
            file_dialog.wait("visible enabled", timeout=15)
            edits = [
                edit
                for edit in file_dialog.descendants(class_name="Edit")
                if edit.is_visible() and edit.is_enabled()
            ]
            if not edits:
                raise RuntimeError("Save-file dialog has no visible filename field")
            edits[-1].set_edit_text(str(Path(args.open_save)))
            file_dialog.type_keys("{ENTER}")
            time.sleep(args.wait)
            save_window = next(
                window
                for window in app.windows()
                if window.is_visible() and window.window_text().startswith("存档编辑器")
            )
            read_button = next(
                item for item in save_window.descendants() if item.control_id() == 190
            )
            read_button.click()
            time.sleep(args.wait)
        if args.select_combo:
            action_windows = [
                window
                for window in app.windows()
                if window.is_visible()
            ]
            for assignment in args.select_combo:
                control_id_text, index_text = assignment.split("=", 1)
                matches = [
                    item
                    for action_window in action_windows
                    for item in action_window.descendants(class_name="ComboBox")
                    if item.control_id() == int(control_id_text)
                    and item.is_visible()
                ]
                if not matches:
                    raise RuntimeError(
                        f"Visible combo ID {control_id_text} was not found"
                    )
                ComboBoxWrapper(matches[0].element_info).select(int(index_text))
                time.sleep(args.wait)
        if args.list_double_click:
            control_id_text, row_text, column_text = args.list_double_click.split(",")
            active_windows = [
                window
                for window in app.windows()
                if window.is_visible()
                and not window.window_text().startswith("SRW2扩容版修改器")
            ]
            active_window = active_windows[0]
            table = next(
                item
                for item in active_window.descendants(class_name="SysListView32")
                if item.control_id() == int(control_id_text)
            )
            table.get_item(int(row_text), int(column_text)).double_click_input()
            time.sleep(args.wait)
        if (
            args.set_edit
            or args.click_control
            or args.post_click_control
            or args.async_click_control
            or args.raw_click_control
            or args.window_click
        ):
            action_windows = [
                window
                for window in app.windows()
                if window.is_visible()
                and not window.window_text().startswith("SRW2扩容版修改器")
            ]
            action_window = action_windows[0] if action_windows else app.top_window()
            if args.window_click:
                x_text, y_text = args.window_click.split(",", 1)
                action_window.click_input(coords=(int(x_text), int(y_text)))
                time.sleep(args.wait)
            for assignment in args.set_edit:
                control_id_text, value = assignment.split("=", 1)
                control = next(
                    item
                    for item in action_window.descendants(class_name="Edit")
                    if item.control_id() == int(control_id_text)
                )
                control.set_edit_text(value)
            for control_id in args.click_control:
                current_windows = [
                    window
                    for window in app.windows()
                    if window.is_visible()
                ]
                matches = [
                    item
                    for current_window in current_windows
                    for item in current_window.descendants()
                    if item.control_id() == control_id and item.is_visible()
                ]
                if not matches:
                    raise RuntimeError(f"Visible control ID {control_id} was not found")
                matches[0].click_input()
                time.sleep(args.wait)
            for control_id in args.post_click_control:
                matches = [
                    item
                    for current_window in app.windows()
                    if current_window.is_visible()
                    for item in current_window.descendants()
                    if item.control_id() == control_id and item.is_visible()
                ]
                if not matches:
                    raise RuntimeError(f"Visible control ID {control_id} was not found")
                matches[0].parent().post_message(
                    0x0111, control_id, matches[0].handle
                )  # WM_COMMAND / BN_CLICKED, asynchronous
                time.sleep(args.wait)
            for control_id in args.async_click_control:
                matches = [
                    item
                    for current_window in app.windows()
                    if current_window.is_visible()
                    for item in current_window.descendants()
                    if item.control_id() == control_id and item.is_visible()
                ]
                if not matches:
                    raise RuntimeError(f"Visible control ID {control_id} was not found")
                threading.Thread(
                    target=matches[0].click,
                    daemon=True,
                ).start()
                time.sleep(args.wait)
            for control_id in args.raw_click_control:
                matches = [
                    item
                    for current_window in app.windows()
                    if current_window.is_visible()
                    for item in current_window.descendants()
                    if item.control_id() == control_id and item.is_visible()
                ]
                if not matches:
                    raise RuntimeError(f"Visible control ID {control_id} was not found")
                win32gui.SetForegroundWindow(matches[0].top_level_parent().handle)
                time.sleep(0.2)
                point = matches[0].rectangle().mid_point()
                win32api.SetCursorPos((point.x, point.y))
                win32api.mouse_event(win32con.MOUSEEVENTF_LEFTDOWN, 0, 0)
                win32api.mouse_event(win32con.MOUSEEVENTF_LEFTUP, 0, 0)
                time.sleep(args.wait)
        if args.save:
            main_window = _main_editor_window(app)
            main_window.menu_select("文件->保存")
            time.sleep(args.wait)
            for window in app.windows():
                if not window.is_visible() or window == main_window:
                    continue
                buttons = window.descendants(class_name="Button")
                accepted = False
                for preferred in ("是", "确定", "保存"):
                    for button in buttons:
                        if button.window_text().replace("&", "") == preferred:
                            button.click()
                            accepted = True
                            time.sleep(args.wait)
                            break
                    if accepted:
                        break
    time.sleep(args.wait)

    desktop = Desktop(backend="win32")
    windows = []
    for window in desktop.windows():
        try:
            pid = window.process_id()
            title = window.window_text()
        except Exception:
            continue
        if (args.pid is not None and pid == args.pid) or "SRW2" in title:
            windows.append(window)

    report = {
        "requested_pid": args.pid,
        "window_count": len(windows),
        "windows": [],
    }
    if app is not None:
        try:
            report["main_menu"] = _menu_records(_main_editor_window(app).menu())
        except Exception as exc:
            report["main_menu_error"] = f"{type(exc).__name__}: {exc}"
        report["application_windows"] = [
            _control_record(window) for window in app.windows()
        ]
    inspected_pids: set[int] = set()
    for window in windows:
        window_record = _control_record(window)
        window_record["pid"] = window.process_id()
        inspected_pids.add(window.process_id())
        window_record["controls"] = [
            _control_record(control) for control in window.descendants()
        ]
        report["windows"].append(window_record)
        try:
            safe_title = "".join(
                character if character.isalnum() else "_"
                for character in str(window_record.get("text", "window"))
            )[:40]
            window.capture_as_image().save(audit_dir / f"ui-{safe_title}.png")
        except Exception:
            pass

    output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

    if not args.keep_open:
        for pid in inspected_pids:
            try:
                Application(backend="win32").connect(process=pid).kill(soft=False)
            except Exception:
                pass
        if app is not None:
            try:
                app.kill(soft=False)
            except Exception:
                pass
    return 0 if windows else 2


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception:
        repo_dir = Path(__file__).resolve().parents[1]
        error_file = (
            repo_dir
            / "output"
            / "build"
            / "legacy-diff-audit"
            / "ui-audit-error.txt"
        )
        error_file.write_text(traceback.format_exc(), encoding="utf-8")
        if _ACTIVE_PID is not None:
            try:
                Application(backend="win32").connect(process=_ACTIVE_PID).kill(
                    soft=False
                )
            except Exception:
                pass
        raise
