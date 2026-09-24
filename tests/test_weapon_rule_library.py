from __future__ import annotations

import os
from pathlib import Path
import tempfile
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

    def test_hidden_prefix_can_be_included_for_complete_inspection(self) -> None:
        table = WEAPON_RULE_TABLES[0]
        offset, visible, aliases = self.catalog.record(table, 1)
        full_offset, complete, full_aliases = self.catalog.record(
            table, 1, include_hidden=True
        )
        self.assertEqual(full_offset, offset)
        self.assertEqual(full_aliases, aliases)
        self.assertEqual(complete[table.hidden_prefix:], visible)
        self.assertEqual(len(complete), len(visible) + table.hidden_prefix)


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
        self.assertFalse(dialog.names["weapon_beam"].isReadOnly())

    def test_search_complete_copy_and_full_page_export_text(self) -> None:
        project = RomProject.load(DEFAULT_ROM)
        dialog = WeaponRuleLibraryDialog(project)
        self.addCleanup(dialog.deleteLater)
        table = WEAPON_RULE_TABLES[0]

        dialog.searches[table.key].setText("2")
        dialog._find_next(table)
        self.assertEqual(dialog.lists[table.key].currentRow(), 1)

        visible = dialog.codes[table.key].toPlainText()
        dialog.complete_checks[table.key].setChecked(True)
        complete = dialog.codes[table.key].toPlainText()
        self.assertGreater(len(complete), len(visible))
        self.assertIn("完整记录", dialog.statuses[table.key].text())

        dialog._copy_current(table)
        copied = QApplication.clipboard().text()
        self.assertIn("光束组图规律 $02", copied)
        self.assertIn("文件地址：0x", copied)
        self.assertIn("代码：", copied)

        exported = dialog._all_text(table)
        self.assertIn("# 记录数：255", exported)
        self.assertIn("$EF\t指针:$A0A5", exported)
        self.assertIn("保留/控制项", exported)
        self.assertEqual(
            len([line for line in exported.splitlines() if line.startswith("$")]),
            table.count,
        )

        dialog.lists[table.key].setCurrentRow(0xEF - 1)
        self.assertEqual(dialog.codes[table.key].toPlainText(), "")
        self.assertIn("保留/控制项", dialog.statuses[table.key].text())

    def test_weapon_rule_name_accept_cancel_undo_and_project_reopen(self) -> None:
        project = RomProject.load(DEFAULT_ROM)
        cancelled = WeaponRuleLibraryDialog(project)
        self.addCleanup(cancelled.deleteLater)
        cancelled.names["weapon_beam"].setText("取消名称")
        cancelled.names["weapon_beam"].textEdited.emit("取消名称")
        cancelled.reject()
        self.assertFalse(project.animation_label_overrides)

        dialog = WeaponRuleLibraryDialog(project)
        self.addCleanup(dialog.deleteLater)
        dialog.names["weapon_beam"].setText("光束测试名称")
        dialog.names["weapon_beam"].textEdited.emit("光束测试名称")
        dialog.accept()
        self.assertEqual(
            project.animation_label_overrides[("weapon_beam", 1)],
            "光束测试名称",
        )
        self.assertTrue(project.can_undo)

        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "weapon-rule-name.dcmod"
            project.save_project(path)
            reopened = RomProject.load_project(path, DEFAULT_ROM)
        self.assertEqual(
            reopened.animation_label_overrides[("weapon_beam", 1)],
            "光束测试名称",
        )
        project.undo()
        self.assertFalse(project.animation_label_overrides)


if __name__ == "__main__":
    unittest.main()
