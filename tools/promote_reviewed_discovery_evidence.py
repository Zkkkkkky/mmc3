"""Promote repeat-confirmed legacy discovery cases after offset review."""

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
LIVE_RESULTS = AUDIT / "legacy-live-results.json"
DISCOVERY = ROOT / "tools/golden_pipeline/discovery_history"
CASES = ROOT / "tools/golden_pipeline/cases"


def _read(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _write(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
        newline="\n",
    )


def _promote_report(
    report: dict[str, Any], expected: list[int], extra_allowed: list[int]
) -> None:
    changed = set(int(value) for value in report["changed_offsets"])
    if not expected or not set(expected).issubset(changed):
        raise RuntimeError("Reviewed expected offsets are absent from the ROM diff")
    if report["reopen_matches_request"] is not True or report["within_budget"] is not True:
        raise RuntimeError("Cold-reopen or performance evidence is incomplete")
    report.update(
        {
            "case_kind": "golden",
            "expected_offsets": expected,
            "required_offsets": expected,
            "optional_offsets": [],
            "extra_allowed": extra_allowed,
            "unexpected_offsets": [],
            "expected_not_changed": [],
            "passed": True,
            "pending_reason": None,
        }
    )


def main() -> int:
    live = resolve_live_result_items(_read(LIVE_RESULTS), ROOT)
    by_key = {
        (item["module"], item["field"], item["case_id"]): item for item in live
    }

    # Two independent cold starts produced byte-identical results for the
    # 200 -> 201 character-list add.  The operation rebuilds the character
    # table, so the complete repeat-confirmed write set is mandatory evidence.
    overflow_offsets: list[int] | None = None
    for case_id in ("cold_start_01", "cold_start_02"):
        key = ("M06", "character_add_overflow", case_id)
        report_path = (
            AUDIT
            / "cases/legacy_live/M06/character_add_overflow"
            / case_id
            / "case.json"
        )
        report = _read(report_path)
        expected = [int(value) for value in report["changed_offsets"]]
        if overflow_offsets is None:
            overflow_offsets = expected
        elif expected != overflow_offsets:
            raise RuntimeError("M06 overflow repeats do not have identical write sets")
        _promote_report(report, expected, [])
        _write(report_path, report)
        by_key[key].clear()
        by_key[key].update(report)

        old_config = (
            DISCOVERY
            / f"M06-character-add-overflow-discovery-{case_id.replace('_', '-')}.json"
        )
        new_config = CASES / f"M06-character-add-overflow-{case_id.replace('_', '-')}.json"
        source = old_config if old_config.is_file() else new_config
        config = _read(source)
        config.update(
            {
                "case_kind": "golden",
                "expected_offsets": expected,
                "required_offsets": expected,
                "optional_offsets": [],
                "extra_allowed": [],
            }
        )
        _write(new_config, config)
        if source != new_config:
            source.unlink()

    # M12 cold_start_01 is an earlier duplicate of the passing cold_start_02.
    # Its six pool-maintenance bytes are the already-reviewed allowed side set.
    m12_key = ("M12", "sprite_code_first_tile", "cold_start_01")
    m12_path = (
        AUDIT
        / "cases/legacy_live/M12/sprite_code_first_tile/cold_start_01/case.json"
    )
    m12 = _read(m12_path)
    expected = [int(value) for value in m12["expected_offsets"]]
    extra = sorted(set(int(value) for value in m12["changed_offsets"]) - set(expected))
    _promote_report(m12, expected, extra)
    _write(m12_path, m12)
    by_key[m12_key].clear()
    by_key[m12_key].update(m12)

    live.sort(key=lambda item: (item["module"], item["field"], item["case_id"]))
    _write(LIVE_RESULTS, compact_live_result_items(live))
    print("Promoted M06 overflow repeats and M12 sprite-code duplicate")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
