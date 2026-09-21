"""Collect resumable one-byte reference saves for every editable M03 field."""

from __future__ import annotations

import argparse
import hashlib
import json
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
CATALOG = ROOT / "output/reports/m03-reference-field-catalog.json"
CALIBRATION = ROOT / "output/verification/legacy-m03-save-calibration-20260920/calibration.json"
OUT = ROOT / "output/verification/legacy-m03-all-fields-20260920"
RUNTIME = OUT / "reference-runtime"
BASELINE = OUT / "normalized-baseline.nes"
WORK = OUT / "work.nes"
FINAL = OUT / "after-all-fields.nes"
CHAIN = OUT / "field-save-chain.jsonl"
STATE = OUT / "state.json"
PROGRESS = OUT / "progress.log"
WARM = OUT / "fresh-inventory-a.json"
COLD = OUT / "fresh-inventory-b.json"
SUMMARY = OUT / "summary.json"
FIELD_ORDER = {"x": 0, "y": 1, "pilot_id": 2, "unit_id": 3, "level": 4, "roster_index": 5, "flags": 6}
FAMILY_ORDER = {"enemy": 0, "guest": 1, "player": 2}
COMBO_IDS = {"pilot_id": 140, "unit_id": 160, "level": 180, "flags": 200, "roster_index": 220}


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def log(message: str) -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    with PROGRESS.open("a", encoding="utf-8") as stream:
        stream.write(f"{time.strftime('%Y-%m-%d %H:%M:%S')} {message}\n")
        stream.flush()


def catalog() -> dict[str, object]:
    return json.loads(CATALOG.read_text(encoding="utf-8"))


def fields(payload: dict[str, object]) -> list[dict[str, object]]:
    return sorted(
        (item for item in payload["fields"] if item["classification"] == "persistent_candidate"),
        key=lambda item: (
            int(item["map_id"]),
            FAMILY_ORDER[str(item["family"])],
            int(item["row"]),
            FIELD_ORDER[str(item["field"])],
        ),
    )


def records(payload: dict[str, object]) -> dict[str, dict[str, object]]:
    result: dict[str, dict[str, object]] = {}
    all_fields = payload["fields"]
    for record in payload["records"]:
        prefix = str(record["record_id"]) + "/"
        own = [item for item in all_fields if str(item["field_id"]).startswith(prefix)]
        result[str(record["record_id"])] = {
            **record,
            "x_offset": next(int(item["file_offset"]) for item in own if item["field"] == "x"),
            "y_offset": next(int(item["file_offset"]) for item in own if item["field"] == "y"),
            "field_ids": {str(item["field"]): str(item["field_id"]) for item in own},
            "field_offsets": {str(item["field"]): int(item["file_offset"]) for item in own},
        }
    return result


def entries() -> list[dict[str, object]]:
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
        json.dumps({"completed": completed, "total": total, "current_sha256": sha(WORK.read_bytes())}, indent=2) + "\n",
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


def record_for(field: dict[str, object], lookup: dict[str, dict[str, object]]) -> dict[str, object]:
    return lookup[str(field["field_id"]).rsplit("/", 1)[0]]


def position(data: bytes, record: dict[str, object]) -> tuple[int, int]:
    return data[int(record["x_offset"])], data[int(record["y_offset"])]


def occupied(data: bytes, lookup: dict[str, dict[str, object]], map_id: int) -> set[tuple[int, int]]:
    return {position(data, item) for item in lookup.values() if int(item["map_id"]) == map_id}


def coordinate_target(data: bytes, record: dict[str, object], name: str, lookup: dict[str, dict[str, object]]) -> tuple[int, int]:
    current = position(data, record)
    used = occupied(data, lookup, int(record["map_id"])) - {current}
    if name == "x":
        candidates = (
            (value, current[1])
            for distance in range(1, 23)
            for value in (current[0] + distance, current[0] - distance)
            if 0 <= value < 23
        )
    else:
        candidates = (
            (current[0], value)
            for distance in range(1, 21)
            for value in (current[1] + distance, current[1] - distance)
            if 0 <= value < 21
        )
    return next(
        point
        for point in candidates
        if point != current
        and point not in used
        # The reference editor can snap a drag by one cell.  Keep a one-cell
        # Manhattan buffer so such snapping cannot land on another record.
        and all(abs(point[0] - other[0]) + abs(point[1] - other[1]) > 1 for other in used)
    )


def mutate_combo(driver: Win32LegacyDriver, field: dict[str, object], record: dict[str, object], data: bytes) -> tuple[int, int]:
    x, y = position(data, record)
    ref.select_main_page(driver, 1)
    ref.select_map(driver, int(field["map_id"]))
    ref.context_command(driver, x, y, 23, 21, 2)
    ref.wait_dialog(driver, "配置设置")
    name = str(field["field"])
    control_id = COMBO_IDS[name]
    observed = ref.combo_index(driver, control_id)
    count = len(ref.combo(driver, control_id).item_texts())
    requested = (observed + 1) % count
    ref.set_combo(driver, control_id, requested)
    ref.click_button(driver, 240)
    driver.current_window = driver._main()
    return observed, requested


def collect_one(driver: Win32LegacyDriver, item: dict[str, object], lookup: dict[str, dict[str, object]], sequence: int, total: int) -> None:
    before = WORK.read_bytes()
    record = record_for(item, lookup)
    name = str(item["field"])
    if name in {"x", "y"}:
        source = position(before, record)
        target = coordinate_target(before, record, name, lookup)
        observed = source[0 if name == "x" else 1]
        requested = target[0 if name == "x" else 1]
        ref.select_main_page(driver, 1)
        ref.select_map(driver, int(item["map_id"]))
        ref.drag_cell(driver, source, target, 23, 21)
    else:
        observed, requested = mutate_combo(driver, item, record, before)
    ref.save(driver)
    after = WORK.read_bytes()
    changed = [index for index, pair in enumerate(zip(before, after)) if pair[0] != pair[1]]
    offset = int(item["file_offset"])
    if changed != [offset]:
        raise RuntimeError(f"M03 {item['field_id']} changed {changed[:12]}, expected only {offset}")
    expected_before = int(observed) + (1 if name in {"pilot_id", "unit_id"} else 0)
    expected_after = int(requested) + (1 if name in {"pilot_id", "unit_id"} else 0)
    coordinate_unique = True
    if name in {"x", "y"}:
        current_after = position(after, record)
        other_positions = [
            position(after, other)
            for other in lookup.values()
            if other["record_id"] != record["record_id"]
            and int(other["map_id"]) == int(record["map_id"])
        ]
        coordinate_unique = current_after not in other_positions
        value_valid = after[offset] != before[offset]
    else:
        value_valid = after[offset] == expected_after
    if before[offset] != expected_before or not value_valid:
        raise RuntimeError(
            f"M03 {item['field_id']} value mismatch: "
            f"before={before[offset]} observed={observed}; "
            f"after={after[offset]} requested={requested}; "
            f"coordinate_unique={coordinate_unique}"
        )
    payload = {
            "sequence": sequence,
            "catalog_field_id": item["field_id"],
            "map_id": item["map_id"],
            "family": item["family"],
            "row": item["row"],
            "field": name,
            "file_offset": offset,
            "ui_observed": observed,
            "ui_requested": requested,
            "before_byte": before[offset],
            "after_byte": after[offset],
            "before_sha256": sha(before),
            "after_sha256": sha(after),
            "changed_offsets": changed,
            "requested_value_persisted": after[offset] == expected_after,
            "coordinate_unique_after_save": coordinate_unique,
            "save_semantics": (
                "reference_snapped_coordinate"
                if name in {"x", "y"} and after[offset] != expected_after
                else "requested_value_exact"
            ),
            "status": "saved",
        }
    if name in {"x", "y"}:
        continuation = bytearray(after)
        continuation[offset] = before[offset]
        WORK.write_bytes(continuation)
        payload["continuation_restored_byte"] = before[offset]
        payload["continuation_sha256"] = sha(bytes(continuation))
        payload["isolated_coordinate_case"] = True
        driver.open_rom(WORK)
    append(payload)
    state(sequence + 1, total)
    if (sequence + 1) % 10 == 0:
        log(f"saved {sequence + 1}/{total} field={item['field_id']}")


def rebuild(evidence: list[dict[str, object]]) -> None:
    data = bytearray(BASELINE.read_bytes())
    for index, item in enumerate(evidence):
        if sha(bytes(data)) != item["before_sha256"] or int(item["sequence"]) != index:
            raise RuntimeError(f"M03 evidence chain broken before {index}")
        offset = int(item["file_offset"])
        if data[offset] != int(item["before_byte"]):
            raise RuntimeError(f"M03 evidence byte broken at {index}")
        data[offset] = int(item["after_byte"])
        if sha(bytes(data)) != item["after_sha256"]:
            raise RuntimeError(f"M03 evidence chain broken after {index}")
        if "continuation_restored_byte" in item:
            data[offset] = int(item["continuation_restored_byte"])
            if sha(bytes(data)) != item["continuation_sha256"]:
                raise RuntimeError(f"M03 evidence continuation broken after {index}")
    WORK.write_bytes(data)


def inventory(payload: dict[str, object], lookup: dict[str, dict[str, object]], label: str) -> dict[str, int]:
    driver = launch()
    result: dict[str, int] = {}
    data = WORK.read_bytes()
    try:
        driver.open_rom(WORK)
        for index, record in enumerate(lookup.values()):
            own = [item for item in payload["fields"] if str(item["field_id"]).startswith(str(record["record_id"]) + "/") and item["classification"] == "persistent_candidate"]
            if not own:
                continue
            x, y = position(data, record)
            ref.select_main_page(driver, 1)
            ref.select_map(driver, int(record["map_id"]))
            ref.context_command(driver, x, y, 23, 21, 2)
            ref.wait_dialog(driver, "配置设置")
            for item in own:
                name = str(item["field"])
                if name == "x":
                    value = x
                elif name == "y":
                    value = y
                else:
                    value = ref.combo_index(driver, COMBO_IDS[name])
                    if name in {"pilot_id", "unit_id"}:
                        value += 1
                result[str(item["field_id"])] = int(value)
            ref.close_dialog_cancel(driver, 250)
            if (index + 1) % 25 == 0:
                log(f"{label} records {index + 1}/{len(lookup)}")
    finally:
        driver.stop()
        time.sleep(5.0)
    return result


def write_summary(items: list[dict[str, object]]) -> None:
    evidence = entries()
    report = {
        "passed": len(evidence) == len(items) and WARM.is_file() and COLD.is_file(),
        "catalog_fields": len(items),
        "completed_fields": len(evidence),
        "safe_denominator_fields": len(evidence),
        "chain_contiguous": all(
            evidence[index].get("continuation_sha256", evidence[index]["after_sha256"])
            == evidence[index + 1]["before_sha256"]
            for index in range(len(evidence) - 1)
        ),
        "fresh_inventories_match": WARM.is_file() and COLD.is_file() and json.loads(WARM.read_text(encoding="utf-8")) == json.loads(COLD.read_text(encoding="utf-8")),
    }
    report["passed"] = all((report["passed"], report["chain_contiguous"], report["fresh_inventories_match"]))
    SUMMARY.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--restart", action="store_true")
    parser.add_argument("--limit", type=int)
    args = parser.parse_args()
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "error.log").unlink(missing_ok=True)
    payload = catalog()
    items = fields(payload)
    lookup = records(payload)
    calibration = json.loads(CALIBRATION.read_text(encoding="utf-8"))
    if not calibration.get("passed"):
        raise RuntimeError("M03 calibration must pass before exhaustive collection")
    if args.restart:
        for path in (CHAIN, STATE, WARM, COLD, FINAL, SUMMARY, OUT / "error.log"):
            path.unlink(missing_ok=True)
        PROGRESS.write_text("", encoding="utf-8")
        shutil.copy2(SOURCE, BASELINE)
        shutil.copy2(BASELINE, WORK)
        state(0, len(items))
    evidence = entries()
    if not BASELINE.is_file() or not WORK.is_file():
        raise RuntimeError("use --restart to initialize M03 exhaustive collection")
    rebuild(evidence)
    start = len(evidence)
    stop = len(items) if args.limit is None else min(len(items), start + args.limit)
    if start < stop:
        driver = launch()
        try:
            driver.open_rom(WORK)
            for index in range(start, stop):
                collect_one(driver, items[index], lookup, index, len(items))
        finally:
            driver.stop()
            time.sleep(5.0)
    if len(entries()) == len(items) and not (WARM.is_file() and COLD.is_file()):
        first = inventory(payload, lookup, "fresh-a")
        WARM.write_text(json.dumps(first, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        second = inventory(payload, lookup, "fresh-b")
        COLD.write_text(json.dumps(second, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        expected = {str(item["field_id"]): WORK.read_bytes()[int(item["file_offset"])] for item in items}
        if first != expected or second != expected:
            raise RuntimeError("M03 fresh inventory differs from final ROM fields")
        shutil.copy2(WORK, FINAL)
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
