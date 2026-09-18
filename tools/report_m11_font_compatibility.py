from __future__ import annotations

import argparse
from datetime import datetime
import hashlib
import json
from pathlib import Path
import sys
import tempfile


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from fc_editor.codecs.dc_font import (  # noqa: E402
    FULL_FONT_PAYLOAD_SIZE,
    decode_full_font_file,
    encode_full_font_file,
    font_tokens,
    full_font_payload,
    glyph_file_offset,
    glyphs_from_full_payload,
    safe_unmapped_tokens,
)
from fc_editor.dc_text import default_dc_text_table  # noqa: E402
from fc_rom_editor_core import RomProject  # noqa: E402


DEFAULT_ROM = ROOT / "output" / "rom" / "DC_kuorong_464K.nes"
DEFAULT_REPORT = ROOT / "output" / "verification" / "m11-font-compatibility.json"
EXPECTED_ROM_SHA256 = (
    "82C218275459D53C0F306F6BC036C4797316976E0FA7AD1D5A8247E338995B8E"
)


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest().upper()


def analyze(rom_path: Path) -> dict[str, object]:
    data = rom_path.read_bytes()
    rom_sha256 = _sha256(data)
    tokens = font_tokens()
    payload = full_font_payload(data)
    glyphs = glyphs_from_full_payload(payload)
    candidates = safe_unmapped_tokens(
        data,
        set(default_dc_text_table().byte_to_text),
    )
    candidate = candidates[0]
    custom_mappings = {candidate: "龘"}
    archive = encode_full_font_file(glyphs, custom_mappings)
    decoded_glyphs, decoded_mappings = decode_full_font_file(archive)

    project = RomProject.load(rom_path)
    before = bytes(project.working)
    changed_glyph = bytes(range(18))
    with project.transaction("M11 报告探针"):
        project.set_font_glyphs({candidate: changed_glyph})
        project.replace_font_character_overrides(custom_mappings)
    after = bytes(project.working)
    changed_offsets = tuple(
        index for index, (old, new) in enumerate(zip(before, after)) if old != new
    )
    candidate_offset = glyph_file_offset(candidate, writable=True)
    padding_offsets = tuple(
        glyph_file_offset(bytes((lead, row * 16)), writable=True) + 252
        for lead in (0xB8, 0xB9, 0xBA, 0xBB, 0xC8, 0xC9, 0xCA, 0xCB, 0xD8, 0xD9, 0xDA, 0xDB)
        for row in range(16)
    )
    padding_preserved = all(
        before[offset : offset + 4] == after[offset : offset + 4]
        for offset in padding_offsets
    )
    project.undo()
    undo_restored = (
        bytes(project.working) == before
        and not project.font_character_overrides
    )
    project.redo()
    redo_restored = (
        bytes(project.working) == after
        and project.font_character_overrides == custom_mappings
    )
    with tempfile.TemporaryDirectory() as directory:
        project_path = Path(directory) / "m11-probe.dcmod"
        project.save_project(project_path)
        reopened = RomProject.load_project(project_path, rom_path)
        project_reopen_ok = (
            bytes(reopened.working) == after
            and reopened.font_character_overrides == custom_mappings
            and reopened.dc_text_table().encode("龘") == candidate
        )

    checks = {
        "supported_rom_hash": rom_sha256 == EXPECTED_ROM_SHA256,
        "all_2688_independent_glyphs_extracted": (
            len(tokens) == 2688 and len(payload) == FULL_FONT_PAYLOAD_SIZE
        ),
        "full_font_archive_roundtrip": (
            decoded_glyphs == glyphs
            and decoded_mappings == custom_mappings
            and encode_full_font_file(decoded_glyphs, decoded_mappings) == archive
        ),
        "safe_slot_count_and_first_token": (
            len(candidates) == 76 and candidate == bytes.fromhex("BAE3")
        ),
        "safe_slots_are_unmapped_uniform_and_unreferenced": all(
            token not in default_dc_text_table().byte_to_text
            and data.count(token) == 0
            and len(
                set(
                    data[
                        glyph_file_offset(token, writable=True) :
                        glyph_file_offset(token, writable=True) + 18
                    ]
                )
            ) == 1
            for token in candidates
        ),
        "single_glyph_probe_changes_only_target": (
            changed_offsets
            and min(changed_offsets) >= candidate_offset
            and max(changed_offsets) < candidate_offset + 18
        ),
        "all_row_padding_preserved": padding_preserved,
        "glyph_and_mapping_are_one_undo_transaction": undo_restored and redo_restored,
        "project_reopen_preserves_mapping_and_glyph": project_reopen_ok,
    }
    return {
        "generated_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "passed": all(checks.values()),
        "rom": {
            "path": rom_path.resolve().relative_to(ROOT).as_posix(),
            "size": len(data),
            "sha256": rom_sha256,
        },
        "font": {
            "pages": 12,
            "independent_glyphs": len(tokens),
            "glyph_bytes": 18,
            "payload_bytes": len(payload),
            "safe_unmapped_slots": len(candidates),
            "first_safe_token": candidate.hex().upper(),
            "first_safe_file_offset": f"0x{candidate_offset:06X}",
            "safe_tokens": [token.hex().upper() for token in candidates],
        },
        "full_font_file": {
            "extension": ".dcfontset",
            "format_version": 1,
            "archive_bytes": len(archive),
            "archive_sha256": _sha256(archive),
            "payload_bytes": FULL_FONT_PAYLOAD_SIZE,
            "custom_mapping_count": len(custom_mappings),
        },
        "probe": {
            "token": candidate.hex().upper(),
            "changed_byte_count": len(changed_offsets),
            "changed_range": (
                f"0x{min(changed_offsets):06X}-0x{max(changed_offsets):06X}"
                if changed_offsets
                else "none"
            ),
            "padding_regions_checked": len(padding_offsets),
        },
        "checks": checks,
        "limitations": [
            "自动分配只使用内置码表未占用、全 ROM 中 Token 零出现、且字模为统一填充值的槽位；不自动回收任何已分配槽。",
            "自定义字符到 Token 的关系是编辑工程元数据，游戏 ROM 只保存字模和正文 Token；单独打开 ROM 时需同时打开 .dcmod 或导入 .dcfontset 才能恢复 Unicode 名称。",
            ".dcfontset 是新修改器的版本化超集协议；参考程序可见窗口没有自动分配或字体文件控件，不能宣称与未知参考文件协议字节级一致。",
        ],
    }


def main() -> int:
    parser = argparse.ArgumentParser(
        description="验证 M11 固定字模、保守自动编码和全字库文件协议。"
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
