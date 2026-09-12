from __future__ import annotations

import os
from pathlib import Path
import tempfile
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QPoint
from PySide6.QtGui import QFont, QFontDatabase
from PySide6.QtWidgets import QApplication, QGroupBox

from dc_modifier.legacy_tools import (
    AttributeCalculatorDialog,
    FontLibraryDialog,
    MapAnimationDialog,
    OtherSettingsDialog,
    SaveEditorDialog,
    TextConverterDialog,
    _glyph_file_offset,
    _glyph_pixmap,
)
from fc_editor.text_table import TextTable
from fc_rom_editor_core import RomProject


ROOT = Path(__file__).resolve().parents[1]
ROM_PATH = ROOT / "output" / "rom" / "DC_kuorong_464K.nes"


from tests.qt_test_case import QtTestCase


class LegacyToolDialogTests(QtTestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.application = QApplication.instance() or QApplication([])
        cls.application.setStyle("Fusion")
        font_id = QFontDatabase.addApplicationFont(r"C:\Windows\Fonts\msyh.ttc")
        families = QFontDatabase.applicationFontFamilies(font_id)
        cls.application.setFont(QFont(families[0] if families else "Microsoft YaHei UI", 10))
        cls.project = RomProject.load(ROM_PATH) if ROM_PATH.is_file() else None

    def tearDown(self) -> None:
        self.application.processEvents()

    def _show(self, dialog) -> None:
        dialog.show()
        self.application.processEvents()

    @staticmethod
    def _top(widget, dialog) -> int:
        return widget.mapTo(dialog, QPoint(0, 0)).y()

    def test_font_library_uses_legacy_grid_and_real_glyph_address(self) -> None:
        before = bytes(self.project.working) if self.project is not None else None
        dialog = FontLibraryDialog(project=self.project)
        self.assertEqual(dialog.windowTitle(), "字库编辑")
        self.assertEqual((dialog.glyph_table.rowCount(), dialog.glyph_table.columnCount()), (16, 16))
        self.assertEqual(dialog.page_selector.count(), 12)
        self.assertEqual(dialog.page_selector.currentData(), 0xC8)
        self.assertEqual(dialog.code_value.text(), "C800")
        self.assertEqual(dialog.address_value.text(), "070010")
        self.assertFalse(dialog.write_button.isEnabled())
        self.assertEqual(dialog.replace_all_button.isEnabled(), self.project is not None)
        self._show(dialog)
        self.assertLess(self._top(dialog.glyph_table, dialog), self._top(dialog.status, dialog))
        if self.project is not None:
            self.assertFalse(dialog.glyph_table.item(0, 0).icon().isNull())
        dialog.reject()
        if self.project is not None:
            self.assertEqual(bytes(self.project.working), before)

    def test_glyph_addresses_follow_verified_paged_row_layout(self) -> None:
        self.assertEqual(_glyph_file_offset(bytes.fromhex("C908")), 0x710A0)
        self.assertEqual(_glyph_file_offset(bytes.fromhex("DAC2")), 0x76C34)
        self.assertEqual(
            _glyph_file_offset(bytes.fromhex("C90E")),
            _glyph_file_offset(bytes.fromhex("C900")),
        )

    def test_glyph_preview_uses_rom_bits_instead_of_host_font(self) -> None:
        blank = _glyph_pixmap(b"\xff" * 18, character="啊", scale=2).toImage()
        self.assertEqual(blank.pixelColor(0, 0).name(), "#080808")
        self.assertEqual(blank.pixelColor(12, 12).name(), "#080808")
        marked = _glyph_pixmap(bytes((0x7F,)) + b"\xff" * 17, character="啊", scale=2).toImage()
        self.assertEqual(marked.pixelColor(0, 0).name(), "#f5f5f5")
        self.assertEqual(marked.pixelColor(2, 0).name(), "#080808")

    def test_map_animation_has_three_legacy_tabs_and_real_rom_instructions(self) -> None:
        if self.project is None:
            self.skipTest("测试 ROM 不存在")
        dialog = MapAnimationDialog(project=self.project)
        self.assertEqual(
            [dialog.tabs.tabText(index) for index in range(dialog.tabs.count())],
            ["地图动画", "规律", "动画调用"],
        )
        self.assertEqual(dialog.animation_list.count(), 153)
        self.assertEqual(dialog.instruction_table.rowCount(), 11)
        self.assertIn("切换 00 区域图库", dialog.instruction_table.item(0, 0).text())
        self.assertEqual(dialog.instruction_table.item(0, 1).text(), "E0 0A")
        self.assertFalse(dialog.add_button.isEnabled())
        self.assertTrue(dialog.code_button.isEnabled())
        self.assertIn("当前 ROM", dialog.read_only_status.text())
        self.assertEqual(dialog.rule_lists["movement"].count(), 157)
        self.assertGreater(dialog.call_table.rowCount(), 50)
        self._show(dialog)
        self.assertLess(self._top(dialog.animation_list, dialog), self._top(dialog.add_button, dialog))
        self.assertLess(self._top(dialog.add_button, dialog), self._top(dialog.animation_name, dialog))
        self.assertLess(self._top(dialog.instruction_table, dialog), self._top(dialog.code_button, dialog))
        dialog.reject()

    def test_text_converter_round_trips_and_reports_invalid_hex(self) -> None:
        table = TextTable({b"\x10": "甲", b"\x11": "乙", b"\xFF": "终"})
        dialog = TextConverterDialog(text_table=table)
        dialog.text_edit.setPlainText("甲乙终")
        dialog.encode_button.click()
        self.assertEqual(dialog.code_edit.toPlainText(), "10 11 FF")
        dialog.text_edit.clear()
        dialog.decode_button.click()
        self.assertEqual(dialog.text_edit.toPlainText(), "甲乙终")
        self.assertEqual(TextConverterDialog.parse_code("<10>, $11 0xFF"), b"\x10\x11\xFF")
        dialog.code_edit.setPlainText("123")
        dialog.decode_button.click()
        self.assertIn("转换失败", dialog.status.text())
        self._show(dialog)
        self.assertLess(self._top(dialog.text_edit, dialog), self._top(dialog.encode_button, dialog))
        self.assertLess(dialog.encode_button.mapTo(dialog, QPoint(0, 0)).x(), dialog.decode_button.mapTo(dialog, QPoint(0, 0)).x())
        self.assertLess(self._top(dialog.decode_button, dialog), self._top(dialog.code_edit, dialog))
        dialog.close()

    def test_attribute_calculator_uses_documented_deterministic_formula(self) -> None:
        dialog = AttributeCalculatorDialog()
        dialog.enemy.strength.setValue(30)
        dialog.enemy.power_land.setValue(20)
        dialog.enemy.weapon_hit.setValue(70)
        dialog.enemy.speed.setValue(25)
        dialog.enemy.multiplier_numerator.setValue(3)
        dialog.enemy.multiplier_denominator.setValue(2)
        dialog.ally.defense.setValue(15)
        dialog.ally.speed.setValue(20)
        dialog.ally.hp.setValue(100)
        dialog.calculate_button.click()
        self.assertEqual(dialog.results.rowCount(), 2)
        self.assertEqual(dialog.results.item(0, 2).text(), "75%")
        self.assertEqual(dialog.results.item(0, 3).text(), "0")
        self.assertEqual(dialog.results.item(0, 4).text(), "60")
        self.assertEqual(dialog.results.item(0, 5).text(), "40")
        self.assertFalse(dialog.results.horizontalHeader().isHidden())
        dialog.close()

    def test_attribute_calculator_opens_with_empty_lower_result_area(self) -> None:
        dialog = AttributeCalculatorDialog()
        self.assertEqual(dialog.results.rowCount(), 0)
        self.assertTrue(dialog.results.horizontalHeader().isHidden())
        self._show(dialog)
        self.assertLess(self._top(dialog.enemy, dialog), self._top(dialog.results, dialog))
        self.assertLess(self._top(dialog.results, dialog), self._top(dialog.calculate_button, dialog))
        dialog.close()

    def test_project_backed_calculator_populates_verified_records(self) -> None:
        if self.project is None:
            self.skipTest("测试ROM不存在")
        dialog = AttributeCalculatorDialog(project=self.project)
        self.assertEqual(dialog.enemy.unit.count(), self.project.unit_count - 1)
        self.assertEqual(dialog.enemy.weapon.count(), self.project.weapon_count)
        self.assertEqual(dialog.enemy.unit.currentData(), 2)
        self.assertEqual(dialog.enemy.character.currentData(), 4)
        self.assertEqual(dialog.enemy.weapon.currentData(), 1)
        unit = self.project.unit_codec.decode_record(
            int(dialog.enemy.unit.currentData()), bytes(self.project.working)
        )
        self.assertEqual(dialog.enemy.strength.value(), unit.get("strength"))
        self.assertEqual(dialog.enemy.hp.value(), unit.get("hp"))
        self.assertIn("人物属性", dialog.enemy.character_summary.text())
        dialog.close()

    def test_save_editor_reads_file_but_never_enables_unverified_writes(self) -> None:
        dialog = SaveEditorDialog(project=self.project)
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "sample.sav"
            payload = bytes(range(256))
            path.write_bytes(payload)
            dialog.load_path(path)
            self.assertTrue(dialog.read_button.isEnabled())
            dialog.read_button.click()
            self.assertEqual(dialog.save_bytes, payload)
            self.assertIn("256 字节", dialog.status.text())
            self.assertEqual(dialog.ally_table.rowCount(), 12)
            self.assertEqual(dialog.enemy_table.rowCount(), 12)
            self.assertFalse(dialog.write_button.isEnabled())
            self.assertFalse(dialog.save_button.isEnabled())
            self._show(dialog)
            self.assertLess(self._top(dialog.ally_table, dialog), self._top(dialog.enemy_table, dialog))
        dialog.close()

    def test_other_settings_loads_real_defaults_and_cancel_discards_drafts(self) -> None:
        if not ROM_PATH.is_file():
            self.skipTest("测试ROM不存在")
        project = RomProject.load(ROM_PATH)
        before = bytes(project.working)
        undo_count = len(project._undo_stack)
        dialog = OtherSettingsDialog(project=project)
        self.assertEqual(len(dialog.double_hit_values), 3)
        self.assertEqual(len(dialog.damage_values), 5)
        self.assertEqual(len(dialog.hit_values), 1)
        self.assertEqual(len(dialog.item_values), 11)
        self.assertEqual(len(dialog.initial_units), 12)
        self.assertTrue(dialog.accept_button.isEnabled())
        self.assertEqual(
            tuple(editor.value() for editor in dialog.double_hit_values),
            (70, 90, 20),
        )
        self.assertEqual(
            tuple(editor.value() for editor in dialog.damage_values),
            (13, 10, 10, 1, 1),
        )
        self.assertEqual(dialog.hit_values[0].value(), 70)
        self.assertEqual(
            tuple(editor.value() for editor in dialog.item_values),
            (1, 1, 1, 5, 3, 1, 3, 3, 25, 25, 50),
        )
        self.assertEqual(
            [combo.currentData() for combo in dialog.initial_units],
            [4, 9, 5, 13, 6, 15, 7, 17, 8, 19, 9, 23],
        )
        self.assertIn(
            project.character_display_name(4),
            dialog.initial_units[0].currentText(),
        )
        self.assertIn(
            project.unit_display_name(9),
            dialog.initial_units[1].currentText(),
        )
        dialog.double_hit_values[0].setValue(71)
        dialog.damage_values[0].setValue(14)
        dialog.hit_values[0].setValue(71)
        dialog.item_values[0].setValue(2)
        replacement = dialog.initial_units[0].findData(10)
        self.assertGreaterEqual(replacement, 0)
        dialog.initial_units[0].setCurrentIndex(replacement)
        self._show(dialog)
        groups = {group.title(): group for group in dialog.findChildren(QGroupBox)}
        self.assertLess(
            self._top(groups["双击公式"], dialog),
            self._top(groups["伤害计算公式"], dialog),
        )
        self.assertLess(
            self._top(groups["伤害计算公式"], dialog),
            self._top(groups["初始机体"], dialog),
        )
        dialog.reject()
        self.assertEqual(bytes(project.working), before)
        self.assertEqual(len(project._undo_stack), undo_count)

    def test_other_settings_ok_writes_every_group_as_one_undo_transaction(self) -> None:
        if not ROM_PATH.is_file():
            self.skipTest("测试ROM不存在")
        project = RomProject.load(ROM_PATH)
        before = bytes(project.working)
        undo_count = len(project._undo_stack)
        dialog = OtherSettingsDialog(project=project)
        new_double = (71, 91, 21)
        new_damage = (14, 11, 12, 2, 3)
        new_hit = 71
        new_items = (2, 2, 2, 6, 4, 2, 4, 4, 26, 26, 51)
        new_roster = tuple((0x10 + row, 0x40 + row) for row in range(6))

        for editor, value in zip(dialog.double_hit_values, new_double):
            editor.setValue(value)
        for editor, value in zip(dialog.damage_values, new_damage):
            editor.setValue(value)
        dialog.hit_values[0].setValue(new_hit)
        for editor, value in zip(dialog.item_values, new_items):
            editor.setValue(value)
        for row, (character_id, unit_id) in enumerate(new_roster):
            for combo, record_id in (
                (dialog.initial_units[row * 2], character_id),
                (dialog.initial_units[row * 2 + 1], unit_id),
            ):
                index = combo.findData(record_id)
                self.assertGreaterEqual(index, 0)
                combo.setCurrentIndex(index)

        self._show(dialog)
        dialog.accept()

        self.assertEqual(dialog.result(), dialog.DialogCode.Accepted)
        self.assertEqual(project.get_double_hit_values(), new_double)
        self.assertEqual(project.get_damage_formula_values(), new_damage)
        self.assertEqual(project.get_hit_threshold(), new_hit)
        self.assertEqual(project.get_item_effect_values(), new_items)
        self.assertEqual(project.get_initial_roster(), new_roster)
        self.assertEqual(len(project._undo_stack), undo_count + 1)
        self.assertEqual(project.undo_description, "其他全局参数")

        self.assertEqual(project.undo(), "其他全局参数")
        self.assertEqual(bytes(project.working), before)

    def test_other_settings_can_open_and_keep_zero_roster_ids(self) -> None:
        if not ROM_PATH.is_file():
            self.skipTest("测试ROM不存在")
        project = RomProject.load(ROM_PATH)
        roster = list(project.get_initial_roster())
        roster[0] = (0, 0)
        project.set_initial_roster(roster)

        dialog = OtherSettingsDialog(project=project)

        self.assertGreaterEqual(dialog.initial_units[0].findData(0), 0)
        self.assertGreaterEqual(dialog.initial_units[1].findData(0), 0)
        self.assertEqual(dialog.initial_units[0].currentData(), 0)
        self.assertEqual(dialog.initial_units[1].currentData(), 0)
        dialog.reject()

    def test_tool_geometry_and_offscreen_screenshots_render(self) -> None:
        flexible_dialogs = (
            ("converter", TextConverterDialog(), (600, 620)),
            ("calculator", AttributeCalculatorDialog(), (1120, 780)),
        )
        fixed_dialogs = (
            ("save", SaveEditorDialog(), (1175, 834)),
            ("other", OtherSettingsDialog(), (1166, 870)),
        )
        font_dialog = FontLibraryDialog(project=self.project)
        self.assertLess(font_dialog.minimumWidth(), font_dialog.maximumWidth())
        self.assertLess(font_dialog.minimumHeight(), font_dialog.maximumHeight())
        self._show(font_dialog)
        self.assertFalse(font_dialog.grab().isNull())
        font_dialog.reject()
        animation_dialog = MapAnimationDialog(project=self.project)
        self.assertLess(animation_dialog.minimumWidth(), animation_dialog.maximumWidth())
        self.assertLess(animation_dialog.minimumHeight(), animation_dialog.maximumHeight())
        self._show(animation_dialog)
        self.assertFalse(animation_dialog.grab().isNull())
        animation_dialog.reject()
        with tempfile.TemporaryDirectory() as directory:
            for name, dialog, expected in flexible_dialogs:
                with self.subTest(dialog=name):
                    self.assertLess(dialog.minimumWidth(), dialog.maximumWidth())
                    self.assertLess(dialog.minimumHeight(), dialog.maximumHeight())
                    self._show(dialog)
                    self.assertEqual((dialog.width(), dialog.height()), expected)
                    screenshot = Path(directory) / f"{name}.png"
                    pixmap = dialog.grab()
                    self.assertTrue(pixmap.save(str(screenshot), "PNG"))
                    self.assertGreater(screenshot.stat().st_size, 2000)
                    dialog.close()
            for name, dialog, expected in fixed_dialogs:
                with self.subTest(dialog=name):
                    self.assertEqual(
                        (dialog.minimumWidth(), dialog.minimumHeight()), expected
                    )
                    self.assertEqual(
                        (dialog.maximumWidth(), dialog.maximumHeight()), expected
                    )
                    self._show(dialog)
                    self.assertEqual((dialog.width(), dialog.height()), expected)
                    screenshot = Path(directory) / f"{name}.png"
                    pixmap = dialog.grab()
                    self.assertEqual((pixmap.width(), pixmap.height()), expected)
                    self.assertTrue(pixmap.save(str(screenshot), "PNG"))
                    self.assertGreater(screenshot.stat().st_size, 2000)
                    image = pixmap.toImage()
                    sample_colors = {
                        image.pixelColor(x, y).rgba()
                        for x in range(0, image.width(), max(1, image.width() // 12))
                        for y in range(0, image.height(), max(1, image.height() // 12))
                    }
                    self.assertGreater(len(sample_colors), 1)
                    dialog.close()

    def test_calculator_reports_minimum_hit_speed_from_visible_formula(self) -> None:
        dialog = AttributeCalculatorDialog()
        dialog.enemy.weapon_hit.setValue(70)
        dialog.enemy.speed.setValue(20)
        dialog.ally.speed.setValue(100)
        hit, minimum_speed, _damage, _remaining = dialog.calculate_attack(
            dialog.enemy, dialog.ally
        )
        self.assertEqual(hit, 0)
        self.assertEqual(minimum_speed, 31)
        dialog.calculate()
        self.assertEqual(dialog.results.columnCount(), 6)
        self.assertEqual(dialog.results.horizontalHeaderItem(3).text(), "最低命中速度")
        self.assertEqual(dialog.results.item(0, 3).text(), "31")
        dialog.close()


if __name__ == "__main__":
    unittest.main()
