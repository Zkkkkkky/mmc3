from __future__ import annotations

import os
import unittest
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

from dc_modifier.app import DEFAULT_ROM
from dc_modifier.legacy_windows import ScenarioDialog
from fc_editor.codecs.chapter_victory import (
    CHAPTER_VICTORY_COUNT,
    CHAPTER_VICTORY_HEADER,
    ChapterVictoryCodec,
)
from fc_editor.codecs.story_text import StoryTextCodec
from fc_rom_editor_core import RomProject

from tests.qt_test_case import QtTestCase


class ChapterVictoryCodecTests(unittest.TestCase):
    def setUp(self) -> None:
        self.project = RomProject.load(DEFAULT_ROM)

    def test_verified_playable_records_round_trip(self) -> None:
        codec = self.project.chapter_victory_codec
        self.assertIsNotNone(codec)
        assert codec is not None
        self.assertEqual(codec.count, CHAPTER_VICTORY_COUNT)
        self.assertEqual(codec.records[0].file_offset, 0x7A010)
        for scenario_id in range(codec.count):
            record = self.project.get_chapter_victory(scenario_id)
            self.assertTrue(record.raw.startswith(CHAPTER_VICTORY_HEADER))
            self.assertEqual(
                StoryTextCodec.standalone_terminator_end(record.raw),
                len(record.raw),
            )
            self.assertTrue(codec.round_trip(scenario_id))
            if scenario_id:
                previous = codec.records[scenario_id - 1]
                self.assertEqual(
                    record.file_offset,
                    previous.file_offset + previous.capacity,
                )

    def test_equal_size_body_write_is_undoable_and_adjacent_safe(self) -> None:
        record = self.project.get_chapter_victory(0)
        following = self.project.get_chapter_victory(1).raw
        replacement = record.body[2:4] + record.body[2:]
        self.assertEqual(len(replacement), record.body_capacity)

        self.project.set_chapter_victory_body(0, replacement)

        self.assertEqual(self.project.get_chapter_victory(0).body, replacement)
        self.assertEqual(self.project.get_chapter_victory(1).raw, following)
        self.assertTrue(self.project.can_undo)
        self.project.undo()
        self.assertEqual(self.project.get_chapter_victory(0).body, record.body)
        self.assertEqual(self.project.get_chapter_victory(1).raw, following)

    def test_length_change_and_embedded_terminator_are_rejected(self) -> None:
        record = self.project.get_chapter_victory(0)
        with self.assertRaisesRegex(ValueError, "必须保持当前记录容量"):
            self.project.set_chapter_victory_body(0, record.body + b"\x00")
        embedded = b"\xFF" + record.body[1:]
        with self.assertRaisesRegex(ValueError, "不能包含独立 FF"):
            self.project.set_chapter_victory_body(0, embedded)


class ChapterVictoryUiTests(QtTestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.application = QApplication.instance() or QApplication([])

    def setUp(self) -> None:
        self.project = RomProject.load(DEFAULT_ROM)
        self.widgets = []

    def tearDown(self) -> None:
        for widget in self.widgets:
            widget.hide()
            widget.deleteLater()
        self.application.processEvents()

    def show(self, widget):
        self.widgets.append(widget)
        widget.show()
        self.application.processEvents()
        return widget

    def test_editor_is_bound_to_selected_chapter_record(self) -> None:
        dialog = self.show(ScenarioDialog(self.project, initial_scenario_id=0))
        record = self.project.get_chapter_victory(0)
        expected = dialog._victory_editor_text(
            self.project.dc_text_table().decode(record.body)
        )
        self.assertFalse(dialog.initial_victory.isReadOnly())
        self.assertEqual(dialog.initial_victory.toPlainText(), expected)
        self.assertIn("0x", hex(record.file_offset))
        self.assertIn(str(record.body_capacity), dialog.initial_victory_status.text())

    def test_valid_victory_draft_commits_before_chapter_switch(self) -> None:
        dialog = self.show(ScenarioDialog(self.project, initial_scenario_id=0))
        original = self.project.get_chapter_victory(0)
        source = dialog.initial_victory.toPlainText()
        self.assertGreaterEqual(len(source), 2)
        changed = source[1] + source[1:]
        normalized = dialog._victory_encoded_text(changed)
        expected = self.project.dc_text_table().encode_preserving_tokens(
            original.body,
            normalized,
        )
        self.assertEqual(len(expected), original.body_capacity)

        dialog.initial_victory.setPlainText(changed)
        dialog.chapter_list.setCurrentRow(1)
        self.application.processEvents()

        self.assertEqual(self.project.get_chapter_victory(0).body, expected)
        self.assertEqual(dialog.current_scenario_id, 1)
        self.assertFalse(dialog._victory_dirty)

    def test_invalid_victory_draft_blocks_chapter_switch(self) -> None:
        dialog = self.show(ScenarioDialog(self.project, initial_scenario_id=0))
        original = self.project.get_chapter_victory(0).raw
        dialog.initial_victory.setPlainText(
            dialog.initial_victory.toPlainText() + "。"
        )
        self.assertTrue(dialog._victory_dirty)

        with patch("dc_modifier.legacy_windows.QMessageBox.warning") as warning:
            dialog.chapter_list.setCurrentRow(1)
            self.application.processEvents()

        warning.assert_called_once()
        self.assertEqual(dialog.current_scenario_id, 0)
        self.assertEqual(dialog.chapter_list.currentRow(), 0)
        self.assertEqual(self.project.get_chapter_victory(0).raw, original)
        self.assertTrue(dialog._victory_dirty)


if __name__ == "__main__":
    unittest.main()
