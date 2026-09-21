"""Collect cumulative, per-physical-field M08 reference save evidence.

Every step starts from the previous verified save, changes exactly one still
untouched physical text field, saves, records the complete byte delta, reopens
the database, and verifies the edited UI value.  The chain is reconstructable
through its before/after SHA-256 values and byte ranges.  A completed chain is
then read back field-by-field from a new reference-editor process.
"""

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

from src.fc_editor.codecs.story_text import StoryTextCodec
from src.fc_editor.dc_text import default_dc_text_table
from tools.golden_pipeline_collect import Win32LegacyDriver
from tools.report_m08_reference_physical_catalog import (
    DEFAULT_JSON as CATALOG_PATH,
    DEFAULT_ROM,
    ui_body,
)


AUDIT = ROOT / "output/build/legacy-diff-audit"
OUT = ROOT / "output/verification/legacy-m08-all-fields-20260920"
WORK = OUT / "work.nes"
FINAL = OUT / "after-all-fields.nes"
EVIDENCE = OUT / "field-save-chain.jsonl"
STATE = OUT / "state.json"
SUMMARY = OUT / "summary.json"
PROGRESS = OUT / "progress.log"
GROUP_INDEX = {"00": 0, "01": 1, "04": 2, "05": 3, "07": 4}


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def log(message: str) -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    with PROGRESS.open("a", encoding="utf-8") as stream:
        stream.write(message + "\n")


def unique_fields(catalog: dict[str, object]) -> list[dict[str, object]]:
    result: list[dict[str, object]] = []
    seen: set[str] = set()
    for field in catalog["fields"]:
        physical_id = str(field["physical_id"])
        if physical_id not in seen:
            seen.add(physical_id)
            result.append(field)
    return result


def mutation_for(field: dict[str, object]) -> str:
    text = str(field["text"])
    raw = bytes.fromhex(str(field["raw_hex"]))[:-1]
    table = default_dc_text_table()
    if not raw:
        # The reference UI exposes one genuinely empty 01-group field.  A
        # one-byte punctuation glyph is the smallest observable save probe.
        return "！"
    candidates = {
        1: ("！", "？", "。", "，", "A", "B", "0", "1"),
        2: ("一", "二", "我", "你", "他", "来", "去"),
    }
    cursor = 0
    for token in StoryTextCodec.tokenize(raw):
        token_text = table.byte_to_text.get(token.raw, f"<{token.raw.hex().upper()}>")
        end = cursor + len(token_text)
        if len(token_text) == 1 and token_text not in {"\n", "\r", "\\"}:
            for replacement in candidates.get(len(token.raw), ()):
                if replacement == token_text:
                    continue
                try:
                    encoded = table.encode(replacement)
                except ValueError:
                    continue
                if len(encoded) != len(token.raw):
                    continue
                mutated = text[:cursor] + replacement + text[end:]
                preserved = table.encode_preserving_tokens(raw, mutated)
                if len(preserved) == len(raw):
                    return mutated
        cursor = end
    raise ValueError(f"No equal-width editable glyph found for {field['field_id']}")


def edit_value(text: str) -> str:
    return text.replace("\n", "\\\r\n")


def diff_ranges(before: bytes, after: bytes) -> list[dict[str, object]]:
    changed = [index for index, pair in enumerate(zip(before, after)) if pair[0] != pair[1]]
    if len(before) != len(after):
        raise ValueError("reference save changed ROM size")
    ranges: list[dict[str, object]] = []
    if not changed:
        return ranges
    start = previous = changed[0]
    for offset in changed[1:] + [changed[-1] + 2]:
        if offset != previous + 1:
            end = previous + 1
            ranges.append(
                {
                    "start": start,
                    "end_exclusive": end,
                    "before_hex": before[start:end].hex().upper(),
                    "after_hex": after[start:end].hex().upper(),
                }
            )
            start = offset
        previous = offset
    return ranges


def navigate(driver: Win32LegacyDriver, field: dict[str, object]) -> None:
    driver.perform(
        (
            {
                "op": "select_index_message",
                "class": "ComboBox",
                "control_id": 1410,
                "value": GROUP_INDEX[str(field["segment"])],
            },
            {"op": "list_select", "class": "ListBox", "control_id": 1390, "row": int(field["row"])},
            {"op": "list_select", "class": "ListBox", "control_id": 2580, "row": int(field["variant"])},
        ),
        0,
    )


def control_handles(driver: Win32LegacyDriver) -> dict[int, int]:
    if driver.current_window is None:
        raise RuntimeError("database window is unavailable")
    wanted = {1410, 1390, 2580, 1370, 590}
    result: dict[int, int] = {}

    def visit(hwnd: int, _extra: object) -> bool:
        control_id = int(win32gui.GetDlgCtrlID(hwnd))
        if control_id in wanted and win32gui.IsWindowVisible(hwnd) and win32gui.IsWindowEnabled(hwnd):
            result[control_id] = hwnd
        return True

    win32gui.EnumChildWindows(int(driver.current_window.handle), visit, None)
    missing = wanted - set(result)
    if missing:
        raise RuntimeError(f"M08 database controls are missing: {sorted(missing)}")
    return result


def open_database(driver: Win32LegacyDriver) -> None:
    last_error: Exception | None = None
    for attempt in range(1, 4):
        time.sleep(0.8)
        try:
            driver.current_window = driver._main()
            driver.perform(
                (
                    {"op": "menu", "path": "数据->数据库"},
                    {"op": "window", "title": "数据库"},
                    {"op": "click_coords", "x": 310, "y": 73},
                ),
                0,
            )
            return
        except (OSError, RuntimeError) as error:
            last_error = error
            log(f"open database attempt {attempt} failed: {error}")
    assert last_error is not None
    raise last_error


def read_selected(driver: Win32LegacyDriver, field: dict[str, object]) -> str:
    handle = control_handles(driver)[2580]
    index = int(field["variant"])
    length = int(win32gui.SendMessage(handle, 0x018A, index, 0))
    if length < 0:
        raise RuntimeError(f"M08 variant {index} is unavailable")
    buffer = ctypes.create_unicode_buffer(length + 1)
    if int(win32gui.SendMessage(handle, 0x0189, index, buffer)) < 0:
        raise RuntimeError(f"M08 variant {index} text read failed")
    return ui_body(buffer.value)


def commit_text(driver: Win32LegacyDriver, value: str) -> None:
    driver.perform(
        (
            {
                "op": "set_text_notify",
                "class": "Edit",
                "control_id": 1370,
                "value": edit_value(value),
            },
            {"op": "click_id", "class": "Button", "control_id": 590},
        ),
        value,
    )


def append_evidence(payload: dict[str, object]) -> None:
    with EVIDENCE.open("a", encoding="utf-8") as stream:
        stream.write(json.dumps(payload, ensure_ascii=False, separators=(",", ":")) + "\n")
        stream.flush()


def save_with_retry(driver: Win32LegacyDriver, field_id: str) -> None:
    last_error: Exception | None = None
    for attempt in range(1, 4):
        try:
            driver.save()
            if attempt > 1:
                log(f"{field_id}: save succeeded on attempt {attempt}")
            return
        except RuntimeError as error:
            last_error = error
            log(f"{field_id}: save attempt {attempt} timed out")
            time.sleep(0.6)
    assert last_error is not None
    raise last_error


def launch_with_retry(label: str) -> Win32LegacyDriver:
    last_error: Exception | None = None
    for attempt in range(1, 4):
        driver = Win32LegacyDriver()
        try:
            pid = driver.launch(AUDIT / "SRW2_patched.exe", AUDIT)
            log(f"{label} launched pid={pid} on attempt {attempt}")
            return driver
        except Exception as error:
            last_error = error
            log(f"{label} launch attempt {attempt} failed: {error}")
            try:
                driver.stop()
            except Exception:
                pass
            time.sleep(0.8)
    assert last_error is not None
    raise last_error


def save_state(completed: int, current_sha: str, total: int) -> None:
    STATE.write_text(
        json.dumps(
            {"completed": completed, "total": total, "current_sha256": current_sha},
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )


def rebuild_work_from_evidence() -> tuple[int, str]:
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
                replacement = bytes.fromhex(change["after_hex"])
                if len(replacement) != end - start:
                    raise ValueError(f"evidence range length breaks at sequence {item['sequence']}")
                data[start:end] = replacement
            if sha(bytes(data)) != item["after_sha256"]:
                raise ValueError(f"evidence chain breaks after sequence {item['sequence']}")
            completed += 1
    WORK.write_bytes(data)
    current_sha = sha(bytes(data))
    save_state(completed, current_sha, 1095)
    log(f"rebuilt work ROM from {completed} evidence records")
    return completed, current_sha


def collect_session(fields: list[dict[str, object]], start: int, stop: int) -> None:
    driver = launch_with_retry("collector")
    try:
        log(f"collector range={start}:{stop}")
        driver.open_rom(WORK)
        open_database(driver)
        for index in range(start, stop):
            field = fields[index]
            original = str(field["text"])
            mutated = mutation_for(field)
            navigate(driver, field)
            actual_before = read_selected(driver, field)
            if actual_before != original:
                raise ValueError(
                    f"{field['field_id']} before readback differs: {actual_before!r} != {original!r}"
                )
            before = WORK.read_bytes()
            commit_text(driver, mutated)
            save_with_retry(driver, str(field["field_id"]))
            after = WORK.read_bytes()
            ranges = diff_ranges(before, after)
            observed_after_sha = sha(after)
            observed_ranges = ranges
            open_database(driver)
            navigate(driver, field)
            actual_after = read_selected(driver, field)
            no_effect = not ranges
            expected_after = original if no_effect else mutated
            redirected_field: dict[str, object] | None = None
            redirected_readback: str | None = None
            status = "no_effect" if no_effect else "saved"
            if (
                actual_after != expected_after
                and field["field_id"] == "M08/05/000/000"
                and actual_after == original
            ):
                redirected_field = {
                    "field_id": "M08/07/000/000",
                    "segment": "07",
                    "row": 0,
                    "variant": 0,
                }
                navigate(driver, redirected_field)
                redirected_readback = read_selected(driver, redirected_field)
                if redirected_readback == mutated:
                    expected_after = original
                    status = "alias_redirected"
                else:
                    # The 05-side entry deterministically writes bytes that
                    # neither 05 nor its shared 07 entry can read back.  Keep
                    # the observed delta as unsafe evidence, but do not carry
                    # those bytes into the next field's baseline.
                    status = "unsafe_orphan_write"
                    expected_after = original
                    WORK.write_bytes(before)
                    after = before
                    ranges = []
            if actual_after != expected_after or (
                status == "alias_redirected" and redirected_readback != mutated
            ):
                raise ValueError(
                    f"{field['field_id']} after readback differs: {actual_after!r} != {expected_after!r}"
                )
            append_evidence(
                {
                    "sequence": index,
                    "field_id": field["field_id"],
                    "physical_id": field["physical_id"],
                    "segment": field["segment"],
                    "row": field["row"],
                    "variant": field["variant"],
                    "original": original,
                    "mutated": mutated,
                    "before_sha256": sha(before),
                    "after_sha256": sha(after),
                    "observed_after_sha256": observed_after_sha,
                    "status": status,
                    "changed_bytes": sum((item["end_exclusive"] - item["start"]) for item in observed_ranges),
                    "ranges": ranges,
                    "observed_ranges": observed_ranges,
                    "same_process_reopen_readback": actual_after,
                    "expected_reopen": expected_after,
                    "redirected_field": redirected_field,
                    "redirected_readback": redirected_readback,
                }
            )
            save_state(index + 1, sha(after), len(fields))
            if status == "unsafe_orphan_write":
                raise RuntimeError(f"{field['field_id']} unsafe orphan write archived; restart required")
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
            log(f"collector session failed at {cursor}: {error}")
            rebuilt_cursor, _current_sha = rebuild_work_from_evidence()
            if rebuilt_cursor > cursor:
                consecutive_failures = 0
            cursor = rebuilt_cursor
            if consecutive_failures >= 3:
                raise
            time.sleep(0.8)


def cold_readback(fields: list[dict[str, object]]) -> None:
    expected: dict[str, str] = {}
    redirected: list[tuple[dict[str, object], str]] = []
    status_counts: Counter[str] = Counter()
    for line in EVIDENCE.read_text(encoding="utf-8").splitlines():
        item = json.loads(line)
        status_counts[str(item.get("status", "saved"))] += 1
        expected[str(item["physical_id"])] = str(
            item.get("expected_reopen", item["mutated"])
        )
        if item.get("status") == "alias_redirected" and item.get("redirected_field"):
            redirected.append((item["redirected_field"], str(item["mutated"])))
    driver = launch_with_retry("cold readback")
    failures: list[dict[str, object]] = []
    try:
        driver.open_rom(WORK)
        open_database(driver)
        for index, field in enumerate(fields):
            navigate(driver, field)
            actual = read_selected(driver, field)
            wanted = expected[str(field["physical_id"])]
            if actual != wanted:
                failures.append({"field_id": field["field_id"], "expected": wanted, "actual": actual})
            if (index + 1) % 50 == 0:
                log(f"cold readback {index + 1}/{len(fields)}")
        for field, wanted in redirected:
            navigate(driver, field)
            actual = read_selected(driver, field)
            if actual != wanted:
                failures.append({"field_id": field["field_id"], "expected": wanted, "actual": actual})
    finally:
        driver.stop()
    if failures:
        raise ValueError(f"cold readback failed for {len(failures)} fields: {failures[:3]}")
    shutil.copy2(WORK, FINAL)
    SUMMARY.write_text(
        json.dumps(
            {
                "passed": True,
                "physical_fields": len(fields),
                "ui_fields": 1248,
                "duplicate_ui_references": 153,
                "saved_fields": status_counts["saved"],
                "no_effect_fields": status_counts["no_effect"],
                "unsafe_orphan_write_fields": status_counts["unsafe_orphan_write"],
                "baseline_sha256": sha(DEFAULT_ROM.read_bytes()),
                "final_sha256": sha(WORK.read_bytes()),
                "same_process_reopen_passed": len(fields),
                "cold_process_reopen_passed": len(fields),
                "evidence": EVIDENCE.relative_to(ROOT).as_posix(),
                "final_rom": FINAL.relative_to(ROOT).as_posix(),
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    log("cold readback complete")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", type=int)
    parser.add_argument("--restart", action="store_true")
    args = parser.parse_args()
    OUT.mkdir(parents=True, exist_ok=True)
    catalog = json.loads(CATALOG_PATH.read_text(encoding="utf-8"))
    fields = unique_fields(catalog)
    if len(fields) != 1095:
        raise ValueError(f"expected 1095 physical fields, got {len(fields)}")
    if args.restart:
        shutil.copy2(DEFAULT_ROM, WORK)
        EVIDENCE.unlink(missing_ok=True)
        STATE.unlink(missing_ok=True)
        SUMMARY.unlink(missing_ok=True)
        FINAL.unlink(missing_ok=True)
        PROGRESS.write_text("restart\n", encoding="utf-8")
    elif not WORK.exists():
        shutil.copy2(DEFAULT_ROM, WORK)
    state = json.loads(STATE.read_text(encoding="utf-8")) if STATE.exists() else {"completed": 0}
    start = int(state["completed"])
    if start and sha(WORK.read_bytes()) != state["current_sha256"]:
        log("work ROM differs from committed state; rebuilding from evidence")
        start, rebuilt_sha = rebuild_work_from_evidence()
        state = {"completed": start, "current_sha256": rebuilt_sha}
    stop = len(fields) if args.limit is None else min(len(fields), start + args.limit)
    if start < stop:
        collect(fields, start, stop)
    if stop == len(fields):
        cold_readback(fields)
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except BaseException:
        OUT.mkdir(parents=True, exist_ok=True)
        (OUT / "error.log").write_text(traceback.format_exc(), encoding="utf-8")
        raise
