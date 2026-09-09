from __future__ import annotations

import os
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

from dc_modifier.app import MainWindow
from dc_modifier.event_page import EventPage
from dc_modifier.map_page import MapPage
from dc_modifier.persuasion_page import PersuasionPage
from dc_modifier.pages import (
    CharacterPage,
    ChangesPage,
    MusicPage,
    UnitPage,
    WeaponPage,
    parse_id_expression,
)
from dc_modifier.story_page import StoryPage
from dc_modifier.unit_import_page import UnitImportPage
from fc_editor.text_table import TextTable


class DesktopEditorSmokeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.application = QApplication.instance() or QApplication([])

    def setUp(self) -> None:
        self.window = MainWindow(open_default=True)
        self.assertIsNotNone(self.window.project)

    def tearDown(self) -> None:
        if self.window.project is not None:
            self.window._saved_snapshot = bytes(self.window.project.working)
        self.window.close()

    def test_navigation_and_default_project(self) -> None:
        assert self.window.project is not None
        self.assertEqual(self.window.navigation.count(), 12)
        self.assertEqual(self.window.workspace.count(), 5)
        self.assertEqual(self.window.project.profile.key, "dc-kuorong-mmc3-v1")
        self.assertEqual(self.window.project.expansion_capacity, 200 * 1024)
        self.window.show_page("weapons")
        self.assertEqual(self.window.workspace.currentIndex(), 1)
        database_tabs = self.window.workspace.currentWidget()
        self.assertEqual(database_tabs.currentIndex(), 2)
        self.assertEqual(self.window.module_status.text(), "武器")

    def test_id_expression_supports_hex_ranges_and_rejects_invalid_ids(self) -> None:
        self.assertEqual(
            parse_id_expression("$00-$02, 0x10，17", 0x20),
            [0, 1, 2, 16, 17],
        )
        with self.assertRaisesRegex(ValueError, "超出范围"):
            parse_id_expression("$21", 0x20)

    def test_unit_import_page_builds_package_and_previews_shared_ids(self) -> None:
        page = self.window.pages[self.window.page_index["unit_import"]]
        self.assertIsInstance(page, UnitImportPage)
        assert isinstance(page, UnitImportPage)
        page.source_unit.setCurrentIndex(page.source_unit.findData(1))
        page.target_unit.setCurrentIndex(page.target_unit.findData(1))
        page.include_chr.setChecked(True)
        page.chr_first_tile.setValue(0x20)
        page.chr_tile_count.setValue(2)
        page.use_selected_unit()
        self.assertIsNotNone(page.loaded_package)
        assert page.loaded_package is not None
        self.assertEqual(len(page.loaded_package.assets), 1)
        self.assertIn("$01", page.package_summary.text())
        self.assertIn("CHR $0020", page.package_summary.text())
        self.assertIn("$05", page.impact.text())
        self.assertIn("$48", page.impact.text())

    def test_chr_canvas_edit_and_undo(self) -> None:
        assert self.window.project is not None
        page = self.window.pages[self.window.page_index["unit_import"]]
        assert isinstance(page, UnitImportPage)
        graphics = page.graphics
        tile_index = next(
            index
            for index in range(self.window.project.chr_tile_count)
            if len(set(self.window.project.chr_tile_pixels(index))) > 1
        )
        graphics.tile_index.setValue(tile_index)
        self.assertEqual(graphics.sheet.selected_tile, tile_index)
        self.assertEqual(graphics.sheet_page.value(), tile_index // 256)
        original = self.window.project.chr_tile_pixels(tile_index)
        staged = list(original)
        staged[0] = (staged[0] + 1) % 4
        graphics.canvas.set_pixels(staged)
        graphics.apply_tile()
        self.assertEqual(self.window.project.chr_tile_pixels(tile_index), tuple(staged))
        self.window.undo()
        self.assertEqual(self.window.project.chr_tile_pixels(tile_index), original)

    def test_unit_page_edit_and_window_undo(self) -> None:
        assert self.window.project is not None
        page = self.window.pages[self.window.page_index["units"]]
        self.assertIsInstance(page, UnitPage)
        assert isinstance(page, UnitPage)
        self.assertLess(page.name_reference.count(), 255)
        self.assertTrue(
            all(
                "原生名称" not in page.name_reference.itemText(index)
                for index in range(page.name_reference.count())
            )
        )
        self.assertEqual(page.record_text(0x79), "$79  里克·大魔")
        self.assertIn("光束军刀", page.weapon_slots[0].itemText(page.weapon_slots[0].findData(1)))
        page.records.setCurrentRow(0)
        unit_id = int(page.records.currentItem().data(256))
        old_value = self.window.project.get_value(unit_id, "movement")
        new_value = (old_value + 1) & 0xFF
        page.fields["movement"].setValue(new_value)
        page.apply_record()
        self.assertEqual(self.window.project.get_value(unit_id, "movement"), new_value)
        self.window.undo()
        self.assertEqual(self.window.project.get_value(unit_id, "movement"), old_value)

    def test_music_binding_and_validation_page(self) -> None:
        assert self.window.project is not None
        page = self.window.pages[self.window.page_index["music"]]
        self.assertIsInstance(page, MusicPage)
        assert isinstance(page, MusicPage)
        page.records.setCurrentRow(0x04)
        page.attacker.setCurrentIndex(page.attacker.findData(0x9E))
        page.defender.setCurrentIndex(page.defender.findData(0x9E))
        self.assertTrue(page.apply_button.isEnabled())
        self.assertIn("尚未应用", page.pending_state.text())
        page.apply_record()
        binding = self.window.project.get_battle_music_binding(0x04)
        self.assertEqual((binding.attacker_command, binding.defender_command), (0x9E, 0x9E))
        self.assertEqual(page.music_slot.count(), 3)
        self.assertEqual(page.music_slot.itemData(0), 0x9D)
        self.assertIn("8192 字节", page.music_slot_status.text())
        self.assertIn("查理", page.record_text(0x02))
        self.assertIn("睿智之神", page.record_text(0x13))

        self.window.validate_project()
        validation_page = self.window.pages[self.window.page_index["changes"]]
        self.assertIsInstance(validation_page, ChangesPage)
        assert isinstance(validation_page, ChangesPage)
        self.assertGreater(validation_page.validation.rowCount(), 0)

    def test_character_page_edits_name_and_music_together(self) -> None:
        assert self.window.project is not None
        page = self.window.pages[self.window.page_index["characters"]]
        self.assertIsInstance(page, CharacterPage)
        assert isinstance(page, CharacterPage)
        page.records.setCurrentRow(0x12)
        self.assertEqual(page.current_id, 0x13)
        self.assertIn("拉坎", page.record_heading.text())
        page.name_reference.setCurrentIndex(page.name_reference.findData(0x02))
        page.ally_music.setCurrentIndex(page.ally_music.findData(0x9E))
        page.enemy_music.setCurrentIndex(page.enemy_music.findData(0x9F))
        self.assertTrue(page.apply_button.isEnabled())
        page.apply_record()
        self.assertEqual(self.window.project.character_display_name(0x13), "查理")
        binding = self.window.project.get_battle_music_binding(0x13)
        self.assertEqual(
            (binding.attacker_command, binding.defender_command),
            (0x9E, 0x9F),
        )
        self.window.undo()
        self.assertEqual(self.window.project.character_display_name(0x13), "拉坎")

    def test_map_page_applies_a_capacity_safe_tile_change(self) -> None:
        assert self.window.project is not None
        page = self.window.pages[self.window.page_index["maps"]]
        self.assertIsInstance(page, MapPage)
        assert isinstance(page, MapPage)
        record = self.window.project.get_map(0)
        self.assertEqual(page.tileset.currentData(), "D")
        self.assertEqual(len(page.canvas.tile_images), 16)
        self.assertFalse(page.canvas.tile_images[1].isNull())
        candidate_tiles = list(record.tiles)
        changed_index = None
        for index in range(1, len(candidate_tiles)):
            if candidate_tiles[index] == candidate_tiles[index - 1]:
                continue
            previous = candidate_tiles[index]
            candidate_tiles[index] = candidate_tiles[index - 1]
            encoded = self.window.project.map_codec.encode(
                record.width,
                record.height,
                tuple(candidate_tiles),
            )
            if len(encoded) <= record.capacity:
                changed_index = index
                break
            candidate_tiles[index] = previous
        self.assertIsNotNone(changed_index)
        page.staged_tiles[:] = candidate_tiles
        page.canvas.tiles = page.staged_tiles
        page.apply_changes()
        changed = self.window.project.get_map(0)
        self.assertEqual(changed.tiles[changed_index], candidate_tiles[changed_index])
        self.window.undo()
        self.assertEqual(self.window.project.get_map(0).tiles, record.tiles)

    def test_map_page_edits_coordinate_event_and_shop(self) -> None:
        assert self.window.project is not None
        page = self.window.pages[self.window.page_index["maps"]]
        assert isinstance(page, MapPage)
        self.assertEqual(self.window.project.get_map_triggers(0), ())
        page.trigger_table.set_rows([(3, 4, 0xFF, 0xF2)])
        self.assertTrue(page.apply_button.isEnabled())
        page.apply_changes()
        entries = self.window.project.get_map_triggers(0)
        self.assertEqual(tuple(entries[0].to_bytes()), (3, 4, 0xFF, 0xF2))
        self.assertTrue(entries[0].is_shop)
        self.assertEqual(entries[0].shop_id, 2)
        self.window.undo()
        self.assertEqual(self.window.project.get_map_triggers(0), ())

    def test_weapon_and_deployment_ids_have_resolved_names(self) -> None:
        weapon_page = self.window.pages[self.window.page_index["weapons"]]
        self.assertIsInstance(weapon_page, WeaponPage)
        assert isinstance(weapon_page, WeaponPage)
        self.assertEqual(weapon_page.record_text(0x01), "$01  光束军刀")
        self.assertEqual(weapon_page.record_text(0x0B), "$0B  交叉粉碎炮")

        map_page = self.window.pages[self.window.page_index["maps"]]
        assert isinstance(map_page, MapPage)
        self.assertIn("伏击之战", map_page.map_list.item(0).text())
        if map_page.enemy_table.rowCount():
            unit_editor = map_page.enemy_table.cellWidget(0, 2)
            pilot_editor = map_page.enemy_table.cellWidget(0, 3)
            self.assertIn(" · ", unit_editor.currentText())
            self.assertIn(" · ", pilot_editor.currentText())

    def test_story_page_decodes_tokens_without_changing_rom(self) -> None:
        assert self.window.project is not None
        page = self.window.pages[self.window.page_index["story"]]
        self.assertIsInstance(page, StoryPage)
        assert isinstance(page, StoryPage)
        self.assertIsNotNone(page.current_selector)
        self.assertIsNotNone(page.current_index)
        self.assertGreater(page.tokens.rowCount(), 0)
        page.selector.setCurrentIndex(page.selector.findData(0x32))
        page.indices.setCurrentRow(0x0E)
        self.assertIn("劝降拉拉", page.decoded.toPlainText())
        self.assertNotIn("<C9", page.decoded.toPlainText())
        before = bytes(self.window.project.working)
        page.apply_text()
        self.assertEqual(bytes(self.window.project.working), before)

    def test_story_unicode_view_preserves_unmapped_tokens(self) -> None:
        page = self.window.pages[self.window.page_index["story"]]
        assert isinstance(page, StoryPage)
        original_raw = page._parse_hex(page.raw.toPlainText())
        page.text_table = TextTable.parse("FF=[结束]\n")
        page._render_decoded()
        decoded = page.decoded.toPlainText()
        self.assertTrue("[结束]" in decoded or "<" in decoded)
        self.assertEqual(page.text_table.encode(decoded), original_raw)

    def test_event_page_edits_reinforcement_with_compatible_template(self) -> None:
        assert self.window.project is not None
        page = self.window.pages[self.window.page_index["events"]]
        self.assertIsInstance(page, EventPage)
        assert isinstance(page, EventPage)
        page.search.setText("A11D")
        self.assertEqual(page.table.rowCount(), 1)
        page.table.selectRow(0)
        instruction = page._selected_instruction()
        self.assertIsNotNone(instruction)
        assert instruction is not None
        self.assertEqual(instruction.opcode, 0x4B)
        self.assertIn("人物ID=$2A（", page._parameter_text(instruction))
        self.assertIn("机体ID=$5E（", page._parameter_text(instruction))
        page.template.setCurrentIndex(page.template.findData(0x4A))
        page.parameters[0].setValue(0x10)
        page.parameters[1].setValue(0x08)
        page.apply_template_button.click()
        changed = self.window.project.chapter_event_codec.instruction_at(
            instruction.address, bytes(self.window.project.working)
        )
        self.assertEqual(changed.opcode, 0x4A)
        self.assertEqual(changed.parameters[:2], (0x10, 0x08))
        self.window.undo()
        restored = self.window.project.chapter_event_codec.instruction_at(
            instruction.address, bytes(self.window.project.working)
        )
        self.assertEqual(restored.opcode, 0x4B)

    def test_persuasion_page_uses_named_characters_and_undo(self) -> None:
        assert self.window.project is not None
        page = self.window.pages[self.window.page_index["persuasion"]]
        self.assertIsInstance(page, PersuasionPage)
        assert isinstance(page, PersuasionPage)
        self.assertEqual(page.table.rowCount(), 4)
        self.assertNotIn("原生名称", page.table.item(0, 2).text())
        original = self.window.project.get_persuasion_rule(0)
        page.table.selectRow(0)
        page.chapter.setCurrentIndex(page.chapter.findData(0x02))
        page.persuader.setCurrentIndex(page.persuader.findData(0x08))
        page.target.setCurrentIndex(page.target.findData(0x42))
        page.apply_button.click()
        changed = self.window.project.get_persuasion_rule(0)
        self.assertEqual(changed.raw, bytes((0x02, 0x08, 0x42)))
        self.window.undo()
        self.assertEqual(self.window.project.get_persuasion_rule(0).raw, original.raw)


if __name__ == "__main__":
    unittest.main(verbosity=2)
