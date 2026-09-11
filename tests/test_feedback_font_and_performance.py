from __future__ import annotations

import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QPersistentModelIndex
from PySide6.QtWidgets import QApplication, QDialog, QMessageBox

from dc_modifier.app import MainWindow
from dc_modifier.legacy_tools import FontLibraryDialog, TextConverterDialog
from dc_modifier.pages import UnitPage
from dc_modifier.window_layout import fit_dialog_to_screen
from fc_editor.codecs.dc_font import decode_glyph, encode_glyph, glyph_file_offset, page_tokens
from fc_rom_editor_core import RomProject

ROOT = Path(__file__).resolve().parents[1]
ROM = ROOT / "output/rom/DC_kuorong_464K.nes"


from tests.qt_test_case import QtTestCase


class FontFeedbackTests(QtTestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self) -> None:
        self.project = RomProject.load(ROM)

    def test_font_codec_roundtrip_padding_and_alias_guards(self) -> None:
        raw = bytes(range(18))
        self.assertEqual(encode_glyph(decode_glyph(raw)), raw)
        tokens = page_tokens(0xC8)
        self.assertEqual(len(tokens), 224)
        for token in tokens:
            offset = glyph_file_offset(token, writable=True)
            self.assertLessEqual((offset - 0x70010) % 0x100 + 18, 252)
        with self.assertRaises(ValueError):
            self.project.set_font_glyphs({bytes.fromhex("C80E"): bytes(18)})
        with self.assertRaises(ValueError):
            self.project.set_font_glyphs({bytes.fromhex("C800"): bytes(17)})
        self.assertFalse(self.project.is_dirty)

    def test_real_one_glyph_is_a_single_eleven_pixel_horizontal_stroke(self) -> None:
        # CAC6 / 一: three 4×12 vertical strips, zero bits are foreground.
        raw = bytes.fromhex("ff ff ff 8f ff ff ff ff ff 0f ff ff ff ff ff 0f ff ff")
        offset = glyph_file_offset(bytes.fromhex("CAC6"))
        self.assertEqual(bytes(self.project.working[offset:offset + 18]), raw)
        expected = [[0] * 12 for _ in range(12)]
        expected[6] = [0] + [1] * 11
        self.assertEqual(decode_glyph(raw), tuple(tuple(row) for row in expected))
        self.assertEqual(encode_glyph(expected), raw)

    def test_font_write_undo_replay_and_only_selected_bytes_change(self) -> None:
        token = bytes.fromhex("C908")
        offset = glyph_file_offset(token)
        before = bytes(self.project.working)
        raw = bytes(value ^ 255 for value in before[offset:offset + 18])
        self.project.set_font_glyphs({token: raw})
        self.assertEqual([r[0] for r in self.project.change_rows()], list(range(offset, offset + 18)))
        expected = bytes(self.project.working)
        self.assertFalse([issue for issue in self.project.validate() if issue.severity == "error"])
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "font.dcmod"
            self.project.save_project(path)
            reopened = RomProject.load_project(path, ROM)
            self.assertEqual(bytes(reopened.working), expected)
        self.project.undo()
        self.assertEqual(bytes(self.project.working), before)
        self.project.redo()
        self.assertEqual(bytes(self.project.working), expected)

    def test_font_dialog_cancel_and_confirm_include_current_pixel_draft(self) -> None:
        before = bytes(self.project.working)
        dialog = FontLibraryDialog(project=self.project)
        token = dialog.current_token
        raw = bytes(value ^ 255 for value in dialog._raw_glyph(token))
        dialog.glyph_canvas.load(raw)
        dialog.glyph_canvas.changed.emit()
        self.assertTrue(dialog.write_button.isEnabled())
        dialog.stage_current_glyph()
        self.assertEqual(bytes(self.project.working), before)
        dialog.reject()
        self.assertEqual(bytes(self.project.working), before)
        dialog = FontLibraryDialog(project=self.project)
        dialog.glyph_canvas.load(raw)
        dialog.glyph_canvas.changed.emit()
        dialog.accept()
        self.assertEqual(dialog.result(), QDialog.DialogCode.Accepted)
        offset = glyph_file_offset(token)
        self.assertEqual(bytes(self.project.working[offset:offset + 18]), raw)

    def test_font_navigation_preserves_pending_pixels_and_page_clear_padding(self) -> None:
        dialog = FontLibraryDialog(project=self.project)
        token = dialog.current_token
        raw = bytes(value ^ 255 for value in dialog._raw_glyph(token))
        dialog.glyph_canvas.load(raw)
        dialog.glyph_canvas.changed.emit()
        dialog._select_cell(1, 1)
        self.assertEqual(dialog._glyph_drafts[token], raw)
        before = bytes(self.project.working)
        with patch.object(QMessageBox, "question", return_value=QMessageBox.StandardButton.Yes):
            dialog.clear_font_page()
        dialog.accept()
        for row in range(16):
            offset = 0x70010 + row * 256
            self.assertEqual(bytes(self.project.working[offset:offset + 252]), b"\xff" * 252)
            self.assertEqual(bytes(self.project.working[offset + 252:offset + 256]), before[offset + 252:offset + 256])

    def test_block_diff_matches_naive_diff_across_boundaries(self) -> None:
        for offset in (0, 4095, 4096, 8192, len(self.project.working) - 1):
            self.project.working[offset] ^= 1
        expected = [(i, a, b) for i, (a, b) in enumerate(zip(self.project.original, self.project.working)) if a != b]
        self.assertEqual(self.project.change_rows(), expected)

    def test_status_reuses_count_but_detects_direct_changes(self) -> None:
        window = MainWindow()
        with patch.object(window.project, "change_rows", wraps=window.project.change_rows) as count:
            window._update_window_state()
            window._update_window_state()
            self.assertEqual(count.call_count, 0)
            window.project.working[0x70010] ^= 1
            window._update_window_state()
            self.assertEqual(count.call_count, 1)
            self.assertIn("1 字节修改", window.change_status.text())
        window.project.working[:] = window.project.original
        window.close()

    def test_fixed_tools_get_scrollable_resizable_form(self) -> None:
        dialog = TextConverterDialog()
        fit_dialog_to_screen(dialog)
        self.assertLess(dialog.minimumWidth(), dialog.maximumWidth())
        self.assertLess(dialog.minimumHeight(), dialog.maximumHeight())
        dialog.text_edit.setPlainText("测试")
        self.assertEqual(dialog.text_edit.toPlainText(), "测试")
        dialog.reject()

    def test_record_refresh_preserves_items_and_loads_selection_once(self) -> None:
        page = UnitPage()
        page.set_project(self.project)
        original = page.records.currentItem()
        persistent = QPersistentModelIndex(page.records.currentIndex())
        with patch.object(page, "load_record", wraps=page.load_record) as load:
            page.refresh()
            self.assertEqual(load.call_count, 1)
        self.assertTrue(persistent.isValid())
        self.assertIs(page.records.currentItem(), original)

        page.project_changed.connect(lambda _message: page.refresh())
        unit_id = page.current_id
        old_hp = page.fields["hp"].value()
        page.fields["hp"].setValue(old_hp + 1)
        page.records.setCurrentRow(1)
        self.assertEqual(self.project.get_value(unit_id, "hp"), old_hp + 1)
        self.assertEqual(page.current_id, 2)
        self.assertTrue(persistent.isValid())
        self.assertIs(page.records.item(0), original)
        page.deleteLater()

    def test_hidden_pages_refresh_once_on_next_visit(self) -> None:
        window = MainWindow()
        hidden = window.pages[window.page_index["units"]]
        window.show_page("maps")
        with patch.object(hidden, "refresh", wraps=hidden.refresh) as refresh:
            window._refresh_registered_pages(preserve_map_draft=True)
            self.assertEqual(refresh.call_count, 0)
            self.assertIn(hidden, window._stale_pages)
            window.show_page("units")
            self.assertEqual(refresh.call_count, 1)
            self.assertNotIn(hidden, window._stale_pages)
            window.show_page("maps")
            window.show_page("units")
            self.assertEqual(refresh.call_count, 1)
        window.close()


if __name__ == "__main__":
    unittest.main()
