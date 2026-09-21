from __future__ import annotations

import argparse
import json
from collections import Counter
from datetime import datetime
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
CATALOG = ROOT / "output/reports/m12-reference-field-catalog.json"
SAVE_SUMMARY = ROOT / "output/verification/legacy-m12-all-fields-20260920/summary.json"
SAVE_EVIDENCE = ROOT / "output/verification/legacy-m12-all-fields-20260920/field-save-chain.jsonl"
META_SUMMARY = ROOT / "output/verification/legacy-m12-metadata-fields-20260920/summary.json"
META_EVIDENCE = ROOT / "output/verification/legacy-m12-metadata-fields-20260920/field-save-chain.jsonl"
IMPLEMENTATION = ROOT / "output/verification/m12-animation-compatibility.json"
DEFAULT_JSON = ROOT / "output/reports/m12-reference-field-coverage.json"
DEFAULT_MD = ROOT / "output/reports/m12-reference-field-coverage.md"


def load_json(path: Path) -> dict[str, object]:
    return json.loads(path.read_text(encoding="utf-8"))


def load_jsonl(path: Path) -> list[dict[str, object]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def first_tile_only(original: str, mutated: str) -> bool:
    before = original.split()
    after = mutated.split()
    return len(before) >= 3 and len(before) == len(after) and [i for i, pair in enumerate(zip(before, after)) if pair[0] != pair[1]] == [2]


def build() -> dict[str, object]:
    catalog = load_json(CATALOG)
    save_summary = load_json(SAVE_SUMMARY)
    meta_summary = load_json(META_SUMMARY)
    implementation = load_json(IMPLEMENTATION)
    save_records = load_jsonl(SAVE_EVIDENCE)
    meta_records = load_jsonl(META_EVIDENCE)
    records = {str(item["field_id"]): item for item in save_records + meta_records}
    catalog_ids = {str(item["field_id"]) for item in catalog["fields"]}
    if set(records) != catalog_ids:
        missing = sorted(catalog_ids - set(records))
        extra = sorted(set(records) - catalog_ids)
        raise AssertionError(f"M12 evidence/catalog mismatch missing={missing[:5]} extra={extra[:5]}")
    if not save_summary["passed"] or not meta_summary["passed"]:
        raise AssertionError("M12 save or metadata evidence is incomplete")
    if not implementation["passed"] or not implementation["checks"]["sprite_code_patch_is_golden_first_tile_only"]:
        raise AssertionError("M12 product first-tile safety gate is not passing")

    details = []
    for field in catalog["fields"]:
        field_id = str(field["field_id"])
        evidence = records[field_id]
        family = str(field["family"])
        if family == "sprite_code":
            if evidence["status"] != "reference_saved_product_blocked" or int(evidence["changed_bytes"]) != 1 or not first_tile_only(str(evidence["original"]), str(evidence["mutated"])):
                raise AssertionError(f"M12 sprite first-tile evidence is not isolated: {field_id}")
            classification = "safe_persistent"
            reason = "参考版逐行仅改首图块一字节并冷读成功；产品同一首图块补丁门禁通过。"
        elif evidence["status"] == "no_effect":
            classification = "no_effect"
            reason = "参考版保存/退出后未持久化；排除出安全分母。"
        else:
            classification = "reference_persistent_product_blocked"
            reason = "参考版可持久化，但产品只开放更窄的已验证参数或缺少精确调用映射，继续禁写。"
        details.append({
            "field_id": field_id,
            "family": family,
            "row": field["row"],
            "classification": classification,
            "reason": reason,
        })
    counts = Counter(item["classification"] for item in details)
    family_counts = Counter((item["family"], item["classification"]) for item in details)
    expected = {"safe_persistent": 198, "no_effect": 894, "reference_persistent_product_blocked": 189}
    checks = {
        "catalog_complete": catalog["passed"] and int(catalog["field_count"]) == 1281,
        "save_entries_complete": int(save_summary["completed"]) == 784 and int(save_summary["cold_process_logical_readback_passed"]) == 784,
        "metadata_entries_complete": int(meta_summary["completed"]) == 497 and int(meta_summary["cold_process_logical_readback_passed"]) == 497 and bool(meta_summary["rom_unchanged"]),
        "evidence_exactly_covers_catalog": len(records) == 1281,
        "classification_counts_match": dict(counts) == expected,
        "all_sprite_first_tile_fields_safe": family_counts[("sprite_code", "safe_persistent")] == 198,
        "all_names_and_preview_no_effect": sum(family_counts[(family, "no_effect")] for family in ("map_name", "movement_name", "sprite_name", "background_name", "sprite_preview_selector")) == 497,
        "all_xy_no_effect": family_counts[("sprite_x", "no_effect")] == 198 and family_counts[("sprite_y", "no_effect")] == 198,
    }
    return {
        "generated_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "module": "M12",
        "passed": all(checks.values()),
        "delivery_status": "reference_field_scope_complete_user_pending",
        "logical_fields": 1281,
        "safe_denominator_fields": 198,
        "classification_counts": dict(sorted(counts.items())),
        "checks": checks,
        "evidence": {
            "catalog": CATALOG.relative_to(ROOT).as_posix(),
            "save_summary": SAVE_SUMMARY.relative_to(ROOT).as_posix(),
            "metadata_summary": META_SUMMARY.relative_to(ROOT).as_posix(),
            "implementation_report": IMPLEMENTATION.relative_to(ROOT).as_posix(),
        },
        "limitations": [
            "114 个运行规律整段代码、32 个背景整段代码、24 个精神调用和 19 个地图武器调用虽可由参考版保存，但产品缺少同粒度安全证明，继续禁写。",
            "496 个名称只在当前参考窗口内变化，新进程全部恢复；产品工程名称属于增强功能，不计参考安全分母。",
            "X/Y、代码编辑动作输入和预览选择器均为 no-effect。",
        ],
        "fields": details,
    }


def markdown(report: dict[str, object]) -> str:
    counts = report["classification_counts"]
    return "\n".join([
        "# M12 参考版逐字段保存覆盖",
        "",
        f"- 逻辑入口：{report['logical_fields']}",
        f"- 安全分母：{report['safe_denominator_fields']}",
        f"- 安全持久字段：{counts['safe_persistent']}",
        f"- 参考持久但产品禁写：{counts['reference_persistent_product_blocked']}",
        f"- No-effect：{counts['no_effect']}",
        f"- 状态：`{report['delivery_status']}`",
        "",
        "安全分母仅包含 198 个组图首图块字段；其余持久字段继续服从产品的窄参数门禁，未因参考版可写而解禁。",
        "",
    ])


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--json", type=Path, default=DEFAULT_JSON)
    parser.add_argument("--markdown", type=Path, default=DEFAULT_MD)
    args = parser.parse_args()
    report = build()
    args.json.parent.mkdir(parents=True, exist_ok=True)
    args.json.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    args.markdown.write_text(markdown(report), encoding="utf-8")
    print(json.dumps({"passed": report["passed"], "logical_fields": report["logical_fields"], "safe_denominator_fields": report["safe_denominator_fields"], "classification_counts": report["classification_counts"]}, ensure_ascii=False))
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
