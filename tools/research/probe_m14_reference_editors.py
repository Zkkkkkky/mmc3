"""Open representative M14 row editors and archive their runtime controls."""

from __future__ import annotations

import json
import sys
import time
import traceback
from pathlib import Path

ROOT_HINT = Path(__file__).resolve().parents[2]
if str(ROOT_HINT) not in sys.path:
    sys.path.insert(0, str(ROOT_HINT))

from tools.research import probe_m14_reference_catalog as base
from tools.research.probe_m16_reference_controls import visible_controls


OUT = base.ROOT / "output/verification/legacy-m14-reference-editors-20260920"
RESULT = OUT / "editors.json"


def windows(driver) -> list[dict[str, object]]:
    result = []
    for window in driver.app.windows():
        try:
            if window.is_visible():
                result.append(
                    {
                        "handle": int(window.handle),
                        "class": window.class_name(),
                        "title": window.window_text(),
                        "controls": visible_controls(window),
                    }
                )
        except Exception:
            continue
    return result


def dismiss_new(driver, known: set[int]) -> None:
    for window in driver.app.windows():
        try:
            if not window.is_visible() or int(window.handle) in known:
                continue
            buttons = [
                control for control in window.descendants(class_name="Button")
                if control.is_visible() and control.is_enabled()
            ]
            cancel = next((item for item in buttons if item.control_id() in (2, 100, 110)), None)
            if cancel:
                cancel.click()
            elif buttons:
                buttons[0].click()
            else:
                window.type_keys("{ESC}", set_foreground=True)
            time.sleep(0.15)
        except Exception:
            continue


def probe_list(driver, control_id: int, row: int, label: str) -> dict[str, object]:
    control = base.any_control(driver, control_id, "ListBox")
    base.select_list(control, row)
    before = windows(driver)
    known = {int(item["handle"]) for item in before}
    rect = control.item_rect(row)
    control.double_click_input(coords=((rect.left + rect.right) // 2, (rect.top + rect.bottom) // 2))
    time.sleep(0.5)
    after = windows(driver)
    new = [item for item in after if int(item["handle"]) not in known]
    result = {
        "label": label,
        "control_id": control_id,
        "row": row,
        "row_text": control.item_texts()[row],
        "new_windows": new,
    }
    dismiss_new(driver, known)
    return result


def main() -> int:
    base.prepare()
    baseline = base.sha(base.ROM)
    driver = base.Win32LegacyDriver()
    probes = []
    try:
        driver.launch(base.RUNTIME / "SRW2_patched.exe", base.RUNTIME)
        driver.open_rom(base.ROM)
        base.open_editor(driver)
        base.page(driver, 0)
        chapters = base.any_control(driver, 220, "ListBox")
        base.select_list(chapters, 0)
        probes.extend(
            probe_list(driver, control_id, 0, label)
            for control_id, label in ((140, "chapter_phase_0"), (150, "chapter_phase_1"), (160, "chapter_phase_2"))
        )
        base.page(driver, 1)
        actions = base.any_control(driver, 260, "ListBox")
        base.select_list(actions, 0)
        probes.append(probe_list(driver, 240, 0, "action_instruction"))
        base.page(driver, 2)
        surrender = base.any_control(driver, 310, "ListBox")
        base.select_list(surrender, 0)
        probes.append(probe_list(driver, 290, 0, "surrender_instruction"))
        base.page(driver, 3)
        maps = base.any_control(driver, 360, "ListBox")
        base.select_list(maps, 0)
        probes.append(probe_list(driver, 340, 0, "map_instruction"))
        result = {"passed": True, "probes": probes}
    finally:
        driver.stop()
    result["rom_unchanged"] = base.sha(base.ROM) == baseline
    result["passed"] = bool(result["passed"] and result["rom_unchanged"])
    OUT.mkdir(parents=True, exist_ok=True)
    RESULT.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return 0 if result["passed"] else 1


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception:
        OUT.mkdir(parents=True, exist_ok=True)
        (OUT / "error.log").write_text(traceback.format_exc(), encoding="utf-8")
        raise
