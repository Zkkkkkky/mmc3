from __future__ import annotations

import os
from types import SimpleNamespace
import unittest
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QPoint, Qt
from PySide6.QtGui import QImage
from PySide6.QtTest import QSignalSpy, QTest
from PySide6.QtWidgets import QApplication

from dc_modifier.app import DEFAULT_ROM
from dc_modifier.database_graphics import palette_color
from dc_modifier.map_page import (
    ByteEntryTable,
    ICON_PALETTE,
    ICON_PALETTE_NES,
    MapCanvas,
    MapPage,
    MAP_ICON_BANK_CANDIDATES,
    MAP_ICON_PALETTES_NES,
    SCENARIO_MAP_ICON_BANKS,
    render_unit_icon_bank,
    render_unit_map_icon,
    scenario_map_icon_banks,
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
        route = (0x34, 0x35, 0x3A)
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

        image = render_unit_map_icon(Project(), 1, "敌", route)
        expected_first = route[2] * 64 + 4
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
            route = scenario_map_icon_banks(map_id)
            for entity in (*layout.enemies, *layout.guests):
                icon_index = self.project.record_bytes(entity.unit_id)[2]
                self.assertEqual(icon_index % 4, 0)
                self.assertLess(icon_index, len(route) * 64)
                self.assertFalse(
                    render_unit_map_icon(
                        self.project, entity.unit_id, "敌", route
                    ).isNull()
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

    def test_map_icon_route_changes_with_scenario(self) -> None:
        self.assertEqual(len(SCENARIO_MAP_ICON_BANKS), self.project.scenario_count)
        self.assertEqual(scenario_map_icon_banks(0), (0x34, 0x35, 0x36))
        self.assertEqual(scenario_map_icon_banks(3), (0x34, 0x35, 0x3A))
        self.assertEqual(scenario_map_icon_banks(9), (0x34, 0x35, 0x3E))
        self.assertEqual(scenario_map_icon_banks(26), (0x34, 0x35, 0x44))
        self.assertEqual(scenario_map_icon_banks(27), (0x46, 0x47, 0x3C))
        self.assertEqual(
            MAP_ICON_BANK_CANDIDATES,
            (0x34, 0x35, 0x36, 0x3A, 0x3C, 0x3E, 0x40, 0x44, 0x46, 0x47, 0x48),
        )

    def test_hidden_icon_library_is_lazy_and_table_choices_share_models(self) -> None:
        self.assertFalse(self.page.icon_preview_group.isVisible())
        with patch("dc_modifier.map_page.render_unit_icon_bank") as render_bank:
            self.page.map_list.setCurrentRow(4)
            self.application.processEvents()
        render_bank.assert_not_called()

        self.page.editor_tabs.setCurrentIndex(1)
        self.page.map_list.setCurrentRow(3)
        self.application.processEvents()
        if self.page.enemy_table.rowCount() >= 2:
            first = self.page.enemy_table.cellWidget(0, 2)
            second = self.page.enemy_table.cellWidget(1, 2)
            self.assertIs(first.model(), second.model())
            first_widget = first
            rows = self.page.enemy_table.rows()
            self.page.enemy_table.set_rows(rows)
            self.assertIs(self.page.enemy_table.cellWidget(0, 2), first_widget)

    def test_map_overlays_receive_the_selected_scenario_route(self) -> None:
        icon = QImage(16, 16, QImage.Format.Format_ARGB32)
        icon.fill(Qt.GlobalColor.transparent)
        with patch(
            "dc_modifier.map_page.render_unit_map_icon", return_value=icon
        ) as render:
            self.page.map_list.setCurrentRow(3)
            self.page.editor_tabs.setCurrentIndex(1)
            self.application.processEvents()
            self.assertTrue(render.called)
            self.assertTrue(
                all(call.args[3] == (0x34, 0x35, 0x3A) for call in render.call_args_list)
            )

            render.reset_mock()
            self.page.map_list.setCurrentRow(27)
            self.page.enemy_table.set_rows([(1, 1, 1, 1, 1, 0)])
            self.page._update_overlays()
            self.application.processEvents()
            self.assertTrue(render.called)
            self.assertTrue(
                all(call.args[3] == (0x46, 0x47, 0x3C) for call in render.call_args_list)
            )

    def test_event_party_slots_render_real_icons_and_empty_slots_do_not_fake_units(self) -> None:
        self.page.map_list.setCurrentRow(8)
        self.page.editor_tabs.setCurrentIndex(1)
        self.application.processEvents()
        slots = self.page._player_slot_state()
        self.assertEqual(slots[10], (10, 21))
        self.assertNotIn(6, slots)
        rows = self.page.player_table.rows()
        slot_ten_row = next(row for row, values in enumerate(rows) if values[2] == 10)
        empty_row = next(row for row, values in enumerate(rows) if values[2] == 6)
        self.assertFalse(
            self.page.canvas.overlay_images[("我", slot_ten_row)].isNull()
        )
        self.assertNotIn(("我", empty_row), self.page.canvas.overlay_images)
        list_row = (
            self.page.enemy_table.rowCount()
            + self.page.guest_table.rowCount()
            + empty_row
        )
        self.assertIn(
            "空队伍槽 $06（当前ROM无机体）",
            self.page.deployment_objects.item(list_row).text(),
        )

    def test_all_chapters_visualize_every_rom_bound_player_unit(self) -> None:
        self.page.editor_tabs.setCurrentIndex(1)
        for map_id in range(self.project.scenario_count):
            self.page.map_list.setCurrentRow(map_id)
            self.application.processEvents()
            slots = self.page._player_slot_state()
            for row, values in enumerate(self.page.player_table.rows()):
                key = ("我", row)
                slot = values[2]
                if slot in slots:
                    self.assertIn(key, self.page.canvas.overlay_images)
                    self.assertFalse(self.page.canvas.overlay_images[key].isNull())
                else:
                    self.assertNotIn(key, self.page.canvas.overlay_images)

    def test_real_map_icon_has_no_permanent_faction_border(self) -> None:
        canvas = MapCanvas()
        canvas.set_cell_size(22)
        tile = QImage(16, 16, QImage.Format.Format_RGB32)
        tile.fill(Qt.GlobalColor.white)
        icon = QImage(16, 16, QImage.Format.Format_ARGB32)
        icon.fill(Qt.GlobalColor.transparent)
        canvas.set_tile_images(tuple(tile for _ in range(16)))
        canvas.set_overlay_images({("敌", 0): icon})
        canvas.set_content(1, 1, [0], [("敌", 0, 0, "1", 0)])
        canvas.show()
        self.application.processEvents()
        rendered = canvas.grab().toImage()
        corner = rendered.pixelColor(1, 1)
        self.assertLess(corner.red(), 30)
        self.assertLess(corner.green(), 30)
        self.assertLess(corner.blue(), 30)
        canvas.close()
        canvas.deleteLater()

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

    def test_selection_and_double_click_open_compact_editor_at_exact_record(self) -> None:
        self.page.enemy_table.set_rows([(3, 4, 1, 1, 5, 0)])
        self.page.editor_tabs.setCurrentIndex(1)
        item = self.page.deployment_objects.item(0)
        side, row = item.data(Qt.ItemDataRole.UserRole)
        self.page._object_list_activated(item)
        self.assertFalse(self.page.deployment_cell_dialog.isModal())
        self.assertTrue(self.page.deployment_cell_dialog.isVisible())
        self.assertEqual(self.page._object_table(side).currentRow(), row)
        self.assertEqual(self.page.deployment_side_combo.currentData(), "敌")
        self.assertEqual(self.page.deployment_x_editor.value(), 3)
        self.assertEqual(self.page.deployment_action_combo.currentData(), 0)
        self.page.deployment_cell_dialog.close()

    def test_initial_configuration_right_click_edits_and_adds_at_exact_cell(self) -> None:
        self.project.configure_expansion(288, 64, 112)
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
        self.assertIn("更改敌军初始配置", actions)
        self.assertIn("在此格添加配置", actions)
        self.assertIn("删除敌军初始配置", actions)
        self.assertIn("更改属性", actions)
        self.assertIn("击落经验计算器", actions)
        self.assertIn("加到属性计算器", actions)
        self.assertIn("复制配置", actions)
        self.assertIn("剪切配置", actions)
        self.assertIn("粘贴配置", actions)
        self.assertFalse(actions["粘贴配置"].isEnabled())
        database_requests = QSignalSpy(self.page.database_record_requested)
        actions["更改属性"].trigger()
        self.assertEqual(database_requests.count(), 1)
        self.assertEqual(list(database_requests.at(0)), ["units", 1])
        experience_requests = QSignalSpy(self.page.defeat_experience_requested)
        actions["击落经验计算器"].trigger()
        self.assertEqual(experience_requests.count(), 1)
        self.assertEqual(list(experience_requests.at(0)), [1, 5])
        actions["更改敌军初始配置"].trigger()
        self.application.processEvents()
        self.assertTrue(self.page.deployment_cell_dialog.isVisible())
        self.assertEqual(self.page.deployment_side_combo.currentData(), "敌")
        self.assertEqual(self.page.enemy_table.currentRow(), 0)
        self.page.deployment_cell_dialog.close()

        add_menu = actions["在此格添加配置"].menu()
        guest_action = next(
            action for action in add_menu.actions() if action.text() == "客军"
        )
        guest_action.trigger()
        self.application.processEvents()
        self.assertTrue(self.page.deployment_cell_dialog.isVisible())
        self.assertEqual(self.page.guest_table.rows(), [])
        self.assertEqual(self.page.deployment_side_combo.currentData(), "客")
        self.page._save_deployment_cell_editor()
        self.assertEqual(self.page.guest_table.rows(), [(3, 4, 0, 1, 1, 0)])

    def test_deployment_tooltip_and_table_show_verified_action_and_attributes(self) -> None:
        self.page.map_list.setCurrentRow(4)
        self.page.editor_tabs.setCurrentIndex(1)
        self.application.processEvents()
        item = self.page.deployment_objects.item(1)
        tooltip = item.toolTip()
        self.assertIn("驾驶员", tooltip)
        self.assertIn("机体基础属性", tooltip)
        self.assertIn("人物补正", tooltip)
        self.assertIn("游戏成长属性", tooltip)
        self.assertIn("武器1", tooltip)
        self.assertIn("特技", tooltip)
        self.assertIn("行动：", tooltip)
        self.assertIn("沙也加行动智商", tooltip)
        action_editor = self.page.enemy_table.cellWidget(1, 5)
        self.assertIn("沙也加行动智商", action_editor.currentText())

        # Golden values shown by the reference editor for 沙也加 / 阿弗洛蒂A
        # at level 54. This covers fixed and table-driven growth together.
        reference = list(self.page.enemy_table.rows()[1])
        reference[4] = 54
        level_54 = self.page._deployment_description("敌", tuple(reference))
        self.assertIn(
            "Lv.54 游戏成长属性：HP 1625 · 强度 280 · 防御 227 · 速度 317 · 移动 134",
            level_54,
        )

    def test_map_hover_shows_the_rich_tooltip_immediately(self) -> None:
        self.page.map_list.setCurrentRow(4)
        self.page.editor_tabs.setCurrentIndex(1)
        self.application.processEvents()
        values = self.page.enemy_table.rows()[0]
        position = QPoint(
            values[0] * self.page.canvas.cell_size + 2,
            values[1] * self.page.canvas.cell_size + 2,
        )
        with patch("dc_modifier.map_page.QToolTip.showText") as show_tooltip:
            QTest.mouseMove(self.page.canvas, position)
            self.application.processEvents()
        show_tooltip.assert_called_once()
        self.assertIn("游戏成长属性", show_tooltip.call_args.args[1])

    def test_compact_editor_switches_type_and_context_clipboard_preserves_fields(self) -> None:
        original = (3, 4, 1, 2, 5, 0x22)
        self.page.enemy_table.set_rows([original])
        self.page.guest_table.set_rows([])
        self.page._open_deployment_cell_editor("敌", 3, 4, 0)
        self.page.deployment_side_combo.setCurrentIndex(
            self.page.deployment_side_combo.findData("客")
        )
        self.page._save_deployment_cell_editor()
        self.assertEqual(self.page.enemy_table.rows(), [])
        self.assertEqual(self.page.guest_table.rows(), [original])

        self.project.configure_expansion(288, 64, 112)
        self.page._copy_deployment_record("客", 0)
        self.page._paste_deployment_at(8, 9)
        self.assertEqual(self.page.guest_table.rows()[1], (8, 9, *original[2:]))
        self.page._copy_deployment_record("客", 0, cut=True)
        self.assertEqual(self.page.guest_table.rows(), [(8, 9, *original[2:])])

    def test_full_fixed_deployment_routes_addition_to_capacity_planning(self) -> None:
        self.page.map_list.setCurrentRow(4)
        errors = []
        self.page.show_error = lambda error: errors.append(str(error))
        before = self.page.enemy_table.rows()
        self.page._open_deployment_cell_editor("敌", 0, 0)
        self.page._save_deployment_cell_editor()
        self.assertEqual(self.page.enemy_table.rows(), before)
        self.assertIn("容量规划", errors[-1])
        self.assertIn("148", self.page.deployment_editor_status.text())

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
