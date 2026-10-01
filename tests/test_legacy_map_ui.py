from __future__ import annotations

import os
import hashlib
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QSize, Qt
from PySide6.QtGui import QColor, QImage
from PySide6.QtTest import QTest
from PySide6.QtWidgets import (
    QApplication, QAbstractSpinBox, QDialogButtonBox, QHeaderView,
)

from dc_modifier.app import DEFAULT_ROM
from dc_modifier.map_page import (
    MapPage,
    NesColorButton,
    NesPaletteDialog,
    TerrainButton,
    TileAttributeDialog,
    _glyph_file_offset,
    _legacy_dpi_tile_pixmap,
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
            ["战场地图", "初始配置", "地图事件/商店"],
        )
        self.assertEqual(self.page.map_list.item(0).text(), "001：伏击之战")
        chapter_margins = self.page.chapter_group.layout().contentsMargins()
        self.assertEqual(
            (
                chapter_margins.left(),
                chapter_margins.top(),
                chapter_margins.right(),
                chapter_margins.bottom(),
            ),
            (8, 18, 8, 8),
        )
        self.assertEqual(self.page.title_preview.text(), "")
        self.assertFalse(self.page.title_preview.pixmap().isNull())
        self.assertFalse(hasattr(self.page, "search"))
        self.assertFalse(hasattr(self.page, "map_count_label"))
        self.assertEqual(
            self.page.map_scroll.horizontalScrollBarPolicy(),
            Qt.ScrollBarPolicy.ScrollBarAsNeeded,
        )
        self.assertEqual(
            self.page.map_scroll.verticalScrollBarPolicy(),
            Qt.ScrollBarPolicy.ScrollBarAsNeeded,
        )
        self.assertEqual(
            self.page.map_scroll.alignment(),
            Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop,
        )
        self.assertLessEqual(
            self.page.canvas.width(), self.page.map_scroll.viewport().width()
        )
        self.assertLessEqual(
            self.page.canvas.height(), self.page.map_scroll.viewport().height()
        )

    def test_tileset_d_reads_the_verified_expanded_chr_bank(self) -> None:
        pixels = bytearray()
        for image in self.page.canvas.tile_images:
            for y in range(16):
                for x in range(16):
                    pixels.extend(image.pixelColor(x, y).rgba().to_bytes(4, "little"))
        self.assertEqual(
            hashlib.sha256(pixels).hexdigest(),
            "8942e101d1a1af099bdc60d21f9f808394cbf2f34b2c3a54435ab8aba8cb0e8c",
        )

    def test_tileset_buttons_use_legacy_two_stage_dpi_scaling(self) -> None:
        pixmap = _legacy_dpi_tile_pixmap(
            self.page.canvas.tile_images[0], 32, 1.25
        )
        self.assertEqual(pixmap.size(), QSize(40, 40))
        self.assertEqual(pixmap.devicePixelRatio(), 1.25)
        self.assertEqual(pixmap.deviceIndependentSize(), QSize(32, 32))
        button = self.page.terrain_buttons.button(0)
        self.assertIsInstance(button, TerrainButton)
        self.assertFalse(button._tile_pixmap.isNull())
        self.assertTrue(button.icon().isNull())

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
            (128, 32),
        )

    def test_map_tiles_render_edge_to_edge_without_editor_grid(self) -> None:
        tile = QImage(8, 8, QImage.Format.Format_ARGB32)
        tile.fill(QColor("#12ab34"))
        self.page.canvas.set_tile_images(tuple(tile for _index in range(16)))
        self.page.canvas.set_cell_size(8)
        self.page.canvas.set_content(2, 1, [0, 0], [])
        image = self.page.canvas.grab().toImage()
        self.assertEqual((image.width(), image.height()), (16, 8))
        self.assertEqual(
            {image.pixelColor(x, y).name() for y in range(8) for x in range(16)},
            {"#12ab34"},
        )

    def test_map_preview_uses_reference_dpi_interpolation(self) -> None:
        tile = QImage(16, 16, QImage.Format.Format_RGB32)
        for y in range(16):
            for x in range(16):
                tile.setPixelColor(x, y, QColor("#0000a8" if x < 8 else "#3cbcfc"))
        self.page.canvas.set_tile_images(tuple(tile for _index in range(16)))
        self.page.canvas.set_cell_size(20)
        self.page.canvas.set_content(1, 1, [0], [])
        image = self.page.canvas.grab().toImage()
        colors = {
            image.pixelColor(x, y).name()
            for y in range(image.height()) for x in range(image.width())
        }
        self.assertIn("#0000a8", colors)
        self.assertGreater(len(colors), 2)

    def test_battlefield_keeps_advanced_raw_data_separate_from_visible_dimensions(self) -> None:
        self.assertEqual(self.page.bitmap_selector.currentText(), "位图D")
        self.assertEqual(self.page.tileset.currentData(), "D")
        self.assertEqual(len(self.page.terrain_buttons.buttons()), 16)
        self.assertFalse(self.page.width_display.isReadOnly())
        self.assertFalse(self.page.height_display.isReadOnly())
        self.assertTrue(self.page.width_display.isVisible())
        self.assertTrue(self.page.height_display.isVisible())
        for advanced_control in (
            self.page.width_editor,
            self.page.height_editor,
            self.page.prelude,
            self.page.show_ids,
            self.page.zoom,
            self.page.fit_view,
            self.page.show_all_objects,
        ):
            self.assertFalse(advanced_control.isVisible())
        for visible_control in (self.page.size_label,
                                self.page.capacity_help_button):
            self.assertTrue(visible_control.isVisible())
        self.assertFalse(self.page.pending_state.isVisible())
        self.assertFalse(self.page.apply_button.isVisible())
        self.assertTrue(self.page.open_map_advanced_button.isVisible())

    def test_battlefield_controls_follow_reference_geometry(self) -> None:
        buttons = self.page.terrain_buttons.buttons()
        self.assertEqual(self.page.canvas.selected_tile, 1)
        self.assertEqual(self.page.canvas.right_selected_tile, 0)
        self.assertTrue(buttons[1].isChecked())
        self.assertEqual(buttons[1].geometry().left(), buttons[0].geometry().right() + 1)
        self.assertEqual(buttons[8].geometry().top(), buttons[0].geometry().bottom() + 2)
        for button in buttons:
            self.assertEqual(button.size(), QSize(32, 32))
            self.assertEqual(button.iconSize(), QSize(32, 32))
            self.assertIn("QPushButton#terrainButton", button.styleSheet())
            self.assertNotIn("border: 3px", button.styleSheet())
        palette_image = self.page.terrain_palette.grab().toImage()
        self.assertEqual(self.page.terrain_palette.size(), QSize(256, 65))
        self.assertTrue(
            all(
                palette_image.pixelColor(x, 32).name() == "#000000"
                for x in range(palette_image.width())
            )
        )
        self.assertEqual(
            self.page.width_display.buttonSymbols(),
            QAbstractSpinBox.ButtonSymbols.NoButtons,
        )
        self.assertEqual(
            self.page.height_display.buttonSymbols(),
            QAbstractSpinBox.ButtonSymbols.NoButtons,
        )
        self.assertEqual(self.page.height_display.objectName(), "mapHeightSpin")
        self.assertIn(
            "QTabWidget#subTabs::pane {",
            self.page.styleSheet(),
        )
        before = self.page.width_display.value()
        self.page.width_increase_button.click()
        self.assertEqual(self.page.width_display.value(), min(32, before + 1))
        self.page.width_decrease_button.click()
        self.assertEqual(self.page.width_display.value(), before)
        self.assertLess(
            self.page.width_decrease_button.geometry().left(),
            self.page.width_increase_button.geometry().left(),
        )
        before_height = self.page.height_display.value()
        self.page.height_increase_button.click()
        self.assertEqual(
            self.page.height_display.value(), min(32, before_height + 1)
        )
        self.page.height_decrease_button.click()
        self.assertEqual(self.page.height_display.value(), before_height)
        self.assertEqual(
            {self.page.height_decrease_button.size(),
             self.page.height_increase_button.size()},
            {QSize(15, 14)},
        )
        self.assertEqual(
            {self.page.width_decrease_button.size(),
             self.page.width_increase_button.size()},
            {QSize(15, 28)},
        )
        self.assertEqual(
            self.page.height_decrease_button.direction, Qt.ArrowType.DownArrow
        )
        self.assertEqual(
            self.page.height_increase_button.direction, Qt.ArrowType.UpArrow
        )
        self.assertEqual(
            self.page.height_decrease_button.geometry().left(),
            self.page.height_increase_button.geometry().left(),
        )
        self.assertLess(
            self.page.height_increase_button.geometry().top(),
            self.page.height_decrease_button.geometry().top(),
        )
        self.assertLessEqual(
            self.page.right_brush_preview.geometry().bottom(),
            self.page.brush_group.contentsRect().bottom(),
        )
        left_center = self.page.left_brush_preview.mapTo(
            self.page.brush_group, self.page.left_brush_preview.rect().center()
        ).x()
        right_center = self.page.right_brush_preview.mapTo(
            self.page.brush_group, self.page.right_brush_preview.rect().center()
        ).x()
        library_center = self.page.tileset.mapTo(
            self.page.brush_group, self.page.tileset.rect().center()
        ).x()
        self.assertLess(left_center, library_center)
        self.assertLess(library_center, right_center)
        self.assertLessEqual(abs((left_center + right_center) - 2 * library_center), 4)
        self.assertEqual(self.page.tileset.size(), QSize(128, 24))
        self.assertEqual(self.page.tileset.view().minimumWidth(), 180)
        self.assertLess(self.page.tileset.width(), self.page.brush_group.width() * 0.65)
        expected_tilesets = [
            f"[{bank:02X}]{bank:03d}: "
            f"{self.project.chr_codec.offset + bank * 0x400:06X}"
            for bank in (0x04, 0x05, 0x06, 0x3D, 0x3F, 0x07, 0x41, 0x45)
        ]
        self.assertEqual(
            [self.page.tileset.itemText(index) for index in range(8)],
            expected_tilesets,
        )
        for button in (
            self.page.open_map_advanced_button,
            self.page.capacity_help_button,
        ):
            self.assertGreater(
                button.mapTo(self.page.canvas_host, button.rect().topLeft()).y(),
                self.page.map_scroll.geometry().bottom(),
            )
        self.assertLess(
            self.page.open_map_advanced_button.geometry().left(),
            self.page.capacity_help_button.geometry().left(),
        )
        self.assertLess(
            self.page.reset_button.geometry().left(),
            self.page.open_map_advanced_button.geometry().left(),
        )
        self.assertEqual(self.page.map_list.font().pixelSize(), 13)
        self.assertGreaterEqual(self.page.map_list.fontMetrics().height(), 13)
        self.assertLessEqual(self.page.map_list.fontMetrics().height(), 17)
        self.assertLessEqual(self.page.map_list.sizeHintForRow(0), 20)
        self.assertLessEqual(
            self.page.canvas.cell_size
            * self.page.map_scroll.viewport().devicePixelRatioF(),
            20.5,
        )
        chapter_margins = self.page.chapter_group.layout().contentsMargins()
        self.assertEqual(chapter_margins.left(), 8)
        self.assertEqual(chapter_margins.right(), 8)
        self.assertGreaterEqual(
            self.page.title_preview.geometry().top()
            - self.page.height_display.mapTo(
                self.page.title_preview.parentWidget(),
                self.page.height_display.rect().bottomLeft(),
            ).y(),
            18,
        )

    def test_main_dimension_spins_stage_rle_resize_and_update_canvas(self) -> None:
        original_width = self.page.staged_width
        original_height = self.page.staged_height
        original_tiles = tuple(self.page.staged_tiles)
        original_rom = bytes(self.project.working)
        self.assertEqual((self.page.width_display.minimum(), self.page.width_display.maximum()), (1, 32))
        self.assertEqual((self.page.height_display.minimum(), self.page.height_display.maximum()), (1, 32))
        self.assertGreater(original_width, 1)
        self.page.width_display.setValue(original_width - 1)
        self.application.processEvents()
        self.assertEqual(self.page.staged_width, original_width - 1)
        self.assertEqual(self.page.width_editor.value(), original_width - 1)
        self.assertEqual(self.page.canvas.map_width, original_width - 1)
        self.assertEqual(self.page.canvas.map_height, original_height)
        self.assertEqual(
            tuple(self.page.staged_tiles[: original_width - 1]),
            original_tiles[: original_width - 1],
        )
        self.assertTrue(self.page.has_pending_draft)
        self.page.height_display.setValue(original_height - 1)
        self.application.processEvents()
        self.assertEqual(self.page.staged_height, original_height - 1)
        self.assertEqual(self.page.height_editor.value(), original_height - 1)
        self.assertEqual(self.page.canvas.map_height, original_height - 1)
        self.assertEqual(bytes(self.project.working), original_rom)

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
        self.assertEqual(self.page.left_brush_preview.size(), QSize(32, 32))
        self.assertEqual(self.page.right_brush_preview.size(), QSize(32, 32))
        self.assertEqual(self.page.left_brush_preview.pixmap().size().width(), 32)
        self.assertEqual(self.page.right_brush_preview.pixmap().size().height(), 32)
        for preview in (
            self.page.left_brush_preview,
            self.page.right_brush_preview,
        ):
            self.assertIn("颜色表：", preview.toolTip())
            self.assertIn("防御补正：", preview.toolTip())
            self.assertIn("海属性：", preview.toolTip())
            self.assertIn("空中通行：", preview.toolTip())
            self.assertIn("移动补正：陆", preview.toolTip())
        for preview, tile in (
            (self.page.left_brush_preview, 3),
            (self.page.right_brush_preview, 7),
        ):
            expected = self.page.canvas.tile_images[tile].scaled(
                32,
                32,
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
        self.assertEqual(dialog.size(), QSize(920, 600))
        self.assertEqual(dialog.minimumSize(), QSize(860, 540))
        self.assertEqual(dialog.palette_preview.size(), QSize(104, 28))
        self.assertFalse(hasattr(dialog, "color_spins"))
        self.assertTrue(
            all(button.size() == QSize(72, 28) for button in dialog.color_buttons)
        )
        self.assertEqual(dialog.table.verticalHeader().defaultSectionSize(), 27)
        self.assertEqual(dialog.table.horizontalHeaderItem(1).text(), "颜色表")
        self.assertEqual(
            tuple(dialog.table.columnWidth(index) for index in range(1, 6)),
            (92, 86, 44, 48, 66),
        )
        self.assertTrue(
            all(
                dialog.table.horizontalHeader().sectionResizeMode(index)
                == QHeaderView.ResizeMode.Stretch
                for index in (6, 7, 8)
            )
        )
        self.assertTrue(all(button.height() == 29 for button in dialog.buttons.buttons()))
        self.assertEqual(tuple(dialog.tileset_buttons), tuple("ABCDEFGH"))
        self.assertTrue(dialog.tileset_buttons["D"].isChecked())
        self.assertTrue(
            all(
                preview.size() == QSize(64, 24) and not preview.pixmap().isNull()
                for preview in dialog.shared_palette_previews.values()
            )
        )
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
        self.assertEqual(picker.windowTitle(), "调色板选择")
        self.assertEqual((picker.width(), picker.height()), (544, 150))
        picker_layout = picker.layout()
        picker_layout.activate()
        self.assertIsNotNone(picker_layout.itemAtPosition(0, 15))
        self.assertIsNotNone(picker_layout.itemAtPosition(1, 0))
        self.assertIsNotNone(picker_layout.itemAtPosition(3, 15))
        first = picker_layout.itemAtPosition(0, 0).widget()
        second = picker_layout.itemAtPosition(0, 1).widget()
        self.assertEqual((first.width(), first.height()), (32, 30))
        self.assertEqual(second.geometry().left() - first.geometry().right(), 2)
        picker._select(0x1A)
        self.assertEqual(picker.selected_value, 0x1A)

        before_rom = bytes(self.project.working)
        dialog = TileAttributeDialog(
            self.project, "D", self.page.canvas.tile_images, self.page
        )
        self.assertFalse(dialog.sea_checks[5].isChecked())
        self.assertIn("ROM 海属性位：0（否）", dialog.sea_checks[5].toolTip())
        self.assertIn("不根据图形推断", dialog.sea_checks[5].toolTip())
        self.assertEqual(dialog.table.horizontalHeaderItem(6).text(), "空中通行")
        self.assertEqual(dialog.air_boxes[8].count(), 2)
        self.assertEqual(dialog.air_boxes[8].currentText(), "可以通行")
        self.assertEqual(dialog.palette_boxes[5].currentText(), "颜色表2")
        self.assertEqual(dialog.defense_spins[5].value(), 85)
        self.assertEqual(dialog.air_boxes[5].currentText(), "可以通行")
        self.assertEqual(dialog.land_boxes[5].currentText(), "补正2格")
        self.assertEqual(dialog.sea_boxes[5].currentText(), "不补正")
        tile_zero = dialog.table.item(0, 0).icon().pixmap(16, 16).toImage()
        expected_zero = render_map_tile(
            self.project,
            "D",
            0,
            attributes=self.project.get_map_tileset_attributes("D"),
        )
        self.assertEqual(tile_zero, expected_zero)
        before_icon = dialog.table.item(1, 0).icon().pixmap(16, 16).toImage()
        dialog.color_buttons[1].set_value(0x0F)
        after_icon = dialog.table.item(1, 0).icon().pixmap(16, 16).toImage()
        self.assertNotEqual(before_icon, after_icon)
        self.assertEqual(bytes(self.project.working), before_rom)
        self.assertEqual(dialog.color_buttons[1].value, 0x0F)
        for palette_index in (2, 3):
            reference = dialog.shared_palette_tiles[palette_index]
            self.assertIn(
                "引用位图",
                reference.text(),
            )
            self.assertNotIn("$", reference.text())
            self.assertIn("不在此窗口显示或修改色号", reference.toolTip())
            self.assertTrue(dialog.palette_boxes[0].itemIcon(palette_index).isNull())
        for palette_index in (2, 3):
            preview = dialog.shared_palette_previews[palette_index]
            self.assertFalse(preview.pixmap().isNull())
            self.assertIn("组合预览（只读）", preview.toolTip())
            self.assertNotIn("$", preview.toolTip())
        self.assertEqual(
            tuple(dialog.palette_boxes[0].itemText(index) for index in range(4)),
            ("背景色", "颜色表1", "颜色表2", "颜色表3"),
        )

    def test_tile_attribute_heal_controls_are_exclusive_and_edit_global_ratio(self) -> None:
        dialog = TileAttributeDialog(
            self.project, "D", self.page.canvas.tile_images, self.page
        )
        self.assertEqual(dialog.table.columnCount(), 9)
        self.assertTrue(dialog.heal_checks[0x0A].isChecked())
        self.assertTrue(dialog.heal_ratio_spins[0x0A].isEnabled())
        self.assertEqual(dialog.heal_ratio_spins[0x0A].value(), 30)
        self.assertFalse(dialog.heal_ratio_spins[2].isEnabled())

        dialog.heal_checks[2].setChecked(True)
        self.assertTrue(dialog.heal_checks[2].isChecked())
        self.assertFalse(dialog.heal_checks[0x0A].isChecked())
        self.assertTrue(dialog.heal_ratio_spins[2].isEnabled())
        dialog.heal_ratio_spins[2].setValue(45)
        self.assertTrue(all(spin.value() == 45 for spin in dialog.heal_ratio_spins))
        dialog.accept()

        for key in "ABCDEFGH":
            value = self.project.get_map_tileset_attributes(key)
            self.assertEqual(value.heal_ratio, 45)
            self.assertTrue(value.tiles[2].heal)
            self.assertEqual(sum(tile.heal for tile in value.tiles), 1)


    def test_runtime_verified_tileset_h_is_editable(self) -> None:
        dialog = TileAttributeDialog(
            self.project, "H", self.page.canvas.tile_images, self.page
        )
        self.assertTrue(dialog._supported)
        self.assertTrue(
            dialog.buttons.button(QDialogButtonBox.StandardButton.Save).isEnabled()
        )

    def test_tile_attribute_dialog_switches_a_to_h_and_keeps_drafts(self) -> None:
        original_d = self.project.get_map_tileset_attributes("D")
        original_e = self.project.get_map_tileset_attributes("E")
        undo_count = len(self.project._undo_stack)
        changed_d = (original_d.tiles[1].defense + 1) & 0x7F
        changed_e = (original_e.tiles[2].defense + 2) & 0x7F

        cancelled = TileAttributeDialog(
            self.project, "D", self.page.canvas.tile_images, self.page
        )
        cancelled.defense_spins[1].setValue(changed_d)
        cancelled.tileset_buttons["E"].click()
        cancelled.defense_spins[2].setValue(changed_e)
        cancelled.reject()
        self.assertEqual(self.project.get_map_tileset_attributes("D"), original_d)
        self.assertEqual(self.project.get_map_tileset_attributes("E"), original_e)

        dialog = TileAttributeDialog(
            self.project, "D", self.page.canvas.tile_images, self.page
        )
        dialog.defense_spins[1].setValue(changed_d)
        dialog.tileset_buttons["E"].click()
        self.assertEqual(dialog.tileset_key, "E")
        self.assertEqual(dialog.defense_spins[2].value(), original_e.tiles[2].defense)
        self.assertIn("图库 E", dialog.notice.text())
        dialog.defense_spins[2].setValue(changed_e)
        dialog.tileset_buttons["D"].click()
        self.assertEqual(dialog.defense_spins[1].value(), changed_d)

        dialog.accept()
        self.assertEqual(
            self.project.get_map_tileset_attributes("D").tiles[1].defense,
            changed_d,
        )
        self.assertEqual(
            self.project.get_map_tileset_attributes("E").tiles[2].defense,
            changed_e,
        )
        self.assertEqual(len(self.project._undo_stack), undo_count + 1)
        self.project.undo()
        self.assertEqual(self.project.get_map_tileset_attributes("D"), original_d)
        self.assertEqual(self.project.get_map_tileset_attributes("E"), original_e)

    def test_initial_configuration_defaults_to_real_icon_sheets(self) -> None:
        self.page.editor_tabs.setCurrentIndex(1)
        self.application.processEvents()
        self.assertEqual(
            [selector.currentData() for selector in self.page.icon_bank_selectors],
            [0x34, 0x35, 0x36],
        )
        self.assertFalse(hasattr(self.page, "icon_preview_toggle"))
        for selector, preview in zip(
            self.page.icon_bank_selectors,
            self.page.icon_sheet_labels,
            strict=True,
        ):
            self.assertIn(":", selector.currentText())
            self.assertEqual(selector.width(), 180)
            self.assertEqual(preview.size(), QSize(256, 64))
            self.assertTrue(preview.isVisible())
            self.assertFalse(preview.pixmap().isNull())
            self.assertEqual(preview.pixmap().size(), QSize(256, 64))
            self.assertGreater(preview.geometry().top(), selector.geometry().bottom())
            self.assertLess(preview.geometry().right(), self.page.icon_preview_group.width())
        self.assertTrue(self.page.icon_preview_group.isVisible())
        self.assertEqual(self.page.icon_preview_group.height(), 325)
        self.assertFalse(hasattr(self.page, "deployment_list_toggle"))
        self.assertFalse(self.page.deployment_summary.isVisible())
        self.assertTrue(self.page.add_deployment_button.isVisible())
        self.assertTrue(self.page.add_deployment_button.isEnabled())
        self.assertFalse(self.page.edit_deployment_button.isEnabled())
        self.assertFalse(self.page.copy_deployment_button.isEnabled())
        self.assertLess(
            self.page.add_deployment_button.geometry().bottom(),
            self.page.reset_button.geometry().top(),
        )
        self.page.editor_tabs.setCurrentIndex(0)
        self.application.processEvents()
        self.assertFalse(self.page.add_deployment_button.isVisible())
        self.page.editor_tabs.setCurrentIndex(1)
        self.application.processEvents()
        self.assertTrue(self.page.add_deployment_button.isVisible())
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
        self.assertFalse(self.page.deployment_objects.isVisible())
        self.assertFalse(self.page.deployment_tabs.isVisible())

    def test_empty_shop_page_uses_map_editor_without_bulk_button(self) -> None:
        self.page.editor_tabs.setCurrentIndex(2)
        self.application.processEvents()
        self.assertEqual(self.page.trigger_table.rowCount(), 0)
        self.assertFalse(self.page.trigger_table.isVisible())
        self.assertFalse(hasattr(self.page, "open_trigger_button"))

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
