"""Collect resumable reference-save evidence for every M09 physical field."""

from __future__ import annotations

import argparse
import ctypes
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
from tools.report_m09_reference_field_catalog import DEFAULT_JSON as CATALOG_PATH, DEFAULT_ROM


AUDIT = ROOT / "output/build/legacy-diff-audit"
OUT = ROOT / "output/verification/legacy-m09-all-fields-20260920"
WORK = OUT / "work.nes"
FINAL = OUT / "after-all-fields.nes"
EVIDENCE = OUT / "field-save-chain.jsonl"
STATE = OUT / "state.json"
SUMMARY = OUT / "summary.json"
PROGRESS = OUT / "progress.log"
NORMALIZATION_OFFSETS = {0x4A101, 0x4A102, 0x4AE2A, 0x4AE2B, 0x79538, 0x79539}


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def log(message: str) -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    with PROGRESS.open("a", encoding="utf-8") as stream:
        stream.write(message + "\n")


def fields_to_probe(catalog: dict[str, object]) -> list[dict[str, object]]:
    # Preserve the original physical-representative prefix so an interrupted
    # 213-record evidence chain remains resumable.  Reference saves split
    # shared system/growth pointers, so every remaining logical field is then
    # appended and must be exercised independently.
    result: list[dict[str, object]] = []
    seen: set[str] = set()
    for field in catalog["fields"]:
        physical_id = str(field["physical_id"])
        if physical_id not in seen:
            seen.add(physical_id)
            result.append(field)
    included = {str(field["field_id"]) for field in result}
    result.extend(field for field in catalog["fields"] if str(field["field_id"]) not in included)
    return result


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
            result.append({
                "start": start,
                "end_exclusive": end,
                "before_hex": before[start:end].hex().upper(),
                "after_hex": after[start:end].hex().upper(),
            })
            start = offset
        previous = offset
    return result


def append_evidence(payload: dict[str, object]) -> None:
    with EVIDENCE.open("a", encoding="utf-8") as stream:
        stream.write(json.dumps(payload, ensure_ascii=False, separators=(",", ":")) + "\n")
        stream.flush()


def save_state(completed: int, current_sha: str, total: int) -> None:
    STATE.write_text(
        json.dumps({"completed": completed, "total": total, "current_sha256": current_sha}, indent=2) + "\n",
        encoding="utf-8",
    )


def rebuild_work_from_evidence(total: int) -> tuple[int, str]:
    data = bytearray(DEFAULT_ROM.read_bytes())
    completed = 0
    if EVIDENCE.exists():
        for line in EVIDENCE.read_text(encoding="utf-8").splitlines():
            item = json.loads(line)
            if sha(bytes(data)) != item["before_sha256"]:
                raise ValueError(f"evidence chain breaks before sequence {item['sequence']}")
            for change in item["ranges"]:
                start = int(change["start"])
                end = int(change["end_exclusive"])
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
    driver.perform(
        (
            {"op": "menu", "path": "数据->数据库"},
            {"op": "window", "title": "数据库"},
            {"op": "click_coords", "x": 390, "y": 62},
        ),
        0,
    )


def select_listview(driver: Win32LegacyDriver, control_id: int, row: int) -> None:
    table = driver._control(control_id, "SysListView32")
    # These Easy Language list views ignore programmatic state messages and
    # report off-by-one item rectangles.  Keyboard navigation is stable once
    # the real control owns focus.  Always reset with HOME, then verify the
    # selected index before exposing the adjacent edit control.
    table.set_focus()
    table.click_input(coords=(35, 45))
    table.type_keys("{HOME}")
    if row:
        table.type_keys(f"{{DOWN {row}}}")
    time.sleep(0.12)
    selected = int(win32gui.SendMessage(table.handle, 0x100C, -1, 0x0002))
    if selected != row:
        raise RuntimeError(f"ListView {control_id} selected row {selected}, expected {row}")


def select_listbox(driver: Win32LegacyDriver, control_id: int, row: int) -> None:
    box = driver._control(control_id, "ListBox")
    if win32gui.SendMessage(box.handle, 0x0186, row, 0) == -1:
        raise RuntimeError(f"ListBox row {row} is unavailable")
    parent = win32gui.GetParent(box.handle)
    win32gui.SendMessage(parent, win32con.WM_COMMAND, control_id | (1 << 16), box.handle)
    time.sleep(0.08)


def select_combo(driver: Win32LegacyDriver, control_id: int, index: int) -> None:
    driver.perform(
        ({"op": "select_index_message", "class": "ComboBox", "control_id": control_id, "value": index},),
        0,
    )


def growth_dialog(driver: Win32LegacyDriver):
    database = driver.current_window
    driver.perform(({"op": "click_id_message", "class": "Button", "control_id": 2650},), 0)
    dialog = driver._wait_window(lambda item: item.is_visible() and item.window_text() == "成长属性")
    driver.current_window = dialog
    return database, dialog


def close_growth_dialog(driver: Win32LegacyDriver, database, button_id: int) -> None:
    dialog_handle = int(driver.current_window.handle)
    driver.perform(({"op": "click_id_message", "class": "Button", "control_id": button_id},), 0)
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline and win32gui.IsWindow(dialog_handle):
        time.sleep(0.05)
    if win32gui.IsWindow(dialog_handle):
        raise RuntimeError("growth dialog did not close")
    driver.current_window = database


def read_field(driver: Win32LegacyDriver, field: dict[str, object]) -> int | str:
    family = str(field["family"])
    if family == "distance":
        select_combo(driver, 1600, int(field["selector_index"]))
        select_listview(driver, 1580, int(field["row"]))
        return int(driver._control(1640, "Edit").window_text())
    if family == "experience":
        select_listview(driver, 1570, int(field["row"]))
        return int(driver._control(1650, "Edit").window_text())
    if family == "system":
        select_listbox(driver, 1750, int(field["row"]))
        return driver._control(1770, "Edit").window_text()
    if family == "growth":
        select_combo(driver, 2620, int(field["selector_index"]))
        database, _dialog = growth_dialog(driver)
        value = driver._control(100, "Edit").window_text().upper()
        close_growth_dialog(driver, database, 120)
        return value
    raise ValueError(f"unsupported family {family}")


def mutation_for(field: dict[str, object], actual: int | str) -> int | str:
    family = str(field["family"])
    if family == "distance":
        value = int(actual)
        return value - 1 if value >= 100 else value + 1
    if family == "experience":
        value = int(actual)
        return value - 1 if value >= 65535 else value + 1
    if family == "growth":
        value = str(actual)
        replacement = "1" if value[0] == "0" else "0"
        return replacement + value[1:]
    text = str(actual)
    if not text:
        return "！"
    replacements = (
        ("我", "你"), ("你", "我"), ("一", "二"), ("上", "下"),
        ("左", "右"), ("是", "否"), ("！", "？"), ("？", "！"),
        ("：", "！"), ("。", "，"), ("，", "。"),
    )
    for old, new in replacements:
        if old in text:
            return text.replace(old, new, 1)
    protected: set[int] = set()
    cursor = 0
    spans = {"{": 7, "[": 5, "|": 3, "*": 4}
    while cursor < len(text):
        length = spans.get(text[cursor], 0)
        if length and all(char in "0123456789ABCDEFabcdef" for char in text[cursor + 1:cursor + length]):
            protected.update(range(cursor, min(len(text), cursor + length)))
            cursor += length
        else:
            cursor += 1
    for index, char in enumerate(text):
        if index not in protected and "\u4e00" <= char <= "\u9fff":
            return text[:index] + ("我" if char != "我" else "你") + text[index + 1:]
    raise ValueError(f"no safe mutation for {field['field_id']}: {text!r}")


def commit_field(driver: Win32LegacyDriver, field: dict[str, object], value: int | str) -> None:
    family = str(field["family"])
    if family == "distance":
        select_combo(driver, 1600, int(field["selector_index"]))
        select_listview(driver, 1580, int(field["row"]))
        driver.perform(({"op": "set_text_notify", "class": "Edit", "control_id": 1640, "value": str(value)},), value)
    elif family == "experience":
        select_listview(driver, 1570, int(field["row"]))
        # The reference page does not commit this edit on the database OK
        # button.  It commits on a real focus transition from the edit.
        driver.perform(({"op": "set_text_notify", "class": "Edit", "control_id": 1650, "value": str(value)},), value)
        driver._control(1650, "Edit").type_keys("{TAB}")
        time.sleep(0.2)
    elif family == "system":
        select_listbox(driver, 1750, int(field["row"]))
        driver.perform(({"op": "set_text_notify", "class": "Edit", "control_id": 1770, "value": str(value)},), value)
    elif family == "growth":
        select_combo(driver, 2620, int(field["selector_index"]))
        database, _dialog = growth_dialog(driver)
        driver.perform(({"op": "set_text_notify", "class": "Edit", "control_id": 100, "value": str(value)},), value)
        close_growth_dialog(driver, database, 110)
    else:
        raise ValueError(f"unsupported family {family}")
    driver.perform(({"op": "click_id", "class": "Button", "control_id": 590},), 0)
    time.sleep(0.25)


def save_with_retry(driver: Win32LegacyDriver) -> None:
    last_error: Exception | None = None
    for _attempt in range(3):
        try:
            driver.save()
            return
        except RuntimeError as error:
            last_error = error
            time.sleep(0.5)
    assert last_error is not None
    raise last_error


def collect_session(fields: list[dict[str, object]], start: int, stop: int) -> None:
    driver = launch("collector")
    try:
        driver.open_rom(WORK)
        open_database(driver)
        for index in range(start, stop):
            field = fields[index]
            actual_before = read_field(driver, field)
            requested = mutation_for(field, actual_before)
            before = WORK.read_bytes()
            commit_field(driver, field, requested)
            save_with_retry(driver)
            observed_after = WORK.read_bytes()
            observed_ranges = diff_ranges(before, observed_after)
            semantic_changed = any(
                offset not in NORMALIZATION_OFFSETS
                for item in observed_ranges
                for offset in range(int(item["start"]), int(item["end_exclusive"]))
            )
            open_database(driver)
            actual_after = read_field(driver, field)
            if actual_after == requested:
                status = "saved"
                after = observed_after
                ranges = observed_ranges
            elif actual_after == actual_before:
                status = "no_effect" if not semantic_changed else "unsafe_unreadable_write"
                after = before
                ranges = []
                WORK.write_bytes(before)
            else:
                status = "unexpected_readback"
                after = before
                ranges = []
                WORK.write_bytes(before)
            append_evidence({
                "sequence": index,
                "field_id": field["field_id"],
                "physical_id": field["physical_id"],
                "family": field["family"],
                "original": actual_before,
                "mutated": requested,
                "status": status,
                "before_sha256": sha(before),
                "after_sha256": sha(after),
                "observed_after_sha256": sha(observed_after),
                "changed_bytes": sum(int(item["end_exclusive"]) - int(item["start"]) for item in observed_ranges),
                "ranges": ranges,
                "observed_ranges": observed_ranges,
                "same_process_reopen_readback": actual_after,
            })
            save_state(index + 1, sha(after), len(fields))
            if status.startswith("unsafe") or status == "unexpected_readback":
                raise RuntimeError(f"{field['field_id']} archived as {status}; restart required")
            if (index + 1) % 10 == 0 or index + 1 == stop:
                log(f"saved {index + 1}/{len(fields)}")
    finally:
        driver.stop()


def collect(fields: list[dict[str, object]], start: int, stop: int) -> None:
    cursor = start
    consecutive_failures = 0
    while cursor < stop:
        session_stop = min(stop, cursor + 20)
        try:
            collect_session(fields, cursor, session_stop)
            cursor = session_stop
            consecutive_failures = 0
        except Exception as error:
            consecutive_failures += 1
            log(f"collector failed at {cursor}: {error}")
            rebuilt, _current_sha = rebuild_work_from_evidence(len(fields))
            if rebuilt > cursor:
                consecutive_failures = 0
            cursor = rebuilt
            if consecutive_failures >= 3:
                raise


def expected_values(catalog: dict[str, object]) -> dict[str, int | str]:
    expected: dict[str, int | str] = {}
    for field in catalog["fields"]:
        family = str(field["family"])
        if family in {"distance", "experience"}:
            expected[str(field["field_id"])] = int(field["value"])
        elif family == "system":
            expected[str(field["field_id"])] = str(field["text"])
        else:
            expected[str(field["field_id"])] = str(field["quick_hex"])
    for line in EVIDENCE.read_text(encoding="utf-8").splitlines():
        item = json.loads(line)
        if item["status"] != "saved":
            continue
        expected[str(item["field_id"])] = item["mutated"]
    # Experience edits store cumulative totals and ripple through later rows.
    # Derive the final "升级还需" display from the final ROM instead of
    # freezing the catalog's original values.
    data = WORK.read_bytes()
    offset = int(catalog["layout"]["experience_offset"])
    totals = [0] + [int.from_bytes(data[offset + index * 2:offset + index * 2 + 2], "little") for index in range(59)]
    for row in range(59):
        expected[f"M09/experience/{row + 1:02d}"] = totals[row + 1] - totals[row]
    expected["M09/experience/60"] = 0
    return expected


def cold_readback(catalog: dict[str, object], probes: list[dict[str, object]]) -> None:
    expected = expected_values(catalog)
    driver = launch("cold readback")
    failures: list[dict[str, object]] = []
    try:
        driver.open_rom(WORK)
        open_database(driver)
        for index, field in enumerate(catalog["fields"]):
            actual = read_field(driver, field)
            wanted = expected[str(field["field_id"])]
            if actual != wanted:
                failures.append({"field_id": field["field_id"], "expected": wanted, "actual": actual})
            if (index + 1) % 25 == 0:
                log(f"cold readback {index + 1}/{len(catalog['fields'])}")
    finally:
        driver.stop()
    if failures:
        raise ValueError(f"cold readback failed for {len(failures)} fields: {failures[:5]}")
    statuses = Counter(json.loads(line)["status"] for line in EVIDENCE.read_text(encoding="utf-8").splitlines())
    shutil.copy2(WORK, FINAL)
    SUMMARY.write_text(json.dumps({
        "passed": True,
        "logical_fields": len(catalog["fields"]),
        "save_probe_fields": len(probes),
        "initial_physical_candidates": int(catalog["counts"]["physical_fields_including_constant"]),
        "persistent_physical_fields": int(catalog["counts"]["persistent_physical_fields"]),
        "saved_fields": statuses["saved"],
        "no_effect_fields": statuses["no_effect"],
        "unsafe_unreadable_write_fields": statuses["unsafe_unreadable_write"],
        "baseline_sha256": sha(DEFAULT_ROM.read_bytes()),
        "final_sha256": sha(WORK.read_bytes()),
        "same_process_reopen_passed": len(probes),
        "cold_process_logical_readback_passed": len(catalog["fields"]),
        "evidence": EVIDENCE.relative_to(ROOT).as_posix(),
        "final_rom": FINAL.relative_to(ROOT).as_posix(),
    }, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", type=int)
    parser.add_argument("--restart", action="store_true")
    parser.add_argument("--rewind", type=int)
    args = parser.parse_args()
    OUT.mkdir(parents=True, exist_ok=True)
    catalog = json.loads(CATALOG_PATH.read_text(encoding="utf-8"))
    probes = fields_to_probe(catalog)
    if len(probes) != 414:
        raise ValueError(f"expected 414 logical save probes, got {len(probes)}")
    if args.restart:
        shutil.copy2(DEFAULT_ROM, WORK)
        for path in (EVIDENCE, STATE, SUMMARY, FINAL, OUT / "error.log"):
            path.unlink(missing_ok=True)
        PROGRESS.write_text("restart\n", encoding="utf-8")
    elif args.rewind is not None:
        lines = EVIDENCE.read_text(encoding="utf-8").splitlines()
        if not 0 <= args.rewind <= len(lines):
            raise ValueError(f"rewind must be within 0..{len(lines)}")
        EVIDENCE.write_text("\n".join(lines[:args.rewind]) + ("\n" if args.rewind else ""), encoding="utf-8")
        for path in (STATE, SUMMARY, FINAL, OUT / "error.log"):
            path.unlink(missing_ok=True)
        start, _current_sha = rebuild_work_from_evidence(len(probes))
        log(f"rewound evidence to {start}/{len(probes)}")
    elif not WORK.exists():
        shutil.copy2(DEFAULT_ROM, WORK)
    state = json.loads(STATE.read_text(encoding="utf-8")) if STATE.exists() else {"completed": 0}
    start = int(state["completed"])
    if start and sha(WORK.read_bytes()) != state["current_sha256"]:
        start, _current_sha = rebuild_work_from_evidence(len(probes))
    stop = len(probes) if args.limit is None else min(len(probes), start + args.limit)
    if start < stop:
        collect(probes, start, stop)
    if stop == len(probes):
        cold_readback(catalog, probes)
    return 0


if __name__ == "__main__":
    try:
        result = main()
    except Exception:
        OUT.mkdir(parents=True, exist_ok=True)
        (OUT / "error.log").write_text(traceback.format_exc(), encoding="utf-8")
        raise
    raise SystemExit(result)
