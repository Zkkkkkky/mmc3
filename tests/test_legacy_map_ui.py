from __future__ import annotations

import os
from types import SimpleNamespace
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from dc_modifier.app import DEFAULT_ROM
from dc_modifier.map_page import (
    MapPage,
    TerrainButton,
    _glyph_file_offset,
    render_map_title,
)
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

    def test_map_title_renders_the_rom_glyph_instead_of_a_host_font(self) -> None:
        working = bytearray(0x70010 + 18)
        working[0x70010 : 0x70010 + 18] = bytes([0xFF] * 18)
        working[0x70010] = 0x7F
        pixmap = render_map_title(SimpleNamespace(working=working), "啊", scale=2)
        image = pixmap.toImage()
        self.assertEqual(image.pixelColor(8, 0).name(), "#d8d8d8")
        self.assertEqual(image.pixelColor(10, 0).name(), "#000000")

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

    def test_initial_configuration_defaults_to_real_icon_sheets(self) -> None:
        self.page.editor_tabs.setCurrentIndex(1)
        self.page.icon_preview_toggle.setChecked(True)
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
            self.assertFalse(preview.pixmap().isNull())
            self.assertTrue(preview.isVisible())
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
