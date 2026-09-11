from __future__ import annotations

import os
import unittest
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication

from dc_modifier.app import DEFAULT_ROM
from dc_modifier.event_page import EventPage
from dc_modifier.legacy_windows import ScenarioDialog
from dc_modifier.story_page import StoryPage
from fc_rom_editor_core import RomProject


from tests.qt_test_case import QtTestCase


class ScenarioFeedbackTests(QtTestCase):
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

    def test_global_tabs_do_not_inherit_chapter_context_or_selection(self) -> None:
        dialog = self.show(ScenarioDialog(self.project, initial_scenario_id=0))
        action_addresses = tuple(
            item.address for item in dialog.action_event_page._visible_instructions()
        )
        persuasion_slot = dialog.persuasion_page.current_slot
        self.assertTrue(dialog.persuasion_page.advanced_panel.isHidden())
        self.assertTrue(dialog.persuasion_page.table.isColumnHidden(4))
        for index in (1, 2, 4, 5):
            dialog.tabs.setCurrentIndex(index)
            self.assertTrue(dialog.chapter_context.isHidden())
        dialog.chapter_list.setCurrentRow(5)
        self.assertEqual(dialog.persuasion_page.current_slot, persuasion_slot)
        self.assertIsNone(dialog.action_event_page.scenario_filter.currentData())
        self.assertEqual(
            tuple(item.address for item in dialog.action_event_page._visible_instructions()),
            action_addresses,
        )
        dialog.tabs.setCurrentIndex(3)
        self.assertFalse(dialog.chapter_context.isHidden())
        self.assertEqual(dialog.map_event_page.scenario_filter.currentData(), 5)
        self.assertLess(dialog.minimumWidth(), dialog.maximumWidth())

    def test_story_overview_selects_groups_and_searches_full_body(self) -> None:
        dialog = self.show(ScenarioDialog(self.project))
        selector = dialog.story_overview_list_group_selector
        self.assertEqual(selector.count(), dialog.story_page.selector.count())
        selector.setCurrentIndex(1)
        self.assertEqual(dialog.story_page.current_selector, selector.currentData())
        overview = dialog.story_overview_list
        item = overview.item(0)
        self.assertNotIn("指针", item.text())
        self.assertIn("指针", item.toolTip())
        dialog.story_overview_list_search.setText("没有这种文本_不存在")
        self.assertTrue(all(overview.item(i).isHidden() for i in range(overview.count())))
        dialog.story_overview_list_search.clear()
        self.assertTrue(all(not overview.item(i).isHidden() for i in range(overview.count())))

    def test_story_group_switch_preserves_invalid_draft_and_outer_selection(self) -> None:
        dialog = self.show(ScenarioDialog(self.project))
        page = dialog.story_page
        old_selector = page.current_selector
        page.raw.setPlainText("GZ")
        with patch.object(page, "show_error") as warning:
            dialog.story_overview_list_group_selector.setCurrentIndex(1)
        warning.assert_called_once()
        self.assertEqual(page.current_selector, old_selector)
        self.assertEqual(dialog.story_overview_list_group_selector.currentData(), old_selector)
        self.assertEqual(page.raw.toPlainText(), "GZ")

    def test_story_default_editor_prioritizes_text_and_keeps_token_access(self) -> None:
        page = self.show(StoryPage())
        page.set_project(self.project)
        self.assertTrue(page.advanced_panel.isHidden())
        self.assertIs(page.editor_tabs.currentWidget(), page.decoded)
        page.advanced_toggle.setChecked(True)
        self.assertFalse(page.advanced_panel.isHidden())
        self.assertGreater(page.tokens.rowCount(), 0)
        page.editor_tabs.setCurrentWidget(page.raw)
        page.focus_text_editor()
        self.assertIs(page.editor_tabs.currentWidget(), page.decoded)

    def event_page(self) -> EventPage:
        page = self.show(EventPage())
        page.set_project(self.project)
        page.kind_filter.setCurrentIndex(page.kind_filter.findText("全部指令（专家）"))
        return page

    def test_unlabelled_parameters_roundtrip_without_phantom_changes(self) -> None:
        page = self.event_page()
        instruction = next(item for item in page._instructions if item.opcode == 0x51)
        page._select_address(instruction.address)
        self.assertFalse(page.has_pending_draft)
        self.assertIn("语义未验证", page.parameter_labels[0].text())
        page.parameters[0].setValue(instruction.parameters[0] ^ 1)
        self.assertTrue(page.has_pending_draft)
        page.copy_instruction()
        expected = bytes((instruction.raw[0], instruction.parameters[0] ^ 1))
        self.assertEqual(QApplication.clipboard().text(), expected.hex(" ").upper())
        self.assertTrue(page.commit_pending_changes())
        changed = self.project.chapter_event_codec.instruction_at(instruction.address, self.project.working)
        self.assertEqual(changed.raw, expected)
        self.project.undo()
        restored = self.project.chapter_event_codec.instruction_at(instruction.address, self.project.working)
        self.assertEqual(restored.raw, instruction.raw)

    def test_event_paste_is_equal_length_draft_until_explicit_apply(self) -> None:
        page = self.event_page()
        instruction = next(item for item in page._instructions if item.opcode == 0x51)
        page._select_address(instruction.address)
        before = bytes(self.project.working)
        expected = bytes((instruction.raw[0], instruction.parameters[0] ^ 1))
        QApplication.clipboard().setText(expected.hex(" ").upper())
        page.paste_instruction()
        self.assertTrue(page.has_pending_draft)
        self.assertFalse(page.advanced_panel.isHidden())
        self.assertEqual(bytes(self.project.working), before)
        self.assertTrue(page.commit_pending_changes())
        self.assertNotEqual(bytes(self.project.working), before)

    def test_event_paste_rejects_multiple_instructions_and_invalid_length(self) -> None:
        page = self.event_page()
        instruction = next(item for item in page._instructions if item.opcode == 0x51)
        page._select_address(instruction.address)
        before = bytes(self.project.working)
        for text in ("51 00 01", "71 72", "GG"):
            QApplication.clipboard().setText(text)
            with patch.object(page, "show_error") as warning:
                page.paste_instruction()
            warning.assert_called_once()
            self.assertFalse(page.has_pending_draft)
            self.assertEqual(bytes(self.project.working), before)

    def test_parameter_draft_cannot_change_variable_instruction_length(self) -> None:
        page = self.event_page()
        instruction = next(item for item in page._instructions if item.opcode == 0x43)
        page._select_address(instruction.address)
        before = bytes(self.project.working)
        page.parameters[0].setValue(0 if len(instruction.raw) == 3 else 0x0B)
        self.assertTrue(page.has_pending_draft)
        self.assertIn("必须保持原槽", page.pending_draft_error or "")
        self.assertFalse(page.commit_pending_changes())
        self.assertEqual(bytes(self.project.working), before)


if __name__ == "__main__":
    unittest.main()
