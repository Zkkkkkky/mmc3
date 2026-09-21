"""Create an isolated one-glyph ROM mutation and static verification report."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from fc_editor.codecs.dc_font import decode_glyph, encode_glyph, glyph_file_offset
from fc_rom_editor_core import RomProject


def main() -> None:
    source = ROOT / "output/rom/DC_kuorong_464K.nes"
    destination = ROOT / "output/verification/font-feedback"
    destination.mkdir(parents=True, exist_ok=True)
    source_bytes = source.read_bytes()
    project = RomProject.load(source)
    token = bytes.fromhex("DAC2")  # 伏, the first chapter-title glyph.
    offset = glyph_file_offset(token, writable=True)
    original = bytes(project.working[offset:offset + 18])
    pixels = [list(row) for row in decode_glyph(original)]
    pixels[0][0] ^= 1
    replacement = encode_glyph(pixels)
    project.set_font_glyphs({token: replacement})
    changed = [index for index, (before, after) in enumerate(
        zip(source_bytes, project.working, strict=True)) if before != after]
    assert changed == [offset]
    assert original[0] ^ replacement[0] == 0x80
    assert bytes(project.working[:16]) == source_bytes[:16]
    assert bytes(project.working[0x100010:]) == source_bytes[0x100010:]
    assert all((index - 16) // 0x2000 == (offset - 16) // 0x2000 for index in changed)
    output_rom = destination / "font_probe_DAC2.nes"
    project.save_as(output_rom, make_backup=False)
    reopened = RomProject.load(output_rom)
    assert bytes(reopened.working[offset:offset + 18]) == replacement
    project.undo()
    assert bytes(project.working) == source_bytes
    project.redo()
    assert bytes(project.working) == output_rom.read_bytes()
    assert source.read_bytes() == source_bytes
    report = {
        "source": str(source.relative_to(ROOT)),
        "source_sha256": hashlib.sha256(source_bytes).hexdigest().upper(),
        "derived": str(output_rom.relative_to(ROOT)),
        "derived_sha256": hashlib.sha256(output_rom.read_bytes()).hexdigest().upper(),
        "size": len(source_bytes),
        "token": token.hex().upper(),
        "glyph_file_offset": f"0x{offset:X}",
        "before": original.hex().upper(),
        "after": replacement.hex().upper(),
        "changed_file_offsets": [f"0x{value:X}" for value in changed],
        "changed_bits": 1,
        "header_unchanged": True,
        "active_chr_unchanged": True,
        "other_bytes_unchanged": True,
        "source_unchanged": True,
        "undo_redo_reopen_passed": True,
        "runtime_validation": "Run the existing tests/emulator/dc_mesen_smoke.lua on the derived ROM.",
        "scope": "Boot/audio smoke does not by itself prove the changed glyph was displayed by the game.",
    }
    (destination / "static-verification.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
