"""Collect isolated exact-byte reference saves for every editable M04 field."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import shutil
import sys
import time
import traceback
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools.golden_pipeline_collect import Win32LegacyDriver
from tools.research import reference_map_editor as ref


AUDIT = ROOT / "output/build/legacy-diff-audit"
SOURCE = AUDIT / "audit.nes"
CATALOG = ROOT / "output/reports/m04-reference-field-catalog.json"
CALIBRATION = ROOT / "output/verification/legacy-m04-save-calibration-20260920/calibration.json"
OUT = ROOT / "output/verification/legacy-m04-all-fields-20260920"
RUNTIME = OUT / "reference-runtime"
BASELINE = OUT / "normalized-baseline.nes"
TEMP = OUT / "current-case.nes"
AGGREGATE = OUT / "aggregate-all-fields.nes"
CHAIN = OUT / "field-save-cases.jsonl"
STATE = OUT / "state.json"
PROGRESS = OUT / "progress.log"
WARM = OUT / "fresh-inventory-a.json"
COLD = OUT / "fresh-inventory-b.json"
SUMMARY = OUT / "summary.json"
FIELD_ORDER = {"x": 0, "y": 1, "character_id": 2, "event_id": 3}


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def log(message: str) -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    with PROGRESS.open("a", encoding="utf-8") as stream:
        stream.write(f"{time.strftime('%Y-%m-%d %H:%M:%S')} {message}\n")
        stream.flush()


def payload() -> dict[str, object]:
    return json.loads(CATALOG.read_text(encoding="utf-8"))


def fields(data: dict[str, object]) -> list[dict[str, object]]:
    return sorted(
        (item for item in data["fields"] if item["classification"] == "persistent_candidate"),
        key=lambda item: (int(item["map_id"]), int(item["row"]), FIELD_ORDER[str(item["field"])]),
    )


def record_values(record: dict[str, object]) -> dict[str, int]:
    raw = bytes.fromhex(str(record["raw_hex"]))
    return dict(zip(("x", "y", "character_id", "event_id"), raw, strict=True))


def records_by_map(data: dict[str, object]) -> dict[int, list[dict[str, object]]]:
    result: dict[int, list[dict[str, object]]] = {}
    for item in data["records"]:
        result.setdefault(int(item["map_id"]), []).append(item)
    for items in result.values():
        items.sort(key=lambda item: int(item["row"]))
    return result


def evidence() -> list[dict[str, object]]:
    if not CHAIN.is_file():
        return []
    return [json.loads(line) for line in CHAIN.read_text(encoding="utf-8").splitlines() if line]


def append(item: dict[str, object]) -> None:
    with CHAIN.open("a", encoding="utf-8") as stream:
        stream.write(json.dumps(item, ensure_ascii=False, separators=(",", ":")) + "\n")
        stream.flush()


def state(completed: int, total: int) -> None:
    temporary = STATE.with_name(STATE.name + ".tmp")
    temporary.write_text(
        json.dumps({"completed": completed, "total": total}, indent=2) + "\n",
        encoding="utf-8",
    )
    temporary.replace(STATE)


def prepare_runtime() -> None:
    deadline = time.monotonic() + 30.0
    waiting_logged = False
    while RUNTIME.exists():
        try:
            shutil.rmtree(RUNTIME)
            break
        except PermissionError:
            if time.monotonic() >= deadline:
                raise
            if not waiting_logged:
                log("waiting for previous reference runtime lock to release")
                waiting_logged = True
            time.sleep(1.0)
    RUNTIME.mkdir(parents=True)
    shutil.copy2(AUDIT / "SRW2_patched.exe", RUNTIME / "SRW2_patched.exe")
    shutil.copytree(AUDIT / "默认配置文件/默认配置文件", RUNTIME / "默认配置文件")


def launch() -> Win32LegacyDriver:
    prepare_runtime()
    driver = Win32LegacyDriver()
    driver.launch(RUNTIME / "SRW2_patched.exe", RUNTIME)
    return driver


def character_ui(raw: int) -> int:
    return 0 if raw == 0xFF else raw


def add(driver: Win32LegacyDriver, values: dict[str, int]) -> None:
    ref.context_command(driver, values["x"], values["y"], 23, 21, 1)
    ref.wait_dialog(driver, "商店设置")
    ref.set_combo(driver, 100, character_ui(values["character_id"]))
    event = values["event_id"]
    if event >= 0xF0:
        ref.click_button(driver, 180)
        ref.set_combo(driver, 130, event - 0xF0)
    else:
        ref.click_button(driver, 190)
        ref.set_combo(driver, 170, event)
    ref.click_button(driver, 140)
    driver.current_window = driver._main()


def requested_value(field: dict[str, object], record: dict[str, object], map_records: list[dict[str, object]]) -> int:
    values = record_values(record)
    name = str(field["field"])
    current = values[name]
    if name in {"x", "y"}:
        occupied = {(record_values(item)["x"], record_values(item)["y"]) for item in map_records}
        if name == "x":
            candidates = ((value, values["y"]) for value in range(23))
        else:
            candidates = ((values["x"], value) for value in range(21))
        target = next(point for point in candidates if point != (values["x"], values["y"]) and point not in occupied)
        return target[0 if name == "x" else 1]
    if name == "character_id":
        return 5 if current == 0xFF else current + 1
    if current >= 0xF0:
        return 0xF0 + ((current - 0xF0 + 1) % 5)
    return (current + 1) % 0xF0


def collect_case(driver: Win32LegacyDriver, field: dict[str, object], maps: dict[int, list[dict[str, object]]], sequence: int, total: int) -> None:
    map_id, row = int(field["map_id"]), int(field["row"])
    map_records = maps[map_id]
    record = map_records[row]
    original = record_values(record)
    changed = dict(original)
    name = str(field["field"])
    changed[name] = requested_value(field, record, map_records)
    shutil.copy2(BASELINE, TEMP)
    driver.open_rom(TEMP)
    before = TEMP.read_bytes()
    ref.select_main_page(driver, 2)
    ref.select_map(driver, map_id)
    # Remove the target and every following row from the end. Re-adding them
    # in their original order restores the exact physical row layout, so the
    # save must differ by only the requested byte.
    for victim in reversed(map_records[row:]):
        values = record_values(victim)
        ref.context_command(driver, values["x"], values["y"], 23, 21, 2)
        time.sleep(0.12)
    add(driver, changed)
    for suffix in map_records[row + 1 :]:
        add(driver, record_values(suffix))
    ref.save(driver)
    after = TEMP.read_bytes()
    changed_offsets = [index for index, pair in enumerate(zip(before, after)) if pair[0] != pair[1]]
    offset = int(field["file_offset"])
    if changed_offsets != [offset] or after[offset] != changed[name]:
        raise RuntimeError(f"M04 {field['field_id']} changed {changed_offsets[:20]}, expected only {offset}")
    append(
        {
            "sequence": sequence,
            "catalog_field_id": field["field_id"],
            "map_id": map_id,
            "row": row,
            "field": name,
            "file_offset": offset,
            "original": original[name],
            "requested": changed[name],
            "before_sha256": sha(before),
            "after_sha256": sha(after),
            "before_byte": before[offset],
            "after_byte": after[offset],
            "changed_offsets": changed_offsets,
            "status": "saved",
        }
    )
    TEMP.unlink(missing_ok=True)
    state(sequence + 1, total)
    if (sequence + 1) % 5 == 0:
        log(f"saved {sequence + 1}/{total} field={field['field_id']}")


def aggregate(rows: list[dict[str, object]]) -> None:
    data = bytearray(BASELINE.read_bytes())
    for item in rows:
        data[int(item["file_offset"])] = int(item["after_byte"])
    AGGREGATE.write_bytes(data)


def parse_raw(text: str) -> bytes:
    parts = re.findall(r"(?i)\b[0-9a-f]{2}\b", text)
    if len(parts) < 4:
        raise RuntimeError(f"M04 record text is not four hex bytes: {text!r}")
    return bytes(int(value, 16) for value in parts[:4])


def inventory(data: dict[str, object], label: str) -> dict[str, int]:
    driver = launch()
    result: dict[str, int] = {}
    try:
        driver.open_rom(AGGREGATE)
        ref.select_main_page(driver, 2)
        maps = records_by_map(data)
        for map_id, records in sorted(maps.items()):
            candidates = [
                record
                for record in records
                if any(
                    str(field["field_id"]).startswith(str(record["record_id"]) + "/")
                    and field["classification"] == "persistent_candidate"
                    for field in data["fields"]
                )
            ]
            if not candidates:
                continue
            ref.select_map(driver, map_id)
            deadline = time.monotonic() + 5.0
            texts: list[str] = []
            while time.monotonic() < deadline:
                texts = list(driver._control(550, "ListBox").item_texts())
                if len(texts) == len(records):
                    break
                time.sleep(0.1)
            if len(texts) != len(records):
                raise RuntimeError(
                    f"M04 map {map_id:02d} list has {len(texts)} rows, "
                    f"expected {len(records)} physical records after refresh"
                )
            for record in candidates:
                row = int(record["row"])
                raw = parse_raw(texts[row])
                prefix = str(record["record_id"]) + "/"
                for field in data["fields"]:
                    if str(field["field_id"]).startswith(prefix) and field["classification"] == "persistent_candidate":
                        result[str(field["field_id"])] = raw[FIELD_ORDER[str(field["field"])]]
            log(f"{label} map={map_id:02d} fields={len(result)}")
    finally:
        driver.stop()
        time.sleep(5.0)
    return result


def write_summary(items: list[dict[str, object]]) -> None:
    rows = evidence()
    report = {
        "passed": len(rows) == len(items) and WARM.is_file() and COLD.is_file(),
        "catalog_fields": len(items),
        "completed_fields": len(rows),
        "safe_denominator_fields": len(rows),
        "isolated_cases_exact": all(item["changed_offsets"] == [item["file_offset"]] for item in rows),
        "fresh_inventories_match": WARM.is_file() and COLD.is_file() and json.loads(WARM.read_text(encoding="utf-8")) == json.loads(COLD.read_text(encoding="utf-8")),
    }
    report["passed"] = all((report["passed"], report["isolated_cases_exact"], report["fresh_inventories_match"]))
    SUMMARY.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--restart", action="store_true")
    parser.add_argument("--limit", type=int)
    args = parser.parse_args()
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "error.log").unlink(missing_ok=True)
    data = payload()
    items = fields(data)
    maps = records_by_map(data)
    calibration = json.loads(CALIBRATION.read_text(encoding="utf-8"))
    if not calibration.get("passed"):
        raise RuntimeError("M04 calibration must pass before exhaustive collection")
    if args.restart:
        for path in (CHAIN, STATE, WARM, COLD, AGGREGATE, SUMMARY, TEMP, OUT / "error.log"):
            path.unlink(missing_ok=True)
        PROGRESS.write_text("", encoding="utf-8")
        shutil.copy2(SOURCE, BASELINE)
        state(0, len(items))
    rows = evidence()
    if not BASELINE.is_file():
        raise RuntimeError("use --restart to initialize M04 exhaustive collection")
    if not all(item["catalog_field_id"] == items[index]["field_id"] for index, item in enumerate(rows)):
        raise RuntimeError("M04 evidence sequence does not match catalog")
    start = len(rows)
    stop = len(items) if args.limit is None else min(len(items), start + args.limit)
    if start < stop:
        driver = launch()
        try:
            for index in range(start, stop):
                collect_case(driver, items[index], maps, index, len(items))
        finally:
            driver.stop()
            time.sleep(5.0)
    rows = evidence()
    if len(rows) == len(items) and not (WARM.is_file() and COLD.is_file()):
        aggregate(rows)
        first = inventory(data, "fresh-a")
        WARM.write_text(json.dumps(first, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        second = inventory(data, "fresh-b")
        COLD.write_text(json.dumps(second, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        expected = {str(item["field_id"]): AGGREGATE.read_bytes()[int(item["file_offset"])] for item in items}
        if first != expected or second != expected:
            raise RuntimeError("M04 fresh inventory differs from aggregate ROM fields")
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
