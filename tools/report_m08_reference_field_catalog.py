"""Build the exhaustive M08 reference UI field catalog from read-only evidence."""

from __future__ import annotations

import hashlib
import json
import re
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "output/verification/legacy-ui-probe-m08-battle-20260920/M08_战斗对话完整控件.json"
JSON_OUT = ROOT / "output/reports/m08-reference-field-catalog.json"
MD_OUT = ROOT / "output/reports/m08-reference-field-catalog.md"


def build_catalog(source: Path = SOURCE) -> dict[str, object]:
    source_bytes = source.read_bytes()
    evidence = json.loads(source_bytes.decode("utf-8"))
    fields: list[dict[str, object]] = []
    group_summary: list[dict[str, object]] = []
    by_text: dict[str, list[str]] = defaultdict(list)
    for group in evidence["variant_counts"]:
        segment = str(group["segment_text"])
        start = len(fields)
        for row in group["rows"]:
            row_index = int(row["row"])
            for variant_index, display_text in enumerate(row["variants"]):
                value = re.sub(r"^\d{3}：", "", str(display_text), count=1)
                field_id = f"M08/{segment}/{row_index:03d}/{variant_index:03d}"
                fields.append(
                    {
                        "field_id": field_id,
                        "segment": segment,
                        "row": row_index,
                        "variant": variant_index,
                        "display_text": display_text,
                        "editable_value": value,
                    }
                )
                by_text[value].append(field_id)
        group_summary.append(
            {
                "segment": segment,
                "rows": int(group["row_count"]),
                "variants": len(fields) - start,
                "minimum_variants_per_row": int(group["minimum_variants"]),
                "maximum_variants_per_row": int(group["maximum_variants"]),
            }
        )
    text_equivalence = [
        {"editable_value": text, "field_ids": ids}
        for text, ids in sorted(by_text.items())
        if len(ids) > 1
    ]
    return {
        "schema_version": 1,
        "source": SOURCE.relative_to(ROOT).as_posix(),
        "source_sha256": hashlib.sha256(source_bytes).hexdigest(),
        "rom_unchanged": bool(evidence["rom_unchanged"]),
        "counts": {
            "segments": len(group_summary),
            "rows": sum(int(item["rows"]) for item in group_summary),
            "ui_fields": len(fields),
            "unique_display_values": len(by_text),
            "text_equivalence_groups": len(text_equivalence),
        },
        "groups": group_summary,
        "verified_physical_aliases": [
            {
                "source_field_id": "M08/07/000/000",
                "reopen_field_id": "M08/05/000/000",
                "evidence": "output/build/legacy-diff-audit/cases/legacy_live/M08/battle_07_alias_row000_variant000/cold_start_01/case.json",
                "note": "07 保存后从 05 组冷启动回读同一修改值。",
            }
        ],
        "scope_note": "text_equivalence 只表示界面原文相同，不自动证明物理指针别名；只有 verified_physical_aliases 可作为跨入口物理别名证据。",
        "fields": fields,
        "text_equivalence": text_equivalence,
    }


def render_markdown(report: dict[str, object]) -> str:
    counts = report["counts"]
    lines = [
        "# M08 参考版可编辑字段目录",
        "",
        f"- 来源：`{report['source']}`",
        f"- 来源 SHA-256：`{report['source_sha256']}`",
        f"- 只读枚举 ROM 未变化：{'是' if report['rom_unchanged'] else '否'}",
        f"- 组/行/界面字段：{counts['segments']} / {counts['rows']} / {counts['ui_fields']}",
        f"- 不同界面原文：{counts['unique_display_values']}；原文重复组：{counts['text_equivalence_groups']}",
        "",
        "> 原文相同不自动等于物理指针相同；只有报告中的 verified_physical_aliases 是保存后跨入口冷回读证实的物理别名。",
        "",
        "| 组 | 行数 | 界面字段 | 单行最少/最多分支 |",
        "|---|---:|---:|---:|",
    ]
    for group in report["groups"]:
        lines.append(
            f"| {group['segment']} | {group['rows']} | {group['variants']} | "
            f"{group['minimum_variants_per_row']} / {group['maximum_variants_per_row']} |"
        )
    lines.extend(["", "完整 1,248 项字段及原文见同名 JSON。", ""])
    return "\n".join(lines)


def main() -> int:
    report = build_catalog()
    JSON_OUT.parent.mkdir(parents=True, exist_ok=True)
    JSON_OUT.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    MD_OUT.write_text(render_markdown(report), encoding="utf-8")
    print(
        f"M08 reference field catalog: {report['counts']['ui_fields']} fields, "
        f"{report['counts']['rows']} rows, {report['counts']['segments']} groups"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
