from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from fc_editor.codecs.story_text import StoryTextCodec
from fc_rom_editor_core import RomProject


ROOT = Path(__file__).resolve().parents[1]
TARGET_ROM = ROOT / "output" / "rom" / "DC_kuorong_464K.nes"


class StoryIntegrityTests(unittest.TestCase):
    def test_standalone_terminator_scan_is_glyph_token_safe(self) -> None:
        # FF is data when it follows a confirmed two-byte Chinese glyph lead.
        self.assertIsNone(StoryTextCodec.standalone_terminator_end(b"\xB8\xFF"))
        self.assertEqual(
            StoryTextCodec.standalone_terminator_end(b"\xB8\xFF\x01\xFF"),
            4,
        )
        self.assertEqual(
            StoryTextCodec.standalone_terminator_end(b"\x01\xFF\x02"),
            2,
        )

    def test_direct_reopen_detects_missing_nonterminal_record_terminator(self) -> None:
        project = RomProject.load(TARGET_ROM)
        project.configure_expansion(304, 48, 112)

        # Index 00 is followed by other physical records.  Its embedded FF is
        # the second byte of a glyph and must not satisfy the terminator check.
        valid = b"\xB8\xFF\x01\xFF"
        project.set_story_text_raw(0x32, 0, valid)
        self.assertFalse(
            any(
                issue.severity == "error"
                and issue.module == "剧情"
                and "缺少独立 FF" in issue.message
                for issue in project.validate()
            )
        )

        record = project.get_story_text(0x32, 0)
        group = project.story_text_codec.group_by_selector[0x32]
        offset = StoryTextCodec.cpu_to_file_offset(group.prg_bank, record.pointer)
        self.assertEqual(bytes(project.working[offset : offset + len(valid)]), valid)
        project.working[offset + len(valid) - 1] = 0x00

        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "missing-story-terminator.nes"
            output.write_bytes(project.working)
            reopened = RomProject.load(output)
            errors = [
                issue
                for issue in reopened.validate()
                if issue.severity == "error" and issue.module == "剧情"
            ]

        self.assertTrue(
            any(
                "$32:00" in issue.message and "缺少独立 FF" in issue.message
                for issue in errors
            ),
            errors,
        )


if __name__ == "__main__":
    unittest.main(verbosity=2)
