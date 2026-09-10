from __future__ import annotations

import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication, QDialog, QMessageBox

from dc_modifier.chr_widget import ChrGraphicsWidget
from dc_modifier.legacy_windows import TransactionalProjectDialog
from dc_modifier.unit_import_page import UnitImportPage
from dc_modifier.workspace import DEFAULT_ROM
from fc_editor.unit_package import UnitPackage
from fc_rom_editor_core import RomProject


class ChrWidgetDraftTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.application = QApplication.instance() or QApplication([])

    def setUp(self) -> None:
        self.project = RomProject.load(DEFAULT_ROM)
        self.graphics = ChrGraphicsWidget()
        self.graphics.set_project(self.project)

    def tearDown(self) -> None:
        self.graphics.close()
        self.graphics.deleteLater()
        self.application.processEvents()

    @staticmethod
    def _stage_valid_draft(graphics: ChrGraphicsWidget) -> tuple[int, tuple[int, ...]]:
        tile_index = graphics.current_tile
        pixels = list(graphics.project.chr_tile_pixels(tile_index))
        pixels[0] = (pixels[0] + 1) % 4
        graphics.canvas.set_pixels(pixels)
        graphics.canvas.pixels_changed.emit()
        return tile_index, tuple(pixels)

    def test_switching_tile_commits_valid_canvas_draft(self) -> None:
        tile_index, staged = self._stage_valid_draft(self.graphics)
        undo_count = len(self.project._undo_stack)
        self.assertTrue(self.graphics.has_pending_draft)
        self.assertIsNone(self.graphics.pending_draft_error)

        self.graphics.tile_index.setValue(tile_index + 1)
        self.application.processEvents()

        self.assertEqual(self.graphics.current_tile, tile_index + 1)
        self.assertEqual(self.project.chr_tile_pixels(tile_index), staged)
        self.assertFalse(self.graphics.has_pending_draft)
        self.assertEqual(len(self.project._undo_stack), undo_count + 1)

    def test_switching_tile_preserves_and_blocks_invalid_canvas_draft(self) -> None:
        tile_index = self.graphics.current_tile
        original = self.project.chr_tile_pixels(tile_index)
        invalid = list(original)
        invalid[0] = 4
        self.graphics.canvas.set_pixels(invalid)
        self.graphics.canvas.pixels_changed.emit()
        self.assertTrue(self.graphics.has_pending_draft)
        self.assertIn("0—3", self.graphics.pending_draft_error or "")

        with patch("dc_modifier.chr_widget.QMessageBox.critical") as critical:
            self.graphics.tile_index.setValue(tile_index + 1)

        critical.assert_called_once()
        self.assertEqual(self.graphics.current_tile, tile_index)
        self.assertEqual(self.graphics.tile_index.value(), tile_index)
        self.assertEqual(self.graphics.sheet_page.value(), tile_index // 256)
        self.assertEqual(self.graphics.canvas.pixels, invalid)
        self.assertEqual(self.project.chr_tile_pixels(tile_index), original)

    def test_refresh_loads_clean_canvas_without_false_draft(self) -> None:
        self.assertFalse(self.graphics.has_pending_draft)
        self.graphics.refresh()
        self.assertFalse(self.graphics.has_pending_draft)
        self.assertIsNone(self.graphics.pending_draft_error)

    def test_outer_ok_commits_nested_chr_canvas_draft(self) -> None:
        dialog = TransactionalProjectDialog(self.project)
        page = dialog.register_page(UnitImportPage())
        dialog.show()
        self.application.processEvents()
        try:
            tile_index, staged = self._stage_valid_draft(page.graphics)
            self.assertTrue(page.has_pending_draft)

            dialog.accept()

            self.assertEqual(dialog.result(), QDialog.DialogCode.Accepted)
            self.assertEqual(self.project.chr_tile_pixels(tile_index), staged)
            self.assertFalse(page.has_pending_draft)
        finally:
            dialog.close()
            dialog.deleteLater()

    def test_outer_ok_blocks_and_preserves_invalid_nested_chr_draft(self) -> None:
        dialog = TransactionalProjectDialog(self.project)
        page = dialog.register_page(UnitImportPage())
        dialog.show()
        self.application.processEvents()
        tile_index = page.graphics.current_tile
        original = self.project.chr_tile_pixels(tile_index)
        invalid = list(original)
        invalid[-1] = -1
        page.graphics.canvas.set_pixels(invalid)
        page.graphics.canvas.pixels_changed.emit()
        try:
            with patch("dc_modifier.legacy_windows.QMessageBox.warning") as warning:
                dialog.accept()

            warning.assert_called_once()
            self.assertNotEqual(dialog.result(), QDialog.DialogCode.Accepted)
            self.assertTrue(dialog.isVisible())
            self.assertEqual(page.graphics.canvas.pixels, invalid)
            self.assertEqual(self.project.chr_tile_pixels(tile_index), original)
        finally:
            dialog.reject()
            dialog.deleteLater()

    def test_package_apply_commits_chr_draft_before_parent_refresh(self) -> None:
        dialog = TransactionalProjectDialog(self.project)
        page = dialog.register_page(UnitImportPage())
        dialog.show()
        self.application.processEvents()
        try:
            page.set_loaded_package(page._package_from_selected_unit())
            tile_index, staged = self._stage_valid_draft(page.graphics)
            undo_count = len(self.project._undo_stack)
            with patch(
                "dc_modifier.unit_import_page.QMessageBox.question",
                return_value=QMessageBox.StandardButton.Yes,
            ):
                page.apply_loaded_package()

            self.assertEqual(self.project.chr_tile_pixels(tile_index), staged)
            self.assertFalse(page.has_pending_draft)
            self.assertEqual(len(self.project._undo_stack), undo_count + 1)
        finally:
            dialog.reject()
            dialog.deleteLater()

    def test_package_export_includes_pending_chr_after_committing_it(self) -> None:
        dialog = TransactionalProjectDialog(self.project)
        page = dialog.register_page(UnitImportPage())
        dialog.show()
        self.application.processEvents()
        try:
            tile_index, staged = self._stage_valid_draft(page.graphics)
            page.include_chr.setChecked(True)
            page.chr_first_tile.setValue(tile_index)
            page.chr_tile_count.setValue(1)
            with tempfile.TemporaryDirectory() as directory:
                destination = Path(directory) / "pending.dcunit"
                with patch(
                    "dc_modifier.unit_import_page.QFileDialog.getSaveFileName",
                    return_value=(str(destination), "新DC机体包 (*.dcunit)"),
                ):
                    page.export_package()
                package = UnitPackage.load(destination)

            self.assertEqual(self.project.chr_tile_pixels(tile_index), staged)
            self.assertFalse(page.has_pending_draft)
            self.assertEqual(len(package.assets), 1)
            self.assertEqual(
                package.assets[0].data,
                self.project.chr_codec.encode_tile(staged),
            )
        finally:
            dialog.reject()
            dialog.deleteLater()

    def test_use_selected_unit_includes_draft_without_committing_it(self) -> None:
        page = UnitImportPage()
        page.set_project(self.project)
        try:
            original = bytes(self.project.working)
            tile_index, staged = self._stage_valid_draft(page.graphics)
            page.include_chr.setChecked(True)
            page.chr_first_tile.setValue(tile_index)
            page.chr_tile_count.setValue(1)

            page.use_selected_unit()

            self.assertIsNotNone(page.loaded_package)
            assert page.loaded_package is not None
            self.assertEqual(len(page.loaded_package.assets), 1)
            self.assertEqual(
                page.loaded_package.assets[0].data,
                self.project.chr_codec.encode_tile(staged),
            )
            self.assertEqual(bytes(self.project.working), original)
            self.assertTrue(page.graphics.has_pending_draft)
        finally:
            page.close()
            page.deleteLater()

    def test_applying_selected_unit_package_preserves_newer_canvas_draft(self) -> None:
        page = UnitImportPage()
        page.set_project(self.project)
        try:
            tile_index, first_draft = self._stage_valid_draft(page.graphics)
            page.include_chr.setChecked(True)
            page.chr_first_tile.setValue(tile_index)
            page.chr_tile_count.setValue(1)
            page.use_selected_unit()
            assert page.loaded_package is not None
            self.assertEqual(
                page.loaded_package.assets[0].data,
                self.project.chr_codec.encode_tile(first_draft),
            )

            newer_draft = list(first_draft)
            newer_draft[1] = (newer_draft[1] + 1) % 4
            page.graphics.canvas.set_pixels(newer_draft)
            page.graphics.canvas.pixels_changed.emit()
            with patch(
                "dc_modifier.unit_import_page.QMessageBox.question",
                return_value=QMessageBox.StandardButton.Yes,
            ):
                page.apply_loaded_package()

            self.assertEqual(
                self.project.chr_tile_pixels(tile_index), tuple(newer_draft)
            )
            self.assertFalse(page.graphics.has_pending_draft)
        finally:
            page.close()
            page.deleteLater()

    def test_chr_range_export_includes_then_commits_valid_draft(self) -> None:
        tile_index, staged = self._stage_valid_draft(self.graphics)
        self.graphics.range_count.setValue(1)
        with tempfile.TemporaryDirectory() as directory:
            destination = Path(directory) / "pending.chr"
            with patch(
                "dc_modifier.chr_widget.QFileDialog.getSaveFileName",
                return_value=(str(destination), "CHR图块数据 (*.chr)"),
            ):
                self.graphics.export_chr()
            payload = destination.read_bytes()

        self.assertEqual(payload, self.project.chr_codec.encode_tile(staged))
        self.assertEqual(self.project.chr_tile_pixels(tile_index), staged)
        self.assertFalse(self.graphics.has_pending_draft)

    def test_file_picker_cancellation_does_not_commit_drafts(self) -> None:
        original = bytes(self.project.working)
        self._stage_valid_draft(self.graphics)
        with patch(
            "dc_modifier.chr_widget.QFileDialog.getSaveFileName",
            return_value=("", ""),
        ):
            self.graphics.export_chr()
        self.assertEqual(bytes(self.project.working), original)
        self.assertTrue(self.graphics.has_pending_draft)

        page = UnitImportPage()
        page.set_project(self.project)
        try:
            self._stage_valid_draft(page.graphics)
            with patch(
                "dc_modifier.unit_import_page.QFileDialog.getSaveFileName",
                return_value=("", ""),
            ):
                page.export_package()
            self.assertEqual(bytes(self.project.working), original)
            self.assertTrue(page.graphics.has_pending_draft)
        finally:
            page.close()
            page.deleteLater()

    def test_export_failures_leave_canvas_drafts_uncommitted(self) -> None:
        original = bytes(self.project.working)
        self._stage_valid_draft(self.graphics)
        with tempfile.TemporaryDirectory() as directory:
            destination = Path(directory) / "failed.chr"
            with (
                patch(
                    "dc_modifier.chr_widget.QFileDialog.getSaveFileName",
                    return_value=(str(destination), "CHR图块数据 (*.chr)"),
                ),
                patch("pathlib.Path.write_bytes", side_effect=OSError("disk full")),
                patch("dc_modifier.pages.QMessageBox.critical") as critical,
            ):
                self.graphics.export_chr()
        critical.assert_called_once()
        self.assertEqual(bytes(self.project.working), original)
        self.assertTrue(self.graphics.has_pending_draft)

        page = UnitImportPage()
        page.set_project(self.project)
        try:
            self._stage_valid_draft(page.graphics)
            page.include_chr.setChecked(True)
            page.chr_first_tile.setValue(page.graphics.current_tile)
            page.chr_tile_count.setValue(1)
            with tempfile.TemporaryDirectory() as directory:
                destination = Path(directory) / "failed.dcunit"
                with (
                    patch(
                        "dc_modifier.unit_import_page.QFileDialog.getSaveFileName",
                        return_value=(
                            str(destination),
                            "新DC机体包 (*.dcunit)",
                        ),
                    ),
                    patch.object(
                        UnitPackage,
                        "save",
                        side_effect=OSError("disk full"),
                    ),
                    patch("dc_modifier.pages.QMessageBox.critical") as critical,
                ):
                    page.export_package()
            critical.assert_called_once()
            self.assertEqual(bytes(self.project.working), original)
            self.assertTrue(page.graphics.has_pending_draft)
        finally:
            page.close()
            page.deleteLater()

    def test_chr_range_import_preserves_valid_draft_as_undo_baseline(self) -> None:
        tile_index, staged = self._stage_valid_draft(self.graphics)
        imported = list(staged)
        imported[1] = (imported[1] + 1) % 4
        payload = self.project.chr_codec.encode_tile(imported)
        undo_count = len(self.project._undo_stack)

        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "replacement.chr"
            source.write_bytes(payload)
            with (
                patch(
                    "dc_modifier.chr_widget.QFileDialog.getOpenFileName",
                    return_value=(str(source), "CHR图块数据 (*.chr)"),
                ),
                patch(
                    "dc_modifier.chr_widget.QMessageBox.question",
                    return_value=QMessageBox.StandardButton.Yes,
                ),
            ):
                self.graphics.import_chr()

        self.assertEqual(
            self.project.chr_tile_pixels(tile_index), tuple(imported)
        )
        self.assertFalse(self.graphics.has_pending_draft)
        self.assertEqual(len(self.project._undo_stack), undo_count + 2)
        self.project.undo()
        self.assertEqual(self.project.chr_tile_pixels(tile_index), staged)

    def test_chr_range_import_rejects_invalid_existing_draft(self) -> None:
        tile_index = self.graphics.current_tile
        original = bytes(self.project.working)
        invalid = list(self.project.chr_tile_pixels(tile_index))
        invalid[0] = 4
        self.graphics.canvas.set_pixels(invalid)
        self.graphics.canvas.pixels_changed.emit()

        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "replacement.chr"
            source.write_bytes(b"\x00" * 16)
            with (
                patch(
                    "dc_modifier.chr_widget.QFileDialog.getOpenFileName",
                    return_value=(str(source), "CHR图块数据 (*.chr)"),
                ),
                patch("dc_modifier.chr_widget.QMessageBox.question") as question,
                patch("dc_modifier.pages.QMessageBox.critical") as critical,
            ):
                self.graphics.import_chr()

        question.assert_not_called()
        critical.assert_called_once()
        self.assertEqual(bytes(self.project.working), original)
        self.assertEqual(self.graphics.canvas.pixels, invalid)


if __name__ == "__main__":
    unittest.main()
