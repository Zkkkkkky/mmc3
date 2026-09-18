from __future__ import annotations

from dataclasses import asdict
from datetime import datetime
import argparse
import hashlib
import json
from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from fc_editor.codecs.animation import (  # noqa: E402
    AnimationCodec,
    decode_sprite_composition,
    decode_sprite_timeline,
)


DEFAULT_ROM = ROOT / "output" / "rom" / "DC_kuorong_464K.nes"
DEFAULT_REPORT = ROOT / "output" / "verification" / "m12-animation-compatibility.json"
INTERPRETER_OFFSET = 16 + 62 * 0x2000 + (0xD194 - 0xC000)
INTERPRETER_SIGNATURE = bytes.fromhex(
    "86 1F BD 00 07 85 07 29 20 85 0C BD 20 07 85 12 "
    "A5 07 29 04 F0 08 A5 07 29 01 D0 02 A9 FF"
)
PUZZLE_SAMPLE = bytes.fromhex(
    "08 00 18 00 08 F4 00 08 F4 00 08 F8 00 28 1E F8 "
    "80 A8 1C F8 80 A8 1A FC 80 A8 18 FC 80 80 FF"
)


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest().upper()


def analyze(rom_path: Path) -> dict[str, object]:
    data = rom_path.read_bytes()
    codec = AnimationCodec(data)
    compositions = []
    for index in range(codec.count("sprite")):
        record = codec.record("sprite", index)
        compositions.append(
            decode_sprite_composition(record.raw, record.offset)
        )
    roles = codec.movement_roles()
    frame_rules = sorted(
        index for index, role in roles.items() if role == {"frames"}
    )
    timelines = {
        index: decode_sprite_timeline(
            codec.record("movement", index).raw,
            codec.count("sprite"),
        )
        for index in frame_rules
    }
    sample = decode_sprite_composition(PUZZLE_SAMPLE)
    first = codec.record("sprite", 0)
    changed = bytes(((first.raw[0] + 1) & 0xFF, first.raw[1])) + first.raw[2:]
    anchor_patch = codec.rule_patch(first, changed)
    unresolved_records = [
        index
        for index, composition in enumerate(compositions)
        if any(tile.tile_index is None for tile in composition.placements)
    ]
    incomplete_timelines = {
        f"{index:02X}": timeline.error
        for index, timeline in timelines.items()
        if not timeline.complete
    }
    checks = {
        "interpreter_signature": (
            data[
                INTERPRETER_OFFSET : INTERPRETER_OFFSET
                + len(INTERPRETER_SIGNATURE)
            ]
            == INTERPRETER_SIGNATURE
        ),
        "six_table_counts": {
            kind: codec.count(kind)
            for kind in ("map", "ally", "enemy", "background", "movement", "sprite")
        }
        == {
            "map": 153,
            "ally": 256,
            "enemy": 256,
            "background": 106,
            "movement": 157,
            "sprite": 249,
        },
        "all_sprite_records_complete": all(
            composition.complete for composition in compositions
        ),
        "sample_matches_16_tile_walk": (
            sample.complete
            and len(sample.placements) == 16
            and (sample.anchor_x, sample.anchor_y) == (8, 0)
            and (sample.placements[0].x, sample.placements[0].y) == (8, 0)
            and (sample.placements[-1].x, sample.placements[-1].y) == (16, 56)
            and sample.placements[-1].vertical_flip
        ),
        "anchor_patch_is_first_byte_only": (
            anchor_patch[0] == first.offset
            and anchor_patch[1] == first.raw
            and anchor_patch[2][1:] == first.raw[1:]
        ),
        "frame_rules_classified": len(frame_rules) == 81,
        "offline_timelines_complete_or_explicit_runtime_dependency": (
            set(incomplete_timelines) == {"12", "21"}
            and all(timeline.frames for timeline in timelines.values())
        ),
    }
    passed = all(checks.values())
    return {
        "generated_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "passed": passed,
        "rom": {
            "path": rom_path.resolve().relative_to(ROOT).as_posix(),
            "size": len(data),
            "sha256": _sha256(data),
        },
        "evidence": {
            "renderer_cpu_range": "$D194-$D2EF",
            "renderer_file_offset": f"0x{INTERPRETER_OFFSET:06X}",
            "table_counts": {
                kind: codec.count(kind)
                for kind in ("map", "ally", "enemy", "background", "movement", "sprite")
            },
            "sprite_records": len(compositions),
            "complete_sprite_records": sum(item.complete for item in compositions),
            "runtime_tile_records": [f"{index:02X}" for index in unresolved_records],
            "frame_rules": len(frame_rules),
            "offline_complete_frame_rules": sum(
                timeline.complete for timeline in timelines.values()
            ),
            "runtime_dependent_frame_rules": incomplete_timelines,
            "sample": {
                "raw": PUZZLE_SAMPLE.hex(" ").upper(),
                "anchor": [sample.anchor_x, sample.anchor_y],
                "placements": [asdict(item) for item in sample.placements],
            },
            "anchor_patch": {
                "offset": f"0x{anchor_patch[0]:06X}",
                "before": anchor_patch[1].hex(" ").upper(),
                "after": anchor_patch[2].hex(" ").upper(),
            },
        },
        "checks": checks,
        "limitations": [
            "13 个组图记录含 $F0-$FF 运行时图块令牌；预览明确画为未解析占位，不猜测 RAM 表。",
            "运行规律 $12 的循环次数来自运行时参数，$21 会切换运行时指针页；两项保留明确门禁。",
            "预览图库、00/80 映射和整图翻转只影响可视验证，不写 ROM。",
        ],
    }


def main() -> int:
    parser = argparse.ArgumentParser(
        description="复验 M12 组图解释器、物理拼图和离线播放边界。"
    )
    parser.add_argument("--rom", type=Path, default=DEFAULT_ROM)
    parser.add_argument("--report", type=Path, default=DEFAULT_REPORT)
    arguments = parser.parse_args()
    report = analyze(arguments.rom)
    arguments.report.parent.mkdir(parents=True, exist_ok=True)
    arguments.report.write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
