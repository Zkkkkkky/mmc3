"""Consolidate validated legacy weapon-FF save probes into frontier evidence.

The probe ROMs are isolated copies.  This reporter only reads their golden
summaries, checks the exact whole-ROM hashes/diff counts, and emits execution
records only for the interactions that the matrix actually exercised.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


EXPECTED_CASES = {
    "legacy-ui-probe-recursive-dbsaveff-01": (
        "C6D9BBCC148D40BB74D4D8F982FFCB14013D4F8C5CB54CA0AAF77B8BEC45A186",
        2648,
        "我方共享脚本/首条",
    ),
    "legacy-ui-probe-recursive-dbsaveff-row1-01": (
        "6E577B780D06D45277F5154D159E87E1EB57A10A7F165F1E251054B3045C46D4",
        2646,
        "我方共享脚本/中间",
    ),
    "legacy-ui-probe-recursive-dbsaveff-w20-r0-01": (
        "464F06D1EAD5449C9FA470C1A84AFE68A542E3B90F79F4F6EAD71DA51801B4BC",
        1629,
        "我方独立脚本/首条",
    ),
    "legacy-ui-probe-recursive-dbsaveff-enemy-w1-r0-01": (
        "2118F30B806BA3ECF957807B65BEB65B2F0D96F0491CB8E5130C9E6F627AA056",
        5944,
        "敌方共享脚本/首条",
    ),
    "legacy-ui-probe-recursive-dbsaveff-enemy-w29-r25-01": (
        "3274B03300847E97CF3582D1C191D52481E95FDA0ABAD4D2D4071C810C4D1354",
        5527,
        "敌方独立脚本/末条有效指令",
    ),
    "legacy-ui-probe-recursive-dbsaveff-enemy-w29-r27-noop-01": (
        "82C218275459D53C0F306F6BC036C4797316976E0FA7AD1D5A8247E338995B8E",
        0,
        "已有结束符/无操作边界",
    ),
}

EXPECTED_ACTION_CASES = {
    "legacy-ui-probe-recursive-dbsaveff-keyboard-01": {
        "label": "FF 按钮键盘激活（真实聚焦后按空格）",
        "action_mode": "keyboard",
        "sha256_after": "C6D9BBCC148D40BB74D4D8F982FFCB14013D4F8C5CB54CA0AAF77B8BEC45A186",
        "diff_count": 2648,
        "selector_closed_by_action": True,
        "keyboard_focus_acquired": True,
    },
    "legacy-ui-probe-recursive-dbsaveff-right-01": {
        "label": "FF 按钮右键无操作",
        "action_mode": "right",
        "sha256_after": "82C218275459D53C0F306F6BC036C4797316976E0FA7AD1D5A8247E338995B8E",
        "diff_count": 0,
        "selector_closed_by_action": False,
        "right_click_noop": True,
    },
}


def build_matrix(verification_root: Path, frontier_path: Path) -> dict[str, Any]:
    cases: list[dict[str, Any]] = []
    for session, (expected_sha, expected_diff, label) in EXPECTED_CASES.items():
        path = (
            verification_root / session / "interaction-discovery"
            / "weapon-ff-save-golden.json"
        )
        payload = json.loads(path.read_text(encoding="utf-8"))
        actual_sha = str(payload.get("sha256_after", "")).upper()
        actual_diff = int(payload.get("diff_count", -1))
        valid = (
            payload.get("validated") is True
            and payload.get("selector_closed_by_action") is True
            and actual_sha == expected_sha
            and actual_diff == expected_diff
        )
        if not valid:
            raise ValueError(f"FF golden mismatch: {path}")
        cases.append(
            {
                "session": session,
                "label": label,
                "sha256_after": actual_sha,
                "diff_count": actual_diff,
                "source": path.as_posix(),
            }
        )
    for session, expected in EXPECTED_ACTION_CASES.items():
        path = (
            verification_root / session / "interaction-discovery"
            / "weapon-ff-save-golden.json"
        )
        payload = json.loads(path.read_text(encoding="utf-8"))
        checked = {
            "action_mode": payload.get("action_mode"),
            "sha256_after": str(payload.get("sha256_after", "")).upper(),
            "diff_count": int(payload.get("diff_count", -1)),
            "selector_closed_by_action": payload.get("selector_closed_by_action"),
        }
        for optional in ("keyboard_focus_acquired", "right_click_noop"):
            if optional in expected:
                checked[optional] = payload.get(optional)
        if payload.get("validated") is not True or any(
            checked.get(key) != value
            for key, value in expected.items()
            if key != "label"
        ):
            raise ValueError(f"FF action golden mismatch: {path}")
        cases.append(
            {
                "session": session,
                "label": expected["label"],
                **checked,
                "source": path.as_posix(),
            }
        )

    frontier = json.loads(frontier_path.read_text(encoding="utf-8"))
    actions = frontier.get("actions", [])

    def find_action(**criteria: Any) -> str:
        matches = [
            action for action in actions
            if all(action.get(key) == value for key, value in criteria.items())
        ]
        if len(matches) != 1:
            raise ValueError(f"Expected one frontier action for {criteria}, got {len(matches)}")
        return str(matches[0]["action_id"])

    insert_action = find_action(
        window="武器修改",
        control_class="ContextMenuItem",
        control_id=20014,
        observed_text="插入",
        action="activate_context_command",
        context_origin={
            "control_class": "ListBox",
            "control_id": 2530,
            "control_index": 10,
            "observed_text": "",
        },
    )
    ff_action = find_action(
        window="武器指令",
        control_class="Button",
        control_id=190,
        observed_text="FF动画结束",
        action="left_click",
    )
    ff_keyboard_action = find_action(
        window="武器指令",
        control_class="Button",
        control_id=190,
        observed_text="FF动画结束",
        action="keyboard_activate",
    )
    ff_right_action = find_action(
        window="武器指令",
        control_class="Button",
        control_id=190,
        observed_text="FF动画结束",
        action="right_click",
    )
    result = (
        "6 个旧修改器实跑样本：敌我双方、共享/独立脚本、首/中/末位置，"
        "并含已有 FF 的零写入边界；全部整 ROM 哈希与差异数吻合。"
    )
    return {
        "schema_version": 1,
        "validated": True,
        "matrix": "weapon-animation-insert-ff",
        "cases": cases,
        "records": [],
        "execution_records": [
            {"action_id": insert_action, "status": "passed", "result": result},
            {"action_id": ff_action, "status": "passed", "result": result},
            {
                "action_id": ff_keyboard_action,
                "status": "passed",
                "result": "旧版真实聚焦 FF 按钮后按空格，结果与左键黄金整 ROM 一致。",
            },
            {
                "action_id": ff_right_action,
                "status": "passed",
                "result": "旧版 FF 按钮右键保持选择器打开；取消数据库后真实保存零差分。",
            },
        ],
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--verification-root", type=Path, default=Path("output/verification")
    )
    parser.add_argument(
        "--frontier", type=Path,
        default=Path("output/reports/legacy-interaction-frontier.json"),
    )
    parser.add_argument(
        "--output", type=Path,
        default=Path(
            "output/verification/legacy-ui-probe-recursive-dbsaveff-matrix-01/"
            "interaction-discovery/weapon-ff-matrix-golden.json"
        ),
    )
    args = parser.parse_args()
    payload = build_matrix(args.verification_root, args.frontier)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps({"validated": True, "cases": len(payload["cases"]),
                      "actions": len(payload["execution_records"])},
                     ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
