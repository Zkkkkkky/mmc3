"""Run isolated, one-field-at-a-time legacy global-setting save experiments."""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import time
import traceback
from dataclasses import dataclass
from pathlib import Path

from pywinauto import Desktop
from pywinauto.application import Application


@dataclass(frozen=True)
class Case:
    name: str
    control_id: int
    old_value: int
    new_value: int
    expected_offsets: tuple[int, ...]


CASES = (
    Case("double_hit_attack_percent", 340, 70, 71, (0x78109, 0x7815A)),
    Case("double_hit_defense_percent", 650, 90, 91, (0x78127, 0x78178)),
    Case("double_hit_bonus", 670, 20, 21, (0x78138, 0x78189)),
    Case("damage_strength_multiplier", 690, 13, 14, (0x780E4,)),
    Case("damage_strength_divisor", 720, 10, 11, (0x780EB,)),
    Case("damage_weapon_multiplier", 770, 3, 4, (0x780C5,)),
    Case("damage_defense_multiplier", 730, 1, 2, (0x9999,)),
    Case("damage_defense_divisor", 800, 1, 2, (0x99A0,)),
    Case("hit_threshold", 830, 70, 71, (0xA44E,)),
    Case("item_01", 350, 1, 2, (0x140CF,)),
    Case("item_02", 360, 1, 2, (0x140D6,)),
    Case("item_03", 160, 1, 2, (0x140DD,)),
    Case("item_04", 120, 5, 6, (0x140E4,)),
    Case("item_05", 180, 3, 4, (0x140EB,)),
    Case("item_06", 200, 1, 2, (0x140F2,)),
    Case("item_07", 220, 3, 4, (0x140F9,)),
    Case("item_08", 250, 3, 4, (0x14100,)),
    Case("item_09", 260, 10, 11, (0x14107,)),
    Case("item_10", 280, 20, 21, (0x1410E,)),
    Case("item_11", 310, 100, 101, (0x14115,)),
)

LEGACY_NORMALIZATION_OFFSETS = (0x4A101, 0x4A102, 0x4AE2A, 0x4AE2B, 0x79538, 0x79539)


def _editor(app: Application):
    deadline = time.monotonic() + 12
    while time.monotonic() < deadline:
        try:
            current = Application(backend="win32").connect(
                process=app.process, timeout=2
            )
            windows = current.windows()
        except Exception:
            windows = app.windows()
        for window in windows:
            try:
                if window.is_visible() and window.window_text().startswith(
                    "SRW2扩容版修改器"
                ):
                    return window
            except Exception:
                continue
        for window in Desktop(backend="win32").windows():
            try:
                if window.is_visible() and window.window_text().startswith(
                    "SRW2扩容版修改器"
                ):
                    return window
            except Exception:
                continue
        time.sleep(0.25)
    raise RuntimeError("Legacy editor window was not found")


def _dialog(app: Application, title: str):
    deadline = time.monotonic() + 12
    while time.monotonic() < deadline:
        try:
            current = Application(backend="win32").connect(
                process=app.process, timeout=2
            )
            windows = current.windows()
        except Exception:
            windows = app.windows()
        for window in windows:
            try:
                if window.is_visible() and window.window_text() == title:
                    return window
            except Exception:
                continue
        time.sleep(0.25)
    raise RuntimeError(f"Legacy dialog was not found: {title}")


def _click_id(window, control_id: int) -> None:
    control = next(item for item in window.descendants() if item.control_id() == control_id)
    control.click()


def _open_rom(app: Application, path: Path) -> None:
    main = _editor(app)
    main.menu_select("文件->打开")
    dialog = Desktop(backend="win32").window(
        process=main.process_id(), title_re="打开.*"
    )
    dialog.wait("visible enabled", timeout=15)
    edits = [
        edit
        for edit in dialog.descendants(class_name="Edit")
        if edit.is_visible() and edit.is_enabled()
    ]
    if not edits:
        raise RuntimeError("Open dialog has no visible filename field")
    edits[-1].set_edit_text(str(path))
    dialog.type_keys("{ENTER}")
    time.sleep(1.2)


def _open_other(app: Application):
    _editor(app).menu_select("数据->其他")
    time.sleep(0.8)
    return _dialog(app, "其他")


def _edit_value(window, control_id: int, value: int) -> None:
    control = next(
        item
        for item in window.descendants(class_name="Edit")
        if item.control_id() == control_id
    )
    control.set_edit_text(str(value))


def _read_value(window, control_id: int) -> int:
    control = next(
        item
        for item in window.descendants(class_name="Edit")
        if item.control_id() == control_id
    )
    return int(control.window_text())


def _diff(before: bytes, after: bytes) -> list[dict[str, int]]:
    return [
        {"offset": index, "before": old, "after": new}
        for index, (old, new) in enumerate(zip(before, after))
        if old != new
    ]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--start", type=int, default=1)
    parser.add_argument("--reclassify-only", action="store_true")
    args = parser.parse_args()
    repo = Path(__file__).resolve().parents[1]
    audit = repo / "output" / "build" / "legacy-diff-audit"
    baseline_path = audit / "audit.nes"
    cases_dir = audit / "cases" / "legacy_globals"
    report_path = audit / "legacy-global-field-results.json"
    progress_path = audit / "legacy-global-field-progress.txt"
    cases_dir.mkdir(parents=True, exist_ok=True)
    baseline = baseline_path.read_bytes()
    if args.reclassify_only:
        results = json.loads(report_path.read_text(encoding="utf-8"))
        for result, case in zip(results, CASES):
            changed_offsets = {item["offset"] for item in result["diffs"]}
            expected = set(case.expected_offsets)
            allowed = expected | set(LEGACY_NORMALIZATION_OFFSETS)
            result["expected_offsets"] = list(case.expected_offsets)
            result["target_offsets_changed"] = expected.issubset(changed_offsets)
            result["only_expected_or_normalization"] = changed_offsets.issubset(allowed)
            result["unexpected_offsets"] = sorted(changed_offsets - allowed)
        report_path.write_text(
            json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        passed = all(
            result["displayed_before"] == result["requested_old"]
            and result["target_offsets_changed"]
            and result["reopen_matches"]
            for result in results
        )
        progress_path.write_text(
            f"complete: {len(results)}/{len(CASES)}, passed={passed}\n",
            encoding="utf-8",
        )
        return 0 if passed else 1
    if args.start > 1 and report_path.exists():
        results = json.loads(report_path.read_text(encoding="utf-8"))
        results = results[: args.start - 1]
    else:
        results: list[dict[str, object]] = []
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

        for index, case in enumerate(CASES, start=1):
            if index < args.start:
                continue
            case_dir = cases_dir / case.name
            case_dir.mkdir(parents=True, exist_ok=True)
            before_path = case_dir / "before.nes"
            after_path = case_dir / "after.nes"
            before_path.write_bytes(baseline)
            shutil.copyfile(before_path, after_path)

            _open_rom(app, after_path)
            other = _open_other(app)
            displayed_before = _read_value(other, case.control_id)
            _edit_value(other, case.control_id, case.new_value)
            _click_id(other, 320)
            time.sleep(0.5)
            _editor(app).menu_select("文件->保存")
            time.sleep(1.0)

            saved = after_path.read_bytes()
            differences = _diff(baseline, saved)
            changed_offsets = tuple(item["offset"] for item in differences)
            expected = set(case.expected_offsets)
            allowed = expected | set(LEGACY_NORMALIZATION_OFFSETS)

            _open_rom(app, after_path)
            other = _open_other(app)
            displayed_after = _read_value(other, case.control_id)
            _click_id(other, 330)
            time.sleep(0.3)

            result = {
                "case": case.name,
                "control_id": case.control_id,
                "requested_old": case.old_value,
                "requested_new": case.new_value,
                "displayed_before": displayed_before,
                "displayed_after_reopen": displayed_after,
                "expected_offsets": list(case.expected_offsets),
                "diffs": differences,
                "target_offsets_changed": expected.issubset(changed_offsets),
                "only_expected_or_normalization": set(changed_offsets).issubset(allowed),
                "unexpected_offsets": sorted(set(changed_offsets) - allowed),
                "reopen_matches": displayed_after == case.new_value,
                "sha256": hashlib.sha256(saved).hexdigest(),
            }
            results.append(result)
            report_path.write_text(
                json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8"
            )
            progress_path.write_text(
                f"{index}/{len(CASES)} {case.name}\n", encoding="utf-8"
            )
    except Exception:
        visible = []
        if app is not None:
            for window in app.windows():
                try:
                    if window.is_visible():
                        visible.append(
                            {
                                "title": window.window_text(),
                                "enabled": window.is_enabled(),
                                "controls": [
                                    {
                                        "text": control.window_text(),
                                        "class": control.class_name(),
                                        "id": control.control_id(),
                                        "visible": control.is_visible(),
                                    }
                                    for control in window.descendants()
                                    if control.is_visible()
                                ],
                            }
                        )
                except Exception:
                    continue
        progress_path.write_text(
            traceback.format_exc()
            + "\nVISIBLE_WINDOWS\n"
            + json.dumps(visible, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        try:
            from PIL import ImageGrab

            ImageGrab.grab(all_screens=True).save(audit / "legacy-global-error.png")
        except Exception:
            pass
        raise
    finally:
        if app is not None:
            try:
                app.kill(soft=False)
            except Exception:
                pass

    passed = all(
        result["displayed_before"] == result["requested_old"]
        and result["target_offsets_changed"]
        and result["reopen_matches"]
        for result in results
    )
    progress_path.write_text(
        f"complete: {len(results)}/{len(CASES)}, passed={passed}\n", encoding="utf-8"
    )
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
