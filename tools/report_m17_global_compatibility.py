from __future__ import annotations

import argparse
from datetime import datetime
import hashlib
import json
from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from fc_rom_editor_core import RomProject  # noqa: E402


DEFAULT_ROM = ROOT / "output" / "rom" / "DC_kuorong_464K.nes"
DEFAULT_INDEX = ROOT / "output" / "build" / "legacy-diff-audit" / "golden" / "index.json"
DEFAULT_REPORT = ROOT / "output" / "verification" / "m17-global-compatibility.json"


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest().upper()


def _changed_offsets(before: bytes, after: bytes) -> list[int]:
    return [
        index
        for index, (old, new) in enumerate(zip(before, after, strict=True))
        if old != new
    ]


def _rejected(action) -> str:
    try:
        action()
    except ValueError as error:
        return str(error)
    raise AssertionError("预期全局参数门禁拒绝操作，但调用成功。")


def _archive_integrity(index_path: Path) -> tuple[list[dict[str, object]], bool]:
    payload = json.loads(index_path.read_text(encoding="utf-8"))
    archive_root = index_path.parent
    entries = [
        value
        for value in payload["fields"].values()
        if value.get("module") == "M17"
    ]
    integrity = True
    result: list[dict[str, object]] = []
    for entry in entries:
        archive_path = archive_root / str(entry["archive"])
        archive_bytes = archive_path.read_bytes()
        archive = json.loads(archive_bytes.decode("utf-8"))
        digest = hashlib.sha256(archive_bytes).hexdigest().lower()
        valid = (
            digest == str(entry["sha256"]).lower()
            and entry.get("passed") is True
            and archive.get("passed") is True
            and archive.get("unexpected_offsets") == []
            and archive.get("reopen_matches_request") is True
        )
        integrity = integrity and valid
        result.append(
            {
                "field": entry["field"],
                "case_id": entry["case_id"],
                "archive": entry["archive"],
                "sha256": str(entry["sha256"]).upper(),
                "valid": valid,
            }
        )
    return result, integrity


def analyze(rom_path: Path, index_path: Path = DEFAULT_INDEX) -> dict[str, object]:
    data = rom_path.read_bytes()
    project = RomProject.load(rom_path)
    spec = project.profile.legacy_global_data
    if spec is None:
        raise ValueError("当前 ROM 未启用 M17 全局参数协议。")
    before = bytes(project.working)

    defaults = {
        "double_hit": list(project.get_double_hit_values()),
        "damage": list(project.get_damage_formula_values()),
        "hit_threshold": project.get_hit_threshold(),
        "item_effects": list(project.get_item_effect_values()),
        "initial_roster": [list(pair) for pair in project.get_initial_roster()],
    }

    project.set_double_hit_values((71, 91, 21))
    double_offsets = _changed_offsets(before, bytes(project.working))
    double_expected = sorted(
        offset for group in spec.double_hit_operand_groups for offset in group
    )
    double_undo = project.undo() == "双击公式" and bytes(project.working) == before

    project.set_damage_formula_values((14, 11, 12, 2, 3))
    damage_offsets = _changed_offsets(before, bytes(project.working))
    damage_expected = sorted(spec.damage_formula_operand_offsets)
    damage_undo = project.undo() == "伤害公式" and bytes(project.working) == before

    project.set_hit_threshold(71)
    hit_offsets = _changed_offsets(before, bytes(project.working))
    hit_expected = [spec.hit_threshold_operand_offset]
    hit_undo = project.undo() == "命中阈值" and bytes(project.working) == before

    item_values = tuple(value + 1 for value in project.get_item_effect_values())
    project.set_item_effect_values(item_values)
    item_offsets = _changed_offsets(before, bytes(project.working))
    item_expected = sorted(spec.item_effect_operand_offsets)
    item_undo = project.undo() == "道具效果" and bytes(project.working) == before

    roster = tuple(
        ((character + 1) & 0xFF, (unit + 1) & 0xFF)
        for character, unit in project.get_initial_roster()
    )
    sentinel_offset = spec.initial_roster_offset + 12
    sentinel_before = project.working[sentinel_offset]
    project.set_initial_roster(roster)
    roster_offsets = _changed_offsets(before, bytes(project.working))
    roster_expected = list(range(spec.initial_roster_offset, sentinel_offset))
    sentinel_after = project.working[sentinel_offset]
    roster_undo = project.undo() == "初始人物/机体" and bytes(project.working) == before

    invalid_strength_divisor = _rejected(
        lambda: project.set_damage_formula_values((13, 10, 0, 1, 1))
    )
    invalid_defense_divisor = _rejected(
        lambda: project.set_damage_formula_values((13, 10, 10, 1, 0))
    )
    rejection_preserved_rom = bytes(project.working) == before

    archives, archive_integrity = _archive_integrity(index_path)
    unique_fields = {(entry["field"]) for entry in archives}

    checks = {
        "verified_defaults": defaults
        == {
            "double_hit": [70, 90, 20],
            "damage": [13, 10, 10, 1, 1],
            "hit_threshold": 70,
            "item_effects": [1, 1, 1, 5, 3, 1, 3, 3, 25, 25, 50],
            "initial_roster": [[4, 9], [5, 13], [6, 15], [7, 17], [8, 19], [9, 23]],
        },
        "double_hit_three_mirrors": double_offsets == double_expected and double_undo,
        "damage_five_operands": damage_offsets == damage_expected and damage_undo,
        "hit_threshold_single_operand": hit_offsets == hit_expected and hit_undo,
        "item_effect_eleven_operands": item_offsets == item_expected and item_undo,
        "initial_roster_twelve_bytes_and_sentinel": (
            roster_offsets == roster_expected
            and sentinel_before == sentinel_after == 0xFF
            and roster_undo
        ),
        "zero_divisors_rejected_atomically": (
            bool(invalid_strength_divisor)
            and bool(invalid_defense_divisor)
            and rejection_preserved_rom
        ),
        "reference_golden_archives": (
            archive_integrity and len(archives) == 33 and len(unique_fields) == 32
        ),
    }

    return {
        "generated_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "passed": all(checks.values()),
        "delivery_status": "aligned_regression_guard_user_checklist_pending",
        "conclusion": (
            "M17 的 20 个公式/道具字段和 12 个初始阵容字段均通过产品侧单字段差分、"
            "撤销、镜像/哨兵和拒绝边界；33 个参考黄金用例档案完整、共覆盖 32 个逻辑字段。"
        ),
        "rom": {
            "path": rom_path.resolve().relative_to(ROOT).as_posix(),
            "size": len(data),
            "sha256": _sha256(data),
        },
        "reference_index": index_path.resolve().relative_to(ROOT).as_posix(),
        "defaults": defaults,
        "product_diffs": {
            "double_hit": {"changed_offsets": double_offsets, "expected_offsets": double_expected},
            "damage": {"changed_offsets": damage_offsets, "expected_offsets": damage_expected},
            "hit_threshold": {"changed_offsets": hit_offsets, "expected_offsets": hit_expected},
            "item_effects": {"changed_offsets": item_offsets, "expected_offsets": item_expected},
            "initial_roster": {
                "changed_offsets": roster_offsets,
                "expected_offsets": roster_expected,
                "sentinel_offset": sentinel_offset,
                "sentinel_value": sentinel_after,
            },
        },
        "rejection_messages": {
            "strength_divisor_zero": invalid_strength_divisor,
            "defense_divisor_zero": invalid_defense_divisor,
        },
        "reference_golden": {
            "case_count": len(archives),
            "logical_field_count": len(unique_fields),
            "cases": archives,
        },
        "checks": checks,
        "pending_acceptance": [
            "由用户按 docs/需求拆分/M17_其他窗口.md 第 7 节执行正式 EXE 现场查看并签收。"
        ],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="复验 M17 全局参数与既有参考黄金档案。")
    parser.add_argument("--rom", type=Path, default=DEFAULT_ROM)
    parser.add_argument("--index", type=Path, default=DEFAULT_INDEX)
    parser.add_argument("--report", type=Path, default=DEFAULT_REPORT)
    arguments = parser.parse_args()
    report = analyze(arguments.rom, arguments.index)
    arguments.report.parent.mkdir(parents=True, exist_ok=True)
    arguments.report.write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
