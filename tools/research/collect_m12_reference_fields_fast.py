"""Collect M12 per-field save diffs as one resumable cumulative chain."""

from __future__ import annotations

import argparse
import json
import shutil
import sys
import traceback
from collections import Counter
from pathlib import Path

ROOT_HINT = Path(__file__).resolve().parents[2]
if str(ROOT_HINT) not in sys.path:
    sys.path.insert(0, str(ROOT_HINT))

from tools.research import collect_m12_reference_fields as base
from tools.golden_pipeline_collect import Win32LegacyDriver


ROOT = base.ROOT
OUT = base.OUT
WORK = base.WORK
EVIDENCE = base.EVIDENCE
STATE = base.STATE
SUMMARY = base.SUMMARY
PROGRESS = base.PROGRESS
FINAL = OUT / "after-all-fields.nes"
COLD = OUT / "cold-process-final-values.json"


def prepare_runtime() -> None:
    if base.RUNTIME.exists():
        shutil.rmtree(base.RUNTIME)
    base.RUNTIME.mkdir(parents=True)
    shutil.copy2(base.AUDIT / "SRW2_patched.exe", base.RUNTIME / "SRW2_patched.exe")
    shutil.copytree(
        base.AUDIT / "默认配置文件" / "默认配置文件",
        base.RUNTIME / "默认配置文件",
    )


def append(payload: dict[str, object]) -> None:
    with EVIDENCE.open("a", encoding="utf-8") as stream:
        stream.write(json.dumps(payload, ensure_ascii=False, separators=(",", ":")) + "\n")


def entries() -> list[dict[str, object]]:
    if not EVIDENCE.exists():
        return []
    return [json.loads(line) for line in EVIDENCE.read_text(encoding="utf-8").splitlines() if line.strip()]


def launch(label: str, sequence: int) -> Win32LegacyDriver:
    return base.launch_with_retry(label, sequence, "cumulative-chain")


def collect(items: list[dict[str, object]], start: int, stop: int) -> None:
    cursor = start
    while cursor < stop:
        session_stop = min(stop, cursor + 40)
        driver = launch("chain", cursor)
        try:
            driver.open_rom(WORK)
            base.open_animation(driver)
            for index in range(cursor, session_stop):
                field = items[index]
                actual_before = base.read_field(driver, field)
                requested = base.mutation(driver, field, actual_before)
                before = WORK.read_bytes()
                base.commit(driver, field, requested)
                base.save_with_retry(driver)
                observed = WORK.read_bytes()
                ranges = base.diff_ranges(before, observed)
                base.open_animation(driver)
                actual_after = base.read_field(driver, field)
                semantic_changed = any(
                    offset not in base.NORMALIZATION_OFFSETS
                    for change in ranges
                    for offset in range(int(change["start"]), int(change["end_exclusive"]))
                )
                if actual_after == requested and semantic_changed:
                    status = "reference_saved_product_blocked"
                elif actual_after == actual_before and not semantic_changed:
                    status = "no_effect"
                elif actual_after == requested:
                    status = "readback_only_or_normalization_only"
                else:
                    status = "unstable"
                if status == "unstable":
                    WORK.write_bytes(before)
                    raise RuntimeError(f"unstable cumulative field {field['field_id']}: {actual_after!r}")
                append(
                    {
                        "sequence": index,
                        "field_id": field["field_id"],
                        "family": field["family"],
                        "row": field["row"],
                        "original": actual_before,
                        "mutated": requested,
                        "same_process_reopen_readback": actual_after,
                        "status": status,
                        "before_sha256": base.sha(before),
                        "after_sha256": base.sha(observed),
                        "changed_bytes": sum(int(item["end_exclusive"]) - int(item["start"]) for item in ranges),
                        "semantic_changed": semantic_changed,
                        "ranges": ranges,
                    }
                )
                base.save_state(index + 1, len(items))
                if (index + 1) % 10 == 0 or index + 1 == session_stop:
                    base.log(f"cumulative probed {index + 1}/{len(items)}")
        finally:
            driver.stop()
        cursor = session_stop


def cold_read(items: list[dict[str, object]], evidence: list[dict[str, object]]) -> None:
    expected = {
        str(item["field_id"]): (
            item["mutated"] if item["status"] != "no_effect" else item["original"]
        )
        for item in evidence
    }
    driver = launch("cold-final", len(items))
    actual: dict[str, object] = {}
    try:
        driver.open_rom(WORK)
        base.open_animation(driver)
        for index, field in enumerate(items):
            actual[str(field["field_id"])] = base.read_field(driver, field)
            if (index + 1) % 50 == 0:
                base.log(f"cold inventory {index + 1}/{len(items)}")
    finally:
        driver.stop()
    failures = [
        {"field_id": key, "expected": value, "actual": actual.get(key)}
        for key, value in expected.items()
        if actual.get(key) != value
    ]
    COLD.write_text(json.dumps(actual, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    if failures:
        raise RuntimeError(f"M12 cold read failed for {len(failures)} fields: {failures[:5]}")


def write_summary(items: list[dict[str, object]]) -> None:
    evidence = entries()
    statuses = Counter(str(item["status"]) for item in evidence)
    families = Counter(str(item["family"]) for item in evidence)
    complete = len(evidence) == len(items) and COLD.is_file()
    SUMMARY.write_text(
        json.dumps(
            {
                "passed": complete,
                "logical_fields": len(items),
                "completed": len(evidence),
                "statuses": dict(sorted(statuses.items())),
                "family_probe_counts": dict(sorted(families.items())),
                "baseline_sha256": base.sha(base.SOURCE.read_bytes()),
                "final_sha256": base.sha(WORK.read_bytes()),
                "chain_valid": all(
                    evidence[index]["after_sha256"] == evidence[index + 1]["before_sha256"]
                    for index in range(len(evidence) - 1)
                ),
                "cold_process_logical_readback_passed": len(items) if complete else 0,
                "evidence": EVIDENCE.relative_to(ROOT).as_posix(),
                "final_rom": FINAL.relative_to(ROOT).as_posix() if complete else None,
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", type=int)
    parser.add_argument("--restart", action="store_true")
    args = parser.parse_args()
    OUT.mkdir(parents=True, exist_ok=True)
    items = base.fields()
    if args.restart:
        prepare_runtime()
        shutil.copy2(base.SOURCE, WORK)
        for path in (EVIDENCE, STATE, SUMMARY, FINAL, COLD, OUT / "error.log"):
            path.unlink(missing_ok=True)
        PROGRESS.write_text("cumulative restart\n", encoding="utf-8")
        baseline = base.SOURCE.read_bytes()
        # The code-editor prompt is a navigation action, not a row field. Its
        # isolated save/cold-read probe proved 0080->0081 has zero ROM effect
        # and reopens as 0080. Seed that already archived result, then keep the
        # cumulative chain focused on actual editable data controls.
        append(
            {
                "sequence": 0,
                "field_id": items[0]["field_id"],
                "family": items[0]["family"],
                "row": items[0]["row"],
                "original": "0080",
                "mutated": "0081",
                "cold_process_readback": "0080",
                "status": "no_effect",
                "before_sha256": base.sha(baseline),
                "after_sha256": base.sha(baseline),
                "changed_bytes": 0,
                "semantic_changed": False,
                "ranges": [],
                "evidence_origin": "isolated_save_and_new_pid_readback",
            }
        )
        base.save_state(1, len(items))
    existing = entries()
    start = len(existing)
    if start and existing[-1]["after_sha256"] != base.sha(WORK.read_bytes()):
        raise RuntimeError("M12 cumulative work ROM does not match evidence tail")
    stop = len(items) if args.limit is None else min(len(items), start + args.limit)
    collect(items, start, stop)
    evidence = entries()
    if len(evidence) == len(items):
        cold_read(items, evidence)
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
