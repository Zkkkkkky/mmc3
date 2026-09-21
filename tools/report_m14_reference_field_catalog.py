from __future__ import annotations

import argparse
import json
from collections import Counter
from datetime import datetime
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
CATALOG_SOURCE = ROOT / "output/verification/legacy-m14-reference-catalog-20260920/catalog.json"
INSTRUCTION_COUNTS = ROOT / "output/verification/legacy-m14-reference-catalog-20260920/instruction-counts.json"
EDITOR_PROBE = ROOT / "output/verification/legacy-m14-reference-editors-20260920/editors.json"
VICTORY_TEXTS = ROOT / "output/verification/legacy-m14-reference-catalog-20260920/victory-texts.json"
DEFAULT_JSON = ROOT / "output/reports/m14-reference-field-catalog.json"
DEFAULT_MD = ROOT / "output/reports/m14-reference-field-catalog.md"


def load(path: Path) -> dict[str, object]:
    return json.loads(path.read_text(encoding="utf-8"))


def build() -> dict[str, object]:
    source = load(CATALOG_SOURCE)
    counts = load(INSTRUCTION_COUNTS)
    editors = load(EDITOR_PROBE)
    victory_texts = load(VICTORY_TEXTS)
    fields: list[dict[str, object]] = []

    for chapter in source["chapter_rows"]:
        row = int(chapter["row"])
        fields.extend(
            (
                {
                    "field_id": f"M14/chapter/{row:03d}/title",
                    "family": "chapter_title",
                    "row": row,
                    "control_id": 600,
                    "original": chapter["title"],
                },
                {
                    "field_id": f"M14/chapter/{row:03d}/initial_victory",
                    "family": "chapter_initial_victory",
                    "row": row,
                    "control_id": 190,
                    "original": chapter["initial_victory"],
                },
            )
        )

    for action in source["action_rows"]:
        row = int(action["row"])
        fields.append(
            {
                "field_id": f"M14/action/{row:03d}/name",
                "family": "action_name",
                "row": row,
                "control_id": 390,
                "original": action["name"],
            }
        )

    for surrender in source["surrender_rows"]:
        row = int(surrender["row"])
        for family, control_id, key in (
            ("surrender_chapter", 430, "chapter"),
            ("surrender_ally", 440, "ally"),
            ("surrender_enemy", 460, "enemy"),
        ):
            fields.append(
                {
                    "field_id": f"M14/surrender/{row:03d}/{family.removeprefix('surrender_')}",
                    "family": family,
                    "row": row,
                    "control_id": control_id,
                    "original": surrender[key],
                }
            )

    for map_row in source["map_rows"]:
        row = int(map_row["row"])
        fields.append(
            {
                "field_id": f"M14/map/{row:03d}/name",
                "family": "map_name",
                "row": row,
                "control_id": 490,
                "original": map_row["name"],
            }
        )

    for group in source["story_rows"]:
        label = str(group["label"])
        records = list(group["records"])
        texts = list(group["texts"])
        if len(records) != len(texts):
            raise AssertionError(f"story group {label} row/text mismatch")
        for row, (record, text) in enumerate(zip(records, texts, strict=True)):
            fields.append(
                {
                    "field_id": f"M14/story/{label}/{row:03d}",
                    "family": "story_text",
                    "group": label,
                    "row": row,
                    "control_id": 520,
                    "record": record,
                    "original": text,
                }
            )

    for victory in victory_texts["rows"]:
        row = int(victory["row"])
        fields.append(
            {
                "field_id": f"M14/victory/{row:03d}",
                "family": "victory_text",
                "row": row,
                "control_id": 650,
                "record": victory["label"],
                "original": victory["text"],
            }
        )

    families = Counter(str(item["family"]) for item in fields)
    instruction_totals = counts["totals"]
    read_only_instruction_rows = (
        sum(int(value) for value in instruction_totals["chapter_phases"])
        + int(instruction_totals["actions"])
        + int(instruction_totals["surrender"])
        + int(instruction_totals["maps"])
    )
    expected = {
        "chapter_title": 32,
        "chapter_initial_victory": 32,
        "action_name": 256,
        "surrender_chapter": 32,
        "surrender_ally": 32,
        "surrender_enemy": 32,
        "map_name": 255,
        "story_text": 2295,
        "victory_text": 251,
    }
    checks = {
        "source_passed_and_unchanged": bool(source["passed"] and source["rom_unchanged"]),
        "instruction_counts_passed_and_unchanged": bool(counts["passed"] and counts["rom_unchanged"]),
        "editor_probe_passed_and_unchanged": bool(editors["passed"] and editors["rom_unchanged"]),
        "victory_texts_recaptured_and_unchanged": bool(victory_texts["passed"] and victory_texts["rom_unchanged"] and len(victory_texts["rows"]) == 251 and all(item["text"] for item in victory_texts["rows"])),
        "six_instruction_surfaces_have_no_editor": len(editors["probes"]) == 6 and all(not item["new_windows"] for item in editors["probes"]),
        "family_counts_match": dict(families) == expected,
        "field_ids_unique": len({str(item["field_id"]) for item in fields}) == len(fields),
        "reference_instruction_rows_counted": read_only_instruction_rows == 9920,
    }
    return {
        "generated_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "module": "M14",
        "passed": all(checks.values()),
        "status": "reference_direct_fields_cataloged_save_evidence_pending",
        "field_count": len(fields),
        "family_counts": dict(families),
        "read_only_instruction_rows": read_only_instruction_rows,
        "instruction_counts": instruction_totals,
        "checks": checks,
        "evidence": {
            "runtime_catalog": CATALOG_SOURCE.relative_to(ROOT).as_posix(),
            "instruction_counts": INSTRUCTION_COUNTS.relative_to(ROOT).as_posix(),
            "editor_probe": EDITOR_PROBE.relative_to(ROOT).as_posix(),
            "victory_texts": VICTORY_TEXTS.relative_to(ROOT).as_posix(),
        },
        "fields": fields,
    }


def markdown(report: dict[str, object]) -> str:
    lines = [
        "# M14 参考版直接字段目录",
        "",
        f"- 直接可编辑字段：{report['field_count']}",
        f"- 只读指令解释行：{report['read_only_instruction_rows']}",
        f"- 状态：`{report['status']}`",
        "",
        "| 字段族 | 数量 |",
        "|---|---:|",
    ]
    for family, count in report["family_counts"].items():
        lines.append(f"| `{family}` | {count} |")
    lines.extend(
        (
            "",
            "关卡三阶段、行动、劝降和地图四类大列表中的 9,920 条非空指令均为解释视图；六类代表行双击不产生编辑窗口。直接字段目录仅包含页面上的 Edit/ComboBox，并等待逐字段保存/冷读分类。",
            "",
        )
    )
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--json", type=Path, default=DEFAULT_JSON)
    parser.add_argument("--markdown", type=Path, default=DEFAULT_MD)
    args = parser.parse_args()
    report = build()
    args.json.parent.mkdir(parents=True, exist_ok=True)
    args.json.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    args.markdown.write_text(markdown(report), encoding="utf-8")
    print(json.dumps({"passed": report["passed"], "field_count": report["field_count"], "read_only_instruction_rows": report["read_only_instruction_rows"], "family_counts": report["family_counts"]}, ensure_ascii=False))
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
