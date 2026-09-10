from __future__ import annotations

import os
from pathlib import Path
import sys
from types import SimpleNamespace
import unittest
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication, QListWidget, QPushButton, QWidget

TOOLS = Path(__file__).resolve().parent
if str(TOOLS) not in sys.path:
    sys.path.insert(0, str(TOOLS))

from dc_modifier.app import DEFAULT_ROM
from dc_modifier.legacy_windows import DatabaseDialog, ScenarioDialog
from fc_rom_editor_core import RomProject


class LegacyWindowTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.application = QApplication.instance() or QApplication([])
        if not DEFAULT_ROM.is_file():
            raise unittest.SkipTest(f"缺少界面测试ROM：{DEFAULT_ROM}")

    def setUp(self) -> None:
        self.project = RomProject.load(DEFAULT_ROM)
        self.dialogs = []

    def tearDown(self) -> None:
        for dialog in self.dialogs:
            dialog.hide()
            dialog.deleteLater()
        self.application.processEvents()

    def _show(self, dialog):
        self.dialogs.append(dialog)
        dialog.show()
        self.application.processEvents()
        return dialog

    @staticmethod
    def _change_one_unit_value(dialog: DatabaseDialog) -> None:
        page = dialog.unit_page
        assert page.current_id is not None
        for editor in page.fields.values():
            value = editor.value()
            if value < editor.maximum():
                editor.setValue(value + 1)
                break
            if value > editor.minimum():
                editor.setValue(value - 1)
                break
        else:
            raise AssertionError("没有可修改的机体字段")
        page.apply_record()

    def test_database_has_all_six_reference_tabs(self) -> None:
        dialog = self._show(DatabaseDialog(self.project))
        self.assertEqual(dialog.tabs.count(), 6)
        self.assertEqual(
            [dialog.tabs.tabText(index) for index in range(dialog.tabs.count())],
            list(DatabaseDialog.TAB_LABELS),
        )
        self.assertEqual(dialog.ok_button.text(), "确定")
        self.assertEqual(dialog.cancel_button.text(), "取消")

    def test_unit_tab_uses_reference_list_and_real_chr_icon_preview(self) -> None:
        dialog = self._show(DatabaseDialog(self.project))
        page = dialog.unit_page
        self.assertTrue(page.records.item(0).text().startswith("[01]001: "))
        self.assertIn("background: #000000", page.body_preview.styleSheet())
        icon = page.icon_preview.pixmap()
        self.assertIsNotNone(icon)
        assert icon is not None
        self.assertFalse(icon.isNull())
        self.assertTrue(page.icon_address.text())
        disabled_actions = {
            button.text(): button
            for button in page.findChildren(QPushButton)
            if button.text() in {"上传机体", "清除机体", "上传碎片", "清除碎片"}
        }
        self.assertEqual(len(disabled_actions), 4)
        self.assertTrue(all(not button.isEnabled() for button in disabled_actions.values()))

    def test_scenario_has_six_tabs_and_three_nested_event_tabs(self) -> None:
        dialog = self._show(ScenarioDialog(self.project))
        self.assertEqual(dialog.tabs.count(), 6)
        self.assertEqual(
            [dialog.tabs.tabText(index) for index in range(dialog.tabs.count())],
            list(ScenarioDialog.TAB_LABELS),
        )
        self.assertEqual(dialog.setup_event_tabs.count(), 3)
        self.assertEqual(
            [
                dialog.setup_event_tabs.tabText(index)
                for index in range(dialog.setup_event_tabs.count())
            ],
            list(ScenarioDialog.EVENT_TAB_LABELS),
        )
        self.assertTrue(
            all(
                isinstance(dialog.setup_event_tabs.widget(index).findChild(QListWidget), QListWidget)
                for index in range(dialog.setup_event_tabs.count())
            )
        )
        self.assertTrue(all(page.isHidden() for page in dialog.setup_event_pages))
        self.assertTrue(dialog.action_event_page.isHidden())
        self.assertTrue(dialog.map_event_page.isHidden())
        title_pixmap = dialog.title_preview.pixmap()
        self.assertIsNotNone(title_pixmap)
        assert title_pixmap is not None
        self.assertFalse(title_pixmap.isNull())
        shared_context = dialog.chapter_context
        dialog.tabs.setCurrentIndex(4)
        self.application.processEvents()
        self.assertIs(shared_context.parentWidget(), dialog._splitters[4])

    def test_scenario_open_does_not_manufacture_unknown_opcode_drafts(self) -> None:
        dialog = self._show(ScenarioDialog(self.project, initial_scenario_id=0))
        self.assertTrue(all(not page.has_pending_draft for page in dialog.pages))

    def test_scenario_inherits_explicit_and_parent_map_chapter(self) -> None:
        explicit = self._show(ScenarioDialog(self.project, initial_scenario_id=5))
        self.assertEqual(explicit.current_scenario_id, 5)
        self.assertEqual(
            explicit.chapter_list.currentItem().data(Qt.ItemDataRole.UserRole),
            5,
        )
        for page in (*explicit.setup_event_pages, explicit.action_event_page, explicit.map_event_page):
            self.assertEqual(page.scenario_filter.currentData(), 5)

        parent = QWidget()
        parent.map_page = SimpleNamespace(current_map_id=7)
        inherited = self._show(ScenarioDialog(self.project, parent))
        self.assertEqual(inherited.current_scenario_id, 7)
        parent.deleteLater()

    def test_scenario_chapter_focus_does_not_modify_persuasion_rule(self) -> None:
        rules_before = tuple(
            self.project.get_persuasion_rule(slot).raw
            for slot in range(self.project.persuasion_rule_codec.spec.editable_count)
        )
        target_slot = 0
        target_scenario = self.project.get_persuasion_rule(target_slot).scenario_id
        dialog = self._show(
            ScenarioDialog(self.project, initial_scenario_id=target_scenario)
        )
        self.assertEqual(dialog.persuasion_page.current_slot, target_slot)
        selected_rule = self.project.get_persuasion_rule(target_slot)
        self.assertEqual(
            dialog.persuasion_page.chapter.currentData(), selected_rule.scenario_id
        )

        different_row = 0 if target_scenario != 0 else 1
        dialog.chapter_list.setCurrentRow(different_row)
        self.application.processEvents()
        rules_after = tuple(
            self.project.get_persuasion_rule(slot).raw
            for slot in range(self.project.persuasion_rule_codec.spec.editable_count)
        )
        self.assertEqual(rules_after, rules_before)

    def test_scenario_direct_ok_commits_hidden_event_editor_draft(self) -> None:
        dialog = self._show(ScenarioDialog(self.project, initial_scenario_id=0))
        page, instruction = next(
            (page, instruction)
            for page in dialog.setup_event_pages
            if (instruction := page._selected_instruction()) is not None
            and len(instruction.raw) > 1
        )
        replacement = bytearray(instruction.raw)
        replacement[-1] ^= 0x01
        before = bytes(self.project.working)
        page.raw.setText(bytes(replacement).hex(" ").upper())
        self.assertTrue(page.has_pending_draft)

        dialog.accept()

        self.assertEqual(dialog.result(), dialog.DialogCode.Accepted)
        self.assertNotEqual(bytes(self.project.working), before)

    def test_scenario_chapter_switch_commits_valid_hidden_event_draft(self) -> None:
        dialog = self._show(ScenarioDialog(self.project, initial_scenario_id=0))
        page, instruction = next(
            (page, instruction)
            for page in dialog.setup_event_pages
            if (instruction := page._selected_instruction()) is not None
            and len(instruction.raw) > 1
        )
        replacement = bytearray(instruction.raw)
        replacement[-1] ^= 0x01
        page.raw.setText(bytes(replacement).hex(" ").upper())
        self.assertTrue(page.has_pending_draft)

        target_row = 1
        target_scenario = dialog.chapter_list.item(target_row).data(
            Qt.ItemDataRole.UserRole
        )
        dialog.chapter_list.setCurrentRow(target_row)
        self.application.processEvents()

        changed = self.project.chapter_event_codec.instruction_at(
            instruction.address, bytes(self.project.working)
        )
        self.assertEqual(changed.raw, bytes(replacement))
        self.assertFalse(page.has_pending_draft)
        self.assertEqual(dialog.current_scenario_id, target_scenario)
        self.assertEqual(
            dialog.chapter_list.currentItem().data(Qt.ItemDataRole.UserRole),
            target_scenario,
        )
        for event_page in (
            *dialog.setup_event_pages,
            dialog.action_event_page,
            dialog.map_event_page,
        ):
            self.assertEqual(event_page.scenario_filter.currentData(), target_scenario)

    def test_scenario_chapter_switch_blocks_invalid_hidden_event_draft(self) -> None:
        dialog = self._show(ScenarioDialog(self.project, initial_scenario_id=0))
        page = next(
            page
            for page in dialog.setup_event_pages
            if page._selected_instruction() is not None
        )
        old_scenario = dialog.current_scenario_id
        page.raw.setText("GG")
        self.assertTrue(page.has_pending_draft)
        self.assertIsNotNone(page.pending_draft_error)
        self.assertIn("#b42318", page.pending_state.styleSheet())

        with patch("dc_modifier.legacy_windows.QMessageBox.warning") as warning:
            dialog.chapter_list.setCurrentRow(1)
            self.application.processEvents()

        warning.assert_called_once()
        self.assertEqual(dialog.current_scenario_id, old_scenario)
        self.assertEqual(
            dialog.chapter_list.currentItem().data(Qt.ItemDataRole.UserRole),
            old_scenario,
        )
        self.assertEqual(page.scenario_filter.currentData(), old_scenario)
        self.assertEqual(page.raw.text(), "GG")

    def test_scenario_persuasion_overview_commits_draft_before_switch(self) -> None:
        dialog = self._show(ScenarioDialog(self.project, initial_scenario_id=0))
        page = dialog.persuasion_page
        old_slot = page.current_slot
        self.assertIsNotNone(old_slot)
        assert old_slot is not None
        original = self.project.get_persuasion_rule(old_slot)
        changed_scenario = (original.scenario_id + 1) % 0x20
        page.chapter.setCurrentIndex(page.chapter.findData(changed_scenario))
        self.assertTrue(page.has_pending_draft)

        target_row = next(
            row
            for row in range(dialog.persuasion_overview_list.count())
            if dialog.persuasion_overview_list.item(row).data(
                Qt.ItemDataRole.UserRole
            )
            != old_slot
        )
        target_slot = dialog.persuasion_overview_list.item(target_row).data(
            Qt.ItemDataRole.UserRole
        )
        dialog.persuasion_overview_list.setCurrentRow(target_row)
        self.application.processEvents()

        self.assertEqual(
            self.project.get_persuasion_rule(old_slot).scenario_id,
            changed_scenario,
        )
        self.assertFalse(page.has_pending_draft)
        self.assertEqual(page.current_slot, target_slot)
        self.assertEqual(
            dialog.persuasion_overview_list.currentItem().data(
                Qt.ItemDataRole.UserRole
            ),
            target_slot,
        )

    def test_scenario_story_overview_commits_draft_before_switch(self) -> None:
        dialog = self._show(ScenarioDialog(self.project, initial_scenario_id=0))
        page = dialog.story_page
        overview = dialog.story_overview_list
        old_selector = page.current_selector
        old_index = page.current_index
        self.assertIsNotNone(old_selector)
        self.assertIsNotNone(old_index)
        assert old_selector is not None and old_index is not None
        original = self.project.get_story_text(old_selector, old_index).raw
        self.assertTrue(original)
        replacement = bytes((original[0] ^ 0x01,)) + original[1:]
        page.raw.setPlainText(replacement.hex(" ").upper())
        self.assertTrue(page.has_pending_draft)
        self.assertIsNone(page.pending_draft_error)

        target_row = next(
            row
            for row in range(overview.count())
            if overview.item(row).data(Qt.ItemDataRole.UserRole) != old_index
        )
        target_index = overview.item(target_row).data(Qt.ItemDataRole.UserRole)
        overview.setCurrentRow(target_row)
        self.application.processEvents()

        self.assertEqual(
            self.project.get_story_text(old_selector, old_index).raw,
            replacement,
        )
        self.assertFalse(page.has_pending_draft)
        self.assertEqual(page.current_index, target_index)
        self.assertEqual(
            overview.currentItem().data(Qt.ItemDataRole.UserRole), target_index
        )

    def test_scenario_victory_overview_blocks_invalid_draft(self) -> None:
        dialog = self._show(ScenarioDialog(self.project, initial_scenario_id=0))
        page = dialog.victory_page
        overview = dialog.victory_overview_list
        old_index = page.current_index
        self.assertIsNotNone(old_index)
        page.raw.setPlainText("0")
        self.assertTrue(page.has_pending_draft)
        self.assertIsNotNone(page.pending_draft_error)

        target_row = next(
            row
            for row in range(overview.count())
            if overview.item(row).data(Qt.ItemDataRole.UserRole) != old_index
        )
        with patch("dc_modifier.legacy_windows.QMessageBox.warning") as warning:
            overview.setCurrentRow(target_row)
            self.application.processEvents()

        warning.assert_called_once()
        self.assertEqual(page.current_index, old_index)
        self.assertEqual(
            overview.currentItem().data(Qt.ItemDataRole.UserRole), old_index
        )
        self.assertEqual(page.raw.toPlainText(), "0")

    def test_scenario_cancel_rolls_back_advanced_event_write(self) -> None:
        dialog = self._show(ScenarioDialog(self.project, initial_scenario_id=0))
        page, instruction = next(
            (page, instruction)
            for page in dialog.setup_event_pages
            if (instruction := page._selected_instruction()) is not None
            and len(instruction.raw) > 1
        )
        replacement = bytearray(instruction.raw)
        replacement[-1] ^= 0x01
        before = bytes(self.project.working)
        page.raw.setText(bytes(replacement).hex(" ").upper())
        page.apply_raw_button.click()
        self.assertNotEqual(bytes(self.project.working), before)

        dialog.reject()

        self.assertEqual(bytes(self.project.working), before)

    def test_cancel_restores_bytes_and_history_after_real_unit_edit(self) -> None:
        dialog = self._show(DatabaseDialog(self.project))
        before = bytes(self.project.working)
        undo_count = len(self.project._undo_stack)
        self._change_one_unit_value(dialog)
        self.assertNotEqual(bytes(self.project.working), before)
        self.assertGreater(len(self.project._undo_stack), undo_count)

        dialog.reject()

        self.assertEqual(bytes(self.project.working), before)
        self.assertEqual(len(self.project._undo_stack), undo_count)

    def test_accept_preserves_real_unit_edit(self) -> None:
        dialog = self._show(DatabaseDialog(self.project))
        before = bytes(self.project.working)
        self._change_one_unit_value(dialog)
        accepted = bytes(self.project.working)
        self.assertNotEqual(accepted, before)

        dialog.accept()

        self.assertEqual(bytes(self.project.working), accepted)
        self.assertNotEqual(bytes(self.project.working), before)

    def test_accept_commits_current_unit_form_without_staging_click(self) -> None:
        dialog = self._show(DatabaseDialog(self.project))
        before = bytes(self.project.working)
        page = dialog.unit_page
        for editor in page.fields.values():
            if editor.value() < editor.maximum():
                editor.setValue(editor.value() + 1)
                break
            if editor.value() > editor.minimum():
                editor.setValue(editor.value() - 1)
                break
        else:
            self.fail("没有可修改的机体字段")
        self.assertTrue(page.apply_button.isEnabled())

        dialog.accept()

        self.assertEqual(dialog.result(), dialog.DialogCode.Accepted)
        self.assertNotEqual(bytes(self.project.working), before)

    def test_accept_keeps_dialog_open_for_invalid_current_form(self) -> None:
        dialog = self._show(DatabaseDialog(self.project))
        dialog.unit_page.name_reference.setCurrentIndex(-1)

        with patch("dc_modifier.legacy_windows.QMessageBox.warning") as warning:
            dialog.accept()

        warning.assert_called_once()
        self.assertTrue(dialog.isVisible())
        self.assertNotEqual(dialog.result(), dialog.DialogCode.Accepted)


if __name__ == "__main__":
    unittest.main()
