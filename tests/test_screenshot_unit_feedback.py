from __future__ import annotations

import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QPoint, Qt
from PySide6.QtGui import QColor, QImage
from PySide6.QtWidgets import QApplication, QMessageBox

from dc_modifier.app import DEFAULT_ROM
from dc_modifier.database_graphics import (
    decode_unit_body_script,
    decode_unit_fragment_script,
    palette_color,
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
    chr_bank_description,
    choose_body_layout,
    compress_image_for_chr,
    encode_body_placements,
    encode_fragment_placements,
    flip_fragment_script,
    image_to_chr_pixels,
    move_body_script,
    move_fragment_script,
    parse_hex_script,
)
from fc_rom_editor_core import RomProject
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
        self.assertFalse(dialog.summary.isVisible())
        dialog.flag_checks[0x20].setChecked(True)
        dialog.low_bits.setCurrentIndex(3)
        self.assertEqual(dialog.value(), 0x33)
        self.assertIn("一击脱离", dialog.summary.text())
        self.assertIn("VPS防御系统", unit_special_summary(dialog.value()))

        database = DatabaseDialog(self.project)
        self.addCleanup(database.close)
        page = database.unit_page
        page.fields["special"].setValue(0xD8)
        self.assertIn("积层装甲反射", page.special_skill_button.text())
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
        appearance = read_unit_appearance(self.project, 2)
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
        changed = {i for i, (a, b) in enumerate(zip(before, self.project.working)) if a != b}
        self.assertEqual(changed, {offset + 7, offset + 8})
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
        dialog._apply_body_grid(7, 9)
        placements = decode_unit_body_script(dialog.body_script, 128)
        self.assertEqual(len(placements), 63)
        self.assertEqual(placements[0].tile_index, 0x40)
        self.assertEqual((placements[0].x, placements[0].y), (0, -8))
        dialog._select_library_tile("body", 12, 68)
        self.assertEqual(dialog._selected_body_tile, 0x41)

    def test_appearance_dialog_uses_main_page_colors_without_duplicate_editors(self) -> None:
        dialog = UnitAppearanceDialog(self.project, 0x09)
        self.addCleanup(dialog.close)
        self.assertEqual(dialog.color_buttons, [])
        self.assertEqual(dialog.palette_values, tuple(dialog.appearance.configuration[1:7]))
        self.assertEqual(dialog.values()[:6], tuple(dialog.appearance.configuration[1:7]))
        self.assertIn("颜色请在数据库机体页调整", dialog.hint.text())

    def test_arbitrary_bmp_is_compressed_with_aspect_ratio_and_padding(self) -> None:
        image = QImage(100, 50, QImage.Format.Format_RGB32)
        image.fill(QColor("#ff0000"))
        result = compress_image_for_chr(image, 64, 64)
        self.assertEqual((result.width(), result.height()), (64, 64))
        self.assertEqual(result.pixelColor(32, 32).name(), "#ff0000")
        self.assertEqual(result.pixelColor(32, 0), palette_color(0x0F))
        self.assertEqual(result.pixelColor(32, 63), palette_color(0x0F))

    def test_body_bmp_import_selects_legacy_layout_and_generates_script(self) -> None:
        dialog = UnitAppearanceDialog(self.project, 0x09)
        self.addCleanup(dialog.close)
        image = QImage(100, 50, QImage.Format.Format_RGB32)
        image.fill(WORK_PALETTE[1])
        self.assertEqual(choose_body_layout(image.width(), image.height()), (10, 6))
        dialog._import_body_image(image)
        placements = decode_unit_body_script(dialog.body_script, 64)
        self.assertEqual(len(placements), 60)
        self.assertEqual((placements[0].tile_index, placements[0].x, placements[0].y),
                         (0, 0, -5))
        self.assertEqual((placements[-1].tile_index, placements[-1].x, placements[-1].y),
                         (59, 9, 0))
        self.assertEqual(dialog.body_script, bytes.fromhex("F3 FB 00 FD 20 0A F9 3C 00 FF"))
        bank = dialog.values()[7]
        self.assertEqual(dialog._draft_tiles[bank * 64 + 63], (0,) * 64)

    def test_body_import_offset_and_uncompressed_mode_change_first_tile(self) -> None:
        dialog = UnitAppearanceDialog(self.project, 0x09)
        self.addCleanup(dialog.close)
        dialog.body_compress_upload.setChecked(False)
        dialog.body_import_offset.setValue(2)
        image = QImage(16, 8, QImage.Format.Format_RGB32)
        image.fill(WORK_PALETTE[1])
        dialog._import_body_image(image)
        placements = decode_unit_body_script(dialog.body_script, 64)
        self.assertEqual([item.tile_index for item in placements], [2, 3])
        bank = dialog.values()[7]
        self.assertNotIn(bank * 64, dialog._draft_tiles)
        self.assertNotIn(bank * 64 + 1, dialog._draft_tiles)
        self.assertEqual(dialog._draft_tiles[bank * 64 + 2], (1,) * 64)
        self.assertIn("偏移 $02", dialog.status.text())

    def test_body_import_offset_rejects_overflow_without_draft(self) -> None:
        dialog = UnitAppearanceDialog(self.project, 0x09)
        self.addCleanup(dialog.close)
        dialog.body_compress_upload.setChecked(False)
        dialog.body_import_offset.setValue(63)
        image = QImage(16, 8, QImage.Format.Format_RGB32)
        image.fill(WORK_PALETTE[1])
        with self.assertRaisesRegex(ValueError, "无法容纳"):
            dialog._import_body_image(image)
        self.assertEqual(dialog._draft_tiles, {})

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
        image = QImage(100, 50, QImage.Format.Format_RGB32)
        image.fill(WORK_PALETTE[3])
        with tempfile.TemporaryDirectory() as temporary:
            source = Path(temporary) / "compressed-fragments.bmp"
            self.assertTrue(image.save(str(source), "BMP"))
            with patch(
                "dc_modifier.unit_appearance_dialog.QFileDialog.getOpenFileName",
                return_value=(str(source), "BMP 图片 (*.bmp)"),
            ):
                dialog._import_library("fragment")
        bank = dialog.values()[6] & 0xFE
        self.assertEqual(list(dialog._draft_tiles), [bank * 64 + 127])
        self.assertIn("偏移 $7F", dialog.status.text())
        self.assertIn("等比压缩并居中", dialog.status.text())

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
        self.assertLessEqual(dialog.minimumSizeHint().width(), 730)
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
            "导入图片\tCtrl+D",
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

    def test_fragment_reference_page_selects_side_by_side_banks_and_flips_hit(self) -> None:
        dialog = UnitAppearanceDialog(self.project, 0x09)
        self.addCleanup(dialog.close)
        dialog._select_library_tile("fragment", 72, 8)
        self.assertEqual(dialog._selected_fragment_tile, 0x49)
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
        self.assertEqual(render_modes, {(True, False), (False, True)})
        self.assertEqual(set(dialog.body_move_buttons), {"up", "left", "right", "down"})
        self.assertEqual(dialog.unit_type_editor.size(), dialog.bank_editors[1].size())
        self.assertEqual(dialog.minimumSize(), dialog.maximumSize())
        fixed_button_positions = {
            key: button.geometry() for key, button in dialog.body_move_buttons.items()
        }
        dialog.resize(900, 900)
        self.app.processEvents()
        self.assertEqual((dialog.width(), dialog.height()), (730, 708))
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
