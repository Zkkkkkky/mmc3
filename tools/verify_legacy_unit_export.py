from __future__ import annotations

import argparse
from datetime import datetime
import hashlib
import json
import os
from pathlib import Path
import sys
import zipfile

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from dc_modifier.legacy_unit_export import (  # noqa: E402
    LEGACY_UNIT_EXPORT_DIRECTORY,
    legacy_unit_export_bitmaps,
    legacy_unit_export_name,
)
from fc_rom_editor_core import RomProject  # noqa: E402


DEFAULT_ROM = ROOT / "output" / "rom" / "DC_kuorong_464K.nes"
DEFAULT_SAMPLES = (
    ROOT
    / "output"
    / "verification"
    / "legacy-user-evidence-2026-09-14"
    / "legacy-unit-export-samples.zip"
)
DEFAULT_REPORT = ROOT / "output" / "verification" / "m18-unit-export-verification.json"


def _relative(path: Path) -> str:
    try:
        return path.resolve().relative_to(ROOT).as_posix()
    except ValueError:
        return path.resolve().as_posix()


def _digest_update(digest, relative_path: str, payload: bytes) -> None:
    digest.update(relative_path.encode("utf-8"))
    digest.update(b"\0")
    digest.update(payload)


def verify(rom_path: Path, samples_path: Path) -> dict[str, object]:
    project = RomProject.load(rom_path)
    before = hashlib.sha256(bytes(project.working)).hexdigest().upper()
    expected: dict[str, bytes] = {}
    with zipfile.ZipFile(samples_path) as archive:
        for info in archive.infolist():
            if info.filename.endswith(".bmp"):
                expected[info.filename] = archive.read(info)

    generated_digest = hashlib.sha256()
    expected_digest = hashlib.sha256()
    mismatches: list[dict[str, object]] = []
    generated_paths: set[str] = set()
    sizes: dict[str, int] = {}
    for unit_id in range(1, 256):
        name = legacy_unit_export_name(project, unit_id)
        directory = f"{unit_id:03d}：{name}"
        for kind, payload in legacy_unit_export_bitmaps(project, unit_id).items():
            relative_path = (
                f"{LEGACY_UNIT_EXPORT_DIRECTORY}/{directory}/{name}[{kind}].bmp"
            )
            generated_paths.add(relative_path)
            sizes[kind] = len(payload)
            _digest_update(generated_digest, relative_path, payload)
            reference = expected.get(relative_path)
            if reference is not None:
                _digest_update(expected_digest, relative_path, reference)
            if reference != payload:
                mismatches.append({
                    "path": relative_path,
                    "expectedSha256": (
                        hashlib.sha256(reference).hexdigest().upper()
                        if reference is not None else None
                    ),
                    "generatedSha256": hashlib.sha256(payload).hexdigest().upper(),
                })

    missing_paths = sorted(set(expected) - generated_paths)
    extra_paths = sorted(generated_paths - set(expected))
    after = hashlib.sha256(bytes(project.working)).hexdigest().upper()
    return {
        "generatedAt": datetime.now().astimezone().isoformat(timespec="seconds"),
        "rom": {
            "path": _relative(rom_path),
            "sha256": hashlib.sha256(rom_path.read_bytes()).hexdigest().upper(),
            "workingBeforeSha256": before,
            "workingAfterSha256": after,
            "unchanged": before == after,
        },
        "reference": {
            "path": _relative(samples_path),
            "sha256": hashlib.sha256(samples_path.read_bytes()).hexdigest().upper(),
        },
        "protocol": {
            "unitDirectories": 255,
            "generatedFiles": len(generated_paths),
            "referenceFiles": len(expected),
            "bytesPerKind": sizes,
        },
        "aggregate": {
            "generatedSha256": generated_digest.hexdigest().upper(),
            "referenceSha256": expected_digest.hexdigest().upper(),
        },
        "missingPaths": missing_paths,
        "extraPaths": extra_paths,
        "mismatches": mismatches,
        "passed": (
            len(generated_paths) == 1_275
            and len(expected) == 1_275
            and not missing_paths
            and not extra_paths
            and not mismatches
            and before == after
            and generated_digest.digest() == expected_digest.digest()
        ),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="验证 M18 旧版五 BMP 机体导出。")
    parser.add_argument("--rom", type=Path, default=DEFAULT_ROM)
    parser.add_argument("--samples", type=Path, default=DEFAULT_SAMPLES)
    parser.add_argument("--report", type=Path, default=DEFAULT_REPORT)
    args = parser.parse_args()

    report = verify(args.rom, args.samples)
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(
        f"M18: {report['protocol']['generatedFiles']}/1275 files; "
        f"mismatches={len(report['mismatches'])}; passed={report['passed']}"
    )
    print(f"report: {_relative(args.report)}")
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
