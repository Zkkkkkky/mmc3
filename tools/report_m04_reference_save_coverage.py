"""Verify and report isolated M04 reference save cases."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
CATALOG = ROOT / "output/reports/m04-reference-field-catalog.json"
EVIDENCE = ROOT / "output/verification/legacy-m04-all-fields-20260920"
CASES = EVIDENCE / "field-save-cases.jsonl"
BASELINE = EVIDENCE / "normalized-baseline.nes"
AGGREGATE = EVIDENCE / "aggregate-all-fields.nes"
WARM = EVIDENCE / "fresh-inventory-a.json"
COLD = EVIDENCE / "fresh-inventory-b.json"
JSON_OUT = ROOT / "output/reports/m04-reference-field-coverage.json"
MD_OUT = ROOT / "output/reports/m04-reference-field-coverage.md"
ORDER = {"x": 0, "y": 1, "character_id": 2, "event_id": 3}


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def rows() -> list[dict[str, object]]:
    if not CASES.is_file():
        return []
    return [json.loads(line) for line in CASES.read_text(encoding="utf-8").splitlines() if line]


def build() -> dict[str, object]:
    catalog = json.loads(CATALOG.read_text(encoding="utf-8"))
    fields = sorted(
        (item for item in catalog["fields"] if item["classification"] == "persistent_candidate"),
        key=lambda item: (int(item["map_id"]), int(item["row"]), ORDER[str(item["field"])]),
    )
    cases = rows()
    identities = len(cases) <= len(fields) and all(item["catalog_field_id"] == fields[index]["field_id"] for index, item in enumerate(cases))
    sequences = all(int(item["sequence"]) == index for index, item in enumerate(cases))
    baseline_sha = sha(BASELINE.read_bytes()) if BASELINE.is_file() else None
    isolated = bool(baseline_sha) and all(
        item["before_sha256"] == baseline_sha
        and item["changed_offsets"] == [item["file_offset"]]
        and item["after_byte"] == item["requested"]
        for item in cases
    )
    aggregate_valid = False
    if BASELINE.is_file() and AGGREGATE.is_file() and len(cases) == len(fields):
        replay = bytearray(BASELINE.read_bytes())
        for item in cases:
            replay[int(item["file_offset"])] = int(item["after_byte"])
        aggregate_valid = bytes(replay) == AGGREGATE.read_bytes()
    warm = json.loads(WARM.read_text(encoding="utf-8")) if WARM.is_file() else {}
    cold = json.loads(COLD.read_text(encoding="utf-8")) if COLD.is_file() else {}
    inventories = len(cold) == len(fields) and warm == cold
    checks = {
        "catalog_passed": bool(catalog["passed"]),
        "all_103_editable_fields_recorded": len(cases) == len(fields) == 103,
        "sequences_contiguous": sequences,
        "catalog_identities_match": identities,
        "each_isolated_case_changes_exactly_target_byte": isolated,
        "aggregate_replays_all_cases": aggregate_valid,
        "two_fresh_reference_inventories_match": inventories,
    }
    return {
        "schema_version": 1,
        "module": "M04",
        "passed": all(checks.values()),
        "status": "complete" if all(checks.values()) else "collecting",
        "counts": {
            "physical_fields": catalog["counts"]["physical_fields"],
            "records": catalog["counts"]["records"],
            "catalog_fields": len(fields),
            "completed_fields": len(cases),
            "remaining_fields": len(fields) - len(cases),
            "safe_denominator_fields": len(cases) if isolated else 0,
            "fresh_inventory_fields": len(cold),
            "excluded_reference_off_viewport": catalog["counts"]["reference_off_viewport_fields"],
            "excluded_reference_forced_unlimited": catalog["counts"]["reference_forced_unlimited_fields"],
        },
        "checks": checks,
        "evidence": {
            "catalog": CATALOG.relative_to(ROOT).as_posix(),
            "isolated_cases": CASES.relative_to(ROOT).as_posix(),
            "aggregate_rom": AGGREGATE.relative_to(ROOT).as_posix(),
            "fresh_inventory_a": WARM.relative_to(ROOT).as_posix(),
            "fresh_inventory_b": COLD.relative_to(ROOT).as_posix(),
        },
    }


def markdown(report: dict[str, object]) -> str:
    count = report["counts"]
    lines = [
        "# M04 参考版逐字段保存覆盖",
        "",
        f"- 状态：`{report['status']}`",
        f"- 已完成：{count['completed_fields']}/{count['catalog_fields']}；剩余 {count['remaining_fields']}",
        f"- 安全持久化候选：{count['catalog_fields']}；当前已证实 {count['safe_denominator_fields']}",
        f"- 最终全新进程目录字段：{count['fresh_inventory_fields']}",
        f"- 排除：固定视口外无编辑入口 {count['excluded_reference_off_viewport']}",
        f"- 排除：事件类限定人物强制 FF {count['excluded_reference_forced_unlimited']}",
        f"- 物理字段全集：{count['physical_fields']}（{count['records']} 条记录）",
        "",
        "| 检查 | 结果 |",
        "|---|---|",
    ]
    lines.extend(f"| `{name}` | {'通过' if value else '待完成'} |" for name, value in report["checks"].items())
    lines.extend(("", "未完成时保持 collecting，写入门禁不解除。", ""))
    return "\n".join(lines)


def main() -> int:
    report = build()
    JSON_OUT.parent.mkdir(parents=True, exist_ok=True)
    JSON_OUT.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    MD_OUT.write_text(markdown(report), encoding="utf-8")
    print(json.dumps({"passed": report["passed"], **report["counts"]}, ensure_ascii=False))
    return 0 if report["passed"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
