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

    for key in "BCDEFG":
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

    manifest_path = output_dir / "generated-b-g.json"
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
    sample_specs = (
        ("A-color1.nes", "A", "color1", MapTileAttributeCodec.record_offset("A")),
        ("A-defense.nes", "A", "tile0.defense", MapTileAttributeCodec.record_offset("A") + 20),
        ("A-sea.nes", "A", "tile0.sea", MapTileAttributeCodec.record_offset("A") + 20),
        ("A-air_move.nes", "A", "tile0.air_move", MapTileAttributeCodec.record_offset("A") + 36),
        ("A-land_move.nes", "A", "tile0.land_move", MapTileAttributeCodec.record_offset("A") + 52),
        ("A-sea_move.nes", "A", "tile0.sea_move", MapTileAttributeCodec.record_offset("A") + 68),
        ("B-color1.nes", "B", "color1", MapTileAttributeCodec.record_offset("B")),
        *((f"{key}-color1.nes", key, "color1", MapTileAttributeCodec.record_offset(key)) for key in "CDEFG"),
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
    ui_sample_path = output_dir / "B-color1-ui.nes"
    ui_sample = ui_sample_path.read_bytes()
    ui_differences = [
        {
            "offset": offset,
            "before": f"{before:02X}",
            "after": f"{after:02X}",
        }
        for offset, (before, after) in enumerate(zip(base, ui_sample, strict=True))
        if before != after
    ]
    expected_ui_offsets = {
        MapTileAttributeCodec.record_offset("B"),
        MapTileAttributeCodec.record_offset("B") + 20 + 5,
    }
    if {item["offset"] for item in ui_differences} != expected_ui_offsets:
        raise RuntimeError(f"B-color1-ui.nes 差分异常：{ui_differences}")
    audit_path = output_dir / "field-diff-manifest.json"
    audit_path.write_text(
        json.dumps(
            {
                "base": base_path.name,
                "base_sha256": sha256(base_path),
                "samples": audited,
                "ui_observed_samples": [
                    {
                        "file": ui_sample_path.name,
                        "gallery": "B",
                        "requested_field": "color1",
                        "automatic_repair": "tile5.sea",
                        "changed_bytes": len(ui_differences),
                        "differences": ui_differences,
                        "sha256": sha256(ui_sample_path),
                    }
                ],
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
