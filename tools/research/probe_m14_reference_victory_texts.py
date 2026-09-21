"""Recapture all M14 victory texts with a full owner-drawn refresh delay."""

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


OUT = base.ROOT / "output/verification/legacy-m14-reference-catalog-20260920"
RESULT = OUT / "victory-texts.json"


def main() -> int:
    base.prepare()
    baseline = base.sha(base.ROM)
    driver = base.Win32LegacyDriver()
    rows = []
    try:
        driver.launch(base.RUNTIME / "SRW2_patched.exe", base.RUNTIME)
        driver.open_rom(base.ROM)
        base.open_editor(driver)
        base.page(driver, 5)
        records = base.any_control(driver, 630, "ListBox")
        labels = records.item_texts()
        edit = base.any_control(driver, 650, "Edit")
        for row, label in enumerate(labels):
            base.select_list(records, row)
            time.sleep(0.09)
            rows.append({"row": row, "label": label, "text": edit.window_text()})
        result = {"passed": True, "rows": rows}
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
        (OUT / "victory-texts-error.log").write_text(traceback.format_exc(), encoding="utf-8")
        raise
