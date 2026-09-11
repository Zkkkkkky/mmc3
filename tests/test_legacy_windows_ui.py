from __future__ import annotations

import os
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication, QListWidget, QPushButton, QWidget

from dc_modifier.app import DEFAULT_ROM
from dc_modifier.legacy_windows import DatabaseDialog, ScenarioDialog
from fc_rom_editor_core import RomProject


from tests.qt_test_case import QtTestCase


class LegacyWindowTests(QtTestCase):
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

    def test_global_tables_load_all_verified_rom_defaults(self) -> None:
        project = RomProject.load(DEFAULT_ROM)
        dialog = self._show(DatabaseDialog(project))
        page = dialog.other_page_1

        experience = tuple(
            int(page.experience_table.item(row, 1).text())
            for row in range(page.experience_table.rowCount())
        )
        corrections = tuple(
            tuple(
                int(page.distance_table.item(row, column).text())
                for column in range(page.distance_table.columnCount())
            )
            for row in range(page.distance_table.rowCount())
        )

        self.assertEqual(len(experience), 99)
        self.assertEqual(experience, project.get_experience_totals())
        self.assertEqual(experience[:10], (20, 60, 120, 200, 300, 420, 560, 720, 900, 1100))
        self.assertEqual(experience[49], 15200)
        self.assertEqual(experience[97:], (64350, 65535))
        self.assertEqual(
            corrections,
            (
                (100,) * 16,
                (100, 98, 96, 94, 92, 90, 88, 86, 84, 82, 80, 78, 76, 74, 72, 70),
                (100, 95, 90, 85, 80, 75, 70, 65, 60, 55, 50, 45, 40, 35, 30, 25),
                (100, 90, 80, 70, 60, 50, 40, 30, 20, 10, 9, 8, 7, 6, 5, 4),
            ),
        )

    def test_database_ok_commits_global_table_drafts_and_undo_restores_both(self) -> None:
        project = RomProject.load(DEFAULT_ROM)
        dialog = self._show(DatabaseDialog(project))
        dialog.tabs.setCurrentWidget(dialog.other_page_1)
        page = dialog.other_page_1
        original_experience = project.get_experience_totals()
        original_corrections = project.get_distance_hit_corrections()

        page.experience_table.item(49, 1).setText("15201")
        page.distance_table.item(3, 15).setText("5")
        self.application.processEvents()
        self.assertTrue(page.has_pending_draft)
        self.assertTrue(page.apply_button.isEnabled())

        dialog.accept()

        self.assertEqual(dialog.result(), dialog.DialogCode.Accepted)
        self.assertEqual(project.get_experience_totals()[49], 15201)
        self.assertEqual(project.get_distance_hit_corrections()[3][15], 5)
        self.assertEqual(project.undo_description, "升级经验与距离命中补正")
        self.assertEqual(project.undo(), "升级经验与距离命中补正")
        self.assertEqual(project.get_experience_totals(), original_experience)
        self.assertEqual(project.get_distance_hit_corrections(), original_corrections)

    def test_database_ok_blocks_invalid_global_cell_and_preserves_draft(self) -> None:
        project = RomProject.load(DEFAULT_ROM)
        before = bytes(project.working)
        dialog = self._show(DatabaseDialog(project))
        dialog.tabs.setCurrentWidget(dialog.other_page_1)
        page = dialog.other_page_1
        page.experience_table.item(0, 1).setText("不是数字")
        self.application.processEvents()
        self.assertTrue(page.has_pending_draft)
        self.assertIsNotNone(page.pending_draft_error)

        with patch("dc_modifier.legacy_windows.QMessageBox.warning") as warning:
            dialog.accept()

        warning.assert_called_once()
        self.assertTrue(dialog.isVisible())
        self.assertNotEqual(dialog.result(), dialog.DialogCode.Accepted)
        self.assertEqual(bytes(project.working), before)
        self.assertEqual(page.experience_table.item(0, 1).text(), "不是数字")
        self.assertTrue(page.has_pending_draft)

    def test_item_table_loads_all_24_verified_names_and_display_prices(self) -> None:
        project = RomProject.load(DEFAULT_ROM)
        dialog = self._show(DatabaseDialog(project))
        page = dialog.other_page_2

        self.assertEqual(page.item_table.rowCount(), 24)
        displayed_names = tuple(
            page.item_table.item(row, 1).text() for row in range(24)
        )
        displayed_prices = tuple(
            int(page.item_table.item(row, 2).text()) for row in range(24)
        )
        self.assertTrue(all(displayed_names))
        self.assertEqual(
            displayed_names,
            tuple(
                page._text_table.decode(raw_name)
                for raw_name in project.get_item_name_records()
            ),
        )
        self.assertFalse(page.has_pending_draft)
        self.assertEqual(
            displayed_prices,
            tuple(value * 10 for value in project.get_item_prices()),
        )
        self.assertEqual(
            displayed_prices,
            (
                4000, 5000, 4000, 5000, 12000, 20000, 18880, 12000,
                15000, 10000, 28000, 6000, 20000, 18000, 12000, 1000,
                4000, 10000, 1000, 5000, 99990, 99990, 99990, 99990,
            ),
        )

    def test_database_ok_commits_item_names_and_price_as_one_undo_entry(self) -> None:
        project = RomProject.load(DEFAULT_ROM)
        original_names = project.get_item_name_records()
        original_prices = project.get_item_prices()
        dialog = self._show(DatabaseDialog(project))
        dialog.tabs.setCurrentWidget(dialog.other_page_2)
        page = dialog.other_page_2
        first_name = page.item_table.item(0, 1).text()
        second_name = page.item_table.item(1, 1).text()
        page.item_table.item(0, 1).setText(second_name)
        page.item_table.item(1, 1).setText(first_name)
        page.item_table.item(0, 2).setText("4010")
        self.application.processEvents()
        self.assertTrue(page.has_pending_draft)
        self.assertIsNone(page.pending_draft_error)

        dialog.accept()

        self.assertEqual(dialog.result(), dialog.DialogCode.Accepted)
        self.assertEqual(
            project.get_item_name_records()[:2],
            (original_names[1], original_names[0]),
        )
        self.assertEqual(project.get_item_prices()[0], 401)
        self.assertEqual(project.undo_description, "道具名称与价格")
        self.assertEqual(project.undo(), "道具名称与价格")
        self.assertEqual(project.get_item_name_records(), original_names)
        self.assertEqual(project.get_item_prices(), original_prices)

    def test_database_ok_blocks_invalid_item_price_and_preserves_draft(self) -> None:
        project = RomProject.load(DEFAULT_ROM)
        before = bytes(project.working)
        dialog = self._show(DatabaseDialog(project))
        dialog.tabs.setCurrentWidget(dialog.other_page_2)
        page = dialog.other_page_2
        page.item_table.item(0, 2).setText("4001")
        self.application.processEvents()
        self.assertTrue(page.has_pending_draft)
        self.assertIn("10的倍数", page.pending_draft_error or "")

        with patch("dc_modifier.legacy_windows.QMessageBox.warning") as warning:
            dialog.accept()

        warning.assert_called_once()
        self.assertTrue(dialog.isVisible())
        self.assertNotEqual(dialog.result(), dialog.DialogCode.Accepted)
        self.assertEqual(bytes(project.working), before)
        self.assertEqual(page.item_table.item(0, 2).text(), "4001")
        self.assertTrue(page.has_pending_draft)

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
        self.assertTrue(shared_context.isHidden())
        dialog.tabs.setCurrentIndex(3)
        self.assertIs(shared_context.parentWidget(), dialog._splitters[3])
        self.assertFalse(shared_context.isHidden())

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
        for page in (*explicit.setup_event_pages, explicit.map_event_page):
            self.assertEqual(page.scenario_filter.currentData(), 5)
        self.assertIsNone(explicit.action_event_page.scenario_filter.currentData())

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

    def test_scenario_ok_blocks_two_drafts_for_one_real_event_address(self) -> None:
        dialog = self._show(ScenarioDialog(self.project, initial_scenario_id=0))
        first_page = dialog.setup_event_pages[0]
        second_page = dialog.setup_event_pages[2]
        shared_address = 0xA0C0
        self.assertTrue(first_page._select_address(shared_address))
        self.assertTrue(second_page._select_address(shared_address))
        first = first_page._selected_instruction()
        second = second_page._selected_instruction()
        self.assertIsNotNone(first)
        self.assertIsNotNone(second)
        assert first is not None and second is not None
        self.assertEqual(first.address, shared_address)
        self.assertEqual(second.address, shared_address)
        self.assertEqual(first.raw, second.raw)

        first_replacement = first.raw[:-1] + bytes((first.raw[-1] ^ 0x01,))
        second_replacement = second.raw[:-1] + bytes((second.raw[-1] ^ 0x02,))
        first_page.raw.setText(first_replacement.hex(" ").upper())
        second_page.raw.setText(second_replacement.hex(" ").upper())
        self.assertTrue(first_page.has_pending_draft)
        self.assertTrue(second_page.has_pending_draft)
        self.assertIn("$A0C0", first_page.pending_draft_error or "")
        self.assertIn("多个编辑页", second_page.pending_draft_error or "")
        before = bytes(self.project.working)
        undo_count = len(self.project._undo_stack)
        self.assertFalse(first_page.commit_pending_changes())
        self.assertEqual(bytes(self.project.working), before)
        self.assertEqual(first_page.raw.text(), first_replacement.hex(" ").upper())
        self.assertEqual(second_page.raw.text(), second_replacement.hex(" ").upper())

        with patch("dc_modifier.legacy_windows.QMessageBox.warning") as warning:
            dialog.accept()

        warning.assert_called_once()
        self.assertTrue(dialog.isVisible())
        self.assertNotEqual(dialog.result(), dialog.DialogCode.Accepted)
        self.assertEqual(bytes(self.project.working), before)
        self.assertEqual(len(self.project._undo_stack), undo_count)
        self.assertEqual(first_page.raw.text(), first_replacement.hex(" ").upper())
        self.assertEqual(second_page.raw.text(), second_replacement.hex(" ").upper())
        self.assertTrue(first_page.has_pending_draft)
        self.assertTrue(second_page.has_pending_draft)

        # Reset is the deliberate escape hatch advertised by the conflict
        # message: discard one local draft without applying either competing
        # replacement, then the remaining draft can be committed normally.
        first_page.reset_button.click()
        self.assertFalse(first_page.has_pending_draft)
        self.assertTrue(second_page.has_pending_draft)
        self.assertIsNone(second_page.pending_draft_error)
        self.assertEqual(bytes(self.project.working), before)
        self.assertEqual(len(self.project._undo_stack), undo_count)

        dialog.accept()
        self.assertEqual(dialog.result(), dialog.DialogCode.Accepted)
        changed = self.project.chapter_event_codec.instruction_at(
            shared_address,
            bytes(self.project.working),
        )
        self.assertEqual(changed.raw, second_replacement)

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
            dialog.map_event_page,
        ):
            self.assertEqual(event_page.scenario_filter.currentData(), target_scenario)
        self.assertIsNone(dialog.action_event_page.scenario_filter.currentData())

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

    def test_story_unicode_draft_commits_before_record_switch(self) -> None:
        dialog = self._show(ScenarioDialog(self.project, initial_scenario_id=0))
        page = dialog.story_page
        old_selector = page.current_selector
        old_index = page.current_index
        self.assertIsNotNone(old_selector)
        self.assertIsNotNone(old_index)
        assert old_selector is not None and old_index is not None
        assert page.text_table is not None
        original_text = page.decoded.toPlainText()
        self.assertIn("！", original_text)
        changed_text = original_text.replace("！", ".", 1)
        replacement = page.text_table.encode(changed_text)

        page.decoded.setPlainText(changed_text)
        self.assertTrue(page.has_pending_draft)
        self.assertIsNone(page.pending_draft_error)

        target_row = next(
            row
            for row in range(page.indices.count())
            if page.indices.item(row).data(Qt.ItemDataRole.UserRole) != old_index
        )
        target_index = page.indices.item(target_row).data(Qt.ItemDataRole.UserRole)
        page.indices.setCurrentRow(target_row)
        self.application.processEvents()

        self.assertEqual(
            self.project.get_story_text(old_selector, old_index).raw,
            replacement,
        )
        self.assertFalse(page.has_pending_draft)
        self.assertEqual(page.current_index, target_index)

    def test_story_unicode_edit_preserves_untouched_real_alias_tokens(self) -> None:
        dialog = self._show(ScenarioDialog(self.project, initial_scenario_id=0))
        page = dialog.story_page
        selector = 0x32
        record_index = 10
        selector_row = page.selector.findData(selector)
        self.assertGreaterEqual(selector_row, 0)
        page.selector.setCurrentIndex(selector_row)
        target_row = next(
            row
            for row in range(page.indices.count())
            if page.indices.item(row).data(Qt.ItemDataRole.UserRole) == record_index
        )
        page.indices.setCurrentRow(target_row)
        self.application.processEvents()

        assert page.text_table is not None
        original = self.project.get_story_text(selector, record_index).raw
        original_text = page.decoded.toPlainText()
        self.assertNotEqual(page.text_table.encode(original_text), original)
        self.assertEqual(original.count(bytes.fromhex("C8 89")), 2)
        changed_text = original_text.replace("退", "走", 1)
        changed_token_offset = original.index(bytes.fromhex("DA 17"))
        expected = (
            original[:changed_token_offset]
            + page.text_table.encode("走")
            + original[changed_token_offset + 2 :]
        )

        page.decoded.setPlainText(changed_text)

        self.assertTrue(page.has_pending_draft)
        self.assertIsNone(page.pending_draft_error)
        self.assertEqual(page._pending_replacement(), expected)
        self.assertEqual(page._pending_replacement().count(bytes.fromhex("C8 89")), 2)

        dialog.accept()

        self.assertEqual(
            self.project.get_story_text(selector, record_index).raw,
            expected,
        )
        self.assertEqual(self.project.undo(), "剧情文本 $32:0A")
        self.assertEqual(
            self.project.get_story_text(selector, record_index).raw,
            original,
        )

    def test_story_unicode_revert_to_same_text_reuses_entire_raw_record(self) -> None:
        dialog = self._show(ScenarioDialog(self.project, initial_scenario_id=0))
        page = dialog.story_page
        selector = 0x32
        record_index = 10
        page.selector.setCurrentIndex(page.selector.findData(selector))
        target_row = next(
            row
            for row in range(page.indices.count())
            if page.indices.item(row).data(Qt.ItemDataRole.UserRole) == record_index
        )
        page.indices.setCurrentRow(target_row)
        self.application.processEvents()

        assert page.text_table is not None
        original = self.project.get_story_text(selector, record_index).raw
        original_text = page.decoded.toPlainText()
        self.assertNotEqual(page.text_table.encode(original_text), original)

        page.decoded.setPlainText(original_text.replace("退", "走", 1))
        self.assertTrue(page.has_pending_draft)
        page.decoded.setPlainText(original_text)

        self.assertFalse(page.has_pending_draft)
        self.assertEqual(page._pending_replacement(), original)
        page.encode_decoded_text()
        self.assertFalse(page.has_pending_draft)
        self.assertEqual(page._pending_replacement(), original)
        self.assertEqual(
            page._parse_hex(page.raw.toPlainText()).count(bytes.fromhex("C8 89")),
            2,
        )
        before = bytes(self.project.working)
        dialog.accept()
        self.assertEqual(bytes(self.project.working), before)
        self.assertFalse(self.project.can_undo)

    def test_story_dual_source_drafts_block_without_losing_either_input(self) -> None:
        dialog = self._show(ScenarioDialog(self.project, initial_scenario_id=0))
        page = dialog.story_page
        selector = 0x32
        record_index = 10
        page.selector.setCurrentIndex(page.selector.findData(selector))
        target_row = next(
            row
            for row in range(page.indices.count())
            if page.indices.item(row).data(Qt.ItemDataRole.UserRole) == record_index
        )
        page.indices.setCurrentRow(target_row)
        self.application.processEvents()

        assert page.text_table is not None
        original = self.project.get_story_text(selector, record_index).raw
        original_text = page.decoded.toPlainText()
        changed_text = original_text.replace("退", "走", 1)
        changed_token_offset = original.index(bytes.fromhex("DA 17"))
        expected = (
            original[:changed_token_offset]
            + page.text_table.encode("走")
            + original[changed_token_offset + 2 :]
        )
        page.decoded.setPlainText(changed_text)
        formatted_raw = page.raw.toPlainText() + " "
        page.raw.setPlainText(formatted_raw)

        self.assertTrue(page.has_pending_draft)
        self.assertIsNone(page.pending_draft_error)
        self.assertEqual(page.decoded.toPlainText(), changed_text)
        self.assertEqual(page.raw.toPlainText(), formatted_raw)
        self.assertEqual(page._pending_replacement(), expected)

        alternate = page.text_table.encode("撤")
        self.assertEqual(len(alternate), 2)
        raw_draft = (
            original[:changed_token_offset]
            + alternate
            + original[changed_token_offset + 2 :]
        ).hex(" ").upper()
        page.raw.setPlainText(raw_draft)

        self.assertTrue(page.has_pending_draft)
        self.assertIn("同时存在", page.pending_draft_error or "")
        self.assertEqual(page.decoded.toPlainText(), changed_text)
        self.assertEqual(page.raw.toPlainText(), raw_draft)
        before = bytes(self.project.working)
        undo_count = len(self.project._undo_stack)

        other_row = next(
            row
            for row in range(page.indices.count())
            if page.indices.item(row).data(Qt.ItemDataRole.UserRole) != record_index
        )
        with patch("dc_modifier.pages.QMessageBox.critical") as critical:
            page.indices.setCurrentRow(other_row)
            self.application.processEvents()

        critical.assert_called_once()
        self.assertEqual(page.current_index, record_index)
        self.assertEqual(page.decoded.toPlainText(), changed_text)
        self.assertEqual(page.raw.toPlainText(), raw_draft)
        self.assertEqual(bytes(self.project.working), before)

        with patch("dc_modifier.legacy_windows.QMessageBox.warning") as warning:
            dialog.accept()

        warning.assert_called_once()
        self.assertTrue(dialog.isVisible())
        self.assertEqual(page.decoded.toPlainText(), changed_text)
        self.assertEqual(page.raw.toPlainText(), raw_draft)
        self.assertEqual(bytes(self.project.working), before)
        self.assertEqual(len(self.project._undo_stack), undo_count)

        page.encode_decoded_text()

        self.assertEqual(page.decoded.toPlainText(), changed_text)
        self.assertEqual(page._parse_hex(page.raw.toPlainText()), expected)
        self.assertEqual(page._parse_hex(page.raw.toPlainText()).count(bytes.fromhex("C8 89")), 2)
        self.assertIsNone(page.pending_draft_error)
        dialog.accept()
        self.assertEqual(
            self.project.get_story_text(selector, record_index).raw,
            expected,
        )

    def test_story_invalid_unicode_draft_blocks_record_switch(self) -> None:
        dialog = self._show(ScenarioDialog(self.project, initial_scenario_id=0))
        page = dialog.story_page
        old_selector = page.current_selector
        old_index = page.current_index
        self.assertIsNotNone(old_selector)
        self.assertIsNotNone(old_index)
        assert old_selector is not None and old_index is not None
        original = self.project.get_story_text(old_selector, old_index).raw
        invalid_text = page.decoded.toPlainText() + "🙂"
        page.decoded.setPlainText(invalid_text)
        self.assertTrue(page.has_pending_draft)
        self.assertIn("没有字库编码", page.pending_draft_error or "")

        target_row = next(
            row
            for row in range(page.indices.count())
            if page.indices.item(row).data(Qt.ItemDataRole.UserRole) != old_index
        )
        with patch("dc_modifier.pages.QMessageBox.critical") as critical:
            page.indices.setCurrentRow(target_row)
            self.application.processEvents()

        critical.assert_called_once()
        self.assertEqual(page.current_index, old_index)
        self.assertEqual(
            page.indices.currentItem().data(Qt.ItemDataRole.UserRole), old_index
        )
        self.assertEqual(page.decoded.toPlainText(), invalid_text)
        self.assertEqual(
            self.project.get_story_text(old_selector, old_index).raw,
            original,
        )
        self.assertTrue(page.has_pending_draft)

    def test_scenario_accept_commits_story_unicode_draft(self) -> None:
        dialog = self._show(ScenarioDialog(self.project, initial_scenario_id=0))
        page = dialog.story_page
        selector = page.current_selector
        index = page.current_index
        self.assertIsNotNone(selector)
        self.assertIsNotNone(index)
        assert selector is not None and index is not None
        assert page.text_table is not None
        original_text = page.decoded.toPlainText()
        self.assertIn("！", original_text)
        changed_text = original_text.replace("！", ".", 1)
        replacement = page.text_table.encode(changed_text)
        page.decoded.setPlainText(changed_text)

        dialog.accept()

        self.assertEqual(
            self.project.get_story_text(selector, index).raw,
            replacement,
        )
        self.assertFalse(page.has_pending_draft)
        self.assertFalse(dialog.isVisible())

    def test_scenario_accept_preserves_invalid_story_unicode_draft(self) -> None:
        dialog = self._show(ScenarioDialog(self.project, initial_scenario_id=0))
        page = dialog.story_page
        selector = page.current_selector
        index = page.current_index
        self.assertIsNotNone(selector)
        self.assertIsNotNone(index)
        assert selector is not None and index is not None
        original = self.project.get_story_text(selector, index).raw
        invalid_text = page.decoded.toPlainText() + "🙂"
        page.decoded.setPlainText(invalid_text)

        with patch("dc_modifier.legacy_windows.QMessageBox.warning") as warning:
            dialog.accept()

        warning.assert_called_once()
        self.assertTrue(dialog.isVisible())
        self.assertEqual(page.decoded.toPlainText(), invalid_text)
        self.assertEqual(self.project.get_story_text(selector, index).raw, original)
        self.assertTrue(page.has_pending_draft)

    def test_story_commit_refreshes_clean_sibling_editor(self) -> None:
        dialog = self._show(ScenarioDialog(self.project, initial_scenario_id=0))
        page = dialog.story_page
        sibling = dialog.victory_page
        selector = page.current_selector
        index = page.current_index
        self.assertEqual(
            (sibling.current_selector, sibling.current_index),
            (selector, index),
        )
        self.assertIsNotNone(selector)
        self.assertIsNotNone(index)
        assert selector is not None and index is not None
        assert page.text_table is not None
        changed_text = page.decoded.toPlainText().replace("！", ".", 1)
        replacement = page.text_table.encode(changed_text)
        page.decoded.setPlainText(changed_text)

        self.assertTrue(page.commit_pending_changes())

        self.assertEqual(
            self.project.get_story_text(selector, index).raw,
            replacement,
        )
        self.assertEqual(sibling._parse_hex(sibling.raw.toPlainText()), replacement)
        self.assertEqual(sibling.decoded.toPlainText(), changed_text)
        self.assertFalse(sibling.has_pending_draft)

    def test_story_sibling_draft_conflict_blocks_every_commit_path(self) -> None:
        dialog = self._show(ScenarioDialog(self.project, initial_scenario_id=0))
        story = dialog.story_page
        victory = dialog.victory_page
        before = bytes(self.project.working)
        story_text = story.decoded.toPlainText().replace("！", ".", 1)
        victory_text = victory.decoded.toPlainText().replace("！", "：", 1)
        story.decoded.setPlainText(story_text)
        victory.decoded.setPlainText(victory_text)
        self.assertTrue(story.has_pending_draft)
        self.assertTrue(victory.has_pending_draft)
        self.assertIn("多个编辑页", story.pending_draft_error or "")
        self.assertIn("多个编辑页", victory.pending_draft_error or "")

        with patch("dc_modifier.pages.QMessageBox.critical") as critical:
            story.apply_text()

        critical.assert_called_once()
        self.assertEqual(bytes(self.project.working), before)
        self.assertEqual(story.decoded.toPlainText(), story_text)
        self.assertEqual(victory.decoded.toPlainText(), victory_text)

        with patch("dc_modifier.legacy_windows.QMessageBox.warning") as warning:
            dialog.accept()

        warning.assert_called_once()
        self.assertTrue(dialog.isVisible())
        self.assertEqual(bytes(self.project.working), before)
        self.assertEqual(story.decoded.toPlainText(), story_text)
        self.assertEqual(victory.decoded.toPlainText(), victory_text)

    def test_loading_text_table_commits_valid_unicode_draft_first(self) -> None:
        dialog = self._show(ScenarioDialog(self.project, initial_scenario_id=0))
        page = dialog.story_page
        selector = page.current_selector
        index = page.current_index
        self.assertIsNotNone(selector)
        self.assertIsNotNone(index)
        assert selector is not None and index is not None
        assert page.text_table is not None
        changed_text = page.decoded.toPlainText().replace("！", ".", 1)
        replacement = page.text_table.encode(changed_text)
        page.decoded.setPlainText(changed_text)

        with tempfile.TemporaryDirectory() as directory:
            table_path = Path(directory) / "replacement.tbl"
            table_path.write_text("FF=[终止]\n", encoding="utf-8")
            with patch(
                "dc_modifier.story_page.QFileDialog.getOpenFileName",
                return_value=(str(table_path), ""),
            ):
                page.load_text_table()

        self.assertEqual(
            self.project.get_story_text(selector, index).raw,
            replacement,
        )
        assert page.text_table is not None
        self.assertEqual(page.text_table.byte_to_text, {b"\xFF": "[终止]"})
        self.assertFalse(page.has_pending_draft)

    def test_loading_text_table_preserves_invalid_unicode_draft(self) -> None:
        dialog = self._show(ScenarioDialog(self.project, initial_scenario_id=0))
        page = dialog.story_page
        selector = page.current_selector
        index = page.current_index
        self.assertIsNotNone(selector)
        self.assertIsNotNone(index)
        assert selector is not None and index is not None
        original = self.project.get_story_text(selector, index).raw
        original_table = page.text_table
        original_status = page.table_status.text()
        invalid_text = page.decoded.toPlainText() + "🙂"
        page.decoded.setPlainText(invalid_text)

        with tempfile.TemporaryDirectory() as directory:
            table_path = Path(directory) / "replacement.tbl"
            table_path.write_text("FF=[终止]\n", encoding="utf-8")
            with (
                patch(
                    "dc_modifier.story_page.QFileDialog.getOpenFileName",
                    return_value=(str(table_path), ""),
                ),
                patch("dc_modifier.pages.QMessageBox.critical") as critical,
            ):
                page.load_text_table()

        critical.assert_called_once()
        self.assertIs(page.text_table, original_table)
        self.assertEqual(page.table_status.text(), original_status)
        self.assertEqual(page.decoded.toPlainText(), invalid_text)
        self.assertEqual(self.project.get_story_text(selector, index).raw, original)
        self.assertTrue(page.has_pending_draft)

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
