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
    decode_background_rule,
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

    def test_map_animation_clone_uses_reserved_slot_and_relocates_loops(self):
        new_index, patches = self.codec.clone_map_animation_patches(0)
        self.assertEqual(new_index, 0x3F)
        self.assertEqual(len(patches), 2)
        self.assertEqual(patches[0][0], 0x5208A)
        self.assertTrue(all(value == 0 for value in patches[1][1]))
        apply_animation_patches(self.project, patches, "复制地图动画")
        cloned = AnimationCodec(self.project.working)
        source = cloned.record("map", 0)
        target = cloned.record("map", new_index)
        self.assertTrue(target.complete)
        self.assertEqual(len(target.raw), len(source.raw))
        delta = cloned.pointers["map"][new_index] - cloned.pointers["map"][0]
        for source_row, target_row in zip(source.instructions, target.instructions):
            self.assertEqual(source_row.raw[:2], target_row.raw[:2])
            if source_row.raw[:1] == b"\xFE":
                self.assertEqual(
                    int.from_bytes(target_row.raw[2:4], "little"),
                    int.from_bytes(source_row.raw[2:4], "little") + delta,
                )
        second_index, second_patches = cloned.clone_map_animation_patches(1)
        self.assertEqual(second_index, 0x40)
        self.assertGreater(second_patches[1][0], patches[1][0])
        self.project.undo()
        self.assertEqual(self.project.working, self.project.original)

    def test_sprite_clone_uses_reserved_tail_and_preserves_record_boundaries(self):
        source = self.codec.record("sprite", 0)
        new_index, patches = self.codec.clone_sprite_rule_patches(0)
        self.assertEqual(new_index, 0xEB)
        self.assertEqual(len(patches), 2)
        self.assertEqual(patches[0][0], 0x31C66)
        self.assertEqual(patches[1][0], 0x33348)
        apply_animation_patches(self.project, patches, "复制组图规律")
        cloned = AnimationCodec(self.project.working)
        self.assertEqual(cloned.record("sprite", 0xEB).raw, source.raw)
        self.assertEqual(cloned.pointers["sprite"][0xF7], 0xB38B)
        self.assertEqual(cloned.pointers["sprite"][0xF8], 0xB38B)

        second_source = cloned.record("sprite", 1)
        second_index, second_patches = cloned.clone_sprite_rule_patches(1)
        self.assertEqual(second_index, 0xEC)
        apply_animation_patches(self.project, second_patches, "再次复制组图规律")
        twice = AnimationCodec(self.project.working)
        self.assertEqual(twice.record("sprite", 0xEB).raw, source.raw)
        self.assertEqual(twice.record("sprite", 0xEC).raw, second_source.raw)
        self.assertLess(
            twice.pointers["sprite"][0xEC],
            twice.pointers["sprite"][0xEB],
        )
        self.project.undo()
        self.project.undo()
        self.assertEqual(self.project.working, self.project.original)

    def test_sprite_clone_rejects_free_source_and_oversized_record(self):
        with self.assertRaisesRegex(ValueError, "尚未分配"):
            self.codec.clone_sprite_rule_patches(0xEB)
        largest = max(
            range(0xEB),
            key=lambda index: len(self.codec.record("sprite", index).raw),
        )
        self.assertGreater(len(self.codec.record("sprite", largest).raw), 83)
        with self.assertRaisesRegex(ValueError, "只剩 83 字节"):
            self.codec.clone_sprite_rule_patches(largest)

    def test_movement_clone_uses_reserved_tail_and_rebinds_unique_role(self):
        source = self.codec.record("movement", 1)
        new_index, role, patches = self.codec.clone_movement_rule_patches(1, 1)
        self.assertEqual((new_index, role), (0x7D, "frames"))
        self.assertEqual(patches[0][0], 0x3349A)
        self.assertEqual(patches[1][0], 0x33B0D)
        self.assertEqual(patches[2][1:], (b"\x01", b"\x7D"))
        apply_animation_patches(self.project, patches, "复制并绑定运行规律")
        cloned = AnimationCodec(self.project.working)
        self.assertEqual(cloned.record("movement", 0x7D).raw, source.raw)
        self.assertEqual(cloned.movement_roles()[0x7D], {"frames"})

        second_source = cloned.record("movement", 6)
        second_index, second_role, second_patches = cloned.clone_movement_rule_patches(6, 2)
        self.assertEqual((second_index, second_role), (0x7E, "frames"))
        apply_animation_patches(self.project, second_patches, "再次复制并绑定运行规律")
        twice = AnimationCodec(self.project.working)
        self.assertEqual(twice.record("movement", 0x7D).raw, source.raw)
        self.assertEqual(twice.record("movement", 0x7E).raw, second_source.raw)
        self.assertEqual(twice.movement_roles()[0x7E], {"frames"})
        self.assertEqual(twice.pointers["movement"][0x7E], 0xBAFD)
        self.assertEqual(twice.pointers["movement"][0x7D], 0xBAFF)
        self.project.undo()
        self.project.undo()
        self.assertEqual(self.project.working, self.project.original)

    def test_movement_clone_rejects_ambiguous_binding_and_capacity(self):
        with self.assertRaisesRegex(ValueError, "恰好一次引用"):
            self.codec.clone_movement_rule_patches(2, 1)
        _new_index, _role, patches = self.codec.clone_movement_rule_patches(1, 1)
        apply_animation_patches(self.project, patches, "复制并绑定运行规律")
        cloned = AnimationCodec(self.project.working)
        _second_index, _second_role, second = cloned.clone_movement_rule_patches(6, 2)
        apply_animation_patches(self.project, second, "再次复制并绑定运行规律")
        full = AnimationCodec(self.project.working)
        with self.assertRaisesRegex(ValueError, "只剩 0 字节"):
            full.clone_movement_rule_patches(7, 8)

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
        for offset in (0xFD407, 0xFE85A, 0xFF4B6, 0xFF7D8, 0x5200E):
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
        with self.assertRaisesRegex(ValueError, "不持久化"):
            self.codec.rule_patch(sprite, bytes((1, 2)) + sprite.raw[2:])
        changed_sprite = bytearray(sprite.raw)
        changed_sprite[2] = 1
        self.codec.rule_patch(sprite, bytes(changed_sprite))
        changed_sprite[3] ^= 1
        with self.assertRaises(ValueError):
            self.codec.rule_patch(sprite, bytes(changed_sprite))

        editable_backgrounds = self.codec.background_editable_indices()
        self.assertEqual(len(editable_backgrounds), 69)
        self.assertEqual(editable_backgrounds[:7], (0, 1, 3, 4, 5, 6, 7))
        self.assertEqual(editable_backgrounds[-4:], (0x50, 0x51, 0x53, 0x58, 0x59)[-4:])
        self.assertEqual(
            self.codec.background_static_reference_indices(),
            (3, 4, 5, 6, 0x18, 0x19),
        )
        background = self.codec.record("background", 3)
        decoded, complete = decode_background_rule(
            background.raw,
            background.offset,
        )
        self.assertTrue(complete)
        self.assertEqual(sum(len(row.raw) for row in decoded), len(background.raw))
        changed_background = bytearray(background.raw)
        changed_background[5] ^= 1
        self.codec.rule_patch(background, bytes(changed_background))
        changed_background[4] = 0xF9
        with self.assertRaises(ValueError):
            self.codec.rule_patch(background, bytes(changed_background))
        literal_background = self.codec.record("background", 4)
        changed_background = bytearray(literal_background.raw)
        changed_background[5] = 0xFF
        with self.assertRaises(ValueError):
            self.codec.rule_patch(literal_background, bytes(changed_background))
        with self.assertRaises(ValueError):
            self.codec.rule_patch(
                self.codec.record("background", 2),
                self.codec.record("background", 2).raw,
            )

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
        self.assertEqual(len(self.codec.calls()), 86)
        self.assertEqual(
            sum(self.codec.call_is_editable(offset) for offset, _ in self.codec.calls()),
            76,
        )
        patch = self.codec.call_patch(0x3BB93, 2)
        self.assertEqual(patch, (0x3BB95, b"\x2c", b"\x02"))
        with self.assertRaises(ValueError):
            self.codec.call_patch(0x3BB93, 255)
        with self.assertRaises(ValueError):
            self.codec.call_patch(0x3BB94, 2)
        self.assertFalse(self.codec.call_is_editable(0x3804A))
        with self.assertRaises(ValueError):
            self.codec.call_patch(0x3804A, 2)

    def test_documented_call_contexts_are_editable_and_other_matches_stay_read_only(self):
        expected = {
            0x38FEA: "战斗流程调用序列",
            0x38FD5: "带参数精神调用序列",
            0x38BEE: "连续动画调用序列",
            0x38C1F: "奇迹闪烁调用序列",
            0x38C27: "奇迹闪烁调用序列",
            0x38113: "资料集地址/编号清单",
            0x384F2: "资料集地址/编号清单",
        }
        for offset, evidence in expected.items():
            with self.subTest(offset=hex(offset)):
                self.assertEqual(self.codec.call_evidence(offset), evidence)
                patch = self.codec.call_patch(offset, 2)
                self.assertEqual(patch[0], offset + 2)
                self.assertEqual(patch[2], b"\x02")
        readonly = [
            offset
            for offset, _ in self.codec.calls()
            if not self.codec.call_is_editable(offset)
        ]
        self.assertEqual(len(readonly), 10)
        self.assertIn(0x3804A, readonly)

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

    def test_every_call_selector_reverses_in_one_window_without_unlocking_unsafe_sites(self):
        dialog = MapAnimationEditorDialog(project=self.project)
        self.addCleanup(dialog.close)
        original = bytes(self.project.working)
        self.assertEqual(len(dialog.call_combos), 86)
        editable = 0
        blocked = 0
        for offset, animation_id in dialog.codec.calls():
            combo = dialog.call_combos[offset]
            replacement = 3 if animation_id == 2 else 2
            if dialog.codec.call_is_editable(offset):
                editable += 1
                self.assertTrue(combo.isEnabled(), hex(offset))
                combo.setCurrentIndex(replacement)
                self.assertEqual(dialog.draft[offset + 2], replacement, hex(offset))
                combo.setCurrentIndex(animation_id)
                self.assertEqual(dialog.draft[offset + 2], animation_id, hex(offset))
            else:
                blocked += 1
                self.assertFalse(combo.isEnabled(), hex(offset))
                combo.setCurrentIndex(replacement)
                self.assertEqual(dialog.draft[offset + 2], animation_id, hex(offset))
        self.assertEqual((editable, blocked), (76, 10))
        self.assertEqual(bytes(dialog.draft), original)
        self.assertEqual(bytes(self.project.working), original)

    def test_documented_calls_allow_second_change_and_survive_save_reopen(self):
        dialog = MapAnimationEditorDialog(project=self.project)
        self.addCleanup(dialog.close)
        original = bytes(self.project.working)
        offsets = (0x38113, 0x384F2)
        for offset in offsets:
            combo = dialog.call_combos[offset]
            self.assertTrue(combo.isEnabled())
            combo.setCurrentIndex(2)
            self.assertEqual(dialog.draft[offset + 2], 2)
            combo.setCurrentIndex(3)
            self.assertEqual(dialog.draft[offset + 2], 3)
        self.assertEqual(bytes(self.project.working), original)
        dialog.accept()
        self.assertEqual(dialog.result(), QDialog.DialogCode.Accepted)
        changed = {index for index, (before, after) in enumerate(zip(original, self.project.working)) if before != after}
        self.assertEqual(changed, {offset + 2 for offset in offsets})
        with tempfile.TemporaryDirectory() as directory:
            saved = Path(directory) / "m12_calls.nes"
            self.project.save_as(saved, make_backup=False)
            reopened = RomProject.load(saved)
            self.assertEqual(bytes(reopened.working), bytes(self.project.working))
        self.project.undo()
        self.assertEqual(bytes(self.project.working), original)

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
        sprite = dialog.codec.record(
            "sprite", dialog.rule_lists["sprite"].currentRow()
        )
        sprite_code = bytearray(sprite.raw[2:])
        sprite_code[0] = 1
        dialog.rule_codes["sprite"].setPlainText(sprite_code.hex(" "))
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
        self.assertEqual(self.project.working[0x31C82], 0)
        self.assertEqual(self.project.working[0x31C84], 1)
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

    def test_rule_panels_show_names_and_only_enable_verified_sprite_add(self):
        dialog = MapAnimationEditorDialog(project=self.project)
        for kind in ("background", "movement", "sprite"):
            row = dialog.rule_lists[kind].currentRow()
            self.assertEqual(dialog.rule_name_edits[kind].text(), dialog.rule_names[kind][row])
            self.assertFalse(dialog.rule_name_edits[kind].isReadOnly())
        self.assertFalse(dialog.animation_name.isReadOnly())
        self.assertEqual(dialog.sprite_preview_library.currentText(), "[08]008：82010")
        self.assertTrue(dialog.sprite_preview_library.isEnabled())
        self.assertTrue(dialog.rule_add_buttons["movement"].isEnabled())
        self.assertTrue(dialog.rule_add_buttons["sprite"].isEnabled())
        self.assertTrue(dialog.animation_puzzle_button.isEnabled())
        self.assertTrue(dialog.sprite_x.isReadOnly())
        self.assertTrue(dialog.sprite_y.isReadOnly())
        self.assertFalse(dialog.rule_codes["sprite"].isReadOnly())
        dialog.reject()

    def test_add_sprite_rule_is_cancelable_and_commits_name_with_bytes(self):
        original = bytes(self.project.working)
        cancelled = MapAnimationEditorDialog(project=self.project)
        cancelled.rule_lists["sprite"].setCurrentRow(0)
        cancelled.rule_add_buttons["sprite"].click()
        self.assertEqual(cancelled.rule_lists["sprite"].currentRow(), 0xEB)
        self.assertNotEqual(bytes(cancelled.draft), original)
        cancelled.reject()
        self.assertEqual(bytes(self.project.working), original)

        dialog = MapAnimationEditorDialog(project=self.project)
        source_raw = dialog.codec.record("sprite", 0).raw
        dialog.rule_lists["sprite"].setCurrentRow(0)
        dialog.rule_add_buttons["sprite"].click()
        dialog.accept()
        self.assertEqual(dialog.result(), QDialog.DialogCode.Accepted)
        codec = AnimationCodec(self.project.working)
        self.assertEqual(codec.record("sprite", 0xEB).raw, source_raw)
        self.assertEqual(
            self.project.animation_label_overrides[("sprite", 0xEB)],
            f"{dialog.rule_names['sprite'][0]} 副本",
        )
        self.assertEqual(len(self.project._undo_stack), 1)
        self.project.undo()
        self.assertEqual(bytes(self.project.working), original)
        self.assertFalse(self.project.animation_label_overrides)

    def test_add_movement_rule_binds_current_map_and_is_one_transaction(self):
        original = bytes(self.project.working)
        cancelled = MapAnimationEditorDialog(project=self.project)
        cancelled.animation_list.setCurrentRow(1)
        cancelled.rule_lists["movement"].setCurrentRow(1)
        cancelled.rule_add_buttons["movement"].click()
        self.assertEqual(cancelled.rule_lists["movement"].currentRow(), 0x7D)
        self.assertEqual(
            AnimationCodec(cancelled.draft).movement_roles()[0x7D],
            {"frames"},
        )
        cancelled.reject()
        self.assertEqual(bytes(self.project.working), original)

        dialog = MapAnimationEditorDialog(project=self.project)
        source_raw = dialog.codec.record("movement", 1).raw
        dialog.animation_list.setCurrentRow(1)
        dialog.rule_lists["movement"].setCurrentRow(1)
        dialog.rule_add_buttons["movement"].click()
        dialog.accept()
        self.assertEqual(dialog.result(), QDialog.DialogCode.Accepted)
        codec = AnimationCodec(self.project.working)
        self.assertEqual(codec.record("movement", 0x7D).raw, source_raw)
        self.assertEqual(codec.movement_roles()[0x7D], {"frames"})
        self.assertEqual(
            self.project.animation_label_overrides[("movement", 0x7D)],
            f"{dialog.rule_names['movement'][1]} 副本",
        )
        self.assertEqual(len(self.project._undo_stack), 1)
        self.project.undo()
        self.assertEqual(bytes(self.project.working), original)
        self.assertFalse(self.project.animation_label_overrides)

    def test_project_animation_names_accept_cancel_undo_and_reopen(self):
        original = bytes(self.project.working)
        cancelled = MapAnimationEditorDialog(project=self.project)
        cancelled.animation_name.setText("取消的动画名")
        cancelled.animation_name.textEdited.emit("取消的动画名")
        cancelled.reject()
        self.assertFalse(self.project.animation_label_overrides)

        dialog = MapAnimationEditorDialog(project=self.project)
        map_row = dialog.animation_list.currentRow()
        background_row = dialog.rule_lists["background"].currentRow()
        dialog.animation_name.setText("工程动画名")
        dialog.animation_name.textEdited.emit("工程动画名")
        background_name = dialog.rule_name_edits["background"]
        background_name.setText("工程背景名")
        background_name.textEdited.emit("工程背景名")
        dialog.accept()
        self.assertEqual(dialog.result(), QDialog.DialogCode.Accepted)
        expected = {
            ("map", map_row): "工程动画名",
            ("background", background_row): "工程背景名",
        }
        self.assertEqual(self.project.animation_label_overrides, expected)
        self.assertEqual(bytes(self.project.working), original)
        self.assertEqual(len(self.project._undo_stack), 1)

        self.project.undo()
        self.assertFalse(self.project.animation_label_overrides)
        self.project.redo()
        self.assertEqual(self.project.animation_label_overrides, expected)

        with tempfile.TemporaryDirectory() as directory:
            project_path = Path(directory) / "animation-names.dcmod"
            self.project.save_project(project_path)
            reopened = RomProject.load_project(project_path, ROM)
        self.assertEqual(reopened.animation_label_overrides, expected)
        reopened_dialog = MapAnimationEditorDialog(project=reopened)
        self.assertEqual(reopened_dialog.names[map_row], "工程动画名")
        self.assertEqual(
            reopened_dialog.rule_names["background"][background_row],
            "工程背景名",
        )
        reopened_dialog.reject()

    def test_add_map_animation_is_a_cancelable_atomic_clone(self):
        original = bytes(self.project.working)
        cancelled = MapAnimationEditorDialog(project=self.project)
        cancelled.animation_list.setCurrentRow(1)
        cancelled.add_button.click()
        self.assertEqual(cancelled.animation_list.currentRow(), 0x3F)
        self.assertNotEqual(bytes(cancelled.draft), original)
        cancelled.reject()
        self.assertEqual(bytes(self.project.working), original)

        dialog = MapAnimationEditorDialog(project=self.project)
        source_raw = dialog.codec.record("map", 1).raw
        dialog.animation_list.setCurrentRow(1)
        dialog.add_button.click()
        self.assertEqual(dialog.animation_list.currentRow(), 0x3F)
        dialog.accept()
        self.assertEqual(dialog.result(), QDialog.DialogCode.Accepted)
        codec = AnimationCodec(self.project.working)
        self.assertEqual(codec.record("map", 0x3F).raw, source_raw)
        self.assertEqual(
            self.project.animation_label_overrides[("map", 0x3F)],
            f"{dialog.names[1]} 副本",
        )
        self.assertEqual(len(self.project._undo_stack), 1)
        self.project.undo()
        self.assertEqual(bytes(self.project.working), original)
        self.assertFalse(self.project.animation_label_overrides)

    def test_referenced_background_rule_edit_is_atomic_and_bounded(self):
        dialog = MapAnimationEditorDialog(project=self.project)
        dialog.rule_lists["background"].setCurrentRow(3)
        self.assertFalse(dialog.rule_codes["background"].isReadOnly())
        raw = bytearray.fromhex(dialog.rule_codes["background"].toPlainText())
        raw[5] ^= 1
        dialog.rule_codes["background"].setPlainText(raw.hex(" "))
        dialog.accept()
        self.assertEqual(dialog.result(), QDialog.DialogCode.Accepted)
        self.assertEqual(self.project.working[0x1661A], raw[5])
        self.assertEqual(len(self.project._undo_stack), 1)
        self.project.undo()
        self.assertEqual(self.project.working, self.project.original)

        blocked = MapAnimationEditorDialog(project=self.project)
        blocked.rule_lists["background"].setCurrentRow(2)
        self.assertTrue(blocked.rule_codes["background"].isReadOnly())
        blocked.reject()

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
