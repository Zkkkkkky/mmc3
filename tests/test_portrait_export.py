from __future__ import annotations

import os
from pathlib import Path
import struct
import tempfile
import unittest
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

from dc_modifier.app import DEFAULT_ROM, MainWindow
from dc_modifier.portrait_export import (
    PORTRAIT_FILENAMES,
    export_portrait_bitmaps,
    portrait_bitmap_bytes,
    portrait_export_paths,
    portrait_layer_pixels,
    safe_portrait_directory_name,
)
from fc_editor.codecs.character_attributes import CharacterAttributesCodec
from fc_editor.legacy_bitmap import LEGACY_MATERIAL_PALETTE_RGB
from fc_rom_editor_core import RomProject
from tests.qt_test_case import QtTestCase


class PortraitExportTests(unittest.TestCase):
    def setUp(self) -> None:
        self.project = RomProject.load(DEFAULT_ROM)

    def test_paths_match_confirmed_legacy_names_and_sanitize_only_component(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            back, front = portrait_export_paths(self.project, 4, directory)
            self.assertEqual(back.parent.name, "4：琉妮")
            self.assertEqual((back.name, front.name), ("[背面].bmp", "[正面].bmp"))
        self.assertEqual(safe_portrait_directory_name(7, ' A/B:*?"<>|. '), "7：A_B_______")
        self.assertEqual(safe_portrait_directory_name(8, "CON"), "8：_CON")

    def test_layers_follow_verified_4_by_4_chr_binding_and_material_palette(self) -> None:
        record = CharacterAttributesCodec(self.project).read_portrait(4)
        for layer, first_tile in (
            ("front", record.front_bank * 64 + record.front_slot * 16),
            ("back", (record.back_bank & 0xFE) * 64 + record.back_slot * 16),
        ):
            rendered = portrait_layer_pixels(self.project, 4, layer)
            self.assertEqual(len(rendered), 32 * 32)
            self.assertTrue(set(rendered) <= set(LEGACY_MATERIAL_PALETTE_RGB))
            first = self.project.chr_tile_pixels(first_tile)
            second_row_tile = self.project.chr_tile_pixels(first_tile + 4)
            self.assertEqual(rendered[0], LEGACY_MATERIAL_PALETTE_RGB[first[0]])
            self.assertEqual(rendered[8 * 32], LEGACY_MATERIAL_PALETTE_RGB[second_row_tile[0]])
        with self.assertRaises(ValueError):
            portrait_layer_pixels(self.project, 4, "composite")

    def test_export_writes_two_32_pixel_bottom_up_bmps_without_mutating_rom(self) -> None:
        before = bytes(self.project.working)
        with tempfile.TemporaryDirectory() as directory:
            paths = export_portrait_bitmaps(self.project, 4, directory)
            self.assertEqual(tuple(path.name for path in paths), tuple(PORTRAIT_FILENAMES.values()))
            for path in paths:
                payload = path.read_bytes()
                self.assertEqual(len(payload), 3_126)
                self.assertEqual(struct.unpack_from("<2sI", payload), (b"BM", 3_126))
                self.assertEqual(struct.unpack_from("<ii", payload, 18), (32, 32))
                self.assertEqual(struct.unpack_from("<H", payload, 28)[0], 24)
            self.assertFalse(tuple(Path(directory).rglob("*.tmp")))
        self.assertEqual(bytes(self.project.working), before)

    def test_bitmap_uses_current_working_chr(self) -> None:
        record = CharacterAttributesCodec(self.project).read_portrait(4)
        first_tile = record.front_bank * 64 + record.front_slot * 16
        self.project.set_chr_tile_pixels(first_tile, [3] * 64)
        self.assertEqual(portrait_layer_pixels(self.project, 4, "front")[0], LEGACY_MATERIAL_PALETTE_RGB[3])
        self.assertEqual(len(portrait_bitmap_bytes(self.project, 4, "front")), 3_126)


class PortraitExportUiTests(QtTestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = QApplication.instance() or QApplication([])

    def test_menu_export_uses_selected_character_and_root_directory(self) -> None:
        window = MainWindow(open_default=True)
        self.addCleanup(window.close)
        assert window.project is not None
        before = bytes(window.project.working)
        with tempfile.TemporaryDirectory() as directory, \
                patch("dc_modifier.app.QFileDialog.getExistingDirectory", return_value=directory), \
                patch("dc_modifier.app.QInputDialog.getItem", return_value=("004 · 琉妮", True)):
            window.export_avatar()
            back = Path(directory) / "4：琉妮" / "[背面].bmp"
            front = Path(directory) / "4：琉妮" / "[正面].bmp"
            self.assertTrue(back.is_file())
            self.assertTrue(front.is_file())
        self.assertEqual(bytes(window.project.working), before)


if __name__ == "__main__":
    unittest.main()
