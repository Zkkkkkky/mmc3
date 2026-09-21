"""Run small resumable batches of both exhaustive map-field collectors."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def run(script: str, limit: int) -> None:
    subprocess.run(
        [sys.executable, str(ROOT / "tools/research" / script), "--restart", "--limit", str(limit)],
        cwd=ROOT,
        check=True,
    )


def main() -> int:
    run("collect_m03_all_reference_fields.py", 8)
    run("collect_m04_all_reference_fields.py", 8)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
