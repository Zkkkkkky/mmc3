"""Check whether the M14 editor can safely perform several saves in one process."""

from __future__ import annotations

import json
import shutil
import sys
import time
import traceback
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools.research import collect_m14_all_reference_fields as base


ROM = base.OUT / "batch-stability.nes"
RESULT = base.OUT / "batch-stability.json"


def main() -> int:
    shutil.copy2(base.NORMALIZED, ROM)
    items = base.fields()[:5]
    driver = base.launch("batch-stability")
    results: list[dict[str, object]] = []
    try:
        driver.open_rom(ROM)
        base.open_editor(driver)
        for index, field in enumerate(items):
            started = time.perf_counter()
            original = base.read_field(driver, field)
            after_read = time.perf_counter()
            requested = base.mutation(driver, field, original)
            before = ROM.read_bytes()
            base.set_selected(driver, field, requested)
            base.commit_close(driver)
            after_commit = time.perf_counter()
            base.save_with_retry(driver)
            after_save = time.perf_counter()
            after = ROM.read_bytes()
            results.append(
                {
                    "sequence": index,
                    "field_id": field["field_id"],
                    "changed_bytes": sum(
                        int(item["end_exclusive"]) - int(item["start"])
                        for item in base.diff_ranges(before, after)
                    ),
                    "seconds": {
                        "read": round(after_read - started, 3),
                        "set_and_commit": round(after_commit - after_read, 3),
                        "save": round(after_save - after_commit, 3),
                    },
                }
            )
            if index + 1 < len(items):
                reopen_started = time.perf_counter()
                time.sleep(0.2)
                driver.current_window = driver._main()
                base.open_editor(driver)
                results[-1]["seconds"]["wait_and_reopen"] = round(time.perf_counter() - reopen_started, 3)
    finally:
        driver.stop()
    RESULT.write_text(json.dumps({"passed": len(results) == len(items), "results": results}, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception:
        RESULT.write_text(json.dumps({"passed": False, "error": traceback.format_exc()}, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        raise
