"""Read representative M07 animation list rows without saving."""

from __future__ import annotations

import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from tools.golden_pipeline_collect import Win32LegacyDriver
from tools.research.probe_m07_animation_editors import click_relative, list_items

AUDIT = REPO / "output" / "build" / "legacy-diff-audit"
ROOT = REPO / "output" / "verification" / "legacy-ui-probe-m07-animation-20260920"
OUTPUT = ROOT / "M07_武器动画列表样本.json"


def main() -> int:
    driver = Win32LegacyDriver()
    before = (AUDIT / "m05-reference-baseline.nes").read_bytes()
    try:
        pid = driver.launch(AUDIT / "SRW2_patched.exe", AUDIT)
        driver.open_rom(AUDIT / "m05-reference-baseline.nes")
        driver.perform(
            (
                {"op": "menu", "path": "数据->数据库"},
                {"op": "window", "title": "数据库"},
                {"op": "click_coords", "x": 220, "y": 73},
            ),
            0,
        )
        database = driver.current_window
        assert database is not None
        hwnd = int(database.handle)
        samples: list[dict[str, object]] = []
        for row in (0, 1, 140):
            driver.current_window = database
            driver.perform(
                ({"op": "list_select", "class": "ListBox", "control_id": 610, "row": row},),
                0,
            )
            click_relative(hwnd, 385, 294)
            ally = list_items(driver, 2530)[:4]
            click_relative(hwnd, 490, 294)
            enemy = list_items(driver, 2520)[:4]
            samples.append({"weapon_row": row, "ally": ally, "enemy": enemy})
        after = (AUDIT / "m05-reference-baseline.nes").read_bytes()
        OUTPUT.write_text(
            json.dumps(
                {"pid": pid, "rom_unchanged": before == after, "samples": samples},
                ensure_ascii=False,
                indent=2,
            )
            + "\n",
            encoding="utf-8",
        )
        print(OUTPUT)
        return 0
    finally:
        driver.stop()


if __name__ == "__main__":
    raise SystemExit(main())
