"""Summarize every documented reference save-comparison scenario.

M01--M18 own their collection checklists.  This report keeps those lists as
the planning source of truth and overlays the archived golden-field counts;
it intentionally does not equate a checklist scenario with one ROM field.
"""

from __future__ import annotations

import json
import re
from collections import Counter
from pathlib import Path
from typing import Any


SECTION_RE = re.compile(r"^## 5\. 黄金对照采集清单")
NEXT_SECTION_RE = re.compile(r"^## 6\.")
ROW_RE = re.compile(r"^\|\s*(\d+)\s*\|(.*)\|\s*$")


def _split_cells(row_tail: str) -> list[str]:
    return [cell.strip() for cell in row_tail.split("|")]


def checklist_rows(path: Path, module: str) -> list[dict[str, Any]]:
    in_section = False
    rows: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if SECTION_RE.match(line):
            in_section = True
            continue
        if in_section and NEXT_SECTION_RE.match(line):
            break
        if not in_section:
            continue
        match = ROW_RE.match(line)
        if not match:
            continue
        cells = _split_cells(match.group(2))
        if len(cells) < 2:
            continue
        rows.append(
            {
                "module": module,
                "scenario": int(match.group(1)),
                "target": cells[0],
                "reference_action": cells[1],
                "expected_diff": cells[2] if len(cells) > 2 else "",
                "notes": cells[3] if len(cells) > 3 else "",
                "source": path.as_posix(),
            }
        )
    return rows


def build_report(repo: Path) -> dict[str, Any]:
    docs_dir = repo / "docs" / "需求拆分"
    scenarios: list[dict[str, Any]] = []
    modules_with_docs: list[str] = []
    for number in range(1, 19):
        module = f"M{number:02d}"
        matches = sorted(docs_dir.glob(f"{module}_*.md"))
        if not matches:
            continue
        modules_with_docs.append(module)
        scenarios.extend(checklist_rows(matches[0], module))

    registry_path = repo / "tools" / "golden_pipeline" / "cases" / "field_registry.json"
    registry = json.loads(registry_path.read_text(encoding="utf-8"))
    registered_fields = {
        (entry["module"], entry["field"]) for entry in registry.get("entries", [])
    }
    registered_by_module = Counter(module for module, _field in registered_fields)
    configured_fields: set[tuple[str, str]] = set()
    configured_discovery_fields: set[tuple[str, str]] = set()
    cases_dir = registry_path.parent
    for config_path in sorted(cases_dir.glob("M*.json")):
        try:
            payload = json.loads(config_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        module = payload.get("module")
        field = payload.get("field")
        if isinstance(module, str) and isinstance(field, str):
            target = (
                configured_fields
                if payload.get("case_kind", "golden") == "golden"
                else configured_discovery_fields
            )
            target.add((module, field))
    configured_by_module = Counter(module for module, _field in configured_fields)
    configured_unarchived = configured_fields - registered_fields
    configured_unarchived_by_module = Counter(
        module for module, _field in configured_unarchived
    )

    coverage_path = repo / "output" / "reports" / "golden-coverage-report.json"
    passed_by_module: Counter[str] = Counter()
    if coverage_path.exists():
        coverage = json.loads(coverage_path.read_text(encoding="utf-8"))
        passed_fields = {
            (item["module"], item["field"])
            for item in coverage.get("field_details", [])
            if item.get("case_kind") == "golden" and item.get("passed") is True
        }
        passed_by_module.update(module for module, _field in passed_fields)

    scenario_counts = Counter(item["module"] for item in scenarios)
    scope_path = repo / "tools" / "golden_pipeline" / "reference_field_scope.json"
    scope_payload = json.loads(scope_path.read_text(encoding="utf-8"))
    scope_by_module = {
        item["module"]: item for item in scope_payload.get("modules", [])
    }
    modules = []
    for module in modules_with_docs:
        scope = scope_by_module.get(module)
        if scope is None:
            raise ValueError(f"reference field scope is missing {module}")
        modules.append(
            {
                "module": module,
                "documented_scenarios": scenario_counts[module],
                "configured_fields": configured_by_module[module],
                "configured_discovery_fields": sum(
                    1 for candidate_module, _field in configured_discovery_fields
                    if candidate_module == module
                ),
                "configured_unarchived_fields": configured_unarchived_by_module[module],
                "registered_fields": registered_by_module[module],
                "passed_golden_fields": passed_by_module[module],
                "has_registered_field": registered_by_module[module] > 0,
                "field_scope_classification": scope["classification"],
                "denominator_complete": bool(scope["denominator_complete"]),
                "denominator_count": scope["denominator_count"],
                "known_families": scope["known_families"],
                "field_scope_remaining": scope["remaining"],
            }
        )
    complete_scope_modules = [
        item for item in modules if item["denominator_complete"]
    ]
    final_denominator_ready = len(complete_scope_modules) == len(modules)
    return {
        "schema_version": 1,
        "scope_note": (
            "documented_scenarios 是采集动作总表，不等同于 G1 的可编辑字段分母；"
            "configured/registered/passed 指标仅描述历史黄金档案流水线；"
            "discovery 配方不属于待归档黄金字段，最终完整性以逐模块字段分母审计为准。"
        ),
        "counts": {
            "modules": len(modules),
            "documented_scenarios": len(scenarios),
            "configured_fields": len(configured_fields),
            "configured_discovery_fields": len(configured_discovery_fields),
            "configured_unarchived_fields": len(configured_unarchived),
            "registered_fields": len(registered_fields),
            "passed_golden_fields": sum(passed_by_module.values()),
            "modules_without_registered_fields": sum(
                1 for item in modules if not item["has_registered_field"]
            ),
            "field_scope_modules_complete": len(complete_scope_modules),
            "field_scope_modules_incomplete": len(modules) - len(complete_scope_modules),
            "known_final_denominator_fields": sum(
                int(item["denominator_count"] or 0) for item in complete_scope_modules
            ),
        },
        "final_denominator_ready": final_denominator_ready,
        "final_denominator_note": (
            "只有全部模块 denominator_complete=true 后，才允许把最终 G1 分母切换为字段全集；"
            "当前 registered_fields 覆盖率仅为临时登记表口径。"
        ),
        "modules": modules,
        "configured_unarchived": [
            {"module": module, "field": field}
            for module, field in sorted(configured_unarchived)
        ],
        "scenarios": scenarios,
    }


def render_markdown(report: dict[str, Any]) -> str:
    counts = report["counts"]
    lines = [
        "# 参考版逐字段保存对照总矩阵",
        "",
        f"- 模块：{counts['modules']}",
        f"- 文档化采集场景：{counts['documented_scenarios']}",
        f"- 已有采集配方字段：{counts['configured_fields']}",
        f"- 发现用配方（非黄金缺口）：{counts['configured_discovery_fields']}",
        f"- 配方已建但尚未归档：{counts['configured_unarchived_fields']}",
        f"- 已登记字段：{counts['registered_fields']}",
        f"- 已通过黄金字段：{counts['passed_golden_fields']}",
        f"- 尚无登记字段的模块：{counts['modules_without_registered_fields']}",
        f"- 字段分母审计完成模块：{counts['field_scope_modules_complete']}/{counts['modules']}",
        f"- 字段分母审计未完成模块：{counts['field_scope_modules_incomplete']}",
        f"- 已确定最终分母字段：{counts['known_final_denominator_fields']}",
        f"- 最终 G1 分母可用：{'是' if report['final_denominator_ready'] else '否'}",
        "",
        f"> {report['scope_note']}",
        f"> {report['final_denominator_note']}",
        "",
        "## 模块覆盖",
        "",
        "| 模块 | 采集场景 | 已有配方 | 发现用配方 | 配方待归档 | 已登记字段 | 已通过黄金字段 | 状态 |",
        "|---|---:|---:|---:|---:|---:|---:|---|",
    ]
    for item in report["modules"]:
        if item["configured_unarchived_fields"]:
            status = "配方待运行/归档"
        else:
            status = "已有黄金" if item["has_registered_field"] else "待建黄金"
        lines.append(
            f"| {item['module']} | {item['documented_scenarios']} | "
            f"{item['configured_fields']} | {item['configured_discovery_fields']} | "
            f"{item['configured_unarchived_fields']} | "
            f"{item['registered_fields']} | {item['passed_golden_fields']} | {status} |"
        )
    lines.extend(
        [
            "",
            "## 最终字段分母审计",
            "",
            "| 模块 | 分类 | 分母完成 | 已确定字段数 | 已知字段族 | 尚缺 |",
            "|---|---|---|---:|---|---|",
        ]
    )
    for item in report["modules"]:
        values = [
            item["module"],
            item["field_scope_classification"],
            "是" if item["denominator_complete"] else "否",
            "—" if item["denominator_count"] is None else str(item["denominator_count"]),
            "；".join(item["known_families"]),
            item["field_scope_remaining"],
        ]
        values = [value.replace("|", "\\|").replace("\n", " ") for value in values]
        lines.append("| " + " | ".join(values) + " |")
    lines.extend(
        [
            "",
            "## 配方已建但尚未归档的字段",
            "",
            "| 模块 | 字段 |",
            "|---|---|",
        ]
    )
    for item in report["configured_unarchived"]:
        lines.append(f"| {item['module']} | `{item['field']}` |")
    lines.extend(
        [
            "",
            "## 全部采集场景",
            "",
            "| 模块 | # | 采集对象 | 参考版操作 | 预期差分语义 | 备注 |",
            "|---|---:|---|---|---|---|",
        ]
    )
    for item in report["scenarios"]:
        values = [
            item["module"],
            str(item["scenario"]),
            item["target"],
            item["reference_action"],
            item["expected_diff"],
            item["notes"],
        ]
        values = [value.replace("|", "\\|").replace("\n", " ") for value in values]
        lines.append("| " + " | ".join(values) + " |")
    lines.append("")
    return "\n".join(lines)


def main() -> int:
    repo = Path(__file__).resolve().parents[1]
    report = build_report(repo)
    out_dir = repo / "output" / "reports"
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "reference-save-matrix.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    (out_dir / "reference-save-matrix.md").write_text(
        render_markdown(report), encoding="utf-8", newline="\n"
    )
    counts = report["counts"]
    print(
        f"reference save matrix: {counts['documented_scenarios']} scenarios, "
        f"{counts['configured_unarchived_fields']} configured fields pending, "
        f"{counts['passed_golden_fields']}/{counts['registered_fields']} "
        "registered fields passed, "
        f"field denominator reviewed {counts['field_scope_modules_complete']}/"
        f"{counts['modules']} "
        f"({'ready' if report['final_denominator_ready'] else 'not ready'})"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
