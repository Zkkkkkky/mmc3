from __future__ import annotations

import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import Qt
from PySide6.QtGui import QFont
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QDialog, QMessageBox

from dc_modifier.app import DEFAULT_ROM
from dc_modifier.legacy_tools import FontLibraryDialog
from fc_editor.codecs.dc_font import (
    FULL_FONT_PAYLOAD_SIZE,
    PAGE_PAYLOAD_SIZE,
    decode_full_font_file,
    encode_full_font_file,
    font_tokens,
    glyph_file_offset,
    page_tokens,
    safe_unmapped_tokens,
)
from fc_rom_editor_core import RomProject


from tests.qt_test_case import QtTestCase


class FontEditTransactionTests(QtTestCase):
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

    def dialog(self, *, no_project: bool = False) -> FontLibraryDialog:
        dialog = FontLibraryDialog(project=None if no_project else self.project)
        self.dialogs.append(dialog)
        return dialog

    @staticmethod
    def paint_changed(dialog: FontLibraryDialog) -> bytes:
        raw = bytes(value ^ 0xFF for value in dialog._raw_glyph(dialog.current_token))
        dialog.glyph_canvas.load(raw)
        dialog.glyph_canvas.changed.emit()
        return raw

    def test_page_switch_stages_previous_page_glyph_without_rebinding_token(self) -> None:
        dialog = self.dialog()
        dialog._select_cell(2, 8)
        token = dialog.current_token
        expected = self.paint_changed(dialog)
        before = bytes(self.project.working)
        dialog.page_selector.setCurrentIndex(dialog.page_selector.findData(0xC9))
        self.assertEqual(dialog._glyph_drafts[token], expected)
        self.assertEqual(dialog.current_token, bytes.fromhex("C900"))
        self.assertFalse(dialog.write_button.isEnabled())
        self.assertEqual(bytes(self.project.working), before)
        dialog.accept()
        offset = glyph_file_offset(token)
        self.assertEqual(bytes(self.project.working[offset:offset + 18]), expected)
        self.assertEqual(self.project.working[:offset], before[:offset])
        self.assertEqual(self.project.working[offset + 18:], before[offset + 18:])

    def test_keyboard_selection_updates_actual_glyph_target(self) -> None:
        dialog = self.dialog()
        dialog.glyph_table.setCurrentCell(1, 5)
        self.assertEqual(dialog.current_token, bytes.fromhex("C815"))
        QTest.keyClick(dialog.glyph_table, Qt.Key.Key_Right)
        self.assertEqual(dialog.glyph_table.currentColumn(), 6)
        self.assertEqual(dialog.current_token, bytes.fromhex("C816"))

    def test_staging_old_glyph_during_selection_keeps_new_highlight_aligned(self) -> None:
        dialog = self.dialog()
        dialog.glyph_table.setCurrentCell(2, 8)
        token = dialog.current_token
        pending = self.paint_changed(dialog)
        dialog.glyph_table.setCurrentCell(3, 4)
        self.assertEqual(dialog._glyph_drafts[token], pending)
        self.assertEqual(dialog.current_token, bytes.fromhex("C834"))
        self.assertEqual(dialog.glyph_table.currentRow(), 3)
        self.assertEqual(dialog.glyph_table.currentColumn(), 4)

    def test_current_unstaged_glyph_detects_concurrent_commit(self) -> None:
        dialog = self.dialog()
        token = dialog.current_token
        original = dialog._raw_glyph(token)
        pending = self.paint_changed(dialog)
        concurrent = bytes((original[0] ^ 1, *original[1:]))
        self.project.set_font_glyphs({token: concurrent})
        before = bytes(self.project.working)
        with patch("dc_modifier.font_edit.QMessageBox.warning") as warning:
            dialog.accept()
        warning.assert_called_once()
        self.assertNotEqual(dialog.result(), QDialog.DialogCode.Accepted)
        self.assertEqual(bytes(self.project.working), before)
        self.assertEqual(dialog._glyph_drafts[token], pending)
        dialog.reject()
        self.assertFalse(dialog._glyph_drafts)
        self.assertEqual(bytes(self.project.working), before)

    def test_cancel_never_rolls_back_another_edit_and_reuse_cannot_resurrect_draft(self) -> None:
        dialog = self.dialog()
        self.paint_changed(dialog)
        dialog.stage_current_glyph()
        other = bytes.fromhex("C808")
        original = dialog._raw_glyph(other)
        changed = bytes((original[0] ^ 1, *original[1:]))
        self.project.set_font_glyphs({other: changed})
        before = bytes(self.project.working)
        dialog.reject()
        self.assertFalse(dialog.write_button.isEnabled())
        self.assertFalse(dialog._glyph_drafts)
        dialog.accept()
        self.assertEqual(bytes(self.project.working), before)

    def test_alias_cells_show_canonical_draft_but_cannot_be_written(self) -> None:
        dialog = self.dialog()
        dialog._select_cell(3, 0)
        token = dialog.current_token
        pending = self.paint_changed(dialog)
        dialog._select_cell(3, 14)
        self.assertEqual(dialog._glyph_drafts[token], pending)
        self.assertEqual(dialog._raw_glyph(bytes.fromhex("C83E")), pending)
        self.assertEqual(dialog._raw_glyph(bytes.fromhex("C83F")), pending)
        self.assertFalse(dialog.glyph_canvas.isEnabled())
        self.assertFalse(dialog.write_button.isEnabled())
        self.assertFalse(dialog.replacement_text.isEnabled())
        self.assertEqual(dialog.glyph_canvas.raw(), pending)

    def test_no_project_has_no_mutating_actions_and_accept_is_safe(self) -> None:
        dialog = self.dialog(no_project=True)
        self.assertFalse(dialog.glyph_canvas.isEnabled())
        self.assertFalse(dialog.import_page_button.isEnabled())
        self.assertFalse(dialog.export_page_button.isEnabled())
        with patch("dc_modifier.font_edit.QMessageBox.question") as question:
            dialog.clear_font_page()
            dialog.replace_font_page()
            dialog.import_font_page()
            dialog.export_font_page()
        question.assert_not_called()
        dialog.accept()
        self.assertEqual(dialog.result(), QDialog.DialogCode.Accepted)

    def test_export_contains_unstaged_current_pixels_without_committing_project(self) -> None:
        dialog = self.dialog()
        token = dialog.current_token
        pending = self.paint_changed(dialog)
        before = bytes(self.project.working)
        with tempfile.TemporaryDirectory() as directory:
            filename = Path(directory) / "glyph-page"
            with patch("dc_modifier.font_edit.QFileDialog.getSaveFileName", return_value=(str(filename), "")):
                dialog.export_font_page()
            raw = filename.with_suffix(".dcfont").read_bytes()
        self.assertEqual(len(raw), PAGE_PAYLOAD_SIZE)
        index = page_tokens(token[0]).index(token)
        self.assertEqual(raw[index * 18:(index + 1) * 18], pending)
        self.assertEqual(bytes(self.project.working), before)
        dialog.reject()
        self.assertEqual(bytes(self.project.working), before)

    def test_import_rejects_wrong_size_and_preserves_canvas_draft(self) -> None:
        dialog = self.dialog()
        pending = self.paint_changed(dialog)
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "bad.dcfont"
            path.write_bytes(bytes(PAGE_PAYLOAD_SIZE + 1))
            with patch("dc_modifier.font_edit.QFileDialog.getOpenFileName", return_value=(str(path), "")), patch("dc_modifier.font_edit.QMessageBox.warning") as warning:
                dialog.import_font_page()
        warning.assert_called_once()
        self.assertEqual(dialog.glyph_canvas.raw(), pending)
        self.assertTrue(dialog.write_button.isEnabled())
        self.assertFalse(dialog._glyph_drafts)

    def test_import_page_excludes_aliases_and_row_padding_and_is_one_undo(self) -> None:
        dialog = self.dialog()
        before = bytes(self.project.working)
        payload = bytes(index % 256 for index in range(PAGE_PAYLOAD_SIZE))
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "page.dcfont"
            path.write_bytes(payload)
            with patch("dc_modifier.font_edit.QFileDialog.getOpenFileName", return_value=(str(path), "")), patch("dc_modifier.font_edit.QMessageBox.question", return_value=QMessageBox.StandardButton.Yes):
                dialog.import_font_page()
        self.assertEqual(bytes(self.project.working), before)
        dialog.accept()
        for index, token in enumerate(page_tokens(0xC8)):
            offset = glyph_file_offset(token)
            self.assertEqual(bytes(self.project.working[offset:offset + 18]), payload[index * 18:(index + 1) * 18])
        for row in range(16):
            padding = 0x70010 + row * 256 + 252
            self.assertEqual(self.project.working[padding:padding + 4], before[padding:padding + 4])
        self.project.undo()
        self.assertEqual(bytes(self.project.working), before)

    def test_pyside_font_chooser_keeps_return_order_and_forces_pixel_size(self) -> None:
        dialog = self.dialog()
        font = QFont("Test Font", 36)
        with patch("dc_modifier.font_edit.QFontDialog.getFont", return_value=(True, font)), patch.object(dialog, "preview_font_character") as preview:
            dialog.choose_font()
        self.assertEqual(dialog._font.family(), "Test Font")
        self.assertEqual(dialog._font.pixelSize(), 12)
        preview.assert_called_once_with(dialog.replacement_text.text())

    def test_invalid_batch_cannot_partially_change_core_or_dialog_drafts(self) -> None:
        dialog = self.dialog()
        batch = {bytes.fromhex("C800"): bytes(18), bytes.fromhex("C801"): bytes(17)}
        before = bytes(self.project.working)
        with self.assertRaises(ValueError):
            self.project.set_font_glyphs(batch)
        self.assertEqual(bytes(self.project.working), before)
        self.assertFalse(self.project.can_undo)
        with self.assertRaises(ValueError):
            dialog._stage_glyphs(batch)
        self.assertFalse(dialog._glyph_drafts)

    def test_safe_auto_allocation_is_transactional_persistent_and_undoable(self) -> None:
        dialog = self.dialog()
        candidates = safe_unmapped_tokens(
            bytes(self.project.working),
            set(dialog.text_table.byte_to_text),
        )
        self.assertEqual(len(candidates), 76)
        self.assertEqual(candidates[0], bytes.fromhex("BAE3"))
        glyph = bytes(range(18))
        before = bytes(self.project.working)
        with patch(
            "dc_modifier.font_edit.QInputDialog.getText",
            return_value=("龘", True),
        ), patch.object(dialog, "_render_character", return_value=glyph):
            dialog.allocate_new_character()
        token = bytes.fromhex("BAE3")
        self.assertEqual(dialog._font_mapping_drafts[token], "龘")
        self.assertEqual(dialog._glyph_drafts[token], glyph)
        self.assertEqual(bytes(self.project.working), before)
        self.assertFalse(self.project.font_character_overrides)

        dialog.accept()
        self.assertEqual(self.project.font_character_overrides, {token: "龘"})
        self.assertEqual(self.project.dc_text_table().encode("龘"), token)
        offset = glyph_file_offset(token, writable=True)
        self.assertEqual(bytes(self.project.working[offset:offset + 18]), glyph)
        self.project.undo()
        self.assertFalse(self.project.font_character_overrides)
        self.assertEqual(bytes(self.project.working), before)
        self.project.redo()
        self.assertEqual(self.project.font_character_overrides, {token: "龘"})
        self.assertEqual(bytes(self.project.working[offset:offset + 18]), glyph)

        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "font-mapping.dcmod"
            self.project.save_project(path)
            reopened = RomProject.load_project(path, DEFAULT_ROM)
        self.assertEqual(reopened.font_character_overrides, {token: "龘"})
        self.assertEqual(reopened.dc_text_table(reference=True).encode("龘"), token)
        self.assertEqual(bytes(reopened.working[offset:offset + 18]), glyph)

    def test_full_font_file_roundtrip_is_deterministic_and_strict(self) -> None:
        glyphs = {
            token: bytes(self.project.working[
                glyph_file_offset(token, writable=True):
                glyph_file_offset(token, writable=True) + 18
            ])
            for token in font_tokens()
        }
        mappings = {bytes.fromhex("BAE3"): "龘"}
        raw = encode_full_font_file(glyphs, mappings)
        decoded_glyphs, decoded_mappings = decode_full_font_file(raw)
        self.assertEqual(decoded_glyphs, glyphs)
        self.assertEqual(decoded_mappings, mappings)
        self.assertEqual(
            len(raw),
            18 + FULL_FONT_PAYLOAD_SIZE + len('{"BAE3":"龘"}'.encode("utf-8")),
        )
        self.assertEqual(raw, encode_full_font_file(decoded_glyphs, decoded_mappings))
        with self.assertRaisesRegex(ValueError, "长度"):
            decode_full_font_file(raw + b"\x00")

    def test_full_font_import_is_one_atomic_undo_and_preserves_padding(self) -> None:
        dialog = self.dialog()
        glyphs = {
            token: bytes(self.project.working[
                glyph_file_offset(token, writable=True):
                glyph_file_offset(token, writable=True) + 18
            ])
            for token in font_tokens()
        }
        token = bytes.fromhex("BAE3")
        glyphs[token] = bytes(range(18))
        mappings = {token: "龘"}
        raw = encode_full_font_file(glyphs, mappings)
        before = bytes(self.project.working)
        padding = {
            offset: before[offset:offset + 4]
            for lead in (0xB8, 0xB9, 0xBA, 0xBB, 0xC8, 0xC9, 0xCA, 0xCB, 0xD8, 0xD9, 0xDA, 0xDB)
            for row in range(16)
            for offset in (glyph_file_offset(bytes((lead, row * 16)), writable=True) + 252,)
        }
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "all.dcfontset"
            path.write_bytes(raw)
            with patch(
                "dc_modifier.font_edit.QFileDialog.getOpenFileName",
                return_value=(str(path), ""),
            ), patch(
                "dc_modifier.font_edit.QMessageBox.question",
                return_value=QMessageBox.StandardButton.Yes,
            ):
                dialog.import_full_font()
        self.assertEqual(bytes(self.project.working), before)
        dialog.accept()
        self.assertEqual(self.project.font_character_overrides, mappings)
        self.assertEqual(
            bytes(self.project.working[
                glyph_file_offset(token, writable=True):
                glyph_file_offset(token, writable=True) + 18
            ]),
            glyphs[token],
        )
        for offset, expected in padding.items():
            self.assertEqual(bytes(self.project.working[offset:offset + 4]), expected)
        self.project.undo()
        self.assertEqual(bytes(self.project.working), before)
        self.assertFalse(self.project.font_character_overrides)


if __name__ == "__main__":
    unittest.main()
