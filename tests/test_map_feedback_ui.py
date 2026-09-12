from __future__ import annotations

import os
from types import SimpleNamespace
import unittest
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QPoint, Qt
from PySide6.QtTest import QSignalSpy, QTest
from PySide6.QtWidgets import QApplication

from dc_modifier.app import DEFAULT_ROM
from dc_modifier.database_graphics import palette_color
from dc_modifier.map_page import (
    ByteEntryTable,
    ICON_PALETTE,
    ICON_PALETTE_NES,
    MapPage,
    MAP_ICON_BANKS,
    MAP_ICON_PALETTES_NES,
    render_unit_icon_bank,
    render_unit_map_icon,
)
from fc_rom_editor_core import RomProject


from tests.qt_test_case import QtTestCase


class MapFeedbackUiTests(QtTestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.application = QApplication.instance() or QApplication([])

    def setUp(self) -> None:
        self.project = RomProject.load(DEFAULT_ROM)
        self.page = MapPage()
        self.page.resize(1280, 820)
        self.page.set_project(self.project)
        self.page.show()
        self.application.processEvents()

    def tearDown(self) -> None:
        self.page.close()
        self.page.deleteLater()
        self.application.processEvents()

    def test_icon_bank_uses_all_four_quadrants_without_inventing_unit_bindings(self) -> None:
        self.assertEqual(ICON_PALETTE_NES, (0x0F, 0x30, 0x21, 0x02))
        self.assertEqual(
            ICON_PALETTE,
            tuple(palette_color(value) for value in ICON_PALETTE_NES),
        )
        calls = []
        def pixels(tile):
            calls.append(tile)
            return [tile % 4] * 64
        image = render_unit_icon_bank(SimpleNamespace(chr_tile_pixels=pixels), 0x34)
        self.assertEqual((image.width(), image.height()), (256, 16))
        self.assertEqual(calls, list(range(0x34 * 64, 0x35 * 64)))
        for x, y, color in ((0, 0, 0), (8, 0, 1), (0, 8, 2), (8, 8, 3)):
            self.assertEqual(image.pixelColor(x, y), ICON_PALETTE[color])

    def test_unit_map_icon_uses_verified_record_index_and_all_four_tiles(self) -> None:
        calls = []
        raw = bytearray(16)
        raw[2] = 0x84

        class Project:
            unit_count = 256

            @staticmethod
            def record_bytes(_unit_id):
                return bytes(raw)

            @staticmethod
            def chr_tile_pixels(tile):
                calls.append(tile)
                return [0 if tile == calls[0] else min(len(calls), 3)] * 64

        image = render_unit_map_icon(Project(), 1, "敌")
        expected_first = MAP_ICON_BANKS[2] * 64 + 4
        self.assertEqual(calls, list(range(expected_first, expected_first + 4)))
        self.assertEqual(image.pixelColor(0, 0).alpha(), 0)
        enemy_colors = tuple(
            palette_color(value) for value in MAP_ICON_PALETTES_NES["敌"]
        )
        self.assertEqual(image.pixelColor(8, 0), enemy_colors[2])
        self.assertEqual(image.pixelColor(0, 8), enemy_colors[3])

    def test_every_static_deployment_resolves_real_unit_icon_and_correct_field_order(self) -> None:
        for map_id in range(self.project.scenario_count):
            layout = self.project.get_scenario_layout(map_id)
            for entity in (*layout.enemies, *layout.guests):
                icon_index = self.project.record_bytes(entity.unit_id)[2]
                self.assertEqual(icon_index % 4, 0)
                self.assertLess(icon_index, len(MAP_ICON_BANKS) * 64)
                self.assertFalse(
                    render_unit_map_icon(self.project, entity.unit_id, "敌").isNull()
                )
        first = self.project.get_scenario_layout(3).enemies[0]
        self.assertEqual((first.pilot_id, first.unit_id), (31, 99))
        self.assertNotIn("空白", self.project.character_display_name(first.pilot_id))
        self.assertNotIn("空白", self.project.unit_display_name(first.unit_id))

        self.page.map_list.setCurrentRow(3)
        self.page.editor_tabs.setCurrentIndex(1)
        self.application.processEvents()
        self.assertIn("白色要塞", self.page.deployment_objects.item(0).text())
        self.assertIn("布莱德", self.page.deployment_objects.item(0).text())
        self.assertFalse(self.page.canvas.overlay_images[("敌", 0)].isNull())

    def test_initial_configuration_distinguishes_empty_scenario_and_map_only_slots(self) -> None:
        self.page.editor_tabs.setCurrentIndex(1)
        self.page.map_list.setCurrentRow(0)
        self.application.processEvents()
        self.assertIn("初始配置表为空", self.page.deployment_summary.text())
        self.page.map_list.setCurrentRow(self.project.scenario_count)
        self.application.processEvents()
        self.assertIn("不属于ROM中的", self.page.deployment_summary.text())
        self.assertIn(
            str(self.project.scenario_count), self.page.deployment_summary.text()
        )

    def test_batch_table_load_has_one_change_notification_and_reuses_labels(self) -> None:
        labels = []
        def provider(value):
            labels.append(value)
            return str(value)
        table = ByteEntryTable(("X", "Y", "机体"), {2: provider})
        spy = QSignalSpy(table.values_changed)
        table.set_rows([(1, 2, 3), (4, 5, 6), (7, 8, 9)])
        self.assertEqual(spy.count(), 1)
        self.assertEqual(len(labels), 256)
        table.set_rows([(1, 2, 4), (5, 6, 8)])
        self.assertEqual(spy.count(), 2)
        self.assertEqual(len(labels), 256)
        table.set_row_coordinates(0, 8, 9)
        self.assertEqual(spy.count(), 3)
        table.deleteLater()

    def test_chapter_load_populates_once_and_does_not_validate_partial_tables(self) -> None:
        with patch.object(self.page, "_load_map_record", wraps=self.page._load_map_record) as load:
            self.page.refresh()
        self.assertEqual(load.call_count, 1)
        self.assertFalse(self.page.has_pending_draft)
        self.assertEqual(self.page.deployment_objects.count(),
                         sum(table.rowCount() for table in
                             (self.page.enemy_table, self.page.guest_table, self.page.player_table)))

    def test_deployment_click_selects_named_list_and_never_paints_empty_ground(self) -> None:
        self.page.enemy_table.set_rows([(3, 4, 1, 1, 5, 0)])
        signature = self.page._draft_signature()
        self.page.editor_tabs.setCurrentIndex(1)
        self.application.processEvents()
        self.assertTrue(self.page.deployment_objects.isVisible())
        self.assertFalse(self.page.canvas.paint_enabled)
        side, x, y, _label, row = self.page.canvas.overlays[0]
        position = QPoint(x * self.page.canvas.cell_size + 3, y * self.page.canvas.cell_size + 3)
        QTest.mouseClick(self.page.canvas, Qt.MouseButton.LeftButton, pos=position)
        self.assertEqual(self.page.canvas.selected_overlay, (side, row))
        self.assertEqual(tuple(self.page.deployment_objects.currentItem().data(Qt.ItemDataRole.UserRole)),
                         (side, row))
        self.assertEqual(self.page._draft_signature(), signature)
        before = tuple(self.page.staged_tiles)
        self.page.canvas.selected_tile = 15
        self.page.canvas._paint_at(QPoint(1, 1), 15)
        self.assertEqual(tuple(self.page.staged_tiles), before)

    def test_selection_and_double_click_open_nonmodal_editor_at_exact_record(self) -> None:
        self.page.enemy_table.set_rows([(3, 4, 1, 1, 5, 0)])
        self.page.editor_tabs.setCurrentIndex(1)
        item = self.page.deployment_objects.item(0)
        side, row = item.data(Qt.ItemDataRole.UserRole)
        self.page._object_list_activated(item)
        self.assertFalse(self.page.deployment_dialog.isModal())
        self.assertTrue(self.page.deployment_dialog.isVisible())
        self.assertEqual(self.page._object_table(side).currentRow(), row)
        self.page.deployment_dialog.close()

    def test_initial_configuration_right_click_edits_and_adds_at_exact_cell(self) -> None:
        self.page.enemy_table.set_rows([(3, 4, 1, 1, 5, 0)])
        self.page.guest_table.set_rows([])
        self.page.player_table.set_rows([])
        self.page.editor_tabs.setCurrentIndex(1)
        self.application.processEvents()
        self.assertTrue(self.page.canvas.deployment_edit_enabled)
        position = QPoint(
            3 * self.page.canvas.cell_size + 2,
            4 * self.page.canvas.cell_size + 2,
        )
        original_tiles = tuple(self.page.staged_tiles)
        with patch("dc_modifier.map_page.QMenu.popup") as show_menu:
            QTest.mouseClick(
                self.page.canvas, Qt.MouseButton.RightButton, pos=position
            )
        show_menu.assert_called_once()
        self.assertEqual(tuple(self.page.staged_tiles), original_tiles)
        actions = {
            action.text(): action
            for action in self.page._deployment_context_menu.actions()
        }
        self.assertIn("编辑敌军初始配置", actions)
        self.assertIn("在此格添加初始配置", actions)
        self.assertIn("删除敌军初始配置", actions)
        actions["编辑敌军初始配置"].trigger()
        self.application.processEvents()
        self.assertTrue(self.page.deployment_dialog.isVisible())
        self.assertEqual(self.page.deployment_tabs.currentIndex(), 0)
        self.assertEqual(self.page.enemy_table.currentRow(), 0)
        self.page.deployment_dialog.close()

        add_menu = actions["在此格添加初始配置"].menu()
        guest_action = next(
            action for action in add_menu.actions() if action.text() == "客军"
        )
        guest_action.trigger()
        self.application.processEvents()
        self.assertEqual(self.page.guest_table.rows(), [(3, 4, 0, 1, 1, 0)])
        self.assertEqual(self.page.deployment_tabs.currentIndex(), 1)
        self.page.deployment_dialog.close()

    def test_shop_list_add_drag_commit_and_undo_preserve_record_semantics(self) -> None:
        self.page.editor_tabs.setCurrentIndex(2)
        self.assertIn("没有", self.page.trigger_summary.text())
        self.page.trigger_table.set_rows([(3, 4, 0xFF, 0xF2)])
        self.assertEqual(self.page.trigger_objects.count(), 1)
        self.assertIn("商店 2", self.page.trigger_objects.item(0).text())
        self.assertIn("任何人物", self.page.trigger_objects.item(0).text())
        self.page._overlay_moved("店", 0, 4, 5)
        self.assertEqual(self.page.trigger_table.rows()[0], (4, 5, 0xFF, 0xF2))
        self.assertTrue(self.page.commit_pending_changes())
        self.assertEqual(tuple(self.project.get_map_triggers(0)[0].to_bytes()), (4, 5, 0xFF, 0xF2))
        self.project.undo()
        self.assertEqual(self.project.get_map_triggers(0), ())

    def test_trigger_tab_right_click_adds_edits_and_deletes_at_map_cell(self) -> None:
        self.page.editor_tabs.setCurrentIndex(2)
        self.application.processEvents()
        self.assertTrue(self.page.canvas.trigger_edit_enabled)
        position = QPoint(
            3 * self.page.canvas.cell_size + 2,
            4 * self.page.canvas.cell_size + 2,
        )
        original_tiles = tuple(self.page.staged_tiles)
        with patch("dc_modifier.map_page.QMenu.popup") as show_menu:
            QTest.mouseClick(
                self.page.canvas, Qt.MouseButton.RightButton, pos=position
            )
        show_menu.assert_called_once()
        self.assertEqual(tuple(self.page.staged_tiles), original_tiles)
        actions = {
            action.text(): action
            for action in self.page._trigger_context_menu.actions()
        }
        self.assertIn("添加地图事件", actions)
        self.assertIn("删除地图事件", actions)
        self.assertFalse(actions["删除地图事件"].isEnabled())
        actions["添加地图事件"].trigger()
        self.application.processEvents()
        self.assertTrue(self.page.trigger_cell_dialog.isVisible())
        self.assertEqual(self.page.trigger_x_editor.value(), 3)
        self.assertEqual(self.page.trigger_y_editor.value(), 4)
        self.page.trigger_event_combo.setCurrentIndex(
            self.page.trigger_event_combo.findData(7)
        )
        self.page._save_trigger_cell_editor()
        self.assertEqual(self.page.trigger_table.rows(), [(3, 4, 0xFF, 7)])

        self.page._open_trigger_cell_editor(3, 4, 0)
        self.page.trigger_shop_radio.setChecked(True)
        self.page.trigger_shop_combo.setCurrentIndex(
            self.page.trigger_shop_combo.findData(0xF2)
        )
        self.page._save_trigger_cell_editor()
        self.assertEqual(self.page.trigger_table.rows(), [(3, 4, 0xFF, 0xF2)])

        with patch("dc_modifier.map_page.QMenu.popup"):
            QTest.mouseClick(
                self.page.canvas, Qt.MouseButton.RightButton, pos=position
            )
        actions = {
            action.text(): action
            for action in self.page._trigger_context_menu.actions()
        }
        self.assertIn("编辑商店", actions)
        self.assertIn("删除地图事件", actions)
        actions["删除地图事件"].trigger()
        self.assertEqual(self.page.trigger_table.rows(), [])

    def test_all_object_overlay_and_manual_zoom_are_accessible(self) -> None:
        self.page.trigger_table.set_rows([(3, 4, 0xFF, 0xF2)])
        self.page.show_all_objects.setChecked(True)
        self.assertEqual(len(self.page.canvas.overlays), self.page.deployment_objects.count() + 1)
        self.page.fit_view.setChecked(False)
        self.page.zoom.setValue(40)
        self.application.processEvents()
        self.assertEqual(self.page.canvas.cell_size, 40)
        self.assertGreater(self.page.map_scroll.horizontalScrollBar().maximum(), 0)

    def test_duplicate_limit_is_reported_and_does_not_change_rows(self) -> None:
        errors = []
        self.page.show_error = lambda error: errors.append(str(error))
        self.page.enemy_table.set_rows([(0, index, 1, 1, 1, 0) for index in range(18)])
        self.page._duplicate_deployment(self.page.enemy_table)
        self.assertEqual(self.page.enemy_table.rowCount(), 18)
        self.assertIn("18", errors[-1])

    def test_capacity_planner_preserves_oversized_draft_and_revalidates_after_linking(self) -> None:
        self.page.height_editor.setValue(30)
        self.page._resize_map()
        draft = self.page._draft_signature()
        self.assertIsNotNone(self.page.pending_draft_error)
        requested = []
        def plan(key):
            requested.append(key)
            self.project.configure_expansion(304, 48, 112)
        self.page.navigation_requested.connect(plan)
        self.page._open_capacity_planner()
        self.assertEqual(requested, ["resources"])
        self.assertEqual(self.page._draft_signature(), draft)
        self.assertIsNone(self.page.pending_draft_error)
        self.assertIn("自动重排", self.page.size_label.text())
        self.assertTrue(self.page.commit_pending_changes())
        self.assertEqual(self.project.get_map(0).height, 30)


if __name__ == "__main__":
    unittest.main(verbosity=2)
