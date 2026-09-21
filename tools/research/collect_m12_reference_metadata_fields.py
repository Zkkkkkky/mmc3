"""Collect M12 reference persistence for 496 names and one preview selector."""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import sys
import traceback
from collections import Counter
from pathlib import Path

ROOT_HINT = Path(__file__).resolve().parents[2]
if str(ROOT_HINT) not in sys.path:
    sys.path.insert(0, str(ROOT_HINT))

from tools.golden_pipeline_collect import Win32LegacyDriver
from tools.research import collect_m12_reference_fields as base


OUT = ROOT_HINT / "output/verification/legacy-m12-metadata-fields-20260920"
RUNTIME = OUT / "reference-runtime"
WORK = OUT / "work.nes"
EVIDENCE = OUT / "field-save-chain.jsonl"
STATE = OUT / "state.json"
SUMMARY = OUT / "summary.json"
PROGRESS = OUT / "progress.log"
COLD = OUT / "cold-process-final-values.json"
FAMILY_ORDER = {
    "map_name": 0,
    "movement_name": 1,
    "sprite_name": 2,
    "background_name": 3,
    "sprite_preview_selector": 4,
}


def fields() -> list[dict[str, object]]:
    catalog = json.loads(base.CATALOG_PATH.read_text(encoding="utf-8"))
    result = [item for item in catalog["fields"] if item["family"] in FAMILY_ORDER]
    return sorted(result, key=lambda item: (FAMILY_ORDER[str(item["family"])], int(item["row"])))


def file_hashes() -> dict[str, str]:
    result = {}
    for path in sorted((RUNTIME / "默认配置文件").rglob("*")):
        if path.is_file():
            result[path.relative_to(RUNTIME).as_posix()] = hashlib.sha256(path.read_bytes()).hexdigest()
    return result


def log(message: str) -> None:
    with PROGRESS.open("a", encoding="utf-8") as stream:
        stream.write(message + "\n")


def append(payload: dict[str, object]) -> None:
    with EVIDENCE.open("a", encoding="utf-8") as stream:
        stream.write(json.dumps(payload, ensure_ascii=False, separators=(",", ":")) + "\n")


def mutate_name(text: str) -> str:
    if not text:
        return "我"
    for index, char in enumerate(text):
        if "\u4e00" <= char <= "\u9fff":
            return text[:index] + ("你" if char == "我" else "我") + text[index + 1 :]
    return ("B" if text[0] == "A" else "A") + text[1:]


def navigate(driver: Win32LegacyDriver, field: dict[str, object]) -> None:
    family = str(field["family"])
    row = int(field["row"])
    if family == "map_name":
        base.select_tab(driver, 45)
        base.select_listbox(driver, 110, row)
    elif family == "movement_name":
        base.select_tab(driver, 95)
        base.select_listbox(driver, 160, row)
    elif family in {"sprite_name", "sprite_preview_selector"}:
        base.select_tab(driver, 95)
        base.select_listbox(driver, 220, row)
    elif family == "background_name":
        base.select_tab(driver, 95)
        base.select_listbox(driver, 530, row)
    else:
        raise ValueError(f"unsupported metadata family {family}")


def read_field(driver: Win32LegacyDriver, field: dict[str, object]) -> int | str:
    navigate(driver, field)
    family = str(field["family"])
    if family == "sprite_preview_selector":
        return base.combo_index(driver, 600)
    edit_id = {"map_name": 280, "movement_name": 210, "sprite_name": 260, "background_name": 570}[family]
    return driver._control(edit_id, "Edit").window_text()


def commit(driver: Win32LegacyDriver, field: dict[str, object], value: int | str) -> None:
    navigate(driver, field)
    family = str(field["family"])
    if family == "sprite_preview_selector":
        driver.perform(({"op": "select_index_message", "class": "ComboBox", "control_id": 600, "value": int(value)},), value)
    else:
        edit_id = {"map_name": 280, "movement_name": 210, "sprite_name": 260, "background_name": 570}[family]
        driver.perform(({"op": "set_text", "class": "Edit", "control_id": edit_id, "value": str(value)},), value)
    driver.perform(({"op": "click_id", "class": "Button", "control_id": 310},), 0)
    driver.current_window = driver._main()


def launch(label: str, sequence: int) -> Win32LegacyDriver:
    last: Exception | None = None
    for attempt in range(3):
        driver = Win32LegacyDriver()
        try:
            pid = driver.launch(RUNTIME / "SRW2_patched.exe", RUNTIME)
            log(f"{label} pid={pid} sequence={sequence} attempt={attempt + 1}")
            return driver
        except Exception as error:
            last = error
            driver.stop()
    raise last or RuntimeError("metadata launch failed")


def collect(items: list[dict[str, object]], start: int, stop: int) -> None:
    cursor = start
    while cursor < stop:
        session_stop = min(stop, cursor + 40)
        driver = launch("metadata-chain", cursor)
        try:
            driver.open_rom(WORK)
            base.open_animation(driver)
            for index in range(cursor, session_stop):
                field = items[index]
                original = read_field(driver, field)
                if field["family"] == "sprite_preview_selector":
                    combo = driver._control(600, "ComboBox")
                    count = int(combo.item_count())
                    requested: int | str = (int(original) + 1) % count
                else:
                    requested = mutate_name(str(original))
                before_rom = base.sha(WORK.read_bytes())
                before_files = file_hashes()
                commit(driver, field, requested)
                base.open_animation(driver)
                readback = read_field(driver, field)
                after_files = file_hashes()
                changed_files = sorted(
                    key for key in set(before_files) | set(after_files) if before_files.get(key) != after_files.get(key)
                )
                rom_unchanged = base.sha(WORK.read_bytes()) == before_rom
                if readback == requested and changed_files and rom_unchanged:
                    status = "saved_external_metadata"
                elif readback == requested and rom_unchanged:
                    status = "accepted_pending_external_flush"
                elif readback == original and not changed_files and rom_unchanged:
                    status = "no_effect"
                else:
                    status = "unstable"
                if status == "unstable":
                    raise RuntimeError(f"metadata field unstable: {field['field_id']} readback={readback!r} files={changed_files}")
                append(
                    {
                        "sequence": index,
                        "field_id": field["field_id"],
                        "family": field["family"],
                        "row": field["row"],
                        "original": original,
                        "mutated": requested,
                        "same_process_reopen_readback": readback,
                        "status": status,
                        "rom_sha256": before_rom,
                        "rom_unchanged": rom_unchanged,
                        "changed_files": changed_files,
                        "before_file_hashes": {key: before_files.get(key) for key in changed_files},
                        "after_file_hashes": {key: after_files.get(key) for key in changed_files},
                    }
                )
                STATE.write_text(json.dumps({"completed": index + 1, "total": len(items)}, indent=2) + "\n", encoding="utf-8")
                if (index + 1) % 10 == 0 or index + 1 == session_stop:
                    log(f"metadata probed {index + 1}/{len(items)}")
        finally:
            driver.stop()
        cursor = session_stop


def classify_cold(records: list[dict[str, object]], actual: dict[str, object]) -> list[dict[str, object]]:
    failures = []
    for item in records:
        field_id = str(item["field_id"])
        cold_value = actual.get(field_id)
        item["cold_process_readback"] = cold_value
        if item["status"] == "accepted_pending_external_flush" and cold_value == item["original"] and not item["changed_files"]:
            item["status"] = "no_effect"
            item["classification_note"] = "same_process_only; reset to original in a new process"
            continue
        expected = item["original"] if item["status"] == "no_effect" else item["mutated"]
        if cold_value != expected:
            failures.append({"field_id": field_id, "expected": expected, "actual": cold_value})
    EVIDENCE.write_text("".join(json.dumps(item, ensure_ascii=False, separators=(",", ":")) + "\n" for item in records), encoding="utf-8")
    return failures


def cold_read(items: list[dict[str, object]], records: list[dict[str, object]]) -> None:
    driver = launch("metadata-cold", len(items))
    actual = {}
    try:
        driver.open_rom(WORK)
        base.open_animation(driver)
        for index, field in enumerate(items):
            actual[str(field["field_id"])] = read_field(driver, field)
            if (index + 1) % 50 == 0:
                log(f"metadata cold {index + 1}/{len(items)}")
    finally:
        driver.stop()
    COLD.write_text(json.dumps(actual, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    failures = classify_cold(records, actual)
    if failures:
        raise RuntimeError(f"metadata cold read failed for {len(failures)}: {failures[:5]}")


def evidence() -> list[dict[str, object]]:
    return [json.loads(line) for line in EVIDENCE.read_text(encoding="utf-8").splitlines() if line.strip()] if EVIDENCE.exists() else []


def write_summary(items: list[dict[str, object]]) -> None:
    records = evidence()
    statuses = Counter(item["status"] for item in records)
    families = Counter(item["family"] for item in records)
    complete = len(records) == len(items) and COLD.is_file()
    SUMMARY.write_text(json.dumps({
        "passed": complete,
        "logical_fields": len(items),
        "completed": len(records),
        "statuses": dict(sorted(statuses.items())),
        "family_probe_counts": dict(sorted(families.items())),
        "rom_unchanged": base.sha(WORK.read_bytes()) == base.sha(base.SOURCE.read_bytes()),
        "cold_process_logical_readback_passed": len(items) if complete else 0,
        "evidence": EVIDENCE.relative_to(ROOT_HINT).as_posix(),
    }, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", type=int)
    parser.add_argument("--restart", action="store_true")
    parser.add_argument("--reclassify-existing", action="store_true")
    args = parser.parse_args()
    OUT.mkdir(parents=True, exist_ok=True)
    items = fields()
    if len(items) != 497:
        raise RuntimeError(f"expected 497 metadata fields, got {len(items)}")
    if args.restart:
        if RUNTIME.exists():
            shutil.rmtree(RUNTIME)
        RUNTIME.mkdir(parents=True)
        shutil.copy2(base.AUDIT / "SRW2_patched.exe", RUNTIME / "SRW2_patched.exe")
        shutil.copytree(base.AUDIT / "默认配置文件" / "默认配置文件", RUNTIME / "默认配置文件")
        shutil.copy2(base.SOURCE, WORK)
        for path in (EVIDENCE, STATE, SUMMARY, COLD, OUT / "error.log"):
            path.unlink(missing_ok=True)
        PROGRESS.write_text("metadata restart\n", encoding="utf-8")
    records = evidence()
    if args.reclassify_existing:
        if len(records) != len(items) or not COLD.is_file():
            raise RuntimeError("complete metadata evidence and cold inventory are required")
        failures = classify_cold(records, json.loads(COLD.read_text(encoding="utf-8")))
        if failures:
            raise RuntimeError(f"metadata cold reclassification failed: {failures[:5]}")
        write_summary(items)
        (OUT / "error.log").unlink(missing_ok=True)
        return 0
    start = len(records)
    stop = len(items) if args.limit is None else min(len(items), start + args.limit)
    collect(items, start, stop)
    records = evidence()
    if len(records) == len(items):
        cold_read(items, records)
    write_summary(items)
    (OUT / "error.log").unlink(missing_ok=True)
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception:
        OUT.mkdir(parents=True, exist_ok=True)
        (OUT / "error.log").write_text(traceback.format_exc(), encoding="utf-8")
        raise
