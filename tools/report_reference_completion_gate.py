"""Cross-check every module's field-scope claim against authoritative evidence."""

from __future__ import annotations

import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCOPE = ROOT / "tools/golden_pipeline/reference_field_scope.json"
MATRIX = ROOT / "output/reports/reference-save-matrix.json"
GOLDEN = ROOT / "output/reports/golden-coverage-report.json"
CONTROL_INVENTORY = ROOT / "output/reports/legacy-control-inventory.json"
PE_DIALOGS = ROOT / "output/reports/legacy-pe-dialogs.json"
JSON_OUT = ROOT / "output/reports/reference-completion-gate.json"
MD_OUT = ROOT / "output/reports/reference-completion-gate.md"

CUSTOM_EVIDENCE = {
    "M03": ("output/reports/m03-reference-field-coverage.json", ("counts", "safe_denominator_fields")),
    "M04": ("output/reports/m04-reference-field-coverage.json", ("counts", "safe_denominator_fields")),
    "M05": ("output/reports/m05-reference-control-catalog.json", ("counts", "golden_save_fields")),
    "M08": ("output/verification/legacy-m08-all-fields-20260920/summary.json", "saved_fields"),
    "M09": ("output/verification/legacy-m09-all-fields-20260920/summary.json", "saved_fields"),
    "M10": ("output/verification/legacy-m10-all-fields-20260920/summary.json", "saved_fields"),
    "M11": ("output/verification/legacy-m11-all-fields-20260920/summary.json", "safe_page_save_fields"),
    "M12": ("output/reports/m12-reference-field-coverage.json", "safe_denominator_fields"),
    "M14": ("output/reports/m14-reference-save-coverage.json", ("counts", "safe_denominator_fields")),
    "M16": ("output/reports/m16-reference-field-coverage.json", "safe_denominator_fields"),
}
GOLDEN_MODULES = {"M06", "M07", "M17"}
GOLDEN_EXCLUDED_FIELDS = {"M06": {"character_add_overflow"}}
ZERO_FIELD_MODULES = {"M01", "M02", "M13", "M15", "M18"}
EXPECTED_FINAL_SAFE_DENOMINATOR = 6885


def nested(payload: dict[str, object], key: str | tuple[str, str]) -> object:
    if isinstance(key, str):
        return payload.get(key)
    parent = payload.get(key[0])
    return parent.get(key[1]) if isinstance(parent, dict) else None


def build() -> dict[str, object]:
    scopes = json.loads(SCOPE.read_text(encoding="utf-8"))["modules"]
    matrix = json.loads(MATRIX.read_text(encoding="utf-8"))
    golden = json.loads(GOLDEN.read_text(encoding="utf-8"))
    inventory = json.loads(CONTROL_INVENTORY.read_text(encoding="utf-8"))
    dialogs = json.loads(PE_DIALOGS.read_text(encoding="utf-8"))
    passed_golden: dict[str, set[str]] = {}
    for item in golden["field_details"]:
        if item["case_kind"] == "golden" and item["passed"] is True:
            passed_golden.setdefault(str(item["module"]), set()).add(str(item["field"]))

    modules: list[dict[str, object]] = []
    for scope in scopes:
        module = str(scope["module"])
        scope_complete = bool(scope["denominator_complete"])
        denominator = scope["denominator_count"]
        evidence_path: str | None = None
        evidence_passed = False
        evidence_count: int | None = None
        evidence_reason = ""
        if module in ZERO_FIELD_MODULES:
            evidence_passed = scope_complete and denominator == 0
            evidence_count = 0
            evidence_reason = "module has no persistent reference fields or is explicitly excluded"
        elif module in GOLDEN_MODULES:
            evidence_count = len(
                passed_golden.get(module, set())
                - GOLDEN_EXCLUDED_FIELDS.get(module, set())
            )
            evidence_passed = scope_complete and evidence_count == denominator
            evidence_path = "output/reports/golden-coverage-report.json"
            evidence_reason = "unique passed golden fields"
        else:
            evidence_path, count_key = CUSTOM_EVIDENCE[module]
            path = ROOT / evidence_path
            if path.is_file():
                payload = json.loads(path.read_text(encoding="utf-8"))
                evidence_count_raw = nested(payload, count_key)
                evidence_count = int(evidence_count_raw) if evidence_count_raw is not None else None
                evidence_passed = bool(payload.get("passed")) and scope_complete and evidence_count == denominator
                evidence_reason = "custom exhaustive report"
            else:
                evidence_reason = "required exhaustive report is missing"
        modules.append(
            {
                "module": module,
                "scope_complete": scope_complete,
                "denominator_count": denominator,
                "evidence_path": evidence_path,
                "evidence_count": evidence_count,
                "evidence_passed": evidence_passed,
                "evidence_reason": evidence_reason,
                "classification": scope["classification"],
            }
        )

    all_scope_complete = all(bool(item["scope_complete"]) for item in modules)
    all_evidence_passed = all(bool(item["evidence_passed"]) for item in modules)
    matrix_ready = bool(matrix["final_denominator_ready"])
    safe_denominator_fields = sum(int(item["denominator_count"] or 0) for item in modules)
    checks = {
        "all_18_modules_present": len(modules) == 18 and len({item["module"] for item in modules}) == 18,
        "runtime_control_inventory_present": int(inventory["counts"]["unique_visible_interactive_signatures"]) >= 621,
        "pe_dialog_inventory_has_zero_failures": int(dialogs["counts"]["parse_failures"]) == 0,
        "all_module_scopes_complete": all_scope_complete,
        "all_scope_claims_have_matching_evidence": all_evidence_passed,
        "matrix_final_denominator_ready": matrix_ready,
        "matrix_and_scope_agree": matrix_ready == all_scope_complete,
        "final_safe_denominator_matches_reviewed_scope": (
            safe_denominator_fields == EXPECTED_FINAL_SAFE_DENOMINATOR
        ),
    }
    return {
        "schema_version": 1,
        "passed": all(checks.values()),
        "status": "complete" if all(checks.values()) else "incomplete",
        "counts": {
            "modules": len(modules),
            "scope_complete": sum(bool(item["scope_complete"]) for item in modules),
            "scope_incomplete": sum(not bool(item["scope_complete"]) for item in modules),
            "evidence_passed": sum(bool(item["evidence_passed"]) for item in modules),
            "safe_denominator_fields": safe_denominator_fields,
        },
        "checks": checks,
        "modules": modules,
    }


def markdown(report: dict[str, object]) -> str:
    counts = report["counts"]
    lines = [
        "# 参考版控件与逐字段保存最终门禁",
        "",
        f"- 状态：`{report['status']}`",
        f"- 范围封口：{counts['scope_complete']}/{counts['modules']}",
        f"- 证据通过：{counts['evidence_passed']}/{counts['modules']}",
        f"- 当前安全字段分母：{counts['safe_denominator_fields']}",
        f"- 封口目标安全字段分母：{EXPECTED_FINAL_SAFE_DENOMINATOR}",
        "",
        "| 模块 | 范围封口 | 安全分母 | 证据通过 | 证据 |",
        "|---|---|---:|---|---|",
    ]
    for item in report["modules"]:
        lines.append(
            f"| {item['module']} | {'是' if item['scope_complete'] else '否'} | "
            f"{item['denominator_count'] if item['denominator_count'] is not None else '-'} | "
            f"{'是' if item['evidence_passed'] else '否'} | {item['evidence_path'] or item['evidence_reason']} |"
        )
    lines.extend(("", "只有 18 个模块范围与证据同时通过时，本门禁才会标记 complete。", ""))
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
