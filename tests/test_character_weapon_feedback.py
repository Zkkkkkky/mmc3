from __future__ import annotations

from dataclasses import replace
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from PySide6.QtCore import Qt
from PySide6.QtGui import QImage, QColor
from PySide6.QtWidgets import QApplication, QMessageBox

from dc_modifier.app import DEFAULT_ROM
from dc_modifier.legacy_windows import DatabaseDialog
from fc_editor.dc_text import concise_dc_text
from fc_editor.codecs.character_attributes import (
    CharacterAttributesCodec, apply_verified_patches,
    weapon_extra_patches, weapon_extra_values,
)
from fc_editor.codecs.character_dialogue import TransformDialogueBinding
from fc_rom_editor_core import RomProject
from tests.qt_test_case import QtTestCase


class CharacterCodecFeedbackTests(unittest.TestCase):
    def setUp(self) -> None:
        self.project = RomProject.load(DEFAULT_ROM)
        self.codec = CharacterAttributesCodec(self.project)

    def test_range_and_skill_changes_survive_project_replay_together(self) -> None:
        self.project.set_weapon_value(1, "max_range", 2)
        apply_verified_patches(self.project, weapon_extra_patches(self.project, 1, 11, 2), "武器组合编辑")
        self.assertEqual(self.project.weapon_record_bytes(1)[:3], bytes.fromhex("B1 6E 02"))
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "weapon.dcmod"
            self.project.save_project(path)
            reopened = RomProject.load_project(path, DEFAULT_ROM)
        self.assertEqual(bytes(reopened.working), bytes(self.project.working))
        self.assertEqual(reopened.get_weapon_value(1, "max_range"), 2)
        self.assertEqual(weapon_extra_values(reopened, 1), (11, 2))

    def test_all_character_and_portrait_records_round_trip_including_reserved_last_id(self) -> None:
        for record_id in range(1, 201):
            self.assertEqual(self.codec.patches(record_id, self.codec.read(record_id)), ())
            self.assertEqual(self.codec.portrait_patches(record_id, self.codec.read_portrait(record_id)), ())
        self.assertEqual(self.codec.read(4).spirit, 33)
        self.assertEqual(self.codec.read(4).growth, 201)
        self.assertEqual(self.codec.read_portrait(4).colors, (55, 40, 23))
        self.assertEqual(self.codec.costs(), (10, 50, 10, 20, 40, 30, 80, 160, 50, 60, 80, 80, 150, 80, 130, 150, 180, 150, 150, 90, 100, 10, 60, 40))

    def test_independent_fixed_size_edit_touches_only_one_record(self) -> None:
        before = bytes(self.project.working)
        old = self.codec.read(4)
        patches = self.codec.patches(4, replace(old, spirit=44, spirit_mask=0x010203))
        apply_verified_patches(self.project, patches, "人物编辑")
        self.assertEqual(self.codec.read(4).spirit_mask, 0x010203)
        changed = {index for index, (a, b) in enumerate(zip(before, self.project.working)) if a != b}
        self.assertTrue(changed <= set(range(0x48598, 0x4859E)))
        self.project.undo()
        self.assertEqual(bytes(self.project.working), before)
        self.project.redo()
        self.assertEqual(self.codec.read(4).spirit, 44)

    def test_shared_edit_is_explicit_and_capacity_failure_does_not_mutate(self) -> None:
        before = bytes(self.project.working)
        record = replace(self.codec.read(1), spirit=1)
        with self.assertRaisesRegex(ValueError, "容量不足"):
            self.codec.patches(1, record)
        self.assertEqual(bytes(self.project.working), before)
        aliases = self.codec.shared_ids(1)
        apply_verified_patches(self.project, self.codec.patches(1, record, shared=True), "共享属性")
        for index in aliases:
            self.assertEqual(self.codec.read(index).spirit, 1)
        self.assertEqual(self.codec.read(4).spirit, 33)

    def test_copy_reuses_existing_record_and_preserves_other_ids(self) -> None:
        before = {index: self.codec.read(index) for index in range(1, 201)}
        apply_verified_patches(self.project, self.codec.patches(4, before[5]), "复制人物")
        for index in range(1, 201):
            self.assertEqual(self.codec.read(index), before[5] if index == 4 else before[index])

    def test_correction_growth_repacking_keeps_every_other_record(self) -> None:
        before = {index: self.codec.read(index) for index in range(1, 201)}
        shorter = replace(before[75], corrections=(0, 0, 0, 0, 0))
        apply_verified_patches(self.project, self.codec.patches(75, shorter), "减少补正")
        changed = replace(self.codec.read(4), corrections=(1, 2, 3, 4, 5))
        apply_verified_patches(self.project, self.codec.patches(4, changed), "增加补正")
        for index in range(1, 201):
            self.assertEqual(self.codec.read(index), changed if index == 4 else shorter if index == 75 else before[index])

    def test_invalid_inputs_and_changed_signatures_are_rejected(self) -> None:
        original = self.codec.read(4)
        for replacement in (replace(original, spirit=-1), replace(original, growth=251),
                            replace(original, spirit_mask=0x1000000), replace(original, corrections=(0, 0, 0, 0, 256))):
            with self.assertRaises(ValueError):
                self.codec.patches(4, replacement)
        for record_id in (0, 201, -1):
            with self.assertRaises(ValueError):
                self.codec.read(record_id)
        self.project.working[0x48030] ^= 1
        with self.assertRaisesRegex(ValueError, "加载代码"):
            self.codec.patches(4, original)

    def test_weapon_extras_preserve_range_and_reserved_distance_high_nibble(self) -> None:
        offset = self.project.weapon_codec.record_offset(1)
        self.project.working[offset] = 0x07
        self.project.working[offset + 2] = 0xA0
        patches = weapon_extra_patches(self.project, 1, 15, 3)
        apply_verified_patches(self.project, patches, "武器")
        self.assertEqual(self.project.working[offset], 0xF7)
        self.assertEqual(self.project.working[offset + 2], 0xA3)
        self.assertEqual(weapon_extra_values(self.project, 1), (15, 3))
        for skill, distance in ((16, 0), (0, 4), (-1, 0), (0, -1)):
            with self.assertRaises(ValueError):
                weapon_extra_patches(self.project, 1, skill, distance)

    def test_project_save_reload_replays_all_new_patch_types(self) -> None:
        before = bytes(self.project.working)
        with self.project.transaction("人物与武器"):
            apply_verified_patches(self.project, self.codec.patches(4, replace(self.codec.read(4), spirit=42)), "人物")
            costs = list(self.codec.costs())
            costs[0] = 11
            apply_verified_patches(self.project, (self.codec.cost_patch(tuple(costs)),), "精神")
            apply_verified_patches(self.project, weapon_extra_patches(self.project, 1, 1, 2), "武器")
        with tempfile.TemporaryDirectory() as folder:
            path = self.project.save_project(Path(folder) / "feedback.dcproj")
            reloaded = RomProject.load_project(path, DEFAULT_ROM)
        self.assertEqual(bytes(reloaded.working), bytes(self.project.working))
        self.project.undo()
        self.assertEqual(bytes(self.project.working), before)

    def test_character_display_and_battle_names_repack_independently(self) -> None:
        codec = self.project.character_name_codec
        self.assertIsNotNone(codec)
        assert codec is not None
        before = bytes(self.project.working)
        normal_before = {
            record_id: codec._terminated_record(
                codec.normal_pointer(record_id, self.project.working),
                self.project.working,
            )
            for record_id in range(1, 0xC9)
        }
        battle_before = {
            record_id: codec._terminated_record(
                codec.pointer(record_id, self.project.working),
                self.project.working,
            )
            for record_id in range(1, 0xC8)
        }
        replacement = concise_dc_text(normal_before[2])
        self.project.set_character_normal_name_text(4, replacement)
        self.assertEqual(
            codec._terminated_record(
                codec.normal_pointer(4, self.project.working),
                self.project.working,
            ),
            normal_before[2],
        )
        for record_id, raw in normal_before.items():
            if record_id != 4:
                self.assertEqual(
                    codec._terminated_record(
                        codec.normal_pointer(record_id, self.project.working),
                        self.project.working,
                    ),
                    raw,
                )
        for record_id, raw in battle_before.items():
            self.assertEqual(
                codec._terminated_record(
                    codec.pointer(record_id, self.project.working),
                    self.project.working,
                ),
                raw,
            )
        changed = {
            index
            for index, (old, new) in enumerate(zip(before, self.project.working))
            if old != new
        }
        allowed = set(range(0x4945B, 0x49906))
        self.assertTrue(changed)
        self.assertTrue(changed <= allowed)
        with tempfile.TemporaryDirectory() as folder:
            path = self.project.save_project(Path(folder) / "character-name.dcproj")
            reopened = RomProject.load_project(path, DEFAULT_ROM)
        self.assertEqual(bytes(reopened.working), bytes(self.project.working))
        self.project.undo()
        self.assertEqual(bytes(self.project.working), before)

    def test_character_name_pool_overflow_is_atomic(self) -> None:
        before = bytes(self.project.working)
        with self.assertRaisesRegex(ValueError, "容量不足"):
            self.project.set_character_normal_name_text(1, "<01>")
        self.assertEqual(bytes(self.project.working), before)

    def test_weapon_ff_is_a_real_editable_record(self) -> None:
        self.assertEqual(self.project.weapon_count, 0x100)
        self.assertEqual(len(self.project.weapon_record_bytes(0xFF)), 6)
        self.assertTrue(self.project.weapon_name_record_bytes(0xFF))
        old_hit = self.project.get_weapon_value(0xFF, "hit")
        self.project.set_weapon_value(0xFF, "hit", (old_hit + 1) & 0xFF)
        self.assertEqual(
            self.project.get_weapon_value(0xFF, "hit"),
            (old_hit + 1) & 0xFF,
        )
        self.project.undo()
        self.assertEqual(self.project.get_weapon_value(0xFF, "hit"), old_hit)

    def test_all_character_dialogue_records_round_trip_and_direct_edit_is_exact(self) -> None:
        codec = self.project.character_dialogue_codec
        self.assertIsNotNone(codec)
        assert codec is not None
        for character_id in range(1, 0xC9):
            self.assertEqual(
                codec.read(character_id, self.project.working).encode(),
                codec.raw_record(character_id, self.project.working),
            )
        character_id = 3
        record = codec.read(character_id, self.project.working)
        direct = list(record.direct)
        direct[0] = replace(
            direct[0], dialogue=(direct[0].dialogue + 1) & 0xFF
        )
        changed = replace(record, direct=tuple(direct))
        patch = codec.patch(self.project.working, character_id, changed)
        self.assertIsNotNone(patch)
        assert patch is not None
        offset, before, after = patch
        self.assertEqual(offset, codec.pointer_to_file_offset(codec.pointer(character_id)))
        self.assertEqual(
            [index for index, pair in enumerate(zip(before, after)) if pair[0] != pair[1]],
            [1],
        )
        aliases = codec.shared_ids(character_id, self.project.working)
        apply_verified_patches(self.project, (patch,), "人物台词")
        self.assertTrue(all(codec.read(item, self.project.working) == changed for item in aliases))
        with tempfile.TemporaryDirectory() as folder:
            path = self.project.save_project(Path(folder) / "character-dialogue.dcproj")
            reopened = RomProject.load_project(path, DEFAULT_ROM)
        self.assertEqual(bytes(reopened.working), bytes(self.project.working))
        self.project.undo()
        self.assertEqual(codec.read(character_id, self.project.working), record)

    def test_transform_dialogue_table_has_fixed_capacity_and_repackages_locally(self) -> None:
        codec = self.project.character_dialogue_codec
        assert codec is not None
        self.assertEqual(
            [len(codec.character_transform_bindings(item, self.project.working)) for item in range(1, 11)],
            [0, 0, 0, 0, 0, 4, 0, 1, 1, 4],
        )
        with self.assertRaisesRegex(ValueError, "最多容纳"):
            codec.transform_patch(
                self.project.working,
                1,
                (TransformDialogueBinding(1, 0, 0xFF, 0),),
            )
        before = bytes(self.project.working)
        retained = codec.character_transform_bindings(6, self.project.working)[:1]
        patch = codec.transform_patch(self.project.working, 6, retained)
        self.assertIsNotNone(patch)
        assert patch is not None
        self.assertEqual(patch[0], 0x1596D)
        self.assertEqual(len(patch[1]), 0x40)
        apply_verified_patches(self.project, (patch,), "变形台词")
        self.assertEqual(
            codec.character_transform_bindings(6, self.project.working), retained
        )
        changed_offsets = {
            index for index, pair in enumerate(zip(before, self.project.working))
            if pair[0] != pair[1]
        }
        self.assertTrue(changed_offsets <= set(range(0x1596D, 0x159AD)))
        with tempfile.TemporaryDirectory() as folder:
            path = self.project.save_project(Path(folder) / "transform-dialogue.dcproj")
            reopened = RomProject.load_project(path, DEFAULT_ROM)
        self.assertEqual(bytes(reopened.working), bytes(self.project.working))
        self.project.undo()
        self.assertEqual(bytes(self.project.working), before)


class CharacterWeaponUiFeedbackTests(QtTestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self) -> None:
        self.project = RomProject.load(DEFAULT_ROM)
        self.before = bytes(self.project.working)
        self.dialog = DatabaseDialog(self.project)
        self.dialog.show()
        self.app.processEvents()
        self.page = self.dialog.character_page
        self.page.records.setCurrentRow(3)
        self.widget = self.page.character_details

    def tearDown(self) -> None:
        self.dialog.reject()
        self.dialog.deleteLater()
        self.app.processEvents()

    def test_switch_stages_spirit_cost_and_portrait_and_outer_cancel_restores(self) -> None:
        self.widget.fields["spirit"].setValue(45)
        self.widget.costs[0].setValue(12)
        self.widget.portrait_fields["color0"].setValue(32)
        self.assertTrue(self.page.has_pending_draft)
        self.page.records.setCurrentRow(4)
        codec = CharacterAttributesCodec(self.project)
        self.assertEqual(codec.read(4).spirit, 45)
        self.assertEqual(codec.costs()[0], 12)
        self.assertEqual(codec.read_portrait(4).colors[0], 32)
        self.dialog.reject()
        self.assertEqual(bytes(self.project.working), self.before)

    def test_capacity_error_preserves_form_and_all_other_pending_changes(self) -> None:
        self.page.records.setCurrentRow(0)
        self.widget.fields["spirit"].setValue(1)
        self.widget.costs[0].setValue(12)
        with patch.object(self.page, "show_error") as error:
            self.page.apply_record()
        self.assertIn("容量不足", str(error.call_args.args[0]))
        self.assertTrue(self.page.has_pending_draft)
        self.assertEqual(bytes(self.project.working), self.before)
        self.widget.shared_attributes.setChecked(True)
        with patch(
            "dc_modifier.database_records.QMessageBox.question",
            return_value=QMessageBox.StandardButton.Yes,
        ):
            self.page.apply_record()
        self.assertEqual(CharacterAttributesCodec(self.project).read(1).spirit, 1)

    def test_shared_character_edit_lists_affected_ids_and_defaults_to_cancel(self) -> None:
        self.page.records.setCurrentRow(0)
        codec = CharacterAttributesCodec(self.project)
        aliases = codec.shared_ids(1)
        self.assertGreater(len(aliases), 1)
        self.widget.shared_attributes.setChecked(True)
        self.widget.fields["spirit"].setValue(1)
        with patch(
            "dc_modifier.database_records.QMessageBox.question",
            return_value=QMessageBox.StandardButton.Cancel,
        ) as prompt:
            self.page.apply_record()
        prompt.assert_called_once()
        message = prompt.call_args.args[2]
        self.assertIn("人物属性记录", message)
        self.assertIn(f"{aliases[0]:02X}", message)
        self.assertEqual(bytes(self.project.working), self.before)
        self.assertTrue(self.page.has_pending_draft)

    def test_shared_portrait_edit_lists_affected_ids_and_defaults_to_cancel(self) -> None:
        codec = CharacterAttributesCodec(self.project)
        character_id = next(
            candidate
            for candidate in range(1, codec.COUNT)
            if len(codec.shared_ids(candidate, portrait=True)) > 1
        )
        self.page.select_record_id(character_id)
        aliases = codec.shared_ids(character_id, portrait=True)
        self.widget.shared_portrait.setChecked(True)
        color = self.widget.portrait_fields["color0"]
        color.setValue((color.value() + 1) & 0x3F)
        with patch(
            "dc_modifier.database_records.QMessageBox.question",
            return_value=QMessageBox.StandardButton.Cancel,
        ) as prompt:
            self.page.apply_record()
        prompt.assert_called_once()
        self.assertIn("头像记录", prompt.call_args.args[2])
        self.assertIn(f"{aliases[0]:02X}", prompt.call_args.args[2])
        self.assertEqual(bytes(self.project.working), self.before)
        self.assertTrue(self.page.has_pending_draft)

    def test_shared_dialogue_edit_lists_ids_and_defaults_to_cancel(self) -> None:
        codec = self.project.character_dialogue_codec
        assert codec is not None
        character_id = next(
            item for item in range(1, 0xC9)
            if len(codec.shared_ids(item, self.project.working)) > 1
        )
        self.page.select_record_id(character_id)
        dialogue = self.page.character_dialogue
        spin = dialogue.direct_controls[0][1]
        spin.setValue((spin.value() + 1) & 0xFF)
        with patch(
            "dc_modifier.database_records.QMessageBox.question",
            return_value=QMessageBox.StandardButton.Cancel,
        ) as prompt:
            self.page.apply_record()
        prompt.assert_called_once()
        self.assertIn("人物战斗台词记录", prompt.call_args.args[2])
        self.assertEqual(bytes(self.project.working), self.before)
        self.assertTrue(self.page.has_pending_draft)

    def test_shared_dialogue_reset_also_requires_confirmation(self) -> None:
        codec = self.project.character_dialogue_codec
        assert codec is not None
        character_id = next(
            item for item in range(1, 0xC9)
            if len(codec.shared_ids(item, self.project.working)) > 1
        )
        record = codec.read(character_id, self.project.working)
        direct = list(record.direct)
        direct[0] = replace(
            direct[0], dialogue=(direct[0].dialogue + 1) & 0xFF
        )
        dialogue_patch = codec.patch(
            self.project.working,
            character_id,
            replace(record, direct=tuple(direct)),
        )
        assert dialogue_patch is not None
        apply_verified_patches(self.project, (dialogue_patch,), "共享人物台词")
        modified = bytes(self.project.working)
        self.page.select_record_id(character_id)
        with patch(
            "dc_modifier.database_records.QMessageBox.question",
            return_value=QMessageBox.StandardButton.Cancel,
        ) as prompt:
            self.page.reset_record()
        prompt.assert_called_once()
        self.assertIn("人物战斗台词记录", prompt.call_args.args[2])
        self.assertEqual(bytes(self.project.working), modified)
        with patch(
            "dc_modifier.database_records.QMessageBox.question",
            return_value=QMessageBox.StandardButton.Yes,
        ):
            self.page.reset_record()
        self.assertEqual(
            codec.read(character_id, self.project.working),
            codec.read(character_id, self.project.original),
        )

    def test_transform_dialogue_clear_is_one_transaction(self) -> None:
        self.page.select_record_id(6)
        dialogue = self.page.character_dialogue
        self.assertEqual(dialogue.transform_table.rowCount(), 4)
        dialogue.transform_table.setCurrentCell(0, 0)
        dialogue._remove_transform()
        self.page.apply_record()
        codec = self.project.character_dialogue_codec
        assert codec is not None
        self.assertEqual(
            len(codec.character_transform_bindings(6, self.project.working)), 3
        )
        self.project.undo()
        self.assertEqual(bytes(self.project.working), self.before)

    def test_upload_stays_a_draft_and_cancel_restores_chr(self) -> None:
        image = QImage(32, 32, QImage.Format.Format_RGB32)
        image.fill(QColor("white"))
        self.widget.import_portrait_image("front", image)
        self.assertEqual(bytes(self.project.working), self.before)
        self.assertTrue(self.page.has_pending_draft)
        self.assertIn("将影响", self.widget.status.text())
        with patch(
            "dc_modifier.database_records.QMessageBox.question",
            return_value=QMessageBox.StandardButton.Yes,
        ):
            self.page.apply_record()
        self.assertNotEqual(bytes(self.project.working), self.before)
        self.dialog.reject()
        self.assertEqual(bytes(self.project.working), self.before)

    def test_invalid_upload_does_not_change_draft_or_rom(self) -> None:
        with self.assertRaisesRegex(ValueError, "32×32"):
            self.widget.import_portrait_image("front", QImage(16, 16, QImage.Format.Format_RGB32))
        self.assertFalse(self.page.has_pending_draft)
        self.assertEqual(bytes(self.project.working), self.before)

    def test_weapon_fields_and_animation_are_one_undo_group(self) -> None:
        self.dialog._select_weapon(1)
        page = self.dialog.weapon_page
        page.fields["hit"].setValue(111)
        page.weapon_skill.setCurrentIndex(11)
        page.distance_correction.setValue(2)
        editor = page.weapon_animation.editors[0]
        raw = bytearray(editor.record.raw)
        # The first known instruction is music command 0x0E; change its argument.
        instruction = next(item for item in editor.record.instructions if item.editable)
        local, minimum, maximum = instruction.editable[0]
        byte_index = instruction.offset - editor.record.offset + local
        raw[byte_index] = minimum if raw[byte_index] != minimum else maximum
        editor.code_edit.setPlainText(raw.hex(" "))
        self.assertTrue(page.has_pending_draft)
        with patch(
            "dc_modifier.database_records.QMessageBox.question",
            return_value=QMessageBox.StandardButton.Yes,
        ):
            page.apply_record()
        self.assertFalse(page.has_pending_draft)
        self.assertEqual(weapon_extra_values(self.project, 1), (11, 2))
        self.project.undo()
        self.assertEqual(bytes(self.project.working), self.before)

    def test_invalid_animation_prevents_other_weapon_fields_from_mutating(self) -> None:
        self.dialog._select_weapon(1)
        page = self.dialog.weapon_page
        page.fields["hit"].setValue(111)
        page.weapon_animation.editors[0].code_edit.setPlainText("ZZ")
        with patch.object(page, "show_error") as error:
            page.apply_record()
        self.assertTrue(error.called)
        self.assertTrue(page.has_pending_draft)
        self.assertEqual(bytes(self.project.working), self.before)

    def test_shared_animation_edit_lists_aliases_and_defaults_to_cancel(self) -> None:
        self.dialog._select_weapon(1)
        page = self.dialog.weapon_page
        editor = page.weapon_animation.editors[0]
        self.assertTrue(editor.record.aliases)
        instruction = next(item for item in editor.record.instructions if item.editable)
        local, minimum, maximum = instruction.editable[0]
        byte_index = instruction.offset - editor.record.offset + local
        raw = bytearray(editor.record.raw)
        raw[byte_index] = minimum if raw[byte_index] != minimum else maximum
        editor.code_edit.setPlainText(raw.hex(" "))
        with patch(
            "dc_modifier.database_records.QMessageBox.question",
            return_value=QMessageBox.StandardButton.Cancel,
        ) as prompt:
            page.apply_record()
        prompt.assert_called_once()
        self.assertIn("动画", prompt.call_args.args[2])
        self.assertEqual(bytes(self.project.working), self.before)
        self.assertTrue(page.has_pending_draft)

    def test_shared_weapon_record_edit_lists_ids_and_cancel_preserves_rom(self) -> None:
        page = self.dialog.weapon_page
        weapon_id = next(
            weapon_id
            for weapon_id in range(1, self.project.weapon_count)
            if len(page.shared_weapon_record_ids(weapon_id)) > 1
        )
        self.dialog._select_weapon(weapon_id)
        affected = page.shared_weapon_record_ids(weapon_id)
        old_value = self.project.get_weapon_value(weapon_id, "hit")
        page.fields["hit"].setValue((old_value + 1) & 0xFF)
        with patch(
            "dc_modifier.database_records.QMessageBox.question",
            return_value=QMessageBox.StandardButton.Cancel,
        ) as prompt:
            page.apply_record()
        prompt.assert_called_once()
        message = prompt.call_args.args[2]
        self.assertIn("命中", message)
        self.assertIn(f"{affected[0]:02X}", message)
        self.assertEqual(bytes(self.project.working), self.before)
        self.assertTrue(page.has_pending_draft)

        with patch(
            "dc_modifier.database_records.QMessageBox.question",
            return_value=QMessageBox.StandardButton.Yes,
        ):
            page.apply_record()
        self.assertTrue(all(
            self.project.get_weapon_value(shared_id, "hit")
            == ((old_value + 1) & 0xFF)
            for shared_id in affected
        ))

    def test_lists_expose_reserved_character_c8_and_weapon_ff(self) -> None:
        character_ids = [
            self.page.records.item(row).data(Qt.ItemDataRole.UserRole)
            for row in range(self.page.records.count())
        ]
        self.assertEqual(character_ids[-1], 0xC8)
        self.assertEqual(len(character_ids), 0xC8)

        page = self.dialog.weapon_page
        weapon_ids = [
            page.records.item(row).data(Qt.ItemDataRole.UserRole)
            for row in range(page.records.count())
        ]
        self.assertEqual(weapon_ids[-1], 0xFF)
        self.assertEqual(len(weapon_ids), 0xFF)

    def test_weapon_rules_button_opens_the_shared_rules_tab(self) -> None:
        page = self.dialog.weapon_page

        class FakeTabs:
            current = None

            def setCurrentIndex(self, value):
                self.current = value

        class FakeDialog:
            instance = None

            def __init__(self, *args, **kwargs):
                type(self).instance = self
                self.tabs = FakeTabs()
                self.title = ""
                self.deleted = False

            def setWindowTitle(self, title):
                self.title = title

            def exec(self):
                return 0

            def deleteLater(self):
                self.deleted = True

        with patch("dc_modifier.legacy_tools.MapAnimationDialog", FakeDialog):
            page.animation_rules_button.click()
        fake = FakeDialog.instance
        self.assertIsNotNone(fake)
        self.assertEqual(fake.title, "规律")
        self.assertEqual(fake.tabs.current, 1)
        self.assertTrue(fake.deleted)

    def test_weapon_animation_test_exports_current_rom_and_starts_mesen(self) -> None:
        page = self.dialog.weapon_page
        self.dialog._select_weapon(1)
        with patch.object(self.project, "save_as") as save_as, patch(
            "dc_modifier.database_records.QProcess.startDetached",
            return_value=(True, 123),
        ) as start:
            page.animation_test_button.click()
        save_as.assert_called_once()
        self.assertEqual(save_as.call_args.kwargs, {"make_backup": False})
        destination = save_as.call_args.args[0]
        self.assertEqual(destination.name, "weapon-animation-01.nes")
        start.assert_called_once()
        self.assertEqual(start.call_args.args[1], [str(destination)])
