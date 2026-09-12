"""Discover and verify the reference editor's maximum-level storage."""

from __future__ import annotations

import json
import shutil
import time
import traceback
from pathlib import Path

from pywinauto.application import Application

from audit_legacy_global_fields import _click_id, _diff, _editor, _open_rom
from audit_legacy_other1_tables import _control, _database, _open_other1


def _level_dialog(app: Application):
    deadline = time.monotonic() + 10
    while time.monotonic() < deadline:
        current = Application(backend="win32").connect(process=app.process, timeout=2)
        for window in current.windows():
            try:
                if window.is_visible() and window.window_text() == "最大值":
                    return window
            except Exception:
                continue
        time.sleep(0.2)
    raise RuntimeError("Maximum-level dialog was not found")


def main() -> int:
    repo = Path(__file__).resolve().parents[1]
    audit = repo / "output" / "build" / "legacy-diff-audit"
    case_dir = audit / "cases" / "legacy_level_cap"
    case_dir.mkdir(parents=True, exist_ok=True)
    before_path = case_dir / "before.nes"
    after_path = case_dir / "after.nes"
    baseline = (audit / "audit.nes").read_bytes()
    before_path.write_bytes(baseline)
    shutil.copyfile(before_path, after_path)
    report_path = audit / "legacy-level-cap-result.json"
    progress_path = audit / "legacy-level-cap-progress.txt"
    app = None

    try:
        app = Application(backend="win32").start(
            str(audit / "SRW2_patched.exe"), work_dir=str(audit), timeout=30
        )
        time.sleep(2)
        landing = app.top_window()
        next(
            button
            for button in landing.descendants(class_name="Button")
            if button.window_text() == "进入修改器"
        ).click()
        time.sleep(4)
        app = Application(backend="win32").connect(process=app.process, timeout=15)

        _open_rom(app, after_path)
        database = _open_other1(app)
        _click_id(database, 1680)
        maximum = _level_dialog(app)
        displayed_before = int(_control(maximum, "Edit", 120).window_text())
        requested_new = displayed_before + 1
        _control(maximum, "Edit", 120).set_edit_text(str(requested_new))
        _click_id(maximum, 100)
        time.sleep(0.5)
        database = _database(app)
        _click_id(database, 590)
        time.sleep(0.8)
        _editor(app).menu_select("文件->保存")
        time.sleep(1.0)
        saved = after_path.read_bytes()

        _open_rom(app, after_path)
        database = _open_other1(app)
        _click_id(database, 1680)
        maximum = _level_dialog(app)
        displayed_after = int(_control(maximum, "Edit", 120).window_text())
        _click_id(maximum, 110)
        time.sleep(0.3)
        _click_id(_database(app), 600)

        differences = _diff(baseline, saved)
        report = {
            "displayed_before": displayed_before,
            "requested_new": requested_new,
            "displayed_after_reopen": displayed_after,
            "reopen_matches": displayed_after == requested_new,
            "diffs": differences,
        }
        report_path.write_text(
            json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        passed = report["reopen_matches"] and bool(differences)
        progress_path.write_text(f"complete: passed={passed}\n", encoding="utf-8")
        return 0 if passed else 1
    except Exception:
        progress_path.write_text(traceback.format_exc(), encoding="utf-8")
        raise
    finally:
        if app is not None:
            try:
                app.kill(soft=False)
            except Exception:
                pass


if __name__ == "__main__":
    raise SystemExit(main())
