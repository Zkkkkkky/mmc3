"""Check whether reference M08 edits can be saved and reverted byte-exactly."""

from __future__ import annotations

import hashlib
import json
import shutil
import sys
import traceback
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools.golden_pipeline_collect import Win32LegacyDriver


AUDIT = ROOT / "output/build/legacy-diff-audit"
OUT = ROOT / "output/verification/legacy-ui-probe-m08-reversible-20260920"


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def diffs(before: bytes, after: bytes) -> list[int]:
    return [index for index, pair in enumerate(zip(before, after)) if pair[0] != pair[1]]


def progress(message: str) -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    with (OUT / "progress.log").open("a", encoding="utf-8") as stream:
        stream.write(message + "\n")


def navigate(driver: Win32LegacyDriver, segment_index: int, row: int, variant: int) -> None:
    driver.perform(
        (
            {"op": "select_index_message", "class": "ComboBox", "control_id": 1410, "value": segment_index},
            {"op": "list_select", "class": "ListBox", "control_id": 1390, "row": row},
            {"op": "list_select", "class": "ListBox", "control_id": 2580, "row": variant},
        ),
        0,
    )


def set_text(driver: Win32LegacyDriver, value: str) -> None:
    driver.perform(
        (
            {"op": "set_text_notify", "class": "Edit", "control_id": 1370, "value": value},
            {"op": "click_id", "class": "Button", "control_id": 590},
        ),
        value,
    )


def open_database(driver: Win32LegacyDriver) -> None:
    driver.perform(
        (
            {"op": "menu", "path": "数据->数据库"},
            {"op": "window", "title": "数据库"},
            {"op": "click_coords", "x": 310, "y": 73},
        ),
        0,
    )


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "progress.log").write_text("start\n", encoding="utf-8")
    baseline_path = AUDIT / "m05-reference-baseline.nes"
    work_path = OUT / "reversible-work.nes"
    shutil.copy2(baseline_path, work_path)
    baseline = work_path.read_bytes()
    checks = (
        ("00", 0, 0, 0, "这一击是决定性的！", "这一击是决定性的？"),
        ("04", 2, 0, 1, "你们该死！", "你们该退！"),
    )
    report: dict[str, object] = {"baseline_sha256": sha(baseline), "checks": []}
    driver = Win32LegacyDriver()
    try:
        report["pid"] = driver.launch(AUDIT / "SRW2_patched.exe", AUDIT)
        progress(f"launched pid={report['pid']}")
        driver.open_rom(work_path)
        progress("opened ROM")
        open_database(driver)
        progress("opened database")
        for segment, segment_index, row, variant, original, changed in checks:
            progress(f"{segment}: navigate edit")
            navigate(driver, segment_index, row, variant)
            set_text(driver, changed)
            progress(f"{segment}: save edit")
            driver.save()
            edited = work_path.read_bytes()
            progress(f"{segment}: reopen database")
            open_database(driver)
            navigate(driver, segment_index, row, variant)
            set_text(driver, original)
            progress(f"{segment}: save restore")
            driver.save()
            restored = work_path.read_bytes()
            report["checks"].append(
                {
                    "segment": segment,
                    "row": row,
                    "variant": variant,
                    "original": original,
                    "changed": changed,
                    "edited_sha256": sha(edited),
                    "edited_changed_offsets": diffs(baseline, edited),
                    "restored_sha256": sha(restored),
                    "restored_exactly": restored == baseline,
                    "restored_changed_offsets": diffs(baseline, restored),
                }
            )
            if (segment, segment_index, row, variant, original, changed) != checks[-1]:
                open_database(driver)
                progress(f"{segment}: opened database for next check")
        report["all_restored_exactly"] = all(
            item["restored_exactly"] for item in report["checks"]
        )
        (OUT / "report.json").write_text(
            json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
        print(json.dumps(report, ensure_ascii=False))
        progress("complete")
        return 0 if report["all_restored_exactly"] else 2
    finally:
        progress("stopping")
        driver.stop()


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except BaseException:
        OUT.mkdir(parents=True, exist_ok=True)
        (OUT / "error.log").write_text(traceback.format_exc(), encoding="utf-8")
        raise
