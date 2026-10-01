from __future__ import annotations

from dataclasses import replace
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import call, patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QPoint, Qt
from PySide6.QtGui import QColor, QImage
from PySide6.QtWidgets import QApplication, QMessageBox

from dc_modifier.app import DEFAULT_ROM
from dc_modifier.database_graphics import (
    CompositionTile,
    FragmentTile,
    decode_unit_body_script,
    decode_unit_fragment_script,
    palette_color,
    read_all_unit_appearances,
    read_unit_appearance,
    render_chr_banks,
    render_unit_battle_preview,
    render_unit_body_composition,
)
from dc_modifier.legacy_windows import (
    DatabaseDialog,
    UNIT_SPECIAL_DIALOG_FLAGS,
    UNIT_SPECIAL_FLAGS,
    UnitSpecialEditorDialog,
    unit_special_summary,
)
from dc_modifier.unit_appearance_dialog import (
    ChrTileEditorDialog,
    WORK_PALETTE,
    UnitAppearanceDialog,
    appearance_patch,
    body_import_alignment_candidates,
    chr_bank_description,
    choose_body_layout,
    encode_body_placements,
    encode_compact_fragment_placements,
    encode_fragment_placements,
    encode_sparse_body_placements,
    flip_fragment_script,
    image_to_chr_pixels,
    legacy_composition_image,
    legacy_fragment_library_image,
    move_body_script,
    move_fragment_script,
    optimize_fragment_slices,
    pad_body_image_to_tile_grid,
    parse_hex_script,
    sparse_body_tiles,
)
from fc_rom_editor_core import RomProject
from fc_editor.expansion_unit import read_stock_composition_layout
from fc_editor.legacy_bitmap import LEGACY_MATERIAL_PALETTE_RGB
from tests.qt_test_case import QtTestCase


class ScreenshotUnitTests(QtTestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self) -> None:
        self.project = RomProject.load(DEFAULT_ROM)

    def test_nested_resource_drafts_accept_replay_and_cancel(self) -> None:
        before = bytes(self.project.working)
        database = DatabaseDialog(self.project)
        database.show()
        self.app.processEvents()
        database.growth_page.growth_table.item(0, 1).setText("3")
        database.shop_page.item_combos[0].setCurrentIndex(0)
        text_page = database.battle_dialogue_page
        text_page.text_edit.setPlainText(text_page.text_edit.toPlainText()[1:])
        self.assertTrue(database.growth_page.has_pending_draft)
        self.assertTrue(database.shop_page.has_pending_draft)
        self.assertTrue(database.battle_dialogue_page.has_pending_draft)
        self.assertIsNone(database.battle_dialogue_page.pending_draft_error)
        self.assertIsNone(database.growth_page.pending_draft_error)
        self.assertIsNone(database.shop_page.pending_draft_error)
        database.accept()
        self.assertFalse(database.isVisible())
        self.assertNotEqual(bytes(self.project.working), before)
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "nested.dcmod"
            self.project.save_project(path)
            reloaded = RomProject.load_project(path, DEFAULT_ROM)
        self.assertEqual(bytes(reloaded.working), bytes(self.project.working))
        kept = bytes(self.project.working)
        database.show()
        self.app.processEvents()
        database.growth_page.growth_table.item(0, 1).setText("4")
        database.shop_page.item_combos[0].setCurrentIndex(1)
        database.reject()
        self.assertEqual(bytes(self.project.working), kept)
        self.assertFalse(database.growth_page.has_pending_draft)
        self.assertFalse(database.shop_page.has_pending_draft)

    def test_replacing_project_discards_local_resource_drafts(self) -> None:
        database = DatabaseDialog(self.project)
        database.growth_page.growth_table.item(0, 1).setText("3")
        database.shop_page.item_combos[0].setCurrentIndex(0)
        database.battle_dialogue_page.text_edit.setPlainText("【】")
        replacement = RomProject.load(DEFAULT_ROM)
        database.set_project(replacement)
        for page in (database.growth_page, database.shop_page, database.battle_dialogue_page):
            self.assertFalse(page.has_pending_draft)
        self.assertEqual(bytes(replacement.working), bytes(replacement.original))

    def test_new_fields_follow_runtime_record_and_preserve_type_flags(self) -> None:
        # $24:8064 loads the selector $71 record into $04EE-$04FD;
        # $04:96C0 copies byte +1 ($04EF) to the runtime skill array.
        self.assertEqual(self.project.working[0x48074:0x4808C], bytes.fromhex(
            "a9 71 85 18 ad e1 04 85 19 20 0b c1 a0 00 b1 18 99 ee 04 c8 c0 10 d0 f6"
        ))
        self.assertEqual(self.project.working[0x96D0:0x96D6], bytes.fromhex("ad ef 04 9d f7 77"))
        raw = self.project.record_bytes(2)
        self.assertEqual(self.project.get_value(2, "upgrade"), 130)
        self.assertEqual(self.project.get_value(2, "experience"), 100)
        self.project.set_value(2, "terrain", 2)
        self.project.set_value(2, "transform", 14)
        self.project.set_value(2, "special", 0x86)
        self.project.set_value(2, "experience", 90)
        after = self.project.record_bytes(2)
        self.assertEqual(after[0], (14 << 2) | 2)
        self.assertEqual(after[1], 0x86)
        self.assertEqual(after[10], 90)
        self.assertEqual(after[2:10], raw[2:10])
        self.assertEqual(after[11:], raw[11:])
        with self.assertRaises(ValueError):
            self.project.set_value(2, "terrain", 4)
        with self.assertRaises(ValueError):
            self.project.set_value(2, "transform", 64)

    def test_base_money_uses_legacy_game_value_scale_in_form(self) -> None:
        database = DatabaseDialog(self.project)
        self.addCleanup(database.close)
        page = database.unit_page
        for row in range(page.records.count()):
            if int(page.records.item(row).data(256)) == 2:
                page.records.setCurrentRow(row)
                break
        self.app.processEvents()
        self.assertEqual(self.project.get_value(2, "upgrade"), 130)
        self.assertEqual(page.fields["upgrade"].value(), 1300)
        self.assertEqual(page.fields["upgrade"].singleStep(), 10)
        page.fields["upgrade"].setValue(1210)
        with patch(
            "dc_modifier.pages.QMessageBox.question",
            return_value=QMessageBox.StandardButton.Yes,
        ):
            page.apply_record()
        self.assertEqual(self.project.get_value(2, "upgrade"), 121)

    def test_unit_special_byte_has_reference_style_visual_editor(self) -> None:
        dialog = UnitSpecialEditorDialog(0x16)
        self.addCleanup(dialog.close)
        self.assertEqual(dialog.value(), 0x16)
        self.assertTrue(dialog.flag_checks[0x10].isChecked())
        self.assertIn("先制攻击", dialog.summary.text())
        self.assertEqual(dialog.windowTitle(), "机体特技")
        self.assertEqual(
            [dialog.flag_checks[mask].text() for mask, _label in UNIT_SPECIAL_DIALOG_FLAGS],
            [label for _mask, label in UNIT_SPECIAL_DIALOG_FLAGS],
        )
        self.assertEqual(dialog.low_bits.itemText(1), "01：T防御系统")
        self.assertFalse(dialog.summary.isHidden())
        self.assertEqual(dialog.size().toTuple(), (380, 250))
        self.assertEqual(dialog.summary.objectName(), "unitSpecialSummary")
        self.assertIn("#D9ECE5", dialog.styleSheet())
        self.assertIn("#3E8798", dialog.styleSheet())
        dialog.flag_checks[0x20].setChecked(True)
        dialog.low_bits.setCurrentIndex(3)
        self.assertEqual(dialog.value(), 0x33)
        self.assertIn("一击脱离", dialog.summary.text())
        self.assertTrue(dialog.summary.text().startswith("当前组合：51 ·"))
        self.assertIn("VPS防御系统", unit_special_summary(dialog.value()))

        database = DatabaseDialog(self.project)
        self.addCleanup(database.close)
        page = database.unit_page
        page.fields["special"].setValue(0xD8)
        self.assertEqual(page.special_skill_button.text(), "216")
        self.assertEqual(
            page.special_skill_expand_button.arrowType(),
            Qt.ArrowType.DownArrow,
        )
        self.assertEqual(page.special_skill_control.width(), 72)
        self.assertIn("积层装甲反射", page.special_skill_button.toolTip())
        self.assertIn("先制攻击", page.special_skill_button.toolTip())
        self.assertIn("异次元连接系统", page.special_skill_button.toolTip())
        self.assertIn("扭曲力场", page.special_skill_button.toolTip())
        page.fields["terrain"].setValue(2)
        page.transform.setCurrentIndex(page.transform.findData(14))
        self.assertEqual(page.fields["transform"].value(), 14)
        self.assertEqual(page.fields["terrain"].value(), 2)

    def test_masked_field_and_raw_flag_changes_survive_project_replay(self) -> None:
        raw = bytearray(self.project.record_bytes(2))
        raw[0] = 0xAB
        self.project.set_record_hex(2, raw.hex())
        self.project.set_value(2, "terrain", 2)
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "flags.dcmod"
            self.project.save_project(path)
            loaded = RomProject.load_project(path, DEFAULT_ROM)
        self.assertEqual(bytes(loaded.working), bytes(self.project.working))

    def test_small_appearance_edit_preserves_neighbour_and_supports_undo(self) -> None:
        appearances_before = read_all_unit_appearances(self.project)
        appearance = appearances_before[1]
        before = bytes(self.project.working)
        dialog = UnitAppearanceDialog(self.project, 2)
        self.assertEqual(len(dialog.editors), 3)
        self.assertFalse(dialog.editors[2].isEnabled())
        dialog.editors[0].setValue(appearance.configuration[7] ^ 0x02)
        dialog.editors[1].setValue(appearance.configuration[8] ^ 0x01)
        dialog.accept()
        self.assertTrue(dialog.changed)
        offset = appearance.file_offset
        self.assertEqual(self.project.working[offset + 9], before[offset + 9])
        appearances_after = read_all_unit_appearances(self.project)
        changed_ids = {
            unit_id
            for unit_id, (old, new) in enumerate(
                zip(appearances_before, appearances_after), start=1
            )
            if old.configuration != new.configuration
        }
        self.assertEqual(changed_ids, {2})
        self.assertEqual(
            appearances_after[1].configuration[7], appearance.configuration[7] ^ 0x02
        )
        self.assertEqual(
            appearances_after[1].configuration[8], appearance.configuration[8] ^ 0x01
        )
        self.project.undo()
        self.assertEqual(bytes(self.project.working), before)

    def test_expanded_scripts_move_flip_repack_and_round_trip(self) -> None:
        self.project.configure_expansion(288, 64, 112)
        before = read_unit_appearance(self.project, 0x09)
        moved_body = move_body_script(before.body_script, 1, -1)
        moved_fragment = move_fragment_script(before.fragment_script, 2, 3)
        flipped_fragment = flip_fragment_script(moved_fragment, 0x40)
        decode_unit_body_script(moved_body, len(before.secondary_banks) * 64)
        decode_unit_fragment_script(flipped_fragment)
        self.project.set_unit_appearance_scripts(
            0x09,
            body_script=moved_body,
            fragment_script=flipped_fragment,
        )
        after = read_unit_appearance(self.project, 0x09)
        self.assertEqual(after.body_script, moved_body)
        self.assertEqual(after.fragment_script, flipped_fragment)
        self.assertEqual(
            parse_hex_script(after.body_script.hex(" "), "主体拼图脚本"),
            moved_body,
        )
        self.assertFalse(
            [issue for issue in self.project.validate() if issue.severity == "error"]
        )
        self.project.undo()
        restored = read_unit_appearance(self.project, 0x09)
        self.assertEqual(restored.body_script, before.body_script)
        self.assertEqual(restored.fragment_script, before.fragment_script)

    def test_expanded_scripts_accept_true_variable_lengths_and_reopen(self) -> None:
        self.project.configure_expansion(288, 64, 112)
        before_status = self.project.unit_composition_pool_status()
        body_before = read_unit_appearance(self.project, 0x09)
        fragment_before = read_unit_appearance(self.project, 0x0A)
        body_tiles = decode_unit_body_script(
            body_before.body_script, len(body_before.secondary_banks) * 64
        )
        fragment_tiles = decode_unit_fragment_script(fragment_before.fragment_script)
        grown_body = encode_body_placements(body_tiles + (body_tiles[-1],))
        shortened_fragment = encode_fragment_placements(fragment_tiles[:5])
        self.assertGreater(len(grown_body), len(body_before.body_script))
        self.assertLess(len(shortened_fragment), len(fragment_before.fragment_script))

        self.project.set_unit_appearance_scripts(0x09, body_script=grown_body)
        self.project.set_unit_appearance_scripts(
            0x0A, fragment_script=shortened_fragment
        )
        after_status = self.project.unit_composition_pool_status()
        self.assertEqual(
            after_status.total_used - before_status.total_used,
            len(grown_body) - len(body_before.body_script)
            + len(shortened_fragment) - len(fragment_before.fragment_script),
        )
        self.assertEqual(
            read_unit_appearance(self.project, 0x09).body_script, grown_body
        )
        self.assertEqual(
            read_unit_appearance(self.project, 0x0A).fragment_script,
            shortened_fragment,
        )
        self.assertFalse(
            [issue for issue in self.project.validate() if issue.severity == "error"]
        )

        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "variable-unit-scripts.nes"
            self.project.save_as(path, make_backup=False)
            reopened = RomProject.load(path)
        self.assertEqual(
            read_unit_appearance(reopened, 0x09).body_script, grown_body
        )
        self.assertEqual(
            read_unit_appearance(reopened, 0x0A).fragment_script,
            shortened_fragment,
        )
        self.assertEqual(
            reopened.unit_composition_pool_status(), after_status
        )

    def test_direct_composition_encoders_preserve_all_stock_geometry(self) -> None:
        for unit_id in range(1, self.project.unit_count):
            appearance = read_unit_appearance(self.project, unit_id)
            body = decode_unit_body_script(
                appearance.body_script, len(appearance.secondary_banks) * 64
            )
            fragments = decode_unit_fragment_script(appearance.fragment_script)
            self.assertEqual(
                decode_unit_body_script(
                    encode_body_placements(body), len(appearance.secondary_banks) * 64
                ),
                body,
            )
            self.assertEqual(
                decode_unit_fragment_script(encode_fragment_placements(fragments)),
                fragments,
            )

    def test_bmp_quantisation_uses_active_game_palette(self) -> None:
        colors = (0x26, 0x06, 0x20)
        image = QImage(8, 8, QImage.Format.Format_ARGB32)
        palette = (palette_color(0x0F), *(palette_color(value) for value in colors))
        for y in range(8):
            for x in range(8):
                image.setPixelColor(x, y, palette[x % 4])
        image.setPixelColor(0, 0, QColor(0, 0, 0, 0))
        pixels = image_to_chr_pixels(image, colors)
        self.assertEqual(len(pixels), 64)
        self.assertEqual(pixels[0], 0)
        self.assertEqual(pixels[1:4], (1, 2, 3))

    def test_library_tile_edit_is_draft_until_dialog_accept(self) -> None:
        dialog = UnitAppearanceDialog(self.project, 0x09)
        self.addCleanup(dialog.close)
        tile_index = dialog._absolute_tile("body")
        before = self.project.chr_tile_pixels(tile_index)
        changed = tuple((value + 1) % 4 for value in before)
        dialog._set_draft_tile(tile_index, changed)
        self.assertEqual(self.project.chr_tile_pixels(tile_index), before)
        self.assertEqual(dialog._draft_project().chr_tile_pixels(tile_index), changed)
        dialog.accept()
        self.assertEqual(self.project.chr_tile_pixels(tile_index), changed)
        self.project.undo()
        self.assertEqual(self.project.chr_tile_pixels(tile_index), before)

    def test_legacy_bank_description_and_large_library_switch(self) -> None:
        dialog = UnitAppearanceDialog(self.project, 11)
        self.addCleanup(dialog.close)
        body_banks = dialog.appearance.secondary_banks
        self.assertEqual(
            chr_bank_description(self.project, body_banks[0]),
            f"[${body_banks[0]:02X}] 十进制 {body_banks[0]:03d} · 文件偏移 "
            f"0x{self.project.chr_codec.tile_offset(body_banks[0] * 64):06X}",
        )
        self.assertTrue(dialog.swap_body_library.isEnabled())
        dialog.swap_body_library.setChecked(True)
        self.assertEqual(dialog._selected_body_tile, 0x40)
        self.assertEqual(dialog._absolute_tile("body"), body_banks[1] * 64)
        # The old editor's 7x9 button is a verified no-op; use its working
        # 9x7 template here to exercise second-bank numbering.
        dialog._apply_body_grid(9, 7)
        placements = decode_unit_body_script(dialog.body_script, 128)
        self.assertEqual(len(placements), 63)
        self.assertEqual(placements[0].tile_index, 0x40)
        self.assertEqual((placements[0].x, placements[0].y), (0, -6))
        dialog._select_library_tile("body", 12, 68)
        self.assertEqual(dialog._selected_body_tile, 0x41)

    def test_large_body_second_library_clear_uses_selected_page(self) -> None:
        dialog = UnitAppearanceDialog(self.project, 0x0B)
        self.addCleanup(dialog.close)
        first_bank, second_bank = dialog.appearance.secondary_banks
        first_before = tuple(
            self.project.chr_tile_pixels(first_bank * 64 + index)
            for index in range(64)
        )
        self.assertTrue(any(
            any(self.project.chr_tile_pixels(second_bank * 64 + index))
            for index in range(64)
        ))

        dialog._select_library_tile("body", 4, 68)
        self.assertGreaterEqual(dialog._selected_body_tile, 0x40)
        with patch.object(
            QMessageBox,
            "question",
            return_value=QMessageBox.StandardButton.Yes,
        ):
            dialog._clear_library("body")
        dialog.accept()

        self.assertEqual(
            tuple(
                self.project.chr_tile_pixels(first_bank * 64 + index)
                for index in range(64)
            ),
            first_before,
        )
        self.assertTrue(all(
            self.project.chr_tile_pixels(second_bank * 64 + index) == (0,) * 64
            for index in range(64)
        ))

    def test_large_body_library_copy_paste_uses_selected_pages(self) -> None:
        dialog = UnitAppearanceDialog(self.project, 0x0B)
        self.addCleanup(dialog.close)
        first_bank, second_bank = dialog.appearance.secondary_banks
        source = tuple(
            self.project.chr_tile_pixels(first_bank * 64 + index)
            for index in range(64)
        )
        self.assertNotEqual(
            source,
            tuple(
                self.project.chr_tile_pixels(second_bank * 64 + index)
                for index in range(64)
            ),
        )

        dialog._select_library_tile("body", 4, 4)
        dialog._copy_library("body")
        dialog._select_library_tile("body", 4, 68)
        dialog._paste_library("body")
        dialog.accept()

        self.assertEqual(
            tuple(
                self.project.chr_tile_pixels(second_bank * 64 + index)
                for index in range(64)
            ),
            source,
        )

    def test_unit_list_clear_removes_attributes_and_composed_images(self) -> None:
        database = DatabaseDialog(self.project)
        self.addCleanup(database.close)
        database.show()
        self.app.processEvents()
        page = database.unit_page
        page.controller.select_record_id(0x09)
        self.app.processEvents()

        page._clear_current_unit()

        cleared = read_unit_appearance(self.project, 0x09)
        self.assertEqual(self.project.record_bytes(0x09), bytes(16))
        self.assertEqual(self.project.get_unit_weapons(0x09), (0, 0))
        self.assertEqual(cleared.body_script, b"\xFF")
        self.assertEqual(cleared.fragment_script, bytes.fromhex("00 F0 00 00 FF"))
        self.assertEqual(len(self.project._undo_stack), 1)
        self.project.undo()
        self.assertNotEqual(self.project.record_bytes(0x09), bytes(16))

    def test_appearance_dialog_uses_main_page_colors_without_duplicate_editors(self) -> None:
        dialog = UnitAppearanceDialog(self.project, 0x09)
        self.addCleanup(dialog.close)
        self.assertEqual(dialog.color_buttons, [])
        self.assertEqual(dialog.palette_values, tuple(dialog.appearance.configuration[1:7]))
        self.assertEqual(dialog.values()[:6], tuple(dialog.appearance.configuration[1:7]))
        self.assertIn("颜色请在数据库机体页调整", dialog.hint.text())

    def test_body_compressed_import_reuses_equal_tiles_and_keeps_positions(self) -> None:
        dialog = UnitAppearanceDialog(self.project, 0x09)
        self.addCleanup(dialog.close)
        image = QImage(128, 128, QImage.Format.Format_RGB32)
        image.fill(WORK_PALETTE[0])
        for origin_x, origin_y in ((8, 56), (80, 120)):
            for y in range(origin_y, origin_y + 8):
                for x in range(origin_x, origin_x + 8):
                    image.setPixelColor(x, y, WORK_PALETTE[1])
        dialog._import_body_image(image)
        placements = decode_unit_body_script(dialog.body_script, 64)
        self.assertEqual(
            [(item.tile_index, item.x, item.y) for item in placements],
            [(0, 1, -8), (0, 10, 0)],
        )
        bank = dialog.values()[7]
        self.assertEqual(dialog._draft_tiles[bank * 64], (1,) * 64)
        self.assertNotIn(bank * 64 + 1, dialog._draft_tiles)
        self.assertIn("使用 1 个图库图块", dialog.status.text())
        self.assertIn("数量最少", dialog.status.text())
        self.assertNotIn(bank * 64 + 63, dialog._draft_tiles)
        self.assertIn("未使用图块保持原值", dialog.status.text())

    def test_shared_body_library_plan_reuses_existing_and_allocates_only_difference(self) -> None:
        dialog = UnitAppearanceDialog(self.project, 0x0B)
        self.addCleanup(dialog.close)
        blank = (0,) * 64
        shared = (1,) * 64
        different = (2,) * 64
        for local_index in range(128):
            dialog._draft_tiles[dialog._absolute_tile("body", local_index)] = blank
        dialog._draft_tiles[dialog._absolute_tile("body", 7)] = shared
        placements = (
            CompositionTile(0, 0, 0),
            CompositionTile(1, 1, 0),
        )

        plan = dialog._plan_shared_library_tiles(
            "body",
            (shared, different),
            placements,
            first_source_tile=0,
            allocation_indices=tuple(range(128)),
        )

        self.assertIsNotNone(plan)
        staged, remapped, reused = plan
        self.assertEqual(reused, 1)
        self.assertEqual(staged, {0: different})
        self.assertEqual([item.tile_index for item in remapped], [7, 0])

    def test_shared_fragment_library_plan_reuses_existing_and_allocates_only_difference(self) -> None:
        dialog = UnitAppearanceDialog(self.project, 0x09)
        self.addCleanup(dialog.close)
        blank = (0,) * 64
        shared = (3,) * 64
        different = tuple((x + y) % 4 for y in range(8) for x in range(8))
        for local_index in range(128):
            dialog._draft_tiles[dialog._absolute_tile("fragment", local_index)] = blank
        dialog._draft_tiles[dialog._absolute_tile("fragment", 12)] = shared
        placements = (
            FragmentTile(0, 16, 144),
            FragmentTile(1, 24, 144),
        )

        plan = dialog._plan_shared_library_tiles(
            "fragment",
            (shared, different),
            placements,
            first_source_tile=0,
            allocation_indices=tuple(range(128)),
        )

        self.assertIsNotNone(plan)
        staged, remapped, reused = plan
        self.assertEqual(reused, 1)
        self.assertEqual(staged, {0: different})
        self.assertEqual([item.tile_index for item in remapped], [12, 0])

    def test_body_padding_preserves_pixels_and_uses_side_specific_bottom_anchor(self) -> None:
        image = QImage(9, 10, QImage.Format.Format_RGB32)
        image.fill(WORK_PALETTE[0])
        image.setPixelColor(0, 0, WORK_PALETTE[3])
        image.setPixelColor(0, 9, WORK_PALETTE[1])
        image.setPixelColor(8, 9, WORK_PALETTE[2])

        friendly = pad_body_image_to_tile_grid(image, enemy=False)
        enemy = pad_body_image_to_tile_grid(image, enemy=True)

        self.assertEqual((friendly.width(), friendly.height()), (16, 16))
        self.assertEqual((enemy.width(), enemy.height()), (16, 16))
        self.assertEqual(friendly.pixelColor(0, 6), WORK_PALETTE[3])
        self.assertEqual(friendly.pixelColor(0, 15), WORK_PALETTE[1])
        self.assertEqual(friendly.pixelColor(8, 15), WORK_PALETTE[2])
        self.assertEqual(enemy.pixelColor(7, 6), WORK_PALETTE[3])
        self.assertEqual(enemy.pixelColor(7, 15), WORK_PALETTE[1])
        self.assertEqual(enemy.pixelColor(15, 15), WORK_PALETTE[2])
        self.assertEqual(friendly.pixelColor(15, 0), WORK_PALETTE[0])
        self.assertEqual(enemy.pixelColor(0, 0), WORK_PALETTE[0])
        self.assertEqual(image.pixelColor(0, 9), WORK_PALETTE[1])

    def test_body_compressed_import_pads_non_grid_source_without_resizing(self) -> None:
        dialog = UnitAppearanceDialog(self.project, 0x09)
        self.addCleanup(dialog.close)
        image = QImage(9, 10, QImage.Format.Format_RGB32)
        image.fill(WORK_PALETTE[0])
        image.setPixelColor(0, 9, WORK_PALETTE[1])
        image.setPixelColor(8, 9, WORK_PALETTE[2])

        dialog._import_body_image(image)

        placements = decode_unit_body_script(dialog.body_script, 64)
        self.assertEqual([(item.x, item.y) for item in placements], [(0, 0), (1, 0)])
        self.assertIn("原图 9×10", dialog.status.text())
        self.assertIn("左下锚点", dialog.status.text())
        self.assertIn("16×16", dialog.status.text())

    def test_body_import_searches_three_pixel_phase_before_writing(self) -> None:
        dialog = UnitAppearanceDialog(self.project, 0x09)
        self.addCleanup(dialog.close)
        image = QImage(128, 128, QImage.Format.Format_RGB32)
        image.fill(WORK_PALETTE[0])
        for y in range(120, 128):
            for x in range(1, 9):
                image.setPixelColor(x, y, WORK_PALETTE[1])

        unshifted_tiles, _placements = sparse_body_tiles(image)
        self.assertEqual(len(unshifted_tiles), 2)
        candidates = body_import_alignment_candidates(image)
        self.assertIn((-1, 0), {(shift_x, shift_y) for _image, shift_x, shift_y in candidates})
        self.assertTrue(all(abs(shift_x) <= 3 and abs(shift_y) <= 3
                            for _image, shift_x, shift_y in candidates))

        dialog._import_body_image(image)

        placements = decode_unit_body_script(dialog.body_script, 64)
        self.assertEqual(len(placements), 1)
        self.assertEqual(len({item.tile_index for item in placements}), 1)
        self.assertIn("向左 1 像素", dialog.status.text())
        self.assertIn("使用 1 个图库图块", dialog.status.text())

    def test_body_import_auto_alignment_can_be_disabled(self) -> None:
        dialog = UnitAppearanceDialog(self.project, 0x09)
        self.addCleanup(dialog.close)
        dialog.body_auto_align_check.setChecked(False)
        self.assertFalse(dialog.body_auto_align_pixels.isEnabled())
        image = QImage(128, 128, QImage.Format.Format_RGB32)
        image.fill(WORK_PALETTE[0])
        for y in range(120, 128):
            for x in range(1, 9):
                image.setPixelColor(x, y, WORK_PALETTE[1])

        dialog._import_body_image(image)

        placements = decode_unit_body_script(dialog.body_script, 64)
        self.assertEqual(len(placements), 2)
        self.assertIn("已关闭自动微调", dialog.status.text())
        self.assertIn("使用 2 个图库图块", dialog.status.text())

    def test_body_import_respects_manual_alignment_pixel_limit(self) -> None:
        image = QImage(128, 128, QImage.Format.Format_RGB32)
        image.fill(WORK_PALETTE[0])
        for y in range(120, 128):
            for x in range(2, 10):
                image.setPixelColor(x, y, WORK_PALETTE[1])

        one_pixel = UnitAppearanceDialog(self.project, 0x09)
        two_pixels = UnitAppearanceDialog(self.project, 0x09)
        self.addCleanup(one_pixel.close)
        self.addCleanup(two_pixels.close)
        one_pixel.body_auto_align_pixels.setValue(1)
        two_pixels.body_auto_align_pixels.setValue(2)

        one_pixel._import_body_image(image)
        two_pixels._import_body_image(image)

        self.assertEqual(
            len(decode_unit_body_script(one_pixel.body_script, 64)), 2
        )
        self.assertIn("1 像素范围", one_pixel.status.text())
        self.assertEqual(
            len(decode_unit_body_script(two_pixels.body_script, 64)), 1
        )
        self.assertIn("向左 2 像素", two_pixels.status.text())

    def test_enemy_body_import_pads_toward_left_and_stays_right_anchored(self) -> None:
        dialog = UnitAppearanceDialog(self.project, 0x09)
        self.addCleanup(dialog.close)
        dialog.unit_type_editor.setCurrentIndex(
            dialog.unit_type_editor.findData(0x40)
        )
        image = QImage(9, 10, QImage.Format.Format_RGB32)
        image.fill(WORK_PALETTE[0])
        image.setPixelColor(0, 9, WORK_PALETTE[1])
        image.setPixelColor(8, 9, WORK_PALETTE[2])

        dialog._import_body_image(image)

        placements = decode_unit_body_script(dialog.body_script, 64)
        self.assertEqual([(item.x, item.y) for item in placements], [(-1, 0), (0, 0)])
        self.assertIn("右下锚点", dialog.status.text())

    def test_body_compressed_import_rejects_oversize_atomically(self) -> None:
        dialog = UnitAppearanceDialog(self.project, 0x09)
        self.addCleanup(dialog.close)
        image = QImage(129, 8, QImage.Format.Format_RGB32)
        image.fill(WORK_PALETTE[1])
        original_script = dialog.body_script

        with self.assertRaisesRegex(ValueError, "不得超过 128×128"):
            dialog._import_body_image(image)

        self.assertEqual(dialog._draft_tiles, {})
        self.assertEqual(dialog.body_script, original_script)

    def test_body_tile_dictionary_is_minimum_for_repeated_patterns(self) -> None:
        image = QImage(128, 128, QImage.Format.Format_RGB32)
        image.fill(WORK_PALETTE[0])
        patterns = ((0, 0, 1), (8, 0, 2), (16, 0, 1), (0, 8, 2))
        for origin_x, origin_y, color in patterns:
            for y in range(origin_y, origin_y + 8):
                for x in range(origin_x, origin_x + 8):
                    image.setPixelColor(x, y, WORK_PALETTE[color])

        tiles, placements = sparse_body_tiles(image, first_tile=5)

        self.assertEqual(len(tiles), 2)
        self.assertEqual([item.tile_index for item in placements], [5, 6, 5, 6])
        self.assertEqual(
            decode_unit_body_script(encode_sparse_body_placements(placements), 64),
            placements,
        )

    def test_sparse_body_encoder_round_trips_non_rectangular_layout(self) -> None:
        image = QImage(128, 128, QImage.Format.Format_RGB32)
        image.fill(WORK_PALETTE[0])
        for x, y in ((4, 20), (70, 70), (71, 70)):
            image.setPixelColor(x, y, WORK_PALETTE[2])
        tiles, placements = sparse_body_tiles(image, first_tile=3)
        script = encode_sparse_body_placements(placements)
        self.assertEqual(len(tiles), 2)
        self.assertEqual(decode_unit_body_script(script, 64), placements)

    def test_fragment_optimizer_proves_minimum_for_overlapping_cover(self) -> None:
        image = QImage(128, 128, QImage.Format.Format_RGB32)
        image.fill(WORK_PALETTE[0])
        for y in range(20, 29):
            for x in range(30, 39):
                image.setPixelColor(x, y, WORK_PALETTE[3])
        result = optimize_fragment_slices(image)
        self.assertTrue(result.exact)
        self.assertEqual(len(result.tiles), 4)
        self.assertEqual(
            decode_unit_fragment_script(
                encode_compact_fragment_placements(result.placements)
            ),
            result.placements,
        )

    def test_body_import_offset_and_uncompressed_mode_change_first_tile(self) -> None:
        dialog = UnitAppearanceDialog(self.project, 0x09)
        self.addCleanup(dialog.close)
        dialog.body_compress_upload.setChecked(False)
        dialog.body_import_offset.setValue(2)
        image = QImage(16, 8, QImage.Format.Format_RGB32)
        image.fill(WORK_PALETTE[1])
        dialog._import_body_image(image)
        placements = decode_unit_body_script(dialog.body_script, 64)
        self.assertEqual([item.tile_index for item in placements], [2, 2])
        bank = dialog.values()[7]
        self.assertNotIn(bank * 64, dialog._draft_tiles)
        self.assertNotIn(bank * 64 + 1, dialog._draft_tiles)
        self.assertEqual(dialog._draft_tiles[bank * 64 + 2], (1,) * 64)
        self.assertNotIn(bank * 64 + 3, dialog._draft_tiles)
        self.assertIn("数量最少", dialog.status.text())
        self.assertIn("偏移 $02", dialog.status.text())

    def test_body_context_import_starts_at_selected_tile(self) -> None:
        dialog = UnitAppearanceDialog(self.project, 0x09)
        self.addCleanup(dialog.close)
        dialog.body_compress_upload.setChecked(False)
        dialog._select_library_tile("body", 24, 0)
        self.assertEqual(dialog._selected_body_tile, 3)
        self.assertEqual(dialog.body_import_offset.value(), 3)
        image = QImage(16, 8, QImage.Format.Format_RGB32)
        image.fill(WORK_PALETTE[1])
        for y in range(8):
            for x in range(8, 16):
                image.setPixelColor(x, y, WORK_PALETTE[2])
        with tempfile.TemporaryDirectory() as temporary:
            source = Path(temporary) / "body-from-selected.bmp"
            self.assertTrue(image.save(str(source), "BMP"))
            with patch(
                "dc_modifier.unit_appearance_dialog.QFileDialog.getOpenFileName",
                return_value=(str(source), "BMP 图片 (*.bmp)"),
            ):
                dialog._import_from_selected_tile("body")
        bank = dialog.values()[7]
        self.assertNotIn(bank * 64, dialog._draft_tiles)
        self.assertEqual(dialog._draft_tiles[bank * 64 + 3], (1,) * 64)
        self.assertEqual(dialog._draft_tiles[bank * 64 + 4], (2,) * 64)
        self.assertIn("偏移 $03", dialog.status.text())

    def test_body_import_offset_rejects_overflow_without_draft(self) -> None:
        dialog = UnitAppearanceDialog(self.project, 0x09)
        self.addCleanup(dialog.close)
        dialog.body_compress_upload.setChecked(False)
        dialog.body_import_offset.setValue(63)
        image = QImage(16, 8, QImage.Format.Format_RGB32)
        image.fill(WORK_PALETTE[1])
        for y in range(8):
            for x in range(8, 16):
                image.setPixelColor(x, y, WORK_PALETTE[2])
        with self.assertRaisesRegex(ValueError, "只剩 1 个图块"):
            dialog._import_body_image(image)
        self.assertEqual(dialog._draft_tiles, {})

    def test_large_body_import_uses_both_library_pages_from_first_page(self) -> None:
        dialog = UnitAppearanceDialog(self.project, 11)
        self.addCleanup(dialog.close)
        self.assertTrue(dialog._is_large())
        self.assertFalse(dialog.swap_body_library.isChecked())
        dialog.body_import_offset.setValue(1)
        image = QImage(128, 128, QImage.Format.Format_RGB32)
        image.fill(WORK_PALETTE[0])
        for tile_index in range(91):
            origin_x = (tile_index % 16) * 8
            origin_y = (tile_index // 16) * 8
            encoded = tile_index + 1
            for pixel in range(8):
                if encoded & (1 << pixel):
                    image.setPixelColor(
                        origin_x + pixel, origin_y, WORK_PALETTE[1]
                    )

        dialog._import_body_image(image)

        placements = decode_unit_body_script(dialog.body_script, 128)
        self.assertEqual(len(dialog._draft_tiles), 91)
        self.assertEqual({item.tile_index for item in placements}, set(range(1, 92)))
        first_bank, second_bank = dialog._library_banks("body")
        self.assertIn(first_bank * 64 + 63, dialog._draft_tiles)
        self.assertIn(second_bank * 64, dialog._draft_tiles)
        self.assertIn(second_bank * 64 + 27, dialog._draft_tiles)

    def test_puzzle_body_clear_erases_only_referenced_tiles_and_body_script(self) -> None:
        dialog = UnitAppearanceDialog(self.project, 0x09)
        self.addCleanup(dialog.close)
        original_fragment = dialog.fragment_script
        referenced = {
            placement.tile_index
            for placement in decode_unit_body_script(dialog.body_script, 64)
        }
        dialog.body_clear_button.click()

        self.assertEqual(dialog.body_script, b"\xFF")
        self.assertEqual(dialog.fragment_script, original_fragment)
        self.assertEqual(set(dialog._draft_tiles), {
            dialog._absolute_tile("body", tile) for tile in referenced
        })
        self.assertEqual(len(dialog._draft_tiles), 56)
        self.assertTrue(all(tile == (0,) * 64 for tile in dialog._draft_tiles.values()))
        self.assertIn("实际引用", dialog.status.text())
        self.assertIn("未引用的图块保持不变", dialog.status.text())

    def test_puzzle_fragment_clear_erases_only_referenced_tiles_and_script(self) -> None:
        dialog = UnitAppearanceDialog(self.project, 0x09)
        self.addCleanup(dialog.close)
        original_body = dialog.body_script
        referenced = {
            placement.tile_index
            for placement in decode_unit_fragment_script(dialog.fragment_script)
        }
        dialog.fragment_clear_button.click()

        self.assertEqual(dialog.fragment_script, bytes.fromhex("00 F0 00 00 FF"))
        self.assertEqual(dialog.body_script, original_body)
        self.assertEqual(set(dialog._draft_tiles), {
            dialog._absolute_tile("fragment", tile) for tile in referenced
        })
        self.assertEqual(len(dialog._draft_tiles), 24)
        self.assertTrue(all(tile == (0,) * 64 for tile in dialog._draft_tiles.values()))
        self.assertIn("实际引用", dialog.status.text())
        self.assertIn("未引用的图块保持不变", dialog.status.text())

    def test_main_page_clear_erases_only_referenced_tiles(self) -> None:
        dialog = UnitAppearanceDialog(self.project, 0x09)
        self.addCleanup(dialog.close)
        cleared = dialog._clear_referenced_image("body")

        self.assertEqual(cleared, 56)
        self.assertEqual(dialog.body_script, b"\xFF")
        self.assertEqual(len(dialog._draft_tiles), 56)
        self.assertIn("实际引用", dialog.status.text())

    def test_stock_rom_safe_clear_accepts_without_unit_expansion(self) -> None:
        self.assertIsNone(self.project.expansion_plan)
        before = bytes(self.project.working)
        original = read_unit_appearance(self.project, 0x09)
        referenced = {
            placement.tile_index
            for placement in decode_unit_body_script(
                original.body_script, len(original.secondary_banks) * 64
            )
        }
        original_tiles = {
            local: self.project.chr_tile_pixels(
                original.secondary_banks[local // 64] * 64 + local % 64
            )
            for local in range(len(original.secondary_banks) * 64)
        }
        dialog = UnitAppearanceDialog(self.project, 0x09)
        self.addCleanup(dialog.close)

        cleared = dialog._clear_referenced_image("body")
        with patch(
            "dc_modifier.unit_appearance_dialog.QMessageBox.warning"
        ) as warning:
            dialog.accept()

        self.assertEqual(cleared, len(referenced))
        warning.assert_not_called()
        self.assertEqual(dialog.result(), dialog.DialogCode.Accepted)
        self.assertTrue(dialog.changed)
        # The original Bank $28/$29 directory is movable.  Clearing writes an
        # independent empty script without requiring expansion metadata.
        self.assertEqual(
            read_unit_appearance(self.project, 0x09).body_script,
            b"\xFF",
        )
        for local, original_pixels in original_tiles.items():
            actual = self.project.chr_tile_pixels(dialog._absolute_tile("body", local))
            self.assertEqual(actual, (0,) * 64 if local in referenced else original_pixels)
        self.assertNotEqual(bytes(self.project.working), before)
        self.project.undo()
        self.assertEqual(bytes(self.project.working), before)

    def test_stock_rom_manual_script_edit_updates_shared_preview_group(self) -> None:
        self.assertIsNone(self.project.expansion_plan)
        before = bytes(self.project.working)
        original_bodies = tuple(
            read_unit_appearance(self.project, unit_id).body_script
            for unit_id in range(1, self.project.unit_count)
        )
        dialog = UnitAppearanceDialog(self.project, 0x09)
        self.addCleanup(dialog.close)
        dialog.body_script_view.setPlainText("FF")

        with patch(
            "dc_modifier.unit_appearance_dialog.QMessageBox.warning"
        ) as warning:
            dialog.accept()

        warning.assert_not_called()
        self.assertEqual(dialog.result(), dialog.DialogCode.Accepted)
        self.assertEqual(read_unit_appearance(self.project, 0x09).body_script, b"\xFF")
        self.assertEqual(read_unit_appearance(self.project, 0x0A).body_script, b"\xFF")
        self.assertEqual(
            tuple(
                read_unit_appearance(self.project, unit_id).body_script
                for unit_id in range(1, self.project.unit_count)
                if unit_id not in (0x09, 0x0A)
            ),
            tuple(
                script
                for unit_id, script in enumerate(original_bodies, 1)
                if unit_id not in (0x09, 0x0A)
            ),
        )
        self.assertNotEqual(bytes(self.project.working), before)
        self.project.undo()
        self.assertEqual(bytes(self.project.working), before)

    def test_body_and_fragment_replacement_sync_only_composed_preview_group(self) -> None:
        record_09 = self.project.record_bytes(0x09)
        record_0a = self.project.record_bytes(0x0A)
        appearance_09 = read_unit_appearance(self.project, 0x09)
        appearance_0a = read_unit_appearance(self.project, 0x0A)
        configuration_09 = appearance_09.configuration
        configuration_0a = appearance_0a.configuration

        body = appearance_09.body_script[:-1] + bytes.fromhex("F3 00 00 FF")
        fragment = bytes.fromhex("00 F0 00 00 FF")
        self.project.set_unit_appearance_scripts(
            0x09,
            body_script=body,
            fragment_script=fragment,
            sync_shared_previews=True,
        )

        updated_09 = read_unit_appearance(self.project, 0x09)
        updated_0a = read_unit_appearance(self.project, 0x0A)
        layout = read_stock_composition_layout(self.project.working)
        self.assertEqual(updated_09.body_script, body)
        self.assertEqual(updated_0a.body_script, body)
        self.assertEqual(updated_09.fragment_script, fragment)
        self.assertEqual(updated_0a.fragment_script, fragment)
        self.assertEqual(layout.body_pointers[0x09], layout.body_pointers[0x0A])
        self.assertEqual(
            layout.fragment_pointers[0x09], layout.fragment_pointers[0x0A]
        )
        self.assertEqual(updated_09.configuration, configuration_09)
        self.assertEqual(updated_0a.configuration, configuration_0a)
        self.assertEqual(self.project.record_bytes(0x09), record_09)
        self.assertEqual(self.project.record_bytes(0x0A), record_0a)

    def test_sync_switch_off_detaches_shared_preview_member(self) -> None:
        original = read_unit_appearance(self.project, 0x09)
        first_body = original.body_script[:-1] + bytes.fromhex("F3 00 00 FF")
        shared_fragment = bytes.fromhex("00 F0 00 00 FF")
        self.project.set_unit_appearance_scripts(
            0x09,
            body_script=first_body,
            fragment_script=shared_fragment,
            sync_shared_previews=True,
        )

        second_body = original.body_script[:-1] + bytes.fromhex("F3 08 00 FF")
        self.project.set_unit_appearance_scripts(
            0x0A,
            body_script=second_body,
            sync_shared_previews=False,
        )

        appearance_09 = read_unit_appearance(self.project, 0x09)
        appearance_0a = read_unit_appearance(self.project, 0x0A)
        layout = read_stock_composition_layout(self.project.working)
        self.assertEqual(appearance_09.body_script, first_body)
        self.assertEqual(appearance_0a.body_script, second_body)
        self.assertNotEqual(layout.body_pointers[0x09], layout.body_pointers[0x0A])
        self.assertEqual(appearance_09.fragment_script, shared_fragment)
        self.assertEqual(appearance_0a.fragment_script, shared_fragment)
        self.assertEqual(
            layout.fragment_pointers[0x09], layout.fragment_pointers[0x0A]
        )

    def test_sync_switch_on_keeps_replacement_group_linked(self) -> None:
        original = read_unit_appearance(self.project, 0x09)
        first_body = original.body_script[:-1] + bytes.fromhex("F3 00 00 FF")
        second_body = original.body_script[:-1] + bytes.fromhex("F3 08 00 FF")
        self.project.set_unit_appearance_scripts(
            0x09,
            body_script=first_body,
            sync_shared_previews=True,
        )
        self.project.set_unit_appearance_scripts(
            0x0A,
            body_script=second_body,
            sync_shared_previews=True,
        )

        layout = read_stock_composition_layout(self.project.working)
        self.assertEqual(
            read_unit_appearance(self.project, 0x09).body_script, second_body
        )
        self.assertEqual(
            read_unit_appearance(self.project, 0x0A).body_script, second_body
        )
        self.assertEqual(layout.body_pointers[0x09], layout.body_pointers[0x0A])

    def test_stock_native_script_growth_moves_directory_and_reopens(self) -> None:
        before_status = self.project.unit_composition_pool_status()
        original = read_unit_appearance(self.project, 0x09)
        other_fragment = read_unit_appearance(self.project, 0x0A).fragment_script
        grown = original.body_script[:-1] + bytes.fromhex("F3 00 00 FF")

        self.project.set_unit_appearance_scripts(0x09, body_script=grown)

        after_status = self.project.unit_composition_pool_status()
        self.assertGreater(after_status.body_used, before_status.body_used)
        self.assertEqual(after_status.fragment_used, before_status.fragment_used)
        self.assertEqual(read_unit_appearance(self.project, 0x09).body_script, grown)
        self.assertEqual(
            read_unit_appearance(self.project, 0x0A).fragment_script,
            other_fragment,
        )
        self.assertFalse(
            [issue for issue in self.project.validate() if issue.severity == "error"]
        )
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "stock-variable-unit-scripts.nes"
            self.project.save_as(path, make_backup=False)
            reopened = RomProject.load(path)
        self.assertIsNone(reopened.expansion_plan)
        self.assertEqual(read_unit_appearance(reopened, 0x09).body_script, grown)
        self.assertEqual(reopened.unit_composition_pool_status(), after_status)

    def test_database_cancel_restores_confirmed_main_page_clear(self) -> None:
        before = bytes(self.project.working)
        original = read_unit_appearance(self.project, 0x09)
        database = DatabaseDialog(self.project)
        self.addCleanup(database.close)
        database.show()
        self.app.processEvents()
        page = database.unit_page
        memory_panel = database._database_memory_panels[0]
        before_memory_summary = memory_panel.summary.text()
        for row in range(page.records.count()):
            if int(page.records.item(row).data(256)) == 0x09:
                page.records.setCurrentRow(row)
                break
        self.app.processEvents()
        with patch.object(QMessageBox, "question") as question:
            page._clear_appearance_from_main("body")
        question.assert_not_called()
        self.assertEqual(read_unit_appearance(self.project, 0x09).body_script, b"\xFF")
        self.assertNotEqual(bytes(self.project.working), before)
        self.assertNotEqual(memory_panel.summary.text(), before_memory_summary)

        database.cancel_button.click()
        self.app.processEvents()

        self.assertEqual(bytes(self.project.working), before)
        restored = read_unit_appearance(self.project, 0x09)
        self.assertEqual(restored.body_script, original.body_script)
        self.assertEqual(restored.fragment_script, original.fragment_script)
        self.assertEqual(memory_panel.summary.text(), before_memory_summary)

    def test_database_main_fragment_clear_is_immediate_without_prompt(self) -> None:
        database = DatabaseDialog(self.project)
        self.addCleanup(database.close)
        database.show()
        self.app.processEvents()
        page = database.unit_page
        for row in range(page.records.count()):
            if int(page.records.item(row).data(256)) == 0x09:
                page.records.setCurrentRow(row)
                break
        self.app.processEvents()

        with patch.object(QMessageBox, "question") as question:
            page.fragment_clear_button.click()
        self.app.processEvents()

        question.assert_not_called()
        self.assertEqual(
            decode_unit_fragment_script(
                read_unit_appearance(self.project, 0x09).fragment_script
            ),
            (),
        )

    def test_database_cancel_restores_confirmed_body_puzzle_clear_session(self) -> None:
        before = bytes(self.project.working)
        before_allocations = self.project.resource_allocator.allocations
        before_undo = tuple(self.project._undo_stack)
        before_redo = tuple(self.project._redo_stack)
        before_status = self.project.unit_composition_pool_status()
        original = read_unit_appearance(self.project, 0x09)
        database = DatabaseDialog(self.project)
        self.addCleanup(database.close)
        database.show()
        self.app.processEvents()
        page = database.unit_page
        for row in range(page.records.count()):
            if int(page.records.item(row).data(256)) == 0x09:
                page.records.setCurrentRow(row)
                break
        self.app.processEvents()

        def clear_and_confirm(child: UnitAppearanceDialog) -> int:
            child._clear_referenced_image("body")
            child.accept()
            return child.result()

        with patch.object(UnitAppearanceDialog, "exec", clear_and_confirm):
            page._edit_appearance(0)

        self.assertEqual(read_unit_appearance(self.project, 0x09).body_script, b"\xFF")
        self.assertNotEqual(bytes(self.project.working), before)
        self.assertNotEqual(tuple(self.project._undo_stack), before_undo)

        database.cancel_button.click()
        self.app.processEvents()

        self.assertEqual(bytes(self.project.working), before)
        self.assertEqual(self.project.resource_allocator.allocations, before_allocations)
        self.assertEqual(tuple(self.project._undo_stack), before_undo)
        self.assertEqual(tuple(self.project._redo_stack), before_redo)
        self.assertEqual(self.project.unit_composition_pool_status(), before_status)
        restored = read_unit_appearance(self.project, 0x09)
        self.assertEqual(restored.body_script, original.body_script)
        self.assertEqual(restored.fragment_script, original.fragment_script)
        reference_project = RomProject.load(DEFAULT_ROM)
        reference_appearance = read_unit_appearance(reference_project, 0x09)
        expected_preview = render_unit_battle_preview(
            reference_project, reference_appearance
        ).scaled(
            page.body_preview.size(),
            Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.FastTransformation,
        )
        self.assertEqual(page.body_preview.pixmap().toImage(), expected_preview)

    def test_legacy_image_clear_cancel_keeps_library_and_scripts_unchanged(self) -> None:
        dialog = UnitAppearanceDialog(self.project, 0x09)
        self.addCleanup(dialog.close)
        original_scripts = (dialog.body_script, dialog.fragment_script)

        with patch(
            "dc_modifier.unit_appearance_dialog.QMessageBox.question",
            return_value=QMessageBox.StandardButton.No,
        ):
            dialog._clear_image("body")
            dialog._clear_image("fragment")

        self.assertEqual(dialog._draft_tiles, {})
        self.assertEqual((dialog.body_script, dialog.fragment_script), original_scripts)

    def test_fragment_import_offset_preserves_preceding_tiles(self) -> None:
        dialog = UnitAppearanceDialog(self.project, 0x09)
        self.addCleanup(dialog.close)
        dialog.fragment_compress_upload.setChecked(False)
        dialog.fragment_import_offset.setValue(2)
        image = QImage(64, 128, QImage.Format.Format_RGB32)
        image.fill(WORK_PALETTE[2])
        with tempfile.TemporaryDirectory() as temporary:
            source = Path(temporary) / "fragments.bmp"
            self.assertTrue(image.save(str(source), "BMP"))
            with patch(
                "dc_modifier.unit_appearance_dialog.QFileDialog.getOpenFileName",
                return_value=(str(source), "BMP 图片 (*.bmp)"),
            ):
                dialog._import_library("fragment")
        bank = dialog.values()[6] & 0xFE
        self.assertNotIn(bank * 64, dialog._draft_tiles)
        self.assertNotIn(bank * 64 + 1, dialog._draft_tiles)
        self.assertEqual(len(dialog._draft_tiles), 126)
        self.assertEqual(dialog._draft_tiles[bank * 64 + 2], (2,) * 64)
        self.assertIn("偏移 $02", dialog.status.text())

    def test_fragment_context_import_starts_at_selected_tile(self) -> None:
        dialog = UnitAppearanceDialog(self.project, 0x09)
        self.addCleanup(dialog.close)
        dialog.fragment_compress_upload.setChecked(True)
        dialog._select_library_tile("fragment", 16, 8)
        self.assertEqual(dialog._selected_fragment_tile, 0x12)
        self.assertEqual(dialog.fragment_import_offset.value(), 0x12)
        image = QImage(128, 128, QImage.Format.Format_RGB32)
        image.fill(WORK_PALETTE[0])
        image.setPixelColor(40, 64, WORK_PALETTE[3])
        with tempfile.TemporaryDirectory() as temporary:
            source = Path(temporary) / "fragment-from-selected.bmp"
            self.assertTrue(image.save(str(source), "BMP"))
            with patch(
                "dc_modifier.unit_appearance_dialog.QFileDialog.getOpenFileName",
                return_value=(str(source), "BMP 图片 (*.bmp)"),
            ), patch(
                "dc_modifier.unit_appearance_dialog.UnitAppearanceDialog."
                "_ask_legacy_fragment_import_position",
                return_value=True,
            ), patch(
                "dc_modifier.unit_appearance_dialog.UnitAppearanceDialog."
                "_prompt_legacy_fragment_tile_index",
                return_value=("12", True),
            ) as prompt_index:
                dialog._import_from_selected_tile("fragment")
        self.assertTrue(dialog.show_fragment_numbers.isChecked())
        prompt_index.assert_called_once_with(0x12)
        bank = dialog.values()[6] & 0xFE
        self.assertEqual(list(dialog._draft_tiles), [bank * 64 + 0x12])
        self.assertEqual(
            decode_unit_fragment_script(dialog.fragment_script)[0].tile_index,
            0x12,
        )
        self.assertIn("偏移 $12", dialog.status.text())

    def test_fragment_compressed_import_prompts_for_every_legacy_tile(self) -> None:
        dialog = UnitAppearanceDialog(self.project, 0x09)
        self.addCleanup(dialog.close)
        dialog.fragment_compress_upload.setChecked(True)
        image = QImage(128, 128, QImage.Format.Format_RGB32)
        image.fill(WORK_PALETTE[0])
        image.setPixelColor(8, 16, WORK_PALETTE[1])
        image.setPixelColor(80, 96, WORK_PALETTE[2])
        responses = iter((("2A", True), ("05", True)))
        visible_drafts: list[tuple[int, tuple[int, ...]]] = []

        def answer_with_live_preview(_default: int) -> tuple[str, bool]:
            visible_drafts.append(
                (dialog._selected_fragment_tile, tuple(dialog._draft_tiles))
            )
            return next(responses)

        with patch(
            "dc_modifier.unit_appearance_dialog.UnitAppearanceDialog."
            "_ask_legacy_fragment_import_position",
            return_value=True,
        ), patch(
            "dc_modifier.unit_appearance_dialog.UnitAppearanceDialog."
            "_prompt_legacy_fragment_tile_index",
            side_effect=answer_with_live_preview,
        ) as prompt_index:
            dialog._import_fragment_image(image, choose_tiles=True)

        self.assertEqual(prompt_index.call_count, 2)
        self.assertEqual(prompt_index.call_args_list, [call(0x00), call(0x2B)])
        bank = dialog.values()[6] & 0xFE
        self.assertEqual(visible_drafts[0], (0x00, ()))
        self.assertEqual(visible_drafts[1], (0x2A, (bank * 64 + 0x2A,)))
        self.assertEqual(set(dialog._draft_tiles), {bank * 64 + 0x2A, bank * 64 + 0x05})
        self.assertEqual(
            [item.tile_index for item in decode_unit_fragment_script(dialog.fragment_script)],
            [0x2A, 0x05],
        )
        self.assertIn("逐项指定图库编号", dialog.status.text())

    def test_fragment_custom_tile_prompt_cancel_is_atomic(self) -> None:
        dialog = UnitAppearanceDialog(self.project, 0x09)
        self.addCleanup(dialog.close)
        dialog.fragment_compress_upload.setChecked(True)
        image = QImage(128, 128, QImage.Format.Format_RGB32)
        image.fill(WORK_PALETTE[0])
        image.setPixelColor(8, 16, WORK_PALETTE[1])
        image.setPixelColor(80, 96, WORK_PALETTE[2])
        before_script = dialog.fragment_script
        before_tiles = dict(dialog._draft_tiles)

        with patch(
            "dc_modifier.unit_appearance_dialog.UnitAppearanceDialog."
            "_ask_legacy_fragment_import_position",
            return_value=True,
        ), patch(
            "dc_modifier.unit_appearance_dialog.UnitAppearanceDialog."
            "_prompt_legacy_fragment_tile_index",
            side_effect=(("2A", True), ("", False)),
        ):
            dialog._import_fragment_image(image, choose_tiles=True)

        self.assertEqual(dialog.fragment_script, before_script)
        self.assertEqual(dialog._draft_tiles, before_tiles)

    def test_fragment_add_tile_supports_current_or_hex_library_index(self) -> None:
        dialog = UnitAppearanceDialog(self.project, 0x09)
        self.addCleanup(dialog.close)
        original = decode_unit_fragment_script(dialog.fragment_script)
        dialog._selected_fragment_tile = 0x19
        with patch(
            "dc_modifier.unit_appearance_dialog.QMessageBox.question",
            return_value=QMessageBox.StandardButton.No,
        ):
            dialog._add_fragment_tile()
        current = decode_unit_fragment_script(dialog.fragment_script)
        self.assertEqual(len(current), len(original) + 1)
        self.assertEqual(current[-1].tile_index, 0x19)

        with patch(
            "dc_modifier.unit_appearance_dialog.QMessageBox.question",
            return_value=QMessageBox.StandardButton.Yes,
        ), patch(
            "dc_modifier.unit_appearance_dialog.QInputDialog.getText",
            return_value=("2A", True),
        ):
            dialog._add_fragment_tile()
        chosen = decode_unit_fragment_script(dialog.fragment_script)
        self.assertEqual(len(chosen), len(original) + 2)
        self.assertEqual(chosen[-1].tile_index, 0x2A)
        self.assertEqual(dialog._selected_fragment_tile, 0x2A)
        self.assertIn("继续添加", dialog.status.text())

        before_cancel = dialog.fragment_script
        with patch(
            "dc_modifier.unit_appearance_dialog.QMessageBox.question",
            return_value=QMessageBox.StandardButton.Cancel,
        ):
            dialog._add_fragment_tile()
        self.assertEqual(dialog.fragment_script, before_cancel)

    def test_fragment_uncompressed_import_rejects_non_64x128_image(self) -> None:
        dialog = UnitAppearanceDialog(self.project, 0x09)
        self.addCleanup(dialog.close)
        dialog.fragment_compress_upload.setChecked(False)
        image = QImage(16, 16, QImage.Format.Format_RGB32)
        image.fill(WORK_PALETTE[1])
        with tempfile.TemporaryDirectory() as temporary:
            source = Path(temporary) / "invalid-fragments.bmp"
            self.assertTrue(image.save(str(source), "BMP"))
            with patch(
                "dc_modifier.unit_appearance_dialog.QFileDialog.getOpenFileName",
                return_value=(str(source), "BMP 图片 (*.bmp)"),
            ), patch(
                "dc_modifier.unit_appearance_dialog.QMessageBox.warning"
            ) as warning:
                dialog._import_library("fragment")
        warning.assert_called_once()
        self.assertIn("64×128", warning.call_args.args[2])
        self.assertEqual(dialog._draft_tiles, {})

    def test_fragment_compressed_import_respects_remaining_offset_capacity(self) -> None:
        dialog = UnitAppearanceDialog(self.project, 0x09)
        self.addCleanup(dialog.close)
        dialog.fragment_compress_upload.setChecked(True)
        dialog.fragment_import_offset.setValue(127)
        image = QImage(128, 128, QImage.Format.Format_RGB32)
        image.fill(WORK_PALETTE[0])
        image.setPixelColor(40, 64, WORK_PALETTE[3])
        dialog._import_fragment_image(image)
        bank = dialog.values()[6] & 0xFE
        self.assertEqual(list(dialog._draft_tiles), [bank * 64 + 127])
        self.assertIn("偏移 $7F", dialog.status.text())
        self.assertIn("1 个图块", dialog.status.text())
        placements = decode_unit_fragment_script(dialog.fragment_script)
        self.assertEqual(len(placements), 1)
        self.assertEqual(placements[0].tile_index, 0x7F)

    def test_compressed_import_preserves_unused_library_tail(self) -> None:
        body = UnitAppearanceDialog(self.project, 0x09)
        fragment = UnitAppearanceDialog(self.project, 0x09)
        self.addCleanup(body.close)
        self.addCleanup(fragment.close)
        image = QImage(128, 128, QImage.Format.Format_RGB32)
        image.fill(WORK_PALETTE[0])
        image.setPixelColor(40, 64, WORK_PALETTE[3])

        body._import_body_image(image)
        fragment._import_fragment_image(image)

        body_bank = body.values()[7]
        fragment_bank = fragment.values()[6] & 0xFE
        self.assertEqual(list(body._draft_tiles), [body_bank * 64])
        self.assertLessEqual(len(fragment._draft_tiles), 1)
        self.assertNotIn(body_bank * 64 + 1, body._draft_tiles)
        self.assertNotIn(fragment_bank * 64 + 1, fragment._draft_tiles)
        self.assertIn("未使用图块保持原值", body.status.text())
        self.assertIn("未使用图块保持原值", fragment.status.text())

    def test_legacy_uncompressed_main_upload_is_preview_only(self) -> None:
        dialog = UnitAppearanceDialog(self.project, 0x09)
        self.addCleanup(dialog.close)
        dialog.body_compress_upload.setChecked(False)
        image = QImage(128, 128, QImage.Format.Format_RGB32)
        image.fill(WORK_PALETTE[2])
        original_scripts = (dialog.body_script, dialog.fragment_script)
        with tempfile.TemporaryDirectory() as temporary:
            source = Path(temporary) / "legacy-preview.bmp"
            self.assertTrue(image.save(str(source), "BMP"))
            with patch(
                "dc_modifier.unit_appearance_dialog.QFileDialog.getOpenFileName",
                return_value=(str(source), "BMP 图片 (*.bmp)"),
            ):
                dialog._import_library("body", strict_legacy=True)

        self.assertIsNotNone(dialog._transient_body_preview)
        self.assertEqual(dialog._draft_tiles, {})
        self.assertEqual((dialog.body_script, dialog.fragment_script), original_scripts)
        self.assertIn("仅预览", dialog.status.text())
        self.assertIn("不会写入", dialog.status.text())

    def test_main_body_upload_accepts_non_grid_source_and_builds_composition(self) -> None:
        dialog = UnitAppearanceDialog(self.project, 0x09)
        self.addCleanup(dialog.close)
        image = QImage(9, 10, QImage.Format.Format_RGB32)
        image.fill(WORK_PALETTE[0])
        image.setPixelColor(8, 9, WORK_PALETTE[2])
        with tempfile.TemporaryDirectory() as temporary:
            source = Path(temporary) / "body-non-grid.bmp"
            self.assertTrue(image.save(str(source), "BMP"))
            with patch(
                "dc_modifier.unit_appearance_dialog.QFileDialog.getOpenFileName",
                return_value=(str(source), "BMP 图片 (*.bmp)"),
            ), patch(
                "dc_modifier.unit_appearance_dialog.QMessageBox.warning"
            ) as warning:
                dialog._import_library("body", strict_legacy=True)

        warning.assert_not_called()
        placements = decode_unit_body_script(dialog.body_script, 64)
        self.assertEqual([(item.x, item.y) for item in placements], [(1, 0)])
        self.assertIn("左下锚点", dialog.status.text())

    def test_legacy_main_upload_rejects_non_128_source_before_draft(self) -> None:
        dialog = UnitAppearanceDialog(self.project, 0x09)
        self.addCleanup(dialog.close)
        image = QImage(64, 64, QImage.Format.Format_RGB32)
        image.fill(WORK_PALETTE[1])
        with tempfile.TemporaryDirectory() as temporary:
            source = Path(temporary) / "wrong-size.bmp"
            self.assertTrue(image.save(str(source), "BMP"))
            with patch(
                "dc_modifier.unit_appearance_dialog.QFileDialog.getOpenFileName",
                return_value=(str(source), "BMP 图片 (*.bmp)"),
            ), patch(
                "dc_modifier.unit_appearance_dialog.QMessageBox.warning"
            ) as warning:
                dialog._import_library("fragment", strict_legacy=True)

        warning.assert_called_once()
        self.assertIn("128×128", warning.call_args.args[2])
        self.assertEqual(dialog._draft_tiles, {})
        self.assertIsNone(dialog._transient_fragment_preview)

    def test_fragment_compressed_import_rejects_resizing(self) -> None:
        dialog = UnitAppearanceDialog(self.project, 0x09)
        self.addCleanup(dialog.close)
        image = QImage(64, 64, QImage.Format.Format_RGB32)
        image.fill(WORK_PALETTE[1])
        original_script = dialog.fragment_script

        with self.assertRaisesRegex(ValueError, "原始 128×128"):
            dialog._import_fragment_image(image)

        self.assertEqual(dialog._draft_tiles, {})
        self.assertEqual(dialog.fragment_script, original_script)

    def test_fragment_compressed_overflow_is_atomic(self) -> None:
        dialog = UnitAppearanceDialog(self.project, 0x09)
        self.addCleanup(dialog.close)
        dialog.fragment_compress_upload.setChecked(True)
        dialog.fragment_import_offset.setValue(127)
        image = QImage(128, 128, QImage.Format.Format_RGB32)
        image.fill(WORK_PALETTE[0])
        image.setPixelColor(8, 16, WORK_PALETTE[1])
        image.setPixelColor(80, 96, WORK_PALETTE[2])
        original_script = dialog.fragment_script
        with self.assertRaisesRegex(ValueError, "超过"):
            dialog._import_fragment_image(image)
        self.assertEqual(dialog._draft_tiles, {})
        self.assertEqual(dialog.fragment_script, original_script)

    def test_appearance_bmp_export_matches_legacy_library_dimensions(self) -> None:
        dialog = UnitAppearanceDialog(self.project, 0x09)
        self.addCleanup(dialog.close)
        tile = QImage.fromData(dialog._export_bitmap_bytes("body", selected_only=True), "BMP")
        body = QImage.fromData(dialog._export_bitmap_bytes("body"), "BMP")
        fragments = QImage.fromData(dialog._export_bitmap_bytes("fragment"), "BMP")
        self.assertFalse(tile.isNull())
        self.assertEqual((tile.width(), tile.height()), (8, 8))
        self.assertEqual((body.width(), body.height()), (64, 64))
        self.assertEqual((fragments.width(), fragments.height()), (64, 128))
        self.assertTrue(dialog.body_export_button.isEnabled())
        self.assertTrue(dialog.fragment_export_button.isEnabled())

    def test_body_8x8_bmp_import_updates_only_the_selected_tile(self) -> None:
        dialog = UnitAppearanceDialog(self.project, 0x09)
        self.addCleanup(dialog.close)
        original_script = dialog.body_script
        image = QImage(8, 8, QImage.Format.Format_RGB32)
        image.fill(QColor(*LEGACY_MATERIAL_PALETTE_RGB[2]))
        with tempfile.TemporaryDirectory() as temporary:
            source = Path(temporary) / "tile.bmp"
            self.assertTrue(image.save(str(source), "BMP"))
            with patch(
                "dc_modifier.unit_appearance_dialog.QFileDialog.getOpenFileName",
                return_value=(str(source), "BMP 图片 (*.bmp)"),
            ):
                dialog._import_library("body")
        self.assertEqual(len(dialog._draft_tiles), 1)
        self.assertEqual(next(iter(dialog._draft_tiles.values())), (2,) * 64)
        self.assertEqual(dialog.body_script, original_script)

    def test_appearance_reference_settings_follow_legacy_body_fragment_split(self) -> None:
        dialog = UnitAppearanceDialog(self.project, 0x09)
        self.addCleanup(dialog.close)
        self.assertEqual(dialog.bank_labels[1].text(), "图库地址1")
        self.assertIn("图库地址2", dialog.bank_labels[2].text())
        self.assertIs(dialog.bank_editors[0].parentWidget(), dialog.bank_labels[0].parentWidget())
        self.assertEqual(dialog.body_selection.text(), "当前选择的图块编号：00")
        bank = dialog.bank_editors[1].value()
        self.assertIn(f"[{bank:02X}]{bank:03d}:", dialog.bank_editors[1].currentText())

    def test_body_page_uses_compact_legacy_frames_without_button_overlap(self) -> None:
        dialog = UnitAppearanceDialog(self.project, 0x09)
        self.addCleanup(dialog.close)
        dialog.show()
        self.app.processEvents()
        self.assertEqual(dialog.body_library_group.title(), "图库（提示：左键选择图块）")
        self.assertEqual(
            dialog.body_composition_group.title(),
            "效果图（提示：左键编辑图块，右键删除图块）",
        )
        self.assertLessEqual(dialog.minimumSizeHint().width(), 704)
        self.assertEqual((dialog.width(), dialog.height()), (740, 700))
        self.assertEqual(dialog.body_library_group.height(), 510)
        self.assertEqual(dialog.body_composition_group.height(), 510)
        self.assertEqual(dialog.body_validate_button.text(), "查看效果")
        self.assertGreaterEqual(
            dialog.body_validate_button.width(),
            dialog.body_validate_button.sizeHint().width(),
        )
        self.assertEqual(
            [button.text() for button in dialog.body_template_buttons],
            ["8×8", "7×9", "9×7", "10×6"],
        )
        preview = dialog.body_composition_preview.geometry()
        left = dialog.body_move_buttons["left"].geometry()
        right = dialog.body_move_buttons["right"].geometry()
        self.assertLess(left.right(), preview.left())
        self.assertLess(preview.right(), right.left())

    def test_library_right_click_menu_matches_legacy_operations(self) -> None:
        dialog = UnitAppearanceDialog(self.project, 0x09)
        self.addCleanup(dialog.close)
        dialog._select_library_tile("body", 12, 4)
        self.assertEqual(dialog._selected_body_tile, 1)
        self.assertEqual(dialog.body_selection.text(), "当前选择的图块编号：01")
        captured = []

        def capture(menu, _point):
            captured.extend(action.text() for action in menu.actions() if not action.isSeparator())

        with patch("dc_modifier.unit_appearance_dialog.QMenu.popup", new=capture):
            dialog._show_library_menu("body", QPoint(10, 10))
        self.assertEqual(captured, [
            "从所选图块导入图片\tCtrl+D",
            "复制图块\tCtrl+C",
            "粘贴图块\tCtrl+V",
            "删除图块\tCtrl+S",
            "复制图库",
            "粘贴图库",
            "清空图库\tCtrl+G",
        ])

    def test_legacy_composition_clicks_edit_and_delete_the_hit_tile(self) -> None:
        dialog = UnitAppearanceDialog(self.project, 0x09)
        self.addCleanup(dialog.close)
        placements = decode_unit_body_script(dialog.body_script, 64)
        target = None
        for placement in placements:
            x = placement.x * 8 + 4
            y = (placement.y + 15) * 8 + 4
            _body, body_hits, _fragments, fragment_hits = dialog._composition_hits(x, y)
            if body_hits and not fragment_hits:
                target = (placement, x, y)
                break
        self.assertIsNotNone(target)
        placement, x, y = target
        opened = []
        dialog._edit_tile = lambda kind, local_tile=None: opened.append((kind, local_tile))
        dialog._composition_pressed(x, y, Qt.MouseButton.LeftButton.value)
        self.assertEqual(opened, [("body", placement.tile_index)])
        before_count = len(placements)
        dialog._composition_pressed(x, y, Qt.MouseButton.RightButton.value)
        self.assertEqual(len(decode_unit_body_script(dialog.body_script, 64)), before_count - 1)

    def test_fragment_reference_page_uses_linear_16_column_order_and_flips_hit(self) -> None:
        dialog = UnitAppearanceDialog(self.project, 0x09)
        self.addCleanup(dialog.close)
        self.assertEqual(dialog.fragment_add_tile_button.text(), "添加图块")
        self.assertTrue(dialog.fragment_add_tile_button.isEnabled())
        dialog._select_library_tile("fragment", 72, 8)
        self.assertEqual(dialog._selected_fragment_tile, 0x19)
        fragments = decode_unit_fragment_script(dialog.fragment_script)
        origin_x = 0x78 if dialog._type_code() & 0x40 else 0
        target = None
        for placement in fragments:
            x = placement.x + origin_x + 4
            y = placement.y + 4
            if 0 <= x < 128 and 0 <= y < 128:
                _body, _body_hits, current, hits = dialog._composition_hits(x, y)
                if hits:
                    target = (x, y, hits[-1], current[hits[-1]].flip_horizontal)
                    break
        self.assertIsNotNone(target)
        x, y, index, before_flip = target
        dialog._fragment_composition_pressed(x, y, Qt.MouseButton.RightButton.value)
        updated = decode_unit_fragment_script(dialog.fragment_script)
        self.assertEqual(len(updated), len(fragments))
        self.assertEqual(updated[index].flip_horizontal, not before_flip)

    def test_fragment_library_and_preview_match_reference_composition(self) -> None:
        dialog = UnitAppearanceDialog(self.project, 0x09)
        self.addCleanup(dialog.close)
        values = dialog.values()
        fragment_bank = values[6] & 0xFE
        raw = render_chr_banks(
            dialog._draft_project(),
            (fragment_bank, fragment_bank + 1),
            values[3:6],
            columns=2,
            display_palette=WORK_PALETTE,
        )
        linear = legacy_fragment_library_image(raw, 0, show_numbers=False)
        # Tile $08 is the first tile of the second source row, but the old
        # window places it in column 8 of the first displayed row.
        self.assertEqual(linear.pixelColor(8 * 24 + 12, 12), raw.pixelColor(4, 12))
        library_colors = {
            dialog.fragment_library_preview.pixmap().toImage().pixelColor(x, y).name()
            for y in range(dialog.fragment_library_preview.pixmap().height())
            for x in range(dialog.fragment_library_preview.pixmap().width())
        }
        self.assertFalse(
            (
                {palette_color(value).name() for value in values[3:6]}
                - {color.name() for color in WORK_PALETTE}
            )
            & library_colors
        )
        self.assertTrue(
            {color.name() for color in WORK_PALETTE[1:]} & library_colors
        )
        preview_appearance = replace(
            dialog.appearance,
            configuration=bytes((dialog._type_code(), *values)),
            body_script=dialog.body_script,
            fragment_script=dialog.fragment_script,
        )
        expected = legacy_composition_image(
            render_unit_battle_preview(
                dialog._draft_project(),
                preview_appearance,
                show_body=True,
                show_fragments=True,
                body_display_palette=WORK_PALETTE,
                fragment_display_palette=(
                    WORK_PALETTE[0],
                    *(palette_color(value) for value in values[3:6]),
                ),
            ),
            preview_appearance,
            show_numbers=False,
            include_body=True,
            include_fragments=True,
        )
        self.assertEqual(
            dialog.fragment_composition_preview.pixmap().toImage(), expected
        )
        old_single_palette = legacy_composition_image(
            render_unit_battle_preview(
                dialog._draft_project(),
                preview_appearance,
                show_body=True,
                show_fragments=True,
                display_palette=WORK_PALETTE,
            ),
            preview_appearance,
            show_numbers=False,
            include_body=True,
            include_fragments=True,
        )
        self.assertNotEqual(expected, old_single_palette)
        preview_colors = {
            dialog.fragment_composition_preview.pixmap().toImage().pixelColor(x, y).name()
            for y in range(dialog.fragment_composition_preview.pixmap().height())
            for x in range(dialog.fragment_composition_preview.pixmap().width())
        }
        self.assertTrue(
            {color.name() for color in WORK_PALETTE[1:]} & preview_colors
        )
        self.assertTrue(
            {palette_color(value).name() for value in values[3:6]} & preview_colors
        )
        clean_effect = dialog.fragment_composition_preview.pixmap().toImage()
        library_without_numbers = dialog.fragment_library_preview.pixmap().toImage()
        dialog.show_fragment_numbers.setChecked(True)
        self.app.processEvents()
        self.assertEqual(
            dialog.fragment_composition_preview.pixmap().toImage(), clean_effect
        )
        self.assertNotEqual(
            dialog.fragment_library_preview.pixmap().toImage(),
            library_without_numbers,
        )

        placements = decode_unit_fragment_script(dialog.fragment_script)
        selected_row = min(3, len(placements) - 1)
        dialog.fragment_placements_view.setCurrentRow(selected_row)
        self.app.processEvents()
        selected_tile = placements[selected_row].tile_index
        self.assertTrue(dialog.fragment_placements_view.currentItem().isSelected())
        self.assertEqual(dialog._selected_fragment_tile, selected_tile)
        selected_x = (selected_tile % 16) * 24
        selected_y = (selected_tile // 16) * 24
        selected_library = dialog.fragment_library_preview.pixmap().toImage()
        self.assertEqual(
            selected_library.pixelColor(selected_x, selected_y).name(), "#ff3048"
        )

    def test_chr_tile_editor_exports_legacy_8x8_bmp(self) -> None:
        editor = ChrTileEditorDialog(tuple(index % 4 for index in range(64)), "test")
        self.addCleanup(editor.close)
        image = QImage.fromData(editor._bitmap_bytes(), "BMP")
        self.assertEqual((image.width(), image.height()), (8, 8))
        self.assertEqual(image.pixelColor(0, 0), QColor(*LEGACY_MATERIAL_PALETTE_RGB[0]))
        self.assertEqual(image.pixelColor(1, 0), QColor(*LEGACY_MATERIAL_PALETTE_RGB[1]))

    def test_unit_type_is_dropdown_only_and_small_to_large_is_safely_relocated(self) -> None:
        unit_id = 0x09
        before = bytes(self.project.working)
        dialog = UnitAppearanceDialog(self.project, unit_id)
        self.addCleanup(dialog.close)
        self.assertFalse(dialog.unit_type_editor.isEditable())
        self.assertEqual(dialog.unit_type_editor.count(), 4)
        self.assertFalse(dialog.bank_editors[2].isEnabled())
        dialog.unit_type_editor.setCurrentIndex(dialog.unit_type_editor.findData(0x80))
        self.assertTrue(dialog.bank_editors[2].isEnabled())
        dialog.accept()
        updated = read_unit_appearance(self.project, unit_id)
        self.assertEqual(updated.configuration[0], 0x80)
        self.assertEqual(len(updated.configuration), 10)
        self.assertTrue(dialog.changed)
        self.project.undo()
        self.assertEqual(bytes(self.project.working), before)

    def test_puzzle_dialog_preserves_large_unit_captain_flag(self) -> None:
        unit_id = 0x0B
        appearance = read_unit_appearance(self.project, unit_id)
        configuration = bytearray(appearance.configuration)
        configuration[0] = (configuration[0] & 0xC0) | 0x20
        self.project.set_unit_appearance_configuration(unit_id, bytes(configuration))

        dialog = UnitAppearanceDialog(self.project, unit_id)
        self.addCleanup(dialog.close)
        dialog.accept()

        self.assertEqual(dialog.result(), dialog.DialogCode.Accepted)
        self.assertEqual(
            read_unit_appearance(self.project, unit_id).configuration[0] & 0xE0,
            configuration[0] & 0xE0,
        )

        small = read_unit_appearance(self.project, 0x09)
        invalid = bytearray(small.configuration)
        invalid[0] = (invalid[0] & 0xC0) | 0x20
        with self.assertRaisesRegex(ValueError, "只适用于大型机"):
            self.project.set_unit_appearance_configuration(0x09, bytes(invalid))

    def test_large_to_small_type_rebuilds_an_invalid_second_bank_script(self) -> None:
        dialog = UnitAppearanceDialog(self.project, 11)
        self.addCleanup(dialog.close)
        self.assertTrue(any(
            placement.tile_index >= 64
            for placement in decode_unit_body_script(dialog.body_script, 128)
        ))
        dialog.unit_type_editor.setCurrentIndex(dialog.unit_type_editor.findData(0x00))
        placements = decode_unit_body_script(dialog.body_script, 64)
        self.assertEqual(len(placements), 64)
        self.assertFalse(dialog.bank_editors[2].isEnabled())
        self.assertIn("8×8单图库脚本", dialog.status.text())

    def test_composition_dialog_uses_fixed_legacy_material_palette(self) -> None:
        appearance = read_unit_appearance(self.project, 0x09)
        normal = render_unit_battle_preview(self.project, appearance)
        material = render_unit_battle_preview(
            self.project, appearance, display_palette=WORK_PALETTE
        )
        normal_colors = {
            normal.pixelColor(x, y).name()
            for y in range(normal.height()) for x in range(normal.width())
        }
        material_colors = {
            material.pixelColor(x, y).name()
            for y in range(material.height()) for x in range(material.width())
        }
        self.assertNotEqual(normal_colors, material_colors)
        self.assertTrue(material_colors.issubset({color.name() for color in WORK_PALETTE}))

    def test_appearance_validation_and_outer_database_cancel(self) -> None:
        before = bytes(self.project.working)
        database = DatabaseDialog(self.project)
        database.show()
        self.app.processEvents()
        appearance = read_unit_appearance(self.project, 11)
        values = tuple(appearance.configuration[1:10])
        with self.assertRaises(ValueError):
            appearance_patch(self.project, 11, (64, *values[1:]))
        with self.assertRaises(ValueError):
            appearance_patch(self.project, 11, (*values[:6], 256, *values[7:]))
        dialog = UnitAppearanceDialog(self.project, 11, database)
        dialog.editors[-1].setValue(0x50)
        dialog.accept()
        self.assertNotEqual(bytes(self.project.working), before)
        database.reject()
        self.assertEqual(bytes(self.project.working), before)
        self.assertFalse(self.project.can_undo)

    def test_appearance_edit_uses_active_relocated_record(self) -> None:
        old = read_unit_appearance(self.project, 2)
        self.project.configure_expansion(288, 64, 112)
        appearance = read_unit_appearance(self.project, 2)
        before = bytes(self.project.working)
        values = list(appearance.configuration[1:9])
        values[0] = 0x16
        offset, _, after = appearance_patch(self.project, 2, tuple(values))
        with self.project.transaction("配色"):
            self.project.working[offset:offset + len(after)] = after
        self.assertNotEqual(offset, old.file_offset + 1)
        self.assertEqual(self.project.working[old.file_offset:old.file_offset + 10],
                         before[old.file_offset:old.file_offset + 10])
        self.assertEqual(read_unit_appearance(self.project, 2).first_palette[0], 0x16)
        self.assertFalse([issue for issue in self.project.validate() if issue.severity == "error"])

    def test_small_to_large_appearance_relocation_survives_expansion(self) -> None:
        before = read_unit_appearance(self.project, 0x09)
        configuration = bytearray(before.configuration)
        configuration[0] = 0x80
        configuration[9] = configuration[8] + 1
        self.project.set_unit_appearance_configuration(0x09, bytes(configuration))
        relocated = read_unit_appearance(self.project, 0x09)
        self.assertNotEqual(relocated.file_offset, before.file_offset)
        self.assertEqual(relocated.configuration, bytes(configuration))

        self.project.configure_expansion(288, 64, 112)
        expanded = read_unit_appearance(self.project, 0x09)
        self.assertEqual(expanded.configuration, bytes(configuration))
        self.assertFalse(
            [issue for issue in self.project.validate() if issue.severity == "error"]
        )

    def test_body_composition_decodes_all_current_records_inside_legacy_canvas(self) -> None:
        for unit_id in range(1, self.project.unit_count):
            appearance = read_unit_appearance(self.project, unit_id)
            placements = decode_unit_body_script(
                appearance.body_script, len(appearance.secondary_banks) * 64
            )
            if not placements:
                continue
            self.assertLessEqual(
                max(item.x for item in placements) - min(item.x for item in placements) + 1,
                16,
            )
            self.assertLessEqual(
                max(item.y for item in placements) - min(item.y for item in placements) + 1,
                16,
            )

    def test_fragment_composition_decodes_and_renders_all_unit_records(self) -> None:
        for unit_id in range(1, self.project.unit_count):
            appearance = read_unit_appearance(self.project, unit_id)
            placements = decode_unit_fragment_script(appearance.fragment_script)
            self.assertTrue(all(0 <= item.tile_index < 0x80 for item in placements))
            image = render_unit_battle_preview(self.project, appearance)
            self.assertEqual((image.width(), image.height()), (128, 128))

        appearance = read_unit_appearance(self.project, 0x11)
        composite = render_unit_battle_preview(self.project, appearance)
        colors = {
            composite.pixelColor(x, y).name()
            for y in range(composite.height()) for x in range(composite.width())
        }
        self.assertTrue(colors & {
            palette_color(value).name() for value in appearance.first_palette
        })
        self.assertTrue(colors & {
            palette_color(value).name() for value in appearance.second_palette
        })

    def test_fragment_leading_coordinates_follow_battle_axes(self) -> None:
        # $09 begins at X=-1, Y=$C4+128+1=69.  The last pixel is the NES OAM
        # compensation: sprites begin on the scanline after their stored Y.
        appearance = read_unit_appearance(self.project, 0x09)
        first = decode_unit_fragment_script(appearance.fragment_script)[0]
        self.assertEqual((first.x, first.y, first.tile_index), (-1, 69, 0x68))

    def test_battle_preview_uses_both_side_origins(self) -> None:
        friendly = render_unit_battle_preview(
            self.project, read_unit_appearance(self.project, 0x09)
        )
        opposing = render_unit_battle_preview(
            self.project, read_unit_appearance(self.project, 0x51)
        )

        def visible_bounds(image):
            background = palette_color(0x0F).rgb()
            points = [
                (x, y)
                for y in range(image.height())
                for x in range(image.width())
                if image.pixel(x, y) != background
            ]
            return (
                min(x for x, _y in points), min(y for _x, y in points),
                max(x for x, _y in points), max(y for _x, y in points),
            )

        self.assertEqual(visible_bounds(friendly), (0, 49, 81, 127))
        self.assertEqual(visible_bounds(opposing), (72, 63, 126, 126))

    def test_enemy_large_legacy_screen_guide_has_no_internal_vertical_line(self) -> None:
        appearance = next(
            read_unit_appearance(self.project, unit_id)
            for unit_id in range(1, self.project.unit_count)
            if read_unit_appearance(self.project, unit_id).configuration[0] & 0xC0
            == 0xC0
        )
        blank = QImage(128, 128, QImage.Format.Format_RGB32)
        blank.fill(QColor("#000000"))

        guided = legacy_composition_image(
            blank, appearance, show_numbers=False, target_size=128
        )

        red = QColor("#ff2038")
        self.assertEqual(guided.pixelColor(20, 24), red)
        self.assertNotEqual(guided.pixelColor(104, 20), red)
        self.assertFalse(any(
            guided.pixelColor(104, y) == red
            for y in range(128)
            if not 22 <= y <= 25
        ))

    def test_enemy_small_legacy_screen_guide_uses_left_boundary(self) -> None:
        appearance = next(
            read_unit_appearance(self.project, unit_id)
            for unit_id in range(1, self.project.unit_count)
            if read_unit_appearance(self.project, unit_id).configuration[0] & 0xC0
            == 0x40
        )
        blank = QImage(128, 128, QImage.Format.Format_RGB32)
        blank.fill(QColor("#000000"))

        guided = legacy_composition_image(
            blank, appearance, show_numbers=False, target_size=128
        )

        red = QColor("#ff2038")
        self.assertEqual(guided.pixelColor(24, 20), red)
        self.assertEqual(guided.pixelColor(20, 24), red)
        self.assertNotEqual(guided.pixelColor(104, 20), red)

    def test_enemy_fragment_uses_legacy_right_side_anchor(self) -> None:
        appearance = read_unit_appearance(self.project, 0x87)
        fragment = render_unit_battle_preview(
            self.project, appearance, show_body=False
        )
        background = palette_color(0x0F).rgb()
        points = [
            (x, y)
            for y in range(fragment.height())
            for x in range(fragment.width())
            if fragment.pixel(x, y) != background
        ]
        self.assertEqual(
            (
                min(x for x, _y in points), min(y for _x, y in points),
                max(x for x, _y in points), max(y for _x, y in points),
            ),
            (76, 60, 119, 126),
        )
    def test_body_composition_expands_shared_rows_and_renders_current_chr(self) -> None:
        placements = decode_unit_body_script(
            bytes.fromhex("F3 F9 00 FD 20 08 F9 40 00 FF"), 64
        )
        self.assertEqual(len(placements), 64)
        self.assertEqual((placements[0].tile_index, placements[0].x, placements[0].y),
                         (0, 0, -7))
        self.assertEqual((placements[-1].tile_index, placements[-1].x, placements[-1].y),
                         (63, 7, 0))
        appearance = read_unit_appearance(self.project, 11)
        image = render_unit_body_composition(
            self.project,
            appearance.body_script,
            appearance.secondary_banks,
            appearance.first_palette,
        )
        self.assertEqual((image.width(), image.height()), (128, 128))
        self.assertGreater(len({image.pixel(x, y) for y in range(128) for x in range(128)}), 1)

    def test_body_composition_rejects_unverified_or_out_of_range_scripts(self) -> None:
        with self.assertRaisesRegex(ValueError, "未验证指令"):
            decode_unit_body_script(bytes.fromhex("F4 FF"), 64)
        with self.assertRaisesRegex(ValueError, "超出当前图库容量"):
            decode_unit_body_script(bytes.fromhex("40 FF"), 64)
        with self.assertRaisesRegex(ValueError, "缺少 FF"):
            decode_unit_body_script(bytes.fromhex("01"), 64)

    def test_palette_groups_match_legacy_screenshot_and_show_exact_hex(self) -> None:
        appearance = read_unit_appearance(self.project, 2)
        self.assertEqual(appearance.first_palette, (0x26, 0x06, 0x20))
        self.assertEqual(appearance.second_palette, (0x2A, 0x00, 0x10))
        self.assertEqual(palette_color(0x26).name().upper(), "#FC7460")
        self.assertEqual(palette_color(0x2A).name().upper(), "#4CDC48")
        dialog = UnitAppearanceDialog(self.project, 11)
        self.addCleanup(dialog.close)
        dialog.show()
        self.app.processEvents()
        self.assertEqual(dialog.palette_values, (0x22, 0x02, 0x20, 0x28, 0x18, 0x00))
        self.assertEqual(dialog.color_swatches, [])
        self.assertEqual(dialog.windowTitle(), "机体拼图")
        self.assertFalse(dialog.preview_tabs.tabBar().isVisible())
        self.assertFalse(dialog.body_import_button.isVisible())
        self.assertFalse(dialog.body_export_button.isVisible())
        self.assertEqual(dialog.body_import_offset.value(), 0)
        self.assertTrue(dialog.body_compress_upload.isChecked())
        self.assertEqual(dialog.fragment_import_offset.value(), 0)
        self.assertTrue(dialog.fragment_compress_upload.isChecked())
        self.assertTrue(dialog.body_auto_align_check.isChecked())
        self.assertTrue(dialog.body_auto_align_check.isVisible())
        self.assertEqual(
            (dialog.body_auto_align_pixels.minimum(),
             dialog.body_auto_align_pixels.maximum(),
             dialog.body_auto_align_pixels.value()),
            (1, 7, 3),
        )
        self.assertTrue(dialog.body_auto_align_pixels.isEnabled())
        self.assertTrue(dialog.sync_shared_previews_check.isChecked())
        self.assertTrue(dialog.sync_shared_previews_check.isVisible())
        self.assertEqual(dialog.preview_tabs.tabText(0), "战斗合成")
        self.assertEqual(dialog.preview_tabs.tabText(1), "碎片原始图库")
        self.assertEqual(dialog.preview_tabs.tabText(2), "拼图脚本原码")
        self.assertEqual(
            dialog.body_script_view.toPlainText(),
            dialog.appearance.body_script.hex(" ").upper(),
        )
        self.assertEqual(
            dialog.fragment_script_view.toPlainText(),
            dialog.appearance.fragment_script.hex(" ").upper(),
        )
        self.assertEqual(
            (dialog.body_library_preview.pixmap().width(),
             dialog.body_library_preview.pixmap().height()),
            (192, 384),
        )
        library = dialog.body_library_preview.pixmap().toImage()
        self.assertNotEqual(library.pixelColor(24, 120), library.pixelColor(25, 120))
        self.assertEqual(dialog.body_library_preview.source_width, 64)
        self.assertEqual(dialog.body_library_preview.source_height, 128)
        self.assertEqual(
            (dialog.body_composition_preview.pixmap().width(),
             dialog.body_composition_preview.pixmap().height()),
            (384, 384),
        )
        self.assertEqual(
            dialog.body_library_preview.mapTo(dialog, QPoint(0, 0)).y(),
            dialog.body_composition_preview.mapTo(dialog, QPoint(0, 0)).y(),
        )
        composition = dialog.body_composition_preview.pixmap().toImage()
        self.assertEqual(composition.pixelColor(312, 0).name(), "#ff2038")
        self.assertEqual(composition.pixelColor(0, 72).name(), "#ff2038")
        self.assertNotEqual(composition.pixelColor(24, 12), composition.pixelColor(25, 12))
        self.assertEqual(dialog.body_composition_preview.toolTip(), "")
        with patch(
            "dc_modifier.unit_appearance_dialog.render_unit_battle_preview",
            wraps=render_unit_battle_preview,
        ) as render_preview:
            dialog.refresh_preview()
        render_modes = {
            (call.kwargs.get("show_body", True), call.kwargs["show_fragments"])
            for call in render_preview.call_args_list
        }
        self.assertEqual(render_modes, {(True, False), (True, True)})
        self.assertEqual(set(dialog.body_move_buttons), {"up", "left", "right", "down"})
        self.assertEqual(dialog.unit_type_editor.size(), dialog.bank_editors[1].size())
        self.assertEqual(dialog.minimumSize(), dialog.maximumSize())
        fixed_button_positions = {
            key: button.geometry() for key, button in dialog.body_move_buttons.items()
        }
        dialog.resize(900, 900)
        self.app.processEvents()
        self.assertEqual((dialog.width(), dialog.height()), (740, 700))
        self.assertEqual(
            fixed_button_positions,
            {key: button.geometry() for key, button in dialog.body_move_buttons.items()},
        )
        self.assertLess(
            dialog.body_move_buttons["up"].geometry().top(),
            dialog.body_composition_preview.geometry().top(),
        )
        self.assertLess(
            dialog.body_move_buttons["left"].geometry().left(),
            dialog.body_composition_preview.geometry().left(),
        )
        before_numbering = dialog.body_composition_preview.pixmap().toImage()
        dialog.show_tile_numbers.setChecked(True)
        self.app.processEvents()
        after_numbering = dialog.body_composition_preview.pixmap().toImage()
        self.assertNotEqual(before_numbering, after_numbering)
        self.assertNotEqual(
            after_numbering.pixelColor(24, 12),
            after_numbering.pixelColor(25, 12),
        )
        dialog.preview_tabs.setCurrentIndex(1)
        self.app.processEvents()
        self.assertEqual(dialog.windowTitle(), "碎片拼图")
        self.assertEqual((dialog.width(), dialog.height()), (887, 708))
        self.assertEqual(dialog.fragment_reference_group.width(), 432)
        self.assertEqual(dialog.fragment_unit_type_editor.size().toTuple(), (164, 24))
        self.assertTrue(
            all(proxy.size().toTuple() == (164, 24)
                for proxy in dialog.fragment_bank_proxies)
        )
        self.assertLess(
            dialog.fragment_reference_labels["type"].geometry().bottom(),
            dialog.fragment_unit_type_editor.geometry().top(),
        )
        self.assertLess(
            dialog.fragment_unit_type_editor.geometry().bottom(),
            dialog.fragment_reference_labels["fragment"].geometry().top(),
        )
        self.assertEqual(
            [
                dialog.fragment_clear_button.width(),
                dialog.fragment_validate_button.width(),
                dialog.fragment_horizontal_flip_button.width(),
                dialog.fragment_vertical_flip_button.width(),
            ],
            [72, 84, 110, 110],
        )
        self.assertFalse(dialog.body_reference_group.isVisible())
        self.assertFalse(dialog.body_code_group.isVisible())
        self.assertEqual(
            (dialog.fragment_library_preview.pixmap().width(),
             dialog.fragment_library_preview.pixmap().height()),
            (384, 192),
        )
        self.assertEqual(
            (dialog.fragment_library_preview.source_width,
             dialog.fragment_library_preview.source_height),
            (128, 64),
        )
        self.assertEqual(
            (dialog.fragment_composition_preview.pixmap().width(),
             dialog.fragment_composition_preview.pixmap().height()),
            (384, 384),
        )
        self.assertEqual(set(dialog.fragment_move_buttons), {"up", "left", "right", "down"})
        self.assertFalse(dialog.fragment_import_button.isVisible())
        self.assertFalse(dialog.fragment_export_button.isVisible())
        self.assertLess(
            dialog.fragment_move_buttons["up"].geometry().top(),
            dialog.fragment_composition_preview.geometry().top(),
        )
        body = render_unit_body_composition(
            self.project,
            dialog.appearance.body_script,
            dialog.appearance.secondary_banks,
            dialog.appearance.first_palette,
        )
        fragments = render_chr_banks(
            self.project,
            (dialog.appearance.primary_bank & 0xFE,
             (dialog.appearance.primary_bank & 0xFE) + 1),
            dialog.appearance.second_palette,
        )
        body_colors = {
            body.pixelColor(x, y).name()
            for y in range(body.height()) for x in range(body.width())
        }
        fragment_colors = {
            fragments.pixelColor(x, y).name()
            for y in range(fragments.height()) for x in range(fragments.width())
        }
        self.assertLessEqual(
            body_colors,
            {"#000000", *(palette_color(value).name()
                           for value in dialog.appearance.first_palette)},
        )
        self.assertLessEqual(
            fragment_colors,
            {"#000000", *(palette_color(value).name()
                           for value in dialog.appearance.second_palette)},
        )


if __name__ == "__main__":
    unittest.main()
