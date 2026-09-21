"""Read valid legacy M07 ally/enemy animation pointers from representative rows."""

from __future__ import annotations

import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from tools.golden_pipeline_collect import Win32LegacyDriver
from tools.research.probe_m07_animation_editors import open_code_dialog

AUDIT = REPO / "output" / "build" / "legacy-diff-audit"
ROOT = REPO / "output" / "verification" / "legacy-ui-probe-m07-animation-20260920"
OUTPUT = ROOT / "M07_武器动画有效指针样本.json"


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
        database_hwnd = int(database.handle)
        samples: list[dict[str, object]] = []
        for row in (0, 1, 2, 3, 4, 140):
            driver.current_window = database
            driver.perform(
                ({"op": "list_select", "class": "ListBox", "control_id": 610, "row": row},),
                0,
            )
            ally = open_code_dialog(
                driver, database_hwnd, pid, 385, f"M07_指针样本_{row:03d}_我方"
            )
            driver.current_window = database
            enemy = open_code_dialog(
                driver, database_hwnd, pid, 490, f"M07_指针样本_{row:03d}_敌方"
            )
            samples.append(
                {
                    "weapon_row": row,
                    "ally": ally.get("value"),
                    "enemy": enemy.get("value"),
                }
            )
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
