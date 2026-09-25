from __future__ import annotations

import os
import unittest
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import (
    QApplication, QComboBox, QDialog, QDialogButtonBox, QLabel, QSpinBox,
)

from dc_modifier.app import DEFAULT_ROM
from dc_modifier.event_instruction_dialog import (
    EventCodeDialog,
    EventInstructionDialog,
    EventParameterDialog,
)
from dc_modifier.event_preview import reference_event_preview
from fc_editor.codecs.action_event import ActionEventInstruction
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
        reference_opcodes = (
            set(range(0x00, 0x17))
            | {0x18, 0x19, 0x1A, 0x1B, 0x1C, 0x1D, 0x1E, 0x1F, 0x20,
               0x21, 0x22, 0x23, 0x24, 0x25, 0x26, 0x36}
            | {0x30, 0x31, 0x32, 0x33, 0x34, 0x35, 0x38, 0x39, 0x3A,
               0x3B, 0x3C, 0x3D, 0x3E, 0x3F}
            | set(range(0x40, 0x5F))
            | set(range(0x60, 0x75))
            | {0xDF}
        )
        for opcode in reference_opcodes:
            self.assertIn(opcode, dialog.opcode_buttons)
        self.assertFalse(hasattr(dialog, "meaning_help"))
        self.assertFalse(hasattr(dialog, "parameters"))
        self.assertFalse(hasattr(dialog, "terminal"))
        self.assertIsNone(
            dialog.buttons.button(QDialogButtonBox.StandardButton.Ok)
        )
        dialog.tabs.setCurrentIndex(2)
        action_texts = {
            button.text() for button in set(dialog.opcode_buttons.values())
        }
        self.assertIn("31/32/33HP增减（行动）", action_texts)
        self.assertIn("51/52开关操作", action_texts)
        self.assertIn("59/5A/5B播放音乐", action_texts)
        self.assertIn("67/68更换阵营（行动）", action_texts)

    def test_event_preview_uses_reference_natural_language(self) -> None:
        jump = ActionEventInstruction(3, 0xA010, 0, bytes.fromhex("57 20 A0"))
        music = ActionEventInstruction(4, 0xA013, 0, bytes.fromhex("59 88"))
        text = ActionEventInstruction(5, 0xA015, 0, bytes.fromhex("44 00 01"))
        self.assertEqual(
            reference_event_preview(jump, index=3, address_rows={0xA020: 23}),
            "003: 是：转：023",
        )
        self.assertEqual(
            reference_event_preview(music, index=4),
            "004: 播放我方地图音乐：地球我方音乐",
        )
        self.assertEqual(
            reference_event_preview(text, index=5, story_summary=lambda _item: "测试文字"),
            "005: 文字显示：内容:测试文字",
        )

    def test_opcode_palette_opens_separate_parameter_dialog(self) -> None:
        dialog = EventInstructionDialog(bytes.fromhex("00 07"))
        with (
            patch.object(EventParameterDialog, "exec", return_value=QDialog.DialogCode.Accepted),
            patch.object(EventParameterDialog, "raw", return_value=bytes.fromhex("81 07")),
        ):
            dialog._choose_opcode(0x01)
        self.assertEqual(dialog.raw(), bytes.fromhex("81 07"))

    def test_reference_page_order_and_variable_window_opcode_are_available(self) -> None:
        dialog = EventInstructionDialog(
            bytes.fromhex("DF"), allow_variable_length=True
        )
        self.assertEqual(dialog._default_raw(0x4B), bytes.fromhex("4B 00 00 00 00 00 00"))
        self.assertEqual(dialog._default_raw(0x43), bytes.fromhex("43 00"))
        self.assertTrue(dialog.opcode_buttons[0x43].isEnabled())

    def test_named_operands_use_dropdowns_and_numbers_remain_spinners(self) -> None:
        project = RomProject.load(DEFAULT_ROM)
        reinforcement = EventParameterDialog(
            bytes.fromhex("4B 05 06 04 20 0A 01"), project=project
        )
        self.assertIsInstance(reinforcement.parameters[0], QSpinBox)
        self.assertIsInstance(reinforcement.parameters[2], QComboBox)
        self.assertIn(
            project.character_display_name(4),
            reinforcement.parameters[2].currentText(),
        )
        self.assertIsInstance(reinforcement.parameters[3], QComboBox)
        self.assertIn(
            project.unit_display_name(0x20),
            reinforcement.parameters[3].currentText(),
        )
        music = EventParameterDialog(bytes.fromhex("59 88"), project=project)
        self.assertIsInstance(music.parameters[0], QComboBox)
        self.assertIn("地球我方音乐", music.parameters[0].currentText())

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
            patch.object(EventParameterDialog, "exec", return_value=QDialog.DialogCode.Accepted),
            patch.object(EventParameterDialog, "raw", return_value=replacement),
        ):
            window._open_advanced_editor(page, "事件指令编辑")

        self.assertNotEqual(bytes(project.working), before)
        self.assertEqual(
            bytes(project.working)[instruction.file_offset : instruction.file_offset + 2],
            replacement,
        )
        window.reject()

    def test_existing_instruction_editor_is_separate_from_command_palette(self) -> None:
        dialog = EventParameterDialog(bytes.fromhex("5E 3C"))
        self.assertFalse(hasattr(dialog, "tabs"))
        self.assertEqual(dialog.windowTitle(), "事件参数修改")
        self.assertEqual(dialog.parameter_labels[0].text(), "等待帧数")
        self.assertIn("60 帧约为 1 秒", dialog.findChild(QLabel, "hintText").text())
        dialog.parameters[0].setValue(0x1E)
        self.assertEqual(dialog.raw(), bytes.fromhex("5E 1E"))

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
