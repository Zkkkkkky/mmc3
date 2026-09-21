"""Verify reference saves at both boundaries of the Other-1 numeric tables."""

from __future__ import annotations

import json
import shutil
import time
import traceback
from dataclasses import dataclass
from pathlib import Path

from pywinauto.application import Application

from audit_legacy_global_fields import (
    _click_id,
    _diff,
    _editor,
    _open_rom,
)


@dataclass(frozen=True)
class Case:
    name: str
    tab: str
    selector_index: int
    row_index: int
    edit_id: int
    expected_offset: int
    byte_width: int


CASES = (
    Case("distance_first", "distance", 0, 0, 1640, 0xB642, 1),
    Case("distance_last", "distance", 3, 15, 1640, 0xB642 + 63, 1),
    Case("experience_level_2", "experience", 0, 1, 1620, 0, 2),
    Case("experience_level_60", "experience", 0, 59, 1620, 0, 2),
)


def _database(app: Application):
    deadline = time.monotonic() + 12
    while time.monotonic() < deadline:
        current = Application(backend="win32").connect(process=app.process, timeout=2)
        for window in current.windows():
            try:
                if window.is_visible() and window.window_text() == "数据库":
                    return window
            except Exception:
                continue
        time.sleep(0.25)
    raise RuntimeError("Database dialog was not found")


def _open_other1(app: Application):
    _editor(app).menu_select("数据->数据库")
    database = _database(app)
    database.click_input(coords=(390, 62))
    time.sleep(0.8)
    return database


def _control(window, class_name: str, control_id: int):
    return next(
        item
        for item in window.descendants(class_name=class_name)
        if item.control_id() == control_id
    )


def _select_case(database, case: Case) -> None:
    if case.tab == "distance":
        _control(database, "ComboBox", 1600).select(case.selector_index)
        time.sleep(0.2)
        table = _control(database, "SysListView32", 1580)
    else:
        table = _control(database, "SysListView32", 1570)
    table.click_input(coords=(35, 45))
    table.type_keys("{HOME}")
    if case.row_index:
        table.type_keys(f"{{DOWN {case.row_index}}}")
    time.sleep(0.3)


def _read_edit(database, control_id: int) -> int:
    return int(_control(database, "Edit", control_id).window_text())


def main() -> int:
    repo = Path(__file__).resolve().parents[1]
    audit = repo / "output" / "build" / "legacy-diff-audit"
    baseline = (audit / "audit.nes").read_bytes()
    cases_dir = audit / "cases" / "legacy_other1"
    report_path = audit / "legacy-other1-results.json"
    progress_path = audit / "legacy-other1-progress.txt"
    cases_dir.mkdir(parents=True, exist_ok=True)
    results = []
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

        for index, case in enumerate(CASES, start=1):
            case_dir = cases_dir / case.name
            case_dir.mkdir(parents=True, exist_ok=True)
            before_path = case_dir / "before.nes"
            after_path = case_dir / "after.nes"
            before_path.write_bytes(baseline)
            shutil.copyfile(before_path, after_path)

            _open_rom(app, after_path)
            database = _open_other1(app)
            _select_case(database, case)
            displayed_before = _read_edit(database, case.edit_id)
            requested_new = displayed_before - 1 if displayed_before == 100 else displayed_before + 1
            _control(database, "Edit", case.edit_id).set_edit_text(str(requested_new))
            _click_id(database, 590)
            time.sleep(0.8)
            _editor(app).menu_select("文件->保存")
            time.sleep(1.0)

            saved = after_path.read_bytes()
            differences = _diff(baseline, saved)
            changed_offsets = {item["offset"] for item in differences}
            target_offsets = (
                set(range(case.expected_offset, case.expected_offset + case.byte_width))
                if case.expected_offset
                else set()
            )

            _open_rom(app, after_path)
            database = _open_other1(app)
            _select_case(database, case)
            displayed_after = _read_edit(database, case.edit_id)
            _click_id(database, 600)
            time.sleep(0.3)

            results.append(
                {
                    "case": case.name,
                    "displayed_before": displayed_before,
                    "requested_new": requested_new,
                    "displayed_after_reopen": displayed_after,
                    "expected_offset": case.expected_offset,
                    "byte_width": case.byte_width,
                    "diffs": differences,
                    "target_changed": (
                        bool(changed_offsets & target_offsets)
                        if target_offsets
                        else bool(changed_offsets)
                    ),
                    "reopen_matches": displayed_after == requested_new,
                }
            )
            report_path.write_text(
                json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8"
            )
            progress_path.write_text(
                f"{index}/{len(CASES)} {case.name}\n", encoding="utf-8"
            )
    except Exception:
        progress_path.write_text(traceback.format_exc(), encoding="utf-8")
        raise
    finally:
        if app is not None:
            try:
                app.kill(soft=False)
            except Exception:
                pass

    passed = all(
        result["target_changed"] and result["reopen_matches"] for result in results
    )
    progress_path.write_text(
        f"complete: {len(results)}/{len(CASES)}, passed={passed}\n",
        encoding="utf-8",
    )
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
