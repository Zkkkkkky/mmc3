"""Read every preserved 8 KiB SAV in the reference M16 editor."""

from __future__ import annotations

import json
import sys
import time
import traceback
from pathlib import Path

ROOT_HINT = Path(__file__).resolve().parents[2]
if str(ROOT_HINT) not in sys.path:
    sys.path.insert(0, str(ROOT_HINT))

from tools.research import probe_m16_reference_controls as controls


OUT = controls.ROOT / "output" / "verification" / "legacy-m16-reference-save-candidates-20260920"
RESULT = OUT / "candidates.json"


def open_path(driver, path: Path) -> None:
    controls.SAVE = path
    controls.load_save(driver)


def dismiss_errors(driver) -> list[str]:
    messages = []
    for window in driver.app.windows():
        try:
            if not window.is_visible() or window.class_name() != "#32770":
                continue
            texts = [
                item.window_text() for item in window.descendants()
                if item.is_visible() and item.window_text()
            ]
            messages.extend(texts)
            buttons = [
                item for item in window.descendants(class_name="Button")
                if item.is_visible() and item.is_enabled()
            ]
            if buttons:
                buttons[0].click()
                time.sleep(0.1)
        except Exception:
            continue
    return messages


def main() -> int:
    controls.prepare()
    OUT.mkdir(parents=True, exist_ok=True)
    candidates = sorted(
        path for path in (controls.ROOT / "references" / "emulator-state" / "fceux" / "sav").glob("*.sav")
        if path.stat().st_size == 8192
    )
    results = []
    for path in candidates:
        driver = controls.Win32LegacyDriver()
        try:
            driver.launch(controls.RUNTIME / "SRW2_patched.exe", controls.RUNTIME)
            driver.open_rom(controls.ROM)
            controls.open_save_editor(driver)
            open_path(driver, path)
            slot = driver._control(140, "ComboBox")
            chapter = driver._control(120, "ComboBox")
            upper = driver._control(100, "SysListView32")
            lower = driver._control(110, "SysListView32")
            record = {
                    "path": path.relative_to(controls.ROOT).as_posix(),
                    "sha256": controls.sha256(path),
                    "slot_selected": slot.window_text(),
                    "slot_items": slot.item_texts(),
                    "chapter": chapter.window_text(),
                    "upper_rows": int(upper.item_count()),
                    "lower_rows": int(lower.item_count()),
                    "upper_first": [
                        upper.get_item(0, column).text()
                        for column in range(int(upper.column_count()))
                    ] if upper.item_count() else [],
                    "lower_first": [
                        lower.get_item(0, column).text()
                        for column in range(int(lower.column_count()))
                    ] if lower.item_count() else [],
                }
            record["dialogs"] = dismiss_errors(driver)
            results.append(record)
        except Exception as exc:
            results.append(
                {
                    "path": path.relative_to(controls.ROOT).as_posix(),
                    "sha256": controls.sha256(path),
                    "probe_error": repr(exc),
                }
            )
        finally:
            driver.stop()
        try:
            RESULT.write_text(
                json.dumps({"passed": False, "count": len(results), "candidates": results}, ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )
        except OSError:
            pass
        time.sleep(0.1)
    RESULT.write_text(
        json.dumps({"passed": True, "count": len(results), "candidates": results}, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception:
        OUT.mkdir(parents=True, exist_ok=True)
        (OUT / "error.log").write_text(traceback.format_exc(), encoding="utf-8")
        raise
