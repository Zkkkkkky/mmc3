"""Preserve a failed/live golden attempt and free its identity for a retry.

The collector intentionally never overwrites a case directory.  A retry must
therefore move the old attempt into a diagnostic history directory and remove
only its row from the live-results index.  No ROM evidence is deleted.
"""

from __future__ import annotations

import argparse
import json
import shutil
from datetime import datetime
from pathlib import Path
from typing import Any, Sequence

try:
    from golden_pipeline_core import AUDIT_DIR_RELATIVE, write_json_atomic
except ImportError:
    from tools.golden_pipeline_core import (  # type: ignore
        AUDIT_DIR_RELATIVE,
        write_json_atomic,
    )


LIVE_ROOT_RELATIVE = AUDIT_DIR_RELATIVE / "cases" / "legacy_live"
LIVE_RESULTS_RELATIVE = AUDIT_DIR_RELATIVE / "legacy-live-results.json"
RETRY_HISTORY_RELATIVE = AUDIT_DIR_RELATIVE / "cases" / "diagnostic" / "retry_history"


def _parse_identity(value: str) -> tuple[str, str, str]:
    parts = tuple(part for part in value.split("/") if part)
    if len(parts) != 3 or any(".." in part or "\\" in part for part in parts):
        raise ValueError("case identity must be module/field/case_id")
    return parts  # type: ignore[return-value]


def prepare_retries(
    repo: Path,
    identities: Sequence[tuple[str, str, str]],
    *,
    reason: str,
    timestamp: str | None = None,
) -> Path:
    repo = repo.resolve()
    live_root = (repo / LIVE_ROOT_RELATIVE).resolve()
    results_path = repo / LIVE_RESULTS_RELATIVE
    history_root = (repo / RETRY_HISTORY_RELATIVE).resolve()
    stamp = timestamp or datetime.now().strftime("%Y%m%dT%H%M%S")
    batch_root = (history_root / stamp).resolve()
    if history_root not in batch_root.parents:
        raise ValueError("retry history path escaped audit directory")
    if batch_root.exists():
        raise FileExistsError(batch_root)

    sources: list[tuple[tuple[str, str, str], Path, Path]] = []
    for identity in identities:
        source = (live_root.joinpath(*identity)).resolve()
        if live_root not in source.parents or not source.is_dir():
            raise FileNotFoundError(source)
        target = (batch_root.joinpath(*identity)).resolve()
        if batch_root not in target.parents:
            raise ValueError("retry target escaped history directory")
        sources.append((identity, source, target))

    results: list[dict[str, Any]] = []
    if results_path.is_file():
        payload = json.loads(results_path.read_text(encoding="utf-8"))
        if not isinstance(payload, list):
            raise ValueError("legacy live results must be a list")
        results = payload
    identity_set = set(identities)
    kept = [
        item
        for item in results
        if (str(item.get("module")), str(item.get("field")), str(item.get("case_id")))
        not in identity_set
    ]
    removed = len(results) - len(kept)

    moved: list[dict[str, Any]] = []
    for identity, source, target in sources:
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(source), str(target))
        moved.append(
            {
                "module": identity[0],
                "field": identity[1],
                "case_id": identity[2],
                "from": source.relative_to(repo).as_posix(),
                "to": target.relative_to(repo).as_posix(),
                "had_case_json": (target / "case.json").is_file(),
                "had_error_json": (target / "error.json").is_file(),
            }
        )
    write_json_atomic(results_path, kept)
    manifest_path = batch_root / "retry_manifest.json"
    write_json_atomic(
        manifest_path,
        {
            "schema_version": 1,
            "reason": reason,
            "timestamp": stamp,
            "moved": moved,
            "live_result_rows_removed": removed,
        },
    )
    return manifest_path


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--case", action="append", required=True)
    parser.add_argument("--reason", required=True)
    args = parser.parse_args(argv)
    repo = Path(__file__).resolve().parents[1]
    identities = [_parse_identity(value) for value in args.case]
    if len(set(identities)) != len(identities):
        raise SystemExit("duplicate --case identity")
    manifest = prepare_retries(repo, identities, reason=args.reason)
    print(f"retry history preserved: {manifest.relative_to(repo).as_posix()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
