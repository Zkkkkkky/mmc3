"""Build an evidence-backed memory distribution report for the legacy editor.

The report is intentionally descriptive rather than authoritative: it records
which file offsets changed in archived before/after ROM pairs and groups nearby
offsets into observed write zones.  A zone is not automatically free space or
an allocation boundary.  Product code may only turn it into a relocatable pool
after pointer ownership, terminators, aliases and runtime readers are verified.
"""

from __future__ import annotations

import argparse
import json
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable


REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_CASES_ROOT = REPO_ROOT / "output/build/legacy-diff-audit/cases"
DEFAULT_GOLDEN_ROOT = REPO_ROOT / "output/build/legacy-diff-audit/golden"
DEFAULT_SCOPE_MATRIX = REPO_ROOT / "output/reports/reference-save-matrix.json"
DEFAULT_JSON = REPO_ROOT / "output/verification/legacy-memory-distribution.json"
DEFAULT_MARKDOWN = REPO_ROOT / "docs/research/legacy-modifier/旧修改器全模块内存分布.md"
DEFAULT_NORMALIZATION_OFFSETS = frozenset(
    (0x4A101, 0x4A102, 0x4AE2A, 0x4AE2B, 0x79538, 0x79539)
)
EXPECTED_MODULES = tuple(f"M{value:02d}" for value in range(1, 20))
SPECIALIZED_EVIDENCE = {
    "M03": ("output/reports/m03-reference-field-coverage.json",),
    "M04": ("output/reports/m04-reference-field-coverage.json",),
    "M11": ("output/reports/m11-reference-field-catalog.json",),
    "M12": ("output/reports/m12-reference-field-coverage.json",),
    "M14": ("output/reports/m14-reference-save-coverage.json",),
    "M16": ("output/reports/m16-reference-field-coverage.json",),
}


@dataclass(frozen=True)
class EvidenceCase:
    path: Path
    module: str
    field: str
    case_id: str
    passed: bool
    offsets: tuple[int, ...]
    required_offsets: tuple[int, ...] = ()
    optional_offsets: tuple[int, ...] = ()
    observed_changed_count: int | None = None


def group_offsets(offsets: Iterable[int], *, maximum_gap: int) -> tuple[tuple[int, int], ...]:
    """Return inclusive offset zones separated by more than ``maximum_gap``."""

    ordered = sorted(set(offsets))
    if not ordered:
        return ()
    result: list[tuple[int, int]] = []
    start = previous = ordered[0]
    for offset in ordered[1:]:
        if offset - previous > maximum_gap:
            result.append((start, previous))
            start = offset
        previous = offset
    result.append((start, previous))
    return tuple(result)


def bank_descriptor(offset: int) -> dict[str, int | str]:
    """Describe an iNES file offset using 8 KiB file-bank coordinates."""

    if offset < 16:
        return {"kind": "header", "file_offset": offset}
    relative = offset - 16
    bank = relative // 0x2000
    return {
        "kind": "8k_file_bank",
        "file_offset": offset,
        "bank": bank,
        "bank_hex": f"${bank:02X}",
        "bank_offset": relative % 0x2000,
    }


def _snapshot_path(case_path: Path, payload: dict, key: str) -> Path | None:
    snapshots = payload.get("snapshots")
    if isinstance(snapshots, dict):
        row = snapshots.get(key)
        if isinstance(row, dict) and isinstance(row.get("path"), str):
            candidate = REPO_ROOT / row["path"]
            if candidate.is_file():
                return candidate
    candidate = case_path.parent / f"{key}.nes"
    return candidate if candidate.is_file() else None


def _actual_offsets(case_path: Path, payload: dict) -> tuple[int, ...]:
    before_path = _snapshot_path(case_path, payload, "before")
    after_path = _snapshot_path(case_path, payload, "after")
    if before_path is not None and after_path is not None:
        before = before_path.read_bytes()
        after = after_path.read_bytes()
        if len(before) == len(after):
            return tuple(
                index
                for index, (left, right) in enumerate(zip(before, after))
                if left != right and index not in DEFAULT_NORMALIZATION_OFFSETS
            )
    return tuple(
        sorted(
            set(int(value) for value in payload.get("changed_offsets", ()))
            - DEFAULT_NORMALIZATION_OFFSETS
        )
    )


def _case_from_payload(path: Path, payload: dict) -> EvidenceCase | None:
    module = str(payload.get("module", "")).strip().upper()
    field = str(payload.get("field", "")).strip()
    case_id = str(payload.get("case_id", path.parent.name)).strip()
    if not module or not field:
        return None
    return EvidenceCase(
        path.relative_to(REPO_ROOT),
        module,
        field,
        case_id,
        bool(payload.get("passed", False)),
        _actual_offsets(path, payload),
        tuple(sorted(set(int(value) for value in payload.get("required_offsets", ())))),
        tuple(sorted(set(int(value) for value in payload.get("optional_offsets", ())))),
        len(payload.get("changed_offsets", ())),
    )


def load_cases(
    cases_root: Path,
    golden_root: Path = DEFAULT_GOLDEN_ROOT,
) -> tuple[EvidenceCase, ...]:
    """Load the reviewed golden archive first, then any unarchived live cases.

    The old implementation only walked ``cases/**/case.json``.  That silently
    omitted promoted/offline evidence and made the generated report lag behind
    the actual golden index.  A module/field/case id is unique; the reviewed
    archive wins when both copies exist.
    """

    keyed: dict[tuple[str, str, str], EvidenceCase] = {}
    index_path = golden_root / "index.json"
    try:
        index = json.loads(index_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        index = {}
    index_fields = index.get("fields", {}) if isinstance(index, dict) else {}
    if isinstance(index_fields, dict):
        for row in index_fields.values():
            if not isinstance(row, dict):
                continue
            module = str(row.get("module", "")).strip().upper()
            field = str(row.get("field", "")).strip()
            case_id = str(row.get("case_id", "")).strip()
            if not module or not field or not case_id:
                continue
            required = tuple(sorted(set(int(value) for value in row.get("required_offsets", ()))))
            optional = tuple(sorted(set(int(value) for value in row.get("optional_offsets", ()))))
            case = EvidenceCase(
                Path(str(row.get("archive", "index.json"))),
                module,
                field,
                case_id,
                bool(row.get("passed", False)),
                tuple(sorted(set((*required, *optional)))),
                required,
                optional,
                int(row.get("changed_count", 0)),
            )
            keyed[(module, field, case_id)] = case

    cases: list[EvidenceCase] = []
    # The index contains every archived golden and discovery case.  Walking the
    # live directory as well would parse several hundred very large diff arrays
    # just to rediscover the same keys.  Fall back to live cases only when an
    # index is unavailable (useful for an in-progress collector workspace).
    if not keyed:
        for path in sorted(cases_root.rglob("case.json")):
            try:
                payload = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, UnicodeDecodeError, json.JSONDecodeError):
                continue
            case = _case_from_payload(path, payload)
            if case is None:
                continue
            key = (case.module, case.field, case.case_id)
            keyed.setdefault(key, case)
    cases.extend(keyed.values())
    return tuple(sorted(cases, key=lambda row: (row.module, row.field, row.case_id)))


def load_scope_matrix(path: Path) -> dict[str, dict[str, object]]:
    if not path.is_file():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return {}
    rows = payload.get("modules", ())
    return {
        str(row.get("module", "")).upper(): row
        for row in rows
        if isinstance(row, dict) and row.get("module")
    }


def load_specialized_target_offsets() -> dict[str, dict[str, set[int]]]:
    """Load direct fixed-field offsets proven outside the compact golden index.

    M03/M04 were exhaustively collected as JSONL chains and M11 as a glyph
    catalog.  Keeping their direct addresses here prevents the historical
    golden archive format from making those completed modules look unmapped.
    Dynamic text/script pools (notably M14) stay referenced by their dedicated
    reports because a single edited record legitimately repacks many bytes.
    """

    result: dict[str, dict[str, set[int]]] = defaultdict(lambda: defaultdict(set))
    for module, name in (
        ("M03", "m03-reference-field-catalog.json"),
        ("M04", "m04-reference-field-catalog.json"),
    ):
        path = REPO_ROOT / "output/reports" / name
        if not path.is_file():
            continue
        payload = json.loads(path.read_text(encoding="utf-8"))
        for row in payload.get("fields", ()):
            if row.get("classification") != "persistent_candidate":
                continue
            family = str(row.get("family", row.get("field", "field")))
            result[module][family].add(int(row["file_offset"]))

    font_path = REPO_ROOT / "output/reports/m11-reference-field-catalog.json"
    if font_path.is_file():
        payload = json.loads(font_path.read_text(encoding="utf-8"))
        for row in payload.get("fields", ()):
            page = str(row.get("page", ""))
            if page not in {"B8", "B9", "C8"}:
                continue
            start = int(row["offset"])
            length = int(row.get("length", 18))
            result["M11"][f"glyph_page_{page}"].update(range(start, start + length))
    return {module: dict(fields) for module, fields in result.items()}


def _zone_payload(offsets: Iterable[int], maximum_gap: int) -> list[dict[str, object]]:
    result = []
    materialized = tuple(sorted(set(offsets)))
    for start, end in group_offsets(materialized, maximum_gap=maximum_gap):
        changed = sum(start <= value <= end for value in materialized)
        result.append(
            {
                "start": start,
                "start_hex": f"0x{start:X}",
                "end_inclusive": end,
                "end_inclusive_hex": f"0x{end:X}",
                "envelope_bytes": end - start + 1,
                "observed_changed_bytes": changed,
                "start_bank": bank_descriptor(start),
                "end_bank": bank_descriptor(end),
            }
        )
    return result


def build_report(
    cases: Iterable[EvidenceCase],
    *,
    maximum_gap: int = 16,
    scope_matrix: dict[str, dict[str, object]] | None = None,
) -> dict[str, object]:
    case_rows = tuple(cases)
    accepted_rows = tuple(case for case in case_rows if case.passed)
    grouped: dict[str, dict[str, list[EvidenceCase]]] = defaultdict(lambda: defaultdict(list))
    for case in accepted_rows:
        grouped[case.module][case.field].append(case)

    scopes = scope_matrix or {}
    specialized = load_specialized_target_offsets()
    modules: dict[str, object] = {}
    for module in EXPECTED_MODULES:
        fields: dict[str, object] = {}
        module_offsets: set[int] = set()
        module_direct_offsets: set[int] = set()
        module_shared_offsets: set[int] = set()
        module_case_count = 0
        module_passed_count = 0
        for field in sorted(grouped[module]):
            rows = grouped[module][field]
            offsets = {offset for row in rows for offset in row.offsets}
            direct_offsets = {
                offset
                for row in rows
                for offset in row.required_offsets
                if offset in offsets
            }
            shared_offsets = {
                offset
                for row in rows
                for offset in row.optional_offsets
                if offset in offsets and offset not in direct_offsets
            }
            observed_change_events = sum(
                row.observed_changed_count
                if row.observed_changed_count is not None
                else len(row.offsets)
                for row in rows
            )
            direct_change_events = sum(
                len(set(row.required_offsets) & set(row.offsets))
                for row in rows
            )
            shared_repack_events = sum(
                len((set(row.optional_offsets) - set(row.required_offsets)) & set(row.offsets))
                for row in rows
            )
            collateral_rewrite_events = max(
                0, observed_change_events - direct_change_events - shared_repack_events
            )
            collateral_offsets = offsets - direct_offsets - shared_offsets
            module_offsets.update(offsets)
            module_direct_offsets.update(direct_offsets)
            module_shared_offsets.update(shared_offsets)
            module_case_count += len(rows)
            module_passed_count += sum(row.passed for row in rows)
            fields[field] = {
                "case_count": len(rows),
                "passed_case_count": sum(row.passed for row in rows),
                "observed_changed_bytes": len(offsets),
                "direct_target_bytes": len(direct_offsets),
                "shared_repack_bytes": len(shared_offsets),
                "collateral_rewrite_bytes": len(collateral_offsets),
                "observed_change_events": observed_change_events,
                "shared_repack_events": shared_repack_events,
                "collateral_rewrite_events": collateral_rewrite_events,
                "direct_target_zones": _zone_payload(direct_offsets, maximum_gap),
                "shared_repack_zones": _zone_payload(shared_offsets, maximum_gap),
                "collateral_rewrite_zones": _zone_payload(collateral_offsets, maximum_gap),
                "write_zones": _zone_payload(offsets, maximum_gap),
                "cases": [
                    {
                        "case_id": row.case_id,
                        "passed": row.passed,
                        "changed_bytes": len(row.offsets),
                        "path": row.path.as_posix(),
                    }
                    for row in rows
                ],
            }
        scope = scopes.get(module, {})
        modules[module] = {
            "case_count": module_case_count,
            "passed_case_count": module_passed_count,
            "field_count": len(fields),
            "observed_changed_bytes": len(module_offsets),
            "direct_target_bytes": len(module_direct_offsets),
            "shared_repack_bytes": len(module_shared_offsets),
            "shared_repack_events": sum(
                int(detail["shared_repack_events"]) for detail in fields.values()
            ),
            "collateral_rewrite_bytes": sum(
                int(detail["collateral_rewrite_events"]) for detail in fields.values()
            ),
            "write_zones": _zone_payload(module_offsets, maximum_gap),
            "direct_target_zones": _zone_payload(module_direct_offsets, maximum_gap),
            "collateral_rewrite_zones": _zone_payload(
                module_offsets - module_direct_offsets, maximum_gap
            ),
            "scope_classification": scope.get("field_scope_classification", "product_extension" if module == "M19" else "unclassified"),
            "safe_field_denominator": int(scope.get("denominator_count", 0)),
            "known_families": list(scope.get("known_families", ())),
            "scope_note": scope.get(
                "field_scope_remaining",
                "产品增强模块：制作信息与出演名单并入地图动画，使用 Bank $3D 固定文字区。"
                if module == "M19"
                else "尚无字段范围说明。",
            ),
            "specialized_evidence": list(SPECIALIZED_EVIDENCE.get(module, ())),
            "specialized_direct_target_bytes": len(
                {offset for offsets in specialized.get(module, {}).values() for offset in offsets}
            ),
            "specialized_target_zones": {
                field: _zone_payload(offsets, maximum_gap)
                for field, offsets in specialized.get(module, {}).items()
            },
            "fields": fields,
        }

    observed = {module for module, rows in grouped.items() if rows}
    return {
        "schema_version": 2,
        "basis": "archived legacy-editor before/after ROM save pairs",
        "interpretation": (
            "direct_target_zones come from reviewed required/optional field offsets; "
            "collateral_rewrite_events count per-save legacy serializer changes and must not "
            "be copied as field ownership; target zones are not free space"
        ),
        "normalization_offsets_excluded": sorted(DEFAULT_NORMALIZATION_OFFSETS),
        "zone_merge_gap_bytes": maximum_gap,
        "scanned_case_count": len(case_rows),
        "case_count": len(accepted_rows),
        "rejected_or_pending_case_count": len(case_rows) - len(accepted_rows),
        "passed_case_count": len(accepted_rows),
        "modules_with_evidence": sorted(observed),
        "modules_without_archived_save_pairs": [
            module for module in EXPECTED_MODULES if module not in observed
        ],
        "modules": modules,
    }


def render_markdown(report: dict[str, object]) -> str:
    modules = report["modules"]
    assert isinstance(modules, dict)
    lines = [
        "# 旧修改器全模块 ROM 写入内存分布",
        "",
        "## 口径",
        "",
        "本表由旧修改器保存前后 ROM 快照自动复算。`写入区间` 是实际发生变化的证据包络，"
        "不是可直接占用的空闲区；只有继续确认指针表、结束码、别名、内部跳转和运行时读取方后，"
        "才能升级为新修改器的可重排资源池。已剔除六个已知保存归一化偏移。",
        "`直接目标` 来自已审核黄金用例的 required 偏移；optional 偏移单列为`共享重排`；"
        "其余变化才是旧版序列化器的`附带重写`。新版必须保留必要的共享重排，但不得为了仿旧复制附带重写。",
        "",
        f"- 已扫描用例：{report['scanned_case_count']}",
        f"- 纳入分布的通过用例：{report['case_count']}",
        f"- 排除的失败/待定用例：{report['rejected_or_pending_case_count']}",
        f"- 已有保存差分模块：{', '.join(report['modules_with_evidence']) or '无'}",
        "- 尚无归档保存对的模块："
        + (", ".join(report["modules_without_archived_save_pairs"]) or "无"),
        "",
        "## 模块总览",
        "",
        "| 模块 | 用例 | 字段 | 安全字段分母 | 直接目标（去重） | 共享重排（去重） | 附带重写事件 | 分类 |",
        "|---|---:|---:|---:|---:|---:|---:|---|",
    ]
    for module, row in modules.items():
        assert isinstance(row, dict)
        lines.append(
            f"| {module} | {row['case_count']} | {row['field_count']} | "
            f"{row['safe_field_denominator']} | "
            f"{row['direct_target_bytes'] + row['specialized_direct_target_bytes']} | "
            f"{row['shared_repack_bytes']} | "
            f"{row['collateral_rewrite_bytes']} | `{row['scope_classification']}` |"
        )

    lines.extend(("", "## 字段写入分布", ""))
    for module, row in modules.items():
        assert isinstance(row, dict)
        lines.extend(
            (
                f"### {module}",
                "",
                f"- 范围：{row['scope_note']}",
                "- 已知字段族：" + ("、".join(row["known_families"]) or "无 ROM 持久字段"),
                "",
                "| 字段 | 用例 | 直接目标（去重） | 共享重排事件 | 附带重写事件 | 总变化事件 | 目标区间 |",
                "|---|---:|---:|---:|---:|---:|---|",
            )
        )
        fields = row["fields"]
        assert isinstance(fields, dict)
        for field, detail in fields.items():
            assert isinstance(detail, dict)
            zones = detail["write_zones"]
            assert isinstance(zones, list)
            zone_text = "；".join(
                f"{zone['start_hex']}–{zone['end_inclusive_hex']}"
                f"（变 {zone['observed_changed_bytes']}/{zone['envelope_bytes']} B）"
                for zone in zones
            ) or "无变化"
            lines.append(
                f"| `{field}` | {detail['case_count']} | {detail['direct_target_bytes']} | "
                f"{detail['shared_repack_events']} | {detail['collateral_rewrite_events']} | "
                f"{detail['observed_change_events']} | "
                f"{zone_text} |"
            )
        specialized_zones = row["specialized_target_zones"]
        for field, zones in specialized_zones.items():
            zone_text = "；".join(
                f"{zone['start_hex']}–{zone['end_inclusive_hex']}"
                f"（{zone['observed_changed_bytes']} B）"
                for zone in zones
            ) or "无变化"
            changed = sum(int(zone["observed_changed_bytes"]) for zone in zones)
            lines.append(
                f"| `{field}`（专项全集） | — | {changed} | 0 | 0 | {changed} | {zone_text} |"
            )
        if row["specialized_evidence"]:
            lines.append("")
            lines.append(
                "专项证据：" + "、".join(f"`{path}`" for path in row["specialized_evidence"])
            )
        lines.append("")

    lines.extend(
        (
            "## 后续解锁规则",
            "",
            "1. 固定结构字段保持原位写入，不因为相邻字节看似空闲而搬移。",
            "2. 指针表与连续池必须用至少一次增长、一次缩短保存差分确认整体重排和池尾。",
            "3. 含内部跳转的脚本必须枚举所有入口和跳转目标，重定位后重新解析并运行验证。",
            "4. 共用指针必须保持别名；同一物理记录收到冲突草稿时原子拒绝。",
            "5. 未出现在归档保存对中的模块继续列入采集队列，不用推断地址解除门禁。",
            "",
        )
    )
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cases-root", type=Path, default=DEFAULT_CASES_ROOT)
    parser.add_argument("--golden-root", type=Path, default=DEFAULT_GOLDEN_ROOT)
    parser.add_argument("--scope-matrix", type=Path, default=DEFAULT_SCOPE_MATRIX)
    parser.add_argument("--json", type=Path, default=DEFAULT_JSON)
    parser.add_argument("--markdown", type=Path, default=DEFAULT_MARKDOWN)
    parser.add_argument("--zone-gap", type=int, default=16)
    args = parser.parse_args()
    if args.zone_gap < 0:
        parser.error("--zone-gap must be non-negative")
    report = build_report(
        load_cases(args.cases_root, args.golden_root),
        maximum_gap=args.zone_gap,
        scope_matrix=load_scope_matrix(args.scope_matrix),
    )
    args.json.parent.mkdir(parents=True, exist_ok=True)
    args.markdown.parent.mkdir(parents=True, exist_ok=True)
    args.json.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    args.markdown.write_text(render_markdown(report), encoding="utf-8")
    print(f"legacy memory distribution: {report['case_count']} cases")
    print(f"json: {args.json}")
    print(f"markdown: {args.markdown}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
