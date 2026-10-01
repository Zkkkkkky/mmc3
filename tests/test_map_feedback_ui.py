from __future__ import annotations

import os
from types import SimpleNamespace
import unittest
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QPoint, Qt
from PySide6.QtGui import QColor, QFontMetrics, QImage
from PySide6.QtTest import QSignalSpy, QTest
from PySide6.QtWidgets import QApplication, QDialogButtonBox

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

    def test_default_page_enables_verified_deployment_and_triggers(self) -> None:
        guarded_project = RomProject.load(DEFAULT_ROM)
        guarded = MapPage()
        guarded.set_project(guarded_project)
        guarded.show()
        self.application.processEvents()
        try:
            self.assertTrue(guarded.enemy_table.isEnabled())
            self.assertTrue(guarded.enemy_table.editing_enabled)
            self.assertTrue(guarded.trigger_table.editing_enabled)
            guarded.editor_tabs.setCurrentIndex(1)
            guarded._update_overlays()
            self.assertTrue(guarded.canvas.deployment_edit_enabled)
            guarded.editor_tabs.setCurrentIndex(2)
            guarded._update_overlays()
            self.assertTrue(guarded.canvas.overlay_move_enabled)
            self.assertTrue(guarded.trigger_cell_buttons.button(
                QDialogButtonBox.StandardButton.Ok
            ).isEnabled())
            guarded.trigger_table.set_rows([(3, 4, 0xFF, 0xF2)])
            self.assertTrue(guarded.commit_pending_changes())
            self.assertEqual(
                tuple(guarded_project.get_map_triggers(0)[0].to_bytes()),
                (3, 4, 0xFF, 0xF2),
            )
            original_tile = guarded.staged_tiles[0]
            guarded.staged_tiles[0] = (original_tile + 1) & 0x0F
            self.assertTrue(guarded.commit_pending_changes())
            self.assertEqual(guarded_project.get_map(0).tiles[0], guarded.staged_tiles[0])
        finally:
            guarded.close()
            guarded.deleteLater()

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

    def test_icon_library_is_permanent_on_initial_tab_and_lazy_while_inactive(self) -> None:
        self.assertFalse(self.page.icon_preview_group.isVisible())
        with patch("dc_modifier.map_page.render_unit_icon_bank") as render_bank:
            self.page.map_list.setCurrentRow(4)
            self.application.processEvents()
        render_bank.assert_not_called()

        self.page.editor_tabs.setCurrentIndex(1)
        self.page.map_list.setCurrentRow(4)
        self.application.processEvents()
        self.assertTrue(self.page.icon_preview_group.isVisible())
        self.assertTrue(all(not label.toolTip() for label in self.page.icon_sheet_labels))
        self.assertTrue(self.page.add_deployment_button.isVisible())
        self.assertFalse(self.page.deployment_summary.isVisible())
        self.assertFalse(self.page.deployment_objects.isVisible())
        if self.page.enemy_table.rowCount() >= 2:
            first = self.page.enemy_table.cellWidget(0, 2)
            second = self.page.enemy_table.cellWidget(1, 2)
            self.assertIs(first.model(), second.model())
            first_widget = first
            rows = self.page.enemy_table.rows()
            self.page.enemy_table.set_rows(rows)
            self.assertIs(self.page.enemy_table.cellWidget(0, 2), first_widget)

    def test_main_deployment_buttons_edit_add_and_copy_without_large_dialog(self) -> None:
        self.project.configure_expansion(288, 64, 112)
        self.page.map_list.setCurrentRow(4)
        self.page.editor_tabs.setCurrentIndex(1)
        self.application.processEvents()
        self.assertFalse(hasattr(self.page, "deployment_dialog"))
        self.assertTrue(self.page.add_deployment_button.isEnabled())

        self.page.add_deployment_button.click()
        self.application.processEvents()
        self.assertTrue(self.page.deployment_cell_dialog.isVisible())
        self.assertIsNone(self.page._deployment_edit_source)
        self.page.deployment_cell_dialog.close()

        self.page._select_object("敌", 0)
        self.assertTrue(self.page.edit_deployment_button.isEnabled())
        self.assertTrue(self.page.copy_deployment_button.isEnabled())
        self.page.edit_deployment_button.click()
        self.application.processEvents()
        self.assertTrue(self.page.deployment_cell_dialog.isVisible())
        self.assertEqual(self.page._deployment_edit_source, ("敌", 0))
        self.page.deployment_cell_dialog.close()

        before = self.page.enemy_table.rowCount()
        self.page.copy_deployment_button.click()
        self.application.processEvents()
        self.assertEqual(self.page.enemy_table.rowCount(), before + 1)
        self.assertEqual(self.page._deployment_edit_source, ("敌", 1))
        self.assertTrue(self.page.deployment_cell_dialog.isVisible())
        self.assertFalse(hasattr(self.page, "deployment_dialog"))
        self.page.deployment_cell_dialog.close()

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

    def test_player_slots_follow_reference_join_records_by_chapter(self) -> None:
        self.page.map_list.setCurrentRow(4)
        self.page.editor_tabs.setCurrentIndex(1)
        self.application.processEvents()
        slots = self.page._player_slot_state()
        self.assertEqual(
            slots,
            {
                0: (4, 9),
                1: (5, 13),
                2: (6, 15),
                3: (7, 17),
                4: (8, 19),
                5: (9, 23),
                10: (10, 21),
                8: (15, 29),
            },
        )
        self.assertEqual(
            [self.page._deployment_player_slot_choice_label(index) for index in range(11)],
            [
                "编号00: 琉妮  西奥妮",
                "编号01: 白河愁  古兰森",
                "编号02: 夏亚  夏亚专用·扎古",
                "编号03: 葵丝  亚古特·多加",
                "编号04: 西罗克  帕拉斯",
                "编号05: 萨拉  卡扎C",
                "编号06:",
                "编号07:",
                "编号08: 罗莉莱  莱茵X1",
                "编号09:",
                "编号0A: 蕾柯亚  玛拉塞",
            ],
        )

        # Later joins live in the other two physical event banks.  The old
        # editor accumulates those $6F records but does not apply runtime leave
        # or transfer opcodes to its configuration combo.
        self.page.map_list.setCurrentRow(12)
        self.application.processEvents()
        self.assertEqual(
            self.page._player_slot_state(),
            {
                0: (4, 9),
                1: (5, 13),
                2: (6, 15),
                3: (7, 17),
                4: (8, 19),
                5: (9, 23),
                6: (18, 33),
                7: (19, 32),
                8: (20, 37),
                10: (10, 21),
            },
        )

    def test_player_slot_preview_reacts_to_join_event_edits(self) -> None:
        self.page.map_list.setCurrentRow(4)
        self.application.processEvents()
        self.assertEqual(self.page._player_slot_state()[8], (15, 29))
        self.assertNotIn(6, self.page._player_slot_state())

        instruction = next(
            item
            for item in self.project.chapter_event_instructions()
            if item.address == 0xA9BB
        )
        self.assertEqual(instruction.raw, bytes((0x6F, 0x08, 0x0F, 0x1D, 0x30)))
        self.project.set_chapter_event_instruction(
            instruction.address,
            bytes((instruction.raw_opcode, 0x06, 0x12, 0x21, 0x30)),
        )

        slots = self.page._player_slot_state()
        self.assertEqual(slots[6], (0x12, 0x21))
        self.assertNotIn(8, slots)
        self.assertEqual(
            self.page._deployment_player_slot_choice_label(6),
            "编号06: 姬娜  龙飞",
        )

    def test_all_chapters_visualize_every_resolved_player_unit(self) -> None:
        self.page.editor_tabs.setCurrentIndex(1)
        for map_id in range(self.project.scenario_count):
            self.page.map_list.setCurrentRow(map_id)
            self.application.processEvents()
            slots = self.page._player_slot_state()
            referenced_slots = {
                values[2] for values in self.page.player_table.rows()
            }
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

    def test_map_overlay_visually_follows_pointer_until_release(self) -> None:
        canvas = MapCanvas()
        canvas.set_cell_size(24)
        tile = QImage(16, 16, QImage.Format.Format_RGB32)
        tile.fill(QColor("#008000"))
        icon = QImage(16, 16, QImage.Format.Format_RGB32)
        icon.fill(QColor("#ff0000"))
        canvas.set_tile_images(tuple(tile for _ in range(16)))
        canvas.set_overlay_images({("敌", 0): icon})
        canvas.set_content(4, 3, [0] * 12, [("敌", 1, 1, "1", 0)])
        canvas.overlay_move_enabled = True
        moved = QSignalSpy(canvas.overlay_moved)
        canvas.show()
        self.application.processEvents()

        QTest.mousePress(
            canvas, Qt.MouseButton.LeftButton, pos=QPoint(30, 30)
        )
        QTest.mouseMove(canvas, QPoint(54, 42), delay=10)
        self.application.processEvents()

        self.assertEqual(canvas.dragged_overlay, ("敌", 0))
        self.assertEqual(canvas.drag_position, QPoint(54, 42))
        rendered = canvas.grab().toImage()
        self.assertGreater(rendered.pixelColor(60, 45).red(), 220)
        self.assertLess(rendered.pixelColor(30, 30).red(), 80)

        QTest.mouseRelease(
            canvas, Qt.MouseButton.LeftButton, pos=QPoint(54, 42)
        )
        self.assertEqual(moved.count(), 1)
        self.assertEqual(list(moved.at(0)), ["敌", 0, 2, 1])
        self.assertIsNone(canvas.dragged_overlay)
        self.assertIsNone(canvas.drag_position)
        canvas.close()
        canvas.deleteLater()

    def test_map_event_and_shop_use_reference_white_red_placards(self) -> None:
        canvas = MapCanvas()
        canvas.set_cell_size(24)
        tile = QImage(16, 16, QImage.Format.Format_RGB32)
        tile.fill(QColor("#008000"))
        canvas.set_tile_images(tuple(tile for _ in range(16)))
        for side in ("事", "店"):
            canvas.set_content(1, 1, [0], [(side, 0, 0, side, 0)])
            canvas.show()
            self.application.processEvents()
            image = canvas.grab().toImage()
            colors = [
                image.pixelColor(x, y)
                for y in range(image.height())
                for x in range(image.width())
            ]
            self.assertGreater(sum(c.red() > 180 and c.green() < 90 for c in colors), 8)
            self.assertGreater(sum(c.red() > 240 and c.green() > 240 for c in colors), 40)
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
        self.application.processEvents()
        table.set_rows([(1, 2, 4), (5, 6, 8), (7, 8, 9)])
        self.assertEqual(spy.count(), 3)
        self.assertEqual(table.rows(), [(1, 2, 4), (5, 6, 8), (7, 8, 9)])
        self.assertTrue(all(
            table.cellWidget(row, column) is not None
            for row in range(table.rowCount())
            for column in range(table.columnCount())
        ))
        self.assertIs(table.cellWidget(0, 2).model(), table.cellWidget(2, 2).model())
        table.set_row_coordinates(0, 8, 9)
        self.assertEqual(spy.count(), 4)
        table.deleteLater()

    def test_backstage_reveal_can_switch_to_other_chapters_and_back(self) -> None:
        backstage_row = next(
            row
            for row in range(self.page.map_list.count())
            if "幕后浮现" in self.page.map_list.item(row).text()
        )
        route = (backstage_row, 0, 11, backstage_row, 4)
        for row in route:
            self.page.map_list.setCurrentRow(row)
            self.application.processEvents()
            self.assertEqual(self.page.map_list.currentRow(), row)
            self.assertEqual(self.page.current_map_id, row)
            for table in (
                self.page.enemy_table,
                self.page.guest_table,
                self.page.player_table,
            ):
                self.assertTrue(all(
                    table.cellWidget(table_row, column) is not None
                    for table_row in range(table.rowCount())
                    for column in range(table.columnCount())
                ))
                table.rows()

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
        self.assertFalse(self.page.deployment_objects.isVisible())
        self.assertFalse(self.page.canvas.paint_enabled)
        side, x, y, _label, row = self.page.canvas.overlays[0]
        position = QPoint(x * self.page.canvas.cell_size + 3, y * self.page.canvas.cell_size + 3)
        QTest.mouseClick(self.page.canvas, Qt.MouseButton.LeftButton, pos=position)
        self.assertEqual(self.page.canvas.selected_overlay, (side, row))
        self.assertEqual(tuple(self.page.deployment_objects.currentItem().data(Qt.ItemDataRole.UserRole)),
                         (side, row))
        self.assertTrue(self.page.deployment_selection_preview.isVisible())
        preview = self.page.deployment_selection_preview.text()
        self.assertIn("配置预览｜敌军 01｜坐标 (03,04)", preview)
        self.assertIn("等级 5", preview)
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

    def test_player_selection_preview_names_roster_slot_and_player_control(self) -> None:
        self.page.player_table.set_rows([(12, 17, 3, 0)])
        self.page.editor_tabs.setCurrentIndex(1)
        self.page._select_object("我", 0)
        preview = self.page.deployment_selection_preview.text()
        self.assertIn("配置预览｜我方出击位 01｜坐标 (12,17)", preview)
        self.assertIn("等级：队伍槽 $03", preview)
        self.assertIn("行动：玩家自控", preview)
        self.assertNotIn("行动 不动", preview)
        tooltip = self.page.deployment_selection_preview.toolTip()
        self.assertIn("武器1：", tooltip)
        self.assertIn("武器2：", tooltip)
        self.assertIn("射程", tooltip)
        self.assertIn("距离补正表", tooltip)
        self.assertIn("行动：玩家自控", tooltip)
        self.assertNotIn("行动：不动", tooltip)

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
        self.assertFalse(any("坐标" in label for label in actions))
        self.assertEqual(
            [action.text() for action in self.page._deployment_context_menu.actions()],
            [
                "添加配置",
                "更改配置",
                "更改属性",
                "击杀经验计算器",
                "加到属性计算器",
                "复制",
                "剪切",
                "粘贴",
                "删除配置",
            ],
        )
        self.assertIn("更改属性", actions)
        self.assertIn("击杀经验计算器", actions)
        self.assertIn("加到属性计算器", actions)
        self.assertFalse(actions["粘贴"].isEnabled())
        self.assertFalse(actions["添加配置"].isEnabled())
        database_requests = QSignalSpy(self.page.database_record_requested)
        actions["更改属性"].trigger()
        self.assertEqual(database_requests.count(), 1)
        self.assertEqual(list(database_requests.at(0)), ["units", 1])
        experience_requests = QSignalSpy(self.page.defeat_experience_requested)
        actions["击杀经验计算器"].trigger()
        self.assertEqual(experience_requests.count(), 1)
        self.assertEqual(list(experience_requests.at(0)), [1, 5])
        actions["更改配置"].trigger()
        self.application.processEvents()
        self.assertTrue(self.page.deployment_cell_dialog.isVisible())
        self.assertFalse(self.page.deployment_x_editor.isVisible())
        self.assertFalse(self.page.deployment_y_editor.isVisible())
        self.assertEqual(self.page.deployment_side_combo.currentData(), "敌")
        self.assertEqual(self.page.enemy_table.currentRow(), 0)
        self.page.deployment_cell_dialog.close()

        with patch("dc_modifier.map_page.QMenu.popup"):
            self.page._show_deployment_context_menu(8, 9, QPoint(0, 0))
        empty_actions = {
            action.text(): action
            for action in self.page._deployment_context_menu.actions()
        }
        self.assertTrue(empty_actions["添加配置"].isEnabled())
        empty_actions["添加配置"].trigger()
        self.application.processEvents()
        self.assertTrue(self.page.deployment_cell_dialog.isVisible())
        self.assertEqual(self.page.guest_table.rows(), [])
        self.assertEqual(self.page.deployment_side_combo.currentData(), "敌")
        self.page.deployment_side_combo.setCurrentIndex(
            self.page.deployment_side_combo.findData("客")
        )
        self.assertEqual(self.page.deployment_side_combo.currentData(), "客")
        self.page._save_deployment_cell_editor()
        self.assertEqual(self.page.guest_table.rows(), [(8, 9, 1, 1, 1, 0)])

    def test_compact_editor_matches_reference_two_column_flow(self) -> None:
        self.project.configure_expansion(288, 64, 112)
        self.page._open_deployment_cell_editor("敌", 3, 4)
        self.application.processEvents()
        self.assertEqual(
            self.page.deployment_cell_buttons.button(
                QDialogButtonBox.StandardButton.Save
            ).text(),
            "确定",
        )
        self.assertTrue(self.page.deployment_details_group.isVisible())
        self.assertTrue(self.page.deployment_details_group.isEnabled())
        self.assertFalse(self.page.deployment_player_group.isEnabled())
        self.assertFalse(self.page.deployment_editor_status.isVisible())
        self.assertFalse(self.page.deployment_capacity_button.isVisible())
        self.assertTrue(
            self.page.deployment_character_combo.currentText().startswith("[01]001:")
        )
        self.assertTrue(
            self.page.deployment_unit_combo.currentText().startswith("[01]001:")
        )
        self.assertEqual(self.page.deployment_character_combo.count(), 255)
        self.assertEqual(self.page.deployment_character_combo.itemData(0), 1)
        self.assertEqual(self.page.deployment_character_combo.findData(0), -1)
        self.assertEqual(self.page.deployment_unit_combo.count(), 255)
        self.assertEqual(self.page.deployment_unit_combo.itemData(0), 1)
        self.assertEqual(self.page.deployment_unit_combo.findData(0), -1)
        self.assertEqual(self.page.deployment_level_editor.currentText(), "等级：01")
        self.assertEqual(self.page.deployment_level_editor.count(), 99)
        self.assertEqual(self.page.deployment_level_editor.itemData(98), 99)
        self.assertTrue(
            self.page.deployment_roster_combo.itemText(0).startswith("编号00:")
        )

        self.page.deployment_side_combo.setCurrentIndex(
            self.page.deployment_side_combo.findData("我")
        )
        self.assertFalse(self.page.deployment_details_group.isEnabled())
        self.assertTrue(self.page.deployment_player_group.isEnabled())
        self.page.deployment_cell_dialog.close()

    def test_invalid_zero_deployment_ids_must_be_reselected_before_save(self) -> None:
        self.page.enemy_table.blockSignals(True)
        self.page.enemy_table.set_rows([(3, 4, 0, 0, 5, 0)])
        self.page.enemy_table.blockSignals(False)
        self.page._open_deployment_cell_editor("敌", 3, 4, 0)
        self.application.processEvents()
        self.assertIsNone(self.page.deployment_character_combo.currentData())
        self.assertIsNone(self.page.deployment_unit_combo.currentData())
        self.assertTrue(self.page.deployment_editor_status.isVisible())
        self.assertIn("不是有效部署编号", self.page.deployment_editor_status.text())

        self.page._save_deployment_cell_editor()
        self.assertTrue(self.page.deployment_cell_dialog.isVisible())
        self.assertEqual(self.page.enemy_table.rows(), [(3, 4, 0, 0, 5, 0)])

        self.page.deployment_character_combo.setCurrentIndex(0)
        self.page.deployment_unit_combo.setCurrentIndex(0)
        self.page._save_deployment_cell_editor()
        self.assertEqual(self.page.enemy_table.rows(), [(3, 4, 1, 1, 5, 0)])

    def test_empty_map_cell_context_menu_enables_add_and_available_paste(self) -> None:
        self.page.enemy_table.set_rows([(3, 4, 1, 1, 5, 0)])
        self.page.guest_table.set_rows([])
        self.page.player_table.set_rows([])
        self.page.editor_tabs.setCurrentIndex(1)
        self.page._deployment_clipboard = (
            "敌",
            self.page.enemy_table.rows()[0],
        )

        with patch("dc_modifier.map_page.QMenu.popup"):
            self.page._show_deployment_context_menu(8, 9, QPoint(0, 0))
        actions = self.page._deployment_context_menu.actions()
        self.assertEqual(
            [action.text() for action in actions],
            [
                "添加配置",
                "更改配置",
                "更改属性",
                "击杀经验计算器",
                "加到属性计算器",
                "复制",
                "剪切",
                "粘贴",
                "删除配置",
            ],
        )
        enabled = {action.text() for action in actions if action.isEnabled()}
        self.assertEqual(enabled, {"添加配置", "粘贴"})

        self.page._deployment_clipboard = None
        with patch("dc_modifier.map_page.QMenu.popup"):
            self.page._show_deployment_context_menu(8, 9, QPoint(0, 0))
        enabled_without_clipboard = {
            action.text()
            for action in self.page._deployment_context_menu.actions()
            if action.isEnabled()
        }
        self.assertEqual(enabled_without_clipboard, {"添加配置"})

        self.page._deployment_clipboard = (
            "敌",
            self.page.enemy_table.rows()[0],
        )
        with patch("dc_modifier.map_page.QMenu.popup"):
            self.page._show_deployment_context_menu(3, 4, QPoint(0, 0))
        selected_actions = {
            action.text(): action
            for action in self.page._deployment_context_menu.actions()
        }
        self.assertFalse(selected_actions["添加配置"].isEnabled())
        self.assertFalse(selected_actions["粘贴"].isEnabled())
        self.assertTrue(
            all(
                action.isEnabled()
                for label, action in selected_actions.items()
                if label not in {"添加配置", "粘贴"}
            )
        )

    def test_deployment_editor_rejects_cross_side_coordinate_overlap(self) -> None:
        self.page.enemy_table.set_rows([(3, 4, 1, 1, 5, 0)])
        self.page.guest_table.set_rows([])
        self.page.player_table.set_rows([])

        self.page._open_deployment_cell_editor("客", 3, 4)
        self.page._save_deployment_cell_editor()

        self.assertEqual(self.page.guest_table.rows(), [])
        self.assertTrue(self.page.deployment_cell_dialog.isVisible())
        self.assertTrue(self.page.deployment_editor_status.isVisible())
        self.assertIn("(03,04)", self.page.deployment_editor_status.text())
        self.assertIn("敌军配置 01", self.page.deployment_editor_status.text())
        self.assertIn("不能放置多个配置", self.page.deployment_editor_status.text())
        self.page.deployment_cell_dialog.close()

    def test_deployment_paste_and_drag_reject_occupied_coordinate(self) -> None:
        enemy = (3, 4, 1, 1, 5, 0)
        guest = (8, 9, 2, 2, 6, 1)
        self.page.enemy_table.set_rows([enemy])
        self.page.guest_table.set_rows([guest])
        self.page.player_table.set_rows([])
        errors = []
        self.page.show_error = lambda error: errors.append(str(error))

        self.page._deployment_clipboard = ("客", guest)
        self.page._paste_deployment_at(3, 4)
        self.assertEqual(self.page.guest_table.rows(), [guest])

        self.page._overlay_moved("客", 0, 3, 4)
        self.assertEqual(self.page.guest_table.rows(), [guest])
        self.assertEqual(len(errors), 2)
        self.assertTrue(all("敌军配置 01" in message for message in errors))

    def test_trigger_move_to_map_cursor_remains_independent_of_deployment_occupancy(self) -> None:
        self.page.enemy_table.set_rows([(3, 4, 1, 1, 5, 0)])
        self.page.trigger_table.set_rows([(8, 9, 0xFF, 7)])
        self.page.trigger_table.setCurrentCell(0, 0)
        self.page.hovered_cell = (3, 4)

        self.page._move_selected_to_hover(self.page.trigger_table)

        self.assertEqual(self.page.trigger_table.rows(), [(3, 4, 0xFF, 7)])

    def test_duplicate_uses_nearest_free_cell_and_final_validation_blocks_overlap(self) -> None:
        original = (3, 4, 1, 1, 5, 0)
        self.page.enemy_table.set_rows([original])
        self.page.guest_table.set_rows([])
        self.page.player_table.set_rows([])
        self.page.enemy_table.setCurrentCell(0, 0)

        self.page._duplicate_deployment(self.page.enemy_table)
        duplicated = self.page.enemy_table.rows()[1]
        self.assertEqual(duplicated[2:], original[2:])
        self.assertNotEqual(duplicated[:2], original[:2])
        self.assertEqual(len({row[:2] for row in self.page.enemy_table.rows()}), 2)

        self.page.guest_table.set_rows([(3, 4, 2, 2, 6, 1)])
        with self.assertRaisesRegex(ValueError, "同一格不能放置多个配置"):
            self.page._validate_deployment_coordinate_uniqueness()
        self.assertIn("同一格不能放置多个配置", self.page.pending_draft_error)

    def test_deployment_level_choices_follow_verified_rom_level_cap(self) -> None:
        with patch.object(self.project, "get_verified_level_cap", return_value=60):
            self.page._refresh_deployment_editor_choices()
        self.assertEqual(self.page._deployment_level_cap, 60)
        self.assertEqual(self.page.deployment_level_editor.count(), 60)
        self.assertEqual(self.page.deployment_level_editor.itemData(59), 60)

        self.page._refresh_deployment_editor_choices()
        self.assertEqual(self.page._deployment_level_cap, 99)
        self.assertEqual(self.page.deployment_level_editor.count(), 99)
        self.assertEqual(self.page.deployment_level_editor.itemData(98), 99)

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
        self.assertIn("距离补正表", tooltip)
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
        empty_weapons = self.page._deployment_description(
            "敌", (3, 4, 1, 1, 5, 0)
        )
        self.assertIn("武器1：无", empty_weapons)
        self.assertIn("武器2：无", empty_weapons)

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

    def test_deployment_growth_uses_the_32_chapter_shared_pool(self) -> None:
        self.page.map_list.setCurrentRow(4)
        self.page.editor_tabs.setCurrentIndex(1)
        errors = []
        self.page.show_error = lambda error: errors.append(str(error))
        before = self.page.enemy_table.rows()
        self.page._open_deployment_cell_editor("敌", 0, 0)
        self.page._save_deployment_cell_editor()
        self.assertEqual(len(self.page.enemy_table.rows()), len(before) + 1)
        self.assertEqual(errors, [])
        self.assertIn("部署正文", self.page.size_label.text())
        self.assertIn("Bank$24八资源共享余量", self.page.size_label.text())

    def test_capacity_status_follows_map_initial_and_shop_event_tabs(self) -> None:
        self.page.map_list.setCurrentRow(0)
        self.page.editor_tabs.setCurrentIndex(0)
        self.assertIn("三Bank", self.page.size_label.text())

        self.page.editor_tabs.setCurrentIndex(1)
        self.assertIn("本关4 B", self.page.size_label.text())
        self.assertIn("部署正文1236 B", self.page.size_label.text())
        self.assertIn("Bank$24八资源共享余量5655 B", self.page.size_label.text())
        self.assertIn("初始配置本关 4 B", self.page.size_label.toolTip())
        self.assertIn("32关部署正文 1236 B", self.page.size_label.toolTip())
        self.assertIn("Bank $24 八资源共享剩余 5655 B", self.page.size_label.toolTip())
        self.assertIn("人物属性、机体属性、武器属性", self.page.size_label.toolTip())
        self.assertIn("当前部署上限 6891 B（其他七项不变时）", self.page.size_label.toolTip())
        self.assertNotIn("事件/商店本关", self.page.size_label.toolTip())

        self.page.editor_tabs.setCurrentIndex(2)
        self.assertIn("本关0条/1 B", self.page.size_label.text())
        self.assertIn("32关事件/商店共享10/310 B", self.page.size_label.text())
        self.assertIn("事件/商店本关 0 条/1 B", self.page.size_label.toolTip())
        self.assertIn("独立于地图RLE和初始配置", self.page.size_label.toolTip())

    def test_user_scenario_1258_to_1264_commits_without_capacity_error(self) -> None:
        self.page.map_list.setCurrentRow(0)
        self.page.editor_tabs.setCurrentIndex(1)
        staged = [(index, 0, index + 1, index + 1, 1, 0) for index in range(3)]
        self.page.enemy_table.set_rows(staged)
        self.assertTrue(self.page.commit_pending_changes())
        self.assertIn("部署正文1258 B", self.page.size_label.text())
        self.assertIn("Bank$24八资源共享余量5633 B", self.page.size_label.text())

        self.page.enemy_table.set_rows(staged + [(4, 0, 4, 4, 1, 0)])
        self.assertIsNone(self.page.pending_draft_error)
        self.assertTrue(self.page.commit_pending_changes())
        self.assertIn("部署正文1264 B", self.page.size_label.text())
        self.assertIn("Bank$24八资源共享余量5627 B", self.page.size_label.text())

    def test_expanded_capacity_status_names_the_unified_map_pool(self) -> None:
        self.project.configure_expansion(288, 64, 112)
        self.page.refresh()
        self.page.map_list.setCurrentRow(0)

        self.page.editor_tabs.setCurrentIndex(1)
        self.assertIn("部署共", self.page.size_label.text())
        self.assertIn("共享池", self.page.size_label.text())
        self.assertNotIn("/6891 B", self.page.size_label.text())

        self.page.editor_tabs.setCurrentIndex(2)
        self.assertIn("触发共", self.page.size_label.text())
        self.assertIn("地图共享池", self.page.size_label.toolTip())
        self.assertNotIn("/310 B", self.page.size_label.text())

    def test_shared_pool_add_then_delete_restores_pointer_table_and_pool(self) -> None:
        self.page.map_list.setCurrentRow(12)
        codec = self.project.scenario_layout_codec
        pointer_start = codec.pointer_table_offset
        pointer_end = pointer_start + self.project.scenario_count * 2
        pool_start = codec.pool_offset
        pool_end = pool_start + codec.pool_capacity
        before = (
            bytes(self.project.working[pointer_start:pointer_end]),
            bytes(self.project.working[pool_start:pool_end]),
        )
        self.assertEqual(self.page.enemy_table.rowCount(), 0)
        self.page._open_deployment_cell_editor("敌", 0, 0)
        self.page._save_deployment_cell_editor()
        self.assertTrue(self.page.commit_pending_changes())
        self.assertNotEqual(
            (
                bytes(self.project.working[pointer_start:pointer_end]),
                bytes(self.project.working[pool_start:pool_end]),
            ),
            before,
        )

        self.page._remove_deployment_row("敌", 0)
        self.assertTrue(self.page.commit_pending_changes())
        self.assertEqual(
            (
                bytes(self.project.working[pointer_start:pointer_end]),
                bytes(self.project.working[pool_start:pool_end]),
            ),
            before,
        )

    def test_shop_list_add_drag_commit_and_undo_preserve_record_semantics(self) -> None:
        self.page.editor_tabs.setCurrentIndex(2)
        self.assertIn("没有", self.page.trigger_summary.text())
        self.assertEqual(self.page.trigger_character_combo.itemData(0), 0xFF)
        self.assertIn("任意我方人物", self.page.trigger_character_combo.itemText(0))
        self.page.trigger_table.set_rows([(3, 4, 0xFF, 0xF2)])
        self.assertEqual(self.page.trigger_objects.count(), 1)
        trigger_item = self.page.trigger_objects.item(0)
        self.assertIn("商店 3", trigger_item.text())
        self.assertIn("任意我方人物", trigger_item.text())
        self.assertEqual(trigger_item.background().style(), Qt.BrushStyle.NoBrush)
        self.page._overlay_moved("店", 0, 4, 5)
        self.assertEqual(self.page.trigger_table.rows()[0], (4, 5, 0xFF, 0xF2))
        self.assertTrue(self.page.commit_pending_changes())
        self.assertEqual(tuple(self.project.get_map_triggers(0)[0].to_bytes()), (4, 5, 0xFF, 0xF2))
        self.project.undo()
        self.assertEqual(self.project.get_map_triggers(0), ())

    def test_trigger_draft_capacity_and_coordinate_errors_preserve_draft(self) -> None:
        self.page.editor_tabs.setCurrentIndex(2)
        width = self.page.staged_width
        accepted = [
            (index % width, index // width, 0xFF, 0xF2)
            for index in range(74)
        ]
        self.page.trigger_table.set_rows(accepted)
        self.assertTrue(self.page.commit_pending_changes())
        self.assertIn("307 / 310 B", self.page.size_label.toolTip())
        self.assertNotIn("全局池", self.page.size_label.text())
        before_overflow = bytes(self.project.working)

        overflow = accepted + [(74 % width, 74 // width, 0xFF, 0xF2)]
        self.page.trigger_table.set_rows(overflow)
        self.assertIn("分段共享池只有 310 字节", self.page.pending_draft_error or "")
        self.assertFalse(self.page.commit_pending_changes())
        self.assertEqual(bytes(self.project.working), before_overflow)
        self.assertEqual(self.page.trigger_table.rows(), overflow)

        out_of_bounds = accepted + [(width, 0, 0xFF, 0xF2)]
        self.page.trigger_table.set_rows(out_of_bounds)
        self.assertIn("超出", self.page.pending_draft_error or "")
        self.assertFalse(self.page.commit_pending_changes())
        self.assertEqual(bytes(self.project.working), before_overflow)
        self.assertEqual(self.page.trigger_table.rows(), out_of_bounds)

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
        self.assertFalse(any("坐标" in label for label in actions))
        self.assertIn("添加地图事件", actions)
        self.assertIn("添加商店入口", actions)
        self.assertIn("删除地图事件", actions)
        self.assertFalse(actions["删除地图事件"].isEnabled())
        actions["添加地图事件"].trigger()
        self.application.processEvents()
        self.assertTrue(self.page.trigger_cell_dialog.isVisible())
        self.assertFalse(self.page.trigger_x_editor.isVisible())
        self.assertFalse(self.page.trigger_y_editor.isVisible())
        self.assertEqual(self.page.trigger_x_editor.value(), 3)
        self.assertEqual(self.page.trigger_y_editor.value(), 4)
        self.assertTrue(self.page.trigger_character_combo.isEnabled())
        self.assertIn("地图事件同样可以限定人物", self.page.trigger_character_combo.toolTip())
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
        self.assertIn("编辑商店入口", actions)
        self.assertIn("删除商店入口", actions)
        actions["删除商店入口"].trigger()
        self.assertEqual(self.page.trigger_table.rows(), [])

    def test_trigger_list_right_click_selects_edits_and_deletes_record(self) -> None:
        self.page.editor_tabs.setCurrentIndex(2)
        self.page.trigger_table.set_rows(
            [(3, 4, 0xFF, 7), (5, 6, 0xFF, 0xF2)]
        )
        self.application.processEvents()

        shop_item = self.page.trigger_objects.item(1)
        position = self.page.trigger_objects.visualItemRect(shop_item).center()
        with patch("dc_modifier.map_page.QMenu.popup") as show_menu:
            self.page.trigger_objects.customContextMenuRequested.emit(position)
        show_menu.assert_called_once()
        self.assertIs(self.page.trigger_objects.currentItem(), shop_item)
        self.assertEqual(self.page.canvas.selected_overlay, ("店", 1))
        actions = {
            action.text(): action
            for action in self.page._trigger_list_context_menu.actions()
        }
        self.assertEqual(set(actions), {"编辑商店入口", "删除商店入口"})

        actions["编辑商店入口"].trigger()
        self.application.processEvents()
        self.assertTrue(self.page.trigger_cell_dialog.isVisible())
        self.assertEqual(self.page._trigger_edit_row, 1)
        self.assertTrue(self.page.trigger_shop_radio.isChecked())
        self.assertEqual(self.page.trigger_shop_combo.currentData(), 0xF2)
        self.page.trigger_cell_dialog.reject()

        event_item = self.page.trigger_objects.item(0)
        position = self.page.trigger_objects.visualItemRect(event_item).center()
        with patch("dc_modifier.map_page.QMenu.popup"):
            self.page.trigger_objects.customContextMenuRequested.emit(position)
        actions = {
            action.text(): action
            for action in self.page._trigger_list_context_menu.actions()
        }
        self.assertEqual(set(actions), {"编辑地图事件", "删除地图事件"})
        actions["删除地图事件"].trigger()
        self.assertEqual(self.page.trigger_table.rows(), [(5, 6, 0xFF, 0xF2)])

    def test_trigger_choices_hide_invalid_shops_and_event_popup_starts_at_one(self) -> None:
        self.assertEqual(self.page.trigger_shop_combo.count(), 5)
        self.assertEqual(
            [self.page.trigger_shop_combo.itemData(index) for index in range(5)],
            list(range(0xF0, 0xF5)),
        )
        for shop_id in range(0xF5, 0x100):
            self.assertEqual(self.page.trigger_shop_combo.findData(shop_id), -1)

        combo = self.page.trigger_event_combo
        self.assertEqual(combo.maxVisibleItems(), 10)
        combo.setCurrentIndex(combo.findData(13))
        combo.showPopup()
        self.application.processEvents()
        self.assertEqual(combo.view().verticalScrollBar().value(), 0)
        self.assertFalse(combo.view().visualRect(combo.model().index(0, 0)).isEmpty())
        row_height = combo.view().sizeHintForRow(0)
        self.assertLessEqual(combo.view().height(), row_height * 10 + 8)
        combo.hidePopup()

        character_combo = self.page.trigger_character_combo
        unknown_index = character_combo.findData(0x1D)
        self.assertEqual(character_combo.itemText(unknown_index), "仅限 ？？？")
        character_combo.setCurrentIndex(unknown_index)
        character_combo.showPopup()
        self.application.processEvents()
        self.assertEqual(character_combo.view().verticalScrollBar().value(), 0)
        character_row_height = character_combo.view().sizeHintForRow(0)
        self.assertLessEqual(
            character_combo.view().height(), character_row_height * 10 + 8
        )
        character_combo.hidePopup()

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
        self.assertIn("Bank共享6709/6722", self.page.size_label.text())
        self.assertIn("三Bank独立14474/17730", self.page.size_label.text())
        self.assertIn("可迁移", self.page.size_label.text())
        self.assertIn("所在Bank 6709 / 6722 B", self.page.size_label.toolTip())
        self.assertIn("三Bank合计 14474 / 17730 B", self.page.size_label.toolTip())
        self.assertIn("共用对象：同一Bank内的地图RLE记录", self.page.size_label.toolTip())
        self.assertIn("三个Bank彼此独立", self.page.size_label.toolTip())
        self.assertIn("可保存（必要时整图迁移）", self.page.size_label.toolTip())
        self.assertGreaterEqual(self.page.size_label.toolTip().count("\n"), 4)
        self.assertLessEqual(
            max(len(line) for line in self.page.size_label.toolTip().splitlines()),
            36,
        )
        self.page.resize(850, 640)
        self.application.processEvents()
        self.assertLessEqual(
            QFontMetrics(self.page.size_label.font()).horizontalAdvance(
                self.page.size_label.text()
            ),
            self.page.size_label.width(),
        )
        _used, total = self.project.map_resource_replacement_usage(
            self.page.current_map_id,
            self.page.staged_width,
            self.page.staged_height,
            tuple(self.page.staged_tiles),
        )
        self.assertIn(f"/{total}", self.page.size_label.text())
        total_used, total_capacity = self.project.legacy_map_terrain_total_usage(
            self.page.current_map_id,
            self.page.staged_width,
            self.page.staged_height,
            tuple(self.page.staged_tiles),
        )
        self.assertEqual((total_used, total_capacity), (14474, 17730))
        self.assertIn("三Bank独立14474/17730", self.page.size_label.text())
        self.page.height_editor.setValue(32)
        self.page.width_editor.setValue(32)
        self.page._resize_map()
        self.page.staged_tiles = [
            index % 2
            for index in range(self.page.staged_width * self.page.staged_height)
        ]
        original_usage = self.project.map_resource_replacement_usage
        self.project.map_resource_replacement_usage = lambda *_args, **_kwargs: (
            (_ for _ in ()).throw(ValueError("测试用旧分区容量不足"))
        )
        self.page._update_size_label()
        draft = self.page._draft_signature()
        self.assertIsNotNone(self.page.pending_draft_error)
        requested = []
        def plan(key):
            requested.append(key)
            self.project.map_resource_replacement_usage = original_usage
            self.project.configure_expansion(304, 48, 112)
        self.page.navigation_requested.connect(plan)
        self.page._open_capacity_planner()
        self.assertEqual(requested, ["resources"])
        self.assertEqual(self.page._draft_signature(), draft)
        self.assertIsNone(self.page.pending_draft_error)
        self.assertIn("共享池重排", self.page.size_label.text())
        self.assertIn("地图共享池", self.page.size_label.toolTip())
        self.assertTrue(self.page.commit_pending_changes())
        self.assertEqual(
            (self.project.get_map(0).width, self.project.get_map(0).height),
            (32, 32),
        )

    def test_two_byte_map_growth_uses_legacy_bank_tail_and_commits(self) -> None:
        record = self.project.get_map(0)
        self.assertEqual((record.tiles[3], len(record.raw)), (5, 324))
        self.page.staged_tiles[3] = 0
        self.page._update_size_label()

        self.assertIsNone(self.page.pending_draft_error)
        self.assertIn("Bank共享6711/6722", self.page.size_label.text())
        self.assertIn("三Bank独立14476/17730", self.page.size_label.text())
        self.assertTrue(self.page.commit_pending_changes())
        self.assertEqual(self.project.get_map(0).tiles[3], 0)

    def test_added_column_cascades_legacy_bank_boundaries_and_commits(self) -> None:
        self.page.width_display.setValue(28)
        self.application.processEvents()

        self.assertIsNone(self.page.pending_draft_error)
        self.assertIn("Bank共享6453/6722", self.page.size_label.text())
        self.assertIn("三Bank独立14520/17730", self.page.size_label.text())
        self.assertIn("可迁移", self.page.size_label.text())
        self.assertTrue(self.page.commit_pending_changes())
        self.assertEqual(
            (self.project.get_map(0).width, self.project.get_map(0).height),
            (28, 26),
        )
        self.assertEqual(
            (self.project.working[0x5BA3], self.project.working[0x5BB7]),
            (0x21, 0x29),
        )


if __name__ == "__main__":
    unittest.main(verbosity=2)
