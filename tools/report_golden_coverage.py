"""M00 golden audit CLI: live collection, diff, archive, stats and verify.

子命令：

- ``diff``：独立差分器——输入 before/after ROM 与预期偏移集，输出四要素 JSON；
- ``archive``：遍历注册表，复算 cases/ 快照差分，写出黄金档案
  （``output/build/legacy-diff-audit/golden/<模块>-<字段>-<用例>.json``）
  与 ``golden/index.json``，并更新字段注册表
  （``tools/golden_pipeline/cases/field_registry.json``）；
- ``stats``：从档案索引与注册表生成 G1/G2 覆盖率统计报告
  （``output/reports/golden-coverage-report.json`` 与 ``.md``）；
- ``verify``：对 cases/ 快照复算差分并与存量 JSON 已存档结果比对，
  输出逐用例 pass/fail 汇总与总体退出码（0=全一致，1=有差异，2=有缺失）。
- ``collect``：按 JSON 操作配方驱动隔离参考 EXE，单字段保存后关闭进程，
  以新进程重开读取，再自动归档与统计。

离线子命令仅使用 Python 标准库；``collect`` 在线驱动需要开发依赖
``pywinauto``。仓库根路径由 ``Path(__file__).resolve().parent.parent``
派生，不硬编码绝对路径。
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path
from typing import Any, Sequence

try:
    from golden_pipeline_core import (
        AUDIT_DIR_RELATIVE,
        COVERAGE_REPORT_JSON_RELATIVE,
        COVERAGE_REPORT_MD_RELATIVE,
        GOLDEN_DIR_RELATIVE,
        GOLDEN_INDEX_RELATIVE,
        NORMALIZATION_OFFSETS,
        ONLINE_FIELD_BUDGET_SECONDS,
        REGISTRY_RELATIVE,
        SCHEMA_VERSION,
        classify_case,
        default_repo_root,
        derive_registry,
        diff_roms,
        find_orphan_archives,
        find_unregistered_snapshots,
        load_family_records,
        sha256_bytes,
        sha256_file,
        write_json_atomic,
        write_registry,
    )
except ImportError:  # 以包路径导入（仓库根目录把 tools 作为包引用时）
    from tools.golden_pipeline_core import (  # type: ignore
        AUDIT_DIR_RELATIVE,
        COVERAGE_REPORT_JSON_RELATIVE,
        COVERAGE_REPORT_MD_RELATIVE,
        GOLDEN_DIR_RELATIVE,
        GOLDEN_INDEX_RELATIVE,
        NORMALIZATION_OFFSETS,
        ONLINE_FIELD_BUDGET_SECONDS,
        REGISTRY_RELATIVE,
        SCHEMA_VERSION,
        classify_case,
        default_repo_root,
        derive_registry,
        diff_roms,
        find_orphan_archives,
        find_unregistered_snapshots,
        load_family_records,
        sha256_bytes,
        sha256_file,
        write_json_atomic,
        write_registry,
    )


# ---------------------------------------------------------------------------
# 通用工具
# ---------------------------------------------------------------------------

#: 偏移合理上限（含 16 字节 iNES 头的 768KB 扩容 ROM 尺寸，0xC0010）。
#: 超出该值的纯数字（无 0x 前缀）token 大概率是十进制/十六进制输入混淆，
#: CLI 解析时以 stderr 告警提示（不阻断）。
ROM_SIZE_LIMIT = 786448


def parse_offset_token(token: str) -> int:
    text = token.strip()
    if text.lower().startswith(("0x", "-0x")):
        return int(text, 16)
    return int(text, 10)


def parse_offsets(
    raw: str, *, warn_out_of_range: bool = False
) -> tuple[int, ...]:
    """解析逗号分隔的偏移串。

    ``warn_out_of_range=True``（CLI 场景）时，对无 0x 前缀且超出
    ``ROM_SIZE_LIMIT`` 的纯数字 token 输出 stderr 告警（不阻断解析）。
    """
    offsets: list[int] = []
    for token in raw.split(","):
        token = token.strip()
        if not token:
            continue
        value = parse_offset_token(token)
        if (
            warn_out_of_range
            and not token.lower().startswith(("0x", "-0x"))
            and value > ROM_SIZE_LIMIT
        ):
            print(
                f"警告：偏移 {token} 为纯数字且超出 ROM 尺寸上限"
                f"{ROM_SIZE_LIMIT}（0x{ROM_SIZE_LIMIT:X}），"
                "请确认不是十进制/十六进制输入混淆",
                file=sys.stderr,
            )
        offsets.append(value)
    return tuple(offsets)


def _diff_entry_payload(offset: int, before_value: int, after_value: int) -> dict[str, int]:
    return {"offset": offset, "before_value": before_value, "after_value": after_value}


# ---------------------------------------------------------------------------
# diff 子命令
# ---------------------------------------------------------------------------


def cmd_diff(args: argparse.Namespace) -> int:
    before_path = Path(args.before)
    after_path = Path(args.after)
    for label, path in (("before", before_path), ("after", after_path)):
        if not path.is_file():
            print(f"错误：{label} ROM 不存在：{path}", file=sys.stderr)
            return 2
    before_bytes = before_path.read_bytes()
    after_bytes = after_path.read_bytes()
    try:
        entries = diff_roms(before_bytes, after_bytes)
    except ValueError as error:
        print(f"错误：{error}", file=sys.stderr)
        return 2
    changed = tuple(item.offset for item in entries)
    try:
        expected = parse_offsets(args.expected, warn_out_of_range=True)
        extra_allowed = parse_offsets(args.extra_allowed, warn_out_of_range=True)
    except ValueError as error:
        print(f"错误：偏移解析失败：{error}", file=sys.stderr)
        return 2
    result = classify_case(changed, expected, extra_allowed)
    payload: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "command": "diff",
        "before": {
            "path": str(before_path),
            "sha256": sha256_bytes(before_bytes),
            "size": len(before_bytes),
        },
        "after": {
            "path": str(after_path),
            "sha256": sha256_bytes(after_bytes),
            "size": len(after_bytes),
        },
        # 黄金对照四要素（重开验证值需在线采集第 4 步，离线差分器记 null）
        "requested_value": args.requested,
        "changed_offsets": list(changed),
        "removed_normalization": list(result.removed_normalization),
        "reopen_value": None,
        "expected_offsets": list(expected),
        "extra_allowed": list(extra_allowed),
        "unexpected_offsets": list(result.unexplained),
        "target_changed": list(result.target_changed),
        "diff_entries": [
            _diff_entry_payload(item.offset, item.before_value, item.after_value)
            for item in entries
        ],
        "counts": {
            "changed": len(changed),
            "removed_normalization": len(result.removed_normalization),
            "unexpected": len(result.unexplained),
            "target_changed": len(result.target_changed),
        },
    }
    text = json.dumps(payload, ensure_ascii=False, indent=2) + "\n"
    if args.out:
        out_path = Path(args.out)
        # 只读边界（M00 §6 禁区 1）：references/ 全程只读，禁止写入。
        references_root = (default_repo_root() / "references").resolve()
        out_resolved = out_path.resolve()
        out_text = str(out_resolved).lower()
        refs_text = str(references_root).lower().rstrip("\\/")
        if out_text == refs_text or out_text.startswith(refs_text + os.sep.lower()):
            print(
                f"错误：--out 目标位于只读目录 references/ 之下：{out_path}",
                file=sys.stderr,
            )
            return 2
        write_json_atomic(out_path, payload)
        print(f"差分报告已写入：{out_path}")
    else:
        print(text, end="")
    print(
        f"差分完成：{len(changed)} 处变化，剔除归一化 "
        f"{len(result.removed_normalization)} 处，未被解释 {len(result.unexplained)} 处"
    )
    return 0


# ---------------------------------------------------------------------------
# archive 子命令
# ---------------------------------------------------------------------------


def cmd_collect(args: argparse.Namespace) -> int:
    try:
        from golden_pipeline_collect import CaseSpec, Win32LegacyDriver, collect_case
    except ImportError:
        from tools.golden_pipeline_collect import (  # type: ignore
            CaseSpec,
            Win32LegacyDriver,
            collect_case,
        )

    try:
        repo = default_repo_root()
        config_path = Path(args.case_config).resolve()
        spec = CaseSpec.from_payload(json.loads(config_path.read_text(encoding="utf-8")))
        audit = repo / AUDIT_DIR_RELATIVE
        baseline = Path(args.baseline).resolve() if args.baseline else audit / "audit.nes"
        executable = (
            Path(args.legacy_exe).resolve() if args.legacy_exe else audit / "SRW2_patched.exe"
        )
        case_dir, report = collect_case(
            repo,
            spec,
            baseline,
            executable,
            Win32LegacyDriver,
            budget_seconds=args.budget_seconds,
        )
    except (OSError, RuntimeError, ValueError, json.JSONDecodeError) as error:
        print(f"在线采集失败：{error}", file=sys.stderr)
        return 2
    print(
        f"在线采集完成：{spec.module}/{spec.field}/{spec.case_id} "
        f"PID {report['first_pid']}→{report['second_pid']}，"
        f"耗时 {report['duration_seconds']}s，passed={report['passed']}"
    )
    print(f"- 用例目录：{case_dir}")
    if not args.defer_archive and (cmd_archive(args) or cmd_stats(args)):
        return 2
    return 0 if report["passed"] else 1


def cmd_archive(args: argparse.Namespace) -> int:
    started = time.perf_counter()
    repo = default_repo_root()
    try:
        records = load_family_records(repo)
        entries = derive_registry(repo)
    except FileNotFoundError as error:
        print(f"错误：{error}", file=sys.stderr)
        return 2
    write_registry(repo / REGISTRY_RELATIVE, entries)

    record_by_key = {
        (record.module, record.field, record.case_id): record for record in records
    }
    golden_dir = repo / GOLDEN_DIR_RELATIVE
    golden_dir.mkdir(parents=True, exist_ok=True)
    fields_index: dict[str, dict[str, Any]] = {}
    missing: list[dict[str, Any]] = []
    mismatches: list[dict[str, Any]] = []

    for entry in entries:
        record = record_by_key[(entry.module, entry.field, entry.case_id)]
        label = f"{entry.module}/{entry.field}/{entry.case_id}"
        if not entry.snapshot_before or not entry.snapshot_after:
            missing.append({"case": label, "reason": "注册表未解析到快照路径"})
            continue
        before_path = repo / entry.snapshot_before
        after_path = repo / entry.snapshot_after
        if not before_path.is_file() or not after_path.is_file():
            missing.append(
                {
                    "case": label,
                    "reason": "快照文件缺失",
                    "before": entry.snapshot_before,
                    "after": entry.snapshot_after,
                }
            )
            continue
        before_bytes = before_path.read_bytes()
        after_bytes = after_path.read_bytes()
        try:
            diff = diff_roms(before_bytes, after_bytes)
        except ValueError as error:
            missing.append({"case": label, "reason": f"快照无法差分：{error}"})
            continue
        changed = tuple(item.offset for item in diff)
        result = classify_case(changed, entry.expected_offsets, entry.extra_allowed)
        required = entry.required_offsets
        required_missing = sorted(set(required) - set(changed))

        # 与存量 JSON 已存档差分的一致性预警（不阻断归档，由 verify 严格把关）
        if set(changed) != set(record.changed_offsets):
            mismatches.append(
                {
                    "case": label,
                    "recomputed_count": len(changed),
                    "stored_count": len(record.changed_offsets),
                    "only_in_recomputed": sorted(
                        set(changed) - set(record.changed_offsets)
                    ),
                    "only_in_stored": sorted(
                        set(record.changed_offsets) - set(changed)
                    ),
                }
            )

        reopen_matches_request: bool | None = None
        if record.reopen_value is not None and record.requested_value is not None:
            reopen_matches_request = record.reopen_value == record.requested_value
        passed: bool | None = None
        within_hard_budget = (
            record.duration_seconds is None
            or record.duration_seconds <= ONLINE_FIELD_BUDGET_SECONDS
        )
        if entry.case_kind == "golden":
            # Diff, mandatory bytes and saved-value reopen are all required.
            passed = (
                (not result.unexplained)
                and bool(required)
                and not required_missing
                and reopen_matches_request is True
                and record.within_budget is not False
                and within_hard_budget
                and record.stored_passed is not False
            )
        pending_reason: str | None = None
        if entry.case_kind == "discovery":
            pending_reason = (
                record.notes[0] if record.notes else "发现型用例，待在线采集补证"
            )
        elif passed is False:
            if reopen_matches_request is not True:
                pending_reason = "重开读取值不等于请求值，或缺少重开证据"
            elif record.within_budget is False or not within_hard_budget:
                pending_reason = "在线采集超出每字段 30 秒性能预算"
            elif record.stored_passed is False:
                pending_reason = "在线采集原始判定未通过"
            elif result.unexplained:
                pending_reason = f"存在 {len(result.unexplained)} 处未被解释的偏移"
            elif not required:
                pending_reason = "required_offsets 为空，无法判定"
            else:
                pending_reason = (
                    f"必写偏移未写入 {len(required_missing)} 处："
                    + ", ".join(f"0x{offset:X}" for offset in required_missing)
                )

        archive_name = f"{entry.module}-{entry.field}-{entry.case_id}.json"
        payload: dict[str, Any] = {
            "schema_version": SCHEMA_VERSION,
            "module": entry.module,
            "field": entry.field,
            "case_id": entry.case_id,
            "case_kind": entry.case_kind,
            # 黄金对照四要素（M00 第 4 节 / 主文档 13.5）
            "requested_value": record.requested_value,
            "changed_offsets": list(changed),
            "removed_normalization": list(result.removed_normalization),
            "reopen_value": record.reopen_value,
            # 判定与解释
            "original_value": record.original_value,
            "reopen_matches_request": reopen_matches_request,
            "reopen_mode": record.reopen_mode or "historical_result",
            "expected_offsets": list(entry.expected_offsets),
            "required_offsets": list(entry.required_offsets),
            "optional_offsets": list(entry.optional_offsets),
            "extra_allowed": list(entry.extra_allowed),
            "unexpected_offsets": list(result.unexplained),
            "target_changed": list(result.target_changed),
            # 针对必写偏移（required）的未写入集；非空则 golden 不得 passed。
            # optional 偏移（如 item-prices 价格高位字节）未写入不在此列。
            "expected_not_changed": required_missing,
            "passed": passed,
            "pending_reason": pending_reason,
            "notes": list(entry.notes),
            "provenance": {"source_json": record.source_json},
            "snapshots": {
                "before": {
                    "path": entry.snapshot_before,
                    "sha256": sha256_bytes(before_bytes),
                    "size": len(before_bytes),
                },
                "after": {
                    "path": entry.snapshot_after,
                    "sha256": sha256_bytes(after_bytes),
                    "size": len(after_bytes),
                },
            },
            "diff_entries": [
                _diff_entry_payload(item.offset, item.before_value, item.after_value)
                for item in diff
            ],
            # 原始四步闭环未计时（存量档案离线复算）；REQ-NFR-PERF-005 的
            # ≤30s/字段预算适用于在线采集闭环，不适用于本离线流程。
            "duration_seconds": record.duration_seconds,
            "budget_seconds": (
                ONLINE_FIELD_BUDGET_SECONDS
                if record.duration_seconds is not None
                else None
            ),
            "within_budget": (
                within_hard_budget if record.duration_seconds is not None else None
            ),
            "duration_note": (
                None if record.duration_seconds is not None else
                "存量档案离线复算：原始四步闭环未计时；"
                "REQ-NFR-PERF-005 的 ≤30s/字段预算适用于在线采集闭环"
            ),
        }
        write_json_atomic(golden_dir / archive_name, payload)

        index_key = f"{entry.module}/{entry.field}/{entry.case_id}"
        if index_key in fields_index:
            raise RuntimeError(f"索引键冲突：{index_key} 已存在")
        fields_index[index_key] = {
            "module": entry.module,
            "field": entry.field,
            "case_id": entry.case_id,
            "case_kind": entry.case_kind,
            "archive": archive_name,
            "sha256": sha256_file(golden_dir / archive_name),
            "passed": passed,
            "expected_known": bool(entry.expected_offsets),
            "required_offsets": list(entry.required_offsets),
            "optional_offsets": list(entry.optional_offsets),
            "unexpected_count": len(result.unexplained),
            "changed_count": len(changed),
            "removed_normalization_count": len(result.removed_normalization),
            "pending_reason": pending_reason,
        }

    unregistered = find_unregistered_snapshots(repo, entries)
    written_archives = {info["archive"] for info in fields_index.values()}
    orphan_archives = find_orphan_archives(golden_dir, written_archives)
    golden_count = sum(1 for entry in entries if entry.case_kind == "golden")
    discovery_count = sum(1 for entry in entries if entry.case_kind == "discovery")
    passed_golden = sum(
        1 for value in fields_index.values() if value["passed"] is True
    )
    failed_golden = sum(
        1 for value in fields_index.values() if value["passed"] is False
    )
    index_payload: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "archive_dir": GOLDEN_DIR_RELATIVE.as_posix(),
        "registry": REGISTRY_RELATIVE.as_posix(),
        "summary": {
            "total_cases": len(entries),
            "archived_cases": len(fields_index),
            "golden_cases": golden_count,
            "discovery_cases": discovery_count,
            "passed_golden_cases": passed_golden,
            "failed_golden_cases": failed_golden,
            "missing_snapshots": missing,
            "unregistered_snapshots": unregistered,
            "orphan_archives": orphan_archives,
            "stored_diff_mismatches": mismatches,
        },
        "fields": fields_index,
    }
    write_json_atomic(repo / GOLDEN_INDEX_RELATIVE, index_payload)

    elapsed = time.perf_counter() - started
    print(
        f"黄金档案归档完成：{len(fields_index)}/{len(entries)} 用例"
        f"（golden {golden_count}，discovery {discovery_count}），耗时 {elapsed:.2f}s"
    )
    print(f"- 通过 golden：{passed_golden}；未通过 golden：{failed_golden}")
    if missing:
        detail = "；".join(f"{item['case']}（{item['reason']}）" for item in missing)
        print(f"- 快照缺失：{len(missing)} -> {detail}")
    else:
        print("- 快照缺失：0")
    if unregistered:
        print(f"- 未登记快照目录：{len(unregistered)} -> {'；'.join(unregistered)}")
    else:
        print("- 未登记快照目录：0")
    if mismatches:
        detail = "；".join(item["case"] for item in mismatches)
        print(f"- 存量差分不一致预警：{len(mismatches)} -> {detail}")
    else:
        print("- 存量差分不一致预警：0")
    if orphan_archives:
        detail = "；".join(orphan_archives)
        print(
            f"- 孤儿档案（不被注册表引用，仅报告未删除）：{len(orphan_archives)}"
            f" -> {detail}"
        )
    else:
        print("- 孤儿档案（不被注册表引用）：0")
    print(
        f"- 档案目录：{GOLDEN_DIR_RELATIVE.as_posix()}"
        f"（{len(fields_index)} 个 JSON + index.json）"
    )
    print(f"- 注册表：{REGISTRY_RELATIVE.as_posix()}")
    return 0


# ---------------------------------------------------------------------------
# stats 子命令
# ---------------------------------------------------------------------------


def _format_ratio(numerator: int, denominator: int, value: float | None) -> str:
    if value is None:
        return "N/A"
    return f"{numerator}/{denominator} = {value:.2%}"


def cmd_stats(args: argparse.Namespace) -> int:
    repo = default_repo_root()
    index_path = repo / GOLDEN_INDEX_RELATIVE
    registry_path = repo / REGISTRY_RELATIVE
    if not index_path.is_file():
        print(
            f"错误：{GOLDEN_INDEX_RELATIVE.as_posix()} 不存在，请先运行 archive 子命令",
            file=sys.stderr,
        )
        return 2
    if not registry_path.is_file():
        print(
            f"错误：{REGISTRY_RELATIVE.as_posix()} 不存在，请先运行 archive 子命令",
            file=sys.stderr,
        )
        return 2
    index = None
    registry = None
    try:
        index = json.loads(index_path.read_text(encoding="utf-8"))
        registry = json.loads(registry_path.read_text(encoding="utf-8"))
    except FileNotFoundError as error:
        print(
            f"错误：读取档案索引或注册表失败（请先运行 archive 子命令）：{error}",
            file=sys.stderr,
        )
        return 2
    assert index is not None and registry is not None
    fields_index: dict[str, dict[str, Any]] = index.get("fields", {})
    registry_entries: list[dict[str, Any]] = registry.get("entries", [])

    registered = {(entry["module"], entry["field"]) for entry in registry_entries}
    cases_by_field: dict[tuple[str, str], list[dict[str, Any]]] = {}
    for info in fields_index.values():
        cases_by_field.setdefault((info["module"], info["field"]), []).append(info)
    passed_fields: set[tuple[str, str]] = set()
    for field_key, infos in cases_by_field.items():
        golden_cases = [info for info in infos if info.get("case_kind") == "golden"]
        if golden_cases and all(info.get("passed") is True for info in golden_cases):
            passed_fields.add(field_key)

    g1_numerator = len(passed_fields)
    g1_denominator = len(registered)
    g1_value = (g1_numerator / g1_denominator) if g1_denominator else None
    golden_cases = [
        info for info in fields_index.values() if info.get("case_kind") == "golden"
    ]
    g2_numerator = sum(
        1
        for info in golden_cases
        if info.get("expected_known") and info.get("unexpected_count", 0) == 0
    )
    g2_denominator = len(golden_cases)
    g2_value = (g2_numerator / g2_denominator) if g2_denominator else None

    pending_cases: list[dict[str, Any]] = []
    for info in sorted(
        fields_index.values(),
        key=lambda item: (item["module"], item["field"], item["case_id"]),
    ):
        if info.get("case_kind") == "discovery" or info.get("passed") is False:
            pending_cases.append(
                {
                    "module": info["module"],
                    "field": info["field"],
                    "case_id": info["case_id"],
                    "case_kind": info["case_kind"],
                    "reason": info.get("pending_reason") or "未通过 golden 判定",
                }
            )
    archived_fields = set(cases_by_field)
    for field_key in sorted(registered - archived_fields):
        pending_cases.append(
            {
                "module": field_key[0],
                "field": field_key[1],
                "case_id": "-",
                "case_kind": "unarchived",
                "reason": "已登记但未归档（快照缺失或差分失败）",
            }
        )

    field_details = [
        {
            "module": info["module"],
            "field": info["field"],
            "case_id": info["case_id"],
            "case_kind": info["case_kind"],
            "passed": info["passed"],
            "changed_count": info.get("changed_count"),
            "removed_normalization_count": info.get("removed_normalization_count"),
            "unexpected_count": info.get("unexpected_count"),
            "archive": info["archive"],
        }
        for info in sorted(
            fields_index.values(),
            key=lambda item: (item["module"], item["field"], item["case_id"]),
        )
    ]
    discovery_count = sum(
        1 for info in fields_index.values() if info.get("case_kind") == "discovery"
    )
    report: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "sources": {
            "index": GOLDEN_INDEX_RELATIVE.as_posix(),
            "registry": REGISTRY_RELATIVE.as_posix(),
        },
        "g1": {
            "definition": "已通过黄金对照的字段数 / 登记字段数",
            "numerator": g1_numerator,
            "denominator": g1_denominator,
            "value": round(g1_value, 4) if g1_value is not None else None,
            "denominator_scope": "registered_fields",
            "denominator_scope_note": (
                "当前分母为 field_registry.json 登记字段数；最终口径为参考版全部"
                "可编辑字段数（主文档第 4/5 章字段清单，M00 第 5 节统计职责），"
                "全量采集完成后需以全量字段数重算分母"
            ),
            "target": ">=95%",
        },
        "g2": {
            "definition": "unexplained 为空且 expected 已知的 golden 用例占比",
            "numerator": g2_numerator,
            "denominator": g2_denominator,
            "value": round(g2_value, 4) if g2_value is not None else None,
            "target": "=100%",
        },
        "counts": {
            "registered_fields": g1_denominator,
            "archived_fields": len(archived_fields),
            "archived_cases": len(fields_index),
            "golden_cases": g2_denominator,
            "discovery_cases": discovery_count,
            "passed_golden_cases": sum(
                1 for info in golden_cases if info.get("passed") is True
            ),
            "failed_golden_cases": sum(
                1 for info in golden_cases if info.get("passed") is False
            ),
            "pending_cases": len(pending_cases),
        },
        "pending_cases": pending_cases,
        "field_details": field_details,
    }
    write_json_atomic(repo / COVERAGE_REPORT_JSON_RELATIVE, report)
    md_path = repo / COVERAGE_REPORT_MD_RELATIVE
    md_path.parent.mkdir(parents=True, exist_ok=True)
    md_path.write_text(
        render_coverage_markdown(report), encoding="utf-8", newline="\n"
    )

    g1_text = _format_ratio(g1_numerator, g1_denominator, g1_value)
    g2_text = _format_ratio(g2_numerator, g2_denominator, g2_value)
    print(
        f"G1 黄金对照覆盖率：{g1_text}"
        "（分母口径 registered_fields；最终口径为主文档第 4/5 章全量字段数）"
    )
    print(f"G2 逐字段差分通过率：{g2_text}")
    print(
        f"用例计数：golden {g2_denominator}"
        f"（通过 {report['counts']['passed_golden_cases']}"
        f"/未通过 {report['counts']['failed_golden_cases']}），"
        f"discovery {discovery_count}，待解释 {len(pending_cases)}"
    )
    print(
        f"报告：{COVERAGE_REPORT_JSON_RELATIVE.as_posix()} / "
        f"{COVERAGE_REPORT_MD_RELATIVE.as_posix()}"
    )
    return 0


def render_coverage_markdown(report: dict[str, Any]) -> str:
    g1 = report["g1"]
    g2 = report["g2"]
    counts = report["counts"]
    lines: list[str] = []
    lines.append("# 黄金对照覆盖率报告（M00 / G1·G2）")
    lines.append("")
    lines.append(f"- 数据源：`{report['sources']['index']}`、`{report['sources']['registry']}`")
    lines.append(
        f"- 归一化剔除：{len(NORMALIZATION_OFFSETS)} 个偏移"
        "（参考版保存时 C9 02→D8 47 副作用，NEG-8）"
    )
    lines.append("")
    lines.append("## 汇总指标")
    lines.append("")
    lines.append("| 指标 | 数值 | 目标 |")
    lines.append("| --- | --- | --- |")
    lines.append(
        f"| G1 黄金对照覆盖率 | "
        f"{_format_ratio(g1['numerator'], g1['denominator'], g1['value'])} "
        f"| {g1['target']} |"
    )
    lines.append(
        f"| G2 逐字段差分通过率 | "
        f"{_format_ratio(g2['numerator'], g2['denominator'], g2['value'])} "
        f"| {g2['target']} |"
    )
    lines.append("")
    lines.append(f"> G1 分母口径 `denominator_scope={g1['denominator_scope']}`：{g1['denominator_scope_note']}")
    lines.append("")
    lines.append("## 用例计数")
    lines.append("")
    lines.append("| 类别 | 数量 |")
    lines.append("| --- | --- |")
    rows = (
        ("注册字段（登记用例）", counts["registered_fields"]),
        ("已归档字段", counts["archived_fields"]),
        ("golden 用例", counts["golden_cases"]),
        ("discovery 用例", counts["discovery_cases"]),
        ("通过 golden 用例", counts["passed_golden_cases"]),
        ("未通过 golden 用例", counts["failed_golden_cases"]),
        ("待解释用例", counts["pending_cases"]),
    )
    for label, value in rows:
        lines.append(f"| {label} | {value} |")
    lines.append("")
    lines.append("## 待解释用例清单")
    lines.append("")
    lines.append("| 模块 | 字段 | 用例 | 类型 | 原因 |")
    lines.append("| --- | --- | --- | --- | --- |")
    if report["pending_cases"]:
        for item in report["pending_cases"]:
            lines.append(
                f"| {item['module']} | {item['field']} | {item['case_id']} "
                f"| {item['case_kind']} | {item['reason']} |"
            )
    else:
        lines.append("| - | - | - | - | 无 |")
    lines.append("")
    lines.append("## 逐字段明细")
    lines.append("")
    lines.append("| 模块 | 字段 | 类型 | passed | 变化偏移 | 剔除归一化 | 未知偏移 | 档案 |")
    lines.append("| --- | --- | --- | --- | --- | --- | --- | --- |")
    for item in report["field_details"]:
        passed_text = "-" if item["passed"] is None else str(item["passed"]).lower()
        lines.append(
            f"| {item['module']} | {item['field']} | {item['case_kind']} "
            f"| {passed_text} | {item['changed_count']} "
            f"| {item['removed_normalization_count']} | {item['unexpected_count']} "
            f"| {item['archive']} |"
        )
    return "\n".join(lines) + "\n"


# ---------------------------------------------------------------------------
# verify 子命令
# ---------------------------------------------------------------------------


def cmd_verify(args: argparse.Namespace) -> int:
    repo = default_repo_root()
    try:
        records = load_family_records(repo)
    except FileNotFoundError as error:
        print(f"错误：{error}", file=sys.stderr)
        return 2
    pass_count = 0
    fail_count = 0
    missing_count = 0
    known_exception_cases: list[str] = []

    for record in records:
        label = f"{record.module}/{record.field}/{record.case_id}"
        if not record.snapshot_dir:
            missing_count += 1
            print(f"[MISS] {label} {record.case_kind}：无快照目录")
            continue
        before_path = repo / record.snapshot_dir / "before.nes"
        after_path = repo / record.snapshot_dir / "after.nes"
        if not before_path.is_file() or not after_path.is_file():
            missing_count += 1
            print(f"[MISS] {label} {record.case_kind}：快照文件缺失")
            continue
        before_bytes = before_path.read_bytes()
        after_bytes = after_path.read_bytes()
        try:
            recomputed = diff_roms(before_bytes, after_bytes)
        except ValueError as error:
            fail_count += 1
            print(f"[FAIL] {label} {record.case_kind}：{error}")
            continue

        recomputed_offsets = {item.offset for item in recomputed}
        stored_map = {
            item.offset: (item.before_value, item.after_value)
            for item in record.stored_diff_entries
        }
        stored_offsets = set(stored_map)
        offsets_equal = recomputed_offsets == stored_offsets
        values_equal = offsets_equal and all(
            stored_map.get(item.offset) == (item.before_value, item.after_value)
            for item in recomputed
        )
        after_sha = sha256_bytes(after_bytes)
        sha_ok = (
            record.stored_after_sha256 is None
            or record.stored_after_sha256 == after_sha
        )
        stored_unexpected = set(record.stored_unexpected_offsets)
        extra_allowed = set(record.extra_allowed)
        unexplained_in_stored = sorted(stored_unexpected - extra_allowed)

        notes: list[str] = []
        if record.stored_unexpected_offsets and not unexplained_in_stored:
            hexes = ", ".join(f"0x{offset:X}" for offset in sorted(stored_unexpected))
            notes.append(
                f"known-exception：存量 unexpected_offsets（{hexes}）为第三镜像口径，"
                "已由 extra_allowed（profiles.py double_hit_operand_groups）解释"
            )
            known_exception_cases.append(label)
        if record.case_kind == "discovery":
            notes.append("discovery：仅做数据一致性比对，不构成字段级通过依据")
        if not offsets_equal:
            notes.append(
                f"偏移集合不一致：复算 {len(recomputed_offsets)} 处 "
                f"vs 存档 {len(stored_offsets)} 处"
            )
        elif not values_equal:
            notes.append("偏移集合一致但字节值不一致")
        if not sha_ok:
            notes.append("after.nes sha256 与存量记录不一致")
        if unexplained_in_stored:
            hexes = ", ".join(f"0x{offset:X}" for offset in unexplained_in_stored)
            notes.append(f"存量 unexpected_offsets 含 extra_allowed 之外的偏移：{hexes}")

        ok = offsets_equal and values_equal and sha_ok and not unexplained_in_stored
        if ok:
            pass_count += 1
            suffix = f"（{'；'.join(notes)}）" if notes else ""
            print(
                f"[PASS] {label} {record.case_kind}："
                f"diffs={len(recomputed_offsets)}{suffix}"
            )
        else:
            fail_count += 1
            print(f"[FAIL] {label} {record.case_kind}：" + "；".join(notes))

    total = len(records)
    print()
    print(
        f"verify 汇总：{total} 用例，pass {pass_count}，fail {fail_count}，"
        f"missing {missing_count}，known-exception {len(known_exception_cases)}"
    )
    if known_exception_cases:
        print(f"known-exception 用例：{'；'.join(known_exception_cases)}")
    if missing_count:
        exit_code = 2
    elif fail_count:
        exit_code = 1
    else:
        exit_code = 0
    print("退出码判定：0=全一致，1=有差异，2=有缺失（缺失优先于差异）")
    print(f"总体退出码：{exit_code}")
    return exit_code


# ---------------------------------------------------------------------------
# 参数解析与入口
# ---------------------------------------------------------------------------


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="report_golden_coverage",
        description=(
            "M00 黄金对照流水线 CLI：在线采集 / 差分 / 归档 / G1·G2 统计 / 复算"
        ),
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    diff_parser = subparsers.add_parser(
        "diff",
        help="独立差分器：对两份 ROM 全字节差分并输出四要素 JSON",
    )
    diff_parser.add_argument("--before", required=True, help="修改前 ROM 路径")
    diff_parser.add_argument("--after", required=True, help="修改后 ROM 路径")
    diff_parser.add_argument(
        "--expected",
        default="",
        help="预期偏移集合，逗号分隔（支持 0x 前缀），如 0x78109,0x7815A",
    )
    diff_parser.add_argument(
        "--extra-allowed",
        default="",
        help="额外允许偏移集合，逗号分隔（如双击公式第三镜像）",
    )
    diff_parser.add_argument(
        "--requested",
        type=int,
        default=None,
        help="请求写入值（四要素之一，可留空记 null）",
    )
    diff_parser.add_argument(
        "--out",
        default=None,
        help="差分报告 JSON 输出路径（缺省打印到标准输出）",
    )
    diff_parser.set_defaults(handler=cmd_diff)

    archive_parser = subparsers.add_parser(
        "archive",
        help="遍历注册表，复算快照差分并归档黄金档案与索引",
    )
    archive_parser.set_defaults(handler=cmd_archive)

    stats_parser = subparsers.add_parser(
        "stats",
        help="从档案索引与注册表生成 G1/G2 覆盖率统计报告",
    )
    stats_parser.set_defaults(handler=cmd_stats)

    verify_parser = subparsers.add_parser(
        "verify",
        help="对 cases 快照复算差分并与存量 JSON 已存档结果比对",
    )
    verify_parser.set_defaults(handler=cmd_verify)

    collect_parser = subparsers.add_parser(
        "collect", help="隔离参考 EXE 单字段采集、保存、冷启动重开、归档和统计"
    )
    collect_parser.add_argument("--case-config", required=True, help="白名单操作步骤 JSON")
    collect_parser.add_argument("--baseline", help="基准 ROM；默认 output/build/legacy-diff-audit/audit.nes")
    collect_parser.add_argument("--legacy-exe", help="隔离参考 EXE；默认 output/build/legacy-diff-audit/SRW2_patched.exe")
    collect_parser.add_argument("--budget-seconds", type=float, default=30.0)
    collect_parser.add_argument(
        "--defer-archive",
        action="store_true",
        help="批量采集时仅写现场用例；由调用方在批次结束后统一 archive/stats",
    )
    collect_parser.set_defaults(handler=cmd_collect)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return int(args.handler(args))


if __name__ == "__main__":
    raise SystemExit(main())
