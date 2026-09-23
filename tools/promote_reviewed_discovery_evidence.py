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


def _promote_noop_report(report: dict[str, Any]) -> None:
    if report["changed_offsets"] or report["diffs"]:
        raise RuntimeError("Reviewed no-op evidence unexpectedly changed ROM bytes")
    if report["requested_value"] == report["original_value"]:
        raise RuntimeError("Reviewed no-op evidence did not exercise a value change")
    if report["reopen_value"] != report["original_value"]:
        raise RuntimeError("Reviewed no-op evidence did not cold-reopen to the original value")
    if report["first_pid"] == report["second_pid"]:
        raise RuntimeError("Reviewed no-op evidence did not use a fresh process")
    if report["snapshots"]["before"]["sha256"] != report["snapshots"]["after"]["sha256"]:
        raise RuntimeError("Reviewed no-op snapshots are not byte-identical")
    if report["within_budget"] is not True:
        raise RuntimeError("Reviewed no-op evidence exceeded the performance budget")
    report.update(
        {
            "case_kind": "golden",
            "expected_noop": True,
            "expected_offsets": [],
            "required_offsets": [],
            "optional_offsets": [],
            "extra_allowed": [],
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

    # The reference sprite-anchor spinner visibly accepts 0 -> 1, but OK/save
    # writes no ROM byte and a fresh process reopens at the original 0.  This
    # is a reviewed negative contract, so archive it as an explicit golden
    # no-op instead of leaving the read-only product boundary as discovery.
    anchor_key = ("M12", "sprite_anchor_x", "cold_start_07")
    anchor_path = (
        AUDIT / "cases/legacy_live/M12/sprite_anchor_x/cold_start_07/case.json"
    )
    anchor = _read(anchor_path)
    _promote_noop_report(anchor)
    _write(anchor_path, anchor)
    by_key[anchor_key].clear()
    by_key[anchor_key].update(anchor)

    anchor_config_path = CASES / "M12-sprite-anchor-x-cold-start-01.json"
    anchor_config = _read(anchor_config_path)
    anchor_config.update(
        {
            "case_id": "cold_start_07",
            "case_kind": "golden",
            "expected_noop": True,
            "expected_offsets": [],
            "required_offsets": [],
            "optional_offsets": [],
            "extra_allowed": [],
        }
    )
    _write(anchor_config_path, anchor_config)

    # Two independent experience rows produced the exact same whole-save
    # rewrite and byte-identical output ROM.  Neither requested value survived
    # a fresh-process reopen, so the rewrite is normalization rather than an
    # experience-field write.
    experience_fields = ("experience_level_2", "experience_level_60")
    experience_reports: list[dict[str, Any]] = []
    for field in experience_fields:
        key = ("M09", field, "cold_start_01")
        report_path = (
            AUDIT / "cases/legacy_live/M09" / field / "cold_start_01/case.json"
        )
        report = _read(report_path)
        if report["requested_value"] == report["original_value"]:
            raise RuntimeError(f"M09 {field} did not exercise a value change")
        if report["reopen_value"] != report["original_value"]:
            raise RuntimeError(f"M09 {field} did not reopen to its original value")
        if report["first_pid"] == report["second_pid"]:
            raise RuntimeError(f"M09 {field} did not use a fresh process")
        if report["within_budget"] is not True:
            raise RuntimeError(f"M09 {field} exceeded the performance budget")
        experience_reports.append(report)

    normalization = [int(value) for value in experience_reports[0]["changed_offsets"]]
    if not normalization:
        raise RuntimeError("M09 experience save normalization is empty")
    if any(
        [int(value) for value in report["changed_offsets"]] != normalization
        or report["snapshots"]["after"]["sha256"]
        != experience_reports[0]["snapshots"]["after"]["sha256"]
        for report in experience_reports[1:]
    ):
        raise RuntimeError("M09 experience no-op repeats do not have identical rewrites")

    for field, report in zip(experience_fields, experience_reports, strict=True):
        report.update(
            {
                "case_kind": "golden",
                "expected_noop": True,
                "expected_offsets": [],
                "required_offsets": [],
                "optional_offsets": [],
                "extra_allowed": normalization,
                "unexpected_offsets": [],
                "expected_not_changed": [],
                "passed": True,
                "pending_reason": None,
            }
        )
        report_path = (
            AUDIT / "cases/legacy_live/M09" / field / "cold_start_01/case.json"
        )
        _write(report_path, report)
        key = ("M09", field, "cold_start_01")
        by_key[key].clear()
        by_key[key].update(report)

        stem = field.replace("_", "-")
        old_config = DISCOVERY / f"M09-{stem}-discovery-cold-start-01.json"
        new_config = CASES / f"M09-{stem}-cold-start-01.json"
        source = old_config if old_config.is_file() else new_config
        config = _read(source)
        config.update(
            {
                "case_kind": "golden",
                "expected_noop": True,
                "expected_offsets": [],
                "required_offsets": [],
                "optional_offsets": [],
                "extra_allowed": [],
                "extra_allowed_profile": "m09_experience_save_normalization_v1",
            }
        )
        _write(new_config, config)
        if source != new_config:
            source.unlink()

    live.sort(key=lambda item: (item["module"], item["field"], item["case_id"]))
    _write(LIVE_RESULTS, compact_live_result_items(live))
    print(
        "Promoted M06 overflow repeats, M12 sprite-code duplicate, "
        "M12 sprite-anchor no-op, and M09 experience no-op repeats"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
