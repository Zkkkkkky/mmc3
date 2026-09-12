"""Verify all 24 legacy item prices with isolated save/reopen experiments."""

from __future__ import annotations

import json
import shutil
import time
import traceback
from pathlib import Path

from pywinauto import Desktop
from pywinauto.application import Application, process_module


NORMALIZATION = {0x4A101, 0x4A102, 0x4AE2A, 0x4AE2B, 0x79538, 0x79539}


def _editor(app: Application, require_data_menu: bool = True):
    deadline = time.monotonic() + 15
    while time.monotonic() < deadline:
        for window in Desktop(backend="win32").windows():
            try:
                if not window.is_visible() or not window.window_text().startswith(
                    "SRW2扩容版修改器"
                ):
                    continue
                if not require_data_menu or any(
                    item.text().startswith("数据") for item in window.menu().items()
                ):
                    return window
            except Exception:
                continue
        time.sleep(0.25)
    raise RuntimeError("Legacy editor window was not found")


def _dialog(app: Application, title: str):
    deadline = time.monotonic() + 12
    while time.monotonic() < deadline:
        for window in Desktop(backend="win32").windows():
            try:
                if window.is_visible() and window.window_text() == title:
                    return window
            except Exception:
                continue
        time.sleep(0.25)
    raise RuntimeError(f"Legacy dialog was not found: {title}")


def _click_id(window, control_id: int) -> None:
    next(
        item for item in window.descendants() if item.control_id() == control_id
    ).click_input()


def _edit_id(window, control_id: int, value: str) -> None:
    next(
        item
        for item in window.descendants(class_name="Edit")
        if item.control_id() == control_id
    ).set_edit_text(value)


def _read_id(window, control_id: int) -> str:
    return next(
        item
        for item in window.descendants(class_name="Edit")
        if item.control_id() == control_id
    ).window_text()


def _open_rom(app: Application, path: Path) -> None:
    last_error: Exception | None = None
    for _attempt in range(3):
        try:
            main = _editor(app, require_data_menu=False)
            main.menu_select("文件->打开")
            dialog = Desktop(backend="win32").window(title_re="打开.*")
            dialog.wait("visible enabled", timeout=8)
            break
        except Exception as exc:
            last_error = exc
            time.sleep(0.5)
    else:
        raise RuntimeError("Unable to open the legacy ROM picker") from last_error
    edits = [
        item
        for item in dialog.descendants(class_name="Edit")
        if item.is_visible() and item.is_enabled()
    ]
    edits[-1].set_edit_text(str(path))
    dialog.type_keys("{ENTER}")
    time.sleep(1.0)


def _open_items(app: Application):
    last_error: Exception | None = None
    for _attempt in range(3):
        try:
            _editor(app).menu_select("数据->数据库")
            break
        except Exception as exc:
            last_error = exc
            time.sleep(0.5)
    else:
        raise RuntimeError("Unable to open the legacy database") from last_error
    time.sleep(0.6)
    database = _dialog(app, "数据库")
    database.click_input(coords=(485, 62))
    time.sleep(0.5)
    return database


def _select_item(database, row: int) -> None:
    table = next(
        item
        for item in database.descendants(class_name="SysListView32")
        if item.control_id() == 1690
    )
    table.set_focus()
    # The Easy Language ListView ignores programmatic item selection. Scroll
    # the target into view and send a physical click through the parent window.
    item = table.get_item(row, 0)
    target_label = item.text()
    target_name = target_label.split("：", 1)[-1]
    item.ensure_visible()
    top_index = int(table.send_message(0x1027))  # LVM_GETTOPINDEX
    base_y = 165 + (row - top_index) * 25
    for delta in (0, -8, 8, -15, 15):
        database.click_input(coords=(100, base_y + delta))
        time.sleep(0.35)
        if _read_id(database, 1710) == target_name:
            return
    raise RuntimeError(
        f"Unable to select item {row + 1:02d}: expected {target_name!r}, "
        f"got {_read_id(database, 1710)!r}"
    )


def _diff(before: bytes, after: bytes) -> list[dict[str, int]]:
    return [
        {"offset": index, "before": old, "after": new}
        for index, (old, new) in enumerate(zip(before, after))
        if old != new
    ]


def _stop(app: Application | None) -> None:
    if app is not None:
        try:
            app.kill(soft=False)
        except Exception:
            pass
    try:
        windows = Desktop(backend="win32").windows()
    except Exception:
        windows = []
    for window in windows:
        try:
            executable = Path(process_module(window.process_id())).resolve()
            if (
                window.window_text().startswith("SRW2扩容版修改器")
                and executable.parent.name == "legacy-diff-audit"
                and executable.name == "SRW2_patched.exe"
            ):
                Application(backend="win32").connect(
                    process=window.process_id()
                ).kill(soft=False)
        except Exception:
            pass


def _launch(audit: Path) -> Application:
    last_error: Exception | None = None
    for _attempt in range(3):
        app = None
        try:
            app = Application(backend="win32").start(
                str(audit / "SRW2_patched.exe"), work_dir=str(audit), timeout=30
            )
            time.sleep(2)
            landing = app.top_window()
            landing.restore()
            landing.move_window(x=30, y=30, width=1200, height=850, repaint=True)
            landing.set_focus()
            next(
                button
                for button in landing.descendants(class_name="Button")
                if button.window_text() == "进入修改器"
            ).click_input()
            time.sleep(4)
            _editor(app, require_data_menu=False)
            return app
        except Exception as exc:
            last_error = exc
            _stop(app)
            time.sleep(1)
    raise RuntimeError("Unable to launch the isolated legacy editor") from last_error


def main() -> int:
    repo = Path(__file__).resolve().parents[1]
    audit = repo / "output" / "build" / "legacy-diff-audit"
    baseline_path = audit / "audit.nes"
    case_root = audit / "cases" / "legacy_item_prices"
    report_path = audit / "legacy-item-price-results.json"
    progress_path = audit / "legacy-item-price-progress.txt"
    case_root.mkdir(parents=True, exist_ok=True)
    baseline = baseline_path.read_bytes()
    app = None
    if report_path.exists():
        loaded = json.loads(report_path.read_text(encoding="utf-8"))
        results: list[dict[str, object]] = [
            item for item in loaded if item.get("passed") is True
        ]
    else:
        results = []
    try:
        for row in range(24):
            if row < len(results):
                continue
            case_dir = case_root / f"item_{row + 1:02d}"
            case_dir.mkdir(parents=True, exist_ok=True)
            before_path = case_dir / "before.nes"
            after_path = case_dir / "after.nes"
            before_path.write_bytes(baseline)
            shutil.copyfile(before_path, after_path)

            app = _launch(audit)
            _open_rom(app, after_path)
            database = _open_items(app)
            _select_item(database, row)
            old_display = int(_read_id(database, 1730))
            new_display = old_display + 10 if old_display <= 99980 else old_display - 10
            _edit_id(database, 1730, str(new_display))
            _click_id(database, 590)
            time.sleep(0.4)
            _editor(app).menu_select("文件->保存")
            time.sleep(0.7)
            _stop(app)
            app = None

            saved = after_path.read_bytes()
            differences = _diff(baseline, saved)
            target_offset = 0x15723 + row * 2
            changed_offsets = {item["offset"] for item in differences}
            allowed = NORMALIZATION | {target_offset, target_offset + 1}

            app = _launch(audit)
            _open_rom(app, after_path)
            database = _open_items(app)
            _select_item(database, row)
            reopened_display = int(_read_id(database, 1730))
            _click_id(database, 600)
            time.sleep(0.2)
            _stop(app)
            app = None

            passed = (
                reopened_display == new_display
                and target_offset in changed_offsets
                and changed_offsets <= allowed
            )
            result = {
                "item": row + 1,
                "old_display": old_display,
                "new_display": new_display,
                "reopened_display": reopened_display,
                "target_offset": target_offset,
                "differences": differences,
                "passed": passed,
            }
            results.append(result)
            report_path.write_text(
                json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8"
            )
            progress_path.write_text(
                f"progress: {len(results)}/24, latest={row + 1:02d}, passed={passed}\n",
                encoding="utf-8",
            )
            if not passed:
                return 1

        progress_path.write_text("complete: 24/24, passed=True\n", encoding="utf-8")
        return 0
    except Exception:
        progress_path.write_text(traceback.format_exc(), encoding="utf-8")
        raise
    finally:
        _stop(app)


if __name__ == "__main__":
    raise SystemExit(main())
