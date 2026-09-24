from __future__ import annotations

import os
import unittest
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication, QDialog

from dc_modifier.app import DEFAULT_ROM
from dc_modifier.event_instruction_dialog import (
    EventCodeDialog,
    EventInstructionDialog,
)
from dc_modifier.legacy_windows import ScenarioDialog
from fc_rom_editor_core import RomProject

from tests.qt_test_case import QtTestCase


class EventInstructionDialogTests(QtTestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.application = QApplication.instance() or QApplication([])

    def test_three_pages_match_reference_numbering_and_expose_commands(self) -> None:
        dialog = EventInstructionDialog(bytes.fromhex("00 01"))
        self.assertEqual(dialog.tabs.count(), 3)
        self.assertEqual(
            [dialog.tabs.tabText(index) for index in range(3)],
            ["1", "2", "3"],
        )
        for opcode in range(0x7B):
            self.assertIn(opcode, dialog.opcode_buttons)
        self.assertTrue(dialog.meaning_help.text())
        dialog.tabs.setCurrentIndex(2)
        action_texts = {
            button.text() for button in set(dialog.opcode_buttons.values())
        }
        self.assertIn("31/32/33HP增减（行动）", action_texts)
        self.assertIn("51/52开关操作", action_texts)
        self.assertIn("59/5A/5B播放音乐", action_texts)
        self.assertIn("67/68更换阵营（行动）", action_texts)

    def test_opcode_palette_preserves_fixed_slot_and_parameters(self) -> None:
        dialog = EventInstructionDialog(bytes.fromhex("00 07"))
        dialog._choose_opcode(0x01)
        self.assertEqual(dialog.raw(), bytes.fromhex("01 07"))
        dialog.terminal.setChecked(True)
        self.assertEqual(dialog.raw(), bytes.fromhex("81 07"))

    def test_code_editor_rejects_wrong_length_and_accepts_valid_code(self) -> None:
        dialog = EventCodeDialog(bytes.fromhex("00 01"), 2)
        dialog.code_edit.setText("00")
        self.assertFalse(
            dialog.buttons.button(dialog.buttons.StandardButton.Ok).isEnabled()
        )
        dialog.code_edit.setText("01 02")
        self.assertTrue(
            dialog.buttons.button(dialog.buttons.StandardButton.Ok).isEnabled()
        )
        self.assertEqual(dialog.raw(), bytes.fromhex("01 02"))

    def test_setup_right_click_editor_applies_dialog_result(self) -> None:
        project = RomProject.load(DEFAULT_ROM)
        window = ScenarioDialog(project, initial_scenario_id=0)
        window.show()
        self.application.processEvents()
        page = next(
            candidate
            for candidate in window.setup_event_pages
            if candidate._instructions and len(candidate._instructions[0].raw) == 2
        )
        instruction = page._instructions[0]
        replacement = bytes((instruction.raw[0], instruction.raw[1] ^ 1))
        before = bytes(project.working)

        with (
            patch.object(EventInstructionDialog, "exec", return_value=QDialog.DialogCode.Accepted),
            patch.object(EventInstructionDialog, "raw", return_value=replacement),
        ):
            window._open_advanced_editor(page, "事件指令编辑")

        self.assertNotEqual(bytes(project.working), before)
        self.assertEqual(
            bytes(project.working)[instruction.file_offset : instruction.file_offset + 2],
            replacement,
        )
        window.reject()

    def test_setup_event_panel_does_not_embed_an_instruction_editor(self) -> None:
        project = RomProject.load(DEFAULT_ROM)
        window = ScenarioDialog(project, initial_scenario_id=0)
        window.show()
        self.application.processEvents()
        self.assertFalse(hasattr(window, "setup_event_editors"))
        self.assertFalse(hasattr(window, "setup_event_edit_buttons"))
        window.reject()


if __name__ == "__main__":
    unittest.main()
