"""Count contiguous non-empty M14 ListBox rows without treating capacity as data."""

from __future__ import annotations

import json
import sys
import time
import traceback
from pathlib import Path

import win32gui

ROOT_HINT = Path(__file__).resolve().parents[2]
if str(ROOT_HINT) not in sys.path:
    sys.path.insert(0, str(ROOT_HINT))

from tools.research import probe_m14_reference_catalog as base


OUT = base.ROOT / "output/verification/legacy-m14-reference-catalog-20260920"
RESULT = OUT / "instruction-counts.json"


def active_count(control) -> int:
    return sum(
        bool(text) and not text.rstrip().endswith("空事件")
        for text in control.item_texts()
    )


def sampled_items(control) -> dict[str, str]:
    items = control.item_texts()
    return {
        str(index): items[index]
        for index in (0, 1, 10, 50, 100, 500, 999)
        if index < len(items)
    }


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
        chapters = base.any_control(driver, 220, "ListBox")
        phases = [base.any_control(driver, value, "ListBox") for value in (140, 150, 160)]
        chapter_counts = []
        for row in range(int(chapters.item_count())):
            base.select_list(chapters, row)
            chapter_counts.append([active_count(control) for control in phases])
        chapter_samples = [sampled_items(control) for control in phases]

        base.page(driver, 1)
        actions = base.any_control(driver, 260, "ListBox")
        action_code = base.any_control(driver, 240, "ListBox")
        action_counts = []
        for row in range(int(actions.item_count())):
            base.select_list(actions, row)
            action_counts.append(active_count(action_code))
        action_samples = sampled_items(action_code)

        base.page(driver, 2)
        surrender = base.any_control(driver, 310, "ListBox")
        surrender_code = base.any_control(driver, 290, "ListBox")
        surrender_counts = []
        for row in range(int(surrender.item_count())):
            base.select_list(surrender, row)
            surrender_counts.append(active_count(surrender_code))
        surrender_samples = sampled_items(surrender_code)

        base.page(driver, 3)
        maps = base.any_control(driver, 360, "ListBox")
        map_code = base.any_control(driver, 340, "ListBox")
        map_counts = []
        for row in range(int(maps.item_count())):
            base.select_list(maps, row)
            map_counts.append(active_count(map_code))
        map_samples = sampled_items(map_code)

        result = {
            "passed": True,
            "rom_sha256_before": baseline,
            "chapter_counts": chapter_counts,
            "action_counts": action_counts,
            "surrender_counts": surrender_counts,
            "map_counts": map_counts,
            "representative_samples": {
                "chapter_phases": chapter_samples,
                "action": action_samples,
                "surrender": surrender_samples,
                "map": map_samples,
            },
            "totals": {
                "chapter_phases": [sum(item[index] for item in chapter_counts) for index in range(3)],
                "actions": sum(action_counts),
                "surrender": sum(surrender_counts),
                "maps": sum(map_counts),
            },
            "nonempty_records": {
                "actions": sum(value > 0 for value in action_counts),
                "surrender": sum(value > 0 for value in surrender_counts),
                "maps": sum(value > 0 for value in map_counts),
            },
        }
    finally:
        driver.stop()
    result["rom_sha256_after"] = base.sha(base.ROM)
    result["rom_unchanged"] = result["rom_sha256_after"] == baseline
    result["passed"] = bool(result["passed"] and result["rom_unchanged"])
    RESULT.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return 0 if result["passed"] else 1


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception:
        OUT.mkdir(parents=True, exist_ok=True)
        (OUT / "instruction-counts-error.log").write_text(traceback.format_exc(), encoding="utf-8")
        raise
