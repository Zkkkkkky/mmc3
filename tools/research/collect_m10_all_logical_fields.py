"""Collect resumable reference-save evidence for every M10 logical field."""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import sys
import time
import traceback
from collections import Counter
from pathlib import Path

import win32con
import win32gui


ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools.golden_pipeline_collect import Win32LegacyDriver
from tools.report_m10_reference_field_catalog import DEFAULT_JSON as CATALOG_PATH, DEFAULT_ROM


AUDIT = ROOT / "output/build/legacy-diff-audit"
OUT = ROOT / "output/verification/legacy-m10-all-fields-20260920"
WORK = OUT / "work.nes"
FINAL = OUT / "after-all-fields.nes"
EVIDENCE = OUT / "field-save-chain.jsonl"
STATE = OUT / "state.json"
SUMMARY = OUT / "summary.json"
PROGRESS = OUT / "progress.log"
SAME_PROCESS = OUT / "same-process-final-values.json"
COLD_PROCESS = OUT / "cold-process-final-values.json"
NORMALIZATION_OFFSETS = {0x4A101, 0x4A102, 0x4AE2A, 0x4AE2B, 0x79538, 0x79539}


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def log(message: str) -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    with PROGRESS.open("a", encoding="utf-8") as stream:
        stream.write(message + "\n")


def ordered_fields(catalog: dict[str, object]) -> list[dict[str, object]]:
    order = {"item_name": 0, "item_price": 1, "item_description": 2, "shop_dialogue_text": 3, "shop_item": 4, "shop_clerk": 5, "shop_dialogue_id": 6}
    return sorted(catalog["fields"], key=lambda field: (not bool(field["product_safe"]), order[str(field["family"])]))


def diff_ranges(before: bytes, after: bytes) -> list[dict[str, object]]:
    if len(before) != len(after):
        raise ValueError("reference save changed ROM size")
    changed = [index for index, pair in enumerate(zip(before, after)) if pair[0] != pair[1]]
    if not changed:
        return []
    result: list[dict[str, object]] = []
    start = previous = changed[0]
    for offset in changed[1:] + [changed[-1] + 2]:
        if offset != previous + 1:
            end = previous + 1
            result.append({"start": start, "end_exclusive": end, "before_hex": before[start:end].hex().upper(), "after_hex": after[start:end].hex().upper()})
            start = offset
        previous = offset
    return result


def append_evidence(payload: dict[str, object]) -> None:
    with EVIDENCE.open("a", encoding="utf-8") as stream:
        stream.write(json.dumps(payload, ensure_ascii=False, separators=(",", ":")) + "\n")
        stream.flush()


def save_state(completed: int, current_sha: str, total: int) -> None:
    STATE.write_text(json.dumps({"completed": completed, "total": total, "current_sha256": current_sha}, indent=2) + "\n", encoding="utf-8")


def rebuild_work_from_evidence(total: int) -> tuple[int, str]:
    data = bytearray(DEFAULT_ROM.read_bytes())
    completed = 0
    if EVIDENCE.exists():
        for line in EVIDENCE.read_text(encoding="utf-8").splitlines():
            item = json.loads(line)
            if sha(bytes(data)) != item["before_sha256"]:
                raise ValueError(f"evidence chain breaks before sequence {item['sequence']}")
            for change in item["ranges"]:
                start, end = int(change["start"]), int(change["end_exclusive"])
                if bytes(data[start:end]).hex().upper() != change["before_hex"]:
                    raise ValueError(f"evidence bytes break at sequence {item['sequence']}")
                data[start:end] = bytes.fromhex(change["after_hex"])
            if sha(bytes(data)) != item["after_sha256"]:
                raise ValueError(f"evidence chain breaks after sequence {item['sequence']}")
            completed += 1
    WORK.write_bytes(data)
    current_sha = sha(bytes(data))
    save_state(completed, current_sha, total)
    return completed, current_sha


def launch(label: str) -> Win32LegacyDriver:
    driver = Win32LegacyDriver()
    pid = driver.launch(AUDIT / "SRW2_patched.exe", AUDIT)
    log(f"{label} launched pid={pid}")
    return driver


def open_database(driver: Win32LegacyDriver) -> None:
    driver.current_window = driver._main()
    driver.perform(({"op": "menu", "path": "数据->数据库"}, {"op": "window", "title": "数据库"}, {"op": "click_coords", "x": 485, "y": 62}), 0)


def select_item(driver: Win32LegacyDriver, row: int) -> None:
    table = driver._control(1690, "SysListView32")
    table.set_focus()
    table.get_item(row, 0).ensure_visible()
    top = int(win32gui.SendMessage(table.handle, 0x1027, 0, 0))
    expected = table.get_item(row, 0).text().split("：", 1)[-1]
    y = 165 + (row - top) * 25
    for delta in (0, -8, 8, -15, 15):
        driver.current_window.click_input(coords=(100, y + delta))
        time.sleep(0.12)
        if driver._control(1710, "Edit").window_text() == expected:
            return
    raise RuntimeError(f"unable to select item row {row}")


def select_shop(driver: Win32LegacyDriver, row: int) -> None:
    box = driver._control(1810, "ListBox")
    if win32gui.SendMessage(box.handle, 0x0186, row, 0) == -1:
        raise RuntimeError(f"shop row {row} unavailable")
    win32gui.SendMessage(win32gui.GetParent(box.handle), win32con.WM_COMMAND, 1810 | (1 << 16), box.handle)
    time.sleep(0.08)


def combo_index(driver: Win32LegacyDriver, control_id: int) -> int:
    return int(win32gui.SendMessage(driver._control(control_id, "ComboBox").handle, 0x0147, 0, 0))


def read_field(driver: Win32LegacyDriver, field: dict[str, object]) -> int | str:
    family = str(field["family"])
    if family.startswith("item_"):
        select_item(driver, int(field["row"]))
        value = driver._control(int(field["control_id"]), "Edit").window_text()
        return int(value) if family == "item_price" else value
    select_shop(driver, int(field["shop_row"]))
    if family == "shop_dialogue_text":
        return driver._control(int(field["control_id"]), "Edit").window_text()
    return combo_index(driver, int(field["control_id"]))


def mutate_text(text: str) -> str:
    if not text:
        return "！"
    replacements = (("佐", "玛"), ("玛", "佐"), ("我", "你"), ("你", "我"), ("一", "二"), ("上", "下"), ("左", "右"), ("是", "否"), ("！", "？"), ("？", "！"), ("。", "，"), ("，", "。"))
    for old, new in replacements:
        if old in text:
            return text.replace(old, new, 1)
    for index, char in enumerate(text):
        if "\u4e00" <= char <= "\u9fff":
            return text[:index] + ("我" if char != "我" else "你") + text[index + 1:]
    for old, new in (("C", "T"), ("T", "C"), ("_", "！")):
        if old in text:
            return text.replace(old, new, 1)
    raise ValueError(f"no safe text mutation for {text!r}")


def mutation_for(driver: Win32LegacyDriver, field: dict[str, object], actual: int | str) -> int | str:
    family = str(field["family"])
    if family == "item_price":
        return int(actual) - 10 if int(actual) >= 99990 else int(actual) + 10
    if family in {"shop_item", "shop_clerk", "shop_dialogue_id"}:
        count = int(win32gui.SendMessage(driver._control(int(field["control_id"]), "ComboBox").handle, 0x0146, 0, 0))
        return (int(actual) + 1) % count
    return mutate_text(str(actual))


def commit_field(driver: Win32LegacyDriver, field: dict[str, object], value: int | str) -> None:
    family = str(field["family"])
    if family.startswith("item_"):
        select_item(driver, int(field["row"]))
        driver.perform(({"op": "set_text_notify", "class": "Edit", "control_id": int(field["control_id"]), "value": str(value)},), value)
    else:
        select_shop(driver, int(field["shop_row"]))
        if family == "shop_dialogue_text":
            driver.perform(({"op": "set_text_notify", "class": "Edit", "control_id": int(field["control_id"]), "value": str(value)},), value)
        else:
            driver.perform(({"op": "select_index_message", "class": "ComboBox", "control_id": int(field["control_id"]), "value": int(value)},), value)
    driver.perform(({"op": "click_id", "class": "Button", "control_id": 590},), 0)
    time.sleep(0.22)


def save_with_retry(driver: Win32LegacyDriver) -> None:
    last: Exception | None = None
    for _attempt in range(3):
        try:
            driver.save()
            return
        except RuntimeError as error:
            last = error
            time.sleep(0.4)
    raise last or RuntimeError("save failed")


def collect_session(fields: list[dict[str, object]], start: int, stop: int) -> None:
    driver = launch("collector")
    try:
        driver.open_rom(WORK)
        open_database(driver)
        for index in range(start, stop):
            field = fields[index]
            actual_before = read_field(driver, field)
            requested = mutation_for(driver, field, actual_before)
            before = WORK.read_bytes()
            commit_field(driver, field, requested)
            save_with_retry(driver)
            observed = WORK.read_bytes()
            observed_ranges = diff_ranges(before, observed)
            open_database(driver)
            actual_after = read_field(driver, field)
            safe = bool(field["product_safe"])
            if actual_after == requested and safe:
                status, after, ranges = "saved", observed, observed_ranges
            elif actual_after == requested:
                status, after, ranges = "reference_saved_product_blocked", before, []
                WORK.write_bytes(before)
            elif actual_after == actual_before:
                status = "no_effect" if safe else "blocked_no_effect"
                after, ranges = before, []
                WORK.write_bytes(before)
            else:
                status = "unexpected_readback" if safe else "blocked_unstable"
                after, ranges = before, []
                WORK.write_bytes(before)
            semantic_changed = any(offset not in NORMALIZATION_OFFSETS for change in observed_ranges for offset in range(int(change["start"]), int(change["end_exclusive"])))
            append_evidence({
                "sequence": index, "field_id": field["field_id"], "physical_id": field["physical_id"], "family": field["family"],
                "product_safe": safe, "original": actual_before, "mutated": requested, "status": status,
                "before_sha256": sha(before), "after_sha256": sha(after), "observed_after_sha256": sha(observed),
                "semantic_changed": semantic_changed, "changed_bytes": sum(int(change["end_exclusive"]) - int(change["start"]) for change in observed_ranges),
                "ranges": ranges, "observed_ranges": observed_ranges, "same_process_reopen_readback": actual_after,
            })
            save_state(index + 1, sha(after), len(fields))
            if status == "unexpected_readback":
                raise RuntimeError(f"safe field {field['field_id']} had unexpected readback")
            if not safe:
                # A blocked reference action can remain dirty in the editor's
                # in-memory image even after WORK is restored.  Reload the
                # clean file so every blocked observation is an isolated
                # single-field experiment rather than a cumulative diff.
                driver.perform(({"op": "click_id", "class": "Button", "control_id": 600},), 0)
                driver.open_rom(WORK)
                open_database(driver)
            if (index + 1) % 10 == 0 or index + 1 == stop:
                log(f"probed {index + 1}/{len(fields)}")
    finally:
        driver.stop()


def collect(fields: list[dict[str, object]], start: int, stop: int) -> None:
    cursor, failures = start, 0
    while cursor < stop:
        session_stop = min(stop, cursor + 20)
        try:
            collect_session(fields, cursor, session_stop)
            cursor, failures = session_stop, 0
        except Exception as error:
            failures += 1
            log(f"collector failed at {cursor}: {error}")
            rebuilt, _ = rebuild_work_from_evidence(len(fields))
            cursor = rebuilt
            if failures >= 3:
                raise


def inventory(driver: Win32LegacyDriver, fields: list[dict[str, object]]) -> dict[str, int | str]:
    values: dict[str, int | str] = {}
    by_item: dict[int, list[dict[str, object]]] = {}
    by_shop: dict[int, list[dict[str, object]]] = {}
    for field in fields:
        if str(field["family"]).startswith("item_"):
            by_item.setdefault(int(field["row"]), []).append(field)
        else:
            by_shop.setdefault(int(field["shop_row"]), []).append(field)
    completed = 0
    for row, group in sorted(by_item.items()):
        select_item(driver, row)
        for field in group:
            value = driver._control(int(field["control_id"]), "Edit").window_text()
            values[str(field["field_id"])] = int(value) if field["family"] == "item_price" else value
            completed += 1
        log(f"inventory {completed}/{len(fields)}")
    for row, group in sorted(by_shop.items()):
        select_shop(driver, row)
        for field in group:
            if field["family"] == "shop_dialogue_text":
                value = driver._control(int(field["control_id"]), "Edit").window_text()
            else:
                value = combo_index(driver, int(field["control_id"]))
            values[str(field["field_id"])] = value
            completed += 1
        log(f"inventory {completed}/{len(fields)}")
    return values


def cold_readback(fields: list[dict[str, object]]) -> None:
    warm = launch("same-process final inventory")
    try:
        warm.open_rom(WORK)
        open_database(warm)
        expected = inventory(warm, fields)
        SAME_PROCESS.write_text(json.dumps(expected, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    finally:
        warm.stop()
    cold = launch("cold final inventory")
    try:
        cold.open_rom(WORK)
        open_database(cold)
        actual = inventory(cold, fields)
        COLD_PROCESS.write_text(json.dumps(actual, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    finally:
        cold.stop()
    failures = [{"field_id": key, "expected": value, "actual": actual.get(key)} for key, value in expected.items() if actual.get(key) != value]
    if failures:
        raise ValueError(f"cold readback failed for {len(failures)} fields: {failures[:5]}")
    statuses = Counter(json.loads(line)["status"] for line in EVIDENCE.read_text(encoding="utf-8").splitlines())
    shutil.copy2(WORK, FINAL)
    SUMMARY.write_text(json.dumps({
        "passed": True, "logical_fields": len(fields), "save_probe_fields": len(fields),
        "product_safe_candidates": sum(bool(field["product_safe"]) for field in fields),
        "product_blocked_candidates": sum(not bool(field["product_safe"]) for field in fields),
        "statuses": dict(sorted(statuses.items())), "saved_fields": statuses["saved"], "no_effect_fields": statuses["no_effect"],
        "reference_saved_product_blocked_fields": statuses["reference_saved_product_blocked"],
        "blocked_no_effect_fields": statuses["blocked_no_effect"], "blocked_unstable_fields": statuses["blocked_unstable"],
        "baseline_sha256": sha(DEFAULT_ROM.read_bytes()), "final_sha256": sha(WORK.read_bytes()),
        "same_process_reopen_probe_count": len(fields), "cold_process_logical_readback_passed": len(fields),
        "evidence": EVIDENCE.relative_to(ROOT).as_posix(), "final_rom": FINAL.relative_to(ROOT).as_posix(),
    }, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", type=int)
    parser.add_argument("--restart", action="store_true")
    parser.add_argument("--rewind", type=int)
    args = parser.parse_args()
    OUT.mkdir(parents=True, exist_ok=True)
    catalog = json.loads(CATALOG_PATH.read_text(encoding="utf-8"))
    fields = ordered_fields(catalog)
    if len(fields) != 254:
        raise ValueError(f"expected 254 save probes, got {len(fields)}")
    if args.restart:
        shutil.copy2(DEFAULT_ROM, WORK)
        for path in (EVIDENCE, STATE, SUMMARY, FINAL, SAME_PROCESS, COLD_PROCESS, OUT / "error.log"):
            path.unlink(missing_ok=True)
        PROGRESS.write_text("restart\n", encoding="utf-8")
    elif args.rewind is not None:
        lines = EVIDENCE.read_text(encoding="utf-8").splitlines()
        EVIDENCE.write_text("\n".join(lines[:args.rewind]) + ("\n" if args.rewind else ""), encoding="utf-8")
        for path in (STATE, SUMMARY, FINAL, SAME_PROCESS, COLD_PROCESS, OUT / "error.log"):
            path.unlink(missing_ok=True)
        rebuild_work_from_evidence(len(fields))
    elif not WORK.exists():
        shutil.copy2(DEFAULT_ROM, WORK)
    state = json.loads(STATE.read_text(encoding="utf-8")) if STATE.exists() else {"completed": 0}
    start = int(state["completed"])
    if start and sha(WORK.read_bytes()) != state["current_sha256"]:
        start, _ = rebuild_work_from_evidence(len(fields))
    stop = len(fields) if args.limit is None else min(len(fields), start + args.limit)
    if start < stop:
        collect(fields, start, stop)
    if stop == len(fields):
        cold_readback(fields)
    return 0


if __name__ == "__main__":
    try:
        result = main()
    except Exception:
        OUT.mkdir(parents=True, exist_ok=True)
        (OUT / "error.log").write_text(traceback.format_exc(), encoding="utf-8")
        raise
    raise SystemExit(result)
