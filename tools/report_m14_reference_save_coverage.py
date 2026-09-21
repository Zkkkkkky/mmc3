"""Verify and report the exhaustive M14 per-field reference save chain."""

from __future__ import annotations

import hashlib
import json
from collections import Counter
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
CATALOG = ROOT / "output/reports/m14-reference-field-catalog.json"
EVIDENCE_DIR = ROOT / "output/verification/legacy-m14-all-fields-20260920"
CHAIN = EVIDENCE_DIR / "field-save-chain.jsonl"
BASELINE = EVIDENCE_DIR / "normalized-baseline.nes"
WORK = EVIDENCE_DIR / "work.nes"
WARM = EVIDENCE_DIR / "same-process-final-values.json"
COLD = EVIDENCE_DIR / "cold-process-final-values.json"
JSON_OUT = ROOT / "output/reports/m14-reference-save-coverage.json"
MD_OUT = ROOT / "output/reports/m14-reference-save-coverage.md"

PERSISTENT = {
    "chapter_initial_victory",
    "surrender_chapter",
    "surrender_ally",
    "surrender_enemy",
    "story_text",
    "victory_text",
}
VOLATILE = {"chapter_title", "action_name", "map_name"}
ORDER = {
    "chapter_initial_victory": 0,
    "surrender_chapter": 1,
    "surrender_ally": 2,
    "surrender_enemy": 3,
    "story_text": 4,
    "victory_text": 5,
    "chapter_title": 6,
    "action_name": 7,
    "map_name": 8,
}


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def rows() -> list[dict[str, object]]:
    if not CHAIN.is_file():
        return []
    return [json.loads(line) for line in CHAIN.read_text(encoding="utf-8").splitlines() if line]


def build() -> dict[str, object]:
    catalog = json.loads(CATALOG.read_text(encoding="utf-8"))
    fields = sorted(
        catalog["fields"],
        key=lambda item: (ORDER[str(item["family"])], str(item.get("group", "")), int(item["row"])),
    )
    evidence = rows()
    sequences = all(int(item["sequence"]) == index for index, item in enumerate(evidence))
    identities = all(
        item["catalog_field_id"] == fields[index]["field_id"]
        for index, item in enumerate(evidence)
        if index < len(fields)
    ) and len(evidence) <= len(fields)
    chain_links = all(
        evidence[index]["after_sha256"] == evidence[index + 1]["before_sha256"]
        for index in range(len(evidence) - 1)
    )
    replay = bytearray(BASELINE.read_bytes()) if BASELINE.is_file() else bytearray()
    replay_valid = bool(replay)
    if replay_valid:
        for item in evidence:
            if sha(bytes(replay)) != item["before_sha256"]:
                replay_valid = False
                break
            for change in item["ranges"]:
                start, end = int(change["start"]), int(change["end_exclusive"])
                if replay[start:end].hex().upper() != change["before_hex"]:
                    replay_valid = False
                    break
                replay[start:end] = bytes.fromhex(change["after_hex"])
            if not replay_valid or sha(bytes(replay)) != item["after_sha256"]:
                replay_valid = False
                break
    tail_matches_work = bool(evidence and WORK.is_file() and evidence[-1]["after_sha256"] == sha(WORK.read_bytes()))
    observed = all(item["observed_before_commit"] == item["mutated"] for item in evidence)
    family_results = Counter(str(item["family"]) for item in evidence)
    statuses = Counter(str(item["status"]) for item in evidence)
    persistence_matches = all(
        (bool(item["ranges"]) if str(item["family"]) in PERSISTENT else not bool(item["ranges"]))
        for item in evidence
    )
    inventories_present = WARM.is_file() and COLD.is_file()
    warm = json.loads(WARM.read_text(encoding="utf-8")) if WARM.is_file() else {}
    cold = json.loads(COLD.read_text(encoding="utf-8")) if COLD.is_file() else {}
    cold_inventory_stable = inventories_present and warm == cold and len(cold) == len(fields)
    complete = len(evidence) == len(fields)
    checks = {
        "catalog_passed": bool(catalog["passed"]),
        "all_3217_fields_recorded": complete,
        "sequences_contiguous": sequences,
        "catalog_identities_match": identities,
        "hash_links_contiguous": chain_links,
        "byte_ranges_replay": replay_valid,
        "tail_matches_work_rom": tail_matches_work,
        "requested_value_observed_before_each_save": observed,
        "persistent_and_volatile_family_classification_matches": persistence_matches,
        "two_fresh_final_inventories_match": cold_inventory_stable,
    }
    return {
        "schema_version": 1,
        "module": "M14",
        "passed": all(checks.values()),
        "status": "complete" if all(checks.values()) else "collecting",
        "counts": {
            "catalog_fields": len(fields),
            "persistent_catalog_fields": sum(
                str(item["family"]) in PERSISTENT for item in fields
            ),
            "volatile_catalog_fields": sum(
                str(item["family"]) in VOLATILE for item in fields
            ),
            "read_only_instruction_rows": int(catalog["read_only_instruction_rows"]),
            "completed_fields": len(evidence),
            "remaining_fields": len(fields) - len(evidence),
            "safe_denominator_fields": sum(
                bool(item["ranges"]) and str(item["family"]) in PERSISTENT
                for item in evidence
            ),
            "families": dict(sorted(family_results.items())),
            "statuses": dict(sorted(statuses.items())),
            "cold_inventory_fields": len(cold),
        },
        "checks": checks,
        "evidence": {
            "catalog": CATALOG.relative_to(ROOT).as_posix(),
            "save_chain": CHAIN.relative_to(ROOT).as_posix(),
            "normalized_baseline": BASELINE.relative_to(ROOT).as_posix(),
            "work_rom": WORK.relative_to(ROOT).as_posix(),
            "same_process_inventory": WARM.relative_to(ROOT).as_posix(),
            "cold_process_inventory": COLD.relative_to(ROOT).as_posix(),
        },
    }


def markdown(report: dict[str, object]) -> str:
    counts = report["counts"]
    lines = [
        "# M14 参考版逐字段保存覆盖",
        "",
        f"- 状态：`{report['status']}`",
        f"- 已完成：{counts['completed_fields']}/{counts['catalog_fields']}；剩余 {counts['remaining_fields']}",
        f"- 安全持久化候选：{counts['persistent_catalog_fields']}；当前已证实 {counts['safe_denominator_fields']}",
        f"- 排除：参考运行时易失字段 {counts['volatile_catalog_fields']}",
        f"- 已枚举但无字段编辑入口的事件/指令行：{counts['read_only_instruction_rows']}",
        f"- 最终冷进程目录字段：{counts['cold_inventory_fields']}",
        "- 已采集字段族：" + "；".join(
            f"{name}={value}" for name, value in counts["families"].items()
        ),
        "",
        "| 检查 | 结果 |",
        "|---|---|",
    ]
    for name, passed in report["checks"].items():
        lines.append(f"| `{name}` | {'通过' if passed else '待完成'} |")
    lines.extend(("", "未完成时本报告保持 collecting，不以部分链冒充全量覆盖。", ""))
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
