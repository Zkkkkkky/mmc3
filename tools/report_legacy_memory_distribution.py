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
DEFAULT_JSON = REPO_ROOT / "output/verification/legacy-memory-distribution.json"
DEFAULT_MARKDOWN = REPO_ROOT / "docs/research/legacy-modifier/旧修改器全模块内存分布.md"
DEFAULT_NORMALIZATION_OFFSETS = frozenset(
    (0x4A101, 0x4A102, 0x4AE2A, 0x4AE2B, 0x79538, 0x79539)
)
EXPECTED_MODULES = tuple(f"M{value:02d}" for value in range(1, 19))


@dataclass(frozen=True)
class EvidenceCase:
    path: Path
    module: str
    field: str
    case_id: str
    passed: bool
    offsets: tuple[int, ...]


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


def load_cases(cases_root: Path) -> tuple[EvidenceCase, ...]:
    cases: list[EvidenceCase] = []
    for path in sorted(cases_root.rglob("case.json")):
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError):
            continue
        module = str(payload.get("module", "")).strip().upper()
        field = str(payload.get("field", "")).strip()
        case_id = str(payload.get("case_id", path.parent.name)).strip()
        if not module or not field:
            continue
        cases.append(
            EvidenceCase(
                path.relative_to(REPO_ROOT),
                module,
                field,
                case_id,
                bool(payload.get("passed", False)),
                _actual_offsets(path, payload),
            )
        )
    return tuple(cases)


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


def build_report(cases: Iterable[EvidenceCase], *, maximum_gap: int = 16) -> dict[str, object]:
    case_rows = tuple(cases)
    accepted_rows = tuple(case for case in case_rows if case.passed)
    grouped: dict[str, dict[str, list[EvidenceCase]]] = defaultdict(lambda: defaultdict(list))
    for case in accepted_rows:
        grouped[case.module][case.field].append(case)

    modules: dict[str, object] = {}
    for module in sorted(grouped):
        fields: dict[str, object] = {}
        module_offsets: set[int] = set()
        module_case_count = 0
        module_passed_count = 0
        for field in sorted(grouped[module]):
            rows = grouped[module][field]
            offsets = {offset for row in rows for offset in row.offsets}
            module_offsets.update(offsets)
            module_case_count += len(rows)
            module_passed_count += sum(row.passed for row in rows)
            fields[field] = {
                "case_count": len(rows),
                "passed_case_count": sum(row.passed for row in rows),
                "observed_changed_bytes": len(offsets),
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
        modules[module] = {
            "case_count": module_case_count,
            "passed_case_count": module_passed_count,
            "field_count": len(fields),
            "observed_changed_bytes": len(module_offsets),
            "write_zones": _zone_payload(module_offsets, maximum_gap),
            "fields": fields,
        }

    observed = set(modules)
    return {
        "schema_version": 1,
        "basis": "archived legacy-editor before/after ROM save pairs",
        "interpretation": (
            "write_zones are observed change envelopes, not proven allocation or free-space "
            "boundaries; relocation requires separate pointer/alias/runtime verification"
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
        "| 模块 | 用例 | 通过 | 字段 | 观察变化字节 | 写入区间数 |",
        "|---|---:|---:|---:|---:|---:|",
    ]
    for module, row in modules.items():
        assert isinstance(row, dict)
        lines.append(
            f"| {module} | {row['case_count']} | {row['passed_case_count']} | "
            f"{row['field_count']} | {row['observed_changed_bytes']} | {len(row['write_zones'])} |"
        )

    lines.extend(("", "## 字段写入分布", ""))
    for module, row in modules.items():
        assert isinstance(row, dict)
        lines.extend((f"### {module}", "", "| 字段 | 用例 | 通过 | 变化字节 | 写入区间 |", "|---|---:|---:|---:|---|"))
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
                f"| `{field}` | {detail['case_count']} | {detail['passed_case_count']} | "
                f"{detail['observed_changed_bytes']} | {zone_text} |"
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
    parser.add_argument("--json", type=Path, default=DEFAULT_JSON)
    parser.add_argument("--markdown", type=Path, default=DEFAULT_MARKDOWN)
    parser.add_argument("--zone-gap", type=int, default=16)
    args = parser.parse_args()
    if args.zone_gap < 0:
        parser.error("--zone-gap must be non-negative")
    report = build_report(load_cases(args.cases_root), maximum_gap=args.zone_gap)
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
