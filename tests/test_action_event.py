from __future__ import annotations

import os
import unittest
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

from dc_modifier.app import DEFAULT_ROM
from dc_modifier.legacy_windows import ScenarioDialog
from fc_editor.codecs.action_event import (
    ACTION_EVENT_CAPACITY,
    ACTION_EVENT_DATA_END,
    ACTION_EVENT_DATA_START,
    ACTION_EVENT_JUMP_OPCODES,
)
from fc_rom_editor_core import RomProject

from tests.qt_test_case import QtTestCase


class ActionEventCodecTests(unittest.TestCase):
    def setUp(self) -> None:
        self.project = RomProject.load(DEFAULT_ROM)

    @staticmethod
    def _semantic_signature(record) -> tuple[tuple[int, bytes | int], ...]:
        return tuple(
            (
                instruction.raw_opcode,
                int.from_bytes(instruction.raw[1:3], "little") - record.pointer
                if instruction.opcode in ACTION_EVENT_JUMP_OPCODES
                else instruction.raw[1:],
            )
            for instruction in record.instructions
        )

    def test_verified_independent_table_decodes_all_256_actions(self) -> None:
        self.assertTrue(self.project.supports_action_events)
        records = tuple(self.project.get_action_event(item) for item in range(0x100))
        self.assertEqual(len(records), 0x100)
        self.assertEqual(records[0].pointer, 0xA000)
        self.assertEqual(records[0].raw, bytes.fromhex("63 D5 00 A0"))
        self.assertEqual(records[0x2E].raw, b"\xDF")
        self.assertEqual(records[0xFF].pointer, records[3].pointer)
        self.assertEqual(records[0xFF].aliases, (3, 0xFF))

        starts = {
            instruction.address
            for record in records
            for instruction in record.instructions
        }
        for record in records:
            self.assertGreaterEqual(record.pointer, ACTION_EVENT_DATA_START)
            self.assertLess(record.pointer, ACTION_EVENT_DATA_END)
            for instruction in record.instructions:
                if instruction.opcode in ACTION_EVENT_JUMP_OPCODES:
                    self.assertIn(int.from_bytes(instruction.raw[1:3], "little"), starts)

        usage = self.project.action_event_usage()
        self.assertEqual(usage.capacity, ACTION_EVENT_CAPACITY)
        self.assertEqual(usage.used, 2541)
        self.assertEqual(usage.free, 210)
        self.assertEqual(usage.physical_records, 45)
        with self.assertRaises(IndexError):
            self.project.get_action_event(-1)
        with self.assertRaises(IndexError):
            self.project.get_action_event(0x100)

    def test_fixed_and_variable_length_edits_are_isolated_and_undoable(self) -> None:
        before = bytes(self.project.working)
        following = self._semantic_signature(self.project.get_action_event(2))
        self.project.set_action_event_instruction(0, 0, bytes.fromhex("E3"))
        self.assertEqual(self.project.get_action_event(0).instructions[0].raw, b"\xE3")
        self.assertEqual(
            self._semantic_signature(self.project.get_action_event(2)), following
        )
        self.project.undo()
        self.assertEqual(bytes(self.project.working), before)

        self.project.set_action_event_instruction(0, 0, bytes.fromhex("60 05"))
        changed = self.project.get_action_event(0)
        self.assertEqual(changed.instructions[0].raw, bytes.fromhex("60 05"))
        self.assertEqual(
            int.from_bytes(changed.instructions[1].raw[1:3], "little"),
            changed.pointer,
        )
        self.assertEqual(self.project.action_event_usage().free, 209)
        self.assertEqual(
            self._semantic_signature(self.project.get_action_event(2)), following
        )
        self.project.undo()
        self.assertEqual(bytes(self.project.working), before)

    def test_insert_delete_compacts_placeholders_and_relocates_jumps(self) -> None:
        before = bytes(self.project.working)
        first = self.project.get_action_event(0).instructions[0].raw
        self.project.insert_action_event_instruction(0, 0, first, after=True)
        record = self.project.get_action_event(0)
        self.assertEqual(record.raw, bytes.fromhex("63 63 D5 00 A0"))
        self.assertEqual(
            int.from_bytes(record.instructions[-1].raw[1:3], "little"),
            record.pointer,
        )
        self.assertEqual(
            self.project.get_action_event(0x2E).pointer,
            self.project.get_action_event(0x2F).pointer,
        )

        # A compacted placeholder can still be edited independently; the
        # codec splits only that logical ID from the shared empty script.
        self.project.set_action_event_instruction(0x2E, 0, b"\xE3")
        self.assertEqual(self.project.get_action_event(0x2E).raw, b"\xE3")
        self.assertEqual(self.project.get_action_event(0x2F).raw, b"\xDF")
        self.assertNotEqual(
            self.project.get_action_event(0x2E).pointer,
            self.project.get_action_event(0x2F).pointer,
        )
        self.project.undo()
        self.project.undo()
        self.assertEqual(bytes(self.project.working), before)

        action = self.project.get_action_event(2)
        self.project.delete_action_event_instruction(2, 1)
        self.assertEqual(
            len(self.project.get_action_event(2).instructions),
            len(action.instructions) - 1,
        )
        self.project.undo()
        self.assertEqual(bytes(self.project.working), before)

    def test_delete_that_breaks_record_boundary_is_atomic(self) -> None:
        before = bytes(self.project.working)
        with self.assertRaisesRegex(ValueError, "越过自身记录边界"):
            self.project.delete_action_event_instruction(0, 1)
        self.assertEqual(bytes(self.project.working), before)


class ActionEventUiTests(QtTestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.application = QApplication.instance() or QApplication([])

    def setUp(self) -> None:
        self.project = RomProject.load(DEFAULT_ROM)
        self.dialog = ScenarioDialog(self.project)
        self.dialog.show()
        self.application.processEvents()

    def tearDown(self) -> None:
        self.dialog.hide()
        self.dialog.deleteLater()
        self.application.processEvents()

    def test_action_tab_is_true_256_entry_table_with_reference_commands(self) -> None:
        page = self.dialog.action_event_page
        self.assertFalse(page.isHidden())
        self.assertEqual(page.action_list.count(), 0x100)
        self.assertEqual(page.copy_button.text(), "复制")
        self.assertEqual(page.paste_button.text(), "粘贴")
        self.assertEqual(page.insert_before_button.text(), "插入（接上）")
        self.assertEqual(page.insert_after_button.text(), "插入（接下）")
        self.assertIn("2541 / 2751", page.capacity_status.text())

    def test_variable_length_draft_commits_before_action_switch(self) -> None:
        page = self.dialog.action_event_page
        page.raw.setText("60 05")
        self.assertTrue(page.has_pending_draft)
        page.action_list.setCurrentRow(2)
        self.application.processEvents()
        self.assertEqual(
            self.project.get_action_event(0).instructions[0].raw,
            bytes.fromhex("60 05"),
        )
        self.assertEqual(page.current_action_id, 2)
        self.assertFalse(page.has_pending_draft)

    def test_invalid_draft_blocks_action_switch(self) -> None:
        page = self.dialog.action_event_page
        page.raw.setText("60")
        self.assertTrue(page.has_pending_draft)
        with patch("dc_modifier.pages.QMessageBox.critical") as warning:
            page.action_list.setCurrentRow(2)
            self.application.processEvents()
        warning.assert_called_once()
        self.assertEqual(page.current_action_id, 0)
        self.assertEqual(page.action_list.currentRow(), 0)


if __name__ == "__main__":
    unittest.main()
