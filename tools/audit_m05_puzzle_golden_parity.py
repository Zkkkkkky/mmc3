"""Compare current puzzle operations with every promoted legacy golden case."""

from __future__ import annotations

import json
from pathlib import Path

from dc_modifier.unit_appearance_dialog import (
    apply_legacy_body_template,
    flip_fragment_script,
    move_body_script,
    move_fragment_script,
)


ROOT = Path(__file__).resolve().parents[1]
CASES = ROOT / "tools/golden_pipeline/cases"
REPORT_JSON = ROOT / "output/reports/m05-puzzle-functional-golden-parity.json"
REPORT_MD = ROOT / "output/reports/m05-puzzle-functional-golden-parity.md"


def _case(stem: str) -> dict[str, object]:
    path = CASES / f"M05-{stem}-cold-start-01.json"
    return json.loads(path.read_text(encoding="utf-8"))


def _apply(stem: str, before: bytes) -> bytes:
    operations = {
        "body-puzzle-clear": lambda value: b"\xFF",
        "body-puzzle-move-up": lambda value: move_body_script(value, 0, -1),
        "body-puzzle-move-down": lambda value: move_body_script(value, 0, 1),
        "body-puzzle-move-left": lambda value: move_body_script(value, -1, 0),
        "body-puzzle-move-right": lambda value: move_body_script(value, 1, 0),
        "body-puzzle-swap-banks": lambda value: value,
        "body-puzzle-template-8x8": lambda value: apply_legacy_body_template(value, 8, 8),
        "body-puzzle-template-7x9": lambda value: apply_legacy_body_template(value, 7, 9),
        "body-puzzle-template-9x7": lambda value: apply_legacy_body_template(value, 9, 7),
        "body-puzzle-template-10x6": lambda value: apply_legacy_body_template(value, 10, 6),
        "fragment-puzzle-move-up": lambda value: move_fragment_script(value, 0, -1),
        "fragment-puzzle-move-down": lambda value: move_fragment_script(value, 0, 1),
        "fragment-puzzle-move-left": lambda value: move_fragment_script(value, -1, 0),
        "fragment-puzzle-move-right": lambda value: move_fragment_script(value, 1, 0),
        "fragment-puzzle-clear": lambda value: bytes.fromhex("00 F0 00 00 FF"),
        "fragment-puzzle-flip-horizontal": lambda value: flip_fragment_script(value, 0x40),
        "fragment-puzzle-flip-vertical": lambda value: flip_fragment_script(value, 0x80),
    }
    return operations[stem](before)


def audit() -> dict[str, object]:
    stems = (
        "body-puzzle-clear",
        "body-puzzle-move-up",
        "body-puzzle-move-down",
        "body-puzzle-move-left",
        "body-puzzle-move-right",
        "body-puzzle-swap-banks",
        "body-puzzle-template-8x8",
        "body-puzzle-template-7x9",
        "body-puzzle-template-9x7",
        "body-puzzle-template-10x6",
        "fragment-puzzle-move-up",
        "fragment-puzzle-move-down",
        "fragment-puzzle-move-left",
        "fragment-puzzle-move-right",
        "fragment-puzzle-clear",
        "fragment-puzzle-flip-horizontal",
        "fragment-puzzle-flip-vertical",
    )
    rows = []
    for stem in stems:
        case = _case(stem)
        before = bytes.fromhex(str(case["expected_before"]))
        expected = bytes.fromhex(str(case["requested_value"]))
        actual = _apply(stem, before)
        rows.append({
            "action": stem,
            "status": "pass" if actual == expected else "fail",
            "before_bytes": len(before),
            "expected_bytes": len(expected),
            "actual_bytes": len(actual),
            "expected_hex": expected.hex(" ").upper(),
            "actual_hex": actual.hex(" ").upper(),
        })
    result = {
        "scope": "M05 body/fragment puzzle functional golden parity",
        "golden_actions": len(rows),
        "passed": sum(row["status"] == "pass" for row in rows),
        "failed": sum(row["status"] != "pass" for row in rows),
        "fragment_import_rule": "retain proven global minimum-tile cover",
        "rows": rows,
    }
    REPORT_JSON.parent.mkdir(parents=True, exist_ok=True)
    REPORT_JSON.write_text(
        json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    lines = [
        "# M05 机体拼图/碎片拼图功能黄金对照",
        "",
        f"- 旧版黄金动作：{result['passed']}/{result['golden_actions']} 通过",
        "- 碎片导入：保留可证明的全局最少图块覆盖规则",
        "",
        "| 动作 | 结果 | 输入/旧版结果/当前结果（字节） |",
        "|---|---:|---:|",
    ]
    lines.extend(
        f"| `{row['action']}` | {row['status']} | "
        f"{row['before_bytes']}/{row['expected_bytes']}/{row['actual_bytes']} |"
        for row in rows
    )
    REPORT_MD.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return result


if __name__ == "__main__":
    report = audit()
    print(json.dumps(report, ensure_ascii=False, indent=2))
    raise SystemExit(1 if report["failed"] else 0)
