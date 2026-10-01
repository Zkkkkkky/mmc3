from __future__ import annotations

import hashlib
import json
import sys
from dataclasses import replace
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from fc_editor.codecs.map_tile_attribute import MapTileAttributeCodec  # noqa: E402


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest().upper()


def main() -> None:
    case_dir = (
        ROOT
        / "output"
        / "build"
        / "legacy-diff-audit"
        / "cases"
        / "manual_m02_new_only_20260915_01"
    )
    base_path = case_dir / "before.nes"
    output_dir = case_dir / "fields"
    output_dir.mkdir(parents=True, exist_ok=True)
    base = base_path.read_bytes()
    generated: list[dict[str, object]] = []

    for key in "ABCDEFGH":
        current = MapTileAttributeCodec.decode(base, key)
        after_color = (current.colors[0] + 1) & 0x3F
        updated = replace(
            current,
            colors=(after_color, current.colors[1], current.colors[2]),
        )
        patches = MapTileAttributeCodec.patches(base, key, updated)
        if len(patches) != 1:
            raise RuntimeError(f"图库 {key} 预期 1 个补丁，实际 {len(patches)} 个。")
        data = bytearray(base)
        for offset, before, after in patches:
            if data[offset : offset + len(before)] != before:
                raise RuntimeError(f"图库 {key} 补丁基线不匹配：{offset:#x}")
            data[offset : offset + len(after)] = after
        output_path = output_dir / f"{key}-color1.nes"
        output_path.write_bytes(data)
        decoded = MapTileAttributeCodec.decode(data, key)
        if decoded.colors[0] != after_color:
            raise RuntimeError(f"图库 {key} 写入后反解失败。")
        generated.append(
            {
                "gallery": key,
                "field": "color1",
                "offset": patches[0][0],
                "before": patches[0][1].hex().upper(),
                "after": patches[0][2].hex().upper(),
                "changed_bytes": len(patches),
                "file": output_path.name,
                "sha256": sha256(output_path),
            }
        )

    manifest_path = output_dir / "generated-a-h.json"
    manifest_path.write_text(
        json.dumps(
            {
                "base": base_path.name,
                "base_sha256": sha256(base_path),
                "generator": "MapTileAttributeCodec",
                "samples": generated,
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    sample_specs = tuple(
        (
            f"{key}-color1.nes",
            key,
            "color1",
            MapTileAttributeCodec.record_offset(key) + 80,
        )
        for key in "ABCDEFGH"
    )
    audited: list[dict[str, object]] = []
    for filename, gallery, field, expected_offset in sample_specs:
        sample_path = output_dir / filename
        sample = sample_path.read_bytes()
        differences = [
            {
                "offset": offset,
                "before": f"{before:02X}",
                "after": f"{after:02X}",
            }
            for offset, (before, after) in enumerate(zip(base, sample, strict=True))
            if before != after
        ]
        if len(differences) != 1 or differences[0]["offset"] != expected_offset:
            raise RuntimeError(
                f"{filename} 不是预期的单字段样本：{differences[:8]}"
            )
        MapTileAttributeCodec.decode(sample, gallery)
        audited.append(
            {
                "file": filename,
                "gallery": gallery,
                "field": field,
                "changed_bytes": 1,
                "difference": differences[0],
                "sha256": sha256(sample_path),
            }
        )
    audit_path = output_dir / "field-diff-manifest.json"
    audit_path.write_text(
        json.dumps(
            {
                "base": base_path.name,
                "base_sha256": sha256(base_path),
                "samples": audited,
                "rejected_legacy_sample": {
                    "file": "B-color1-ui.nes",
                    "reason": "旧产品按图形推断并旁写海属性，且记录分组错误；不再作为黄金样本。",
                },
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    print(manifest_path)
    print(audit_path)


if __name__ == "__main__":
    main()
