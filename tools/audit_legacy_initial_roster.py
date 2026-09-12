"""Verify each legacy initial-roster selector with an isolated ROM copy."""

from __future__ import annotations

import json
import shutil
import time
import traceback
from pathlib import Path

from pywinauto.application import Application

from audit_legacy_global_fields import (
    LEGACY_NORMALIZATION_OFFSETS,
    _click_id,
    _dialog,
    _diff,
    _editor,
    _open_other,
    _open_rom,
)


CONTROL_IDS = (380, 500, 400, 520, 420, 540, 440, 560, 460, 580, 480, 600)
ROSTER_OFFSET = 0x3965D


def _combo(window, control_id: int):
    return next(
        item
        for item in window.descendants(class_name="ComboBox")
        if item.control_id() == control_id
    )


def _displayed_id(combo) -> int:
    return int(combo.window_text().split("：", 1)[0])


def main() -> int:
    repo = Path(__file__).resolve().parents[1]
    audit = repo / "output" / "build" / "legacy-diff-audit"
    baseline_path = audit / "audit.nes"
    cases_dir = audit / "cases" / "legacy_initial_roster"
    report_path = audit / "legacy-initial-roster-results.json"
    progress_path = audit / "legacy-initial-roster-progress.txt"
    cases_dir.mkdir(parents=True, exist_ok=True)
    baseline = baseline_path.read_bytes()
    results = []
    app = None

    try:
        app = Application(backend="win32").start(
            str(audit / "SRW2_patched.exe"), work_dir=str(audit), timeout=30
        )
        time.sleep(2)
        landing = app.top_window()
        enter = next(
            button
            for button in landing.descendants(class_name="Button")
            if button.window_text() == "进入修改器"
        )
        enter.click()
        time.sleep(4)
        app = Application(backend="win32").connect(process=app.process, timeout=15)

        for index, control_id in enumerate(CONTROL_IDS):
            kind = "character" if index % 2 == 0 else "unit"
            slot = index // 2 + 1
            name = f"slot_{slot}_{kind}"
            case_dir = cases_dir / name
            case_dir.mkdir(parents=True, exist_ok=True)
            before_path = case_dir / "before.nes"
            after_path = case_dir / "after.nes"
            before_path.write_bytes(baseline)
            shutil.copyfile(before_path, after_path)

            _open_rom(app, after_path)
            other = _open_other(app)
            combo = _combo(other, control_id)
            displayed_before = _displayed_id(combo)
            selected_before = combo.selected_index()
            combo.select(selected_before + 1)
            expected_new = _displayed_id(combo)
            _click_id(other, 320)
            time.sleep(0.5)
            _editor(app).menu_select("文件->保存")
            time.sleep(1.0)

            saved = after_path.read_bytes()
            differences = _diff(baseline, saved)
            changed_offsets = {item["offset"] for item in differences}
            target_offset = ROSTER_OFFSET + index

            _open_rom(app, after_path)
            other = _open_other(app)
            displayed_after = _displayed_id(_combo(other, control_id))
            _click_id(other, 330)
            time.sleep(0.3)

            allowed = {target_offset} | set(LEGACY_NORMALIZATION_OFFSETS)
            results.append(
                {
                    "case": name,
                    "control_id": control_id,
                    "target_offset": target_offset,
                    "displayed_before": displayed_before,
                    "rom_before": baseline[target_offset],
                    "selected_index_before": selected_before,
                    "requested_new": expected_new,
                    "displayed_after_reopen": displayed_after,
                    "rom_after": saved[target_offset],
                    "diffs": differences,
                    "target_offset_changed": target_offset in changed_offsets,
                    "only_target_or_normalization": changed_offsets.issubset(allowed),
                    "reopen_matches": displayed_after == expected_new,
                }
            )
            report_path.write_text(
                json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8"
            )
            progress_path.write_text(
                f"{index + 1}/{len(CONTROL_IDS)} {name}\n", encoding="utf-8"
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
        result["displayed_before"] == result["rom_before"]
        and result["rom_after"] == result["requested_new"]
        and result["target_offset_changed"]
        and result["only_target_or_normalization"]
        and result["reopen_matches"]
        for result in results
    )
    progress_path.write_text(
        f"complete: {len(results)}/{len(CONTROL_IDS)}, passed={passed}\n",
        encoding="utf-8",
    )
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
