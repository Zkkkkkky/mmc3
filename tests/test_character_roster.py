from __future__ import annotations

from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from dataclasses import replace

from dc_modifier.workspace import DEFAULT_ROM
from fc_editor.codecs.bank24_composite import character_count, parse
from fc_editor.codecs.character_attributes import CharacterAttributesCodec
from fc_editor.codecs.character_roster import addition_patches
from fc_editor.profiles import MMC5_PROFILE
from fc_rom_editor_core import RomProject


class CharacterRosterTests(unittest.TestCase):
    def setUp(self) -> None:
        self.project = RomProject.load(DEFAULT_ROM)

    def test_add_is_atomic_and_reopens_with_dynamic_count(self) -> None:
        before = bytes(self.project.working)
        new_id = self.project.add_character()
        self.assertEqual(new_id, 0xC9)
        self.assertEqual(character_count(self.project.working), 0xC9)
        logical = parse(self.project.working)
        self.assertEqual(logical.character_attributes[-1], b"\x00" * 6)
        self.assertEqual(logical.normal_names[-1], b"\xFF")
        self.assertEqual(logical.battle_names[-1], b"\xFF")
        codec = CharacterAttributesCodec(self.project)
        self.assertEqual(codec.record_bytes(new_id, portrait=True), b"\x00" * 5 + b"\xC0\x80")
        self.assertEqual(self.project.get_battle_music_binding(new_id - 1).attacker_command, 0)
        self.assertEqual(self.project.get_battle_music_binding(new_id - 1).defender_command, 0)
        self.assertEqual(
            self.project.character_dialogue_codec.raw_record(new_id, self.project.working),
            self.project.character_dialogue_codec.raw_record(new_id - 1, self.project.working),
        )

        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "added.nes"
            path.write_bytes(self.project.working)
            reopened = RomProject.load(path)
            self.assertEqual(reopened.character_count, 0xC9)
            self.assertEqual(reopened.character_normal_display_name(new_id), "空白/未分配人物槽")

        self.assertEqual(self.project.undo(), "新增人物 $C9")
        self.assertEqual(bytes(self.project.working), before)
        self.assertEqual(self.project.character_count, 0xC8)
        self.assertEqual(self.project.redo(), "新增人物 $C9")
        self.assertEqual(self.project.character_count, 0xC9)

    def test_multiple_adds_are_detected_after_reopen(self) -> None:
        self.assertEqual([self.project.add_character() for _ in range(3)], [0xC9, 0xCA, 0xCB])
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "three.nes"
            path.write_bytes(self.project.working)
            self.assertEqual(RomProject.load(path).character_count, 0xCB)

    def test_matches_two_process_legacy_add_golden_byte_for_byte(self) -> None:
        root = Path(__file__).resolve().parents[1]
        case = root / "output/build/legacy-diff-audit/cases/legacy_live/M06/character_add_overflow/cold_start_01"
        before_path = case / "before.nes"
        after_path = case / "after.nes"
        if not before_path.is_file() or not after_path.is_file():
            self.skipTest("缺少旧修改器新增人物黄金样本")
        working = bytearray(before_path.read_bytes())
        legacy_profile = replace(
            MMC5_PROFILE,
            character_dialogue_pointer_table_offset=0xD14C,
        )
        probe = SimpleNamespace(
            working=working,
            _base_character_profile=legacy_profile,
        )
        for offset, before, after in addition_patches(probe):
            self.assertEqual(bytes(working[offset:offset + len(before)]), before)
            working[offset:offset + len(after)] = after
        self.assertEqual(bytes(working), after_path.read_bytes())


if __name__ == "__main__":
    unittest.main()
