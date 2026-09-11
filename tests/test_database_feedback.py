from __future__ import annotations

import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication, QListWidgetItem, QMessageBox
import shiboken6

from dc_modifier.app import DEFAULT_ROM
from dc_modifier.database_graphics import palette_color, read_unit_appearance, render_chr_banks
from dc_modifier.legacy_windows import DatabaseDialog
from dc_modifier.unit_packages import package_from_project
from fc_editor.unit_package import UnitPackage
from fc_rom_editor_core import RomProject


from tests.qt_test_case import QtTestCase


class DatabaseFeedbackTests(QtTestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = QApplication.instance() or QApplication([])
        if not DEFAULT_ROM.is_file():
            raise unittest.SkipTest("缺少数据库测试 ROM。")

    def setUp(self) -> None:
        self.project = RomProject.load(DEFAULT_ROM)
        self.dialog = DatabaseDialog(self.project)
        self.dialog.show()
        self.app.processEvents()

    def tearDown(self) -> None:
        self.dialog.reject()
        self.dialog.deleteLater()
        self.app.processEvents()

    def test_appearance_reads_active_bytes_and_excludes_small_record_trailing_byte(self) -> None:
        appearance = read_unit_appearance(self.project, 2)
        self.assertEqual(appearance.configuration, bytes.fromhex("00 26 06 20 2a 00 10 4e 00 00"))
        self.assertEqual(appearance.primary_bank, 0x4E)
        self.assertEqual(appearance.secondary_banks, (0,))
        self.assertEqual(appearance.first_palette, (0x26, 6, 0x20))
        self.project.working[appearance.file_offset + 1] = 0x12
        self.assertEqual(read_unit_appearance(self.project, 2).first_palette[0], 0x12)

    def test_appearance_reader_follows_relocated_resources(self) -> None:
        before = read_unit_appearance(self.project, 2)
        self.project.configure_expansion(288, 64, 112)
        after = read_unit_appearance(self.project, 2)
        self.assertNotEqual(before.file_offset, after.file_offset)
        self.assertEqual(before.configuration, after.configuration)
        self.assertEqual(before.body_script, after.body_script)
        self.assertEqual(before.fragment_script, after.fragment_script)

    def test_changed_runtime_signature_stops_semantic_preview(self) -> None:
        self.project.working[0x8E65] ^= 1
        with self.assertRaisesRegex(ValueError, "加载代码"):
            read_unit_appearance(self.project, 2)

    def test_chr_preview_uses_all_actual_pixels_without_changing_rom(self) -> None:
        before = bytes(self.project.working)
        image = render_chr_banks(self.project, (0x4E,), (0, 0x10, 0x20))
        colors = (0xFF000000, *(palette_color(index).rgba() for index in (0, 0x10, 0x20)))
        for tile in range(64):
            pixels = self.project.chr_tile_pixels(0x4E * 64 + tile)
            for y in range(8):
                for x in range(8):
                    self.assertEqual(image.pixel(tile % 8 * 8 + x, tile // 8 * 8 + y), colors[pixels[y * 8 + x]])
        self.assertEqual(before, bytes(self.project.working))

    def test_weapon_usage_lists_real_units_and_both_slots_once(self) -> None:
        self.project.set_unit_weapon(2, 0, 1)
        self.project.set_unit_weapon(2, 1, 1)
        self.dialog._select_weapon(1)
        page = self.dialog.weapon_page
        page.refresh_usage()
        expected = {unit_id for unit_id in range(1, self.project.unit_count)
                    if 1 in self.project.get_unit_weapons(unit_id)}
        actual = {int(page.usage_list.item(row).data(Qt.ItemDataRole.UserRole))
                  for row in range(page.usage_list.count())}
        self.assertEqual(expected, actual)
        item = next(page.usage_list.item(row) for row in range(page.usage_list.count())
                    if page.usage_list.item(row).data(Qt.ItemDataRole.UserRole) == 2)
        self.assertIn("1、2", item.text())
        self.dialog.database_search.setText("不存在的筛选")
        page._open_usage(item)
        self.assertEqual(self.dialog.unit_page.current_id, 2)
        self.assertEqual(self.dialog.database_search.text(), "")
        self.assertFalse(self.dialog.unit_page.records.currentItem().isHidden())

    def test_unit_weapon_jump_keeps_draft_and_cancel_rolls_back(self) -> None:
        before = bytes(self.project.working)
        page = self.dialog.unit_page
        unit_id = page.current_id
        old_value = page.fields["hp"].value()
        page.fields["hp"].setValue(old_value + 1)
        page.weapon_slots[0].setCurrentIndex(page.weapon_slots[0].findData(1))
        page._request_weapon(0)
        self.assertEqual(self.dialog.weapon_page.current_id, 1)
        self.assertEqual(self.project.get_value(unit_id, "hp"), old_value + 1)
        self.assertIn(unit_id, {
            self.dialog.weapon_page.usage_list.item(row).data(Qt.ItemDataRole.UserRole)
            for row in range(self.dialog.weapon_page.usage_list.count())
        })
        self.dialog.reject()
        self.assertEqual(bytes(self.project.working), before)

    def test_current_unit_export_contains_visible_draft_not_unrelated_graphics(self) -> None:
        page = self.dialog.unit_page
        unit_id = page.current_id
        page.fields["hp"].setValue(page.fields["hp"].value() + 1)
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "current.dcunit"
            with patch("dc_modifier.legacy_windows.QFileDialog.getSaveFileName", return_value=(str(output), "")):
                page._export_current_package()
            package = UnitPackage.load(output)
        self.assertEqual(package.source_unit_id, unit_id)
        self.assertEqual(package.unit_record, self.project.record_bytes(unit_id))
        self.assertEqual(package.assets, ())

    def test_record_name_choices_put_pointer_noise_in_tooltips(self) -> None:
        for page in (self.dialog.unit_page, self.dialog.character_page, self.dialog.weapon_page):
            self.assertNotIn("指针", page.name_reference.itemText(0))
            self.assertIn("指针", page.name_reference.itemData(0, Qt.ItemDataRole.ToolTipRole))

    def test_cancelled_export_preserves_uncommitted_form(self) -> None:
        page = self.dialog.unit_page
        before = bytes(self.project.working)
        page.fields["hp"].setValue(page.fields["hp"].value() + 1)
        with patch("dc_modifier.legacy_windows.QFileDialog.getSaveFileName", return_value=("", "")):
            page._export_current_package()
        self.assertEqual(before, bytes(self.project.working))
        self.assertTrue(page.has_pending_draft)

    def test_inline_import_preserves_equipment_and_outer_cancel_restores_all(self) -> None:
        page = self.dialog.unit_page
        unit_id = page.current_id
        before = bytes(self.project.working)
        weapons = self.project.get_unit_weapons(unit_id)
        package = package_from_project(self.project, 2)
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "source.dcunit"
            package.save(source)
            with patch("dc_modifier.legacy_windows.QFileDialog.getOpenFileName", return_value=(str(source), "")), patch(
                "dc_modifier.legacy_windows.QMessageBox.question", return_value=QMessageBox.StandardButton.Yes
            ):
                page._import_current_package()
        self.assertEqual(package.unit_record, self.project.record_bytes(unit_id))
        self.assertEqual(weapons, self.project.get_unit_weapons(unit_id))
        self.dialog.reject()
        self.assertEqual(before, bytes(self.project.working))

    def test_small_database_window_keeps_footer_and_uses_vertical_form(self) -> None:
        self.dialog.resize(900, 600)
        self.app.processEvents()
        self.assertLess(self.dialog.ok_button.geometry().bottom(), self.dialog.height())
        self.assertEqual(self.dialog.unit_page.detail_scroll.horizontalScrollBar().maximum(), 0)

    def test_weapon_usage_jump_keeps_target_when_commit_rebuilds_usage_items(self) -> None:
        self.dialog._select_weapon(1)
        page = self.dialog.weapon_page
        selected = page.usage_list.currentItem()
        self.assertIsNotNone(selected)
        target_id = int(selected.data(Qt.ItemDataRole.UserRole))
        before = bytes(self.project.working)
        hit = page.fields["hit"].value() + 1
        page.fields["hit"].setValue(hit)
        self.assertTrue(page.has_pending_draft)
        page.usage_list.itemDoubleClicked.emit(selected)
        self.assertTrue(shiboken6.isValid(selected))
        self.assertEqual(self.dialog.unit_page.current_id, target_id)
        self.assertEqual(self.project.get_weapon_value(1, "hit"), hit)
        self.dialog.reject()
        self.assertEqual(bytes(self.project.working), before)

    def test_usage_parameter_refresh_preserves_item_identity_and_selection(self) -> None:
        self.dialog._select_weapon(1)
        page = self.dialog.weapon_page
        page.usage_list.setCurrentRow(page.usage_list.count() - 1)
        selected = page.usage_list.currentItem()
        before = tuple(page.usage_list.item(row) for row in range(page.usage_list.count()))
        page.refresh_usage()
        self.assertIs(page.usage_list.currentItem(), selected)
        self.assertEqual(before, tuple(page.usage_list.item(row)
                                     for row in range(page.usage_list.count())))
        self.assertTrue(all(shiboken6.isValid(item) for item in before))

    def test_database_navigation_reacquires_items_after_selection_rebuild(self) -> None:
        for page, navigate in ((self.dialog.unit_page, self.dialog._select_unit),
                               (self.dialog.weapon_page, self.dialog._select_weapon)):
            records = page.records
            original_select = records.setCurrentRow

            def rebuilding_select(row: int) -> None:
                entries = tuple((records.item(index).text(),
                                 records.item(index).data(Qt.ItemDataRole.UserRole))
                                for index in range(records.count()))
                blocked = records.blockSignals(True)
                try:
                    records.clear()
                    for text, record_id in entries:
                        item = QListWidgetItem(text)
                        item.setData(Qt.ItemDataRole.UserRole, record_id)
                        records.addItem(item)
                    original_select(row)
                finally:
                    records.blockSignals(blocked)

            with patch.object(records, "setCurrentRow", side_effect=rebuilding_select):
                navigate(2)
            self.assertEqual(records.currentItem().data(Qt.ItemDataRole.UserRole), 2)


if __name__ == "__main__":
    unittest.main()
