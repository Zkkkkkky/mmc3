"""Calibrate M04 delete-and-readd field saves on isolated ROM copies."""

from __future__ import annotations

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
CATALOG = ROOT / "output/reports/m04-reference-field-catalog.json"
OUT = ROOT / "output/verification/legacy-m04-save-calibration-20260920"


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def prepare_runtime() -> Path:
    runtime = OUT / "reference-runtime"
    if runtime.exists():
        shutil.rmtree(runtime)
    runtime.mkdir(parents=True)
    shutil.copy2(AUDIT / "SRW2_patched.exe", runtime / "SRW2_patched.exe")
    shutil.copytree(AUDIT / "默认配置文件/默认配置文件", runtime / "默认配置文件")
    return runtime


def character_ui(raw: int) -> int:
    return 0 if raw == 0xFF else raw


def add_record(driver: Win32LegacyDriver, values: dict[str, int]) -> None:
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


def replace(driver: Win32LegacyDriver, map_id: int, original: dict[str, int], changed: dict[str, int]) -> None:
    last_error: Exception | None = None
    for _attempt in range(3):
        ref.select_main_page(driver, 2)
        ref.select_map(driver, map_id)
        try:
            ref.context_command(driver, original["x"], original["y"], 23, 21, 2)
            break
        except RuntimeError as error:
            last_error = error
            time.sleep(0.4)
    else:
        raise last_error or RuntimeError("M04 record context menu did not open")
    time.sleep(0.25)
    add_record(driver, changed)


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    payload = json.loads(CATALOG.read_text(encoding="utf-8"))
    fields = {str(item["field_id"]): item for item in payload["fields"]}
    records = {str(item["record_id"]): item for item in payload["records"]}
    samples = [
        "M04/00/trigger/00/x",
        "M04/00/trigger/00/y",
        "M04/00/trigger/00/character_id",
        "M04/00/trigger/00/event_id",
        "M04/01/trigger/03/character_id",
        "M04/01/trigger/03/event_id",
    ]
    runtime = prepare_runtime()
    normalized = OUT / "normalized-baseline.nes"
    shutil.copy2(SOURCE, normalized)
    driver = Win32LegacyDriver()
    results: list[dict[str, object]] = []
    try:
        driver.launch(runtime / "SRW2_patched.exe", runtime)
        driver.open_rom(normalized)
        ref.save(driver)
        for sequence, field_id in enumerate(samples):
            field = fields[field_id]
            record = records[field_id.rsplit("/", 1)[0]]
            raw = bytes.fromhex(str(record["raw_hex"]))
            values = dict(zip(("x", "y", "character_id", "event_id"), raw, strict=True))
            changed = dict(values)
            name = str(field["field"])
            if name == "x":
                changed[name] = 0 if values[name] != 0 else 1
            elif name == "y":
                changed[name] = 0 if values[name] != 0 else 1
            elif name == "character_id":
                changed[name] = 5 if values[name] == 0xFF else values[name] + 1
            elif values[name] >= 0xF0:
                changed[name] = 0xF0 + ((values[name] - 0xF0 + 1) % 5)
            else:
                changed[name] = (values[name] + 1) % 0xF0
            case = OUT / f"case-{sequence:02d}.nes"
            shutil.copy2(normalized, case)
            driver.open_rom(case)
            before = case.read_bytes()
            replace(driver, int(field["map_id"]), values, changed)
            ref.save(driver)
            after = case.read_bytes()
            changed_offsets = [index for index, pair in enumerate(zip(before, after)) if pair[0] != pair[1]]
            offset = int(field["file_offset"])
            forced_unlimited = name == "character_id" and values["event_id"] < 0xF0
            results.append(
                {
                    "sequence": sequence,
                    "field_id": field_id,
                    "field": name,
                    "file_offset": offset,
                    "original": values[name],
                    "requested": changed[name],
                    "changed_offsets": changed_offsets,
                    "target_after": after[offset],
                    "before_sha256": sha(before),
                    "after_sha256": sha(after),
                    "expected_rom_effect": not forced_unlimited,
                    "mapping_passed": (
                        changed_offsets == [] and after[offset] == 0xFF
                        if forced_unlimited
                        else changed_offsets == [offset] and after[offset] == changed[name]
                    ),
                }
            )
            case.unlink()
    finally:
        driver.stop()
        time.sleep(5.0)
    report = {"schema_version": 1, "module": "M04", "samples": results, "passed": len(results) == len(samples) and all(item["mapping_passed"] for item in results)}
    (OUT / "calibration.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    (OUT / "error.log").unlink(missing_ok=True)
    print(json.dumps(report, ensure_ascii=False))
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception:
        OUT.mkdir(parents=True, exist_ok=True)
        (OUT / "error.log").write_text(traceback.format_exc(), encoding="utf-8")
        raise
