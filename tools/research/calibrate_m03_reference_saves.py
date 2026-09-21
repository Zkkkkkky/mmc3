"""Calibrate M03 UI-to-byte mappings on isolated reference-editor saves."""

from __future__ import annotations

import hashlib
import json
import shutil
import sys
import time
import traceback
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SRC = ROOT / "src"
for path in (ROOT, SRC):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from fc_editor.codecs.map import MapCodec
from fc_editor.rom_image import RomImage
from tools.golden_pipeline_collect import Win32LegacyDriver
from tools.research import reference_map_editor as ref


AUDIT = ROOT / "output/build/legacy-diff-audit"
SOURCE = AUDIT / "audit.nes"
CATALOG = ROOT / "output/reports/m03-reference-field-catalog.json"
OUT = ROOT / "output/verification/legacy-m03-save-calibration-20260920"


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def ranges(before: bytes, after: bytes) -> list[dict[str, object]]:
    changed = [index for index, values in enumerate(zip(before, after)) if values[0] != values[1]]
    return [{"offset": index, "before": before[index], "after": after[index]} for index in changed]


def runtime() -> Path:
    target = OUT / "reference-runtime"
    if target.exists():
        shutil.rmtree(target)
    target.mkdir(parents=True)
    shutil.copy2(AUDIT / "SRW2_patched.exe", target / "SRW2_patched.exe")
    shutil.copytree(AUDIT / "默认配置文件/默认配置文件", target / "默认配置文件")
    return target


def open_record(driver: Win32LegacyDriver, item: dict[str, object], dimensions: dict[int, tuple[int, int]]) -> None:
    map_id = int(item["map_id"])
    width, height = dimensions[map_id]
    ref.select_main_page(driver, 1)
    ref.select_map(driver, map_id)
    ref.context_command(driver, int(item["x"]), int(item["y"]), width, height, 2)
    ref.wait_dialog(driver, "配置设置")


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    work_dir = runtime()
    catalog = json.loads(CATALOG.read_text(encoding="utf-8"))
    fields = {item["field_id"]: item for item in catalog["fields"]}
    rom = RomImage.load(SOURCE)
    maps = MapCodec(rom)
    dimensions = {index: (maps.decode(index).width, maps.decode(index).height) for index in range(32)}
    records: dict[str, dict[str, object]] = {}
    for record in catalog["records"]:
        record_fields = [item for item in catalog["fields"] if item["field_id"].startswith(record["record_id"] + "/")]
        records[record["record_id"]] = {
            **record,
            "x": next(item["original"] for item in record_fields if item["field"] == "x"),
            "y": next(item["original"] for item in record_fields if item["field"] == "y"),
        }

    normalized = OUT / "normalized-baseline.nes"
    shutil.copy2(SOURCE, normalized)
    driver = Win32LegacyDriver()
    results: list[dict[str, object]] = []
    try:
        driver.launch(work_dir / "SRW2_patched.exe", work_dir)
        driver.open_rom(normalized)
        ref.save(driver)
        normalized_bytes = normalized.read_bytes()
        samples = [
            "M03/00/player/00/x",
            "M03/00/player/00/y",
            "M03/00/player/00/roster_index",
            "M03/00/player/00/flags",
            "M03/00/enemy/01/pilot_id",
            "M03/00/enemy/01/unit_id",
            "M03/00/enemy/01/level",
            "M03/00/enemy/01/flags",
            "M03/22/guest/00/pilot_id",
            "M03/22/guest/00/unit_id",
            "M03/22/guest/00/level",
            "M03/22/guest/00/flags",
        ]
        combo_ids = {"pilot_id": 140, "unit_id": 160, "level": 180, "flags": 200, "roster_index": 220}
        occupied = {(int(item["x"]), int(item["y"])) for item in records.values() if int(item["map_id"]) == 0}
        for sequence, field_id in enumerate(samples):
            field = fields[field_id]
            record_id = field_id.rsplit("/", 1)[0]
            record = records[record_id]
            case = OUT / f"case-{sequence:02d}.nes"
            shutil.copy2(normalized, case)
            driver.open_rom(case)
            before = case.read_bytes()
            name = str(field["field"])
            observed: int
            requested: int
            if name in {"x", "y"}:
                source = (int(record["x"]), int(record["y"]))
                if name == "x":
                    candidates = ((x, source[1]) for x in range(dimensions[0][0]))
                else:
                    candidates = ((source[0], y) for y in range(dimensions[0][1]))
                target = next(point for point in candidates if point != source and point not in occupied)
                observed = source[0 if name == "x" else 1]
                requested = target[0 if name == "x" else 1]
                ref.select_main_page(driver, 1)
                ref.select_map(driver, 0)
                ref.drag_cell(driver, source, target, *dimensions[0])
            else:
                open_record(driver, record, dimensions)
                control_id = combo_ids[name]
                observed = ref.combo_index(driver, control_id)
                count = len(ref.combo(driver, control_id).item_texts())
                requested = (observed + 1) % count
                ref.set_combo(driver, control_id, requested)
                ref.click_button(driver, 240)
                driver.current_window = driver._main()
            ref.save(driver)
            after = case.read_bytes()
            diff = ranges(before, after)
            expected_rom_effect = not (str(field["family"]) == "player" and name == "flags")
            changed_offsets = [item["offset"] for item in diff]
            results.append(
                {
                    "sequence": sequence,
                    "field_id": field_id,
                    "field": name,
                    "file_offset": field["file_offset"],
                    "catalog_original": field["original"],
                    "ui_observed": observed,
                    "ui_requested": requested,
                    "before_sha256": sha(before),
                    "after_sha256": sha(after),
                    "changed_offsets": changed_offsets,
                    "target_after": after[int(field["file_offset"])],
                    "target_changed": int(field["file_offset"]) in {item["offset"] for item in diff},
                    "expected_rom_effect": expected_rom_effect,
                    "mapping_passed": (
                        changed_offsets == [int(field["file_offset"])]
                        if expected_rom_effect
                        else changed_offsets == []
                    ),
                    "diff": diff,
                }
            )
            case.unlink()
    finally:
        driver.stop()
        time.sleep(1.0)

    report = {
        "schema_version": 1,
        "module": "M03",
        "normalized_sha256": sha(normalized.read_bytes()),
        "samples": results,
        "passed": len(results) == 12 and all(item["mapping_passed"] for item in results),
    }
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
