"""Collect resumable per-field save and cold-read evidence for every M14 field."""

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
from tools.research import probe_m14_reference_catalog as ui


AUDIT = ROOT / "output/build/legacy-diff-audit"
SOURCE = AUDIT / "默认配置文件/测试.nes"
CATALOG = ROOT / "output/reports/m14-reference-field-catalog.json"
OUT = ROOT / "output/verification/legacy-m14-all-fields-20260920"
RUNTIME = OUT / "reference-runtime"
NORMALIZED = OUT / "normalized-baseline.nes"
WORK = OUT / "work.nes"
FINAL = OUT / "after-all-fields.nes"
EVIDENCE = OUT / "field-save-chain.jsonl"
STATE = OUT / "state.json"
SUMMARY = OUT / "summary.json"
PROGRESS = OUT / "progress.log"
WARM_VALUES = OUT / "same-process-final-values.json"
COLD_VALUES = OUT / "cold-process-final-values.json"
COLD_CHAIN = OUT / "cold-read-chain.jsonl"
NORMALIZATION = OUT / "normalization.json"
PERSISTENT_FAMILIES = {
    "chapter_initial_victory",
    "surrender_chapter",
    "surrender_ally",
    "surrender_enemy",
    "story_text",
    "victory_text",
}
COMMIT_CLOSE_FAMILIES = {
    "surrender_chapter",
    "surrender_ally",
    "surrender_enemy",
    "story_text",
}
FAMILY_ORDER = {
    "chapter_initial_victory": 0,
    "surrender_chapter": 1,
    "surrender_ally": 2,
    "surrender_enemy": 3,
    "story_text": 4,
    "victory_text": 5,
    "chapter_title": 6,
    "action_name": 7,
    "map_name": 8,
}


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def log(message: str) -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    stamp = time.strftime("%Y-%m-%d %H:%M:%S")
    with PROGRESS.open("a", encoding="utf-8") as stream:
        stream.write(f"{stamp} {message}\n")
        stream.flush()


def diff_ranges(before: bytes, after: bytes) -> list[dict[str, object]]:
    if len(before) != len(after):
        raise RuntimeError("reference save changed ROM size")
    changed = [index for index, pair in enumerate(zip(before, after)) if pair[0] != pair[1]]
    if not changed:
        return []
    result: list[dict[str, object]] = []
    start = previous = changed[0]
    for offset in changed[1:] + [changed[-1] + 2]:
        if offset != previous + 1:
            end = previous + 1
            result.append(
                {
                    "start": start,
                    "end_exclusive": end,
                    "before_hex": before[start:end].hex().upper(),
                    "after_hex": after[start:end].hex().upper(),
                }
            )
            start = offset
        previous = offset
    return result


def fields() -> list[dict[str, object]]:
    catalog = json.loads(CATALOG.read_text(encoding="utf-8"))
    return sorted(
        catalog["fields"],
        key=lambda item: (
            FAMILY_ORDER[str(item["family"])],
            str(item.get("group", "")),
            int(item["row"]),
        ),
    )


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


def launch(label: str) -> Win32LegacyDriver:
    # A true cold read must not inherit the reference editor's mutable sidecar
    # configuration.  Recreate the isolated runtime for every new process;
    # the ROM under test lives outside this directory and remains untouched.
    prepare_runtime()
    driver = Win32LegacyDriver()
    pid = driver.launch(RUNTIME / "SRW2_patched.exe", RUNTIME)
    log(f"{label} launched pid={pid}")
    return driver


def open_editor(driver: Win32LegacyDriver) -> None:
    ui.open_editor(driver)
    controls: dict[tuple[int, str], object] = {}
    for item in driver.current_window.descendants():
        try:
            key = (int(item.control_id()), str(item.class_name()))
            if key[0] and key not in controls:
                controls[key] = item
        except Exception:
            continue
    driver._m14_controls = controls


def control(driver: Win32LegacyDriver, control_id: int, class_name: str):
    cached = getattr(driver, "_m14_controls", {}).get((control_id, class_name))
    if cached is not None:
        return cached
    return ui.any_control(driver, control_id, class_name)


def select_for(driver: Win32LegacyDriver, field: dict[str, object], *, select_page: bool = True) -> None:
    family = str(field["family"])
    if family in {"chapter_title", "chapter_initial_victory"}:
        page_index, selectors = 0, ((220, "ListBox", int(field["row"])),)
    elif family == "action_name":
        page_index, selectors = 1, ((260, "ListBox", int(field["row"])),)
    elif family.startswith("surrender_"):
        page_index, selectors = 2, ((310, "ListBox", int(field["row"])),)
    elif family == "map_name":
        page_index, selectors = 3, ((360, "ListBox", int(field["row"])),)
    elif family == "story_text":
        page_index = 4
        group = control(driver, 570, "ComboBox")
        labels = group.item_texts()
        group_index = labels.index(str(field["group"]))
        selectors = ((570, "ComboBox", group_index), (560, "ListBox", int(field["row"])))
    elif family == "victory_text":
        page_index, selectors = 5, ((630, "ListBox", int(field["row"])),)
    else:
        raise ValueError(f"unknown M14 family {family}")
    if select_page:
        ui.page(driver, page_index)
    for control_id, class_name, row in selectors:
        selected = control(driver, control_id, class_name)
        if class_name == "ComboBox":
            ui.select_combo(selected, row)
        else:
            ui.select_list(selected, row)


def read_selected(driver: Win32LegacyDriver, field: dict[str, object]) -> int | str:
    selected = control(driver, int(field["control_id"]), "ComboBox" if str(field["family"]).startswith("surrender_") else "Edit")
    return int(selected.selected_index()) if selected.class_name() == "ComboBox" else selected.window_text()


def read_field(driver: Win32LegacyDriver, field: dict[str, object], *, select_page: bool = True) -> int | str:
    select_for(driver, field, select_page=select_page)
    return read_selected(driver, field)


def mutation(driver: Win32LegacyDriver, field: dict[str, object], actual: int | str) -> int | str:
    if str(field["family"]).startswith("surrender_"):
        selected = control(driver, int(field["control_id"]), "ComboBox")
        count = len(selected.item_texts())
        return (int(actual) + 1) % count
    text = str(actual)
    if not text:
        return "_"
    return ("C" if text.startswith("_") else "_") + text[1:]


def set_selected(driver: Win32LegacyDriver, field: dict[str, object], value: int | str) -> None:
    control_id = int(field["control_id"])
    if str(field["family"]).startswith("surrender_"):
        ui.select_combo(control(driver, control_id, "ComboBox"), int(value))
        return
    selected = control(driver, control_id, "Edit")
    selected.set_edit_text(str(value))
    parent = win32gui.GetParent(selected.handle)
    win32gui.SendMessage(parent, win32con.WM_COMMAND, control_id | (0x0300 << 16), selected.handle)
    time.sleep(0.04)


def commit_close(driver: Win32LegacyDriver) -> None:
    control(driver, 100, "Button").click()
    handle = int(driver.current_window.handle)
    deadline = time.monotonic() + 5.0
    while win32gui.IsWindow(handle) and time.monotonic() < deadline:
        time.sleep(0.04)
    if win32gui.IsWindow(handle):
        raise RuntimeError("M14 editor did not close after commit")
    driver.current_window = driver._main()


def save_with_retry(driver: Win32LegacyDriver) -> None:
    last: Exception | None = None
    for _attempt in range(3):
        try:
            driver.save()
            return
        except RuntimeError as error:
            last = error
            time.sleep(0.3)
    raise last or RuntimeError("reference save failed")


def append(payload: dict[str, object]) -> None:
    with EVIDENCE.open("a", encoding="utf-8") as stream:
        stream.write(json.dumps(payload, ensure_ascii=False, separators=(",", ":")) + "\n")
        stream.flush()


def append_cold(payload: dict[str, object]) -> None:
    with COLD_CHAIN.open("a", encoding="utf-8") as stream:
        stream.write(json.dumps(payload, ensure_ascii=False, separators=(",", ":")) + "\n")
        stream.flush()


def entries() -> list[dict[str, object]]:
    if not EVIDENCE.exists():
        return []
    return [json.loads(line) for line in EVIDENCE.read_text(encoding="utf-8").splitlines() if line.strip()]


def cold_entries() -> list[dict[str, object]]:
    if not COLD_CHAIN.exists():
        return []
    return [json.loads(line) for line in COLD_CHAIN.read_text(encoding="utf-8").splitlines() if line.strip()]


def save_state(completed: int, total: int) -> None:
    temporary = STATE.with_name(STATE.name + ".tmp")
    temporary.write_text(
        json.dumps({"completed": completed, "total": total, "current_sha256": sha(WORK.read_bytes())}, indent=2) + "\n",
        encoding="utf-8",
    )
    temporary.replace(STATE)


def rebuild_work(evidence: list[dict[str, object]]) -> None:
    data = bytearray(NORMALIZED.read_bytes())
    for item in evidence:
        if sha(bytes(data)) != item["before_sha256"]:
            raise RuntimeError(f"evidence chain broken before {item['sequence']}")
        for change in item["ranges"]:
            start, end = int(change["start"]), int(change["end_exclusive"])
            if data[start:end].hex().upper() != change["before_hex"]:
                raise RuntimeError(f"evidence bytes broken at {item['sequence']}")
            data[start:end] = bytes.fromhex(change["after_hex"])
        if sha(bytes(data)) != item["after_sha256"]:
            raise RuntimeError(f"evidence chain broken after {item['sequence']}")
    WORK.write_bytes(data)


def normalize() -> None:
    shutil.copy2(SOURCE, WORK)
    before = WORK.read_bytes()
    trigger = next(item for item in fields() if item["family"] == "chapter_title")
    driver = launch("normalization")
    try:
        driver.open_rom(WORK)
        open_editor(driver)
        original = read_field(driver, trigger)
        requested = mutation(driver, trigger, original)
        set_selected(driver, trigger, requested)
        commit_close(driver)
        save_with_retry(driver)
    finally:
        driver.stop()
    time.sleep(1.0)
    forward = WORK.read_bytes()
    ranges = diff_ranges(before, forward)
    if not ranges:
        raise RuntimeError("M14 normalization save unexpectedly changed zero bytes")
    cold = launch("normalization-cold-check")
    try:
        cold.open_rom(WORK)
        open_editor(cold)
        cold_readback = read_field(cold, trigger)
    finally:
        cold.stop()
    time.sleep(1.0)
    if cold_readback != original:
        raise RuntimeError(
            f"normalization trigger leaked into a clean runtime: {original!r}->{requested!r}->{cold_readback!r}"
        )
    shutil.copy2(WORK, NORMALIZED)
    NORMALIZATION.write_text(
        json.dumps(
            {
                "source_sha256": sha(before),
                "forward_sha256": sha(forward),
                "normalized_sha256": sha(forward),
                "changed_bytes": sum(int(item["end_exclusive"]) - int(item["start"]) for item in ranges),
                "trigger_field_id": trigger["field_id"],
                "trigger_original": original,
                "trigger_requested": requested,
                "trigger_cold_readback": cold_readback,
                "ranges": ranges,
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    log(f"normalization complete changed_bytes={sum(int(item['end_exclusive']) - int(item['start']) for item in ranges)}")


def verify_previous(driver: Win32LegacyDriver, items: list[dict[str, object]], sequence: int) -> None:
    cold = cold_entries()
    if len(cold) > sequence:
        if cold[sequence]["classification"] == "unstable":
            raise RuntimeError(f"M14 field {cold[sequence]['catalog_field_id']} already has unstable cold evidence")
        return
    if len(cold) != sequence:
        raise RuntimeError(f"M14 cold evidence sequence mismatch: {len(cold)} != {sequence}")
    evidence = entries()[sequence]
    field = items[sequence]
    actual = read_field(driver, field)
    ranges = evidence["ranges"]
    if ranges and actual == evidence["mutated"]:
        classification = "saved"
    elif not ranges and actual == evidence["original"]:
        classification = "no_rom_effect"
    elif not ranges and actual == evidence["mutated"]:
        classification = "external_persistence_without_rom_diff"
    else:
        classification = "unstable"
    append_cold(
        {
            "sequence": sequence,
            "catalog_field_id": field["field_id"],
            "family": field["family"],
            "original": evidence["original"],
            "mutated": evidence["mutated"],
            "cold_process_readback": actual,
            "classification": classification,
            "rom_changed": bool(ranges),
        }
    )
    log(f"cold {sequence + 1}/{len(items)} field={field['field_id']} classification={classification}")
    if classification == "unstable":
        raise RuntimeError(
            f"unstable M14 cold read {field['field_id']}: "
            f"{evidence['original']!r}->{evidence['mutated']!r}->{actual!r}"
        )


def collect_one(items: list[dict[str, object]], index: int) -> None:
    field = items[index]
    driver = launch(f"field {index + 1}/{len(items)}")
    try:
        driver.open_rom(WORK)
        open_editor(driver)
        if index:
            verify_previous(driver, items, index - 1)
        actual_before = read_field(driver, field)
        requested = mutation(driver, field, actual_before)
        before = WORK.read_bytes()
        set_selected(driver, field, requested)
        observed_before_commit = read_selected(driver, field)
        commit_close(driver)
        save_with_retry(driver)
        after = WORK.read_bytes()
        ranges = diff_ranges(before, after)
        append(
            {
                "sequence": index,
                "catalog_field_id": field["field_id"],
                "family": field["family"],
                "group": field.get("group"),
                "row": field["row"],
                "persistent_family_expected": str(field["family"]) in PERSISTENT_FAMILIES,
                "original": actual_before,
                "mutated": requested,
                "observed_before_commit": observed_before_commit,
                "status": "rom_changed_pending_cold" if ranges else "no_rom_effect_pending_cold",
                "before_sha256": sha(before),
                "after_sha256": sha(after),
                "changed_bytes": sum(int(item["end_exclusive"]) - int(item["start"]) for item in ranges),
                "ranges": ranges,
            }
        )
        save_state(index + 1, len(items))
        log(f"saved {index + 1}/{len(items)} field={field['field_id']} changed_bytes={sum(int(item['end_exclusive']) - int(item['start']) for item in ranges)}")
    finally:
        driver.stop()
        # The legacy launcher keeps a single-instance mutex after its last
        # window exits.  A five-second process boundary avoids the next clean
        # runtime being launched into that stale owner and immediately dying.
        time.sleep(5.0)


def collect_batch(items: list[dict[str, object]], start: int, stop: int) -> None:
    driver = launch(f"batch {start + 1}-{stop}/{len(items)}")
    try:
        driver.open_rom(WORK)
        open_editor(driver)
        for index in range(start, stop):
            field = items[index]
            actual_before = read_field(driver, field)
            requested = mutation(driver, field, actual_before)
            before = WORK.read_bytes()
            set_selected(driver, field, requested)
            observed_before_commit = read_selected(driver, field)
            committed_by_close = str(field["family"]) in COMMIT_CLOSE_FAMILIES
            if committed_by_close:
                commit_close(driver)
            save_with_retry(driver)
            after = WORK.read_bytes()
            ranges = diff_ranges(before, after)
            append(
                {
                    "sequence": index,
                    "catalog_field_id": field["field_id"],
                    "family": field["family"],
                    "group": field.get("group"),
                    "row": field["row"],
                    "persistent_family_expected": str(field["family"]) in PERSISTENT_FAMILIES,
                    "original": actual_before,
                    "mutated": requested,
                    "observed_before_commit": observed_before_commit,
                    "commit_mode": "confirm_close" if committed_by_close else "live_control",
                    "status": "saved" if ranges else "no_rom_effect",
                    "before_sha256": sha(before),
                    "after_sha256": sha(after),
                    "changed_bytes": sum(int(item["end_exclusive"]) - int(item["start"]) for item in ranges),
                    "ranges": ranges,
                }
            )
            save_state(index + 1, len(items))
            if (index + 1) % 10 == 0 or index + 1 == stop:
                log(f"saved {index + 1}/{len(items)} field={field['field_id']} status={'saved' if ranges else 'no_rom_effect'}")
            if committed_by_close and index + 1 < stop:
                time.sleep(0.2)
                driver.current_window = driver._main()
                open_editor(driver)
    finally:
        driver.stop()
        # Give the legacy single-instance mutex time to leave the previous
        # process before the next clean runtime starts.
        time.sleep(5.0)


def collect(items: list[dict[str, object]], start: int, stop: int) -> None:
    cursor, failures = start, 0
    while cursor < stop:
        commit_close = str(items[cursor]["family"]) in COMMIT_CLOSE_FAMILIES
        # Some high-row story records leave the legacy editor unable to reopen
        # after the confirm button closes it.  A fresh process per confirm-close
        # field preserves the same save semantics and avoids a watchdog-sized
        # hang between otherwise valid evidence rows.
        batch_limit = 1 if commit_close else 250
        batch_stop = cursor
        while batch_stop < stop and batch_stop < cursor + batch_limit:
            same_mode = (
                str(items[batch_stop]["family"]) in COMMIT_CLOSE_FAMILIES
            ) == commit_close
            if not same_mode:
                break
            batch_stop += 1
        try:
            collect_batch(items, cursor, batch_stop)
            cursor, failures = batch_stop, 0
        except Exception as error:
            failures += 1
            log(f"collector retry={failures} cursor={cursor} error={type(error).__name__}: {error}")
            current = entries()
            rebuild_work(current)
            cursor = len(current)
            save_state(cursor, len(items))
            if failures >= 3:
                raise


def verify_final_field(items: list[dict[str, object]]) -> None:
    evidence = entries()
    cold = cold_entries()
    if not evidence or len(cold) == len(evidence):
        return
    if len(cold) != len(evidence) - 1:
        raise RuntimeError("M14 final cold evidence is not contiguous")
    driver = launch("final-field-cold")
    try:
        driver.open_rom(WORK)
        open_editor(driver)
        verify_previous(driver, items, len(evidence) - 1)
    finally:
        driver.stop()
        time.sleep(1.0)


def inventory(items: list[dict[str, object]], label: str) -> dict[str, object]:
    driver = launch(label)
    values: dict[str, object] = {}
    try:
        driver.open_rom(WORK)
        open_editor(driver)
        current_family = None
        for index, field in enumerate(items):
            family = str(field["family"])
            select_page = family != current_family
            values[str(field["field_id"])] = read_field(driver, field, select_page=select_page)
            current_family = family
            if (index + 1) % 100 == 0:
                log(f"{label} inventory {index + 1}/{len(items)}")
    finally:
        driver.stop()
        time.sleep(1.0)
    return values


def cold_verify(items: list[dict[str, object]]) -> None:
    warm = inventory(items, "same-process-final")
    WARM_VALUES.write_text(json.dumps(warm, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    cold = inventory(items, "cold-process-final")
    COLD_VALUES.write_text(json.dumps(cold, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    failures = [
        {"field_id": key, "same_process": value, "cold_process": cold.get(key)}
        for key, value in warm.items()
        if cold.get(key) != value
    ]
    if failures:
        raise RuntimeError(f"M14 cold inventory differs for {len(failures)} fields: {failures[:5]}")


def write_summary(items: list[dict[str, object]]) -> None:
    evidence = entries()
    statuses = Counter(str(item["status"]) for item in evidence)
    families = Counter(str(item["family"]) for item in evidence)
    complete = len(evidence) == len(items) and WARM_VALUES.is_file() and COLD_VALUES.is_file()
    chain_valid = all(
        evidence[index]["after_sha256"] == evidence[index + 1]["before_sha256"]
        for index in range(len(evidence) - 1)
    )
    report = {
        "passed": complete and chain_valid,
        "logical_fields": len(items),
        "completed": len(evidence),
        "cold_verified": len(items) if complete else 0,
        "statuses": dict(sorted(statuses.items())),
        "family_probe_counts": dict(sorted(families.items())),
        "source_sha256": sha(SOURCE.read_bytes()),
        "normalized_baseline_sha256": sha(NORMALIZED.read_bytes()),
        "final_sha256": sha(WORK.read_bytes()),
        "chain_valid": chain_valid,
        "cold_process_logical_readback_passed": len(items) if complete else 0,
        "evidence": EVIDENCE.relative_to(ROOT).as_posix(),
        "normalization": NORMALIZATION.relative_to(ROOT).as_posix(),
        "final_rom": FINAL.relative_to(ROOT).as_posix() if complete else None,
    }
    SUMMARY.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--restart", action="store_true")
    parser.add_argument("--limit", type=int)
    args = parser.parse_args()
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "error.log").unlink(missing_ok=True)
    items = fields()
    if args.restart:
        prepare_runtime()
        for path in (EVIDENCE, COLD_CHAIN, STATE, SUMMARY, FINAL, WARM_VALUES, COLD_VALUES, NORMALIZATION, OUT / "error.log"):
            path.unlink(missing_ok=True)
        PROGRESS.write_text("", encoding="utf-8")
        normalize()
        save_state(0, len(items))
    evidence = entries()
    if not NORMALIZED.is_file() or not WORK.is_file():
        raise RuntimeError("use --restart to create the normalized M14 baseline")
    if evidence:
        if evidence[-1]["after_sha256"] != sha(WORK.read_bytes()):
            raise RuntimeError("M14 work ROM does not match evidence tail")
    elif sha(WORK.read_bytes()) != sha(NORMALIZED.read_bytes()):
        raise RuntimeError("M14 empty evidence does not match normalized baseline")
    start = len(evidence)
    stop = len(items) if args.limit is None else min(len(items), start + args.limit)
    collect(items, start, stop)
    if len(entries()) == len(items):
        cold_verify(items)
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
