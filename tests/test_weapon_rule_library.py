from __future__ import annotations

import os
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

from dc_modifier.app import DEFAULT_ROM
from dc_modifier.weapon_rule_library import (
    WEAPON_RULE_TABLES,
    WeaponRuleCatalog,
    WeaponRuleLibraryDialog,
)
from fc_rom_editor_core import RomProject
from tests.qt_test_case import QtTestCase


class WeaponRuleCatalogTests(unittest.TestCase):
    def setUp(self) -> None:
        self.project = RomProject.load(DEFAULT_ROM)
        self.catalog = WeaponRuleCatalog(self.project.working)

    def test_four_reference_tables_have_verified_counts_and_first_codes(self) -> None:
        self.assertEqual(
            tuple(table.count for table in WEAPON_RULE_TABLES),
            (255, 252, 250, 255),
        )
        expected = (
            "FD 20 20 F8 FF 00 FF",
            "00 83 F0 FC 00 83 F0 FC",
            "00 83 F0 FC 00 83 F0 FC",
            "01 00 00 08 F0 00 00 00 28 04 E8 80 80 80 A8 01 E8 80 80 80 FF",
        )
        for table, code in zip(WEAPON_RULE_TABLES, expected, strict=True):
            _offset, raw, _aliases = self.catalog.record(table, 1)
            self.assertEqual(raw.hex(" ").upper(), code)

    def test_invalid_pointer_signature_fails_closed(self) -> None:
        broken = bytearray(self.project.working)
        broken[WEAPON_RULE_TABLES[0].pointer_table + 2] ^= 1
        with self.assertRaisesRegex(ValueError, "指针表"):
            WeaponRuleCatalog(broken)


class WeaponRuleLibraryUiTests(QtTestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = QApplication.instance() or QApplication([])

    def test_dialog_exposes_four_independent_reference_tabs(self) -> None:
        project = RomProject.load(DEFAULT_ROM)
        dialog = WeaponRuleLibraryDialog(project)
        self.addCleanup(dialog.deleteLater)
        self.assertEqual(
            [dialog.tabs.tabText(index) for index in range(dialog.tabs.count())],
            ["光束组图规律", "物理运行规律1", "物理运行规律2", "物理图片"],
        )
        self.assertEqual(
            [dialog.lists[table.key].count() for table in WEAPON_RULE_TABLES],
            [255, 252, 250, 255],
        )
        self.assertIn("FD 20 20", dialog.codes["weapon_beam"].toPlainText())
        self.assertTrue(dialog.codes["weapon_beam"].isReadOnly())


if __name__ == "__main__":
    unittest.main()
