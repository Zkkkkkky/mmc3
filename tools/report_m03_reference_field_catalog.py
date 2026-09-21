"""Build the exhaustive M03 physical-field catalog from the reference ROM."""

from __future__ import annotations

import hashlib
import json
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from fc_editor.codecs.scenario_layout import ScenarioLayoutCodec
from fc_editor.rom_image import RomImage


SOURCE = ROOT / "output/build/legacy-diff-audit/audit.nes"
JSON_OUT = ROOT / "output/reports/m03-reference-field-catalog.json"
MD_OUT = ROOT / "output/reports/m03-reference-field-catalog.md"
CONTROL_CATALOG = ROOT / "output/verification/legacy-m03-reference-controls-20260920/catalog.json"
EXISTING_RECORD_CATALOG = ROOT / "output/verification/legacy-m03-m04-existing-records-20260920/catalog.json"


def build() -> dict[str, object]:
    rom = RomImage.load(SOURCE)
    codec = ScenarioLayoutCodec(rom)
    fields: list[dict[str, object]] = []
    records: list[dict[str, object]] = []
    route_fields: list[dict[str, object]] = []
    type_actions: list[dict[str, object]] = []
    specs = (
        ("enemy", "enemies", ("x", "y", "pilot_id", "unit_id", "level", "flags")),
        ("guest", "guests", ("x", "y", "pilot_id", "unit_id", "level", "flags")),
        ("player", "player_placements", ("x", "y", "roster_index", "flags")),
    )
    for map_id in range(rom.profile.scenario_count):
        layout = codec.decode(map_id)
        cursor = codec.record_offset(map_id) + len(layout.prelude) + 1
        for family, attribute, names in specs:
            entries = getattr(layout, attribute)
            for row, entry in enumerate(entries):
                record_id = f"M03/{map_id:02d}/{family}/{row:02d}"
                values = entry.to_bytes()
                records.append(
                    {
                        "record_id": record_id,
                        "map_id": map_id,
                        "family": family,
                        "row": row,
                        "offset": cursor,
                        "size": len(names),
                    }
                )
                type_actions.append(
                    {
                        "field_id": f"{record_id}/type",
                        "classification": "structural_move_action_guarded",
                        "reason": "changing side moves a record between variable-length lists",
                    }
                )
                in_reference_viewport = entry.x < 23 and entry.y < 21
                for index, (name, value) in enumerate(zip(names, values, strict=True)):
                    classification = (
                        "reference_off_viewport_no_editor"
                        if not in_reference_viewport
                        else (
                            "reference_no_rom_effect"
                            if family == "player" and name == "flags"
                            else "persistent_candidate"
                        )
                    )
                    fields.append(
                        {
                            "field_id": f"{record_id}/{name}",
                            "map_id": map_id,
                            "family": family,
                            "row": row,
                            "field": name,
                            "file_offset": cursor + index,
                            "original": value,
                            "classification": classification,
                        }
                    )
                cursor += len(names)
            cursor += 1
        for slot, control_id in enumerate((140, 160, 180), start=1):
            route_fields.append(
                {
                    "field_id": f"M03/{map_id:02d}/icon_route/{slot}",
                    "map_id": map_id,
                    "slot": slot,
                    "control_id": control_id,
                    "classification": "runtime_selector_save_probe_pending",
                }
            )
    counts = Counter(str(item["family"]) for item in records)
    controls = json.loads(CONTROL_CATALOG.read_text(encoding="utf-8")) if CONTROL_CATALOG.is_file() else {}
    existing = json.loads(EXISTING_RECORD_CATALOG.read_text(encoding="utf-8")) if EXISTING_RECORD_CATALOG.is_file() else {}
    control_ids = {int(item["control_id"]) for item in controls.get("visible_controls", [])}
    checks = {
        "scenario_count_is_32": rom.profile.scenario_count == 32,
        "record_count_is_386": len(records) == 386,
        "physical_field_count_is_2134": len(fields) == 2134,
        "persistent_candidate_count_is_1380": sum(item["classification"] == "persistent_candidate" for item in fields) == 1380,
        "player_flags_no_rom_effect_count_is_52": sum(item["classification"] == "reference_no_rom_effect" for item in fields) == 52,
        "off_viewport_field_count_is_702": sum(item["classification"] == "reference_off_viewport_no_editor" for item in fields) == 702,
        "field_ids_unique": len({item["field_id"] for item in fields}) == len(fields),
        "physical_offsets_unique": len({item["file_offset"] for item in fields}) == len(fields),
        "route_selector_views_complete": len(route_fields) == 96,
        "structural_type_actions_guarded": len(type_actions) == len(records),
        "reference_editor_controls_enumerated": bool(controls.get("passed")),
        "reference_editor_rom_unchanged": bool(controls.get("rom_unchanged")),
        "reference_editor_core_controls_present": {100, 120, 140, 160, 180, 200, 220, 240, 250} <= control_ids,
        "existing_record_editor_opened": bool(existing.get("m03", {}).get("passed")),
        "existing_record_probe_rom_unchanged": bool(existing.get("m03", {}).get("rom_unchanged")),
    }
    return {
        "schema_version": 1,
        "module": "M03",
        "passed": all(checks.values()),
        "status": "physical_fields_cataloged_save_evidence_pending",
        "source": SOURCE.relative_to(ROOT).as_posix(),
        "source_sha256": hashlib.sha256(SOURCE.read_bytes()).hexdigest(),
        "counts": {
            "maps": 32,
            "records": len(records),
            "records_by_family": dict(counts),
            "physical_fields": len(fields),
            "persistent_candidate_fields": sum(item["classification"] == "persistent_candidate" for item in fields),
            "reference_no_rom_effect_fields": sum(item["classification"] == "reference_no_rom_effect" for item in fields),
            "reference_off_viewport_fields": sum(item["classification"] == "reference_off_viewport_no_editor" for item in fields),
            "runtime_route_selector_views": len(route_fields),
            "guarded_structural_type_actions": len(type_actions),
            "logical_ui_entries": len(fields) + len(route_fields) + len(type_actions),
        },
        "checks": checks,
        "records": records,
        "fields": fields,
        "runtime_route_selectors": route_fields,
        "guarded_type_actions": type_actions,
        "reference_editor_controls": controls,
        "control_evidence": CONTROL_CATALOG.relative_to(ROOT).as_posix(),
        "existing_record_evidence": EXISTING_RECORD_CATALOG.relative_to(ROOT).as_posix(),
    }


def markdown(report: dict[str, object]) -> str:
    counts = report["counts"]
    return "\n".join(
        [
            "# M03 参考版字段目录",
            "",
            f"- 地图/部署记录：{counts['maps']} / {counts['records']}",
            f"- 物理字段：{counts['physical_fields']}（可保存候选 {counts['persistent_candidate_fields']}；参考版无 ROM 效果 {counts['reference_no_rom_effect_fields']}；固定视口外无编辑入口 {counts['reference_off_viewport_fields']}）",
            f"- 图标路由视图：{counts['runtime_route_selector_views']}",
            f"- 保持门禁的阵营迁移动作：{counts['guarded_structural_type_actions']}",
            f"- 参考版“配置设置”可见控件：{report['reference_editor_controls'].get('visible_control_count', 0)}",
            f"- 状态：`{report['status']}`",
            "",
            "完整字段、偏移、原值和记录身份见同名 JSON；动态参考版保存证据完成前不进入安全分母。",
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
