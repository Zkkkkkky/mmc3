from __future__ import annotations

import os
from pathlib import Path
import struct
import tempfile
import unittest
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

from dc_modifier.app import DEFAULT_ROM
from dc_modifier.character_editor import CharacterDetailsWidget, legacy_portrait_selectors
from dc_modifier.legacy_windows import DatabaseDialog
from dc_modifier.portrait_export import (
    PORTRAIT_BACKGROUND_PALETTE_NES,
    PORTRAIT_FILENAMES,
    export_portrait_bitmaps,
    portrait_bitmap_bytes,
    portrait_export_paths,
    portrait_layer_pixels,
    safe_portrait_directory_name,
)
from dc_modifier.database_graphics import FCEUX_RGB
from fc_editor.codecs.character_attributes import CharacterAttributesCodec
from fc_rom_editor_core import RomProject
from tests.qt_test_case import QtTestCase


class PortraitExportTests(unittest.TestCase):
    def setUp(self) -> None:
        self.project = RomProject.load(DEFAULT_ROM)

    def test_paths_match_confirmed_legacy_names_and_sanitize_only_component(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            back, front, effect = portrait_export_paths(self.project, 4, directory)
            self.assertEqual(back.parent.name, "4：琉妮")
            self.assertEqual(
                (back.name, front.name, effect.name),
                ("[背面].bmp", "[正面].bmp", "[效果].bmp"),
            )
        self.assertEqual(safe_portrait_directory_name(7, ' A/B:*?"<>|. '), "7：A_B_______")
        self.assertEqual(safe_portrait_directory_name(8, "CON"), "8：_CON")

    @staticmethod
    def _rgb(index: int) -> tuple[int, int, int]:
        start = (index & 0x3F) * 3
        return tuple(FCEUX_RGB[start:start + 3])

    def test_layers_follow_verified_4_by_4_chr_binding_and_portrait_palettes(self) -> None:
        record = CharacterAttributesCodec(self.project).read_portrait(4)
        for layer, first_tile, palette_indices in (
            (
                "front",
                record.front_bank * 64 + record.front_slot * 16,
                (0x0F, *record.colors),
            ),
            (
                "back",
                record.back_bank * 64 + record.back_slot * 16,
                PORTRAIT_BACKGROUND_PALETTE_NES,
            ),
        ):
            palette = tuple(self._rgb(index) for index in palette_indices)
            rendered = portrait_layer_pixels(self.project, 4, layer)
            self.assertEqual(len(rendered), 32 * 32)
            self.assertTrue(set(rendered) <= set(palette))
            first = self.project.chr_tile_pixels(first_tile)
            second_row_tile = self.project.chr_tile_pixels(first_tile + 4)
            self.assertEqual(rendered[0], palette[first[0]])
            self.assertEqual(rendered[8 * 32], palette[second_row_tile[0]])
        with self.assertRaises(ValueError):
            portrait_layer_pixels(self.project, 4, "composite")

    def test_rosamia_front_uses_record_colors_instead_of_unit_material_colors(self) -> None:
        record = CharacterAttributesCodec(self.project).read_portrait(16)
        self.assertEqual(record.colors, (0x37, 0x17, 0x04))
        expected_palette = {
            self._rgb(0x0F),
            *(self._rgb(index) for index in record.colors),
        }
        self.assertTrue(
            set(portrait_layer_pixels(self.project, 16, "front")) <= expected_palette
        )

    def test_back_uses_fixed_background_palette_and_effect_preserves_both_palettes(self) -> None:
        record = CharacterAttributesCodec(self.project).read_portrait(4)
        front_palette = {
            self._rgb(0x0F),
            *(self._rgb(index) for index in record.colors),
        }
        back_palette = {
            self._rgb(index) for index in PORTRAIT_BACKGROUND_PALETTE_NES
        }
        self.assertTrue(set(portrait_layer_pixels(self.project, 4, "back")) <= back_palette)
        self.assertTrue(
            set(portrait_layer_pixels(self.project, 4, "effect")) <= front_palette | back_palette
        )

    def test_effect_composites_nonzero_front_pixels_over_back(self) -> None:
        back = portrait_layer_pixels(self.project, 4, "back")
        front = portrait_layer_pixels(self.project, 4, "front")
        effect = portrait_layer_pixels(self.project, 4, "effect")
        transparent = self._rgb(0x0F)
        self.assertEqual(
            effect,
            tuple(
                front_pixel if front_pixel != transparent else back_pixel
                for back_pixel, front_pixel in zip(back, front, strict=True)
            ),
        )

    def test_export_writes_three_32_pixel_bottom_up_bmps_without_mutating_rom(self) -> None:
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
        self.assertEqual(
            portrait_layer_pixels(self.project, 4, "front")[0],
            self._rgb(record.colors[2]),
        )
        self.assertEqual(len(portrait_bitmap_bytes(self.project, 4, "front")), 3_126)

    def test_legacy_selectors_match_verified_reference_field_roles(self) -> None:
        record = CharacterAttributesCodec(self.project).read_portrait(6)
        self.assertEqual(
            (record.front_bank, record.front_slot, record.back_bank, record.back_slot),
            (25, 0, 27, 1),
        )
        self.assertEqual(legacy_portrait_selectors(record), (25, 1, 27, 2))


class PortraitExportUiTests(QtTestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = QApplication.instance() or QApplication([])

    def test_database_portrait_button_exports_selected_character(self) -> None:
        project = RomProject.load(DEFAULT_ROM)
        dialog = DatabaseDialog(project)
        self.addCleanup(dialog.close)
        page = dialog.character_page
        page.load_record(4)
        before = bytes(project.working)
        with tempfile.TemporaryDirectory() as directory, \
                patch(
                    "dc_modifier.database_records.QFileDialog.getExistingDirectory",
                    return_value=directory,
                ):
            page.character_details.portrait_export_button.click()
            back = Path(directory) / "4：琉妮" / "[背面].bmp"
            front = Path(directory) / "4：琉妮" / "[正面].bmp"
            effect = Path(directory) / "4：琉妮" / "[效果].bmp"
            self.assertTrue(back.is_file())
            self.assertTrue(front.is_file())
            self.assertTrue(effect.is_file())
        self.assertEqual(bytes(project.working), before)

    def test_character_widget_legacy_selector_round_trip_preserves_raw_portrait(self) -> None:
        project = RomProject.load(DEFAULT_ROM)
        widget = CharacterDetailsWidget()
        self.addCleanup(widget.deleteLater)
        widget.set_record(project, 6)
        self.assertEqual(widget.portrait_fields["front_bank"].value(), 25)
        self.assertEqual(widget.portrait_fields["front_slot"].value(), 1)
        self.assertEqual(widget.portrait_fields["back_bank"].value(), 27)
        self.assertEqual(widget.portrait_fields["back_slot"].value(), 2)
        self.assertEqual(
            widget.portrait_record(),
            CharacterAttributesCodec(project).read_portrait(6),
        )


if __name__ == "__main__":
    unittest.main()
