from __future__ import annotations

import os
from pathlib import Path
import tempfile
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

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
from dc_modifier.legacy_windows import DatabaseDialog
from dc_modifier.unit_appearance_dialog import UnitAppearanceDialog, appearance_patch
from fc_rom_editor_core import RomProject
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
        self.project.set_value(2, "special", 0x86)
        self.project.set_value(2, "experience", 90)
        after = self.project.record_bytes(2)
        self.assertEqual(after[0], (raw[0] & 0xFC) | 2)
        self.assertEqual(after[1], 0x86)
        self.assertEqual(after[10], 90)
        self.assertEqual(after[2:10], raw[2:10])
        self.assertEqual(after[11:], raw[11:])
        with self.assertRaises(ValueError):
            self.project.set_value(2, "terrain", 4)

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
        self.assertEqual(len(dialog.editors), 8)
        dialog.editors[0].setValue(0x12)
        dialog.editors[6].setValue(0x42)
        dialog.accept()
        self.assertTrue(dialog.changed)
        offset = appearance.file_offset
        self.assertEqual(self.project.working[offset + 9], before[offset + 9])
        changed = {i for i, (a, b) in enumerate(zip(before, self.project.working)) if a != b}
        self.assertEqual(changed, {offset + 1, offset + 7})
        self.project.undo()
        self.assertEqual(bytes(self.project.working), before)

    def test_appearance_colors_use_visual_palette_buttons_and_stay_in_sync(self) -> None:
        dialog = UnitAppearanceDialog(self.project, 0x09)
        self.addCleanup(dialog.close)
        self.assertEqual(len(dialog.color_buttons), 6)
        self.assertEqual(dialog.color_buttons[0].value, dialog.editors[0].value())
        self.assertIn("background:", dialog.color_buttons[0].styleSheet())
        self.assertIn("点击展开64色", dialog.color_buttons[0].toolTip())

        dialog.color_buttons[0].set_value(0x2A)
        self.assertEqual(dialog.editors[0].value(), 0x2A)
        dialog.editors[1].setValue(0x16)
        self.assertEqual(dialog.color_buttons[1].value, 0x16)

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
        # $09 begins at X=-1, Y=$C4+128=68.  These two bytes were previously
        # interpreted in the opposite order, detaching the sprite layer.
        appearance = read_unit_appearance(self.project, 0x09)
        first = decode_unit_fragment_script(appearance.fragment_script)[0]
        self.assertEqual((first.x, first.y, first.tile_index), (-1, 68, 0x68))

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

        self.assertEqual(visible_bounds(friendly), (0, 48, 81, 127))
        self.assertEqual(visible_bounds(opposing), (72, 63, 127, 125))
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
        self.assertEqual([editor.text() for editor in dialog.editors[:6]],
                         ["$22", "$02", "$20", "$28", "$18", "$00"])
        self.assertIn("#5c94fc", dialog.color_swatches[0].styleSheet())
        self.assertIn("#f0bc3c", dialog.color_swatches[3].styleSheet())
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
            (208, 416),
        )
        self.assertEqual(
            (dialog.body_composition_preview.pixmap().width(),
             dialog.body_composition_preview.pixmap().height()),
            (416, 416),
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
