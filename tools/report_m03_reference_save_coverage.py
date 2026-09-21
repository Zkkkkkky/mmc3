"""Verify and report the exhaustive M03 reference save chain."""

from __future__ import annotations

import hashlib
import json
import time
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
CATALOG = ROOT / "output/reports/m03-reference-field-catalog.json"
EVIDENCE = ROOT / "output/verification/legacy-m03-all-fields-20260920"
CHAIN = EVIDENCE / "field-save-chain.jsonl"
BASELINE = EVIDENCE / "normalized-baseline.nes"
WORK = EVIDENCE / "work.nes"
WARM = EVIDENCE / "fresh-inventory-a.json"
COLD = EVIDENCE / "fresh-inventory-b.json"
JSON_OUT = ROOT / "output/reports/m03-reference-field-coverage.json"
MD_OUT = ROOT / "output/reports/m03-reference-field-coverage.md"
FAMILY_ORDER = {"enemy": 0, "guest": 1, "player": 2}
FIELD_ORDER = {"x": 0, "y": 1, "pilot_id": 2, "unit_id": 3, "level": 4, "roster_index": 5, "flags": 6}


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def rows() -> list[dict[str, object]]:
    if not CHAIN.is_file():
        return []
    return [json.loads(line) for line in CHAIN.read_text(encoding="utf-8").splitlines() if line]


def consistent_rows_and_work() -> tuple[list[dict[str, object]], bytes]:
    """Read a chain/work pair that is not between the save and append steps."""
    evidence: list[dict[str, object]] = []
    work = WORK.read_bytes() if WORK.is_file() else b""
    for _attempt in range(40):
        evidence = rows()
        work = WORK.read_bytes() if WORK.is_file() else b""
        if not evidence or evidence[-1].get(
            "continuation_sha256", evidence[-1]["after_sha256"]
        ) == sha(work):
            return evidence, work
        time.sleep(0.05)
    return evidence, work


def build() -> dict[str, object]:
    catalog = json.loads(CATALOG.read_text(encoding="utf-8"))
    fields = sorted(
        (item for item in catalog["fields"] if item["classification"] == "persistent_candidate"),
        key=lambda item: (int(item["map_id"]), FAMILY_ORDER[str(item["family"])], int(item["row"]), FIELD_ORDER[str(item["field"])]),
    )
    evidence, work = consistent_rows_and_work()
    identities = len(evidence) <= len(fields) and all(item["catalog_field_id"] == fields[index]["field_id"] for index, item in enumerate(evidence))
    sequences = all(int(item["sequence"]) == index for index, item in enumerate(evidence))
    links = all(
        evidence[index].get("continuation_sha256", evidence[index]["after_sha256"])
        == evidence[index + 1]["before_sha256"]
        for index in range(len(evidence) - 1)
    )
    exact_offsets = all(item["changed_offsets"] == [item["file_offset"]] for item in evidence)
    exact_values = all(
        str(item["field"]) in {"x", "y"}
        or (
            int(item["before_byte"])
            == int(item["ui_observed"])
            + (1 if str(item["field"]) in {"pilot_id", "unit_id"} else 0)
            and int(item["after_byte"])
            == int(item["ui_requested"])
            + (1 if str(item["field"]) in {"pilot_id", "unit_id"} else 0)
        )
        for item in evidence
    )
    coordinate_results_safe = all(
        str(item["field"]) not in {"x", "y"}
        or (
            int(item["after_byte"]) != int(item["before_byte"])
            and bool(item.get("isolated_coordinate_case"))
            and int(item.get("continuation_restored_byte", -1))
            == int(item["before_byte"])
        )
        for item in evidence
    )
    replay = bytearray(BASELINE.read_bytes()) if BASELINE.is_file() else bytearray()
    replay_valid = bool(replay)
    if replay_valid:
        for item in evidence:
            if sha(bytes(replay)) != item["before_sha256"]:
                replay_valid = False
                break
            offset = int(item["file_offset"])
            if replay[offset] != int(item["before_byte"]):
                replay_valid = False
                break
            replay[offset] = int(item["after_byte"])
            if sha(bytes(replay)) != item["after_sha256"]:
                replay_valid = False
                break
            if "continuation_restored_byte" in item:
                replay[offset] = int(item["continuation_restored_byte"])
                if sha(bytes(replay)) != item["continuation_sha256"]:
                    replay_valid = False
                    break
    tail = bool(work) and (
        (
            evidence[-1].get(
                "continuation_sha256", evidence[-1]["after_sha256"]
            )
            == sha(work)
        )
        if evidence
        else bool(replay) and sha(work) == sha(bytes(replay))
    )
    warm = json.loads(WARM.read_text(encoding="utf-8")) if WARM.is_file() else {}
    cold = json.loads(COLD.read_text(encoding="utf-8")) if COLD.is_file() else {}
    inventories = len(warm) == len(fields) and warm == cold
    checks = {
        "catalog_passed": bool(catalog["passed"]),
        "all_1380_editable_fields_recorded": len(evidence) == len(fields) == 1380,
        "sequences_contiguous": sequences,
        "catalog_identities_match": identities,
        "hash_links_contiguous": links,
        "each_save_changes_exactly_target_byte": exact_offsets,
        "requested_value_persisted_exactly": exact_values,
        "coordinate_result_changed_and_isolated": coordinate_results_safe,
        "byte_chain_replays": replay_valid,
        "tail_matches_work_rom": tail,
        "two_fresh_reference_inventories_match": inventories,
    }
    return {
        "schema_version": 1,
        "module": "M03",
        "passed": all(checks.values()),
        "status": "complete" if all(checks.values()) else "collecting",
        "counts": {
            "physical_fields": catalog["counts"]["physical_fields"],
            "catalog_fields": len(fields),
            "completed_fields": len(evidence),
            "remaining_fields": len(fields) - len(evidence),
            "safe_denominator_fields": (
                len(evidence)
                if exact_offsets and exact_values and coordinate_results_safe
                else 0
            ),
            "fresh_inventory_fields": len(cold),
            "excluded_reference_no_rom_effect": catalog["counts"]["reference_no_rom_effect_fields"],
            "excluded_reference_off_viewport": catalog["counts"]["reference_off_viewport_fields"],
            "runtime_route_selector_views": catalog["counts"]["runtime_route_selector_views"],
            "guarded_structural_type_actions": catalog["counts"]["guarded_structural_type_actions"],
            "logical_ui_entries": catalog["counts"]["logical_ui_entries"],
        },
        "checks": checks,
        "evidence": {
            "catalog": CATALOG.relative_to(ROOT).as_posix(),
            "save_chain": CHAIN.relative_to(ROOT).as_posix(),
            "work_rom": WORK.relative_to(ROOT).as_posix(),
            "fresh_inventory_a": WARM.relative_to(ROOT).as_posix(),
            "fresh_inventory_b": COLD.relative_to(ROOT).as_posix(),
        },
    }


def markdown(report: dict[str, object]) -> str:
    count = report["counts"]
    lines = [
        "# M03 参考版逐字段保存覆盖",
        "",
        f"- 状态：`{report['status']}`",
        f"- 已完成：{count['completed_fields']}/{count['catalog_fields']}；剩余 {count['remaining_fields']}",
        f"- 安全持久化候选：{count['catalog_fields']}；当前已证实 {count['safe_denominator_fields']}",
        f"- 最终全新进程目录字段：{count['fresh_inventory_fields']}",
        f"- 排除：参考版保存无 ROM 效果 {count['excluded_reference_no_rom_effect']}；固定视口外无编辑入口 {count['excluded_reference_off_viewport']}",
        f"- 非字段交互入口：三路图标地址视图 {count['runtime_route_selector_views']}；阵营迁移动作 {count['guarded_structural_type_actions']}",
        f"- 物理字段全集：{count['physical_fields']}；逻辑 UI 入口总数：{count['logical_ui_entries']}",
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
