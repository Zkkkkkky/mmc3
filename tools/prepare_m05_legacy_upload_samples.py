"""Extract deterministic M05 upload fixtures from the archived legacy export."""

from __future__ import annotations

import hashlib
import json
import struct
import zipfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
ARCHIVE = (
    ROOT
    / "output/verification/legacy-user-evidence-2026-09-14/legacy-unit-export-samples.zip"
)
OUTPUT = ROOT / "output/build/legacy-diff-audit/m05-upload-samples"
MEMBERS = {
    "body.bmp": "\u5bfc\u51fa\u7684\u673a\u4f53/009\uff1a\u897f\u5965\u59ae/\u897f\u5965\u59ae[\u673a\u4f53].bmp",
    "fragment.bmp": "\u5bfc\u51fa\u7684\u673a\u4f53/009\uff1a\u897f\u5965\u59ae/\u897f\u5965\u59ae[\u788e\u7247].bmp",
    "icon.bmp": "\u5bfc\u51fa\u7684\u673a\u4f53/009\uff1a\u897f\u5965\u59ae/\u897f\u5965\u59ae[\u56fe\u68071].bmp",
}
EXPECTED_SIZE = {
    "body.bmp": (128, 128),
    "fragment.bmp": (128, 128),
    "icon.bmp": (16, 16),
}


def bmp_size(payload: bytes) -> tuple[int, int]:
    if len(payload) < 26 or payload[:2] != b"BM":
        raise ValueError("legacy upload fixture is not a BMP")
    width, height = struct.unpack_from("<ii", payload, 18)
    return width, abs(height)


def prepare() -> dict[str, object]:
    if not ARCHIVE.is_file():
        raise FileNotFoundError(ARCHIVE)
    OUTPUT.mkdir(parents=True, exist_ok=True)
    files: dict[str, object] = {}
    with zipfile.ZipFile(ARCHIVE) as archive:
        for filename, member in MEMBERS.items():
            payload = archive.read(member)
            dimensions = bmp_size(payload)
            if dimensions != EXPECTED_SIZE[filename]:
                raise ValueError(
                    f"{member} dimensions differ: {dimensions} != {EXPECTED_SIZE[filename]}"
                )
            target = OUTPUT / filename
            target.write_bytes(payload)
            files[filename] = {
                "source_member": member,
                "bytes": len(payload),
                "dimensions": list(dimensions),
                "sha256": hashlib.sha256(payload).hexdigest(),
            }
    manifest = {
        "archive": ARCHIVE.relative_to(ROOT).as_posix(),
        "archive_sha256": hashlib.sha256(ARCHIVE.read_bytes()).hexdigest(),
        "files": files,
    }
    (OUTPUT / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    return manifest


if __name__ == "__main__":
    print(json.dumps(prepare(), ensure_ascii=False, indent=2))
