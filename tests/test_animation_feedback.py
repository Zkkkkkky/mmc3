from __future__ import annotations

import os
import hashlib
from dataclasses import replace
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QPoint, Qt
from PySide6.QtGui import QImage
from PySide6.QtWidgets import (
    QApplication, QComboBox, QDialog, QDialogButtonBox, QLabel, QMessageBox,
)

from fc_editor.codecs.animation import (
    AnimationCodec,
    apply_animation_patches,
    decode_background_rule,
    decode_legacy_beam_composition,
    decode_script,
    decode_sprite_composition,
    decode_sprite_timeline,
    encode_legacy_sprite_composition,
    encode_legacy_beam_composition,
    encode_sprite_composition,
)
from fc_editor.codecs.production_credits import ProductionCreditsCodec
from fc_rom_editor_core import RomProject
from dc_modifier.animation_editor import (
    AnimationPointerDialog,
    MapAnimationEditorDialog,
    MapAnimationPreviewDialog,
    RuntimeMapAnimationPlaybackDialog,
    SpritePuzzlePreviewDialog,
    WeaponAnimationWidget,
    WeaponAnimationCommandDialog,
    WeaponAnimationCommandPaletteDialog,
    _LEGACY_WEAPON_INSERT_ROWS,
)
from dc_modifier.map_animation_runtime_preview import (
    SPIRIT_PREVIEW_CALL_OFFSET,
    TITLE_PREVIEW_CALL_OFFSET,
    prepare_map_animation_runtime_preview,
    runtime_preview_frames,
)
from tests.qt_test_case import QtTestCase

ROOT = Path(__file__).resolve().parents[1]
ROM = ROOT / "output/rom/DC_kuorong_464K.nes"


@unittest.skipUnless(ROM.is_file(), "需要正式构建 ROM")
class AnimationCodecTests(unittest.TestCase):
    def test_legacy_beam_literal_f3_codec_matches_reference_two_tile_golden(self) -> None:
        before = bytes.fromhex("FE 0A 10 78 F3 00 00 FF")
        decoded = decode_legacy_beam_composition(before)
        self.assertTrue(decoded.complete)
        self.assertTrue(decoded.editable)
        self.assertEqual((decoded.anchor_x, decoded.anchor_y), (0x10, 0x0A))
        self.assertEqual(
            [(item.tile_token, item.x, item.y) for item in decoded.placements],
            [(0x78, 0x10, 0x0A)],
        )
        placements = (
            replace(decoded.placements[0], tile_index=0xB8, tile_token=0xB8),
            replace(
                decoded.placements[0],
                x=0x14,
                y=0x0F,
                tile_index=0xA4,
                tile_token=0xA4,
            ),
        )
        self.assertEqual(
            encode_legacy_beam_composition(
                placements,
                anchor_x=decoded.anchor_x,
                anchor_y=decoded.anchor_y,
            ),
            bytes.fromhex("FE 0A 10 B8 F3 05 03 A4 F3 00 00 FF"),
        )

    def test_legacy_beam_compressed_stream_is_editable_and_round_trips(self) -> None:
        decoded = decode_legacy_beam_composition(
            bytes.fromhex("FE 06 10 FD 20 20 F8 FF 00 FF")
        )
        self.assertTrue(decoded.complete)
        self.assertTrue(decoded.editable)
        self.assertEqual(decoded.unsupported_commands, ())
        self.assertEqual(decoded.error, "")
        self.assertEqual(len(decoded.placements), 0xFF)
        self.assertEqual(
            (decoded.placements[0].x, decoded.placements[0].y),
            (0x10, 0x06),
        )
        self.assertEqual(
            (decoded.placements[32].x, decoded.placements[32].y),
            (0x10, 0x07),
        )
        self.assertEqual(
            encode_legacy_beam_composition(
                decoded.placements,
                anchor_x=decoded.anchor_x,
                anchor_y=decoded.anchor_y,
            ),
            bytes.fromhex("FE 06 10 FD 20 20 F8 FF 00 FF"),
        )

    def test_legacy_beam_compressed_replace_and_delete_preserve_geometry(self) -> None:
        original = decode_legacy_beam_composition(
            bytes.fromhex("FE 06 10 FD 20 20 F8 FF 00 FF")
        )
        changed = list(original.placements)
        changed[164] = replace(
            changed[164], tile_index=0xA4, tile_token=0xA4
        )
        encoded = encode_legacy_beam_composition(
            changed,
            anchor_x=original.anchor_x,
            anchor_y=original.anchor_y,
        )
        self.assertLess(len(encoded), 24)
        decoded = decode_legacy_beam_composition(encoded)
        self.assertTrue(decoded.complete)
        self.assertTrue(decoded.editable)
        self.assertEqual(
            [(item.x, item.y, item.tile_token) for item in decoded.placements],
            [(item.x, item.y, item.tile_token) for item in changed],
        )

        del changed[164]
        deleted_raw = encode_legacy_beam_composition(
            changed,
            anchor_x=original.anchor_x,
            anchor_y=original.anchor_y,
        )
        deleted = decode_legacy_beam_composition(deleted_raw)
        self.assertTrue(deleted.complete)
        self.assertEqual(
            [(item.x, item.y, item.tile_token) for item in deleted.placements],
            [(item.x, item.y, item.tile_token) for item in changed],
        )

    def test_legacy_beam_f8_repeat_f9_sequence_and_f3_cursor_follow_reference(self) -> None:
        repeated = decode_legacy_beam_composition(
            bytes.fromhex(
                "FE 07 85 F8 0B 00 F3 03 F5 F8 0B 00 "
                "F3 03 F5 F8 0B 00 FF"
            )
        )
        self.assertTrue(repeated.complete)
        self.assertEqual(len(repeated.placements), 33)
        self.assertEqual(
            [(repeated.placements[i].x, repeated.placements[i].y)
             for i in (0, 11, 22)],
            [(0x85, 0x07), (0x85, 0x0A), (0x85, 0x0D)],
        )
        sequential = decode_legacy_beam_composition(
            bytes.fromhex("FE 09 10 FD 20 08 F9 08 40 FF")
        )
        self.assertEqual(
            [item.tile_token for item in sequential.placements],
            list(range(0x40, 0x48)),
        )

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
        self.assertEqual(len(record.instructions), 12)
        self.assertEqual(record.instructions[0].text, "切换00区域的图库号：图库编号:0A")
        self.assertEqual(record.instructions[1].text, "调用颜色（物理）：颜色三字节:28 17 20")
        self.assertEqual(record.instructions[2].text, "刷新调色板/显示状态：00")
        self.assertEqual(self.codec.record("movement", 1).raw[:8], bytes.fromhex("09 FB 04 FC 0A FB 04 FC"))
        self.assertEqual(self.codec.record("background", 0).raw[:6], bytes.fromhex("FC 20 00 FC 20 4F"))
        self.assertEqual(self.codec.record("ally", 1).offset, 0x44230)
        self.assertEqual(self.codec.record("enemy", 1).offset, 0x40230)

    def test_call_scan_is_reused_by_status_checks(self):
        calls = self.codec.calls()
        self.assertIs(self.codec.calls(), calls)
        for offset, _animation_id in calls:
            self.codec.call_status(offset)
        self.assertIs(self.codec.calls(), calls)

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

    def test_weapon_movement_command_is_one_editable_instruction(self):
        rows, complete = decode_script(bytes.fromhex("42 69 02 06 07 FF"), 0x100)
        self.assertTrue(complete)
        self.assertEqual([row.raw for row in rows], [bytes.fromhex("42 69 02 06 07"), b"\xFF"])
        self.assertIn("调取物体运行规律(42 69", rows[0].text)
        self.assertEqual(len(rows[0].editable), 4)

    def test_title_animation_background_offset_is_a_bounded_editable_parameter(self):
        rows, complete = decode_script(bytes.fromhex("F7 70 F8 FF"), 0x100)
        self.assertTrue(complete)
        self.assertEqual(rows[0].text, "设置背景位置：状态代码:70 X轴偏移:-8")
        self.assertEqual(rows[0].editable, ((2, 0, 255),))
        record = self.codec.record("map", 0)
        changed = bytearray(record.raw)
        target = next(
            row for row in record.instructions
            if row.raw[:2] == bytes.fromhex("F7 70")
        )
        local = target.offset - record.offset + 2
        changed[local] = 0xF7
        patch_row = self.codec.script_patch(record, bytes(changed))
        self.assertEqual(patch_row[0], record.offset)
        self.assertEqual(patch_row[2][local], 0xF7)

    def test_weapon_sequence_insert_relocates_later_records_and_rebases_pointers(self):
        record = self.codec.record("ally", 1)
        later_before = self.codec.record("ally", 3)
        replacement = record.raw[:-1] + b"\x01\xFF"
        patch = self.codec.script_sequence_patch(record, replacement)
        self.assertGreater(len(patch[1]), len(record.raw))
        apply_animation_patches(self.project, (patch,), "插入武器动画指令")
        changed = AnimationCodec(self.project.working)
        self.assertEqual(changed.record("ally", 1).raw, replacement)
        later_after = changed.record("ally", 3)
        self.assertEqual(later_after.raw, later_before.raw)
        self.assertEqual(later_after.offset, later_before.offset + 1)
        self.assertFalse([issue for issue in self.project.validate() if issue.severity == "error"])
        with tempfile.TemporaryDirectory() as directory:
            saved = Path(directory) / "weapon_sequence_insert.nes"
            self.project.save_as(saved, make_backup=False)
            reopened = AnimationCodec(RomProject.load(saved).working)
            self.assertEqual(reopened.record("ally", 1).raw, replacement)
            self.assertEqual(reopened.record("ally", 3).raw, later_before.raw)
            self.assertEqual(reopened.record("ally", 3).offset, later_before.offset + 1)

    def test_weapon_sequence_delete_keeps_terminator_and_next_record(self):
        record = self.codec.record("ally", 1)
        later = self.codec.record("ally", 3)
        replacement = b"".join(row.raw for row in record.instructions[1:])
        patch = self.codec.script_sequence_patch(record, replacement)
        apply_animation_patches(self.project, (patch,), "删除武器动画指令")
        changed = AnimationCodec(self.project.working)
        self.assertEqual(changed.record("ally", 1).raw, replacement)
        self.assertEqual(changed.record("ally", 3).raw, later.raw)
        self.assertEqual(
            changed.record("ally", 3).offset,
            later.offset - (len(record.raw) - len(replacement)),
        )

    def test_weapon_ff_insert_matches_shared_middle_and_unique_reference_goldens(self):
        cases = (
            ("ally", 1, 1, "6E577B780D06D45277F5154D159E87E1EB57A10A7F165F1E251054B3045C46D4"),
            ("ally", 20, 0, "464F06D1EAD5449C9FA470C1A84AFE68A542E3B90F79F4F6EAD71DA51801B4BC"),
            ("enemy", 1, 0, "2118F30B806BA3ECF957807B65BEB65B2F0D96F0491CB8E5130C9E6F627AA056"),
            ("enemy", 29, 27, "3274B03300847E97CF3582D1C191D52481E95FDA0ABAD4D2D4071C810C4D1354"),
        )
        for kind, weapon_id, row, expected_hash in cases:
            with self.subTest(kind=kind, weapon_id=weapon_id, row=row):
                project = RomProject.load(ROM)
                codec = AnimationCodec(project.working)
                record = codec.record(kind, weapon_id)
                patch = codec.script_insert_end_patch(record, row)
                apply_animation_patches(project, (patch,), "插入 FF 动画结束")
                self.assertEqual(
                    hashlib.sha256(project.working).hexdigest().upper(),
                    expected_hash,
                )
                changed = AnimationCodec(project.working)
                expected_visible = (
                    b"".join(item.raw for item in record.instructions[:row])
                    + b"\xFF"
                )
                self.assertEqual(
                    changed.record(kind, weapon_id).raw,
                    expected_visible,
                )

    def test_weapon_ff_insert_on_existing_end_is_a_noop(self):
        record = self.codec.record("enemy", 29)
        end = len(record.instructions) - 1
        self.assertEqual(record.instructions[end].raw, b"\xFF")
        with self.assertRaisesRegex(ValueError, "已经是动画结束"):
            self.codec.script_insert_end_patch(record, end)

    def test_map_pool_reclaims_shrunk_bytes_for_later_growth(self):
        usage = self.codec.script_pool_usage("map")
        self.assertEqual((usage.capacity, usage.used, usage.free), (7890, 5584, 2306))
        shrink = self.codec.record("map", 14)
        shrink_patch = self.codec.script_sequence_patch(shrink, b"\xFF")
        shrunk_data = bytearray(self.project.working)
        shrunk_data[shrink_patch[0]:shrink_patch[0] + len(shrink_patch[2])] = shrink_patch[2]
        shrunk = AnimationCodec(shrunk_data)
        released = len(shrink.raw) - 1
        self.assertEqual(shrunk.script_pool_usage("map").free, usage.free + released)

        grow = shrunk.record("map", 1)
        replacement = grow.raw[:-1] + b"\x01" * (usage.free + 1) + b"\xFF"
        grow_patch = shrunk.script_sequence_patch(grow, replacement)
        shrunk_data[grow_patch[0]:grow_patch[0] + len(grow_patch[2])] = grow_patch[2]
        grown = AnimationCodec(shrunk_data)
        self.assertEqual(grown.record("map", 1).raw, replacement)
        self.assertEqual(grown.record("map", 14).raw, b"\xFF")
        self.assertGreaterEqual(grown.script_pool_usage("map").free, 0)

    def test_map_pool_overflow_is_rejected_without_partial_patch(self):
        record = self.codec.record("map", 1)
        free = self.codec.script_pool_usage("map").free
        replacement = record.raw[:-1] + b"\x01" * (free + 1) + b"\xFF"
        before = bytes(self.project.working)
        with self.assertRaisesRegex(ValueError, "总容量.*还差"):
            self.codec.script_sequence_patch(record, replacement)
        self.assertEqual(bytes(self.project.working), before)

    def test_pool_repack_relocates_cross_record_fe_target(self):
        source = self.codec.record("ally", 1)
        target = self.codec.record("ally", 4)
        target_pointer = self.codec.pointers["ally"][4]
        with_cross_jump = (
            source.raw[:-1]
            + b"\xFE\x01"
            + target_pointer.to_bytes(2, "little")
            + b"\xFF"
        )
        first_patch = self.codec.script_sequence_patch(source, with_cross_jump)
        draft = bytearray(self.project.working)
        draft[first_patch[0]:first_patch[0] + len(first_patch[2])] = first_patch[2]
        first = AnimationCodec(draft)

        moved_target = first.record("ally", 4)
        grown_target = moved_target.raw[:-1] + b"\x01\xFF"
        second_patch = first.script_sequence_patch(moved_target, grown_target)
        draft[second_patch[0]:second_patch[0] + len(second_patch[2])] = second_patch[2]
        second = AnimationCodec(draft)
        jump = next(
            row
            for row in second.record("ally", 1).instructions
            if row.raw[:1] == b"\xFE"
        )
        self.assertEqual(
            int.from_bytes(jump.raw[2:4], "little"),
            second.pointers["ally"][4],
        )

    def test_weapon_sequence_insert_rebases_internal_fe_target(self):
        record = self.codec.record("ally", 4)
        loop_row = next(row for row in record.instructions if row.raw[:1] == b"\xFE")
        loop_target = int.from_bytes(loop_row.raw[2:4], "little")
        pointer = self.codec.pointers["ally"][4]
        target_index, target_row = next(
            (index, row)
            for index, row in enumerate(record.instructions)
            if pointer + row.offset - record.offset == loop_target
        )
        self.assertEqual(
            loop_target, pointer + target_row.offset - record.offset,
        )
        replacement = b"".join(
            row.raw for row in record.instructions[:target_index]
        ) + b"\x01" + b"".join(
            row.raw for row in record.instructions[target_index:]
        )
        patch = self.codec.script_sequence_patch(record, replacement)
        apply_animation_patches(self.project, (patch,), "插入循环目标前指令")
        changed = AnimationCodec(self.project.working)
        changed_record = changed.record("ally", 4)
        changed_loop = next(
            row for row in changed_record.instructions if row.raw[:1] == b"\xFE"
        )
        self.assertEqual(
            int.from_bytes(changed_loop.raw[2:4], "little"),
            pointer + target_row.offset - record.offset + 1,
        )

    def test_weapon_sequence_delete_rejects_referenced_instruction(self):
        record = self.codec.record("ally", 4)
        pointer = self.codec.pointers["ally"][4]
        loop = next(row for row in record.instructions if row.raw[:1] == b"\xFE")
        target = int.from_bytes(loop.raw[2:4], "little")
        target_index = next(
            index for index, row in enumerate(record.instructions)
            if pointer + row.offset - record.offset == target
        )
        replacement = b"".join(
            row.raw
            for index, row in enumerate(record.instructions)
            if index != target_index
        )
        with self.assertRaisesRegex(ValueError, "循环目标.*已删除"):
            self.codec.script_sequence_patch(record, replacement)

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

        canonical = encode_sprite_composition(composition.placements)
        decoded = decode_sprite_composition(canonical)
        self.assertTrue(decoded.complete)
        self.assertEqual(
            [
                (item.tile_token, item.x, item.y, item.attributes & 0xC3)
                for item in decoded.placements
            ],
            [
                (item.tile_token, item.x, item.y, item.attributes & 0xC3)
                for item in composition.placements
            ],
        )

        self.assertEqual(encode_legacy_sprite_composition(composition.placements), raw)

    def test_reference_physical_puzzle_compact_flip_bytes(self):
        raw = bytes.fromhex(
            "00 00 01 00 00 08 F0 00 00 00 28 04 E8 80 80 80 "
            "A8 01 E8 80 80 80 FF"
        )
        composition = decode_sprite_composition(raw)
        flipped = [
            item.__class__(
                command_offset=item.command_offset,
                x=-item.x,
                y=item.y,
                tile_index=item.tile_index,
                tile_token=item.tile_token,
                attributes=item.attributes ^ 0x40,
            )
            for item in composition.placements
        ]
        self.assertEqual(
            encode_legacy_sprite_composition(flipped),
            bytes.fromhex(
                "00 00 01 44 F8 44 F8 48 10 44 F8 44 F8 44 F8 68 "
                "04 18 C4 F8 C4 F8 C4 F8 E8 01 18 C4 F8 C4 F8 C0 FF"
            ),
        )

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
            78,
        )
        patch = self.codec.call_patch(0x3BB93, 2)
        self.assertEqual(patch, (0x3BB95, b"\x2c", b"\x02"))
        with self.assertRaises(ValueError):
            self.codec.call_patch(0x3BB93, 255)
        with self.assertRaises(ValueError):
            self.codec.call_patch(0x3BB94, 2)
        self.assertFalse(self.codec.call_is_editable(0x3804A))
        self.assertIn("资料编号冲突", self.codec.call_status(0x3804A)[1])
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
            0x380DF: "参考逐字段保存同址黄金",
            0x38EEA: "参考逐字段保存同址黄金",
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
        self.assertEqual(len(readonly), 8)
        self.assertIn(0x3804A, readonly)

    def test_background_and_call_guards_explain_the_exact_reason(self):
        editable, status = self.codec.background_edit_status(3)
        self.assertTrue(editable)
        self.assertIn("已验证绘制参数", status)
        editable, status = self.codec.background_edit_status(2)
        self.assertFalse(editable)
        self.assertIn("没有背景结束码", status)
        editable, status = self.codec.call_status(0x3B9DC)
        self.assertFalse(editable)
        self.assertIn("嵌入数据未验证", status)

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
        self.assertEqual((editable, blocked), (78, 8))
        self.assertEqual(bytes(dialog.draft), original)
        self.assertEqual(bytes(self.project.working), original)

    def test_verified_calls_allow_second_change_and_survive_save_reopen(self):
        dialog = MapAnimationEditorDialog(project=self.project)
        self.addCleanup(dialog.close)
        original = bytes(self.project.working)
        offsets = (0x380DF, 0x38113, 0x384F2, 0x38EEA)
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

    def test_opening_subtitles_are_staged_inside_map_animation_transaction(self):
        original = bytes(self.project.working)
        cancelled = MapAnimationEditorDialog(project=self.project)
        self.addCleanup(cancelled.close)
        self.assertTrue(cancelled.credits_button.isHidden())
        cancelled.animation_list.setCurrentRow(0x13)
        self.assertFalse(cancelled.credits_button.isHidden())
        production, cast = self.project.get_production_credits()
        changed_cast = cast.text.replace("太勒", "太")
        cancelled._pending_credits = (production.text, changed_cast)
        cancelled.reject()
        self.assertEqual(bytes(self.project.working), original)
        self.assertFalse(self.project.can_undo)

        accepted = MapAnimationEditorDialog(project=self.project)
        self.addCleanup(accepted.close)
        accepted.animation_list.setCurrentRow(0x14)
        self.assertFalse(accepted.credits_button.isHidden())
        accepted._pending_credits = (production.text, changed_cast)
        accepted.accept()
        self.assertEqual(accepted.result(), QDialog.DialogCode.Accepted)
        self.assertNotIn("勒", self.project.get_production_credits()[1].text)
        self.assertEqual(len(self.project._undo_stack), 1)
        self.project.undo()
        self.assertEqual(bytes(self.project.working), original)

    def test_pending_opening_subtitles_are_included_in_preview_copy(self):
        original = bytes(self.project.working)
        dialog = MapAnimationEditorDialog(project=self.project)
        self.addCleanup(dialog.close)
        production, cast = self.project.get_production_credits()
        changed_cast = cast.text.replace("太勒", "太")
        dialog._pending_credits = (production.text, changed_cast)

        preview_data = dialog._preview_data()
        preview_production, preview_cast = ProductionCreditsCodec(
            preview_data
        ).records(
            preview_data,
            text_table=self.project.dc_text_table(channel="story"),
        )

        self.assertEqual(preview_production.text, production.text)
        self.assertEqual(preview_cast.text, changed_cast)
        self.assertNotEqual(preview_data, original)
        self.assertEqual(bytes(self.project.working), original)
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

    def test_map_variable_length_accept_save_reopen_undo_redo(self):
        dialog = MapAnimationEditorDialog(project=self.project)
        self.assertEqual(dialog.names[0], "开始界面标题组合动画")
        self.assertEqual(
            dialog.animation_list.item(0).text(),
            "[00]000：开始界面标题组合动画",
        )
        original = dialog.script_editor.record.raw
        usage = AnimationCodec(dialog.draft).script_pool_usage("map")
        self.assertIsNone(dialog.script_editor.structure_bar)
        self.assertTrue(dialog.script_editor.pool_status.isHidden())
        self.assertEqual(
            dialog.script_editor.pool_usage.format(),
            f"内存：已用 {usage.used} / {usage.capacity} 字节｜剩余 {usage.free} 字节",
        )
        self.assertIn("当前动画共 9 项动作", dialog.script_editor.status.text())
        self.assertIn("实际为 12 条底层指令", dialog.script_editor.status.toolTip())
        self.assertEqual(
            dialog.instruction_table.item(0, 0).text(),
            "000：切换00区域的图库号：图库编号:0A",
        )
        self.assertTrue(dialog.instruction_table.isRowHidden(2))
        self.assertEqual(
            dialog.instruction_table.item(4, 0).text().splitlines(),
            [
                "003：创建物体： 物体编号:0F 物体X坐标:248 物体Y坐标:248",
            ],
        )
        self.assertEqual(
            dialog.instruction_table.item(5, 0).text(),
            "004：调取物体运行规律(40 68：地图动画专用)："
            "取图规律号:[01]001 X轴运行规律号[02]002 Y轴运行规律号[02]002",
        )
        self.assertGreaterEqual(dialog.instruction_table.rowCount(), 23)
        self.assertEqual(dialog.instruction_table.rowHeight(0), 18)
        dialog.show()
        QApplication.processEvents()
        self.assertEqual((dialog.width(), dialog.height()), (900, 650))
        self.assertEqual(dialog.animation_selection_group.title(), "动画选择")
        self.assertEqual(dialog.animation_editor_group.title(), "动画编辑")
        self.assertLessEqual(
            abs(
                dialog.animation_selection_group.geometry().top()
                - dialog.animation_editor_group.geometry().top()
            ),
            1,
        )
        self.assertEqual(dialog.read_only_status.objectName(), "infoPanel")
        self.assertGreaterEqual(
            dialog.instruction_table.viewport().height(),
            23 * dialog.instruction_table.rowHeight(0),
        )
        self.assertEqual(
            dialog.instruction_table.item(1, 0).background().style(),
            Qt.BrushStyle.NoBrush,
        )
        replacement = original[:-1] + b"\x01\xFF"
        dialog.script_editor.code_edit.setPlainText(replacement.hex(" "))
        self.assertEqual(
            dialog.script_editor.pool_usage.format(),
            f"内存：已用 {usage.used + 1} / {usage.capacity} 字节｜剩余 {usage.free - 1} 字节",
        )
        dialog.accept()
        self.assertEqual(dialog.result(), QDialog.DialogCode.Accepted)
        self.assertEqual(AnimationCodec(self.project.working).record("map", 1).raw, replacement)
        self.assertFalse(
            [issue for issue in self.project.validate() if issue.severity == "error"]
        )
        self.project.undo()
        self.assertEqual(bytes(self.project.working), self.project.original)
        self.project.redo()
        self.assertEqual(AnimationCodec(self.project.working).record("map", 1).raw, replacement)
        with tempfile.TemporaryDirectory() as directory:
            saved = Path(directory) / "map-variable-length.nes"
            self.project.save_as(saved, make_backup=False)
            reopened = AnimationCodec(RomProject.load(saved).working)
            self.assertEqual(reopened.record("map", 1).raw, replacement)

    def test_map_reference_layout_hides_inline_panel_but_keeps_safe_object_editors(self):
        dialog = MapAnimationEditorDialog(project=self.project)
        self.addCleanup(dialog.close)
        before_rom = bytes(self.project.working)
        self.assertTrue(dialog.script_editor.parameters.isHidden())

        dialog.instruction_table.setCurrentCell(0, 0)
        library = dialog.script_editor.parameters.findChild(
            QComboBox, "animationParameter1"
        )
        self.assertIsNotNone(library)
        self.assertIn("ROM $", library.currentText())

        dialog.instruction_table.setCurrentCell(4, 0)
        QApplication.processEvents()
        object_slot = next(
            combo for combo in dialog.script_editor.parameters.findChildren(QComboBox)
            if combo.objectName() == "animationParameter1" and combo.count() == 0xFF
        )
        self.assertEqual(object_slot.count(), 0xFF)
        record = dialog.script_editor.record
        instruction = record.instructions[4]
        byte_index = instruction.offset - record.offset + 1
        object_slot.setCurrentIndex(0x2A)
        draft = bytes.fromhex(dialog.script_editor.code_edit.toPlainText())
        self.assertEqual(draft[byte_index], 0x2A)
        self.assertEqual(bytes(self.project.working), before_rom)

        dialog.instruction_table.setCurrentCell(5, 0)
        QApplication.processEvents()
        sprite_rule = dialog.script_editor.parameters.findChild(
            QComboBox, "animationParameter2"
        )
        x_rule = dialog.script_editor.parameters.findChild(
            QComboBox, "animationParameter3"
        )
        y_rule = dialog.script_editor.parameters.findChild(
            QComboBox, "animationParameter4"
        )
        self.assertGreater(sprite_rule.count(), 200)
        self.assertGreater(x_rule.count(), 100)
        self.assertGreater(y_rule.count(), 100)
        self.assertNotIn("未命名", sprite_rule.itemText(1))
        self.assertIn("状态代码", " ".join(
            label.text() for label in dialog.script_editor.parameters.findChildren(QLabel)
        ))

        details = WeaponAnimationCommandDialog(
            raw=instruction.raw,
            allow_type_change=False,
        )
        self.addCleanup(details.close)
        self.assertEqual(
            [local for local, _editor, _signed in details.parameter_editors],
            [2, 3],
        )

    def test_bad_hex_and_changed_command_block_switch_and_accept(self):
        dialog = MapAnimationEditorDialog(project=self.project)
        dialog.script_editor.code_edit.setPlainText("F")
        dialog.animation_list.setCurrentRow(2)
        self.assertEqual(dialog.animation_list.currentRow(), 1)
        dialog.accept()
        self.assertEqual(dialog.result(), 0)
        self.assertFalse(self.project.can_undo)
        dialog.reject()

    def test_pointer_dialog_locates_existing_animation_without_writing_rom(self):
        dialog = MapAnimationEditorDialog(project=self.project)
        before = bytes(dialog.draft)
        self.assertEqual(
            dialog.instruction_table.contextMenuPolicy(),
            Qt.ContextMenuPolicy.CustomContextMenu,
        )
        self.assertIsNone(dialog.script_editor.structure_bar)
        self.assertFalse(dialog.script_editor.code_edit.isVisible())
        target = dialog.codec.pointers["map"][2]
        with patch.object(
            AnimationPointerDialog,
            "exec",
            return_value=QDialog.DialogCode.Accepted,
        ), patch.object(
            AnimationPointerDialog,
            "pointer",
            return_value=target,
        ):
            dialog.code_button.click()
        self.assertEqual(dialog.animation_list.currentRow(), 2)
        self.assertFalse(dialog.script_editor.code_edit.isHidden())
        self.assertIn(f"${target:04X}", dialog.script_editor.status.text())
        self.assertIn("结构代码区已展开", dialog.script_editor.status.text())
        self.assertIn("循环目标会安全重定位", dialog.script_editor.status.text())
        self.assertEqual(bytes(dialog.draft), before)

        pointer_dialog = AnimationPointerDialog(pointer=target)
        self.assertEqual(pointer_dialog.value(), target.to_bytes(2, "little").hex().upper())
        self.assertEqual(pointer_dialog.pointer(), target)

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

        editable = SpritePuzzlePreviewDialog(
            sprite,
            self.project,
            dialog.codec,
            dialog,
            editable=True,
            puzzle_kind="physical",
        )
        self.assertEqual(editable.library_list.count(), 128)
        self.assertEqual(editable.library_list.item(0).text(), "00")
        editable.high_start_radio.click()
        self.assertEqual(editable.library_list.item(0).text(), "80")
        original = decode_sprite_composition(editable.edited_raw())
        editable._flip_composition(horizontal=True)
        flipped = decode_sprite_composition(editable.edited_raw())
        self.assertEqual(
            flipped.placements[0].x,
            -original.placements[0].x,
        )
        self.assertEqual(
            bool(flipped.placements[0].attributes & 0x40),
            not bool(original.placements[0].attributes & 0x40),
        )
        editable._flip_composition(horizontal=True)
        editable.library_list.setCurrentRow(0x48)
        editable.placement_table.selectRow(0)
        editable._preview_pressed(0.5, 0.5, Qt.MouseButton.LeftButton)
        moved = decode_sprite_composition(editable.edited_raw())
        self.assertEqual(moved.placements[0].tile_token, 0x48)
        self.assertEqual((moved.placements[0].x, moved.placements[0].y), (64, 64))
        editable._preview_pressed(0.5, 0.5, Qt.MouseButton.RightButton)
        changed = decode_sprite_composition(editable.edited_raw())
        self.assertEqual(len(changed.placements), len(original.placements))
        self.assertNotEqual(
            [item.attributes & 0x40 for item in changed.placements],
            [item.attributes & 0x40 for item in moved.placements],
        )
        editable.reject()

        beam_record = replace(
            sprite,
            raw=bytes.fromhex("10 0A 78 F3 00 00 FF"),
        )
        beam = SpritePuzzlePreviewDialog(
            beam_record,
            self.project,
            dialog.codec,
            dialog,
            editable=True,
            puzzle_kind="beam",
        )
        self.assertEqual(beam.library_list.item(0).text(), "40")
        beam.high_start_radio.click()
        beam.library_list.setCurrentRow(0x24)
        self.assertEqual(beam.library_list.item(0x24).text(), "A4")
        beam_before = decode_legacy_beam_composition(
            beam._beam_full(beam.edited_raw())
        )
        beam._preview_pressed(
            (4 * 8 + 1) / 128,
            (15 * 8 + 1) / 128,
            Qt.MouseButton.LeftButton,
        )
        beam_replaced = decode_legacy_beam_composition(
            beam._beam_full(beam.edited_raw())
        )
        self.assertIn(0xA4, [item.tile_token for item in beam_replaced.placements])
        self.assertEqual(
            beam.edited_raw(),
            bytes.fromhex("10 0A B8 F3 05 03 A4 F3 00 00 FF"),
        )
        beam._preview_pressed(
            (4 * 8 + 1) / 128,
            (15 * 8 + 1) / 128,
            Qt.MouseButton.RightButton,
        )
        beam_deleted = decode_legacy_beam_composition(
            beam._beam_full(beam.edited_raw())
        )
        self.assertEqual(
            len(beam_deleted.placements), len(beam_before.placements)
        )
        beam.reject()

        compressed_record = replace(
            sprite,
            raw=bytes.fromhex("10 06 FD 20 20 F8 FF 00 FF"),
        )
        compressed = SpritePuzzlePreviewDialog(
            compressed_record,
            self.project,
            dialog.codec,
            dialog,
            editable=True,
            puzzle_kind="beam",
        )
        unchanged = compressed.code_view.toPlainText()
        compressed._preview_pressed(0.5, 0.5, Qt.MouseButton.LeftButton)
        self.assertNotEqual(compressed.code_view.toPlainText(), unchanged)
        self.assertTrue(compressed.code_error.isHidden())
        rewritten = decode_legacy_beam_composition(
            compressed._beam_full(compressed.edited_raw())
        )
        self.assertTrue(rewritten.complete)
        self.assertTrue(rewritten.editable)
        self.assertEqual(len(rewritten.placements), 0xFF)
        compressed.reject()
        dialog.reject()

    def test_map_preview_plays_current_unsaved_draft_without_writing_rom(self):
        dialog = MapAnimationEditorDialog(project=self.project)
        self.assertEqual(dialog.preview_button.text(), "游戏内真实预览")
        self.assertEqual(dialog.offline_preview_button.text(), "快速结构预览（非实机）")
        before = bytes(self.project.working)
        draft = bytearray(dialog.script_editor.record.raw)
        wait = next(
            item.offset - dialog.script_editor.record.offset
            for item in dialog.script_editor.record.instructions
            if 0 < item.raw[0] < 0xE0
            and item.raw[0] not in (0x40, 0x42, 0xC0, 0xC2)
        )
        draft[wait] = 2
        dialog.script_editor.code_edit.setPlainText(draft.hex(" "))
        self.assertTrue(dialog._flush_script())
        preview = MapAnimationPreviewDialog(
            self.project,
            dialog.draft,
            dialog.animation_list.currentRow(),
            dialog.animation_name.text(),
            dialog,
        )
        self.assertGreater(len(preview.frames), 1)
        self.assertFalse(preview.preview_label.pixmap().isNull())
        self.assertEqual(preview.frame_slider.maximum(), len(preview.frames) - 1)
        preview.timer.stop()
        preview.next_button.click()
        self.assertEqual(preview.frame_index, 1)
        self.assertIn("第 2 /", preview.frame_status.text())
        self.assertEqual(bytes(self.project.working), before)
        preview.reject()
        dialog.reject()

    def test_runtime_preview_builds_isolated_rom_and_battle_save(self):
        before = bytes(self.project.working)
        source_save = ROOT / "references/emulator-state/fceux/sav/DC_kuorong.sav"
        battle_script = ROOT / "tests/emulator/helpers/dc_map_animation_runtime_preview.lua"
        title_script = ROOT / "tests/emulator/helpers/dc_title_animation_runtime_preview.lua"
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            artifacts = prepare_map_animation_runtime_preview(
                before,
                1,
                source_save,
                root / "output",
                root / "mesen",
                battle_script,
                title_script,
            )
            preview_rom = artifacts.rom_path.read_bytes()
            self.assertEqual(preview_rom[SPIRIT_PREVIEW_CALL_OFFSET:SPIRIT_PREVIEW_CALL_OFFSET + 3],
                             bytes.fromhex("38 02 01"))
            self.assertIsNotNone(artifacts.save_path)
            self.assertEqual(artifacts.save_path.stat().st_size, 8192)
            self.assertEqual(artifacts.context, "活动战场精神场景")
            self.assertEqual(bytes(self.project.working), before)

            title = prepare_map_animation_runtime_preview(
                before,
                0,
                source_save,
                root / "output",
                root / "mesen",
                battle_script,
                title_script,
            )
            title_rom = title.rom_path.read_bytes()
            self.assertEqual(title_rom[TITLE_PREVIEW_CALL_OFFSET:TITLE_PREVIEW_CALL_OFFSET + 3],
                             bytes.fromhex("38 02 00"))
            self.assertIsNone(title.save_path)
            self.assertEqual(title.context, "标题场景")
            self.assertEqual(bytes(self.project.working), before)

    def test_runtime_preview_player_uses_real_captured_frames(self):
        with tempfile.TemporaryDirectory() as temporary:
            folder = Path(temporary)
            first = QImage(256, 240, QImage.Format.Format_RGB32)
            first.fill(Qt.GlobalColor.black)
            second = QImage(256, 240, QImage.Format.Format_RGB32)
            second.fill(Qt.GlobalColor.red)
            self.assertTrue(first.save(str(folder / "runtime-frame-0002.png")))
            self.assertTrue(second.save(str(folder / "runtime-frame-0004.png")))
            frames = runtime_preview_frames(folder)
            self.assertEqual([path.name for path in frames], [
                "runtime-frame-0002.png", "runtime-frame-0004.png"
            ])
            player = RuntimeMapAnimationPlaybackDialog(
                frames, 1, "坠机爆炸", "活动战场精神场景"
            )
            player.timer.stop()
            self.assertFalse(player.preview_label.pixmap().isNull())
            self.assertIn("真实游戏运行帧 1 / 2", player.status.text())
            player.next_button.click()
            self.assertEqual(player.frame_index, 1)
            player.reject()

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

    def test_weapon_animation_rows_have_right_click_parameter_editor(self):
        widget = WeaponAnimationWidget()
        widget.set_record(self.project, 1)
        editor = widget.editors[0]
        self.assertEqual(
            editor.instruction_table.contextMenuPolicy(),
            Qt.ContextMenuPolicy.CustomContextMenu,
        )
        self.assertIn("右键", editor.instruction_table.toolTip())
        row = next(
            index
            for index, instruction in enumerate(editor.record.instructions)
            if instruction.editable
        )
        editor.instruction_table.setCurrentCell(row, 0)
        with patch("dc_modifier.animation_editor.QMenu.popup") as popup:
            editor._show_instruction_context_menu(QPoint(-1, -1))
        popup.assert_called_once()
        widget.close()

    def test_weapon_edit_and_insert_use_separate_command_flows(self):
        edit = WeaponAnimationCommandDialog(raw=bytes.fromhex("F4 03"))
        self.addCleanup(edit.close)
        self.assertFalse(edit.allow_type_change)
        self.assertFalse(edit.command_type.isEnabled())
        self.assertEqual(edit.windowTitle(), "定义声音")
        self.assertEqual(edit.type_label.text(), "播放音乐或音效")
        self.assertEqual(len(edit.parameter_editors), 1)
        self.assertEqual(edit.parameter_editors[0][1].text(), "03")
        edit.parameter_editors[0][1].setValue(4)
        self.assertEqual(edit.command(), bytes.fromhex("F4 04"))
        self.assertEqual(edit.parameter_editors[0][1].text(), "04")
        self.assertIn("实际效果", edit.preview_label.text())

        palette = WeaponAnimationCommandPaletteDialog()
        self.addCleanup(palette.close)
        self.assertEqual(palette.windowTitle(), "动画指令")
        self.assertFalse(hasattr(palette, "raw_edit"))
        self.assertFalse(hasattr(palette, "parameter_editors"))
        palette.command_list.setCurrentRow(0)
        self.assertEqual(palette.command_list.currentItem().text(), "F4定义声音")
        self.assertEqual(palette.preset(), bytes.fromhex("F4 00"))
        self.assertEqual(
            [palette.command_list.item(row).text() for row in range(palette.command_list.count())],
            [row[1] for row in _LEGACY_WEAPON_INSERT_ROWS],
        )
        self.assertEqual(palette.command_list.count(), 12)
        self.assertIn("F2定义光束图库", [
            palette.command_list.item(row).text()
            for row in range(palette.command_list.count())
        ])
        self.assertNotIn("F6写入IO端口2001", [
            palette.command_list.item(row).text()
            for row in range(palette.command_list.count())
        ])
        palette.command_list.setCurrentRow(3)
        self.assertEqual(palette.command_list.currentItem().text(), "F3定义光束规律")
        self.assertEqual(palette.preset(), bytes.fromhex("F3 22 01"))
        palette.command_list.setCurrentRow(0)

        insert_parameters = WeaponAnimationCommandDialog(
            raw=palette.preset(),
            allow_type_change=False,
            operation="insert",
        )
        self.addCleanup(insert_parameters.close)
        self.assertFalse(insert_parameters.command_type.isEnabled())
        self.assertEqual(
            insert_parameters.windowTitle(),
            "定义声音",
        )
        self.assertEqual(
            insert_parameters.parameter_form.labelForField(
                insert_parameters.parameter_editors[0][1]
            ).text(),
            "音乐代码",
        )

        colors = WeaponAnimationCommandDialog(
            raw=bytes.fromhex("F0 11 03 0F 16 20"),
            allow_type_change=False,
            operation="insert",
        )
        self.addCleanup(colors.close)
        self.assertEqual(len(colors.parameter_editors), 3)
        self.assertEqual(set(colors.color_swatches), {3, 4, 5})
        self.assertEqual(
            [editor.text() for _local, editor, _signed in colors.parameter_editors],
            ["0F", "16", "20"],
        )
        self.assertEqual(colors.windowTitle(), "定义颜色")
        self.assertEqual(colors.parameter_group.title(), "颜色设置")
        self.assertTrue(colors.physical_color.isChecked())
        self.assertIn("实际效果：调用颜色（物理）", colors.preview_label.text())

        beam_rule = WeaponAnimationCommandDialog(
            raw=bytes.fromhex("F3 22 02"),
            allow_type_change=False,
            operation="insert",
        )
        self.addCleanup(beam_rule.close)
        self.assertEqual(beam_rule.windowTitle(), "定义光束规律")
        self.assertEqual(len(beam_rule.parameter_editors), 0)
        self.assertEqual(beam_rule.beam_rule_combo.count(), 0xFF)
        self.assertEqual(
            beam_rule.beam_rule_combo.currentText(),
            "[02]002：消除屏幕2",
        )
        beam_rule.beam_rule_combo.setCurrentIndex(2)
        self.assertEqual(beam_rule.command(), bytes.fromhex("F3 22 03"))

        beam_library = WeaponAnimationCommandDialog(
            raw=bytes.fromhex("F2 03 01 01"),
            allow_type_change=False,
            operation="insert",
        )
        self.addCleanup(beam_library.close)
        self.assertEqual(beam_library.windowTitle(), "定义光束规律图库")
        self.assertEqual(len(beam_library.parameter_editors), 0)
        self.assertEqual(beam_library.beam_library_combo.count(), 0x100)
        self.assertEqual(
            beam_library.beam_library_combo.currentText(),
            "[01]001：80410",
        )
        with patch.object(
            QMessageBox,
            "exec",
            return_value=QMessageBox.StandardButton.No,
        ):
            beam_library._accept_command()
        self.assertEqual(beam_library.command(), bytes.fromhex("F2 03 01 01"))

        large_beam_library = WeaponAnimationCommandDialog(
            raw=bytes.fromhex("F2 03 01 01"),
            allow_type_change=False,
            operation="insert",
        )
        self.addCleanup(large_beam_library.close)
        with patch.object(
            QMessageBox,
            "exec",
            return_value=QMessageBox.StandardButton.Yes,
        ):
            large_beam_library._accept_command()
        self.assertEqual(
            large_beam_library.command(), bytes.fromhex("F2 04 01 01")
        )

        for raw, title, expected in (
            ("E0 01", "切换精灵图库0", bytes.fromhex("E0 02")),
            ("E1 01", "切换精灵图库1", bytes.fromhex("E1 02")),
        ):
            library_switch = WeaponAnimationCommandDialog(
                raw=bytes.fromhex(raw),
                allow_type_change=False,
                operation="insert",
            )
            self.addCleanup(library_switch.close)
            self.assertEqual(library_switch.windowTitle(), title)
            self.assertEqual(len(library_switch.parameter_editors), 0)
            self.assertEqual(
                library_switch.beam_library_combo.currentText(),
                "[01]001：80410",
            )
            library_switch.beam_library_combo.setCurrentIndex(2)
            self.assertEqual(library_switch.command(), expected)

        loop = WeaponAnimationCommandDialog(
            raw=bytes.fromhex("FE 02 26 82"),
            allow_type_change=False,
            operation="insert",
            loop_targets=(
                ("000：播放音乐或音效", 0x8224),
                ("001：调用颜色（物理）", 0x8226),
            ),
        )
        self.addCleanup(loop.close)
        self.assertEqual(loop.windowTitle(), "跳转重复")
        self.assertEqual(loop.loop_target_combo.count(), 200)
        self.assertEqual(loop.loop_target_combo.currentText(), "001")
        self.assertIn(
            "调用颜色（物理）",
            loop.loop_target_combo.currentData(Qt.ItemDataRole.ToolTipRole),
        )
        self.assertFalse(loop.loop_target_combo.model().item(2).isEnabled())
        loop.loop_target_combo.setCurrentIndex(0)
        self.assertEqual(loop.command(), bytes.fromhex("FE 02 24 82"))

        create_object = WeaponAnimationCommandDialog(
            raw=bytes.fromhex("F9 0A 12 34"),
            allow_type_change=False,
            operation="insert",
        )
        self.addCleanup(create_object.close)
        self.assertEqual(create_object.object_combo.count(), 0xFF)
        self.assertEqual(create_object.object_combo.currentText(), "0A")
        self.assertEqual(
            [editor.value() for _local, editor, _signed in create_object.parameter_editors],
            [18, 52],
        )
        create_object.object_combo.setCurrentIndex(0x2A)
        self.assertEqual(create_object.command(), bytes.fromhex("F9 2A 12 34"))

        object_rule = WeaponAnimationCommandDialog(
            raw=bytes.fromhex("42 69 01 02 03"),
            allow_type_change=False,
            operation="insert",
        )
        self.addCleanup(object_rule.close)
        self.assertEqual(object_rule.windowTitle(), "运行规律")
        self.assertTrue(object_rule.rule_42.isChecked())
        self.assertEqual(object_rule.rule_variant.currentText(), "规律1")
        self.assertEqual(len(object_rule.parameter_editors), 0)
        self.assertEqual(
            [combo.count() for combo in object_rule.object_rule_combos],
            [0xFC, 0xFC, 0xFC],
        )
        self.assertEqual(
            object_rule.object_rule_combos[0].currentText(),
            "[01]001：静止1E0H帧",
        )
        object_rule.rule_c2.setChecked(True)
        object_rule.rule_variant.setCurrentIndex(1)
        self.assertEqual(object_rule.command(), bytes.fromhex("C2 6A 01 02 03"))

        background = WeaponAnimationCommandDialog(
            raw=bytes.fromhex("F7 70 F8"),
            allow_type_change=False,
        )
        self.addCleanup(background.close)
        self.assertEqual(background.windowTitle(), "设置背景位置")
        self.assertEqual(background.parameter_group.title(), "背景位置设置")
        self.assertEqual(background.parameter_editors[0][1].value(), -8)
        background.parameter_editors[0][1].setValue(-7)
        self.assertEqual(background.command(), bytes.fromhex("F7 70 F9"))

        title_colors = WeaponAnimationCommandDialog(
            raw=bytes.fromhex("F0 05 09 00 1C 0C 0F 00 1C 10 0F 00"),
            allow_type_change=False,
        )
        self.addCleanup(title_colors.close)
        self.assertEqual(len(title_colors.parameter_editors), 9)
        self.assertGreaterEqual(title_colors.height(), 460)

    def test_weapon_ff_insert_is_immediate_truncation_and_matches_reference_golden(self):
        project = RomProject.load(ROM)
        widget = WeaponAnimationWidget()
        self.addCleanup(widget.close)
        widget.set_record(project, 1)
        editor = widget.editors[0]

        class FakePalette:
            def __init__(self, _parent=None):
                pass

            def exec(self) -> int:
                return QDialog.DialogCode.Accepted

            @staticmethod
            def preset() -> bytes:
                return b"\xFF"

            def deleteLater(self) -> None:
                pass

        with patch(
            "dc_modifier.animation_editor.WeaponAnimationCommandPaletteDialog",
            FakePalette,
        ), patch(
            "dc_modifier.animation_editor.WeaponAnimationCommandDialog"
        ) as parameter_dialog:
            editor.insert_instruction(0)
        parameter_dialog.assert_not_called()
        self.assertEqual(bytes.fromhex(editor.code_edit.toPlainText()), b"\xFF")
        original = AnimationCodec(project.working)
        shared_before = original.record("ally", 2).raw
        widget.apply_pending()
        self.assertEqual(
            hashlib.sha256(project.working).hexdigest().upper(),
            "C6D9BBCC148D40BB74D4D8F982FFCB14013D4F8C5CB54CA0AAF77B8BEC45A186",
        )
        changed = AnimationCodec(project.working)
        self.assertEqual(changed.record("ally", 1).raw, b"\xFF")
        self.assertEqual(changed.record("ally", 2).raw, shared_before)
        self.assertNotEqual(
            changed.pointers["ally"][1], changed.pointers["ally"][2]
        )
        project.undo()
        self.assertEqual(bytes(project.working), project.original)
        project.redo()
        self.assertEqual(
            hashlib.sha256(project.working).hexdigest().upper(),
            "C6D9BBCC148D40BB74D4D8F982FFCB14013D4F8C5CB54CA0AAF77B8BEC45A186",
        )

    def test_weapon_context_commands_match_reference_draft_semantics(self):
        widget = WeaponAnimationWidget()
        self.addCleanup(widget.close)
        self.addCleanup(
            setattr, type(widget.editors[0]), "_command_clipboard", tuple()
        )
        widget.set_record(self.project, 1)
        editor = widget.editors[0]
        rows, complete = editor._draft_instructions()
        self.assertTrue(complete)
        original = [row.raw for row in rows]
        body = original[:-1]

        editor.copy_instruction(0)
        self.assertEqual(type(editor)._command_clipboard, (body[0],))
        editor.paste_instructions(1)
        pasted, complete = editor._draft_instructions()
        self.assertTrue(complete)
        self.assertEqual(
            [row.raw for row in pasted],
            [body[0], body[0], *body[3:], b"\xFF"],
        )

        editor.cut_instruction(1)
        cut, complete = editor._draft_instructions()
        self.assertTrue(complete)
        self.assertEqual(
            [row.raw for row in cut],
            [body[0], *body[3:], b"\xFF"],
        )
        self.assertEqual(type(editor)._command_clipboard, (body[0],))

        # Reload the unchanged project before exercising the independent
        # copy-all/paste-all reference path.
        widget.set_record(self.project, 1)
        editor = widget.editors[0]
        editor.copy_all_instructions()
        self.assertEqual(type(editor)._command_clipboard, tuple(body))
        widget.set_record(self.project, 20)
        target = widget.editors[0]
        target.paste_instructions(0, True)
        replaced, complete = target._draft_instructions()
        self.assertTrue(complete)
        self.assertEqual([row.raw for row in replaced], [*body, b"\xFF"])

        widget.set_record(self.project, 1)
        editor = widget.editors[0]
        editor.delete_instruction(0)
        deleted, complete = editor._draft_instructions()
        self.assertTrue(complete)
        self.assertEqual([row.raw for row in deleted], [*body[1:], b"\xFF"])
        editor.clear_instructions()
        cleared, complete = editor._draft_instructions()
        self.assertTrue(complete)
        self.assertEqual([row.raw for row in cleared], [b"\xFF"])

    def test_weapon_destructive_context_saves_match_reference_whole_rom_goldens(self):
        expected = {
            "cut": "335BF292439B0CC9AB2EF89BDC02E0D1A0F5FE82C0A32C90CFA4EC9A9BBD54E9",
            "paste": "8BA8A2AC1160DA965212FA6B6CF779C29E9F78A2DEB3E43D3137F884535E05E8",
            "paste-all": "8783E7CEAF5EEB08C8B78C77F72B628CE83A3AFC357DBD008863757B5FE8F3D1",
            "delete": "335BF292439B0CC9AB2EF89BDC02E0D1A0F5FE82C0A32C90CFA4EC9A9BBD54E9",
            "clear": "D976B33D03F7F2B667BAD619F82D181560381DB11E07D9F235DDC5F4F7DF4D53",
        }
        for operation, golden in expected.items():
            with self.subTest(operation=operation):
                project = RomProject.load(ROM)
                widget = WeaponAnimationWidget()
                self.addCleanup(widget.close)
                widget.set_record(project, 1)
                editor = widget.editors[0]
                type(editor)._command_clipboard = tuple()
                if operation == "cut":
                    editor.cut_instruction(0)
                elif operation == "paste":
                    editor.copy_instruction(0)
                    editor.paste_instructions(1)
                elif operation == "paste-all":
                    editor.copy_all_instructions()
                    widget.set_record(project, 20)
                    widget.editors[0].paste_instructions(0, True)
                elif operation == "delete":
                    editor.delete_instruction(0)
                else:
                    editor.clear_instructions()
                widget.apply_pending()
                self.assertEqual(
                    hashlib.sha256(project.working).hexdigest().upper(),
                    golden,
                )

    def test_enemy_weapon_context_rebuild_matches_shared_and_unique_goldens(self):
        cases = (
            (
                "shared-clear", 1, "clear",
                "B9FBD3F4C1D6A1684422D62C2100E0091890F8AC77C1264CF9C22881A6EDD1A9",
            ),
            (
                "unique-delete", 29, "delete",
                "3A50C96CA4B648525A94E157FAA581947AE5900BA26A22A171CC24E00386B1C1",
            ),
        )
        for label, weapon_id, operation, golden in cases:
            with self.subTest(case=label):
                project = RomProject.load(ROM)
                widget = WeaponAnimationWidget()
                self.addCleanup(widget.close)
                widget.set_record(project, weapon_id)
                editor = widget.editors[1]
                if operation == "clear":
                    editor.clear_instructions()
                else:
                    editor.delete_instruction(0)
                widget.apply_pending()
                self.assertEqual(
                    hashlib.sha256(project.working).hexdigest().upper(),
                    golden,
                )

    def test_weapon_loop_targets_follow_current_draft_instruction_numbers(self):
        widget = WeaponAnimationWidget()
        self.addCleanup(widget.close)
        widget.set_record(self.project, 1)
        editor = widget.editors[0]
        rows, complete = editor._draft_instructions()
        self.assertTrue(complete)
        targets = editor._weapon_loop_targets()
        self.assertEqual(len(targets), len(rows))
        pointer = editor.codec.pointers[editor.record.kind][editor.record.index]
        self.assertEqual(targets[0][1], pointer)
        self.assertEqual(
            targets[1][1],
            pointer + rows[1].offset - editor.record.offset,
        )
        self.assertTrue(targets[0][0].startswith("000："))
        self.assertTrue(targets[1][0].startswith("001："))

    def test_weapon_animation_right_click_edit_changes_only_verified_parameter_draft(self):
        widget = WeaponAnimationWidget()
        widget.set_record(self.project, 1)
        editor = widget.editors[0]
        row = next(
            index
            for index, instruction in enumerate(editor.record.instructions)
            if instruction.editable
        )
        instruction = editor.record.instructions[row]
        before_rom = bytes(self.project.working)
        before_draft = bytes.fromhex(editor.code_edit.toPlainText())
        current = []
        expected = set()
        for local, low, high in instruction.editable:
            index = instruction.offset - editor.record.offset + local
            value = before_draft[index]
            replacement = low if value != low else high
            current.append(replacement)
            if value != replacement:
                expected.add(index)
        editor._apply_instruction_values(row, tuple(current))
        after_draft = bytes.fromhex(editor.code_edit.toPlainText())
        changed = {
            index for index, (left, right) in enumerate(zip(before_draft, after_draft))
            if left != right
        }
        self.assertEqual(changed, expected)
        self.assertTrue(widget.has_pending_changes())
        self.assertEqual(bytes(self.project.working), before_rom)
        widget.close()
