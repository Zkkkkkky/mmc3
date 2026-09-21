"""M00 黄金对照流水线核心库（阶段 A：统一差分器；阶段 B：存量适配与注册表）。

仅依赖 Python 标准库（禁止 pywinauto 等第三方依赖），提供：

- ``diff_roms``：全字节差分器（长度不等时抛 ``ValueError``）；
- ``classify_case``：归一化偏移剔除与预期偏移解释判定，语义对齐
  ``tools/audit_legacy_global_fields.py``（allowed = expected ∪ 归一化；
  本库在其上扩展 extra_allowed）；
- ``load_family_records``：把 5 个存量差分族 JSON 适配为统一 ``GoldenRecord``；
- ``derive_registry`` / ``write_registry``：从存量 JSON 与 ``cases/`` 快照
  自动派生并写出黄金对照字段注册表；
- ``find_unregistered_snapshots``：发现 cases/ 下未登记的孤儿快照目录。

关键口径：

- 归一化偏移（参考版保存时 ``C9 02`` → ``D8 47`` 的副作用，NEG-8）在差分
  判定前必须剔除（REQ-BEH-EX-001/002/003）。
- 双击公式三参数的第三镜像操作数（0x7FF03/0x7FF12/0x7FF1A）取自
  ``src/fc_editor/profiles.py`` 的 ``double_hit_operand_groups``
  （REQ-GLOB-001 三镜像同步）；审计 CASES 仅登记前两镜像，适配
  global-fields 双击字段时把第三镜像预填进 extra_allowed。
- passed 判定在“无未解释偏移”之上还要求必写偏移全部写入
  （``set(required_offsets) ⊆ set(changed)``，语义对齐
  ``audit_legacy_global_fields`` 的 ``target_offsets_changed`` 检查）；
  ``optional_offsets`` 承载同字段跨度内合理可不写的偏移
  （item-prices 价格高位字节），且 ``required ∪ optional == expected``。
- ``find_unregistered_snapshots`` / ``find_orphan_archives``：路径比较
  统一大小写不敏感（Windows 文件系统不区分大小写，注册表路径与实际
  目录名大小写可能不一致）。
"""

from __future__ import annotations

import hashlib
import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Sequence

SCHEMA_VERSION = 1

#: 在线单字段“复制→修改→保存→关闭→新进程重开”闭环的硬门禁。
#: 调用方可以要求更短预算用于测试，但不得用更大值放宽验收标准。
ONLINE_FIELD_BUDGET_SECONDS = 30.0

#: 参考版每次保存都会把以下 6 个偏移的文本 Token ``C9 02`` 归一化为
#: ``D8 47``。这是保存副作用而非功能行为（NEG-8），差分判定（G2）前必须剔除。
#: 语义来源：``tools/audit_legacy_global_fields.py`` 的
#: ``LEGACY_NORMALIZATION_OFFSETS``（REQ-BEH-EX-001/002）。
NORMALIZATION_OFFSETS: tuple[int, ...] = (
    0x4A101,
    0x4A102,
    0x4AE2A,
    0x4AE2B,
    0x79538,
    0x79539,
)

#: 双击公式三参数各自的第三镜像操作数（审计 CASES 仅登记前两镜像）。
#: 来源：``src/fc_editor/profiles.py`` 的 ``double_hit_operand_groups``
#: = ((0x78109, 0x7815A, 0x7FF03), (0x78127, 0x78178, 0x7FF12),
#:    (0x78138, 0x78189, 0x7FF1A))（REQ-GLOB-001：写入必须同步全部三镜像）。
DOUBLE_HIT_THIRD_MIRRORS: tuple[int, ...] = (0x7FF03, 0x7FF12, 0x7FF1A)

#: 需要预填第三镜像 extra_allowed 的双击公式字段名。
DOUBLE_HIT_FIELDS: frozenset[str] = frozenset(
    {
        "double_hit_attack_percent",
        "double_hit_defense_percent",
        "double_hit_bonus",
    }
)

#: 差分族 -> 归属模块（docs/需求拆分：M09=其他修改1、M10=其他修改2、M17=其他窗口）。
FAMILY_MODULES: dict[str, str] = {
    "global-fields": "M17",
    "initial-roster": "M17",
    "item-prices": "M10",
    "other1": "M09",
    "level-cap": "M09",
}

#: 差分族 -> 存量结果 JSON 文件名（位于 output/build/legacy-diff-audit/）。
FAMILY_RESULT_JSON: dict[str, str] = {
    "global-fields": "legacy-global-field-results.json",
    "initial-roster": "legacy-initial-roster-results.json",
    "item-prices": "legacy-item-price-results.json",
    "other1": "legacy-other1-results.json",
    "level-cap": "legacy-level-cap-result.json",
}

# New online cases are optional until the first live collection succeeds.
LIVE_RESULT_JSON = "legacy-live-results.json"

#: 差分族 -> cases/ 下的快照分组目录名。
FAMILY_CASE_GROUPS: dict[str, str] = {
    "global-fields": "legacy_globals",
    "initial-roster": "legacy_initial_roster",
    "item-prices": "legacy_item_prices",
    "other1": "legacy_other1",
    "level-cap": "legacy_level_cap",
}

#: 存量档案统一用例标识：单字段修改→确定→保存（写入场景）。
CASE_ID_WRITE: str = "write"

#: 仓库相对路径约定（不硬编码机器绝对路径）。
AUDIT_DIR_RELATIVE = Path("output") / "build" / "legacy-diff-audit"
GOLDEN_DIR_RELATIVE = AUDIT_DIR_RELATIVE / "golden"
GOLDEN_INDEX_RELATIVE = GOLDEN_DIR_RELATIVE / "index.json"
REGISTRY_RELATIVE = Path("tools") / "golden_pipeline" / "cases" / "field_registry.json"
REPORTS_DIR_RELATIVE = Path("output") / "reports"
COVERAGE_REPORT_JSON_RELATIVE = REPORTS_DIR_RELATIVE / "golden-coverage-report.json"
COVERAGE_REPORT_MD_RELATIVE = REPORTS_DIR_RELATIVE / "golden-coverage-report.md"


def default_repo_root() -> Path:
    """从本模块位置（tools/）推导仓库根目录。"""
    return Path(__file__).resolve().parents[1]


def _audit_relative(*parts: str) -> str:
    """拼接 output/build/legacy-diff-audit 下的仓库相对路径（POSIX 分隔）。"""
    return "/".join((AUDIT_DIR_RELATIVE.as_posix(), *parts))


# ---------------------------------------------------------------------------
# 差分器与判定
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class DiffEntry:
    """单处字节差异。"""

    offset: int
    before_value: int
    after_value: int


def diff_roms(before: bytes, after: bytes) -> list[DiffEntry]:
    """对两份 ROM 做全字节差分，返回全部差异（按偏移升序）。

    长度不等时先抛 ``ValueError``（存量审计脚本的 zip 差分会静默截断，
    本库为黄金对照流水线的严谨性改为显式报错）。
    """
    if len(before) != len(after):
        raise ValueError(
            f"ROM 长度不一致：before={len(before)} 字节，after={len(after)} 字节"
        )
    return [
        DiffEntry(offset=index, before_value=old, after_value=new)
        for index, (old, new) in enumerate(zip(before, after))
        if old != new
    ]


@dataclass(frozen=True)
class ClassifyResult:
    """差分判定结果。

    - ``target_changed``：预期偏移中实际发生变化的部分；
    - ``unexplained``：剔除归一化后仍不能被 expected ∪ extra_allowed
      解释的偏移（G2 判定的关键量）；
    - ``removed_normalization``：变化偏移 ∩ 归一化偏移集（被剔除项）。
    """

    target_changed: tuple[int, ...]
    unexplained: tuple[int, ...]
    removed_normalization: tuple[int, ...]


def classify_case(
    changed_offsets: Sequence[int],
    expected_offsets: Sequence[int],
    extra_allowed: Sequence[int] = (),
) -> ClassifyResult:
    """判定变化偏移集能否被预期偏移解释。

    语义对齐 ``audit_legacy_global_fields`` 的
    ``allowed = expected ∪ LEGACY_NORMALIZATION_OFFSETS``，并在其上扩展
    ``extra_allowed``（如双击公式第三镜像）。归一化偏移总是被允许且
    单独计入 ``removed_normalization``。
    """
    changed = set(changed_offsets)
    expected = set(expected_offsets)
    extra = set(extra_allowed)
    normalization = set(NORMALIZATION_OFFSETS)
    allowed = expected | extra | normalization
    return ClassifyResult(
        target_changed=tuple(sorted(expected & changed)),
        unexplained=tuple(sorted(changed - allowed)),
        removed_normalization=tuple(sorted(changed & normalization)),
    )


# ---------------------------------------------------------------------------
# 统一记录与存量适配器
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class GoldenRecord:
    """由存量差分族 JSON 适配出的统一黄金记录。

    ``expected_offsets`` 为存量口径的全部预期偏移；``required_offsets``
    为 passed 判定必须全部写入的子集，``optional_offsets`` 为同字段跨度
    内合理可不写的部分（如 item-prices 仅进位时变化的价格高位字节），
    满足 ``required ∪ optional == expected``、二者不相交。
    """

    family: str
    module: str
    field: str
    case_id: str
    case_kind: str
    requested_value: int | str | None
    original_value: int | str | None
    reopen_value: int | str | None
    expected_offsets: tuple[int, ...]
    extra_allowed: tuple[int, ...]
    required_offsets: tuple[int, ...]
    optional_offsets: tuple[int, ...]
    changed_offsets: tuple[int, ...]
    stored_diff_entries: tuple[DiffEntry, ...]
    stored_unexpected_offsets: tuple[int, ...]
    stored_after_sha256: str | None
    source_json: str
    snapshot_dir: str | None
    notes: tuple[str, ...]
    duration_seconds: float | None = None
    reopen_mode: str | None = None
    within_budget: bool | None = None
    stored_passed: bool | None = None


def _stored_diff_entries(
    raw_diffs: Sequence[dict[str, Any]],
) -> tuple[DiffEntry, ...]:
    return tuple(
        DiffEntry(
            offset=int(item["offset"]),
            before_value=int(item["before"]),
            after_value=int(item["after"]),
        )
        for item in raw_diffs
    )


def _make_record(
    *,
    family: str,
    field: str,
    case_kind: str,
    requested_value: int | None,
    original_value: int | None,
    reopen_value: int | None,
    expected_offsets: tuple[int, ...],
    raw_diffs: Sequence[dict[str, Any]],
    extra_allowed: tuple[int, ...] = (),
    required_offsets: tuple[int, ...] | None = None,
    optional_offsets: tuple[int, ...] = (),
    stored_unexpected_offsets: Sequence[int] = (),
    stored_after_sha256: str | None = None,
    snapshot_name: str | None = None,
    notes: tuple[str, ...] = (),
) -> GoldenRecord:
    """构造统一记录；``required_offsets`` 缺省取全部 ``expected_offsets``。"""
    entries = _stored_diff_entries(raw_diffs)
    group = FAMILY_CASE_GROUPS[family]
    if family == "level-cap":
        snapshot_dir: str | None = _audit_relative("cases", group)
    elif snapshot_name is None:
        snapshot_dir = None
    else:
        snapshot_dir = _audit_relative("cases", group, snapshot_name)
    return GoldenRecord(
        family=family,
        module=FAMILY_MODULES[family],
        field=field,
        case_id=CASE_ID_WRITE,
        case_kind=case_kind,
        requested_value=requested_value,
        original_value=original_value,
        reopen_value=reopen_value,
        expected_offsets=expected_offsets,
        extra_allowed=extra_allowed,
        required_offsets=(
            expected_offsets if required_offsets is None else required_offsets
        ),
        optional_offsets=optional_offsets,
        changed_offsets=tuple(sorted(entry.offset for entry in entries)),
        stored_diff_entries=entries,
        stored_unexpected_offsets=tuple(sorted(int(o) for o in stored_unexpected_offsets)),
        stored_after_sha256=stored_after_sha256,
        source_json=_audit_relative(FAMILY_RESULT_JSON[family]),
        snapshot_dir=snapshot_dir,
        notes=notes,
    )


def _adapt_global_fields(payload: list[dict[str, Any]]) -> list[GoldenRecord]:
    """legacy-global-field-results.json：组级列表，diffs/unexpected_offsets/sha256。"""
    records: list[GoldenRecord] = []
    for item in payload:
        case_name = str(item["case"])
        expected = tuple(int(offset) for offset in item.get("expected_offsets") or ())
        extra: tuple[int, ...] = ()
        notes: tuple[str, ...] = ()
        if case_name in DOUBLE_HIT_FIELDS:
            extra = DOUBLE_HIT_THIRD_MIRRORS
            mirrors = "/".join(f"0x{offset:X}" for offset in extra)
            notes = (
                "双击公式字段：审计 CASES 仅登记前两镜像，存量 JSON 的 "
                f"unexpected_offsets 即第三镜像；extra_allowed 预填 {mirrors}，"
                "来源 src/fc_editor/profiles.py 的 double_hit_operand_groups"
                "（REQ-GLOB-001 三镜像同步）",
            )
        records.append(
            _make_record(
                family="global-fields",
                field=case_name,
                case_kind="golden",
                requested_value=int(item["requested_new"]),
                original_value=int(item["displayed_before"]),
                reopen_value=int(item["displayed_after_reopen"]),
                expected_offsets=expected,
                extra_allowed=extra,
                raw_diffs=item["diffs"],
                stored_unexpected_offsets=item.get("unexpected_offsets") or (),
                stored_after_sha256=item.get("sha256"),
                snapshot_name=case_name,
                notes=notes,
            )
        )
    return records


def _adapt_initial_roster(payload: list[dict[str, Any]]) -> list[GoldenRecord]:
    """legacy-initial-roster-results.json：单偏移 target_offset 的 12 项阵容。"""
    records: list[GoldenRecord] = []
    for item in payload:
        case_name = str(item["case"])
        records.append(
            _make_record(
                family="initial-roster",
                field=case_name,
                case_kind="golden",
                requested_value=int(item["requested_new"]),
                original_value=int(item["displayed_before"]),
                reopen_value=int(item["displayed_after_reopen"]),
                expected_offsets=(int(item["target_offset"]),),
                raw_diffs=item["diffs"],
                snapshot_name=case_name,
            )
        )
    return records


def _adapt_item_prices(payload: list[dict[str, Any]]) -> list[GoldenRecord]:
    """legacy-item-price-results.json：item 序号 + 2 字节价格字段（UI=ROM×10）。"""
    records: list[GoldenRecord] = []
    for item in payload:
        number = int(item["item"])
        target = int(item["target_offset"])
        records.append(
            _make_record(
                family="item-prices",
                field=f"item_price_{number:02d}",
                case_kind="golden",
                requested_value=int(item["new_display"]),
                original_value=int(item["old_display"]),
                reopen_value=int(item["reopened_display"]),
                expected_offsets=(target, target + 1),
                raw_diffs=item["differences"],
                required_offsets=(target,),
                optional_offsets=(target + 1,),
                snapshot_name=f"item_{number:02d}",
                notes=(
                    f"道具 {number:02d} 价格为 0x{target:X} 起的 2 字节字段"
                    "（UI 显示值 = ROM 值×10），进位时高低字节均可变化；"
                    f"required_offsets=(0x{target:X},)（本次改值必写的低位字节），"
                    f"optional_offsets=(0x{target + 1:X},)（仅进位时变化的价格高位字节）"
                ),
            )
        )
    return records


def _adapt_other1(payload: list[dict[str, Any]]) -> list[GoldenRecord]:
    """legacy-other1-results.json：距离/经验表格边界用例（含 2 个发现型）。"""
    records: list[GoldenRecord] = []
    for item in payload:
        case_name = str(item["case"])
        expected_offset = int(item["expected_offset"])
        byte_width = int(item.get("byte_width", 1))
        reopen_matches = bool(item["reopen_matches"])
        if expected_offset:
            expected = tuple(
                range(expected_offset, expected_offset + max(byte_width, 1))
            )
        else:
            expected = ()
        discovery = expected_offset == 0 or not reopen_matches
        notes: tuple[str, ...] = ()
        if discovery:
            if expected_offset == 0 and not reopen_matches:
                reason = "存量 expected_offset=0（写入偏移未知）且重开读取值不等于请求值"
            elif expected_offset == 0:
                reason = "存量 expected_offset=0（写入偏移未知）"
            else:
                reason = "重开读取值不等于请求值"
            notes = (f"发现型用例：{reason}，需在线采集补证",)
        records.append(
            _make_record(
                family="other1",
                field=case_name,
                case_kind="discovery" if discovery else "golden",
                requested_value=int(item["requested_new"]),
                original_value=int(item["displayed_before"]),
                reopen_value=int(item["displayed_after_reopen"]),
                expected_offsets=expected,
                raw_diffs=item["diffs"],
                snapshot_name=case_name,
                notes=notes,
            )
        )
    return records


def _adapt_level_cap(payload: dict[str, Any]) -> list[GoldenRecord]:
    """legacy-level-cap-result.json：单 dict，3778 处联动重写的发现型用例。"""
    entries = _stored_diff_entries(payload["diffs"])
    notes = (
        "发现型用例：等级上限 60→61 触发成长曲线等联动重写"
        f"（{len(entries)} 处偏移），无单一预期偏移集，待在线采集拆解（D5 决策）",
    )
    return [
        _make_record(
            family="level-cap",
            field="level_cap",
            case_kind="discovery",
            requested_value=int(payload["requested_new"]),
            original_value=int(payload["displayed_before"]),
            reopen_value=int(payload["displayed_after_reopen"]),
            expected_offsets=(),
            raw_diffs=payload["diffs"],
            snapshot_name=None,
            notes=notes,
        )
    ]


FAMILY_ADAPTERS: dict[str, Callable[[Any], list[GoldenRecord]]] = {
    "global-fields": _adapt_global_fields,
    "initial-roster": _adapt_initial_roster,
    "item-prices": _adapt_item_prices,
    "other1": _adapt_other1,
    "level-cap": _adapt_level_cap,
}


def _adapt_live(payload: list[dict[str, Any]]) -> list[GoldenRecord]:
    """Adapt new-process cases into the same registry/archive contract."""
    records: list[GoldenRecord] = []
    for item in payload:
        before_path = Path(item["snapshots"]["before"]["path"])
        after_path = Path(item["snapshots"]["after"]["path"])
        if before_path.parent != after_path.parent:
            raise ValueError("Live before/after snapshots must share a case directory")
        expected = tuple(int(offset) for offset in item["expected_offsets"])
        required = tuple(int(offset) for offset in item["required_offsets"])
        optional = tuple(int(offset) for offset in item.get("optional_offsets", []))
        partitioned = (
            not (set(required) & set(optional))
            and set(required) | set(optional) == set(expected)
        )
        # 发现型在线用例允许在尚未识别真实写入偏移时以空口径入档；
        # 它只作为待审证据保留，不参与 golden 通过率。正式 golden 仍必须
        # 至少声明一个 required 偏移，避免空集合被误判为已验证。
        unknown_discovery = (
            item.get("case_kind") == "discovery"
            and not expected
            and not required
            and not optional
        )
        if not partitioned or (not required and not unknown_discovery):
            raise ValueError("Live required/optional offsets do not partition expected")
        entries = _stored_diff_entries(item["diffs"])
        records.append(
            GoldenRecord(
                family="live",
                module=str(item["module"]),
                field=str(item["field"]),
                case_id=str(item["case_id"]),
                case_kind=str(item["case_kind"]),
                requested_value=item["requested_value"],
                original_value=item["original_value"],
                reopen_value=item["reopen_value"],
                expected_offsets=expected,
                extra_allowed=tuple(int(offset) for offset in item.get("extra_allowed", [])),
                required_offsets=required,
                optional_offsets=optional,
                changed_offsets=tuple(sorted(entry.offset for entry in entries)),
                stored_diff_entries=entries,
                stored_unexpected_offsets=tuple(int(offset) for offset in item["unexpected_offsets"]),
                stored_after_sha256=item["snapshots"]["after"]["sha256"],
                source_json=_audit_relative(LIVE_RESULT_JSON),
                snapshot_dir=before_path.parent.as_posix(),
                notes=("在线单字段采集：保存后关闭进程，再以不同 PID 冷启动重开",),
                duration_seconds=float(item["duration_seconds"]),
                reopen_mode=str(item["reopen_mode"]),
                within_budget=bool(item["within_budget"]),
                stored_passed=bool(item["passed"]),
            )
        )
    return records


def load_family_records(repo_root: Path | None = None) -> list[GoldenRecord]:
    """Read five historical families and any new live cases, sorted stably."""
    repo = repo_root if repo_root is not None else default_repo_root()
    audit_dir = repo / AUDIT_DIR_RELATIVE
    records: list[GoldenRecord] = []
    for family in sorted(FAMILY_RESULT_JSON):
        result_path = audit_dir / FAMILY_RESULT_JSON[family]
        if not result_path.is_file():
            raise FileNotFoundError(f"存量差分结果 JSON 不存在：{result_path}")
        payload = json.loads(result_path.read_text(encoding="utf-8"))
        records.extend(FAMILY_ADAPTERS[family](payload))
    live_path = audit_dir / LIVE_RESULT_JSON
    if live_path.is_file():
        records.extend(_adapt_live(json.loads(live_path.read_text(encoding="utf-8"))))
    identities = [(record.module, record.field, record.case_id) for record in records]
    if len(set(identities)) != len(identities):
        raise ValueError("Duplicate module/field/case_id in golden records")
    records.sort(key=lambda record: (record.module, record.field, record.case_id))
    return records


# ---------------------------------------------------------------------------
# 注册表
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class RegistryEntry:
    """黄金对照字段注册表条目。

    ``required_offsets``/``optional_offsets`` 语义同 ``GoldenRecord``：
    passed 判定要求 required 全部写入，optional 为合理可不写的跨度偏移。
    """

    module: str
    field: str
    case_id: str
    case_kind: str
    source_json: str
    snapshot_before: str | None
    snapshot_after: str | None
    expected_offsets: tuple[int, ...]
    extra_allowed: tuple[int, ...]
    required_offsets: tuple[int, ...]
    optional_offsets: tuple[int, ...]
    notes: tuple[str, ...]


def derive_registry(repo_root: Path | None = None) -> list[RegistryEntry]:
    """从存量 JSON、在线用例和 cases/ 快照目录派生注册表条目。

    快照缺失（目录或文件不存在）的条目 snapshot_before/snapshot_after 记
    ``None``，由 archive 汇总显式报告，不静默。
    """
    repo = repo_root if repo_root is not None else default_repo_root()
    entries: list[RegistryEntry] = []
    for record in load_family_records(repo):
        snapshot_before: str | None = None
        snapshot_after: str | None = None
        if record.snapshot_dir:
            if (repo / record.snapshot_dir / "before.nes").is_file():
                snapshot_before = f"{record.snapshot_dir}/before.nes"
            if (repo / record.snapshot_dir / "after.nes").is_file():
                snapshot_after = f"{record.snapshot_dir}/after.nes"
        entries.append(
            RegistryEntry(
                module=record.module,
                field=record.field,
                case_id=record.case_id,
                case_kind=record.case_kind,
                source_json=record.source_json,
                snapshot_before=snapshot_before,
                snapshot_after=snapshot_after,
                expected_offsets=record.expected_offsets,
                extra_allowed=record.extra_allowed,
                required_offsets=record.required_offsets,
                optional_offsets=record.optional_offsets,
                notes=record.notes,
            )
        )
    entries.sort(key=lambda entry: (entry.module, entry.field, entry.case_id))
    return entries


def _registry_entry_payload(entry: RegistryEntry) -> dict[str, Any]:
    return {
        "module": entry.module,
        "field": entry.field,
        "case_id": entry.case_id,
        "case_kind": entry.case_kind,
        "source_json": entry.source_json,
        "snapshot_before": entry.snapshot_before,
        "snapshot_after": entry.snapshot_after,
        "expected_offsets": list(entry.expected_offsets),
        "required_offsets": list(entry.required_offsets),
        "optional_offsets": list(entry.optional_offsets),
        "extra_allowed": list(entry.extra_allowed),
        "notes": list(entry.notes),
    }


def write_registry(path: Path, entries: Sequence[RegistryEntry]) -> None:
    """把注册表写为稳定排序的 JSON（原子写入）。"""
    ordered = sorted(entries, key=lambda entry: (entry.module, entry.field, entry.case_id))
    payload: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "description": (
            "M00 黄金对照字段注册表：由 5 个存量差分审计 JSON 与 cases/ ROM "
            "快照自动派生（tools/golden_pipeline_core.py derive_registry）"
        ),
        "normalization_offsets": list(NORMALIZATION_OFFSETS),
        "normalization_semantics": (
            "参考版保存时 C9 02→D8 47 归一化副作用（NEG-8），差分判定前必须剔除"
        ),
        "required_optional_semantics": (
            "required_offsets：passed 判定要求全部写入的必写偏移"
            "（set(required) ⊆ set(changed)，对齐 audit_legacy_global_fields 的"
            " target_offsets_changed 检查）；optional_offsets：同字段跨度内"
            "合理可不写的偏移（如 item-prices 仅进位时变化的价格高位字节）；"
            "required ∪ optional == expected_offsets 且二者不相交"
        ),
        "families": {
            family: {
                "module": FAMILY_MODULES[family],
                "result_json": _audit_relative(FAMILY_RESULT_JSON[family]),
                "case_group": _audit_relative("cases", FAMILY_CASE_GROUPS[family]),
            }
            for family in sorted(FAMILY_RESULT_JSON)
        },
        "entries": [_registry_entry_payload(entry) for entry in ordered],
    }
    if any(entry.source_json.endswith(LIVE_RESULT_JSON) for entry in ordered):
        payload["families"]["live"] = {
            "module": "M01-M18",
            "result_json": _audit_relative(LIVE_RESULT_JSON),
            "case_group": _audit_relative("cases", "legacy_live"),
        }
    write_json_atomic(path, payload)


def find_unregistered_snapshots(
    repo_root: Path | None = None,
    entries: Sequence[RegistryEntry] | None = None,
) -> list[str]:
    """扫描 cases/ 下未被注册表引用的孤儿快照目录（仓库相对路径，稳定排序）。

    例如早期实验遗留的 cases/global_hit_threshold、cases/item_price_01，
    以及无 JSON 记录的 cases/legacy_other1/experience_level_98。
    """
    repo = repo_root if repo_root is not None else default_repo_root()
    if entries is None:
        entries = derive_registry(repo)
    cases_root = repo / AUDIT_DIR_RELATIVE / "cases"
    if not cases_root.is_dir():
        return []
    registered = {
        str(Path(entry.snapshot_before).parent.as_posix()).lower()
        for entry in entries
        if entry.snapshot_before
    }
    orphans: list[str] = []
    for before in sorted(cases_root.rglob("before.nes")):
        case_dir = before.parent
        relative_under_cases = case_dir.relative_to(cases_root)
        if relative_under_cases.parts and relative_under_cases.parts[0].lower() == "diagnostic":
            continue
        if not (case_dir / "after.nes").is_file():
            continue
        # A failed live attempt is deliberately retained as diagnostic evidence,
        # but it is not an unregistered golden case waiting to be archived.
        if (case_dir / "error.json").is_file():
            continue
        relative = case_dir.relative_to(repo).as_posix()
        if relative.lower() not in registered:
            orphans.append(relative)
    return orphans


def find_orphan_archives(
    golden_dir: Path,
    referenced_archives: "set[str] | frozenset[str]",
) -> list[str]:
    """扫描 golden/ 下未被注册条目引用的孤儿档案（稳定排序，仅报告不删除）。

    与 ``find_unregistered_snapshots`` 互补：前者发现注册表漏登记的快照
    目录，本函数发现 golden/ 目录下不再被注册表引用的旧档案
    （如字段改名/移除后的遗留），交由人工决定去留，与 verify 的
    missing 报告风格一致（显式输出、不自动删除）。
    """
    orphans: list[str] = []
    for path in sorted(golden_dir.glob("*.json")):
        if path.name == "index.json":
            continue
        if path.name not in referenced_archives:
            orphans.append(path.name)
    return orphans


# ---------------------------------------------------------------------------
# 通用 IO 工具
# ---------------------------------------------------------------------------


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def write_json_atomic(path: Path, payload: Any) -> None:
    """以原子写入方式落盘 JSON（UTF-8、LF、缩进 2），避免半写文件。"""
    path.parent.mkdir(parents=True, exist_ok=True)
    text = json.dumps(payload, ensure_ascii=False, indent=2) + "\n"
    temp = path.with_name(path.name + ".tmp")
    with temp.open("w", encoding="utf-8", newline="\n") as handle:
        handle.write(text)
    os.replace(temp, path)
