from __future__ import annotations

import os
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

from dc_modifier.legacy_tools import AttributeCalculatorDialog
from dc_modifier.legacy_windows import DatabaseDialog
from dc_modifier.rom_data_browser import (
    RomDataBrowserDialog,
    build_animation_sheet,
    build_character_sheet,
    build_event_sheet,
    build_map_sheet,
    build_text_sheet,
    build_unit_sheet,
    build_weapon_sheet,
)
from fc_rom_editor_core import RomProject
from tests.qt_test_case import QtTestCase


ROOT = Path(__file__).resolve().parents[1]
ROM = ROOT / "output" / "rom" / "DC_kuorong_464K.nes"


class RomDataBrowserTests(QtTestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.application = QApplication.instance() or QApplication([])
        cls.project = RomProject.load(ROM)

    def test_every_verified_table_is_indexed_with_raw_bytes(self) -> None:
        sheets = (
            build_unit_sheet(self.project),
            build_character_sheet(self.project),
            build_weapon_sheet(self.project),
            build_map_sheet(self.project),
            build_text_sheet(self.project),
            build_animation_sheet(self.project),
            build_event_sheet(self.project),
        )
        self.assertEqual(
            tuple(len(sheet.rows) for sheet in sheets),
            (255, 199, 254, 100, 1258, 1177, 6911),
        )
        self.assertEqual(sheets[0].rows[0][4], "08 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00")
        self.assertEqual(sheets[0].rows[1][4], "18 00 00 08 3C 84 36 82 90 01 64 00 02 CA 02 0A")
        self.assertEqual(sheets[1].rows[3][5], "21 C9 A0 00 08 00")
        self.assertEqual(len(bytes.fromhex(sheets[2].rows[0][3])), 6)
        self.assertTrue(sheets[3].rows[0][4])
        self.assertTrue(any(row[0] == "分Bank关卡脚本" for row in sheets[6].rows))

    def test_browser_exposes_structured_pages_and_every_rom_byte(self) -> None:
        dialog = RomDataBrowserDialog(self.project)
        self.assertEqual(dialog.tabs.count(), 8)
        self.assertIn(f"{len(self.project.working):,}", dialog.summary.text())
        offset = self.project.record_file_offset(2) + 4
        dialog.show_offset(offset)
        self.assertIs(dialog.tabs.currentWidget(), dialog.hex_page)
        row = (offset & 0xFF) // 16
        column = offset & 0x0F
        self.assertEqual(
            dialog.hex_page.table.item(row, column).text(),
            f"{self.project.working[offset]:02X}",
        )
        self.assertIn(f"0x{offset:06X}", dialog.hex_page.detail.text())
        dialog.reject()

    def test_database_opens_on_populated_records_and_keeps_raw_zero_records_available(self) -> None:
        dialog = DatabaseDialog(self.project)
        self.assertEqual(dialog.unit_page.current_id, 9)
        self.assertEqual(dialog.character_page.current_id, 4)
        self.assertEqual(dialog.unit_page.fields["strength"].value(), 98)
        self.assertIn("00 10 00 07", dialog.unit_page.raw_unit_record.text())
        self.assertIn("21 C9 A0 00 08 00", dialog.character_page.character_details.raw_details.text())
        dialog.unit_page.records.setCurrentRow(0)
        self.assertEqual(dialog.unit_page.current_id, 1)
        self.assertTrue(dialog.unit_page.raw_unit_record.text().endswith("00 00 00 00"))
        dialog.reject()

    def test_attribute_calculator_loads_character_unit_and_weapon_values(self) -> None:
        dialog = AttributeCalculatorDialog(project=self.project)
        for side in (dialog.enemy, dialog.ally):
            self.assertEqual(side.character.currentData(), 4)
            self.assertEqual(side.unit.currentData(), 2)
            self.assertEqual(side.weapon.currentData(), 1)
            self.assertEqual(side.strength.value(), 132)
            self.assertEqual(side.skill.value(), self.project.get_value(2, "special"))
            self.assertIn("21 C9 A0 00 08 00", side.character_summary.text())
            self.assertIn("武器特技", side.weapon_summary.text())
        dialog.reject()
