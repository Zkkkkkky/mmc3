"""Test M14 per-field saves without closing and reopening the editor."""

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


ROM = base.OUT / "inplace-save.nes"
RESULT = base.OUT / "inplace-save.json"


def main() -> int:
    shutil.copy2(base.NORMALIZED, ROM)
    all_items = base.fields()
    def first(family: str, *, empty: bool | None = None):
        for item in all_items:
            if item["family"] != family:
                continue
            if empty is None or (not bool(item["original"])) == empty:
                return item
        raise RuntimeError(f"missing representative {family}/{empty}")
    items = [
        first("chapter_initial_victory"),
        first("surrender_chapter"),
        first("story_text", empty=False),
        first("story_text", empty=True),
        first("victory_text"),
        first("chapter_title"),
        first("action_name"),
        first("map_name", empty=True),
    ]
    expected: dict[str, object] = {}
    results: list[dict[str, object]] = []
    driver = base.launch("inplace-save")
    try:
        driver.open_rom(ROM)
        base.open_editor(driver)
        for field in items:
            started = time.perf_counter()
            original = base.read_field(driver, field)
            requested = base.mutation(driver, field, original)
            before = ROM.read_bytes()
            base.set_selected(driver, field, requested)
            if str(field["family"]).startswith("surrender_"):
                commit_target = next(
                    item for item in all_items
                    if item["family"] == field["family"] and int(item["row"]) == int(field["row"]) + 1
                )
                base.read_field(driver, commit_target)
            elif field["family"] == "story_text":
                commit_target = next(
                    item for item in all_items
                    if item["family"] == "story_text"
                    and item["group"] == field["group"]
                    and int(item["row"]) == int(field["row"]) + 1
                )
                base.read_field(driver, commit_target)
            after_set = time.perf_counter()
            base.save_with_retry(driver)
            after_save = time.perf_counter()
            after = ROM.read_bytes()
            ranges = base.diff_ranges(before, after)
            expected[str(field["field_id"])] = requested
            results.append(
                {
                    "field_id": field["field_id"],
                    "original": original,
                    "requested": requested,
                    "changed_bytes": sum(int(item["end_exclusive"]) - int(item["start"]) for item in ranges),
                    "set_seconds": round(after_set - started, 3),
                    "save_seconds": round(after_save - after_set, 3),
                }
            )
    finally:
        driver.stop()
    time.sleep(1.0)
    cold = base.launch("inplace-save-cold")
    actual: dict[str, object] = {}
    try:
        cold.open_rom(ROM)
        base.open_editor(cold)
        for field in items:
            actual[str(field["field_id"])] = base.read_field(cold, field)
    finally:
        cold.stop()
    changed = {str(item["field_id"]): bool(item["changed_bytes"]) for item in results}
    persistent = {str(item["field_id"]): str(item["family"]) in base.PERSISTENT_FAMILIES for item in items}
    failures = [
        key for key, value in expected.items()
        if (persistent[key] and (actual.get(key) != value or not changed[key]))
        or (not persistent[key] and (actual.get(key) == value or changed[key]))
    ]
    RESULT.write_text(
        json.dumps({"passed": not failures, "results": results, "cold": actual, "failures": failures}, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return 0 if not failures else 1


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception:
        RESULT.write_text(json.dumps({"passed": False, "error": traceback.format_exc()}, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        raise
