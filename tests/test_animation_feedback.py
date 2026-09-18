from __future__ import annotations

import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication, QDialog

from fc_editor.codecs.animation import (
    AnimationCodec,
    apply_animation_patches,
    decode_sprite_composition,
    decode_sprite_timeline,
)
from fc_rom_editor_core import RomProject
from dc_modifier.animation_editor import (
    AnimationPointerDialog,
    MapAnimationEditorDialog,
    SpritePuzzlePreviewDialog,
    WeaponAnimationWidget,
)
from tests.qt_test_case import QtTestCase

ROOT = Path(__file__).resolve().parents[1]
ROM = ROOT / "output/rom/DC_kuorong_464K.nes"


@unittest.skipUnless(ROM.is_file(), "需要正式构建 ROM")
class AnimationCodecTests(unittest.TestCase):
    def setUp(self):
        self.project = RomProject.load(ROM)
        self.codec = AnimationCodec(self.project.working)

    def test_verified_tables_and_map_explosion_match_real_bytes(self):
        self.assertEqual({k: len(v) for k, v in self.codec.pointers.items()},
                         {"map": 153, "ally": 256, "enemy": 256,
                          "background": 106, "movement": 157, "sprite": 249})
        record = self.codec.record("map", 1)
        self.assertEqual(record.offset, 0x5213E)
        self.assertEqual(record.raw, bytes.fromhex(
            "E0 0A F0 11 03 28 17 20 F1 00 01 F9 0F F8 F8 40 68 01 02 02 "
            "F4 02 1D E0 08 F0 11 03 30 23 0F F1 00 FF"))
        self.assertTrue(record.complete)
        self.assertEqual(self.codec.record("movement", 1).raw[:8], bytes.fromhex("09 FB 04 FC 0A FB 04 FC"))
        self.assertEqual(self.codec.record("background", 0).raw[:6], bytes.fromhex("FC 20 00 FC 20 4F"))
        self.assertEqual(self.codec.record("ally", 1).offset, 0x44230)
        self.assertEqual(self.codec.record("enemy", 1).offset, 0x40230)

    def test_every_live_script_decodes_losslessly_including_shared_records(self):
        for kind in ("map", "ally", "enemy"):
            for index in range(0 if kind == "map" else 1, self.codec.count(kind)):
                record = self.codec.record(kind, index)
                self.assertTrue(record.complete, (kind, index))
                self.assertEqual(b"".join(row.raw for row in record.instructions), record.raw)
        self.assertIn(34, self.codec.record("map", 3).aliases)

    def test_script_edit_is_bounded_and_preserves_command_and_pointer_bytes(self):
        record = self.codec.record("map", 1)
        changed = bytearray(record.raw)
        changed[5] = 0x27
        changed[10] = 3
        patch = self.codec.script_patch(record, bytes(changed))
        apply_animation_patches(self.project, (patch,), "动画测试")
        self.assertEqual([row[0] for row in self.project.change_rows()], [0x52143, 0x52148])
        self.assertFalse([issue for issue in self.project.validate() if issue.severity == "error"])
        self.project.undo()
        self.assertEqual(bytes(self.project.working), self.project.original)
        self.project.redo()
        self.assertEqual(self.project.working[0x52148], 3)
        with self.assertRaises(ValueError):
            self.codec.script_patch(record, record.raw + b"\0")
        changed[0] = 0xE1
        with self.assertRaises(ValueError):
            self.codec.script_patch(record, bytes(changed))

    def test_animation_project_save_and_replay(self):
        record = self.codec.record("ally", 1)
        changed = bytearray(record.raw)
        changed[1] = 0x10
        apply_animation_patches(self.project, (self.codec.script_patch(record, bytes(changed)),), "武器动画")
        with tempfile.TemporaryDirectory(dir=ROOT / "output/verification") as directory:
            destination = Path(directory) / "animation.dcmod"
            self.project.save_project(destination)
            reopened = RomProject.load_project(destination, ROM)
            self.assertEqual(reopened.working, self.project.working)

    def test_interpreter_and_pointer_corruption_fail_closed(self):
        for offset in (0xFE85A, 0xFF4B6, 0x5200E):
            changed = bytearray(self.project.working)
            changed[offset] = 0
            with self.assertRaises(ValueError, msg=hex(offset)):
                AnimationCodec(changed)

    def test_map_rule_roles_and_safe_edits(self):
        roles = self.codec.movement_roles()
        self.assertEqual(roles[1], {"frames"})
        self.assertEqual(roles[2], {"axis"})
        record = self.codec.record("movement", 1)
        changed = bytearray(record.raw)
        changed[2] = 5
        self.codec.rule_patch(record, bytes(changed))
        changed[3] = 0xFB
        with self.assertRaises(ValueError):
            self.codec.rule_patch(record, bytes(changed))
        sprite = self.codec.record("sprite", 0)
        self.codec.rule_patch(sprite, bytes((1, 2)) + sprite.raw[2:])
        with self.assertRaises(ValueError):
            self.codec.rule_patch(sprite, sprite.raw[:2] + b"\x7f" + sprite.raw[3:])

    def test_physical_puzzle_decoder_matches_verified_tile_walk(self):
        raw = bytes.fromhex(
            "08 00 18 00 08 F4 00 08 F4 00 08 F8 00 28 1E F8 "
            "80 A8 1C F8 80 A8 1A FC 80 A8 18 FC 80 80 FF"
        )
        composition = decode_sprite_composition(raw)
        self.assertTrue(composition.complete)
        self.assertEqual((composition.anchor_x, composition.anchor_y), (8, 0))
        self.assertEqual(len(composition.placements), 16)
        self.assertEqual(
            [
                (tile.tile_index, tile.x, tile.y, tile.vertical_flip)
                for tile in composition.placements
            ],
            [
                (0x18, 8, 0, False), (0x19, 16, 0, False),
                (0x1A, 4, 8, False), (0x1B, 12, 8, False),
                (0x1C, 0, 16, False), (0x1D, 8, 16, False),
                (0x1E, 0, 24, False), (0x1F, 8, 24, False),
                (0x1E, 0, 32, True), (0x1F, 8, 32, True),
                (0x1C, 0, 40, True), (0x1D, 8, 40, True),
                (0x1A, 4, 48, True), (0x1B, 12, 48, True),
                (0x18, 8, 56, True), (0x19, 16, 56, True),
            ],
        )
        self.assertFalse(decode_sprite_composition(raw[:-1]).complete)

    def test_every_sprite_record_decodes_and_frame_streams_fail_closed(self):
        compositions = [
            decode_sprite_composition(
                self.codec.record("sprite", index).raw,
                self.codec.record("sprite", index).offset,
            )
            for index in range(self.codec.count("sprite"))
        ]
        self.assertTrue(all(item.complete for item in compositions))
        self.assertEqual(
            sum(
                any(tile.tile_index is None for tile in item.placements)
                for item in compositions
            ),
            13,
        )
        roles = self.codec.movement_roles()
        frame_rules = sorted(
            index for index, role in roles.items() if role == {"frames"}
        )
        timelines = {
            index: decode_sprite_timeline(
                self.codec.record("movement", index).raw,
                self.codec.count("sprite"),
            )
            for index in frame_rules
        }
        self.assertEqual(len(frame_rules), 81)
        self.assertEqual(
            {index for index, timeline in timelines.items() if not timeline.complete},
            {18, 33},
        )
        self.assertTrue(all(timeline.frames for timeline in timelines.values()))

    def test_frame_timeline_expands_wait_and_detects_loop(self):
        timeline = decode_sprite_timeline(
            bytes.fromhex("01 FE 02 02 FF"), self.codec.count("sprite")
        )
        self.assertEqual(timeline.frames, (1, 1, 1, 2))
        self.assertTrue(timeline.terminated)
        loop = decode_sprite_timeline(
            bytes.fromhex("01 F8"), self.codec.count("sprite")
        )
        self.assertTrue(loop.complete)
        self.assertEqual(loop.frames, (1, 1))
        self.assertEqual(loop.loop_start, 1)

    def test_call_edit_changes_one_existing_operand_and_rejects_invalid_id(self):
        self.assertIn((0x3BB93, 0x2C), self.codec.calls())
        patch = self.codec.call_patch(0x3BB93, 2)
        self.assertEqual(patch, (0x3BB95, b"\x2c", b"\x02"))
        with self.assertRaises(ValueError):
            self.codec.call_patch(0x3BB93, 255)
        with self.assertRaises(ValueError):
            self.codec.call_patch(0x3BB94, 2)
        self.assertFalse(self.codec.call_is_editable(0x3804A))
        with self.assertRaises(ValueError):
            self.codec.call_patch(0x3804A, 2)

    def test_stale_batch_fails_without_applying_earlier_patches(self):
        first = self.codec.record("ally", 1)
        second = self.codec.record("enemy", 1)
        replacements = []
        for record in (first, second):
            raw = bytearray(record.raw)
            raw[1] = 0x10
            replacements.append(self.codec.script_patch(record, bytes(raw)))
        self.project.working[second.offset + 1] = 0x11
        before = bytes(self.project.working)
        with self.assertRaises(ValueError):
            apply_animation_patches(self.project, tuple(replacements), "过期动画草稿")
        self.assertEqual(self.project.working, before)
        self.assertFalse(self.project.can_undo)


@unittest.skipUnless(ROM.is_file(), "需要正式构建 ROM")
class AnimationUiTests(QtTestCase):
    @classmethod
    def setUpClass(cls):
        cls.application = QApplication.instance() or QApplication([])

    def setUp(self):
        self.project = RomProject.load(ROM)

    def test_map_cancel_discards_scripts_rules_and_calls(self):
        dialog = MapAnimationEditorDialog(project=self.project)
        raw = bytearray(dialog.script_editor.record.raw)
        raw[5] = 0x27
        dialog.script_editor.code_edit.setPlainText(raw.hex(" "))
        dialog.animation_list.setCurrentRow(2)
        dialog.sprite_x.setValue(3)
        dialog.call_combos[0x3BB93].setCurrentIndex(2)
        self.assertNotEqual(dialog.draft, self.project.working)
        dialog.reject()
        self.assertEqual(self.project.working, self.project.original)
        self.assertFalse(self.project.can_undo)

    def test_map_accept_commits_all_tabs_in_one_undo_step(self):
        dialog = MapAnimationEditorDialog(project=self.project)
        raw = bytearray(dialog.script_editor.record.raw)
        raw[5] = 0x27
        dialog.script_editor.code_edit.setPlainText(raw.hex(" "))
        dialog.sprite_x.setValue(3)
        dialog.call_combos[0x3BB93].setCurrentIndex(2)
        movement = bytearray.fromhex(dialog.rule_codes["movement"].toPlainText())
        movement[2] = 6
        dialog.rule_codes["movement"].setPlainText(movement.hex(" "))
        dialog.accept()
        self.assertEqual(dialog.result(), QDialog.DialogCode.Accepted)
        self.assertEqual(len(self.project._undo_stack), 1)
        self.assertEqual(self.project.working[0x52143], 0x27)
        self.assertEqual(self.project.working[0x3BB95], 2)
        self.assertEqual(self.project.working[0x334DC], 6)
        self.project.undo()
        self.assertEqual(self.project.working, self.project.original)

    def test_bad_hex_and_changed_command_block_switch_and_accept(self):
        dialog = MapAnimationEditorDialog(project=self.project)
        dialog.script_editor.code_edit.setPlainText("F")
        dialog.animation_list.setCurrentRow(2)
        self.assertEqual(dialog.animation_list.currentRow(), 1)
        dialog.accept()
        self.assertEqual(dialog.result(), 0)
        self.assertFalse(self.project.can_undo)
        dialog.reject()

    def test_reference_secondary_dialog_entries_do_not_guess_unverified_writes(self):
        dialog = MapAnimationEditorDialog(project=self.project)
        before = bytes(dialog.draft)
        self.assertFalse(dialog.script_editor.code_edit.isVisible())
        with patch.object(
            AnimationPointerDialog,
            "exec",
            return_value=QDialog.DialogCode.Accepted,
        ):
            dialog.code_button.click()
        self.assertFalse(dialog.script_editor.code_edit.isVisible())
        self.assertIn("0080", dialog.script_editor.status.text())
        self.assertEqual(bytes(dialog.draft), before)

        sprite = dialog.codec.record("sprite", dialog.rule_lists["sprite"].currentRow())
        preview = SpritePuzzlePreviewDialog(
            sprite, self.project, dialog.codec, dialog
        )
        self.assertEqual(preview.windowTitle(), "物理拼图")
        self.assertEqual(preview.code_view.toPlainText(), sprite.raw.hex(" ").upper())
        self.assertTrue(preview.library_combo.isEnabled())
        self.assertEqual(preview.library_combo.currentData(), 8)
        self.assertEqual(preview.library_list.count(), 256)
        self.assertGreater(preview.placement_table.rowCount(), 0)
        self.assertFalse(preview.preview_label.pixmap().isNull())
        self.assertGreater(preview.timeline_combo.count(), 1)
        preview.reject()
        dialog.reject()

    def test_rule_panels_show_reference_names_and_keep_unverified_add_disabled(self):
        dialog = MapAnimationEditorDialog(project=self.project)
        for kind in ("background", "movement", "sprite"):
            row = dialog.rule_lists[kind].currentRow()
            self.assertEqual(dialog.rule_name_edits[kind].text(), dialog.rule_names[kind][row])
            self.assertTrue(dialog.rule_name_edits[kind].isReadOnly())
        self.assertEqual(dialog.sprite_preview_library.currentText(), "[08]008：82010")
        self.assertTrue(dialog.sprite_preview_library.isEnabled())
        rule_add_buttons = [
            button
            for button in dialog.tabs.widget(1).findChildren(type(dialog.add_button))
            if button.text() == "添加"
        ]
        self.assertEqual(len(rule_add_buttons), 2)
        self.assertTrue(all(not button.isEnabled() for button in rule_add_buttons))
        self.assertTrue(dialog.animation_puzzle_button.isEnabled())
        dialog.reject()

    def test_weapon_widget_applies_both_sides_in_one_transaction(self):
        widget = WeaponAnimationWidget()
        widget.set_record(self.project, 1)
        for editor in widget.editors:
            raw = bytearray(editor.record.raw)
            raw[1] = 0x10
            editor.code_edit.setPlainText(raw.hex(" "))
        self.assertTrue(widget.has_pending_changes())
        self.assertEqual(len(widget.pending_patches()), 2)
        widget.apply_pending()
        self.assertEqual(len(self.project._undo_stack), 1)
        self.assertEqual(self.project.working[0x44231], 0x10)
        self.assertEqual(self.project.working[0x40231], 0x10)
        self.assertFalse(widget.has_pending_changes())
        widget.close()
