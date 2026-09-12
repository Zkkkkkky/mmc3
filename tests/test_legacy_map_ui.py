from __future__ import annotations

import os
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QSize, Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QDialogButtonBox

from dc_modifier.app import DEFAULT_ROM
from dc_modifier.map_page import (
    MapPage,
    NesColorButton,
    NesPaletteDialog,
    TerrainButton,
    TileAttributeDialog,
    _glyph_file_offset,
    render_map_title,
)
from dc_modifier.map_tiles import render_map_tile
from fc_editor.dc_text import dc_map_label
from fc_rom_editor_core import RomProject


from tests.qt_test_case import QtTestCase


class LegacyMapUiTests(QtTestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.application = QApplication.instance() or QApplication([])
        if not DEFAULT_ROM.is_file():
            raise unittest.SkipTest(f"缺少界面测试ROM：{DEFAULT_ROM}")

    def setUp(self) -> None:
        self.project = RomProject.load(DEFAULT_ROM)
        self.page = MapPage()
        self.page.resize(1280, 820)
        self.page.set_project(self.project)
        self.page.show()
        self.application.processEvents()

    def tearDown(self) -> None:
        self.page.hide()
        self.page.deleteLater()
        self.application.processEvents()

    def test_three_legacy_tabs_share_chapter_list_and_map(self) -> None:
        self.assertEqual(
            [
                self.page.editor_tabs.tabText(index)
                for index in range(self.page.editor_tabs.count())
            ],
            ["战场地图", "初始配置", "商店事件"],
        )
        self.assertEqual(self.page.map_list.item(0).text(), "001：伏击之战")
        self.assertEqual(self.page.title_preview.text(), "")
        self.assertFalse(self.page.title_preview.pixmap().isNull())
        self.assertTrue(self.page.search.isVisible())
        self.assertEqual(
            self.page.map_scroll.horizontalScrollBarPolicy(),
            Qt.ScrollBarPolicy.ScrollBarAsNeeded,
        )
        self.assertEqual(
            self.page.map_scroll.verticalScrollBarPolicy(),
            Qt.ScrollBarPolicy.ScrollBarAsNeeded,
        )
        self.assertLessEqual(
            self.page.canvas.width(), self.page.map_scroll.viewport().width()
        )
        self.assertLessEqual(
            self.page.canvas.height(), self.page.map_scroll.viewport().height()
        )

    def test_map_title_uses_verified_glyph_addresses(self) -> None:
        self.assertEqual(_glyph_file_offset(bytes.fromhex("C908")), 0x710A0)
        self.assertEqual(_glyph_file_offset(bytes.fromhex("DAC2")), 0x76C34)

    def test_map_title_renderer_covers_every_map_slot_without_missing_cells(self) -> None:
        for map_id in range(self.project.map_count):
            title = dc_map_label(map_id)
            image = render_map_title(self.project, title).toImage()
            self.assertEqual((image.width(), image.height()),
                             (16 + len(title) * 40, 48))
            for index, character in enumerate(title):
                if character.isspace():
                    continue
                cell_has_ink = any(
                    image.pixelColor(8 + index * 40 + x, y).name() != "#000000"
                    for y in range(image.height()) for x in range(40)
                )
                self.assertTrue(cell_has_ink, f"地图 ${map_id:02X} 漏字：{character}")
        stage_two = render_map_title(self.project, "街上追击战").toImage()
        signatures = {
            bytes(stage_two.copy(8 + index * 40, 0, 40, 48).bits())
            for index in range(5)
        }
        self.assertGreaterEqual(len(signatures), 4, "标题字体退化成了相同的缺字方框")

    def test_map_title_default_scale_matches_game_preview(self) -> None:
        pixmap = render_map_title(self.project, "伏击之战")
        self.assertEqual((pixmap.width(), pixmap.height()), (176, 48))
        image = pixmap.toImage()
        ink = [
            (x, y)
            for y in range(image.height()) for x in range(image.width())
            if image.pixelColor(x, y).name() != "#000000"
        ]
        self.assertEqual(
            (min(x for x, _y in ink), min(y for _x, y in ink),
             max(x for x, _y in ink), max(y for _x, y in ink)),
            (8, 4, 165, 43),
        )
        self.assertEqual(
            (self.page.title_preview.pixmap().width(),
             self.page.title_preview.pixmap().height()),
            (176, 48),
        )

    def test_battlefield_keeps_advanced_raw_data_separate_from_visible_save_status(self) -> None:
        self.assertEqual(self.page.bitmap_selector.currentText(), "位图D")
        self.assertEqual(self.page.tileset.currentData(), "D")
        self.assertEqual(len(self.page.terrain_buttons.buttons()), 16)
        self.assertTrue(self.page.width_display.isReadOnly())
        self.assertTrue(self.page.height_display.isReadOnly())
        for advanced_control in (
            self.page.width_editor,
            self.page.height_editor,
            self.page.prelude,
            self.page.show_ids,
        ):
            self.assertFalse(advanced_control.isVisible())
        for visible_control in (self.page.zoom, self.page.fit_view, self.page.size_label,
                                self.page.pending_state, self.page.apply_button):
            self.assertTrue(visible_control.isVisible())
        self.assertTrue(self.page.open_map_advanced_button.isVisible())

    def test_left_and_right_mouse_brushes_are_independent(self) -> None:
        left_button = self.page.terrain_buttons.button(3)
        right_button = self.page.terrain_buttons.button(7)
        self.assertIsInstance(left_button, TerrainButton)
        self.assertIsInstance(right_button, TerrainButton)
        QTest.mouseClick(left_button, Qt.MouseButton.LeftButton)
        QTest.mouseClick(right_button, Qt.MouseButton.RightButton)
        self.assertEqual(self.page.canvas.selected_tile, 3)
        self.assertEqual(self.page.canvas.right_selected_tile, 7)
        self.assertEqual(self.page.terrain.currentData(), 3)
        self.assertEqual(self.page.right_terrain.currentData(), 7)
        self.assertEqual(self.page.left_brush_preview.pixmap().size().width(), 56)
        self.assertEqual(self.page.right_brush_preview.pixmap().size().height(), 56)
        for preview, tile in (
            (self.page.left_brush_preview, 3),
            (self.page.right_brush_preview, 7),
        ):
            expected = self.page.canvas.tile_images[tile].scaled(
                56,
                56,
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.FastTransformation,
            )
            self.assertEqual(preview.pixmap().toImage(), expected)

    def test_tile_attribute_dialog_applies_one_transaction_and_cancel_is_clean(self) -> None:
        original = self.project.get_map_tileset_attributes("D")
        undo_count = len(self.project._undo_stack)
        dialog = TileAttributeDialog(
            self.project, "D", self.page.canvas.tile_images, self.page
        )
        self.assertTrue(dialog._supported)
        self.assertEqual(dialog.table.rowCount(), 16)
        dialog.defense_spins[1].setValue((original.tiles[1].defense + 1) & 0x7F)
        dialog.reject()
        self.assertEqual(self.project.get_map_tileset_attributes("D"), original)

        dialog = TileAttributeDialog(
            self.project, "D", self.page.canvas.tile_images, self.page
        )
        changed = (original.tiles[1].defense + 1) & 0x7F
        dialog.defense_spins[1].setValue(changed)
        dialog.accept()
        self.assertEqual(
            self.project.get_map_tileset_attributes("D").tiles[1].defense, changed
        )
        self.assertEqual(len(self.project._undo_stack), undo_count + 1)

    def test_tile_attribute_palette_is_visual_and_previews_draft_without_writing(self) -> None:
        button = NesColorButton(0x2A)
        self.assertEqual(button.value, 0x2A)
        self.assertEqual(button.text(), "$2A")
        self.assertIn("#4CDC48", button.toolTip())
        picker = NesPaletteDialog(0x2A)
        picker_layout = picker.layout()
        self.assertIsNotNone(picker_layout.itemAtPosition(0, 15))
        self.assertIsNotNone(picker_layout.itemAtPosition(1, 0))
        self.assertIsNotNone(picker_layout.itemAtPosition(3, 15))
        picker._select(0x1A)
        self.assertEqual(picker.selected_value, 0x1A)

        before_rom = bytes(self.project.working)
        dialog = TileAttributeDialog(
            self.project, "D", self.page.canvas.tile_images, self.page
        )
        self.assertTrue(dialog.sea_checks[5].isChecked())
        self.assertIn("ROM 漏写海属性", dialog.sea_checks[5].toolTip())
        self.assertIn("应用后会补写标志", dialog.sea_checks[5].toolTip())
        tile_zero = dialog.table.item(0, 0).icon().pixmap(16, 16).toImage()
        expected_zero = render_map_tile(
            self.project,
            "D",
            0,
            attributes=self.project.get_map_tileset_attributes("D"),
        )
        self.assertEqual(tile_zero, expected_zero)
        before_icon = dialog.table.item(1, 0).icon().pixmap(16, 16).toImage()
        dialog.color_spins[1].setValue(0x0F)
        after_icon = dialog.table.item(1, 0).icon().pixmap(16, 16).toImage()
        self.assertNotEqual(before_icon, after_icon)
        self.assertEqual(bytes(self.project.working), before_rom)
        self.assertEqual(dialog.color_buttons[1].value, 0x0F)
        for palette_index in (2, 3):
            preview = dialog.shared_palette_previews[palette_index]
            self.assertFalse(preview.pixmap().isNull())
            self.assertIn("只读", preview.toolTip())
            self.assertIn("真实 NES 色号", preview.toolTip())
            expected = (
                "$0F · $30 · $21 · $02"
                if palette_index == 2
                else "$0F · $37 · $27 · $16"
            )
            self.assertIn(expected, dialog.shared_palette_tiles[palette_index].text())
            self.assertIn(
                "属性原码引用图块",
                dialog.shared_palette_tiles[palette_index].text(),
            )
            self.assertFalse(
                dialog.palette_boxes[0].itemIcon(palette_index).isNull()
            )

    def test_unverified_tileset_h_stays_read_only(self) -> None:
        dialog = TileAttributeDialog(
            self.project, "H", self.page.canvas.tile_images, self.page
        )
        self.assertFalse(dialog._supported)
        self.assertFalse(
            dialog.buttons.button(QDialogButtonBox.StandardButton.Save).isEnabled()
        )

    def test_initial_configuration_defaults_to_real_icon_sheets(self) -> None:
        self.page.editor_tabs.setCurrentIndex(1)
        self.application.processEvents()
        self.assertEqual(
            [selector.currentData() for selector in self.page.icon_bank_selectors],
            [0x34, 0x35, 0x36],
        )
        for selector, preview in zip(
            self.page.icon_bank_selectors,
            self.page.icon_sheet_labels,
            strict=True,
        ):
            self.assertIn(":", selector.currentText())
            self.assertEqual(selector.width(), 150)
            self.assertEqual(preview.size(), QSize(192, 48))
            self.assertTrue(preview.pixmap().isNull())
            self.assertFalse(preview.isVisible())
        self.assertFalse(self.page.icon_preview_group.isVisible())
        self.assertEqual(self.page.icon_preview_group.maximumHeight(), 195)
        self.assertLessEqual(self.page.icon_preview_toggle.maximumWidth(), 220)
        self.assertLessEqual(self.page.deployment_list_toggle.maximumWidth(), 180)
        self.assertLessEqual(self.page.open_deployment_button.maximumWidth(), 210)
        self.assertTrue(self.page.icon_preview_toggle.isVisible())
        self.assertIn("展开", self.page.icon_preview_toggle.text())
        self.page.icon_preview_toggle.setChecked(True)
        self.application.processEvents()
        self.assertTrue(self.page.icon_preview_group.isVisible())
        self.assertIn("收起", self.page.icon_preview_toggle.text())
        for preview in self.page.icon_sheet_labels:
            self.assertTrue(preview.isVisible())
            self.assertFalse(preview.pixmap().isNull())
            self.assertEqual(preview.pixmap().size(), QSize(192, 48))
        self.assertIn("10D810", self.page.icon_bank_selectors[2].currentText())
        self.page.map_list.setCurrentRow(3)
        self.application.processEvents()
        self.assertEqual(
            [selector.currentData() for selector in self.page.icon_bank_selectors],
            [0x34, 0x35, 0x3A],
        )
        self.page.map_list.setCurrentRow(27)
        self.application.processEvents()
        self.assertEqual(
            [selector.currentData() for selector in self.page.icon_bank_selectors],
            [0x46, 0x47, 0x3C],
        )
        self.assertTrue(self.page.deployment_objects.isVisible())
        self.assertIn("收起", self.page.deployment_list_toggle.text())
        self.page.deployment_list_toggle.setChecked(False)
        self.application.processEvents()
        self.assertFalse(self.page.deployment_objects.isVisible())
        self.page.deployment_list_toggle.setChecked(True)
        self.application.processEvents()
        self.assertTrue(self.page.deployment_objects.isVisible())
        self.assertTrue(self.page.open_deployment_button.isVisible())
        self.assertFalse(self.page.deployment_tabs.isVisible())

    def test_empty_shop_page_keeps_safe_editor_in_advanced_dialog(self) -> None:
        self.page.editor_tabs.setCurrentIndex(2)
        self.application.processEvents()
        self.assertEqual(self.page.trigger_table.rowCount(), 0)
        self.assertFalse(self.page.trigger_table.isVisible())
        self.assertTrue(self.page.open_trigger_button.isVisible())

    def test_overlays_follow_the_active_legacy_tab(self) -> None:
        self.page.editor_tabs.setCurrentIndex(0)
        self.application.processEvents()
        self.assertEqual(self.page.canvas.overlays, [])
        self.page.editor_tabs.setCurrentIndex(1)
        self.application.processEvents()
        expected = (
            self.page.enemy_table.rowCount()
            + self.page.guest_table.rowCount()
            + self.page.player_table.rowCount()
        )
        self.assertEqual(len(self.page.canvas.overlays), expected)

    def test_pending_draft_api_commits_valid_and_rejects_invalid_input(self) -> None:
        self.assertFalse(self.page.has_pending_draft)
        original_tile = self.page.staged_tiles[0]
        changed_tile = (original_tile + 1) & 0x0F
        self.page.staged_tiles[0] = changed_tile
        self.page._update_size_label()
        self.assertTrue(self.page.has_pending_draft)
        self.assertIsNone(self.page.pending_draft_error)
        self.assertTrue(self.page.commit_pending_changes())
        self.assertEqual(self.project.get_map(0).tiles[0], changed_tile)
        self.assertFalse(self.page.has_pending_draft)

        before_invalid = bytes(self.project.working)
        self.page.prelude.setText("0")
        self.assertTrue(self.page.has_pending_draft)
        self.assertTrue(self.page.apply_button.isEnabled())
        self.assertIn("完整", self.page.pending_draft_error or "")
        self.assertFalse(self.page.commit_pending_changes())
        self.assertEqual(bytes(self.project.working), before_invalid)

    def test_invalid_draft_blocks_chapter_switch_instead_of_being_discarded(self) -> None:
        errors: list[str] = []
        self.page.show_error = lambda error: errors.append(str(error))
        self.page.prelude.setText("0")
        self.assertTrue(self.page.has_pending_draft)

        self.page.map_list.setCurrentRow(1)
        self.application.processEvents()

        self.assertEqual(self.page.current_map_id, 0)
        self.assertEqual(self.page.map_list.currentRow(), 0)
        self.assertTrue(errors)
        self.assertIn("完整", errors[-1])


if __name__ == "__main__":
    unittest.main(verbosity=2)
