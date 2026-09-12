from __future__ import annotations

import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QRect
from PySide6.QtGui import QAction, QImage, QPainter
from PySide6.QtWidgets import (
    QApplication,
    QDialog,
    QFileDialog,
    QLabel,
    QPushButton,
    QStyle,
    QStyleOptionSpinBox,
    QToolBar,
)

import dc_modifier.workspace as workspace_module
from dc_modifier.app import (
    LEGACY_ROM, LEGACY_WINDOW_TITLE, LauncherWindow, MainWindow,
    VisibleArrowStyle,
)
from dc_modifier.event_page import EventPage
from dc_modifier.legacy_windows import DatabaseDialog, ScenarioDialog
from dc_modifier.map_page import MapPage
from dc_modifier.persuasion_page import PersuasionPage
from dc_modifier.pages import (
    CharacterPage,
    ChangesPage,
    MusicPage,
    ResourcePage,
    UnitPage,
    WeaponPage,
    parse_id_expression,
)
from dc_modifier.story_page import StoryPage
from dc_modifier.unit_import_page import UnitImportPage
from fc_editor.codecs.chapter_event import ACTION_LABELS
from fc_editor.text_table import TextTable
from fc_rom_editor_core import RomProject


from tests.qt_test_case import QtTestCase


class DesktopEditorSmokeTests(QtTestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.application = QApplication.instance() or QApplication([])

    def setUp(self) -> None:
        self.window = MainWindow(open_default=True)
        self.assertIsNotNone(self.window.project)

    def test_numeric_spin_style_draws_large_visible_up_and_down_arrows(self) -> None:
        style = VisibleArrowStyle("Fusion")
        option = QStyleOptionSpinBox()
        option.rect = QRect(0, 0, 100, 36)
        option.state = QStyle.StateFlag.State_Enabled
        up = style.subControlRect(
            QStyle.ComplexControl.CC_SpinBox, option,
            QStyle.SubControl.SC_SpinBoxUp,
        )
        down = style.subControlRect(
            QStyle.ComplexControl.CC_SpinBox, option,
            QStyle.SubControl.SC_SpinBoxDown,
        )
        self.assertGreaterEqual(up.width(), 16)
        self.assertEqual(up.width(), down.width())
        self.assertLess(up.center().y(), down.center().y())

        image = QImage(24, 18, QImage.Format.Format_RGB32)
        image.fill(0xFFFFFFFF)
        painter = QPainter(image)
        option.rect = image.rect()
        style.drawPrimitive(
            QStyle.PrimitiveElement.PE_IndicatorSpinUp, option, painter
        )
        painter.end()
        self.assertTrue(any(
            image.pixelColor(x, y).lightness() < 100
            for y in range(image.height()) for x in range(image.width())
        ))

    def tearDown(self) -> None:
        if self.window.project is not None:
            # Tests intentionally exercise uncommitted (including invalid) map
            # drafts. Discard the page-local draft before closing so the
            # unsaved-changes confirmation cannot make an offscreen run hang.
            self.window.map_page.refresh()
            self.window._saved_snapshot = bytes(self.window.project.working)
        self.window.close()

    def test_default_exports_use_output_directory(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            with patch.object(workspace_module, "ROOT", root):
                destination = workspace_module.default_export_path("sample.dcmod")
                self.assertEqual(
                    destination,
                    root / "output" / "exports" / "sample.dcmod",
                )
                self.assertTrue(destination.parent.is_dir())
                for blocked in (
                    root / "references",
                    root / "references" / "blocked.dcmod",
                    root / "output" / ".." / "references" / "blocked.ips",
                ):
                    with self.assertRaisesRegex(ValueError, "只读参考目录"):
                        workspace_module.writable_output_path(blocked)
                allowed = workspace_module.writable_output_path(
                    root / "references-copy" / "allowed.dcmod"
                )
                self.assertEqual(allowed, root / "references-copy" / "allowed.dcmod")

    def _stage_capacity_safe_tile_draft(
        self,
        page: MapPage,
        map_id: int = 0,
    ) -> tuple[object, int, int]:
        """Stage one real tile change without exceeding the record's RLE capacity."""

        assert self.window.project is not None
        if page.current_map_id != map_id:
            page.map_list.setCurrentRow(map_id)
            self.application.processEvents()
        record = self.window.project.get_map(map_id)
        candidate_tiles = list(record.tiles)
        changed_index = None
        for index in range(1, len(candidate_tiles)):
            if candidate_tiles[index] == candidate_tiles[index - 1]:
                continue
            previous = candidate_tiles[index]
            candidate_tiles[index] = candidate_tiles[index - 1]
            encoded = self.window.project.map_codec.encode(
                record.width,
                record.height,
                tuple(candidate_tiles),
            )
            if len(encoded) <= record.capacity:
                changed_index = index
                break
            candidate_tiles[index] = previous
        self.assertIsNotNone(changed_index)
        assert changed_index is not None
        page.staged_tiles[:] = candidate_tiles
        page.canvas.tiles = page.staged_tiles
        page._update_size_label()
        self.assertTrue(page.has_pending_draft)
        self.assertIsNone(page.pending_draft_error)
        return record, changed_index, candidate_tiles[changed_index]

    def test_empty_shell_and_legacy_data_shortcuts(self) -> None:
        empty = MainWindow(open_default=False)
        try:
            self.assertIsNone(empty.project)
            self.assertIs(empty.workspace.currentWidget(), empty.blank_page)
            self.assertEqual(empty.windowTitle(), LEGACY_WINDOW_TITLE)
            self.assertEqual(
                [action.text() for action in empty.menuBar().actions() if action.isVisible()],
                ["文件(&F)", "帮助(&H)"],
            )
            file_menu = empty.menuBar().actions()[0].menu()
            assert file_menu is not None
            file_actions = [
                action for action in file_menu.actions() if not action.isSeparator()
            ]
            self.assertEqual(
                [action.text() for action in file_actions],
                ["打开(&O)…", "保存(&S)", "退出(&X)"],
            )
            self.assertEqual(
                [action.shortcut().toString() for action in file_actions],
                ["Ctrl+O", "Ctrl+S", "Ctrl+X"],
            )
            self.assertTrue(empty.open_rom_action.isEnabled())
            self.assertFalse(empty.save_rom_action.isEnabled())
            self.assertTrue(empty.exit_action.isEnabled())
            self.assertFalse(empty.data_menu.menuAction().isVisible())
            self.assertFalse(empty.extension_menu.menuAction().isVisible())
            self.assertFalse(empty.project_menu.menuAction().isVisible())
        finally:
            empty.close()

    def test_launcher_only_shows_author_and_enter_button(self) -> None:
        launcher = LauncherWindow()
        try:
            author = launcher.findChild(QLabel, "launcherAuthor")
            enter = launcher.findChild(QPushButton, "launcherEnterButton")
            self.assertIsNotNone(author)
            self.assertIsNotNone(enter)
            assert author is not None
            self.assertEqual(author.text(), "作者 断月残心")
            self.assertIn("#ef4e4e", author.styleSheet())
            self.assertEqual(
                [button.text() for button in launcher.findChildren(QPushButton)],
                ["进入修改器"],
            )
        finally:
            launcher.close()

    def test_closing_main_window_closes_hidden_launcher_session(self) -> None:
        class TrackingLauncher(LauncherWindow):
            def __init__(self) -> None:
                self.close_event_count = 0
                super().__init__()

            def closeEvent(self, event) -> None:
                self.close_event_count += 1
                super().closeEvent(event)

        launcher = TrackingLauncher()
        launcher.show()
        try:
            launcher.enter_editor()
            self.application.processEvents()
            self.assertIsNotNone(launcher.main_window)
            assert launcher.main_window is not None
            closed_events: list[bool] = []
            launcher.main_window.closed.connect(lambda: closed_events.append(True))

            with patch.object(launcher.main_window, "_confirm_discard", return_value=False):
                self.assertFalse(launcher.main_window.close())
            self.application.processEvents()
            self.assertEqual(closed_events, [])
            self.assertEqual(launcher.close_event_count, 0)
            self.assertTrue(launcher.main_window.isVisible())

            launcher.main_window.close()
            self.application.processEvents()
            self.assertEqual(closed_events, [True])
            self.assertEqual(launcher.close_event_count, 1)
            self.assertFalse(launcher.isVisible())
        finally:
            if launcher.main_window is not None and launcher.main_window.isVisible():
                launcher.main_window._saved_snapshot = None
                launcher.main_window.close()
            launcher.close()

        self.assertEqual(
            [action.text() for action in self.window.menuBar().actions() if action.isVisible()],
            ["文件(&F)", "数据(&A)", "扩展功能", "工程", "帮助(&H)"],
        )

        data_actions = [
            action for action in self.window.data_menu.actions() if not action.isSeparator()
        ]
        self.assertEqual(
            [action.text() for action in data_actions],
            [
                "数据库(&D)",
                "完整ROM数据读取",
                "文字库(&W)",
                "地图动画(&M)",
                "文字转换(&Z)",
                "剧情事件(&J)",
                "导出机体(&P)",
                "导出头像(&L)",
                "属性计算器",
                "存档修改器",
                "其他(&T)",
            ],
        )
        self.assertEqual(
            [action.shortcut().toString() for action in data_actions],
            ["Ctrl+D", "", "Ctrl+W", "Ctrl+M", "Ctrl+Z", "Ctrl+J", "Ctrl+F", "Ctrl+L", "", "", "Ctrl+T"],
        )
        project_actions = [
            action for action in self.window.project_menu.actions() if not action.isSeparator()
        ]
        self.assertEqual(
            [action.text() for action in project_actions],
            [
                "打开工程…",
                "保存工程",
                "工程另存为…",
                "ROM另存为…",
                "导出IPS…",
                "一键构建…",
                "撤销",
                "重做",
                "完整检查",
            ],
        )
        self.assertEqual(
            [action.shortcut().toString() for action in project_actions],
            [
                "Ctrl+Shift+O",
                "Ctrl+Shift+S",
                "",
                "Ctrl+Alt+S",
                "",
                "Ctrl+B",
                "Ctrl+Alt+Z",
                "Ctrl+Alt+Y",
                "F7",
            ],
        )
        shortcuts = [
            action.shortcut().toString()
            for action in self.window.findChildren(QAction)
            if action.isEnabled() and action.shortcut().toString()
        ]
        self.assertEqual(len(shortcuts), len(set(shortcuts)))

    def test_legacy_tool_menu_entries_construct_without_runtime_error(self) -> None:
        with patch.object(QDialog, "exec", return_value=QDialog.DialogCode.Rejected):
            self.window.open_font_library()
            self.window.open_map_animation()
            self.window.open_text_converter()
            self.window.open_attribute_calculator()
            self.window.open_save_editor()
            self.window.open_other_settings()

    def test_overview_routes_resolve_to_legacy_or_extension_windows(self) -> None:
        with patch.object(QDialog, "exec", return_value=QDialog.DialogCode.Rejected):
            for key in (
                "maps",
                "units",
                "characters",
                "weapons",
                "story",
                "events",
                "persuasion",
                "music",
                "resources",
                "changes",
            ):
                with self.subTest(key=key):
                    self.window._open_extension_page(key)
        self.application.processEvents()

    def test_navigation_and_default_project(self) -> None:
        assert self.window.project is not None
        self.assertEqual(self.window.navigation.count(), 12)
        self.assertEqual(self.window.workspace.count(), 13)
        self.assertEqual(self.window.project.profile.key, "dc-kuorong-mmc3-v2")
        self.assertEqual(self.window.project.expansion_capacity, 464 * 1024)
        self.assertIs(self.window.workspace.currentWidget(), self.window.map_page)

        database = DatabaseDialog(self.window.project, self.window)
        self.assertEqual(
            [database.tabs.tabText(index) for index in range(database.tabs.count())],
            ["机体修改", "人物修改", "武器修改", "战斗对话", "其他修改1", "其他修改2"],
        )
        scenario = ScenarioDialog(self.window.project, self.window)
        self.assertEqual(
            [scenario.tabs.tabText(index) for index in range(scenario.tabs.count())],
            ["关卡设置", "行动事件", "劝降事件", "地图事件", "剧情对话", "胜利文字"],
        )
        self.assertEqual(
            [
                scenario.setup_event_tabs.tabText(index)
                for index in range(scenario.setup_event_tabs.count())
            ],
            ["界面事件", "回合事件", "即时事件"],
        )

    def test_all_pages_use_the_legacy_editor_shell(self) -> None:
        self.window.show()
        self.application.processEvents()
        self.assertEqual(
            [action.text() for action in self.window.menuBar().actions() if action.isVisible()],
            ["文件(&F)", "数据(&A)", "扩展功能", "工程", "帮助(&H)"],
        )
        self.assertEqual(self.window.findChildren(QToolBar), [])
        for page in self.window.pages:
            page_titles = [
                label
                for label in page.findChildren(QLabel)
                if label.objectName() in ("pageTitle", "pageSubtitle")
            ]
            self.assertTrue(all(label.isHidden() for label in page_titles))
        for page_key, page_type in (
            ("units", UnitPage),
            ("characters", CharacterPage),
            ("weapons", WeaponPage),
            ("music", MusicPage),
        ):
            self.window.show_page(page_key)
            self.application.processEvents()
            record_page = self.window.pages[self.window.page_index[page_key]]
            self.assertIsInstance(record_page, page_type)
            self.assertLess(
                record_page.records.geometry().bottom(),
                record_page.search_panel.geometry().top(),
            )

        self.window.show_page("story")
        self.application.processEvents()
        story_page = self.window.pages[self.window.page_index["story"]]
        assert isinstance(story_page, StoryPage)
        self.assertLess(
            story_page.indices.geometry().bottom(), story_page.search.geometry().top()
        )

        self.window.show_page("maps")
        map_page = self.window.pages[self.window.page_index["maps"]]
        assert isinstance(map_page, MapPage)
        self.assertEqual(
            [
                map_page.editor_tabs.tabText(index)
                for index in range(map_page.editor_tabs.count())
            ],
            ["战场地图", "初始配置", "商店事件"],
        )

    def test_resource_page_tracks_managed_import_and_undo(self) -> None:
        assert self.window.project is not None
        page = self.window.pages[self.window.page_index["resources"]]
        self.assertIsInstance(page, ResourcePage)
        assert isinstance(page, ResourcePage)
        allocation = self.window.project.import_expansion_resource(
            "ui.sample",
            "界面测试资源",
            bytes(range(64)),
        )
        page.refresh()
        self.assertEqual(page.allocation_table.rowCount(), 1)
        self.assertIn("64", page.capacity.format())
        self.assertIn("$40", page.allocation_table.item(0, 2).text())
        self.window.project.undo()
        page.refresh()
        self.assertEqual(page.allocation_table.rowCount(), 0)
        self.assertEqual(allocation.first_bank, 0x40)

    def test_resource_page_applies_recommended_auto_plan(self) -> None:
        assert self.window.project is not None
        page = self.window.pages[self.window.page_index["resources"]]
        self.assertIsInstance(page, ResourcePage)
        assert isinstance(page, ResourcePage)
        page.refresh()
        self.assertEqual(
            (page.map_quota.value(), page.unit_quota.value(), page.story_quota.value()),
            (304, 48, 112),
        )
        self.assertTrue(page.apply_plan_button.isEnabled())

        page.apply_plan_button.click()
        plan = self.window.project.expansion_plan
        self.assertIsNotNone(plan)
        assert plan is not None
        self.assertEqual(plan.total_kib, 464)
        self.assertEqual(self.window.project.expansion_available, 0)
        self.assertEqual(page.allocation_table.rowCount(), 4)
        self.assertFalse(page.map_quota.isEnabled())
        self.assertIn("已接通", page.plan_status.text())

        self.window.undo()
        self.assertIsNone(self.window.project.expansion_plan)
        self.assertEqual(self.window.project.expansion_allocations, ())

    def test_advanced_resource_import_requires_a_safe_planned_remainder(self) -> None:
        assert self.window.project is not None
        page = self.window.pages[self.window.page_index["resources"]]
        assert isinstance(page, ResourcePage)

        page.refresh()
        self.assertIsNone(self.window.project.expansion_plan)
        self.assertGreater(self.window.project.expansion_available, 0)
        self.assertFalse(page.import_button.isEnabled())

        self.window.project.configure_expansion(16, 48, 16)
        page.refresh()
        self.assertGreater(self.window.project.expansion_available, 0)
        self.assertTrue(page.import_button.isEnabled())

        with tempfile.TemporaryDirectory() as directory:
            output = self.window.project.save_as(Path(directory) / "partial-plan.nes")
            self.assertTrue(self.window.load_rom(output))
            guarded_page = self.window.pages[self.window.page_index["resources"]]
            assert isinstance(guarded_page, ResourcePage)
            guarded_page.refresh()
            self.assertTrue(
                any(
                    allocation.resource_id.startswith("auto.reopen_guard.")
                    for allocation in self.window.project.expansion_allocations
                )
            )
            self.assertFalse(guarded_page.import_button.isEnabled())

        if LEGACY_ROM.is_file():
            self.assertTrue(self.window.load_rom(LEGACY_ROM))
            legacy_page = self.window.pages[self.window.page_index["resources"]]
            assert isinstance(legacy_page, ResourcePage)
            legacy_page.refresh()
            self.assertIsNone(self.window.project.expansion_plan)
            self.assertGreater(self.window.project.expansion_available, 0)
            self.assertTrue(legacy_page.import_button.isEnabled())

    def test_unplanned_project_open_and_drop_keep_legacy_map_route(self) -> None:
        assert self.window.project is not None

        class LocalUrl:
            def __init__(self, path: Path) -> None:
                self.path = path

            def toLocalFile(self) -> str:
                return str(self.path)

        class DropMimeData:
            def __init__(self, path: Path) -> None:
                self.url = LocalUrl(path)

            def urls(self) -> list[LocalUrl]:
                return [self.url]

        class DropEvent:
            def __init__(self, path: Path) -> None:
                self.data = DropMimeData(path)

            def mimeData(self) -> DropMimeData:
                return self.data

        with tempfile.TemporaryDirectory() as directory:
            project_path = Path(directory) / "unplanned.dcmod"
            self.window.project.save_project(project_path)

            self.window.show_page("maps")
            with patch.object(
                QFileDialog,
                "getOpenFileName",
                return_value=(str(project_path), "DC修改工程 (*.dcmod)"),
            ):
                self.window.open_project_dialog()
            self.assertEqual(self.window.module_status.text(), "战场地图")
            self.assertIs(self.window.workspace.currentWidget(), self.window.map_page)

            self.window.show_page("maps")
            self.window.dropEvent(DropEvent(project_path))
            self.assertEqual(self.window.module_status.text(), "战场地图")
            self.assertIs(self.window.workspace.currentWidget(), self.window.map_page)

    def test_id_expression_supports_hex_ranges_and_rejects_invalid_ids(self) -> None:
        self.assertEqual(
            parse_id_expression("$00-$02, 0x10，17", 0x20),
            [0, 1, 2, 16, 17],
        )
        with self.assertRaisesRegex(ValueError, "超出范围"):
            parse_id_expression("$21", 0x20)

    def test_unit_import_page_builds_package_and_previews_shared_ids(self) -> None:
        page = self.window.pages[self.window.page_index["unit_import"]]
        self.assertIsInstance(page, UnitImportPage)
        assert isinstance(page, UnitImportPage)
        page.source_unit.setCurrentIndex(page.source_unit.findData(1))
        page.target_unit.setCurrentIndex(page.target_unit.findData(1))
        page.include_chr.setChecked(True)
        page.chr_first_tile.setValue(0x20)
        page.chr_tile_count.setValue(2)
        page.use_selected_unit()
        self.assertIsNotNone(page.loaded_package)
        assert page.loaded_package is not None
        self.assertEqual(len(page.loaded_package.assets), 1)
        self.assertIn("$01", page.package_summary.text())
        self.assertIn("CHR $0020", page.package_summary.text())
        self.assertIn("$05", page.impact.text())
        self.assertIn("$48", page.impact.text())

    def test_chr_canvas_edit_and_undo(self) -> None:
        assert self.window.project is not None
        page = self.window.pages[self.window.page_index["unit_import"]]
        assert isinstance(page, UnitImportPage)
        graphics = page.graphics
        tile_index = next(
            index
            for index in range(self.window.project.chr_tile_count)
            if len(set(self.window.project.chr_tile_pixels(index))) > 1
        )
        graphics.tile_index.setValue(tile_index)
        self.assertEqual(graphics.sheet.selected_tile, tile_index)
        self.assertEqual(graphics.sheet_page.value(), tile_index // 256)
        original = self.window.project.chr_tile_pixels(tile_index)
        staged = list(original)
        staged[0] = (staged[0] + 1) % 4
        graphics.canvas.set_pixels(staged)
        graphics.apply_tile()
        self.assertEqual(self.window.project.chr_tile_pixels(tile_index), tuple(staged))
        self.window.undo()
        self.assertEqual(self.window.project.chr_tile_pixels(tile_index), original)

    def test_unit_page_edit_and_window_undo(self) -> None:
        assert self.window.project is not None
        page = self.window.pages[self.window.page_index["units"]]
        self.assertIsInstance(page, UnitPage)
        assert isinstance(page, UnitPage)
        self.assertLess(page.name_reference.count(), 255)
        self.assertTrue(
            all(
                "原生名称" not in page.name_reference.itemText(index)
                for index in range(page.name_reference.count())
            )
        )
        self.assertEqual(page.record_text(0x79), "$79  里克·大魔")
        self.assertIn("光束军刀", page.weapon_slots[0].itemText(page.weapon_slots[0].findData(1)))
        page.records.setCurrentRow(0)
        unit_id = int(page.records.currentItem().data(256))
        old_value = self.window.project.get_value(unit_id, "movement")
        new_value = (old_value + 1) & 0xFF
        page.fields["movement"].setValue(new_value)
        page.apply_record()
        self.assertEqual(self.window.project.get_value(unit_id, "movement"), new_value)
        self.window.undo()
        self.assertEqual(self.window.project.get_value(unit_id, "movement"), old_value)

    def test_music_binding_and_validation_page(self) -> None:
        assert self.window.project is not None
        page = self.window.pages[self.window.page_index["music"]]
        self.assertIsInstance(page, MusicPage)
        assert isinstance(page, MusicPage)
        page.records.setCurrentRow(0x04)
        page.attacker.setCurrentIndex(page.attacker.findData(0x9E))
        page.defender.setCurrentIndex(page.defender.findData(0x9E))
        self.assertTrue(page.apply_button.isEnabled())
        self.assertIn("尚未应用", page.pending_state.text())
        page.apply_record()
        binding = self.window.project.get_battle_music_binding(0x04)
        self.assertEqual((binding.attacker_command, binding.defender_command), (0x9E, 0x9E))
        self.assertEqual(page.music_slot.count(), 3)
        self.assertEqual(page.music_slot.itemData(0), 0x9D)
        self.assertIn("8192 字节", page.music_slot_status.text())
        self.assertIn("查理", page.record_text(0x02))
        self.assertIn("睿智之神", page.record_text(0x13))

        validation_dialog = self.window._create_extension_dialog("changes")
        validation_page = validation_dialog.page
        self.assertIsInstance(validation_page, ChangesPage)
        assert isinstance(validation_page, ChangesPage)
        self.assertGreater(validation_page.validation.rowCount(), 0)
        validation_dialog.reject()

    def test_character_page_edits_name_and_music_together(self) -> None:
        assert self.window.project is not None
        page = self.window.pages[self.window.page_index["characters"]]
        self.assertIsInstance(page, CharacterPage)
        assert isinstance(page, CharacterPage)
        page.records.setCurrentRow(0x12)
        self.assertEqual(page.current_id, 0x13)
        self.assertIn("拉坎", page.record_heading.text())
        page.name_reference.setCurrentIndex(page.name_reference.findData(0x02))
        page.ally_music.setCurrentIndex(page.ally_music.findData(0x9E))
        page.enemy_music.setCurrentIndex(page.enemy_music.findData(0x9F))
        self.assertTrue(page.apply_button.isEnabled())
        page.apply_record()
        self.assertEqual(self.window.project.character_display_name(0x13), "查理")
        binding = self.window.project.get_battle_music_binding(0x13)
        self.assertEqual(
            (binding.attacker_command, binding.defender_command),
            (0x9E, 0x9F),
        )
        self.window.undo()
        self.assertEqual(self.window.project.character_display_name(0x13), "拉坎")

    def test_map_page_applies_a_capacity_safe_tile_change(self) -> None:
        assert self.window.project is not None
        page = self.window.pages[self.window.page_index["maps"]]
        self.assertIsInstance(page, MapPage)
        assert isinstance(page, MapPage)
        self.assertEqual(page.tileset.currentData(), "D")
        self.assertEqual(len(page.canvas.tile_images), 16)
        self.assertFalse(page.canvas.tile_images[1].isNull())
        record, changed_index, changed_tile = self._stage_capacity_safe_tile_draft(page)
        page.apply_changes()
        changed = self.window.project.get_map(0)
        self.assertEqual(changed.tiles[changed_index], changed_tile)
        self.window.undo()
        self.assertEqual(self.window.project.get_map(0).tiles, record.tiles)

    def test_map_record_switch_commits_one_draft_as_one_undo_step(self) -> None:
        assert self.window.project is not None
        page = self.window.pages[self.window.page_index["maps"]]
        assert isinstance(page, MapPage)
        record, changed_index, changed_tile = self._stage_capacity_safe_tile_draft(page)
        undo_count = len(self.window.project._undo_stack)

        page.map_list.setCurrentRow(1)
        self.application.processEvents()

        self.assertEqual(page.current_map_id, 1)
        self.assertEqual(
            self.window.project.get_map(0).tiles[changed_index],
            changed_tile,
        )
        self.assertEqual(len(self.window.project._undo_stack), undo_count + 1)
        self.window.undo()
        self.assertEqual(self.window.project.get_map(0).tiles, record.tiles)
        self.assertEqual(len(self.window.project._undo_stack), undo_count)

    def test_map_draft_immediately_updates_window_unsaved_state(self) -> None:
        page = self.window.pages[self.window.page_index["maps"]]
        assert isinstance(page, MapPage)
        self.assertFalse(self.window.has_unsaved_changes)
        self.assertFalse(self.window.windowTitle().endswith(" *"))

        self._stage_capacity_safe_tile_draft(page)
        self.application.processEvents()

        self.assertTrue(self.window.has_unsaved_changes)
        self.assertTrue(self.window.windowTitle().endswith(" *"))
        self.assertIn("0 字节修改", self.window.session_status.text())
        self.assertIn("未应用草稿", self.window.session_status.text())
        self.assertTrue(self.window.undo_action.isEnabled())

        page.refresh()
        self.application.processEvents()
        self.assertFalse(page.has_pending_draft)
        self.assertFalse(self.window.has_unsaved_changes)
        self.assertFalse(self.window.windowTitle().endswith(" *"))
        self.assertFalse(self.window.undo_action.isEnabled())

        page.prelude.setText("0")
        self.application.processEvents()
        self.assertIsNotNone(page.pending_draft_error)
        self.assertTrue(self.window.has_unsaved_changes)
        self.assertTrue(self.window.windowTitle().endswith(" *"))

    def test_undo_commits_valid_map_draft_then_undoes_it(self) -> None:
        assert self.window.project is not None
        page = self.window.pages[self.window.page_index["maps"]]
        assert isinstance(page, MapPage)
        record, _, _ = self._stage_capacity_safe_tile_draft(page)

        self.window.undo()

        self.assertFalse(page.has_pending_draft)
        self.assertEqual(self.window.project.get_map(0).tiles, record.tiles)
        self.assertTrue(self.window.project.can_redo)
        self.assertFalse(self.window.has_unsaved_changes)

    def test_undo_blocks_and_preserves_invalid_map_draft(self) -> None:
        assert self.window.project is not None
        page = self.window.pages[self.window.page_index["maps"]]
        assert isinstance(page, MapPage)
        before = bytes(self.window.project.working)
        page.prelude.setText("0")

        with patch("dc_modifier.app.QMessageBox.warning") as warning:
            self.window.undo()

        warning.assert_called_once()
        self.assertEqual(bytes(self.window.project.working), before)
        self.assertEqual(page.prelude.text(), "0")
        self.assertTrue(page.has_pending_draft)
        self.assertIsNotNone(page.pending_draft_error)

    def test_redo_blocks_and_preserves_valid_map_draft(self) -> None:
        assert self.window.project is not None
        page = self.window.pages[self.window.page_index["maps"]]
        assert isinstance(page, MapPage)
        record, _, _ = self._stage_capacity_safe_tile_draft(page)
        page.apply_changes()
        self.window.undo()
        self.assertEqual(self.window.project.get_map(0).tiles, record.tiles)
        self.assertTrue(self.window.project.can_redo)
        before = bytes(self.window.project.working)

        self._stage_capacity_safe_tile_draft(page)
        draft_signature = page._draft_signature()
        with patch("dc_modifier.app.QMessageBox.warning") as warning:
            self.window.redo()

        warning.assert_called_once()
        self.assertEqual(bytes(self.window.project.working), before)
        self.assertTrue(page.has_pending_draft)
        self.assertEqual(page._draft_signature(), draft_signature)
        self.assertTrue(self.window.project.can_redo)

    def test_redo_blocks_and_preserves_invalid_map_draft(self) -> None:
        assert self.window.project is not None
        page = self.window.pages[self.window.page_index["maps"]]
        assert isinstance(page, MapPage)
        record, _, _ = self._stage_capacity_safe_tile_draft(page)
        page.apply_changes()
        self.window.undo()
        self.assertEqual(self.window.project.get_map(0).tiles, record.tiles)
        self.assertTrue(self.window.project.can_redo)
        before = bytes(self.window.project.working)
        page.prelude.setText("0")

        with patch("dc_modifier.app.QMessageBox.warning") as warning:
            self.window.redo()

        warning.assert_called_once()
        self.assertEqual(bytes(self.window.project.working), before)
        self.assertTrue(self.window.project.can_redo)
        self.assertEqual(page.prelude.text(), "0")
        self.assertTrue(page.has_pending_draft)

    def test_validation_commits_valid_map_draft_before_opening_results(self) -> None:
        assert self.window.project is not None
        page = self.window.pages[self.window.page_index["maps"]]
        assert isinstance(page, MapPage)
        _, changed_index, changed_tile = self._stage_capacity_safe_tile_draft(page)

        with patch.object(self.window, "_open_extension_page") as open_page:
            self.window.validate_project()

        open_page.assert_called_once_with("changes")
        self.assertFalse(page.has_pending_draft)
        self.assertEqual(
            self.window.project.get_map(0).tiles[changed_index],
            changed_tile,
        )

    def test_validation_blocks_and_preserves_invalid_map_draft(self) -> None:
        assert self.window.project is not None
        page = self.window.pages[self.window.page_index["maps"]]
        assert isinstance(page, MapPage)
        before = bytes(self.window.project.working)
        page.prelude.setText("0")

        with (
            patch("dc_modifier.app.QMessageBox.warning") as warning,
            patch.object(self.window, "_open_extension_page") as open_page,
        ):
            self.window.validate_project()

        warning.assert_called_once()
        open_page.assert_not_called()
        self.assertEqual(bytes(self.window.project.working), before)
        self.assertEqual(page.prelude.text(), "0")
        self.assertTrue(page.has_pending_draft)

    def test_save_project_commits_valid_map_draft_before_writing(self) -> None:
        assert self.window.project is not None
        page = self.window.pages[self.window.page_index["maps"]]
        assert isinstance(page, MapPage)
        _, changed_index, changed_tile = self._stage_capacity_safe_tile_draft(page)
        self.assertNotEqual(
            self.window.project.get_map(0).tiles[changed_index],
            changed_tile,
        )

        with tempfile.TemporaryDirectory() as directory:
            destination = Path(directory) / "valid-map-draft.dcmod"
            self.window.project_path = destination
            self.window.save_project()

            self.assertTrue(destination.is_file())
            self.assertFalse(page.has_pending_draft)
            self.assertEqual(
                self.window.project.get_map(0).tiles[changed_index],
                changed_tile,
            )
            reopened = RomProject.load_project(destination, self.window.project.path)
            self.assertEqual(reopened.get_map(0).tiles[changed_index], changed_tile)

    def test_write_rom_commits_valid_map_draft_before_writing(self) -> None:
        assert self.window.project is not None
        page = self.window.pages[self.window.page_index["maps"]]
        assert isinstance(page, MapPage)
        _, changed_index, changed_tile = self._stage_capacity_safe_tile_draft(page)

        with tempfile.TemporaryDirectory() as directory:
            destination = Path(directory) / "valid-map-draft.nes"
            self.window._write_rom(destination)

            self.assertTrue(destination.is_file())
            self.assertFalse(page.has_pending_draft)
            reopened = RomProject.load(destination)
            self.assertEqual(reopened.get_map(0).tiles[changed_index], changed_tile)

    def test_invalid_map_draft_blocks_project_and_rom_writes(self) -> None:
        assert self.window.project is not None
        page = self.window.pages[self.window.page_index["maps"]]
        assert isinstance(page, MapPage)
        before = bytes(self.window.project.working)
        page.prelude.setText("0")
        self.assertTrue(page.has_pending_draft)
        self.assertIsNotNone(page.pending_draft_error)

        with tempfile.TemporaryDirectory() as directory:
            project_destination = Path(directory) / "invalid-map-draft.dcmod"
            rom_destination = Path(directory) / "invalid-map-draft.nes"
            self.window.project_path = project_destination
            with patch("dc_modifier.app.QMessageBox.warning") as warning:
                self.window.save_project()
                self.window._write_rom(rom_destination)

            self.assertEqual(warning.call_count, 2)
            self.assertFalse(project_destination.exists())
            self.assertFalse(rom_destination.exists())
            self.assertEqual(bytes(self.window.project.working), before)
            self.assertTrue(page.has_pending_draft)

    def test_map_page_matches_legacy_layout_and_fits_full_map(self) -> None:
        page = self.window.pages[self.window.page_index["maps"]]
        assert isinstance(page, MapPage)
        self.window.show_page("maps")
        self.window.show()
        self.application.processEvents()

        self.assertEqual(page.main_splitter.count(), 2)
        self.assertIs(page.main_splitter.widget(0), page.navigator)
        self.assertIs(page.main_splitter.widget(1), page.canvas_host)
        self.assertEqual(page.navigator.layout().indexOf(page.editor_tabs), 0)
        self.assertLess(page.editor_tabs.geometry().bottom(), page.chapter_group.geometry().top())
        self.assertGreaterEqual(page.chapter_group.minimumHeight(), 260)
        self.assertFalse(page.icon_preview_toggle.isChecked())
        self.assertFalse(page.icon_preview_group.isVisible())
        self.assertTrue(page.fit_view.isChecked())
        self.assertFalse(page.zoom.isEnabled())

        page._fit_map_to_viewport()
        self.application.processEvents()
        viewport = page.map_scroll.viewport()
        self.assertLessEqual(page.canvas.width(), viewport.width())
        self.assertLessEqual(page.canvas.height(), viewport.height())
        self.assertEqual(page.canvas.cell_size, page.zoom.value())
        self.assertEqual(page.map_scroll.horizontalScrollBar().maximum(), 0)
        self.assertEqual(page.map_scroll.verticalScrollBar().maximum(), 0)

        page.fit_view.setChecked(False)
        self.assertTrue(page.zoom.isEnabled())

    def test_map_page_edits_coordinate_event_and_shop(self) -> None:
        assert self.window.project is not None
        page = self.window.pages[self.window.page_index["maps"]]
        assert isinstance(page, MapPage)
        self.assertEqual(self.window.project.get_map_triggers(0), ())
        page.trigger_table.set_rows([(3, 4, 0xFF, 0xF2)])
        self.assertTrue(page.apply_button.isEnabled())
        page.apply_changes()
        entries = self.window.project.get_map_triggers(0)
        self.assertEqual(tuple(entries[0].to_bytes()), (3, 4, 0xFF, 0xF2))
        self.assertTrue(entries[0].is_shop)
        self.assertEqual(entries[0].shop_id, 2)
        self.window.undo()
        self.assertEqual(self.window.project.get_map_triggers(0), ())

    def test_weapon_and_deployment_ids_have_resolved_names(self) -> None:
        weapon_page = self.window.pages[self.window.page_index["weapons"]]
        self.assertIsInstance(weapon_page, WeaponPage)
        assert isinstance(weapon_page, WeaponPage)
        self.assertEqual(weapon_page.record_text(0x01), "$01  光束军刀")
        self.assertEqual(weapon_page.record_text(0x0B), "$0B  交叉粉碎炮")

        map_page = self.window.pages[self.window.page_index["maps"]]
        assert isinstance(map_page, MapPage)
        self.assertIn("伏击之战", map_page.map_list.item(0).text())
        if map_page.enemy_table.rowCount():
            unit_editor = map_page.enemy_table.cellWidget(0, 2)
            pilot_editor = map_page.enemy_table.cellWidget(0, 3)
            self.assertIn(" · ", unit_editor.currentText())
            self.assertIn(" · ", pilot_editor.currentText())

    def test_story_page_decodes_tokens_without_changing_rom(self) -> None:
        assert self.window.project is not None
        page = self.window.pages[self.window.page_index["story"]]
        self.assertIsInstance(page, StoryPage)
        assert isinstance(page, StoryPage)
        self.assertIsNotNone(page.current_selector)
        self.assertIsNotNone(page.current_index)
        self.assertGreater(page.tokens.rowCount(), 0)
        page.selector.setCurrentIndex(page.selector.findData(0x32))
        page.indices.setCurrentRow(0x0E)
        self.assertIn("劝降拉拉", page.decoded.toPlainText())
        self.assertNotIn("<C9", page.decoded.toPlainText())
        before = bytes(self.window.project.working)
        page.apply_text()
        self.assertEqual(bytes(self.window.project.working), before)

    def test_story_unicode_view_preserves_unmapped_tokens(self) -> None:
        page = self.window.pages[self.window.page_index["story"]]
        assert isinstance(page, StoryPage)
        original_raw = page._parse_hex(page.raw.toPlainText())
        page.text_table = TextTable.parse("FF=[结束]\n")
        page._render_decoded()
        decoded = page.decoded.toPlainText()
        self.assertTrue("[结束]" in decoded or "<" in decoded)
        self.assertEqual(page.text_table.encode(decoded), original_raw)

    def test_event_page_edits_reinforcement_with_compatible_template(self) -> None:
        assert self.window.project is not None
        page = self.window.pages[self.window.page_index["events"]]
        self.assertIsInstance(page, EventPage)
        assert isinstance(page, EventPage)
        page.search.setText("A11D")
        self.assertEqual(page.table.rowCount(), 1)
        page.table.selectRow(0)
        instruction = page._selected_instruction()
        self.assertIsNotNone(instruction)
        assert instruction is not None
        self.assertEqual(instruction.opcode, 0x4B)
        self.assertIn("人物ID=$2A（", page._parameter_text(instruction))
        self.assertIn("机体ID=$5E（", page._parameter_text(instruction))
        page.template.setCurrentIndex(page.template.findData(0x4A))
        page.parameters[0].setValue(0x10)
        page.parameters[1].setValue(0x08)
        page.apply_template_button.click()
        changed = self.window.project.chapter_event_codec.instruction_at(
            instruction.address, bytes(self.window.project.working)
        )
        self.assertEqual(changed.opcode, 0x4A)
        self.assertEqual(changed.parameters[:2], (0x10, 0x08))
        self.window.undo()
        restored = self.window.project.chapter_event_codec.instruction_at(
            instruction.address, bytes(self.window.project.working)
        )
        self.assertEqual(restored.opcode, 0x4B)

    def test_event_page_can_toggle_terminal_bit_without_semantic_template(self) -> None:
        assert self.window.project is not None
        page = self.window.pages[self.window.page_index["events"]]
        self.assertIsInstance(page, EventPage)
        assert isinstance(page, EventPage)
        page.kind_filter.setCurrentIndex(
            page.kind_filter.findText("全部指令（专家）")
        )
        self.application.processEvents()
        instruction = next(
            item for item in page._instructions if item.opcode not in ACTION_LABELS
        )
        self.assertTrue(page._select_address(instruction.address))
        self.application.processEvents()
        self.assertIsNone(page.template.currentData())

        page.terminal.setChecked(not instruction.is_terminal)
        self.assertTrue(page.has_pending_draft)
        self.assertIsNone(page.pending_draft_error)
        self.assertTrue(page.apply_template_button.isEnabled())
        page.apply_template_button.click()

        changed = self.window.project.chapter_event_codec.instruction_at(
            instruction.address, bytes(self.window.project.working)
        )
        self.assertEqual(changed.raw[0], instruction.raw[0] ^ 0x80)
        self.assertEqual(changed.raw[1:], instruction.raw[1:])
        self.window.undo()
        restored = self.window.project.chapter_event_codec.instruction_at(
            instruction.address, bytes(self.window.project.working)
        )
        self.assertEqual(restored.raw, instruction.raw)

    def test_event_filter_commits_terminal_draft_to_the_old_instruction(self) -> None:
        assert self.window.project is not None
        page = self.window.pages[self.window.page_index["events"]]
        assert isinstance(page, EventPage)
        page.kind_filter.setCurrentIndex(
            page.kind_filter.findText("全部指令（专家）")
        )
        self.application.processEvents()
        old = next(item for item in page._instructions if item.opcode not in ACTION_LABELS)
        self.assertTrue(page._select_address(old.address))
        self.application.processEvents()
        page.terminal.setChecked(not old.is_terminal)
        page.kind_filter.setCurrentIndex(
            page.kind_filter.findText("可编辑事件动作")
        )
        self.application.processEvents()

        changed_old = self.window.project.chapter_event_codec.instruction_at(
            old.address, bytes(self.window.project.working)
        )
        self.assertEqual(changed_old.raw[0], old.raw[0] ^ 0x80)
        selected = page._selected_instruction()
        self.assertIsNotNone(selected)
        assert selected is not None
        self.assertNotEqual(selected.address, old.address)
        self.assertEqual(
            selected.raw,
            self.window.project.chapter_event_codec.instruction_at(
                selected.address, self.window.project.original
            ).raw,
        )

    def test_event_search_commits_draft_before_repopulating_same_row(self) -> None:
        assert self.window.project is not None
        page = self.window.pages[self.window.page_index["events"]]
        assert isinstance(page, EventPage)
        instruction = page._selected_instruction()
        self.assertIsNotNone(instruction)
        assert instruction is not None
        page.terminal.setChecked(not instruction.is_terminal)

        page.search.setText(f"{instruction.address:04X}")
        self.application.processEvents()

        changed = self.window.project.chapter_event_codec.instruction_at(
            instruction.address, bytes(self.window.project.working)
        )
        self.assertEqual(changed.raw[0], instruction.raw[0] ^ 0x80)
        self.assertFalse(page.has_pending_draft)

    def test_event_filter_rejects_invalid_draft_and_restores_filter(self) -> None:
        page = self.window.pages[self.window.page_index["events"]]
        assert isinstance(page, EventPage)
        instruction = page._selected_instruction()
        self.assertIsNotNone(instruction)
        assert instruction is not None
        invalid = "00" if len(instruction.raw) != 1 else "00 00"
        page.raw.setText(invalid)
        self.assertTrue(page.has_pending_draft)
        self.assertIsNotNone(page.pending_draft_error)

        with patch("dc_modifier.pages.QMessageBox.critical") as critical:
            page.search.setText("不会命中")
            self.application.processEvents()

        critical.assert_called_once()
        self.assertEqual(page.search.text(), "")
        self.assertEqual(page.current_address, instruction.address)
        self.assertEqual(page.raw.text(), invalid)
        self.assertTrue(page.has_pending_draft)

    def test_event_invalid_raw_blocks_simultaneous_template_draft(self) -> None:
        assert self.window.project is not None
        page = self.window.pages[self.window.page_index["events"]]
        assert isinstance(page, EventPage)
        instruction = page._selected_instruction()
        self.assertIsNotNone(instruction)
        assert instruction is not None
        before = bytes(self.window.project.working)

        page.terminal.setChecked(not instruction.is_terminal)
        page.raw.setText("GG")

        self.assertTrue(page.has_pending_draft)
        self.assertTrue(page.apply_template_button.isEnabled())
        self.assertFalse(page.apply_raw_button.isEnabled())
        self.assertIsNotNone(page.pending_draft_error)
        self.assertFalse(page.commit_pending_changes())
        self.assertEqual(bytes(self.window.project.working), before)
        self.assertEqual(page.raw.text(), "GG")
        self.assertEqual(page.terminal.isChecked(), not instruction.is_terminal)

    def test_persuasion_page_uses_named_characters_and_undo(self) -> None:
        assert self.window.project is not None
        page = self.window.pages[self.window.page_index["persuasion"]]
        self.assertIsInstance(page, PersuasionPage)
        assert isinstance(page, PersuasionPage)
        self.assertEqual(page.table.rowCount(), 4)
        self.assertNotIn("原生名称", page.table.item(0, 2).text())
        original = self.window.project.get_persuasion_rule(0)
        page.table.selectRow(0)
        page.chapter.setCurrentIndex(page.chapter.findData(0x02))
        page.persuader.setCurrentIndex(page.persuader.findData(0x08))
        page.target.setCurrentIndex(page.target.findData(0x42))
        page.apply_button.click()
        changed = self.window.project.get_persuasion_rule(0)
        self.assertEqual(changed.raw, bytes((0x02, 0x08, 0x42)))
        self.window.undo()
        self.assertEqual(self.window.project.get_persuasion_rule(0).raw, original.raw)


if __name__ == "__main__":
    unittest.main(verbosity=2)
