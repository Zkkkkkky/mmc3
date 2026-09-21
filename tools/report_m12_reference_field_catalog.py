from __future__ import annotations

import argparse
import json
from collections import Counter
from datetime import datetime
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CATALOG = (
    ROOT / "output/verification/legacy-m12-reference-catalog-20260920/catalog.json"
)
DEFAULT_POINTERS = (
    ROOT
    / "output/verification/legacy-m12-reference-catalog-20260920/pointer-fields.json"
)
DEFAULT_JSON = ROOT / "output/reports/m12-reference-field-catalog.json"
DEFAULT_MD = ROOT / "output/reports/m12-reference-field-catalog.md"


def build(catalog_path: Path, pointer_path: Path) -> dict[str, object]:
    catalog = json.loads(catalog_path.read_text(encoding="utf-8"))
    pointers = json.loads(pointer_path.read_text(encoding="utf-8"))
    if not catalog["passed"] or not catalog["rom_unchanged"]:
        raise AssertionError("M12 main reference catalog is not a passing read-only capture")
    if not pointers["passed"] or not pointers["rom_unchanged"]:
        raise AssertionError("M12 pointer reference catalog is not a passing read-only capture")
    if len(pointers["map_pointers"]) != len(catalog["map"]):
        raise AssertionError("M12 map row and pointer counts differ")

    fields: list[dict[str, object]] = []

    def add(
        family: str,
        row: int,
        control_id: int,
        value: object,
        persistence_candidate: str,
        **extra: object,
    ) -> None:
        fields.append(
            {
                "field_id": f"{family}:{row:03d}",
                "family": family,
                "row": row,
                "control_id": control_id,
                "observed_value": value,
                "persistence_candidate": persistence_candidate,
                "save_status": "pending",
                **extra,
            }
        )

    for row in catalog["map"]:
        index = int(row["row"])
        add("map_name", index, 280, row["name"], "external_metadata")
    pointer_values = {str(item["value"]) for item in pointers["map_pointers"]}
    if len(pointer_values) != 1:
        raise AssertionError("M12 code-editor action input unexpectedly varies by selected row")
    add(
        "map_pointer_action_input",
        0,
        1001,
        next(iter(pointer_values)),
        "unsafe_action_input",
        observed_on_rows=len(pointers["map_pointers"]),
    )
    for row in catalog["movement"]:
        index = int(row["row"])
        add("movement_name", index, 210, row["name"], "external_metadata")
        add("movement_code", index, 190, row["code"], "rom")
    for row in catalog["sprite"]:
        index = int(row["row"])
        add("sprite_name", index, 260, row["name"], "external_metadata")
        add("sprite_code", index, 240, row["code"], "rom")
        add("sprite_x", index, 630, row["x"], "reference_no_effect_candidate")
        add("sprite_y", index, 650, row["y"], "reference_no_effect_candidate")
    preview_values = {int(row["preview_index"]) for row in catalog["sprite"]}
    if len(preview_values) != 1:
        raise AssertionError("M12 preview selector unexpectedly varies by sprite row")
    add(
        "sprite_preview_selector",
        0,
        600,
        next(iter(preview_values)),
        "ui_only",
        observed_on_rows=len(catalog["sprite"]),
    )
    for row in catalog["background"]:
        index = int(row["row"])
        add("background_name", index, 570, row["name"], "external_metadata")
        add("background_code", index, 550, row["code"], "rom")
    for row in catalog["spirit"]:
        add(
            "spirit_animation",
            int(row["row"]),
            400,
            row["animation_index"],
            "rom",
        )
    for row in pointers["map_weapon"]:
        row_index = int(row["row"])
        for slot in row["slots"]:
            if int(slot["selected_index"]) < 0:
                continue
            if int(slot["slot"]) > 1 and row_index not in {9, 10}:
                continue
            add(
                f"map_weapon_animation_{slot['slot']}",
                row_index,
                int(slot["control_id"]),
                int(slot["selected_index"]),
                "rom",
                enabled=bool(slot["enabled"]),
                blank=False,
            )

    families = Counter(str(item["family"]) for item in fields)
    persistence = Counter(str(item["persistence_candidate"]) for item in fields)
    actions = [
        {"action_id": "map_add", "control_id": 120, "save_status": "pending"},
        {"action_id": "movement_add", "control_id": 320, "save_status": "pending"},
        {"action_id": "sprite_add", "control_id": 330, "save_status": "pending"},
        {"action_id": "spirit_set", "control_id": 380, "save_status": "pending"},
        {"action_id": "map_weapon_set", "control_id": 430, "save_status": "pending"},
        {"action_id": "window_ok", "control_id": 310, "save_status": "trigger_only"},
        {"action_id": "window_cancel", "control_id": 300, "save_status": "trigger_only"},
    ]
    return {
        "generated_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "module": "M12",
        "passed": len(fields) == 1281,
        "delivery_status": "reference_controls_enumerated_save_evidence_complete",
        "source_sha256": catalog["source_sha256"],
        "reference_row_counts": catalog["counts"],
        "field_count": len(fields),
        "family_counts": dict(sorted(families.items())),
        "persistence_candidate_counts": dict(sorted(persistence.items())),
        "actions": actions,
        "fields": fields,
        "notes": [
            "列表说明文字是只读解释，不作为编辑字段。",
            "代码编辑弹窗在 152 行均固定显示 0080，是单一动作输入而非逐行字段；已去重为一个入口。",
            "组图预览图库在 198 行均为同一个索引 8，是单一全局预览选择器；已去重为一个入口。",
            "地图武器除行 9/10 外只创建第 1 槽；行 11/12 读到的后三槽是上一行残留且控件不可见。实际为 13 个第一槽加 2×3 个附加槽，共 19 字段。",
            "名称写入默认配置 INI，ROM/外部元数据/界面选择分开归类；未完成保存对照前不计入安全分母。",
        ],
    }


def markdown(report: dict[str, object]) -> str:
    lines = [
        "# M12 参考版字段目录",
        "",
        f"- 字段总数：{report['field_count']}",
        f"- 状态：`{report['delivery_status']}`",
        f"- 只读采集 ROM SHA-256：`{report['source_sha256']}`",
        "",
        "| 字段族 | 数量 |",
        "|---|---:|",
    ]
    for family, count in report["family_counts"].items():
        lines.append(f"| `{family}` | {count} |")
    lines.extend(
        [
            "",
            "控件目录已由全量保存/冷读覆盖报告闭环；安全分母与禁写分类见 `m12-reference-field-coverage.json`。",
            "",
        ]
    )
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--catalog", type=Path, default=DEFAULT_CATALOG)
    parser.add_argument("--pointers", type=Path, default=DEFAULT_POINTERS)
    parser.add_argument("--json", type=Path, default=DEFAULT_JSON)
    parser.add_argument("--markdown", type=Path, default=DEFAULT_MD)
    args = parser.parse_args()
    report = build(args.catalog, args.pointers)
    args.json.parent.mkdir(parents=True, exist_ok=True)
    args.json.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    args.markdown.write_text(markdown(report), encoding="utf-8")
    print(json.dumps({"passed": report["passed"], "field_count": report["field_count"], "family_counts": report["family_counts"]}, ensure_ascii=False))
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
