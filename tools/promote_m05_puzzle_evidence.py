"""Promote reviewed M05 puzzle discoveries to golden evidence.

The legacy editor performs a large, stable M05 save-time rewrite even when a
puzzle action is a no-op.  This script uses the collected no-op ``move_down``
case as a hash-pinned normalization profile, then promotes only actions whose
saved ROM differs independently from that baseline and whose cold reopen value
matches the captured request.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from tools.golden_pipeline_core import (
    compact_live_result_items,
    resolve_live_result_items,
)


ROOT = Path(__file__).resolve().parents[1]
AUDIT = ROOT / "output/build/legacy-diff-audit"
LIVE_ROOT = AUDIT / "cases/legacy_live/M05"
DISCOVERY_ROOT = ROOT / "tools/golden_pipeline/discovery_history"
CASE_ROOT = ROOT / "tools/golden_pipeline/cases"
PROFILE_ROOT = ROOT / "tools/golden_pipeline/profiles"
LIVE_RESULTS = AUDIT / "legacy-live-results.json"
BASELINE_FIELD = "body_puzzle_move_down"
PROFILE_NAME = "m05_puzzle_save_normalization_v1"

PROMOTED_FIELDS = (
    "body_puzzle_clear",
    "body_puzzle_move_right",
    "body_puzzle_move_up",
    "body_puzzle_template_10x6",
    "body_puzzle_template_9x7",
    "fragment_puzzle_clear",
    "fragment_puzzle_flip_horizontal",
    "fragment_puzzle_flip_vertical",
    "fragment_puzzle_move_down",
    "fragment_puzzle_move_left",
    "fragment_puzzle_move_right",
    "fragment_puzzle_move_up",
)

PROMOTED_NOOP_FIELDS = (
    "body_puzzle_move_down",
    "body_puzzle_move_left",
    "body_puzzle_swap_banks",
    "body_puzzle_template_7x9",
    "icon_binding_double_click",
)


def _read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
        newline="\n",
    )


def _ranges(offsets: tuple[int, ...]) -> list[list[int]]:
    result: list[list[int]] = []
    for offset in offsets:
        if result and offset == result[-1][1] + 1:
            result[-1][1] = offset
        else:
            result.append([offset, offset])
    return result


def _case_report(field: str) -> Path:
    return LIVE_ROOT / field / "cold_start_01/case.json"


def _config(field: str) -> Path:
    stem = field.replace("_", "-")
    return DISCOVERY_ROOT / f"M05-{stem}-discovery-cold-start-01.json"


def _golden_config(field: str) -> Path:
    stem = field.replace("_", "-")
    return CASE_ROOT / f"M05-{stem}-cold-start-01.json"


def main() -> int:
    baseline_report_path = _case_report(BASELINE_FIELD)
    baseline_report = _read_json(baseline_report_path)
    baseline_after = (ROOT / baseline_report["snapshots"]["after"]["path"]).read_bytes()
    common_offsets = tuple(int(value) for value in baseline_report["changed_offsets"])
    if baseline_report["reopen_matches_request"] is not True or not common_offsets:
        raise RuntimeError("M05 no-op normalization evidence is incomplete")

    _write_json(
        PROFILE_ROOT / f"{PROFILE_NAME}.json",
        {
            "schema_version": 1,
            "name": PROFILE_NAME,
            "description": (
                "参考版进入 M05 机体拼图后保存 ROM 时的稳定重写集合；来源为边界位置按下移键、"
                "脚本内容与重开值均不变的冷启动 no-op 用例。动作黄金用例仅把相对此基线新增的"
                "差异列为必写偏移。"
            ),
            "ranges": _ranges(common_offsets),
        },
    )

    live_results = resolve_live_result_items(_read_json(LIVE_RESULTS), ROOT)
    result_by_field = {
        item["field"]: item
        for item in live_results
        if item.get("module") == "M05" and item.get("case_id") == "cold_start_01"
    }

    for field in PROMOTED_FIELDS:
        report_path = _case_report(field)
        report = _read_json(report_path)
        if report["reopen_matches_request"] is not True or report["within_budget"] is not True:
            raise RuntimeError(f"{field}: reopen or time-budget evidence is incomplete")
        action_after = (ROOT / report["snapshots"]["after"]["path"]).read_bytes()
        if len(action_after) != len(baseline_after):
            raise RuntimeError(f"{field}: ROM size differs from normalization baseline")
        expected = [
            offset
            for offset, (baseline_value, action_value) in enumerate(
                zip(baseline_after, action_after)
            )
            if baseline_value != action_value
        ]
        if not expected:
            raise RuntimeError(f"{field}: action has no independent ROM difference")
        changed = set(int(value) for value in report["changed_offsets"])
        if not set(expected).issubset(changed):
            raise RuntimeError(f"{field}: reviewed offsets are absent from original diff")

        source_config = _config(field)
        if not source_config.is_file():
            source_config = _golden_config(field)
        config = _read_json(source_config)
        if config.get("requested_value") == "$capture_after":
            config["requested_value"] = report["requested_value"]
            config.pop("capture_after_step", None)
        config.update(
            {
                "case_kind": "golden",
                "expected_offsets": expected,
                "required_offsets": expected,
                "optional_offsets": [],
                "extra_allowed": [],
                "extra_allowed_profile": PROFILE_NAME,
            }
        )
        _write_json(_golden_config(field), config)
        if source_config != _golden_config(field):
            source_config.unlink()

        promoted = dict(report)
        promoted.update(
            {
                "case_kind": "golden",
                "expected_offsets": expected,
                "required_offsets": expected,
                "optional_offsets": [],
                "extra_allowed": list(common_offsets),
                "extra_allowed_profile": PROFILE_NAME,
                "unexpected_offsets": [],
                "expected_not_changed": [],
                "passed": True,
                "pending_reason": None,
            }
        )
        _write_json(report_path, promoted)
        result_by_field[field].clear()
        result_by_field[field].update(promoted)

    for field in PROMOTED_NOOP_FIELDS:
        report_path = _case_report(field)
        report = _read_json(report_path)
        if (
            report["requested_value"] != report["original_value"]
            or report["reopen_matches_request"] is not True
            or report["within_budget"] is not True
            or tuple(int(value) for value in report["changed_offsets"])
            != common_offsets
        ):
            raise RuntimeError(f"{field}: reviewed no-op evidence is not stable")

        source_config = _config(field)
        if not source_config.is_file():
            source_config = _golden_config(field)
        config = _read_json(source_config)
        config.update(
            {
                "case_kind": "golden",
                "expected_noop": True,
                "expected_offsets": [],
                "required_offsets": [],
                "optional_offsets": [],
                "extra_allowed": [],
                "extra_allowed_profile": PROFILE_NAME,
            }
        )
        _write_json(_golden_config(field), config)
        if source_config != _golden_config(field):
            source_config.unlink()

        promoted = dict(report)
        promoted.update(
            {
                "case_kind": "golden",
                "expected_noop": True,
                "expected_offsets": [],
                "required_offsets": [],
                "optional_offsets": [],
                "extra_allowed": list(common_offsets),
                "extra_allowed_profile": PROFILE_NAME,
                "unexpected_offsets": [],
                "expected_not_changed": [],
                "passed": True,
                "pending_reason": None,
            }
        )
        _write_json(report_path, promoted)
        result_by_field[field].clear()
        result_by_field[field].update(promoted)

    live_results.sort(key=lambda item: (item["module"], item["field"], item["case_id"]))
    _write_json(LIVE_RESULTS, compact_live_result_items(live_results))
    print(
        f"Promoted {len(PROMOTED_FIELDS)} M05 write cases and "
        f"{len(PROMOTED_NOOP_FIELDS)} no-op cases; "
        f"normalization_offsets={len(common_offsets)}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
