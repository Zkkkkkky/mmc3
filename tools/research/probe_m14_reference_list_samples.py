"""Capture representative raw rows from M14 preallocated ListBoxes."""

from __future__ import annotations

import json
import sys
import traceback
from pathlib import Path

ROOT_HINT = Path(__file__).resolve().parents[2]
if str(ROOT_HINT) not in sys.path:
    sys.path.insert(0, str(ROOT_HINT))

from tools.research import probe_m14_reference_catalog as base


OUT = base.ROOT / "output/verification/legacy-m14-reference-catalog-20260920"
RESULT = OUT / "list-samples.json"
INDICES = (0, 1, 10, 20, 50, 100, 500, 999)


def sample(control) -> dict[str, str]:
    items = control.item_texts()
    return {str(index): items[index] for index in INDICES if index < len(items)}


def main() -> int:
    base.prepare()
    baseline = base.sha(base.ROM)
    driver = base.Win32LegacyDriver()
    result: dict[str, object] = {}
    try:
        driver.launch(base.RUNTIME / "SRW2_patched.exe", base.RUNTIME)
        driver.open_rom(base.ROM)
        base.open_editor(driver)
        base.page(driver, 0)
        chapter = base.any_control(driver, 220, "ListBox")
        base.select_list(chapter, 0)
        chapter_samples = {
            str(control_id): sample(base.any_control(driver, control_id, "ListBox"))
            for control_id in (140, 150, 160)
        }
        base.page(driver, 1)
        action = base.any_control(driver, 260, "ListBox")
        base.select_list(action, 0)
        action_sample = sample(base.any_control(driver, 240, "ListBox"))
        base.page(driver, 2)
        surrender = base.any_control(driver, 310, "ListBox")
        base.select_list(surrender, 0)
        surrender_sample = sample(base.any_control(driver, 290, "ListBox"))
        base.page(driver, 3)
        maps = base.any_control(driver, 360, "ListBox")
        base.select_list(maps, 0)
        map_sample = sample(base.any_control(driver, 340, "ListBox"))
        result = {
            "passed": True,
            "chapter": chapter_samples,
            "action": action_sample,
            "surrender": surrender_sample,
            "map": map_sample,
        }
    finally:
        driver.stop()
    result["rom_unchanged"] = base.sha(base.ROM) == baseline
    result["passed"] = bool(result["passed"] and result["rom_unchanged"])
    RESULT.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return 0 if result["passed"] else 1


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception:
        OUT.mkdir(parents=True, exist_ok=True)
        (OUT / "list-samples-error.log").write_text(traceback.format_exc(), encoding="utf-8")
        raise
