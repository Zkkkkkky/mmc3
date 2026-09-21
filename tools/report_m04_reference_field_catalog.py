"""Build the exhaustive M04 map-trigger field catalog from the reference ROM."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "output/build/legacy-diff-audit/audit.nes"
JSON_OUT = ROOT / "output/reports/m04-reference-field-catalog.json"
MD_OUT = ROOT / "output/reports/m04-reference-field-catalog.md"
CONTROL_CATALOG = ROOT / "output/verification/legacy-m04-reference-controls-20260920/catalog.json"
EXISTING_RECORD_CATALOG = ROOT / "output/verification/legacy-m03-m04-existing-records-20260920/catalog.json"
PRG_BANK = 0x0A
WINDOW_BASE = 0x8000
POINTER_TABLE = 0x987E
SCENARIOS = 32


def file_offset(address: int) -> int:
    return 16 + PRG_BANK * 0x2000 + address - WINDOW_BASE


def build() -> dict[str, object]:
    source = SOURCE.read_bytes()
    table = file_offset(POINTER_TABLE)
    pointers = [int.from_bytes(source[table + index * 2 : table + index * 2 + 2], "little") for index in range(SCENARIOS)]
    fields: list[dict[str, object]] = []
    records: list[dict[str, object]] = []
    names = ("x", "y", "character_id", "event_id")
    for map_id, pointer in enumerate(pointers):
        cursor = file_offset(pointer)
        row = 0
        while source[cursor] != 0xFF:
            record_id = f"M04/{map_id:02d}/trigger/{row:02d}"
            raw = source[cursor : cursor + 4]
            in_reference_viewport = raw[0] < 23 and raw[1] < 21
            record_kind = "shop" if raw[3] >= 0xF0 else "event"
            records.append(
                {
                    "record_id": record_id,
                    "map_id": map_id,
                    "row": row,
                    "pointer": pointer,
                    "offset": cursor,
                    "raw_hex": raw.hex().upper(),
                    "kind": record_kind,
                }
            )
            for index, (name, value) in enumerate(zip(names, raw, strict=True)):
                fields.append(
                    {
                        "field_id": f"{record_id}/{name}",
                        "map_id": map_id,
                        "row": row,
                        "field": name,
                        "file_offset": cursor + index,
                        "original": value,
                        "classification": (
                            "reference_off_viewport_no_editor"
                            if not in_reference_viewport
                            else (
                                "reference_forced_unlimited_no_effect"
                                if name == "character_id" and record_kind == "event"
                                else "persistent_candidate"
                            )
                        ),
                    }
                )
            cursor += 4
            row += 1
    controls = json.loads(CONTROL_CATALOG.read_text(encoding="utf-8")) if CONTROL_CATALOG.is_file() else {}
    existing = json.loads(EXISTING_RECORD_CATALOG.read_text(encoding="utf-8")) if EXISTING_RECORD_CATALOG.is_file() else {}
    control_ids = {int(item["control_id"]) for item in controls.get("visible_controls", [])}
    checks = {
        "scenario_count_is_32": len(pointers) == 32,
        "record_count_is_44": len(records) == 44,
        "physical_field_count_is_176": len(fields) == 176,
        "persistent_candidate_count_is_103": sum(item["classification"] == "persistent_candidate" for item in fields) == 103,
        "forced_unlimited_count_is_29": sum(item["classification"] == "reference_forced_unlimited_no_effect" for item in fields) == 29,
        "off_viewport_field_count_is_44": sum(item["classification"] == "reference_off_viewport_no_editor" for item in fields) == 44,
        "field_ids_unique": len({item["field_id"] for item in fields}) == len(fields),
        "record_offsets_unique": len({item["offset"] for item in records}) == len(records),
        "all_pointers_readable": all(0x9946 <= pointer < 0xA000 for pointer in pointers),
        "reference_editor_controls_enumerated": bool(controls.get("passed")),
        "reference_editor_rom_unchanged": bool(controls.get("rom_unchanged")),
        "reference_editor_core_controls_present": {100, 130, 140, 150, 170, 180, 190} <= control_ids,
        "existing_record_path_enumerated": bool(existing.get("m04", {}).get("passed")),
        "existing_record_requires_delete_and_readd": existing.get("m04", {}).get("reference_update_mode") == "delete_and_readd",
        "existing_record_probe_rom_unchanged": bool(existing.get("m04", {}).get("rom_unchanged")),
    }
    return {
        "schema_version": 1,
        "module": "M04",
        "passed": all(checks.values()),
        "status": "physical_fields_cataloged_save_evidence_pending",
        "source": SOURCE.relative_to(ROOT).as_posix(),
        "source_sha256": hashlib.sha256(source).hexdigest(),
        "counts": {
            "maps": 32,
            "nonempty_maps": len({item["map_id"] for item in records}),
            "records": len(records),
            "physical_fields": len(fields),
            "persistent_candidate_fields": sum(item["classification"] == "persistent_candidate" for item in fields),
            "reference_off_viewport_fields": sum(item["classification"] == "reference_off_viewport_no_editor" for item in fields),
            "reference_forced_unlimited_fields": sum(item["classification"] == "reference_forced_unlimited_no_effect" for item in fields),
        },
        "checks": checks,
        "records": records,
        "fields": fields,
        "ui_alias_note": "shop/event radio and selection controls jointly encode event_id; x/y are selected through the owner-drawn map.",
        "reference_editor_controls": controls,
        "control_evidence": CONTROL_CATALOG.relative_to(ROOT).as_posix(),
        "existing_record_evidence": EXISTING_RECORD_CATALOG.relative_to(ROOT).as_posix(),
    }


def markdown(report: dict[str, object]) -> str:
    counts = report["counts"]
    return "\n".join(
        [
            "# M04 参考版字段目录",
            "",
            f"- 地图/非空地图：{counts['maps']} / {counts['nonempty_maps']}",
            f"- 触发记录：{counts['records']}",
            f"- 物理字段：{counts['physical_fields']}（可保存候选 {counts['persistent_candidate_fields']}；事件类限定人物强制 FF {counts['reference_forced_unlimited_fields']}；固定视口外无编辑入口 {counts['reference_off_viewport_fields']}）",
            f"- 参考版“商店设置”可见控件：{report['reference_editor_controls'].get('visible_control_count', 0)}",
            f"- 状态：`{report['status']}`",
            "",
            "商店/事件单选与选择框共同编码 event_id；x/y 由自绘地图坐标提供。完整物理字段目录见同名 JSON，保存证据完成前不进入安全分母。",
            "",
        ]
    )


def main() -> int:
    report = build()
    JSON_OUT.parent.mkdir(parents=True, exist_ok=True)
    JSON_OUT.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    MD_OUT.write_text(markdown(report), encoding="utf-8")
    print(json.dumps({"passed": report["passed"], **report["counts"]}, ensure_ascii=False))
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
