from __future__ import annotations

from datetime import datetime
import argparse
import hashlib
import json
from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from fc_editor.codecs import LegacyGrowthCodec  # noqa: E402
from fc_editor.codecs.legacy_text import LegacyTextCodec  # noqa: E402
from fc_rom_editor_core import RomProject  # noqa: E402
from tools.report_m09_level_cap_compatibility import (  # noqa: E402
    DEFAULT_AUDIT_AFTER,
    DEFAULT_AUDIT_BEFORE,
    analyze as analyze_level_cap,
)


DEFAULT_ROM = ROOT / "output" / "rom" / "DC_kuorong_464K.nes"
DEFAULT_REPORT = ROOT / "output" / "verification" / "m09-other1-compatibility.json"
REFERENCE_ALL_FIELDS = ROOT / "output" / "verification" / "legacy-m09-all-fields-20260920" / "summary.json"


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest().upper()


def _changed_indices(before: bytes, after: bytes) -> list[int]:
    return [
        index
        for index, (left, right) in enumerate(zip(before, after))
        if left != right
    ]


def _rejected(action) -> str:
    try:
        action()
    except ValueError as error:
        return str(error)
    raise AssertionError("预期门禁拒绝操作，但调用成功。")


def analyze(
    rom_path: Path,
    audit_before_path: Path = DEFAULT_AUDIT_BEFORE,
    audit_after_path: Path = DEFAULT_AUDIT_AFTER,
) -> dict[str, object]:
    data = rom_path.read_bytes()
    original_hash = _sha256(data)
    project = RomProject.load(rom_path)
    global_codec = project.legacy_global_data_codec
    if global_codec is None:
        raise ValueError("当前 ROM 未启用已验证的全局数据协议。")

    distance_rows = global_codec.distance_hit_corrections(data)
    changed_distance = [list(row) for row in distance_rows]
    changed_distance[0][15] = (changed_distance[0][15] - 1) & 0xFF
    distance_patch = global_codec.distance_hit_correction_patches(
        data, changed_distance
    )[0]

    experience = global_codec.experience_totals(data)
    changed_experience = list(experience)
    changed_experience[49] += 1
    experience_patch = global_codec.experience_total_patches(
        data, changed_experience
    )[0]

    text_codec = LegacyTextCodec(data)
    system_roundtrips = []
    system_variants = 0
    for index in range(221):
        for variant in range(text_codec.variant_count("system", index)):
            record = text_codec.record("system", index, variant)
            patch = text_codec.replacement_patch(
                "system", index, variant, record.text
            )
            system_roundtrips.append(patch[1] == patch[2])
            system_variants += 1
    system_record = text_codec.record("system", 9)
    system_patch = text_codec.replacement_patch(
        "system", 9, 0, system_record.text.replace("我方", "敌方", 1)
    )

    growth_codec = LegacyGrowthCodec(data)
    growth_records = [
        growth_codec.record(growth_id) for growth_id in range(201, 254)
    ]
    growth_roundtrips = [
        growth_codec.replacement_patch(record.growth_id, record.values)[1:]
        for record in growth_records
    ]
    growth = growth_codec.record(201)
    changed_values = list(growth.values)
    changed_values[0] = 14 if changed_values[0] == 15 else changed_values[0] + 1
    growth_patch = growth_codec.replacement_patch(201, changed_values)

    quick_values = list(growth.values)
    quick_values[:60] = [15] * 60
    quick_patch = growth_codec.replacement_patch(201, quick_values)
    invalid_growth_length = _rejected(
        lambda: growth_codec.replacement_patch(201, growth.values[:-1])
    )
    invalid_growth_value = _rejected(
        lambda: growth_codec.replacement_patch(201, (16,) + growth.values[1:])
    )
    shared_record = growth_codec.record(214)
    reference_all_fields = json.loads(REFERENCE_ALL_FIELDS.read_text(encoding="utf-8"))

    level_cap = analyze_level_cap(
        rom_path, audit_before_path, audit_after_path
    )
    checks = {
        "distance_table_4x16_single_field": (
            len(distance_rows) == 4
            and all(len(row) == 16 for row in distance_rows)
            and _changed_indices(distance_patch[1], distance_patch[2]) == [15]
        ),
        "experience_99_single_field": (
            len(experience) == 99
            and experience[49] == 15200
            and experience[-2:] == (64350, 65535)
            and _changed_indices(experience_patch[1], experience_patch[2])
            == [98]
        ),
        "system_text_all_roundtrip_and_sample_confined": (
            system_variants >= 221
            and all(system_roundtrips)
            and bool(_changed_indices(system_patch[1], system_patch[2]))
            and system_patch[0] == system_record.file_offset
        ),
        "growth_53_slots_and_99_values": (
            len(growth_records) == 53
            and all(len(record.values) == 99 for record in growth_records)
            and all(before == after for before, after in growth_roundtrips)
        ),
        "growth_single_nibble_preserves_neighbor_and_reserved": (
            _changed_indices(growth_patch[1], growth_patch[2]) == [0]
            and (growth_patch[1][0] & 0x0F) == (growth_patch[2][0] & 0x0F)
            and (growth_patch[1][-1] & 0x0F) == (growth_patch[2][-1] & 0x0F)
        ),
        "growth_quick_60_preserves_levels_61_99": (
            quick_patch[2][:30] == bytes((0xFF,)) * 30
            and quick_patch[2][30:] == quick_patch[1][30:]
        ),
        "growth_invalid_input_rejected": (
            "99 个" in invalid_growth_length and "0—15" in invalid_growth_value
        ),
        "shared_growth_ids_explicit": shared_record.shared_ids == tuple(range(214, 254)),
        "level_cap_compatibility_report_passed": bool(level_cap["passed"]),
        "source_rom_unchanged": _sha256(data) == original_hash,
        "reference_all_414_fields_cold_readback": (
            reference_all_fields.get("passed") is True
            and reference_all_fields.get("logical_fields") == 414
            and reference_all_fields.get("saved_fields") == 412
            and reference_all_fields.get("no_effect_fields") == 2
            and reference_all_fields.get("cold_process_logical_readback_passed") == 414
        ),
    }
    return {
        "generated_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "passed": all(checks.values()),
        "delivery_status": "reference_field_scope_complete_product_compatibility_and_user_pending",
        "conclusion": (
            "M09 当前 99 级安全范围、经验/命中表、系统文字和成长编辑均通过实现侧门禁；"
            "参考 audit.nes 的 414 个逻辑入口保存/冷读已全部完成。参考 5×16/60 级/30 字节"
            "与当前 4×16/99 级/50 字节布局差异和用户签收继续保留。"
        ),
        "rom": {
            "path": rom_path.resolve().relative_to(ROOT).as_posix(),
            "size": len(data),
            "sha256": original_hash,
            "unchanged_after_analysis": _sha256(data) == original_hash,
        },
        "evidence": {
            "distance_hit": {
                "shape": [len(distance_rows), len(distance_rows[0])],
                "offset": f"0x{distance_patch[0]:06X}",
                "sample_changed_indices": _changed_indices(
                    distance_patch[1], distance_patch[2]
                ),
            },
            "experience": {
                "entries": len(experience),
                "level_50": experience[49],
                "level_98": experience[-2],
                "level_99": experience[-1],
                "offset": f"0x{experience_patch[0]:06X}",
                "sample_changed_indices": _changed_indices(
                    experience_patch[1], experience_patch[2]
                ),
            },
            "system_text": {
                "indices": 221,
                "variants": system_variants,
                "no_op_roundtrips": sum(system_roundtrips),
                "sample_id": 9,
                "sample_offset": f"0x{system_patch[0]:06X}",
                "sample_changed_indices": _changed_indices(
                    system_patch[1], system_patch[2]
                ),
            },
            "growth": {
                "slots": len(growth_records),
                "unique_records": len({record.file_offset for record in growth_records}),
                "values_per_record": len(growth.values),
                "record_bytes": len(growth.raw),
                "no_op_roundtrips": sum(
                    before == after for before, after in growth_roundtrips
                ),
                "single_nibble_patch_offset": f"0x{growth_patch[0]:06X}",
                "single_nibble_changed_indices": _changed_indices(
                    growth_patch[1], growth_patch[2]
                ),
                "quick_edit_values": 60,
                "quick_edit_changed_record_bytes": _changed_indices(
                    quick_patch[1], quick_patch[2]
                ),
                "shared_ids_214_253": list(shared_record.shared_ids),
                "invalid_length_rejection": invalid_growth_length,
                "invalid_value_rejection": invalid_growth_value,
            },
            "level_cap": level_cap,
            "reference_all_fields": reference_all_fields,
        },
        "checks": checks,
        "pending_acceptance": [
            "确认参考第五距离段在当前扩容 ROM 中的目标布局；未经证实不开放写入。",
            "正式 EXE 人工执行 M09 验收清单并由用户签收。",
        ],
    }


def main() -> int:
    parser = argparse.ArgumentParser(
        description="复验 M09 命中/经验、系统文字、成长方式及 99 级边界。"
    )
    parser.add_argument("--rom", type=Path, default=DEFAULT_ROM)
    parser.add_argument("--audit-before", type=Path, default=DEFAULT_AUDIT_BEFORE)
    parser.add_argument("--audit-after", type=Path, default=DEFAULT_AUDIT_AFTER)
    parser.add_argument("--report", type=Path, default=DEFAULT_REPORT)
    arguments = parser.parse_args()
    report = analyze(
        arguments.rom, arguments.audit_before, arguments.audit_after
    )
    arguments.report.parent.mkdir(parents=True, exist_ok=True)
    arguments.report.write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
