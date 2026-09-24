from __future__ import annotations

import os
from pathlib import Path
import tempfile
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

from dc_modifier.app import DEFAULT_ROM
from dc_modifier.legacy_windows import ChapterTitleDialog, ScenarioDialog
from dc_modifier.database_graphics import palette_color
from dc_modifier.map_page import CHAPTER_TITLE_PALETTE_NES, render_chapter_title
from fc_editor.codecs.chapter_title import (
    CHAPTER_TITLE_CHR_TABLE_OFFSET,
    CHAPTER_TITLE_COUNT,
    CHAPTER_TITLE_POINTER_TABLE_OFFSET,
    ChapterTitleCodec,
)
from fc_rom_editor_core import RomProject

from tests.qt_test_case import QtTestCase


class ChapterTitleCodecTests(unittest.TestCase):
    def setUp(self) -> None:
        self.project = RomProject.load(DEFAULT_ROM)

    def test_all_verified_title_records_round_trip(self) -> None:
        codec = self.project.chapter_title_codec
        self.assertIsNotNone(codec)
        assert codec is not None
        self.assertEqual(codec.count, CHAPTER_TITLE_COUNT)
        first = self.project.get_chapter_title(0)
        self.assertEqual(first.pointer, 0xAB7A)
        self.assertEqual(first.file_offset, 0x16B8A)
        self.assertEqual(first.chr_banks, (0x5C, 0x5D, 0x5E))
        self.assertEqual(len(first.segments), 2)
        self.assertEqual(first.title_segment.width, 8)
        for scenario_id in range(codec.count):
            self.assertTrue(codec.round_trip(scenario_id))
            record = self.project.get_chapter_title(scenario_id)
            self.assertEqual(record.raw[-1], 0xFF)
            self.assertGreaterEqual(len(record.segments), 1)

    def test_equal_capacity_script_and_chr_pages_are_isolated_and_undoable(self) -> None:
        before = bytes(self.project.working)
        current = self.project.get_chapter_title(0)
        following = self.project.get_chapter_title(1)
        replacement = bytearray(current.raw)
        replacement[4] ^= 1
        new_banks = (current.chr_banks[1], current.chr_banks[0], current.chr_banks[2])

        self.project.set_chapter_title(0, new_banks, bytes(replacement))

        changed = self.project.get_chapter_title(0)
        self.assertEqual(changed.raw, bytes(replacement))
        self.assertEqual(changed.chr_banks, new_banks)
        self.assertEqual(self.project.get_chapter_title(1), following)
        pointer_size = CHAPTER_TITLE_COUNT * 2
        self.assertEqual(
            self.project.working[
                CHAPTER_TITLE_POINTER_TABLE_OFFSET:
                CHAPTER_TITLE_POINTER_TABLE_OFFSET + pointer_size
            ],
            before[
                CHAPTER_TITLE_POINTER_TABLE_OFFSET:
                CHAPTER_TITLE_POINTER_TABLE_OFFSET + pointer_size
            ],
        )
        self.project.undo()
        self.assertEqual(bytes(self.project.working), before)

    def test_shared_pool_allows_balanced_length_changes_and_rejects_overflow(self) -> None:
        current = self.project.get_chapter_title(0)
        following = self.project.get_chapter_title(1)
        first = current.segments[-1]
        shorter = (
            current.raw[: -(len(first.tiles) + 5)]
            + bytes((0xFE, first.x, first.y, first.width - 1))
            + first.tiles[:-2]
            + b"\xFF"
        )
        self.project.set_chapter_title(0, current.chr_banks, shorter)
        self.assertEqual(len(self.project.get_chapter_title(0).raw), len(current.raw) - 2)

        second = following.segments[-1]
        longer = (
            following.raw[: -(len(second.tiles) + 5)]
            + bytes((0xFE, second.x, second.y, second.width + 1))
            + second.tiles
            + second.tiles[-2:]
            + b"\xFF"
        )
        self.project.set_chapter_title(1, following.chr_banks, longer)
        self.assertEqual(len(self.project.get_chapter_title(1).raw), len(following.raw) + 2)
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "title-repacked.nes"
            self.project.save_as(output)
            reopened = RomProject.load(output)
            self.assertEqual(reopened.get_chapter_title(0).raw, shorter)
            self.assertEqual(reopened.get_chapter_title(1).raw, longer)
        self.project.undo()
        self.project.undo()
        self.assertEqual(self.project.get_chapter_title(0), current)
        self.assertEqual(self.project.get_chapter_title(1), following)

        with self.assertRaisesRegex(ValueError, "共享池容量不足"):
            self.project.set_chapter_title(
                0,
                current.chr_banks,
                longer,
            )
        self.assertEqual(self.project.get_chapter_title(0), current)

    def test_invalid_structure_and_chr_page_are_rejected(self) -> None:
        current = self.project.get_chapter_title(0)
        invalid = bytearray(current.raw)
        invalid[0] = 0x00
        with self.assertRaisesRegex(ValueError, "必须以 FE 开始"):
            self.project.set_chapter_title(0, current.chr_banks, bytes(invalid))
        invalid_bank = self.project.chr_tile_count // 64
        with self.assertRaisesRegex(ValueError, "CHR 图库必须"):
            self.project.set_chapter_title(
                0,
                (invalid_bank, current.chr_banks[1], current.chr_banks[2]),
                current.raw,
            )

    def test_chr_table_has_three_bytes_per_scenario(self) -> None:
        last = CHAPTER_TITLE_CHR_TABLE_OFFSET + CHAPTER_TITLE_COUNT * 3
        self.assertLess(last, len(self.project.working))


class ChapterTitleUiTests(QtTestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.application = QApplication.instance() or QApplication([])

    def setUp(self) -> None:
        self.project = RomProject.load(DEFAULT_ROM)
        self.widgets = []

    def tearDown(self) -> None:
        for widget in self.widgets:
            widget.hide()
            widget.deleteLater()
        self.application.processEvents()

    def show(self, widget):
        self.widgets.append(widget)
        widget.show()
        self.application.processEvents()
        return widget

    def test_scenario_uses_true_rom_title_and_enables_editor(self) -> None:
        dialog = self.show(ScenarioDialog(self.project, initial_scenario_id=0))
        expected = render_chapter_title(self.project, 0)
        actual = dialog.title_preview.pixmap()
        self.assertTrue(dialog.title_code_button.isEnabled())
        self.assertFalse(actual.isNull())
        self.assertEqual(actual.size(), expected.size())
        self.assertEqual((actual.width(), actual.height()), (192, 48))

    def test_title_pixels_keep_verified_light_to_dark_nes_index_order(self) -> None:
        self.assertEqual(
            CHAPTER_TITLE_PALETTE_NES,
            (0x0F, 0x20, 0x10, 0x00),
        )
        record = self.project.get_chapter_title(0)
        segment = record.title_segment
        rendered = render_chapter_title(self.project, 0).toImage()
        found: dict[int, tuple[int, int]] = {}
        for position, tile_code in enumerate(segment.tiles):
            bank_index = max(0, tile_code // 0x40 - 1)
            tile = self.project.chr_tile_pixels(
                record.chr_banks[bank_index] * 0x40 + tile_code % 0x40
            )
            for pixel, value in enumerate(tile):
                if value and value not in found:
                    found[value] = (
                        (position % segment.width * 8 + pixel % 8) * 3,
                        (position // segment.width * 8 + pixel // 8) * 3,
                    )
        self.assertEqual(set(found), {1, 2, 3})
        for index, (x, y) in found.items():
            self.assertEqual(
                rendered.pixelColor(x, y),
                palette_color(CHAPTER_TITLE_PALETTE_NES[index]),
            )

    def test_title_library_preview_uses_the_same_exact_nes_gray_ramp(self) -> None:
        dialog = self.show(ChapterTitleDialog(self.project, 0))
        image = dialog.bank_previews[0].pixmap().toImage()
        scale = image.width() // 64
        bank = self.project.get_chapter_title(0).chr_banks[0]
        found: dict[int, tuple[int, int]] = {}
        for tile_index in range(64):
            tile = self.project.chr_tile_pixels(bank * 64 + tile_index)
            for pixel, value in enumerate(tile):
                if value and value not in found:
                    found[value] = (
                        (tile_index % 8 * 8 + pixel % 8) * scale,
                        (tile_index // 8 * 8 + pixel // 8) * scale,
                    )
        self.assertEqual(set(found), {1, 2, 3})
        for index, (x, y) in found.items():
            self.assertEqual(
                image.pixelColor(x, y),
                palette_color(CHAPTER_TITLE_PALETTE_NES[index]),
            )

    def test_title_dialog_applies_one_fixed_capacity_tile_change(self) -> None:
        before = bytes(self.project.working)
        original = self.project.get_chapter_title(0)
        dialog = self.show(ChapterTitleDialog(self.project, 0))
        replacement = bytearray(original.raw)
        replacement[4] ^= 1
        dialog.code_edit.setPlainText(bytes(replacement).hex(" ").upper())
        self.application.processEvents()
        self.assertTrue(dialog.ok_button.isEnabled())

        dialog.accept()

        self.assertEqual(self.project.get_chapter_title(0).raw, bytes(replacement))
        self.assertNotEqual(bytes(self.project.working), before)
        self.assertTrue(self.project.can_undo)

    def test_title_dialog_exposes_reference_segment_fields_and_tile_numbers(self) -> None:
        dialog = self.show(ChapterTitleDialog(self.project, 0))
        record = self.project.get_chapter_title(0)
        segment = record.segments[-1]
        self.assertEqual(dialog.segment_selector.count(), len(record.segments))
        self.assertEqual(dialog.segment_x.value(), segment.x)
        self.assertEqual(dialog.segment_y.value(), segment.y)
        self.assertEqual(dialog.segment_width.value(), segment.width)
        self.assertEqual(
            bytes.fromhex(dialog.segment_tiles.text()),
            segment.tiles,
        )
        dialog.show_tile_numbers.setChecked(True)
        self.application.processEvents()
        self.assertFalse(dialog.bank_previews[0].pixmap().isNull())

    def test_title_structured_segment_edit_updates_raw_without_changing_capacity(self) -> None:
        dialog = self.show(ChapterTitleDialog(self.project, 0))
        original = self.project.get_chapter_title(0)
        segment = original.segments[-1]
        changed = bytearray(segment.tiles)
        changed[0] ^= 1
        dialog.segment_tiles.setText(bytes(changed).hex(" ").upper())
        dialog.segment_apply.click()
        self.application.processEvents()
        raw = bytes.fromhex(dialog.code_edit.toPlainText())
        self.assertEqual(len(raw), original.capacity)
        self.assertEqual(ChapterTitleCodec.parse_segments(raw)[-1].tiles, bytes(changed))


if __name__ == "__main__":
    unittest.main()
