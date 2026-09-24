from __future__ import annotations

import os
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QPoint
from PySide6.QtGui import QFont, QFontDatabase
from PySide6.QtWidgets import QApplication, QGroupBox, QPushButton, QWidget

from dc_modifier.legacy_tools import (
    AttributeCalculatorDialog,
    DamageMultiplierDialog,
    FontLibraryDialog,
    MapAnimationDialog,
    OtherSettingsDialog,
    SaveEditorDialog,
    TextConverterDialog,
    _glyph_file_offset,
    _glyph_pixmap,
)
from fc_editor.dc_text import reference_dc_text_table
from fc_editor.codecs.legacy_save import LegacySaveCodec, LegacySaveFormatError
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
        self.assertIn("点阵变化后即可写入", dialog.write_button.toolTip())
        self.assertEqual(dialog.replace_all_button.isEnabled(), self.project is not None)
        self._show(dialog)
        visible_buttons = {
            button.text()
            for button in dialog.findChildren(QPushButton)
            if button.isVisible()
        }
        self.assertEqual(
            visible_buttons,
            {"写入文字", "选择字体", "替换全部字体", "清空本页", "确定"},
        )
        self.assertFalse(dialog.import_page_button.isVisible())
        self.assertFalse(dialog.export_page_button.isVisible())
        self.assertFalse(hasattr(dialog, "cancel_button"))
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
        # The command editor keeps spare rows visible so a beginner can see
        # where structural insertion would occur.  The selected ROM record
        # itself still contains the verified 11 decoded commands.
        record = dialog.codec.record("map", 1)
        self.assertEqual(len(record.instructions), 11)
        self.assertGreaterEqual(dialog.instruction_table.rowCount(), len(record.instructions))
        self.assertIn("切换 00 区域图库", dialog.instruction_table.item(0, 0).text())
        self.assertEqual(dialog.instruction_table.item(0, 1).text(), "E0 0A")
        self.assertTrue(dialog.add_button.isEnabled())
        self.assertIn("预留槽", dialog.add_button.toolTip())
        self.assertTrue(dialog.code_button.isEnabled())
        self.assertIn("当前 ROM", dialog.read_only_status.text())
        self.assertEqual(dialog.rule_lists["movement"].count(), 157)
        self.assertEqual(dialog.rule_category_tabs.count(), 3)
        self.assertEqual(
            [
                dialog.rule_category_tabs.tabText(index)
                for index in range(dialog.rule_category_tabs.count())
            ],
            ["背景规律", "运行规律", "组图规律"],
        )
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
        self.assertIn("转换失败", dialog.last_status)
        self._show(dialog)
        visible_children = [
            widget
            for widget in dialog.findChildren(QWidget)
            if widget.parent() is dialog and widget.isVisible()
        ]
        self.assertEqual(len(visible_children), 6)
        self.assertEqual(
            sorted(type(widget).__name__ for widget in visible_children),
            ["QLabel", "QLabel", "QPlainTextEdit", "QPlainTextEdit", "QPushButton", "QPushButton"],
        )
        self.assertEqual(dialog.text_edit.placeholderText(), "")
        self.assertEqual(dialog.code_edit.placeholderText(), "")
        self.assertEqual(dialog.encode_button.size().toTuple(), (80, 32))
        self.assertEqual(dialog.decode_button.size().toTuple(), (80, 32))
        self.assertLess(self._top(dialog.text_edit, dialog), self._top(dialog.encode_button, dialog))
        self.assertLess(dialog.encode_button.mapTo(dialog, QPoint(0, 0)).x(), dialog.decode_button.mapTo(dialog, QPoint(0, 0)).x())
        self.assertLess(self._top(dialog.decode_button, dialog), self._top(dialog.code_edit, dialog))
        dialog.close()

    def test_text_converter_uses_all_nonempty_legacy_table_entries(self) -> None:
        source = ROOT / "src" / "resources" / "default_config" / "码表.ini"
        entries = []
        for line in source.read_text(encoding="gbk").splitlines():
            _address, code, value = line.split("=", 2)
            if code and value:
                entries.append((bytes.fromhex(code), value))
        table = reference_dc_text_table()
        self.assertEqual(len(entries), 2713)
        self.assertEqual(len(table.byte_to_text), 2713)
        for code, value in entries:
            self.assertEqual(table.byte_to_text.get(code), value, code.hex().upper())
            self.assertEqual(table.decode(code), value, code.hex().upper())
        self.assertEqual(table.decode(b"\xF2"), "\\")
        dialog = TextConverterDialog()
        dialog.code_edit.setPlainText("F1 F2 F6 F9")
        dialog.decode_button.click()
        self.assertEqual(dialog.text_edit.toPlainText(), "@\\】【")

    def test_text_converter_uses_project_local_font_assignment(self) -> None:
        if not ROM_PATH.is_file():
            self.skipTest("测试 ROM 不存在")
        project = RomProject.load(ROM_PATH)
        project.replace_font_character_overrides({bytes.fromhex("BAE3"): "龘"})
        dialog = TextConverterDialog(project=project)
        dialog.text_edit.setPlainText("龘")
        dialog.encode_button.click()
        self.assertEqual(dialog.code_edit.toPlainText(), "BA E3")
        dialog.text_edit.clear()
        dialog.decode_button.click()
        self.assertEqual(dialog.text_edit.toPlainText(), "龘")

    def test_attribute_calculator_uses_live_formula_and_legacy_result_lines(self) -> None:
        dialog = AttributeCalculatorDialog()
        dialog.enemy.strength.setValue(30)
        dialog.enemy.power_land.setValue(20)
        dialog.enemy.weapon_hit.setValue(70)
        dialog.enemy.speed.setValue(25)
        dialog.enemy.weapon_range.setValue(1)
        dialog.enemy.multiplier_numerator.setValue(3)
        dialog.enemy.multiplier_denominator.setValue(2)
        dialog.ally.defense.setValue(15)
        dialog.ally.speed.setValue(20)
        dialog.ally.hp.setValue(100)
        dialog.ally.terrain_value = 1
        dialog.ally.skill.setValue(0)
        dialog.calculate_button.click()
        self.assertEqual(dialog.last_results["敌方"].hit_score, 75)
        self.assertEqual(dialog.last_results["敌方"].minimum_hit_speed, 20)
        self.assertEqual(dialog.last_results["敌方"].predicted_damage, 66)
        self.assertEqual(dialog.last_results["敌方"].remaining_hp, 34)
        result_lines = [
            dialog.results.item(row).text() for row in range(dialog.results.count())
        ]
        self.assertIn("预计伤害计算：敌方 对 我方 造成预计伤害 66（对陆火力 20）", result_lines)
        self.assertTrue(any("计算结果： 可以命中" in line for line in result_lines))
        dialog.close()

    def test_attribute_calculator_opens_with_empty_lower_result_area(self) -> None:
        dialog = AttributeCalculatorDialog()
        self.assertEqual(dialog.results.count(), 0)
        self._show(dialog)
        self.assertLess(self._top(dialog.enemy, dialog), self._top(dialog.results, dialog))
        self.assertLess(self._top(dialog.results, dialog), self._top(dialog.calculate_button, dialog))
        dialog.close()

    def test_project_backed_calculator_populates_verified_records(self) -> None:
        if self.project is None:
            self.skipTest("测试ROM不存在")
        dialog = AttributeCalculatorDialog(project=self.project)
        self.assertEqual(dialog.enemy.unit.count(), self.project.unit_count - 1)
        self.assertEqual(dialog.enemy.character.count(), 200)
        self.assertEqual(dialog.enemy.unit.currentData(), 9)
        self.assertEqual(dialog.enemy.character.currentData(), 4)
        self.assertEqual(
            tuple(dialog.enemy.weapon.itemData(index) for index in range(dialog.enemy.weapon.count())),
            (7, 11),
        )
        self.assertEqual(dialog.enemy.weapon.currentData(), 7)
        unit = self.project.unit_codec.decode_record(
            int(dialog.enemy.unit.currentData()), bytes(self.project.working)
        )
        self.assertEqual(dialog.enemy.strength.value(), unit.get("strength"))
        self.assertEqual(dialog.enemy.hp.value(), unit.get("hp"))
        weapon = self.project.weapon_codec.decode_record(
            int(dialog.enemy.weapon.currentData()), bytes(self.project.working)
        )
        self.assertEqual(
            dialog.enemy.power_land.value(),
            weapon.get("power_land") * self.project.get_damage_formula_values()[1] + 8,
        )
        self.assertIn("人物属性", dialog.enemy.character_summary.text())
        dialog.close()

    def test_attribute_calculator_applies_level_growth_and_character_corrections(self) -> None:
        if self.project is None:
            self.skipTest("测试ROM不存在")
        dialog = AttributeCalculatorDialog(project=self.project)
        side = dialog.enemy
        unit_id = int(side.unit.currentData())
        base_strength = self.project.get_value(unit_id, "strength")
        side.level.setCurrentIndex(9)
        self.assertGreaterEqual(side.strength.value(), base_strength)
        self.assertLessEqual(side.strength.value(), 255)
        side.level.setCurrentIndex(59)
        self.assertLessEqual(side.strength.value(), 255)
        self.assertLessEqual(side.hp.value(), 9999)
        dialog.close()

    def test_attribute_calculator_enables_safe_transient_multiplier_editor(self) -> None:
        dialog = AttributeCalculatorDialog(project=self.project)
        for side in (dialog.enemy, dialog.ally):
            self.assertTrue(side.change_multiplier_button.isEnabled())
            self.assertIn("不写入 ROM", side.change_multiplier_button.toolTip())
            self.assertEqual(side.level.count(), 60)
        dialog.close()

    def test_damage_multiplier_dialog_clamps_and_returns_values(self) -> None:
        dialog = DamageMultiplierDialog(0, 120)
        self.assertEqual(dialog.values, (1, 99))
        dialog.numerator.setValue(3)
        dialog.denominator.setValue(2)
        self.assertEqual(dialog.values, (3, 2))
        dialog.close()

    def test_attribute_calculator_reads_changed_m17_parameters_without_writing_rom(self) -> None:
        if not ROM_PATH.is_file():
            self.skipTest("测试ROM不存在")
        project = RomProject.load(ROM_PATH)
        dialog = AttributeCalculatorDialog(project=project)
        before_calculation = bytes(project.working)
        raw_power = dialog.enemy._raw_weapon_powers[1]
        changed = list(project.get_damage_formula_values())
        changed[1] += 1
        project.set_damage_formula_values(changed)
        after_parameter_change = bytes(project.working)

        dialog.calculate()

        self.assertEqual(
            dialog.enemy.power_land.value(), raw_power * changed[1] + 8
        )
        self.assertEqual(bytes(project.working), after_parameter_change)
        self.assertNotEqual(before_calculation, after_parameter_change)
        dialog.close()

    def test_save_editor_keeps_reference_buttons_and_independent_title(self) -> None:
        dialog = SaveEditorDialog()
        self.assertEqual(dialog.windowTitle(), "存档编辑器：")
        self.assertTrue(dialog.open_button.isEnabled())
        self.assertTrue(dialog.read_button.isEnabled())
        self.assertTrue(dialog.write_button.isEnabled())
        self.assertTrue(dialog.save_button.isEnabled())
        self.assertEqual(dialog.ally_table.columnCount(), 11)
        self.assertEqual(dialog.enemy_table.columnCount(), 11)
        dialog.close()

    def test_save_editor_reads_stages_and_atomically_saves_verified_slot(self) -> None:
        dialog = SaveEditorDialog(project=self.project)
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "sample.sav"
            payload = bytearray(LegacySaveCodec.SAVE_SIZE)
            active = bytearray(LegacySaveCodec.SLOT_LENGTH)
            active[LegacySaveCodec.CHAPTER_OFFSET] = 4
            active[LegacySaveCodec.CHARACTER_OFFSET] = 4
            active[LegacySaveCodec.UNIT_OFFSET] = 9
            active[LegacySaveCodec.LEVEL_OFFSET] = 8
            active[LegacySaveCodec.EXP_LOW_OFFSET] = 0x34
            active[LegacySaveCodec.EXP_HIGH_OFFSET] = 0x12
            payload[
                LegacySaveCodec.ACTIVE_OFFSET : LegacySaveCodec.ACTIVE_OFFSET
                + LegacySaveCodec.SLOT_LENGTH
            ] = active
            slot_offset = LegacySaveCodec.SLOT_DATA_OFFSETS[0]
            checksum_offset = LegacySaveCodec.SLOT_CHECKSUM_OFFSETS[0]
            payload[slot_offset : slot_offset + LegacySaveCodec.SLOT_LENGTH] = active
            payload[checksum_offset : checksum_offset + 2] = (
                LegacySaveCodec.checksum(active).to_bytes(2, "little")
            )
            payload = bytes(payload)
            path.write_bytes(payload)
            dialog.load_path(path)
            dialog.read_button.click()
            self.assertEqual(dialog.save_bytes, payload)
            self.assertIn("有效槽 1/3", dialog.status.text())
            self.assertEqual(dialog.ally_table.item(0, 1).text().split()[0], "$04")
            self.assertEqual(dialog.ally_table.item(0, 2).text().split()[0], "$09")
            dialog.ally_table.item(0, 9).setText("1000")
            self.assertTrue(dialog._table_draft)
            dialog.write_button.click()
            self.assertTrue(dialog._staged)
            self.assertEqual(path.read_bytes(), payload)
            staged = LegacySaveCodec.decode(dialog.save_bytes)
            self.assertTrue(staged.slots[0].checksum_valid)
            self.assertEqual(staged.slots[0].roster[0].experience, 1000)
            dialog.slot_selector.setCurrentIndex(1)
            dialog.read_button.click()
            self.assertTrue(dialog._staged)
            self.assertEqual(
                LegacySaveCodec.decode(dialog.save_bytes).slots[0].roster[0].experience,
                1000,
            )
            dialog.slot_selector.setCurrentIndex(0)
            dialog.read_button.click()
            self.assertEqual(dialog.ally_table.item(0, 9).text(), "1000")
            dialog.save_button.click()
            self.assertFalse(dialog._staged)
            self.assertEqual(path.read_bytes(), dialog.save_bytes)
            self.assertIsNotNone(dialog.last_backup_path)
            self.assertEqual(dialog.last_backup_path.read_bytes(), payload)
            self._show(dialog)
            self.assertLess(self._top(dialog.ally_table, dialog), self._top(dialog.enemy_table, dialog))
        dialog.close()

    def test_save_editor_does_not_silently_drop_an_unwritten_table_draft(self) -> None:
        dialog = SaveEditorDialog(project=self.project)
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "sample.sav"
            payload = bytearray(LegacySaveCodec.SAVE_SIZE)
            active = bytearray(LegacySaveCodec.SLOT_LENGTH)
            active[LegacySaveCodec.CHAPTER_OFFSET] = 4
            active[LegacySaveCodec.CHARACTER_OFFSET] = 4
            active[LegacySaveCodec.UNIT_OFFSET] = 9
            active[LegacySaveCodec.LEVEL_OFFSET] = 8
            slot_offset = LegacySaveCodec.SLOT_DATA_OFFSETS[0]
            checksum_offset = LegacySaveCodec.SLOT_CHECKSUM_OFFSETS[0]
            payload[slot_offset : slot_offset + LegacySaveCodec.SLOT_LENGTH] = active
            payload[checksum_offset : checksum_offset + 2] = (
                LegacySaveCodec.checksum(active).to_bytes(2, "little")
            )
            path.write_bytes(payload)
            dialog.load_path(path)
            dialog.read_save()
            dialog.ally_table.item(0, 9).setText("123")
            dialog.read_save()
            self.assertEqual(dialog.ally_table.item(0, 9).text(), "123")
            self.assertIn("未写入内存", dialog.status.text())
        dialog._table_draft = False
        dialog.close()

    def test_save_editor_only_derives_enemy_unit_from_a_unique_rom_match(self) -> None:
        data = bytearray(LegacySaveCodec.SAVE_SIZE)
        data[LegacySaveCodec.ACTIVE_OFFSET + LegacySaveCodec.CHAPTER_OFFSET] = 4
        layout = LegacySaveCodec._BATTLE_LAYOUT["enemy"]
        base = LegacySaveCodec.ACTIVE_OFFSET
        data[base + layout["character"]] = 0x2F
        data[base + layout["level"]] = 12
        document = LegacySaveCodec.decode(data)

        class Project:
            def __init__(self, enemies) -> None:
                self.enemies = enemies

            def get_scenario_layout(self, _map_id):
                return SimpleNamespace(enemies=self.enemies)

        matching = SimpleNamespace(pilot_id=0x2F, level=12, unit_id=9)
        duplicate = SimpleNamespace(pilot_id=0x2F, level=12, unit_id=10)
        dialog = SaveEditorDialog(project=Project([matching, duplicate]))
        self.assertIsNone(dialog._resolve_enemy_units_for_active(document)[0])
        dialog.project = Project([matching])
        self.assertEqual(dialog._resolve_enemy_units_for_active(document)[0], 9)
        dialog.close()

    def test_save_editor_rejects_non_8k_files_before_reading(self) -> None:
        dialog = SaveEditorDialog()
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "bad.sav"
            path.write_bytes(bytes(256))
            with self.assertRaisesRegex(LegacySaveFormatError, "8192"):
                dialog.load_path(path)
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
            ("converter", TextConverterDialog(), (473, 483)),
            ("calculator", AttributeCalculatorDialog(), (920, 650)),
        )
        additional_flexible_dialogs = (
            ("save", SaveEditorDialog(), (950, 650)),
            ("other", OtherSettingsDialog(), (820, 620)),
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
            for name, dialog, expected in additional_flexible_dialogs:
                with self.subTest(dialog=name):
                    self.assertLess(dialog.minimumWidth(), dialog.maximumWidth())
                    self.assertLess(dialog.minimumHeight(), dialog.maximumHeight())
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
        result = dialog.calculate_attack(
            dialog.enemy, dialog.ally
        )
        self.assertEqual(result.hit_score, 0)
        self.assertEqual(result.minimum_hit_speed, 100)
        dialog.calculate()
        self.assertTrue(
            any(
                "命中最低速度计算：速度至少大于 99 才能命中"
                in dialog.results.item(row).text()
                for row in range(dialog.results.count())
            )
        )
        dialog.close()


if __name__ == "__main__":
    unittest.main()
