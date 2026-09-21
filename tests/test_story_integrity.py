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

    def test_split_selector_37_exposes_only_its_51_text_slots(self) -> None:
        project = RomProject.load(TARGET_ROM)
        codec = project.story_text_codec
        group = codec.group_by_selector[0x37]

        self.assertEqual(group.prg_bank, 0x0E)
        self.assertEqual(group.pointer_table, 0x9E28)
        self.assertEqual(group.count, 52)
        self.assertEqual((group.data_start, group.data_end), (0x9B4A, 0x9E28))
        self.assertEqual(codec.pointers(0x37)[0], 0x9E90)

        sentinel = project.get_story_text(0x37, 0)
        self.assertEqual((sentinel.raw, sentinel.capacity), (b"", 0))
        records = [project.get_story_text(0x37, index) for index in range(1, 52)]
        self.assertTrue(all(record.capacity > 0 for record in records))
        self.assertTrue(
            all(
                StoryTextCodec.standalone_terminator_end(record.raw)
                == record.capacity
                for record in records
            )
        )
        self.assertTrue(all(codec.round_trip(0x37, index) for index in range(52)))
        self.assertEqual(len(codec.ids_by_pointer(0x37)), 35)
        self.assertEqual(codec.ids_by_pointer(0x37)[0x9E26], tuple(range(34, 52)))

    def test_split_selector_37_stays_in_place_after_capacity_planning(self) -> None:
        project = RomProject.load(TARGET_ROM)
        project.configure_expansion(304, 48, 112)
        self.assertIsNone(project.expansion_plan.story_pair_for(0x37))

        before = bytes(project.working)
        record = project.get_story_text(0x37, 1)
        replacement = record.raw[:1] + bytes((record.raw[1] ^ 1,)) + record.raw[2:]
        self.assertEqual(
            project.story_text_replacement_usage(0x37, 1, replacement),
            (record.capacity, record.capacity),
        )
        project.set_story_text_raw(0x37, 1, replacement)
        changed = tuple(
            index
            for index, (old, new) in enumerate(
                zip(before, project.working, strict=True)
            )
            if old != new
        )
        expected = StoryTextCodec.cpu_to_file_offset(0x0E, record.pointer) + 1
        self.assertEqual(changed, (expected,))
        self.assertEqual(project.get_story_text(0x37, 1).raw, replacement)

        project.undo()
        self.assertEqual(bytes(project.working), before)
        with self.assertRaisesRegex(ValueError, "空/哨兵记录"):
            project.set_story_text_raw(0x37, 0, b"\xFF")
        self.assertEqual(bytes(project.working), before)


if __name__ == "__main__":
    unittest.main(verbosity=2)
