"""M00 黄金对照流水线核心库与产物的一致性测试（阶段 D / 任务 #3）。

仅依赖 Python 标准库（禁止 pywinauto 等第三方依赖，不触发 GUI）：

- 归一化常量与 ``tools/audit_legacy_global_fields.py`` 源码字面一致（文本解析，
  不 import 该脚本以免引入 pywinauto）；
- ``diff_roms`` 差分语义（单点差异、升序、长度不等抛 ``ValueError``）；
- ``classify_case`` 判定语义（预期内 / 归一化剔除 / extra_allowed 解释 /
  未知偏移进 unexplained）；
- passed 判定的必写偏移检查（``required ⊆ changed``，optional 合理可缺写）；
- 黄金档案四要素齐全性与注册表口径一致（产物缺失时跳过）；
- 档案命名合规与 ``golden/index.json`` 双向一致（产物缺失时跳过）；
- cases/ 快照复算与档案 JSON 一致（快照缺失时跳过）；
- G1/G2 覆盖率算术口径（golden 才计入分子、discovery 排除、
  ``denominator_scope`` 声明）——先用构造数据复算，再对真实报告复算；
- CLI 边界：diff --out 的 references/ 只读边界、偏移解析错误退出码 2、
  纯数字超限偏移告警、孤儿快照/档案检测；
- 双击公式第三镜像与 ``src/fc_editor/profiles.py`` 的
  ``double_hit_operand_groups`` 及注册表 ``extra_allowed`` 三方一致
  （profiles 包全链路纯标准库，可安全 import）。
"""

from __future__ import annotations

import contextlib
import io
import json
import re
import sys
import tempfile
import unittest
from pathlib import Path
from typing import Any
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
for import_root in (ROOT, SRC):
    if str(import_root) not in sys.path:
        sys.path.insert(0, str(import_root))

from tools import golden_pipeline_core as core  # noqa: E402
from tools import report_golden_coverage as cli  # noqa: E402
from fc_editor.profiles import (  # noqa: E402
    DC_EXPANDED_MMC3_LEGACY_PROFILE,
    MMC5_LEGACY_GLOBAL_DATA,
    MMC5_PROFILE,
)


#: 审计脚本与核心库共同声明的 6 个归一化偏移（C9 02 -> D8 47 保存副作用）。
EXPECTED_NORMALIZATION_OFFSETS = (
    0x4A101,
    0x4A102,
    0x4AE2A,
    0x4AE2B,
    0x79538,
    0x79539,
)

#: profiles.py 的双击公式三镜像操作数（审计 CASES 仅登记前两镜像）。
EXPECTED_DOUBLE_HIT_OPERAND_GROUPS = (
    (0x78109, 0x7815A, 0x7FF03),
    (0x78127, 0x78178, 0x7FF12),
    (0x78138, 0x78189, 0x7FF1A),
)

#: 黄金对照四要素（以 golden_pipeline_core / 档案实际字段名为准）。
FOUR_ELEMENTS = ("requested_value", "changed_offsets", "removed_normalization", "reopen_value")

AUDIT_SCRIPT = ROOT / "tools" / "audit_legacy_global_fields.py"
AUDIT_DIR = ROOT / core.AUDIT_DIR_RELATIVE
GOLDEN_DIR = ROOT / core.GOLDEN_DIR_RELATIVE
GOLDEN_INDEX = ROOT / core.GOLDEN_INDEX_RELATIVE
REGISTRY_PATH = ROOT / core.REGISTRY_RELATIVE
REPORT_JSON = ROOT / core.COVERAGE_REPORT_JSON_RELATIVE

GOLDEN_ARCHIVE_PATTERN = re.compile(r"^M\d{2}-[a-z0-9_]+-[a-z0-9_]+\.json$")

#: 四要素抽查样例：global-fields 3 例（含双击 1 例）+ item-prices 1 例。
SCHEMA_SAMPLES = (
    "M17-double_hit_attack_percent-write.json",
    "M17-hit_threshold-write.json",
    "M17-damage_strength_multiplier-write.json",
    "M10-item_price_01-write.json",
)

#: 与审计脚本 CASES / profiles.py 对齐的预期偏移口径（十进制存储于档案）。
EXPECTED_OFFSETS_BY_SAMPLE = {
    "M17-double_hit_attack_percent-write.json": [0x78109, 0x7815A],
    "M17-hit_threshold-write.json": [0xA44E],
    "M17-damage_strength_multiplier-write.json": [0x780E4],
}

#: verify 复算抽查：cases/legacy_globals 3 例（含双击 1 例）。
SNAPSHOT_SAMPLES = (
    "double_hit_attack_percent",
    "hit_threshold",
    "damage_strength_multiplier",
)
SNAPSHOT_ROOT = AUDIT_DIR / "cases" / "legacy_globals"

#: 当前快照中的 3 个 discovery 字段（M00 计划：G2 分母排除、G1 不计分子）。
EXPECTED_DISCOVERY_FIELDS = frozenset(
    {
        "M09/experience_level_2",
        "M09/experience_level_60",
        "M09/level_cap",
    }
)

DOUBLE_HIT_FIELD_NAMES = (
    "double_hit_attack_percent",
    "double_hit_defense_percent",
    "double_hit_bonus",
)

#: 双击字段 -> 审计 CASES 登记的前两镜像（ profiles.py 各组的 group[:2]）。
DOUBLE_HIT_FIRST_TWO_MIRRORS_BY_FIELD = {
    "double_hit_attack_percent": (0x78109, 0x7815A),
    "double_hit_defense_percent": (0x78127, 0x78178),
    "double_hit_bonus": (0x78138, 0x78189),
}

HAS_AUDIT_SCRIPT = AUDIT_SCRIPT.is_file()
HAS_GOLDEN = GOLDEN_DIR.is_dir() and GOLDEN_INDEX.is_file()
HAS_REGISTRY = REGISTRY_PATH.is_file()
HAS_REPORT = REPORT_JSON.is_file()
HAS_SCHEMA_SAMPLES = HAS_GOLDEN and all(
    (GOLDEN_DIR / name).is_file() for name in SCHEMA_SAMPLES
)
HAS_SNAPSHOT_SAMPLES = HAS_GOLDEN and all(
    (SNAPSHOT_ROOT / name / "before.nes").is_file()
    and (SNAPSHOT_ROOT / name / "after.nes").is_file()
    for name in SNAPSHOT_SAMPLES
)


def load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def make_index_entry(
    module: str,
    field: str,
    case_kind: str,
    expected_offsets: tuple[int, ...],
    changed_offsets: tuple[int, ...],
    extra_allowed: tuple[int, ...] = (),
    required_offsets: tuple[int, ...] | None = None,
    optional_offsets: tuple[int, ...] = (),
) -> dict[str, Any]:
    """按 ``cmd_archive`` 的判定逻辑由核心库复算单条 index 记录。

    口径（对齐 ``cmd_archive``）：golden 用例
    ``passed = (not unexplained) and bool(required)
    and set(required) ⊆ set(changed)``；discovery 用例不判定（``passed=None``）。
    ``required_offsets`` 缺省取全部 ``expected_offsets``，
    ``optional_offsets`` 承载同字段跨度内合理可不写的偏移。
    """
    result = core.classify_case(changed_offsets, expected_offsets, extra_allowed)
    required = expected_offsets if required_offsets is None else required_offsets
    required_missing = sorted(set(required) - set(changed_offsets))
    if case_kind == "golden":
        passed: bool | None = (
            (not result.unexplained)
            and bool(required)
            and not required_missing
        )
    else:
        passed = None
    return {
        "module": module,
        "field": field,
        "case_id": core.CASE_ID_WRITE,
        "case_kind": case_kind,
        "passed": passed,
        "expected_known": bool(expected_offsets),
        "required_offsets": list(required),
        "optional_offsets": list(optional_offsets),
        "unexpected_count": len(result.unexplained),
        "changed_count": len(set(changed_offsets)),
        "removed_normalization_count": len(result.removed_normalization),
    }


def recompute_coverage(
    fields_index: dict[str, dict[str, Any]],
    registry_entries: list[dict[str, Any]],
) -> tuple[int, int, int, int]:
    """复算 G1/G2 分子分母（口径与 ``report_golden_coverage.cmd_stats`` 一致）。

    - G1 分子：存在 golden 用例且其全部 golden 用例均通过的登记字段数
      （只看 golden 用例，同字段 discovery 用例的 ``passed=None`` 不拖累，
      与 ``cmd_stats`` 的判定逐字对齐）；分母：登记字段总数（discovery
      字段计入分母、绝不计入分子）；
    - G2 分子：expected 已知且 ``unexpected_count==0`` 的 golden 用例数；
      分母：全部 golden 用例数（discovery 用例排除）。
    """
    registered = {(entry["module"], entry["field"]) for entry in registry_entries}
    cases_by_field: dict[tuple[str, str], list[dict[str, Any]]] = {}
    for info in fields_index.values():
        cases_by_field.setdefault((info["module"], info["field"]), []).append(info)
    passed_fields: set[tuple[str, str]] = set()
    for field_key, infos in cases_by_field.items():
        golden_cases = [info for info in infos if info.get("case_kind") == "golden"]
        if golden_cases and all(info.get("passed") is True for info in golden_cases):
            passed_fields.add(field_key)
    golden_cases = [
        info for info in fields_index.values() if info.get("case_kind") == "golden"
    ]
    g2_numerator = sum(
        1
        for info in golden_cases
        if info.get("expected_known") and info.get("unexpected_count", 0) == 0
    )
    return len(passed_fields), len(registered), g2_numerator, len(golden_cases)


# ---------------------------------------------------------------------------
# 归一化常量一致性（文本解析，不 import 审计脚本）
# ---------------------------------------------------------------------------


class NormalizationConstantsTests(unittest.TestCase):
    def test_normalization_offsets_match_documented_values(self) -> None:
        self.assertEqual(
            core.NORMALIZATION_OFFSETS, EXPECTED_NORMALIZATION_OFFSETS
        )

    @unittest.skipIf(not HAS_AUDIT_SCRIPT, "审计脚本不存在，跳过文本对照")
    def test_normalization_offsets_match_audit_script_literal(self) -> None:
        """文本解析审计脚本的 ``LEGACY_NORMALIZATION_OFFSETS`` 字面元组。

        用源码文本对照而非 import，避免引入 pywinauto（无桌面环境可跑）。
        """
        source = AUDIT_SCRIPT.read_text(encoding="utf-8")
        match = re.search(
            r"LEGACY_NORMALIZATION_OFFSETS\s*=\s*\(([^)]*)\)", source
        )
        self.assertIsNotNone(
            match, "审计脚本中未找到 LEGACY_NORMALIZATION_OFFSETS 字面元组"
        )
        tokens = [token.strip() for token in match.group(1).split(",")]
        tokens = [token for token in tokens if token]
        self.assertEqual(len(tokens), 6)
        offsets = tuple(int(token, 16) for token in tokens)
        self.assertEqual(offsets, EXPECTED_NORMALIZATION_OFFSETS)
        self.assertEqual(offsets, core.NORMALIZATION_OFFSETS)

    def test_double_hit_third_mirrors_constant(self) -> None:
        self.assertEqual(
            core.DOUBLE_HIT_THIRD_MIRRORS, (0x7FF03, 0x7FF12, 0x7FF1A)
        )
        self.assertEqual(
            sorted(core.DOUBLE_HIT_THIRD_MIRRORS),
            list(core.DOUBLE_HIT_THIRD_MIRRORS),
        )

    def test_double_hit_fields_constant(self) -> None:
        self.assertEqual(
            core.DOUBLE_HIT_FIELDS, frozenset(DOUBLE_HIT_FIELD_NAMES)
        )


# ---------------------------------------------------------------------------
# diff_roms 差分语义
# ---------------------------------------------------------------------------


class DiffRomsTests(unittest.TestCase):
    def test_single_byte_change_is_reported(self) -> None:
        entries = core.diff_roms(b"\x00\x01\x02", b"\x00\x05\x02")
        self.assertEqual(len(entries), 1)
        self.assertEqual(entries[0].offset, 1)
        self.assertEqual(entries[0].before_value, 1)
        self.assertEqual(entries[0].after_value, 5)

    def test_identical_inputs_yield_no_diff(self) -> None:
        self.assertEqual(core.diff_roms(b"\x00\x01\x02", b"\x00\x01\x02"), [])

    def test_entries_are_sorted_by_offset(self) -> None:
        before = bytearray(16)
        after = bytearray(16)
        after[12] = 0xAA
        after[3] = 0xBB
        after[7] = 0xCC
        entries = core.diff_roms(bytes(before), bytes(after))
        self.assertEqual([entry.offset for entry in entries], [3, 7, 12])
        self.assertEqual(
            [(entry.before_value, entry.after_value) for entry in entries],
            [(0, 0xBB), (0, 0xCC), (0, 0xAA)],
        )

    def test_length_mismatch_raises_value_error(self) -> None:
        with self.assertRaises(ValueError):
            core.diff_roms(b"\x00", b"\x00\x01")
        with self.assertRaises(ValueError):
            core.diff_roms(b"\x00\x01\x02", b"\x00\x01")


# ---------------------------------------------------------------------------
# classify_case 判定语义
# ---------------------------------------------------------------------------


class ClassifyCaseTests(unittest.TestCase):
    def test_expected_change_is_fully_explained(self) -> None:
        result = core.classify_case((0x78109,), (0x78109, 0x7815A))
        self.assertEqual(result.target_changed, (0x78109,))
        self.assertEqual(result.unexplained, ())
        self.assertEqual(result.removed_normalization, ())

    def test_normalization_offsets_are_removed_not_unexplained(self) -> None:
        result = core.classify_case(
            (0x100, 0x4A101, 0x79539), (0x100,)
        )
        self.assertEqual(result.unexplained, ())
        self.assertEqual(result.removed_normalization, (0x4A101, 0x79539))
        self.assertEqual(result.target_changed, (0x100,))

    def test_normalization_only_side_effect_still_passes_golden(self) -> None:
        """预期偏移 + 归一化副作用：unexplained 为空即可通过 G2 判定。"""
        changed = (0x100, *core.NORMALIZATION_OFFSETS)
        result = core.classify_case(changed, (0x100,))
        self.assertEqual(result.unexplained, ())
        self.assertEqual(result.removed_normalization, core.NORMALIZATION_OFFSETS)
        self.assertTrue((not result.unexplained) and bool((0x100,)))

    def test_extra_allowed_explains_third_mirror(self) -> None:
        result = core.classify_case(
            (0x7FF03,), (), core.DOUBLE_HIT_THIRD_MIRRORS
        )
        self.assertEqual(result.unexplained, ())
        self.assertEqual(result.target_changed, ())
        self.assertEqual(result.removed_normalization, ())

    def test_unknown_offset_lands_in_unexplained(self) -> None:
        result = core.classify_case((0x100, 0x12345), (0x100,))
        self.assertEqual(result.unexplained, (0x12345,))
        self.assertEqual(result.target_changed, (0x100,))

    def test_double_hit_write_semantics(self) -> None:
        """双击写入：前两镜像 + 第三镜像 + 归一化副作用，无未知偏移。"""
        changed = (0x78109, 0x7815A, 0x7FF03, *core.NORMALIZATION_OFFSETS)
        result = core.classify_case(
            changed, (0x78109, 0x7815A), core.DOUBLE_HIT_THIRD_MIRRORS
        )
        self.assertEqual(result.unexplained, ())
        self.assertEqual(result.target_changed, (0x78109, 0x7815A))
        self.assertEqual(result.removed_normalization, core.NORMALIZATION_OFFSETS)


# ---------------------------------------------------------------------------
# 黄金档案四要素齐全性抽查（产物缺失时跳过）
# ---------------------------------------------------------------------------


@unittest.skipIf(not HAS_SCHEMA_SAMPLES, "黄金档案样例缺失，跳过四要素抽查")
class GoldenArchiveSchemaTests(unittest.TestCase):
    def test_four_elements_present_in_sample_archives(self) -> None:
        for name in SCHEMA_SAMPLES:
            with self.subTest(archive=name):
                payload = load_json(GOLDEN_DIR / name)
                self.assertEqual(payload["schema_version"], core.SCHEMA_VERSION)
                self.assertEqual(payload["case_kind"], "golden")
                for key in FOUR_ELEMENTS:
                    self.assertIn(key, payload, f"档案 {name} 缺少四要素 {key}")
                self.assertIsInstance(payload["requested_value"], int)
                self.assertIsInstance(payload["changed_offsets"], list)
                self.assertIsInstance(payload["removed_normalization"], list)
                self.assertIsInstance(payload["reopen_value"], int)
                self.assertIs(payload["reopen_matches_request"], True)
                self.assertTrue(payload["passed"])

    def test_sample_expected_offsets_match_audit_cases(self) -> None:
        """抽查档案的 expected_offsets 与审计 CASES / profiles 口径一致。"""
        for name, expected in EXPECTED_OFFSETS_BY_SAMPLE.items():
            with self.subTest(archive=name):
                payload = load_json(GOLDEN_DIR / name)
                self.assertEqual(payload["expected_offsets"], expected)
                self.assertEqual(
                    set(payload["target_changed"]),
                    set(payload["expected_offsets"])
                    & set(payload["changed_offsets"]),
                )

    def test_double_hit_archive_carries_third_mirror_extra_allowed(self) -> None:
        payload = load_json(GOLDEN_DIR / "M17-double_hit_attack_percent-write.json")
        self.assertEqual(
            payload["extra_allowed"], list(core.DOUBLE_HIT_THIRD_MIRRORS)
        )
        self.assertEqual(payload["unexpected_offsets"], [])
        # 第三镜像确实被参考版写入（REQ-GLOB-001 三镜像同步的实证）。
        self.assertIn(0x7FF03, payload["changed_offsets"])
        # 归一化偏移被单独剔除、不出现在 unexpected 中。
        self.assertEqual(
            set(payload["removed_normalization"]),
            set(payload["changed_offsets"]) & set(core.NORMALIZATION_OFFSETS),
        )

    @unittest.skipIf(not HAS_REGISTRY, "字段注册表缺失，跳过档案对照")
    def test_sample_archives_match_registry_entries(self) -> None:
        registry = load_json(REGISTRY_PATH)
        by_field = {
            (entry["module"], entry["field"]): entry
            for entry in registry["entries"]
        }
        for name in SCHEMA_SAMPLES:
            with self.subTest(archive=name):
                payload = load_json(GOLDEN_DIR / name)
                entry = by_field[(payload["module"], payload["field"])]
                self.assertEqual(
                    payload["expected_offsets"], entry["expected_offsets"]
                )
                self.assertEqual(
                    payload["required_offsets"], entry["required_offsets"]
                )
                self.assertEqual(
                    payload["optional_offsets"], entry["optional_offsets"]
                )
                self.assertEqual(
                    payload["extra_allowed"], entry["extra_allowed"]
                )
                self.assertEqual(payload["case_kind"], entry["case_kind"])
                self.assertEqual(payload["case_id"], entry["case_id"])
                self.assertEqual(
                    payload["snapshots"]["before"]["path"],
                    entry["snapshot_before"],
                )
                self.assertEqual(
                    payload["snapshots"]["after"]["path"],
                    entry["snapshot_after"],
                )

    @unittest.skipIf(
        not (GOLDEN_DIR / "M10-item_price_01-write.json").is_file(),
        "item_price_01 档案缺失，跳过 required/optional 划分抽查",
    )
    def test_item_price_archive_splits_required_optional(self) -> None:
        """item-prices 档案：价格高位字节归 optional，不进 expected_not_changed。"""
        payload = load_json(GOLDEN_DIR / "M10-item_price_01-write.json")
        target = 87843
        self.assertEqual(payload["expected_offsets"], [target, target + 1])
        self.assertEqual(payload["required_offsets"], [target])
        self.assertEqual(payload["optional_offsets"], [target + 1])
        # expected_not_changed 语义为针对 required 的未写入：
        # 高位字节归 optional 后不应再出现。
        self.assertEqual(payload["expected_not_changed"], [])
        self.assertIs(payload["passed"], True)

    def test_all_archive_pass_flags_match_recompute(self) -> None:
        """全量档案的 passed 标志必须与 make_index_entry 复算口径一致。"""
        archive_files = sorted(
            path.name for path in GOLDEN_DIR.glob("M*.json")
        )
        self.assertTrue(archive_files)
        for name in archive_files:
            with self.subTest(archive=name):
                payload = load_json(GOLDEN_DIR / name)
                entry = make_index_entry(
                    payload["module"],
                    payload["field"],
                    payload["case_kind"],
                    tuple(payload["expected_offsets"]),
                    tuple(payload["changed_offsets"]),
                    tuple(payload["extra_allowed"]),
                    required_offsets=tuple(payload["required_offsets"]),
                    optional_offsets=tuple(payload["optional_offsets"]),
                )
                self.assertIs(entry["passed"], payload["passed"])


# ---------------------------------------------------------------------------
# 档案命名合规与 index.json 双向一致（产物缺失时跳过）
# ---------------------------------------------------------------------------


@unittest.skipIf(not HAS_GOLDEN, "黄金档案目录或 index.json 缺失，跳过一致性检查")
class GoldenIndexConsistencyTests(unittest.TestCase):
    def test_archive_filenames_match_convention(self) -> None:
        archive_files = {
            path.name for path in GOLDEN_DIR.glob("*.json")
        } - {"index.json"}
        self.assertTrue(archive_files)
        for name in sorted(archive_files):
            with self.subTest(archive=name):
                self.assertRegex(name, GOLDEN_ARCHIVE_PATTERN)

    def test_index_entries_match_archive_files(self) -> None:
        index = load_json(GOLDEN_INDEX)
        fields = index["fields"]
        archive_files = {
            path.name for path in GOLDEN_DIR.glob("*.json")
        } - {"index.json"}
        referenced: dict[str, str] = {}
        for key, info in fields.items():
            with self.subTest(field=key):
                self.assertEqual(key, f"{info['module']}/{info['field']}")
                archive = info["archive"]
                # 无缺失：index 引用的档案必须存在。
                self.assertIn(archive, archive_files)
                # 无重复：同名档案不得被多条目引用。
                self.assertNotIn(archive, referenced)
                referenced[archive] = key
                # 命名由 module-field-case_id 拼接。
                self.assertEqual(
                    archive,
                    f"{info['module']}-{info['field']}-{info['case_id']}.json",
                )
        # 无孤儿：目录中每个档案都被 index 引用。
        self.assertEqual(set(referenced), archive_files)
        self.assertEqual(index["summary"]["archived_cases"], len(fields))
        self.assertEqual(
            index["summary"]["archived_cases"],
            index["summary"]["golden_cases"]
            + index["summary"]["discovery_cases"],
        )

    def test_index_summary_declares_orphan_archives(self) -> None:
        """index.summary 必须显式记录孤儿档案检测结果（不删除，仅报告）。"""
        index = load_json(GOLDEN_INDEX)
        self.assertIn("orphan_archives", index["summary"])
        self.assertEqual(index["summary"]["orphan_archives"], [])

    def test_index_required_optional_match_archives(self) -> None:
        """index 条目的 required/optional/pending_reason 与档案一致。"""
        index = load_json(GOLDEN_INDEX)
        for key, info in index["fields"].items():
            with self.subTest(field=key):
                payload = load_json(GOLDEN_DIR / info["archive"])
                self.assertEqual(
                    info["required_offsets"], payload["required_offsets"]
                )
                self.assertEqual(
                    info["optional_offsets"], payload["optional_offsets"]
                )
                self.assertEqual(info["pending_reason"], payload["pending_reason"])
                self.assertIs(info["passed"], payload["passed"])


# ---------------------------------------------------------------------------
# cases/ 快照复算一致性（verify 口径，快照缺失时跳过）
# ---------------------------------------------------------------------------


@unittest.skipIf(
    not HAS_SNAPSHOT_SAMPLES, "legacy_globals 快照样例缺失，跳过复算校验"
)
class SnapshotRecomputeTests(unittest.TestCase):
    def test_recomputed_diff_matches_archive(self) -> None:
        for name in SNAPSHOT_SAMPLES:
            with self.subTest(case=name):
                archive = load_json(GOLDEN_DIR / f"M17-{name}-write.json")
                before = (SNAPSHOT_ROOT / name / "before.nes").read_bytes()
                after = (SNAPSHOT_ROOT / name / "after.nes").read_bytes()
                entries = core.diff_roms(before, after)
                # 偏移集合与档案 changed_offsets 一致（verify 的核心断言）。
                self.assertEqual(
                    {entry.offset for entry in entries},
                    set(archive["changed_offsets"]),
                )
                # 字节值与档案 diff_entries 一致。
                self.assertEqual(
                    {
                        (entry.offset, entry.before_value, entry.after_value)
                        for entry in entries
                    },
                    {
                        (item["offset"], item["before_value"], item["after_value"])
                        for item in archive["diff_entries"]
                    },
                )
                # 快照哈希与档案记录一致。
                self.assertEqual(
                    core.sha256_bytes(after),
                    archive["snapshots"]["after"]["sha256"],
                )
                # 用档案口径复算 classify，判定字段必须与档案一致。
                result = core.classify_case(
                    [entry.offset for entry in entries],
                    archive["expected_offsets"],
                    archive["extra_allowed"],
                )
                self.assertEqual(
                    result.unexplained, tuple(archive["unexpected_offsets"])
                )
                self.assertEqual(
                    result.removed_normalization,
                    tuple(archive["removed_normalization"]),
                )

    def test_double_hit_third_mirror_written_and_explained(self) -> None:
        name = "double_hit_attack_percent"
        archive = load_json(GOLDEN_DIR / f"M17-{name}-write.json")
        before = (SNAPSHOT_ROOT / name / "before.nes").read_bytes()
        after = (SNAPSHOT_ROOT / name / "after.nes").read_bytes()
        changed = tuple(entry.offset for entry in core.diff_roms(before, after))
        result = core.classify_case(
            changed, archive["expected_offsets"], archive["extra_allowed"]
        )
        # 第三镜像 0x7FF03 实际被写入且被 extra_allowed 解释，不进 unexplained。
        self.assertIn(0x7FF03, changed)
        self.assertEqual(result.unexplained, ())
        self.assertIs(archive["passed"], True)
        # 前两镜像均被写入（审计 CASES 登记的 expected 偏移全部命中）。
        self.assertEqual(result.target_changed, (0x78109, 0x7815A))


# ---------------------------------------------------------------------------
# G1/G2 覆盖率算术口径（构造数据，无需产物）
# ---------------------------------------------------------------------------


class CoverageArithmeticTests(unittest.TestCase):
    def test_g1_g2_semantics_on_constructed_cases(self) -> None:
        """构造 3 字段复算：golden 通过 / golden 失败 / discovery。

        - G1：分子 1（仅 alpha），分母 3（discovery 字段计入分母但不计分子）；
        - G2：分子 1，分母 2（discovery 用例被完全排除）。
        """
        alpha = make_index_entry(
            "M99", "alpha", "golden", (0x100,), (0x100,)
        )
        beta = make_index_entry(
            "M99", "beta", "golden", (0x200,), (0x200, 0x99999)
        )
        gamma = make_index_entry(
            "M99", "gamma", "discovery", (), (0x300,)
        )
        self.assertIs(alpha["passed"], True)
        self.assertIs(beta["passed"], False)
        self.assertIsNone(gamma["passed"])
        self.assertEqual(beta["unexpected_count"], 1)
        self.assertFalse(gamma["expected_known"])

        fields_index = {
            "M99/alpha": alpha,
            "M99/beta": beta,
            "M99/gamma": gamma,
        }
        registry_entries = [
            {"module": "M99", "field": name}
            for name in ("alpha", "beta", "gamma")
        ]
        g1_num, g1_den, g2_num, g2_den = recompute_coverage(
            fields_index, registry_entries
        )
        self.assertEqual((g1_num, g1_den), (1, 3))
        self.assertEqual((g2_num, g2_den), (1, 2))

    def test_multi_case_field_requires_all_golden_cases_pass(self) -> None:
        """同字段多个 golden 用例：任一用例未通过则字段不计入 G1 分子。"""
        first = make_index_entry(
            "M98", "field_x", "golden", (0x100,), (0x100,)
        )
        second = make_index_entry(
            "M98", "field_x", "golden", (0x200,), (0x200, 0xABCDEF)
        )
        third = make_index_entry(
            "M98", "field_y", "golden", (0x300,), (0x300,)
        )
        fields_index = {
            "M98/field_x/write#1": first,
            "M98/field_x/write#2": second,
            "M98/field_y/write": third,
        }
        registry_entries = [
            {"module": "M98", "field": "field_x"},
            {"module": "M98", "field": "field_y"},
        ]
        g1_num, g1_den, g2_num, g2_den = recompute_coverage(
            fields_index, registry_entries
        )
        self.assertEqual((g1_num, g1_den), (1, 2))
        self.assertEqual((g2_num, g2_den), (2, 3))

    def test_mixed_golden_pass_and_discovery_counts_in_g1(self) -> None:
        """同一字段混合 golden(passed=True)+discovery 用例时计入 G1 分子。

        锁定 ``cmd_stats`` 口径：G1 分子只看该字段的 golden 用例是否全部
        通过；discovery 用例的 ``passed=None`` 不得拖累同字段 golden 的
        通过判定（修复前测试辅助函数的旧口径会把 discovery 的 None
        误当未通过）。G2 分母只含 golden 用例，discovery 完全排除。
        """
        golden_ok = make_index_entry(
            "M97", "field_m", "golden", (0x100,), (0x100,)
        )
        discovery = make_index_entry(
            "M97", "field_m", "discovery", (), (0x300,)
        )
        only_discovery = make_index_entry(
            "M97", "field_n", "discovery", (), (0x400,)
        )
        fields_index = {
            "M97/field_m/write": golden_ok,
            "M97/field_m/discover": discovery,
            "M97/field_n/write": only_discovery,
        }
        registry_entries = [
            {"module": "M97", "field": "field_m"},
            {"module": "M97", "field": "field_n"},
        ]
        g1_num, g1_den, g2_num, g2_den = recompute_coverage(
            fields_index, registry_entries
        )
        # field_m：golden 通过即计入分子；field_n：无 golden 用例不计入。
        self.assertEqual((g1_num, g1_den), (1, 2))
        # G2 分母只含 golden 用例（discovery 排除）。
        self.assertEqual((g2_num, g2_den), (1, 1))

    def test_constructed_double_hit_case_counts_as_golden_pass(self) -> None:
        """双击字段（expected 前两镜像 + extra 第三镜像）通过 golden 判定。"""
        entry = make_index_entry(
            "M17",
            "double_hit_attack_percent",
            "golden",
            (0x78109, 0x7815A),
            (0x78109, 0x7815A, 0x7FF03, *core.NORMALIZATION_OFFSETS),
            core.DOUBLE_HIT_THIRD_MIRRORS,
        )
        self.assertIs(entry["passed"], True)
        self.assertEqual(entry["unexpected_count"], 0)
        self.assertEqual(entry["expected_known"], True)
        self.assertEqual(entry["removed_normalization_count"], 6)


# ---------------------------------------------------------------------------
# passed 判定的必写偏移检查（required/optional 划分）
# ---------------------------------------------------------------------------


class RequiredOptionalSemanticsTests(unittest.TestCase):
    """golden passed 判定要求必写偏移全部写入（修复：漏写保护缺失）。"""

    def test_item_price_high_byte_optional_not_written_still_passes(self) -> None:
        """item-prices 用例：仅价格低位字节（required）写入即可通过。"""
        target = 87843  # M10-item_price_01 的 target_offset
        entry = make_index_entry(
            "M10",
            "item_price_01",
            "golden",
            (target, target + 1),
            (target, *core.NORMALIZATION_OFFSETS),
            required_offsets=(target,),
            optional_offsets=(target + 1,),
        )
        self.assertIs(entry["passed"], True)
        self.assertEqual(entry["required_offsets"], [target])
        self.assertEqual(entry["optional_offsets"], [target + 1])
        self.assertEqual(entry["unexpected_count"], 0)

    def test_required_offset_missing_fails_golden(self) -> None:
        """required 全集缺写（默认 required=expected）不得 passed。"""
        entry = make_index_entry(
            "M99", "field_z", "golden", (0x100, 0x200), (0x100,)
        )
        self.assertIs(entry["passed"], False)

    def test_optional_only_missing_still_passes_when_required_written(self) -> None:
        """仅 optional 偏移未写入：不阻断 passed（合理可不变跨度）。"""
        entry = make_index_entry(
            "M99",
            "field_w",
            "golden",
            (0x100, 0x200),
            (0x100,),
            required_offsets=(0x100,),
            optional_offsets=(0x200,),
        )
        self.assertIs(entry["passed"], True)

    def test_empty_required_fails_golden(self) -> None:
        """required 为空（无任何必写偏移）无法判定，不得 passed。"""
        entry = make_index_entry(
            "M99", "field_v", "golden", (), ()
        )
        self.assertIs(entry["passed"], False)
        self.assertFalse(entry["expected_known"])


# ---------------------------------------------------------------------------
# 覆盖率报告复算一致性（产物缺失时跳过）
# ---------------------------------------------------------------------------


@unittest.skipIf(
    not (HAS_REPORT and HAS_GOLDEN and HAS_REGISTRY),
    "覆盖率报告 / index / 注册表产物缺失，跳过报告复算",
)
class CoverageReportConsistencyTests(unittest.TestCase):
    def test_report_matches_recomputed_values(self) -> None:
        report = load_json(REPORT_JSON)
        index = load_json(GOLDEN_INDEX)
        registry = load_json(REGISTRY_PATH)
        g1_num, g1_den, g2_num, g2_den = recompute_coverage(
            index["fields"], registry["entries"]
        )
        self.assertEqual(report["g1"]["numerator"], g1_num)
        self.assertEqual(report["g1"]["denominator"], g1_den)
        self.assertEqual(report["g2"]["numerator"], g2_num)
        self.assertEqual(report["g2"]["denominator"], g2_den)
        self.assertEqual(
            report["g1"]["value"], round(g1_num / g1_den, 4)
        )
        self.assertEqual(
            report["g2"]["value"], round(g2_num / g2_den, 4)
        )
        self.assertEqual(report["counts"]["registered_fields"], g1_den)
        self.assertEqual(report["counts"]["golden_cases"], g2_den)

    def test_report_declares_denominator_scope(self) -> None:
        report = load_json(REPORT_JSON)
        self.assertEqual(report["g1"]["denominator_scope"], "registered_fields")
        self.assertTrue(report["g1"]["denominator_scope_note"])
        self.assertEqual(report["g1"]["target"], ">=95%")
        self.assertEqual(report["g2"]["target"], "=100%")
        self.assertEqual(report["schema_version"], core.SCHEMA_VERSION)

    def test_discovery_cases_are_excluded_from_g2(self) -> None:
        report = load_json(REPORT_JSON)
        index = load_json(GOLDEN_INDEX)
        counts = report["counts"]
        # G2 分母只含 golden 用例：golden + discovery == 已归档用例总数。
        self.assertEqual(
            counts["archived_cases"],
            counts["golden_cases"] + counts["discovery_cases"],
        )
        discovery_fields = {
            f"{info['module']}/{info['field']}"
            for info in index["fields"].values()
            if info["case_kind"] == "discovery"
        }
        self.assertEqual(discovery_fields, EXPECTED_DISCOVERY_FIELDS)
        # discovery 用例不参与 G2 判定：passed 为 null、expected 未知。
        for key in discovery_fields:
            info = index["fields"][key]
            self.assertIsNone(info["passed"])
            self.assertFalse(info["expected_known"])
        # discovery 字段也不得进入 G1 分子：全部列入待解释清单。
        pending = {
            (item["module"], item["field"]) for item in report["pending_cases"]
        }
        for field_key in discovery_fields:
            module, field = field_key.split("/")
            self.assertIn((module, field), pending)


# ---------------------------------------------------------------------------
# CLI 边界：diff --out 只读边界 / 偏移解析错误 / 超限告警
# ---------------------------------------------------------------------------


class CliParseOffsetsTests(unittest.TestCase):
    """parse_offsets 的纯数字超限告警（无 0x 前缀 token）。"""

    def test_bare_decimal_over_limit_warns_on_stderr(self) -> None:
        stderr = io.StringIO()
        with contextlib.redirect_stderr(stderr):
            offsets = cli.parse_offsets("800000,0x100", warn_out_of_range=True)
        self.assertEqual(offsets, (800000, 0x100))
        message = stderr.getvalue()
        self.assertIn("警告", message)
        self.assertIn("800000", message)

    def test_hex_prefix_and_at_limit_do_not_warn(self) -> None:
        """0x 前缀 token 与恰好等于上限的纯数字不告警（阈值 > 才触发）。"""
        stderr = io.StringIO()
        with contextlib.redirect_stderr(stderr):
            offsets = cli.parse_offsets(
                f"{cli.ROM_SIZE_LIMIT},0x{cli.ROM_SIZE_LIMIT:X},0x100",
                warn_out_of_range=True,
            )
        self.assertEqual(
            offsets, (cli.ROM_SIZE_LIMIT, cli.ROM_SIZE_LIMIT, 0x100)
        )
        self.assertEqual(stderr.getvalue(), "")

    def test_warning_disabled_by_default(self) -> None:
        stderr = io.StringIO()
        with contextlib.redirect_stderr(stderr):
            cli.parse_offsets("800000")
        self.assertEqual(stderr.getvalue(), "")

    def test_invalid_token_raises_value_error(self) -> None:
        with self.assertRaises(ValueError):
            cli.parse_offsets("not-a-number")


class CliDiffCommandTests(unittest.TestCase):
    """cmd_diff：--out 只读边界（references/）与解析错误的友好退出码 2。"""

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.before_path = Path(self._tmp.name) / "before.nes"
        self.after_path = Path(self._tmp.name) / "after.nes"
        self.before_path.write_bytes(b"\x00\x01\x02")
        self.after_path.write_bytes(b"\x00\x05\x02")

    def _run(self, *extra: str) -> int:
        return cli.main(
            [
                "diff",
                "--before",
                str(self.before_path),
                "--after",
                str(self.after_path),
                *extra,
            ]
        )

    def test_out_inside_references_is_rejected(self) -> None:
        """--out 指向 references/ 之下：退出码 2 且不产生任何写入。"""
        out_path = ROOT / "references" / "tmp-diff-report.json"
        stderr = io.StringIO()
        with contextlib.redirect_stderr(stderr):
            code = self._run("--out", str(out_path))
        self.assertEqual(code, 2)
        self.assertIn("references", stderr.getvalue())
        self.assertFalse(out_path.exists())

    def test_invalid_offset_token_returns_2(self) -> None:
        stderr = io.StringIO()
        with contextlib.redirect_stderr(stderr):
            code = self._run("--expected", "not-a-number")
        self.assertEqual(code, 2)
        self.assertIn("偏移解析失败", stderr.getvalue())

    def test_out_writes_report_atomically(self) -> None:
        out_path = Path(self._tmp.name) / "reports" / "diff-report.json"
        code = self._run("--out", str(out_path), "--expected", "1")
        self.assertEqual(code, 0)
        payload = json.loads(out_path.read_text(encoding="utf-8"))
        self.assertEqual(payload["changed_offsets"], [1])
        self.assertEqual(payload["unexpected_offsets"], [])
        # 原子写入：临时文件应已被替换清除。
        self.assertFalse(
            (out_path.parent / (out_path.name + ".tmp")).exists()
        )

    def test_bare_decimal_over_limit_warns_but_succeeds(self) -> None:
        """超限纯数字偏移仅告警不阻断（退出码仍 0）。"""
        stderr = io.StringIO()
        with contextlib.redirect_stderr(stderr):
            code = self._run("--expected", "800000")
        self.assertEqual(code, 0)
        self.assertIn("警告", stderr.getvalue())


class CliMissingInputsTests(unittest.TestCase):
    """archive/verify/stats 入口对存量 JSON 缺失的友好退出码 2。"""

    def _run_in_empty_repo(self, command: str) -> tuple[int, str]:
        stderr = io.StringIO()
        with tempfile.TemporaryDirectory() as tmp:
            with mock.patch.object(
                cli, "default_repo_root", return_value=Path(tmp)
            ):
                with contextlib.redirect_stderr(stderr):
                    code = cli.main([command])
        return code, stderr.getvalue()

    def test_archive_missing_result_json_returns_2(self) -> None:
        code, message = self._run_in_empty_repo("archive")
        self.assertEqual(code, 2)
        self.assertIn("错误", message)
        self.assertIn("不存在", message)

    def test_verify_missing_result_json_returns_2(self) -> None:
        code, message = self._run_in_empty_repo("verify")
        self.assertEqual(code, 2)
        self.assertIn("错误", message)
        self.assertIn("不存在", message)

    def test_stats_missing_index_returns_2(self) -> None:
        code, message = self._run_in_empty_repo("stats")
        self.assertEqual(code, 2)
        self.assertIn("不存在", message)


# ---------------------------------------------------------------------------
# 路径比较大小写不敏感与孤儿档案检测（仅报告不删除）
# ---------------------------------------------------------------------------


class UnregisteredSnapshotPathTests(unittest.TestCase):
    """find_unregistered_snapshots 的路径比较两侧统一 lower()。"""

    def test_registry_path_case_mismatch_is_not_orphan(self) -> None:
        """注册表路径大小写与实际目录不一致时不得误报孤儿。"""
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            case_dir = (
                repo
                / core.AUDIT_DIR_RELATIVE
                / "cases"
                / "Legacy_Globals"
                / "SomeCase"
            )
            case_dir.mkdir(parents=True)
            (case_dir / "before.nes").write_bytes(b"\x00")
            (case_dir / "after.nes").write_bytes(b"\x01")
            entry = core.RegistryEntry(
                module="M17",
                field="some_case",
                case_id="write",
                case_kind="golden",
                source_json=(
                    "output/build/legacy-diff-audit/"
                    "legacy-global-field-results.json"
                ),
                snapshot_before=(
                    "output/build/legacy-diff-audit/cases/legacy_globals/"
                    "SomeCase/before.nes"
                ),
                snapshot_after=(
                    "output/build/legacy-diff-audit/cases/legacy_globals/"
                    "SomeCase/after.nes"
                ),
                expected_offsets=(1,),
                extra_allowed=(),
                required_offsets=(1,),
                optional_offsets=(),
                notes=(),
            )
            orphans = core.find_unregistered_snapshots(repo, [entry])
            self.assertEqual(orphans, [])

    def test_unregistered_case_dir_is_reported(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            case_dir = (
                repo / core.AUDIT_DIR_RELATIVE / "cases" / "legacy_globals" / "Ghost"
            )
            case_dir.mkdir(parents=True)
            (case_dir / "before.nes").write_bytes(b"\x00")
            (case_dir / "after.nes").write_bytes(b"\x01")
            orphans = core.find_unregistered_snapshots(repo, [])
            self.assertEqual(
                orphans,
                [(core.AUDIT_DIR_RELATIVE / "cases" / "legacy_globals" / "Ghost").as_posix()],
            )


class OrphanArchiveTests(unittest.TestCase):
    """find_orphan_archives：golden/ 下未被引用的旧档案仅报告不删除。"""

    def test_reports_unreferenced_archives_excluding_index(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            golden_dir = Path(tmp)
            for name in (
                "M10-item_price_01-write.json",
                "M17-hit_threshold-write.json",
                "index.json",
                "M99-stale_field-write.json",
            ):
                (golden_dir / name).write_text("{}\n", encoding="utf-8")
            orphans = core.find_orphan_archives(
                golden_dir,
                {
                    "M10-item_price_01-write.json",
                    "M17-hit_threshold-write.json",
                },
            )
            self.assertEqual(orphans, ["M99-stale_field-write.json"])
            # 仅报告不删除：孤儿档案仍在磁盘上。
            self.assertTrue((golden_dir / "M99-stale_field-write.json").is_file())

    def test_no_orphans_when_all_referenced(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            golden_dir = Path(tmp)
            (golden_dir / "index.json").write_text("{}\n", encoding="utf-8")
            (golden_dir / "M10-item_price_01-write.json").write_text(
                "{}\n", encoding="utf-8"
            )
            self.assertEqual(
                core.find_orphan_archives(
                    golden_dir, {"M10-item_price_01-write.json"}
                ),
                [],
            )


@unittest.skipIf(not HAS_REGISTRY, "字段注册表缺失，跳过 required/optional 分区检查")
class RegistryRequiredOptionalTests(unittest.TestCase):
    """注册表 required/optional 与 expected 的分区关系。"""

    def test_required_optional_partition_matches_expected(self) -> None:
        registry = load_json(REGISTRY_PATH)
        self.assertTrue(registry["entries"])
        for entry in registry["entries"]:
            with self.subTest(field=f"{entry['module']}/{entry['field']}"):
                self.assertEqual(
                    sorted(
                        set(entry["required_offsets"])
                        | set(entry["optional_offsets"])
                    ),
                    sorted(set(entry["expected_offsets"])),
                )
                self.assertFalse(
                    set(entry["required_offsets"])
                    & set(entry["optional_offsets"])
                )
                self.assertIn("required_optional_semantics", registry)

    def test_item_price_required_low_byte_only(self) -> None:
        """item-prices：required=价格低位字节，optional=高位字节；
        其他族（如 hit_threshold）required=expected 全集、optional 为空。"""
        registry = load_json(REGISTRY_PATH)
        by_field = {
            (entry["module"], entry["field"]): entry
            for entry in registry["entries"]
        }
        item = by_field[("M10", "item_price_01")]
        self.assertEqual(item["expected_offsets"], [87843, 87844])
        self.assertEqual(item["required_offsets"], [87843])
        self.assertEqual(item["optional_offsets"], [87844])
        hit = by_field[("M17", "hit_threshold")]
        self.assertEqual(hit["required_offsets"], hit["expected_offsets"])
        self.assertEqual(hit["optional_offsets"], [])


# ---------------------------------------------------------------------------
# 双击第三镜像三方一致（profiles.py / 核心库 / 注册表）
# ---------------------------------------------------------------------------


class ThirdMirrorConsistencyTests(unittest.TestCase):
    def test_profiles_double_hit_groups_carry_third_mirrors(self) -> None:
        groups = MMC5_LEGACY_GLOBAL_DATA.double_hit_operand_groups
        self.assertEqual(groups, EXPECTED_DOUBLE_HIT_OPERAND_GROUPS)
        # 三组各自的第三镜像恰为 (0x7FF03, 0x7FF12, 0x7FF1A)。
        self.assertEqual(
            tuple(group[2] for group in groups), core.DOUBLE_HIT_THIRD_MIRRORS
        )
        # 每组镜像互不重叠且前两镜像非空（REQ-GLOB-001 三镜像同步）。
        self.assertEqual(
            [len(group) for group in groups], [3, 3, 3]
        )
        flattened = [offset for group in groups for offset in group]
        self.assertEqual(len(flattened), len(set(flattened)))

    def test_dc_profiles_reference_the_same_mirror_table(self) -> None:
        self.assertIs(
            MMC5_PROFILE.legacy_global_data, MMC5_LEGACY_GLOBAL_DATA
        )
        self.assertIs(
            DC_EXPANDED_MMC3_LEGACY_PROFILE.legacy_global_data,
            MMC5_LEGACY_GLOBAL_DATA,
        )
        self.assertEqual(
            DC_EXPANDED_MMC3_LEGACY_PROFILE.legacy_global_data.double_hit_operand_groups,
            EXPECTED_DOUBLE_HIT_OPERAND_GROUPS,
        )

    @unittest.skipIf(not HAS_REGISTRY, "字段注册表缺失，跳过 extra_allowed 对照")
    def test_registry_double_hit_extra_allowed_matches_profiles(self) -> None:
        registry = load_json(REGISTRY_PATH)
        by_field = {
            (entry["module"], entry["field"]): entry
            for entry in registry["entries"]
        }
        for field in DOUBLE_HIT_FIELD_NAMES:
            with self.subTest(field=field):
                entry = by_field[("M17", field)]
                self.assertEqual(entry["case_kind"], "golden")
                self.assertEqual(
                    entry["extra_allowed"], list(core.DOUBLE_HIT_THIRD_MIRRORS)
                )
                self.assertEqual(
                    entry["extra_allowed"],
                    [group[2] for group in EXPECTED_DOUBLE_HIT_OPERAND_GROUPS],
                )
                # 审计 CASES 登记的前两镜像恰为 expected_offsets。
                self.assertEqual(
                    entry["expected_offsets"],
                    list(DOUBLE_HIT_FIRST_TWO_MIRRORS_BY_FIELD[field]),
                )


if __name__ == "__main__":
    unittest.main()
