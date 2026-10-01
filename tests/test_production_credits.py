from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication, QDialogButtonBox

from dc_modifier.app import DEFAULT_ROM
from dc_modifier.production_credits_editor import ProductionCreditsDialog
from fc_editor.codecs.dc_font import font_reference_counts
from fc_editor.codecs.production_credits import (
    CAST_RECORD_END,
    CAST_RECORD_START,
    PRODUCTION_RECORD_END,
    PRODUCTION_RECORD_START,
    ProductionCreditsCodec,
)
from fc_editor.dc_text import reference_dc_text_table
from fc_rom_editor_core import RomProject
from tests.qt_test_case import QtTestCase


class ProductionCreditsCodecTests(unittest.TestCase):
    def setUp(self) -> None:
        self.data = DEFAULT_ROM.read_bytes()
        self.codec = ProductionCreditsCodec(self.data)
        self.table = reference_dc_text_table()

    def test_verified_records_decode_without_exposing_binary_prefix(self) -> None:
        production, cast = self.codec.records(text_table=self.table)
        self.assertEqual(production.capacity, 75)
        self.assertEqual(cast.capacity, 109)
        self.assertIn("作者：零", production.text)
        self.assertIn("出演", cast.text)
        self.assertIn("盖塔   太勒", cast.text)

    def test_same_text_round_trip_has_no_patch(self) -> None:
        production, cast = self.codec.records(text_table=self.table)
        self.assertEqual(
            self.codec.replacement_patches(
                self.data,
                production.text,
                cast.text,
                text_table=self.table,
            ),
            (),
        )

    def test_shorter_cast_is_padded_without_moving_adjacent_data(self) -> None:
        production, cast = self.codec.records(text_table=self.table)
        patches = self.codec.replacement_patches(
            self.data,
            production.text,
            cast.text.replace("太勒", "太"),
            text_table=self.table,
        )
        self.assertEqual(len(patches), 1)
        offset, before, after = patches[0]
        self.assertEqual(offset, CAST_RECORD_START)
        self.assertEqual(len(before), CAST_RECORD_END - CAST_RECORD_START)
        self.assertEqual(len(after), len(before))
        changed = bytearray(self.data)
        changed[offset:offset + len(after)] = after
        self.assertEqual(changed[:CAST_RECORD_START], self.data[:CAST_RECORD_START])
        self.assertEqual(changed[CAST_RECORD_END:], self.data[CAST_RECORD_END:])
        self.assertNotIn("勒", ProductionCreditsCodec(changed).records(text_table=self.table)[1].text)

    def test_over_capacity_is_rejected(self) -> None:
        _production, cast = self.codec.records(text_table=self.table)
        with self.assertRaisesRegex(ValueError, "固定容量"):
            self.codec.replacement_patches(
                self.data,
                "\n".join(("第" * 18,) * 3),
                cast.text,
                text_table=self.table,
            )

    def test_scroll_layout_rejects_extra_lines_and_overwide_rows(self) -> None:
        production, cast = self.codec.records(text_table=self.table)
        with self.assertRaisesRegex(ValueError, "最多 3 行"):
            self.codec.replacement_patches(
                self.data,
                "一\n二\n三\n四",
                cast.text,
                text_table=self.table,
            )
        with self.assertRaisesRegex(ValueError, "每行最多 10 个显示格"):
            self.codec.replacement_patches(
                self.data,
                production.text,
                "一" * 11,
                text_table=self.table,
            )

    def test_binary_prefix_and_suffix_are_outside_writable_records(self) -> None:
        self.assertLess(PRODUCTION_RECORD_START, PRODUCTION_RECORD_END)
        self.assertLess(PRODUCTION_RECORD_END, CAST_RECORD_START)
        production, cast = self.codec.records(text_table=self.table)
        patches = self.codec.replacement_patches(
            self.data,
            production.text.replace("零", "无"),
            cast.text,
            text_table=self.table,
        )
        self.assertEqual(patches[0][0], production.payload_start)
        self.assertGreater(patches[0][0], PRODUCTION_RECORD_START)


class ProductionCreditsProjectAndUiTests(QtTestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.application = QApplication.instance() or QApplication([])

    def setUp(self) -> None:
        self.project = RomProject.load(DEFAULT_ROM)
        self.dialogs = []

    def tearDown(self) -> None:
        for dialog in self.dialogs:
            dialog.hide()
            dialog.deleteLater()
        self.application.processEvents()

    def test_project_edit_removes_reference_and_undo_restores_it(self) -> None:
        before = bytes(self.project.working)
        production, cast = self.project.get_production_credits()
        self.project.set_production_credits(
            production.text,
            cast.text.replace("太勒", "太"),
        )
        self.assertEqual(font_reference_counts(self.project.working).get(bytes.fromhex("C9F3"), 0), 0)
        self.assertNotIn("勒", self.project.get_production_credits()[1].text)
        self.assertTrue(self.project.undo())
        self.assertEqual(bytes(self.project.working), before)

    def test_edited_text_survives_derived_rom_save_and_reopen(self) -> None:
        production, cast = self.project.get_production_credits()
        expected_production = production.text.replace("470351839", "470351830")
        expected_cast = cast.text.replace("太勒", "太")
        self.project.set_production_credits(expected_production, expected_cast)

        with tempfile.TemporaryDirectory() as folder:
            derived_rom = Path(folder) / "production-credits-derived.nes"
            derived_rom.write_bytes(bytes(self.project.working))
            reopened = RomProject.load(derived_rom)

        reopened_production, reopened_cast = reopened.get_production_credits()
        self.assertEqual(reopened_production.text, expected_production)
        self.assertEqual(reopened_cast.text, expected_cast)

    def test_dialog_has_two_editors_live_capacity_and_preview(self) -> None:
        dialog = ProductionCreditsDialog(project=self.project)
        self.dialogs.append(dialog)
        self.assertEqual(
            dialog.production_counter.text(),
            "75/75 字节｜3/3 行｜最长 18/18 格",
        )
        self.assertEqual(
            dialog.cast_counter.text(),
            "109/109 字节｜11/11 行｜最长 10/10 格",
        )
        self.assertIn("太勒", dialog.cast_preview.toPlainText())
        dialog.cast_edit.setPlainText("第" * 100)
        self.application.processEvents()
        self.assertFalse(
            dialog.buttons.button(QDialogButtonBox.StandardButton.Ok).isEnabled()
        )

    def test_deferred_dialog_stages_text_without_mutating_project(self) -> None:
        before = bytes(self.project.working)
        production, cast = self.project.get_production_credits()
        dialog = ProductionCreditsDialog(
            project=self.project,
            defer_apply=True,
        )
        self.dialogs.append(dialog)
        dialog.cast_edit.setPlainText(cast.text.replace("太勒", "太"))
        dialog.apply_and_accept()
        self.assertEqual(bytes(self.project.working), before)
        self.assertEqual(
            dialog.edited_texts,
            (production.text, cast.text.replace("太勒", "太")),
        )

