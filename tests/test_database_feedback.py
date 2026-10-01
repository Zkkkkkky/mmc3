from __future__ import annotations

import os
from pathlib import Path
import struct
import tempfile
import unittest
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QImage
from PySide6.QtWidgets import (
    QAbstractSpinBox,
    QApplication,
    QDialogButtonBox,
    QGroupBox,
    QLabel,
    QListWidgetItem,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QWidget,
)
import shiboken6

from dc_modifier.app import DEFAULT_ROM
from dc_modifier.database_graphics import (
    FCEUX_RGB,
    decode_unit_body_script,
    palette_color,
    read_unit_appearance,
    render_chr_banks,
    render_unit_battle_preview,
)
from dc_modifier.legacy_windows import DatabaseDialog
from dc_modifier.unit_icon_dialog import UnitIconBindingDialog, UnitIconDialog
from dc_modifier.unit_packages import package_from_project
from fc_editor.legacy_bitmap import LEGACY_MATERIAL_PALETTE_RGB
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

    def test_display_colors_match_the_bundled_fceux_palette_byte_for_byte(self) -> None:
        palette_path = (
            Path(__file__).resolve().parents[1]
            / "tools" / "vendor" / "fceux-2.6.6" / "palettes" / "FCEUX.pal"
        )
        self.assertEqual(FCEUX_RGB, palette_path.read_bytes())
        self.assertEqual(palette_color(0x0F).name().upper(), "#000000")

    def tearDown(self) -> None:
        self.dialog.reject()
        self.dialog.deleteLater()
        self.app.processEvents()

    def test_untouched_close_does_not_rebuild_every_database_page(self) -> None:
        with patch.object(self.dialog, "_refresh_pages") as refresh_pages:
            self.dialog.reject()
        refresh_pages.assert_not_called()

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

    def test_database_main_picture_layers_body_and_fragments_like_battle(self) -> None:
        self.dialog._select_unit(11)
        page = self.dialog.unit_page
        appearance = read_unit_appearance(self.project, 11)
        expected = render_unit_battle_preview(self.project, appearance)
        actual = page.body_preview.pixmap().toImage()
        self.assertEqual((actual.width(), actual.height()), (256, 256))
        expected_colors = {
            expected.pixelColor(x, y).name()
            for y in range(expected.height()) for x in range(expected.width())
        }
        actual_colors = {
            actual.pixelColor(x, y).name()
            for y in range(actual.height()) for x in range(actual.width())
        }
        self.assertEqual(actual_colors, expected_colors)
        self.assertIn("战斗合成预览", page.body_preview.toolTip())
        self.assertEqual(page.appearance_type.currentData(), 0x80)
        self.assertFalse(page.appearance_summary.isVisible())
        self.assertFalse(page.raw_body_preview.isVisible())
        self.assertFalse(page.fragment_preview.isVisible())

    def test_database_unit_palette_buttons_apply_visually_and_cancel_rolls_back(self) -> None:
        self.dialog._select_unit(0x09)
        page = self.dialog.unit_page
        before = bytes(self.project.working)
        old_value = read_unit_appearance(self.project, 0x09).first_palette[0]
        replacement = (old_value + 1) & 0x3F

        self.assertEqual(len(page.appearance_color_buttons), 6)
        self.assertEqual(page.appearance_color_buttons[0].value, old_value)
        self.assertIn("点击展开64色", page.appearance_color_buttons[0].toolTip())
        page.appearance_color_buttons[0].set_value(replacement)
        self.assertEqual(
            read_unit_appearance(self.project, 0x09).first_palette[0], replacement
        )
        self.assertFalse(page.body_preview.pixmap().isNull())

        self.dialog.reject()
        self.assertEqual(bytes(self.project.working), before)

    def test_database_unit_type_and_picture_addresses_are_editable(self) -> None:
        self.dialog._select_unit(0x09)
        page = self.dialog.unit_page
        before = bytes(self.project.working)
        original = read_unit_appearance(self.project, 0x09)

        self.assertEqual(page.appearance_type.currentData(), 0x00)
        self.assertFalse(page.appearance_bank_editors[2].isEnabled())
        page.appearance_type.setCurrentIndex(
            page.appearance_type.findData(0x80)
        )
        changed = read_unit_appearance(self.project, 0x09)
        self.assertEqual(changed.configuration[0], 0x80)
        self.assertEqual(
            changed.secondary_banks,
            (original.secondary_banks[0], original.secondary_banks[0] + 1),
        )
        self.assertTrue(page.appearance_bank_editors[2].isEnabled())

        page.appearance_bank_editors[0].setValue(0x44)
        page.appearance_bank_editors[1].setValue(0x45)
        page.appearance_bank_editors[2].setValue(0x46)
        changed = read_unit_appearance(self.project, 0x09)
        self.assertEqual(changed.primary_bank, 0x44)
        self.assertEqual(changed.secondary_banks, (0x45, 0x46))
        self.assertFalse(page.body_preview.pixmap().isNull())

        self.dialog.reject()
        self.assertEqual(bytes(self.project.working), before)

    def test_large_unit_captain_checkbox_writes_flag_and_cancel_rolls_back(self) -> None:
        self.dialog._select_unit(0x0B)
        page = self.dialog.unit_page
        before = bytes(self.project.working)
        original = read_unit_appearance(self.project, 0x0B)
        self.assertTrue(original.configuration[0] & 0x80)
        self.assertFalse(page.captain_check.isHidden())
        self.assertTrue(page.captain_check.isEnabled())
        self.assertEqual(
            page.captain_check.isChecked(),
            bool(original.configuration[0] & 0x20),
        )

        page.captain_check.setChecked(not page.captain_check.isChecked())
        changed = read_unit_appearance(self.project, 0x0B)
        self.assertEqual(changed.configuration[0] & 0xC0, original.configuration[0] & 0xC0)
        self.assertEqual(
            bool(changed.configuration[0] & 0x20),
            not bool(original.configuration[0] & 0x20),
        )
        self.assertEqual(changed.configuration[1:], original.configuration[1:])

        self.dialog._select_unit(0x09)
        self.assertTrue(page.captain_check.isHidden())
        self.assertFalse(page.captain_check.isEnabled())

        self.dialog.reject()
        self.assertEqual(bytes(self.project.working), before)

    def test_database_rejects_unsafe_stock_large_to_small_type_change(self) -> None:
        self.dialog._select_unit(11)
        page = self.dialog.unit_page
        self.assertTrue(any(
            placement.tile_index >= 64
            for placement in decode_unit_body_script(
                read_unit_appearance(self.project, 11).body_script, 128
            )
        ))
        with patch.object(page, "show_error") as show_error:
            page.appearance_type.setCurrentIndex(page.appearance_type.findData(0x00))
        show_error.assert_called_once()
        changed = read_unit_appearance(self.project, 11)
        self.assertEqual(changed.configuration[0], 0x80)
        self.assertFalse(page.body_preview.pixmap().isNull())

    def test_unit_map_icon_can_be_bound_and_edited(self) -> None:
        self.dialog._select_unit(0x87)
        page = self.dialog.unit_page
        before = bytes(self.project.working)
        self.assertEqual(page.icon_bank.currentData(), 0x36)
        self.assertEqual(page.icon_index.currentData(), 2)
        self.assertIn("机体字段 $88", page.icon_address.text())
        self.assertFalse(page.icon_bank.isVisible())
        self.assertFalse(page.icon_index.isVisible())
        self.assertFalse(page.icon_address.isVisible())

        page.icon_bank.setCurrentIndex(page.icon_bank.findData(0x35))
        page.icon_index.setCurrentIndex(page.icon_index.findData(3))
        page._bind_unit_icon()
        self.assertEqual(self.project.record_bytes(0x87)[2], 0x4C)

        dialog = UnitIconDialog(
            self.project, 0x35, 3, (0x0F, 0x37, 0x27, 0x16)
        )
        self.addCleanup(dialog.close)
        original = list(dialog.canvas.pixels)
        dialog.canvas.pixels[0] = (dialog.canvas.pixels[0] + 1) % 4
        dialog.accept()
        self.assertTrue(dialog.changed)
        reopened = UnitIconDialog(
            self.project, 0x35, 3, (0x0F, 0x37, 0x27, 0x16)
        )
        self.addCleanup(reopened.close)
        self.assertNotEqual(reopened.canvas.pixels, original)

        self.dialog.reject()
        self.assertEqual(bytes(self.project.working), before)

    def test_unit_icon_binding_uses_selected_scenario_route(self) -> None:
        dialog = UnitIconBindingDialog(
            self.project, 0x88, (0x0F, 0x37, 0x27, 0x16)
        )
        self.addCleanup(dialog.close)
        dialog.show()
        self.app.processEvents()
        self.assertEqual((dialog.width(), dialog.height()), (530, 356))
        self.assertEqual(dialog.selector_box.height(), 88)
        self.assertEqual(len(dialog.icon_buttons), 48)
        self.assertTrue(all(button.autoRaise() for button in dialog.icon_buttons))
        self.assertLessEqual(dialog.minimumWidth(), 700)
        self.assertLessEqual(dialog.icon_grid.height(), 170)
        self.assertEqual(dialog.scenario.width(), 210)
        self.assertEqual(dialog.icon_number.width(), 210)
        button_box = dialog.findChild(QDialogButtonBox)
        self.assertIsNotNone(button_box)
        self.assertEqual(
            button_box.button(QDialogButtonBox.StandardButton.Ok).text(), "确定"
        )
        self.assertEqual(
            button_box.button(QDialogButtonBox.StandardButton.Cancel).text(), "取消"
        )
        self.assertEqual(dialog.icon_number.currentData(), 34)
        self.assertEqual(dialog.raw_icon_value, 0x88)
        self.assertEqual(dialog.selected_bank, 0x36)
        self.assertEqual(dialog.selected_icon_index, 2)

        dialog.scenario.setCurrentIndex(9)
        self.assertEqual(dialog.selected_bank, 0x3E)
        self.assertEqual(dialog.raw_icon_value, 0x88)
        dialog.icon_number.setCurrentIndex(47)
        self.assertEqual(dialog.selected_bank, 0x3E)
        self.assertEqual(dialog.selected_icon_index, 15)
        self.assertEqual(dialog.raw_icon_value, 0xBC)

    def test_unit_icon_exports_legacy_24_bit_bmp_and_imports_bmp_palette(self) -> None:
        dialog = UnitIconDialog(
            self.project, 0x36, 2, (0x0F, 0x37, 0x27, 0x16)
        )
        self.addCleanup(dialog.close)
        dialog.show()
        self.app.processEvents()
        self.assertGreater(
            dialog.palette_box.geometry().left(), dialog.canvas.geometry().right()
        )
        self.assertEqual(dialog.canvas.size().toTuple(), (273, 273))
        self.assertTrue(all(
            button.width() == 120 and button.height() >= 44
            for button in dialog.palette_buttons
        ))
        button_box = dialog.findChild(QDialogButtonBox)
        self.assertIsNotNone(button_box)
        self.assertEqual(
            button_box.button(QDialogButtonBox.StandardButton.Ok).text(), "确定"
        )
        self.assertEqual(
            button_box.button(QDialogButtonBox.StandardButton.Cancel).text(), "取消"
        )
        dialog.canvas.pixels = [index % 4 for index in range(256)]
        encoded = dialog._bitmap_bytes()
        self.assertEqual(len(encoded), 822)
        self.assertEqual(encoded[:2], b"BM")
        self.assertEqual(struct.unpack_from("<iiH", encoded, 18), (16, 16, 1))
        self.assertEqual(struct.unpack_from("<H", encoded, 28)[0], 24)

        image = QImage.fromData(encoded, "BMP")
        self.assertFalse(image.isNull())
        self.assertEqual(dialog._pixels_from_image(image), dialog.canvas.pixels)

        material = QImage(16, 16, QImage.Format.Format_RGB32)
        for y in range(16):
            for x in range(16):
                material.setPixelColor(
                    x, y, QColor(*LEGACY_MATERIAL_PALETTE_RGB[(x + y) % 4])
                )
        self.assertEqual(
            dialog._pixels_from_image(material),
            [(x + y) % 4 for y in range(16) for x in range(16)],
        )

    def test_unit_icon_horizontal_flip_updates_draft_and_round_trips(self) -> None:
        dialog = UnitIconDialog(
            self.project, 0x36, 2, (0x0F, 0x37, 0x27, 0x16)
        )
        self.addCleanup(dialog.close)
        self.assertEqual(dialog.flip_button.text(), "水平翻转图标")
        source = [(x + y * 2) % 4 for y in range(16) for x in range(16)]
        expected = [
            source[y * 16 + (15 - x)]
            for y in range(16)
            for x in range(16)
        ]
        dialog.canvas.set_pixels(source)
        dialog.flip_button.click()
        self.assertEqual(dialog.canvas.pixels, expected)
        dialog.accept()
        self.assertTrue(dialog.changed)

        reopened = UnitIconDialog(
            self.project, 0x36, 2, (0x0F, 0x37, 0x27, 0x16)
        )
        self.addCleanup(reopened.close)
        self.assertEqual(reopened.canvas.pixels, expected)
        reopened.flip_button.click()
        self.assertEqual(reopened.canvas.pixels, source)

    def test_unit_icon_import_rejects_non_16_by_16_bitmap(self) -> None:
        dialog = UnitIconDialog(
            self.project, 0x36, 2, (0x0F, 0x37, 0x27, 0x16)
        )
        self.addCleanup(dialog.close)
        before = list(dialog.canvas.pixels)
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "wrong-size.bmp"
            image = QImage(32, 16, QImage.Format.Format_RGB32)
            image.fill(QColor("black"))
            self.assertTrue(image.save(str(path), "BMP"))
            with (
                patch(
                    "dc_modifier.unit_icon_dialog.QFileDialog.getOpenFileName",
                    return_value=(str(path), ""),
                ),
                patch("dc_modifier.unit_icon_dialog.QMessageBox.warning") as warning,
            ):
                dialog._import_bitmap()
        warning.assert_called_once()
        self.assertIn("16×16", warning.call_args.args[2])
        self.assertIn("32×16", warning.call_args.args[2])
        self.assertEqual(dialog.canvas.pixels, before)

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

    def test_context_export_writes_current_unit_five_bitmap_layout(self) -> None:
        page = self.dialog.unit_page
        unit_id = page.current_id
        with tempfile.TemporaryDirectory() as directory, patch(
            "dc_modifier.legacy_windows.QFileDialog.getExistingDirectory",
            return_value=directory,
        ):
            page._export_current_legacy_bitmaps()
            exported = list(Path(directory).glob(f"{unit_id:03d}：*/*.bmp"))
        self.assertEqual(len(exported), 5)
        self.assertEqual(
            {path.stem.rsplit("[", 1)[-1].rstrip("]") for path in exported},
            {"效果", "机体", "碎片", "图标1", "图标2"},
        )

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

    def test_reference_database_width_keeps_all_three_groups_on_one_row(self) -> None:
        self.dialog.resize(1525, 900)
        self.app.processEvents()
        page = self.dialog.unit_page
        self.assertEqual(page._compact_data_layout, "wide")
        self.assertEqual(page.detail_scroll.horizontalScrollBar().maximum(), 0)
        self.assertEqual(page.detail_scroll.verticalScrollBar().maximum(), 0)
        self.assertFalse(page.record_heading.isVisible())
        self.assertFalse(page.pending_state.isVisible())
        self.assertFalse(page.graphics_status.isVisible())
        self.assertEqual(page.body_preview.size().width(), 256)
        self.assertEqual(page.body_preview.size().height(), 256)
        self.assertEqual(self.dialog._database_memory_panels[0].height(), 28)
        self.assertLessEqual(self.dialog.database_search.width(), 360)
        self.assertLessEqual(page.appearance_type.width(), 190)
        self.assertGreaterEqual(page.appearance_type.width(), 170)
        self.assertTrue(all(
            170 <= editor.width() <= 190 for editor in page.appearance_bank_editors
        ), [editor.width() for editor in page.appearance_bank_editors])
        self.assertTrue(all(editor.minimumContentsLength() == 16
                            for editor in page.appearance_bank_editors))
        self.assertTrue(all(button.width() == 80 for button in page.weapon_jump_buttons))
        self.assertTrue(all(
            button.geometry().right() <= page.weapons_group.contentsRect().right()
            for button in page.weapon_jump_buttons
        ))
        self.assertTrue(all(
            editor.width() >= 190 for editor in page.weapon_slots
        ))
        self.assertTrue(all(
            editor.geometry().top() > button.geometry().top()
            for editor, button in zip(page.weapon_slots, page.weapon_jump_buttons)
        ))

    def test_125_percent_scaled_database_width_does_not_scroll_horizontally(self) -> None:
        # 1525×984 physical pixels at the reporter's 125% Windows scale is
        # approximately a 1220×787 logical Qt window.
        self.dialog.resize(1220, 787)
        self.app.processEvents()
        page = self.dialog.unit_page
        self.assertEqual(page._compact_data_layout, "wide")
        self.assertEqual(page.detail_scroll.horizontalScrollBar().maximum(), 0)
        self.assertEqual(page.detail_scroll.verticalScrollBar().maximum(), 0)
        self.assertEqual(page.weapons_group.geometry().top(), page.basic_group.geometry().top())

    def test_default_database_uses_legacy_scaled_footprint(self) -> None:
        page = self.dialog.unit_page
        self.assertEqual(self.dialog.size().toTuple(), (1050, 700))
        self.assertEqual(page._compact_data_layout, "wide")
        self.assertEqual(page.detail_scroll.horizontalScrollBar().maximum(), 0)
        self.assertEqual(page.detail_scroll.verticalScrollBar().maximum(), 0)
        self.assertEqual(
            {editor.geometry().left() for editor in page.appearance_bank_editors},
            {page.appearance_type.geometry().left()},
        )
        self.assertLess(
            page.appearance_type.geometry().top(),
            page.appearance_bank_editors[1].geometry().top(),
        )
        self.assertLess(
            page.appearance_bank_editors[1].geometry().top(),
            page.appearance_bank_editors[2].geometry().top(),
        )
        self.assertLess(
            page.appearance_bank_editors[2].geometry().top(),
            page.appearance_bank_editors[0].geometry().top(),
        )
        self.assertFalse(page.apply_button.isVisible())

    def test_character_page_uses_reference_compact_first_screen_layout(self) -> None:
        # DatabaseDialog actually opens at 1050x670 logical pixels.  Testing
        # a much wider canvas hid the horizontal overflow seen at 125% DPI.
        self.dialog.resize(1050, 670)
        self.dialog.tabs.setCurrentIndex(1)
        self.dialog.character_page.select_record_id(4)
        self.app.processEvents()

        page = self.dialog.character_page
        scroll = page.findChild(QScrollArea)
        workspace = page.findChild(QWidget, "characterWorkspace")
        self.assertIsNotNone(scroll)
        self.assertIsNotNone(workspace)
        self.assertTrue(page.character_details.portrait_group.isVisible())
        self.assertGreaterEqual(page.records.width(), 200)
        self.assertLessEqual(page.records.width(), 250)
        self.assertEqual(page.records.currentItem().text(), "[04]004：琉妮")
        self.assertEqual(page.records.item(0).text(), "[01]001：")
        self.assertEqual(page.records.item(0x0B - 1).text(), "[0B]011：")
        self.assertNotIn("未分配人物槽", page.records.item(0).text())
        self.assertEqual(page.character_list_heading.text(), "人物选择")
        self.assertFalse(page.record_heading.isVisible())
        self.assertFalse(page.pending_state.isVisible())
        self.assertFalse(page.apply_button.isVisible())
        portrait = page.character_details.portrait_group
        self.assertEqual(portrait.title(), "头像设置")
        selector_sections = page.character_details.portrait_selector_sections
        color_sections = page.character_details.portrait_color_sections
        self.assertEqual([section.width() for section in selector_sections], [96, 96])
        self.assertEqual([section.width() for section in color_sections], [80, 80, 80])
        ordered_sections = (*selector_sections, *color_sections)
        self.assertTrue(all(
            left.geometry().right() < right.geometry().left()
            for left, right in zip(ordered_sections, ordered_sections[1:])
        ))
        visibility_section = portrait.findChild(QWidget, "portraitVisibilitySection")
        upload_section = portrait.findChild(QWidget, "portraitUploadSection")
        self.assertIsNotNone(visibility_section)
        self.assertIsNotNone(upload_section)
        assert visibility_section is not None and upload_section is not None
        portrait_columns = (
            page.character_details.portrait_preview,
            visibility_section,
            upload_section,
            *ordered_sections,
        )
        column_gaps = [
            right.geometry().left() - left.geometry().right() - 1
            for left, right in zip(portrait_columns, portrait_columns[1:])
        ]
        self.assertLessEqual(max(column_gaps) - min(column_gaps), 1)
        self.assertGreaterEqual(min(column_gaps), 10)
        self.assertEqual(
            {section.geometry().top() for section in ordered_sections},
            {selector_sections[0].geometry().top()},
        )
        first_control_tops = {
            page.character_details.portrait_fields[key].mapTo(
                portrait,
                page.character_details.portrait_fields[key].rect().topLeft(),
            ).y()
            for key in ("front_bank", "back_bank", "color0", "color1", "color2")
        }
        self.assertEqual(len(first_control_tops), 1)
        self.assertTrue(all(
            page.character_details.portrait_fields[key].width() == 77
            for key in ("color0", "color1", "color2")
        ))
        for bank_key, slot_key in (
            ("front_bank", "front_slot"),
            ("back_bank", "back_slot"),
        ):
            bank = page.character_details.portrait_fields[bank_key]
            slot = page.character_details.portrait_fields[slot_key]
            self.assertEqual(bank.width(), 96)
            self.assertEqual(slot.width(), 96)
            self.assertEqual(bank.geometry().left(), slot.geometry().left())
            self.assertLess(bank.geometry().bottom(), slot.geometry().top())
        self.assertTrue(all(
            page.character_details.portrait_fields[key].number.buttonSymbols()
            == QAbstractSpinBox.ButtonSymbols.NoButtons
            for key in ("color0", "color1", "color2")
        ))
        portrait_labels = {label.text() for label in portrait.findChildren(QLabel)}
        self.assertNotIn("正面位置", portrait_labels)
        self.assertNotIn("背景位置", portrait_labels)
        self.assertFalse(hasattr(page.character_details, "shared_portrait"))
        self.assertFalse(page.character_details.shared_attributes.isVisible())
        self.assertFalse(page.advanced_details_host.isVisible())
        self.assertFalse(page.capability_status.isVisible())
        self.assertFalse(page.original_name.isVisible())
        self.assertFalse(page.original_music.isVisible())
        self.assertFalse(page.character_details.portrait_export_button.isVisible())
        self.assertFalse(page.character_details.portrait_advanced_button.isVisible())
        self.assertLess(
            page.character_details.portrait_group.geometry().top(),
            workspace.geometry().top(),
        )
        self.assertGreater(
            page.character_dialogue.geometry().left(),
            page.character_reference_left.geometry().right(),
        )
        self.assertEqual(scroll.horizontalScrollBar().maximum(), 0)
        self.assertEqual(scroll.verticalScrollBar().maximum(), 0)
        self.assertEqual(page.basic_group.title(), "基本设置")
        self.assertFalse(page.name_reference.isVisible())
        self.assertEqual(page.ally_music.currentText(), f"音乐{int(page.ally_music.currentData()):02X}")
        self.assertIn(
            f"命令 ${int(page.ally_music.currentData()):02X}",
            page.ally_music.currentData(Qt.ItemDataRole.ToolTipRole),
        )
        earth_index = page.ally_music.findData(0x87)
        unknown_index = page.ally_music.findData(0x94)
        extension_index = page.ally_music.findData(0x9D)
        self.assertEqual(page.ally_music.itemText(earth_index), "地球我方音乐")
        self.assertEqual(page.ally_music.itemText(unknown_index), "音乐94")
        self.assertEqual(page.ally_music.itemText(extension_index), "音乐9D")
        attributes = page.character_details.attributes_group
        spirits = page.character_details.spirits_group
        self.assertEqual(page.basic_group.geometry().top(), attributes.geometry().top())
        self.assertLess(page.basic_group.geometry().left(), attributes.geometry().left())
        self.assertGreater(spirits.geometry().top(), page.basic_group.geometry().bottom())
        self.assertLessEqual(spirits.geometry().left(), page.basic_group.geometry().left())
        self.assertGreaterEqual(spirits.geometry().right(), attributes.geometry().right())
        attack_tops = [
            button.geometry().top()
            for button in page.character_dialogue.direct_buttons[:2]
        ]
        defense_tops = [
            button.geometry().top()
            for button in page.character_dialogue.direct_buttons[2:]
        ]
        self.assertEqual(attack_tops, sorted(attack_tops))
        self.assertEqual(defense_tops, sorted(defense_tops))
        self.assertEqual(len(set(defense_tops)), 6)

    def test_database_visible_button_captions_fit_at_default_size(self) -> None:
        self.dialog.resize(1050, 670)
        for tab in range(self.dialog.tabs.count()):
            self.dialog.tabs.setCurrentIndex(tab)
            self.app.processEvents()
            overflows = []
            for button in self.dialog.tabs.currentWidget().findChildren(QPushButton):
                if not button.isVisible() or not button.text():
                    continue
                longest_line = max(button.text().splitlines(), key=len)
                needed = button.fontMetrics().horizontalAdvance(longest_line) + 4
                if needed > button.width():
                    overflows.append((button.text(), button.width(), needed))
            self.assertEqual(overflows, [], self.dialog.tabs.tabText(tab))

    def test_weapon_page_keeps_core_fields_and_animation_on_first_screen(self) -> None:
        self.dialog.resize(1220, 787)
        self.dialog.tabs.setCurrentIndex(2)
        self.dialog.weapon_page.select_record_id(1)
        self.app.processEvents()

        page = self.dialog.weapon_page
        scroll = page.findChild(QScrollArea)
        self.assertIsNotNone(scroll)
        self.assertEqual(scroll.horizontalScrollBar().maximum(), 0)
        self.assertEqual(scroll.verticalScrollBar().maximum(), 0)
        self.assertFalse(page.capability_status.isVisible())
        self.assertFalse(page.rom_summary.isVisible())
        parameters = next(
            group for group in page.findChildren(QGroupBox)
            if group.title() == "战斗参数"
        )
        self.assertEqual(parameters.geometry().top(), page.extras_group.geometry().top())

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
