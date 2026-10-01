from __future__ import annotations

import hashlib
import io
import json
import tempfile
import unittest
import zipfile
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch

from fc_editor.codecs.battle_music import BattleMusicCodec
from fc_editor.codecs.character_name import CharacterNameCodec
from fc_editor.codecs.chr import ChrCodec
from fc_editor.codecs.chapter_event import ChapterEventCodec
from fc_editor.codecs.custom_music import CustomMusicCodec
from fc_editor.codecs.map import MapCodec
from fc_editor.codecs.map_trigger import MapTrigger, MapTriggerCodec
from fc_editor.codecs.persuasion import PersuasionRuleCodec
from fc_editor.codecs.scenario_layout import ScenarioLayoutCodec
from fc_editor.codecs.story_text import StoryTextCodec
from fc_editor.codecs.unit import UnitCodec
from fc_editor.codecs.unit_name import UnitNameReferenceCodec
from fc_editor.codecs.unit_weapon import UnitWeaponCodec
from fc_editor.codecs.weapon import WeaponCodec
from fc_editor.codecs.weapon_name import WeaponNameReferenceCodec
from fc_editor.dc_text import dc_map_label, decode_dc_text, default_dc_text_table
from fc_editor.profiles import (
    DC_EXPANDED_MMC3_LEGACY_PROFILE,
    DC_EXPANDED_MMC3_PROFILE,
)
from fc_editor.project import ProjectDocument
from fc_editor.resources import Allocation, BankAllocator, ResourceGraph
from fc_editor.rom_image import RomImage
from fc_editor.models import ScenarioEntity
from fc_editor.unit_package import UnitPackage, UnitPackageAsset
from fc_editor.text_table import TextTable
from fc_rom_editor_core import RomProject, apply_ips
from dc_modifier.unit_packages import (
    affected_unit_ids,
    apply_unit_package,
    package_from_project,
)
from dc_modifier.music_import import assemble_famistudio_music_source, load_music_bank
from dc_modifier.map_tiles import campaign_tileset_key, render_map_tile


ROOT = Path(__file__).resolve().parents[1]
TARGET_ROM = ROOT / "output" / "rom" / "DC_kuorong_464K.nes"
LEGACY_ROM = ROOT / "references" / "rom" / "baselines" / "DC_kuorong.nes"
TARGET_SHA256 = "82C218275459D53C0F306F6BC036C4797316976E0FA7AD1D5A8247E338995B8E"


class DcExpandedProfileTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.rom = RomImage.load(TARGET_ROM)

    def test_target_identity_and_profile(self) -> None:
        self.assertEqual(hashlib.sha256(self.rom.data).hexdigest().upper(), TARGET_SHA256)
        self.assertIs(self.rom.profile, DC_EXPANDED_MMC3_PROFILE)
        self.assertTrue(self.rom.is_reference_base)
        self.assertEqual(self.rom.mapper, 194)
        self.assertEqual(self.rom.size, 1_310_736)

    def test_legacy_rom_remains_supported_without_becoming_the_default(self) -> None:
        legacy = RomImage.load(LEGACY_ROM)
        self.assertIs(legacy.profile, DC_EXPANDED_MMC3_LEGACY_PROFILE)
        self.assertTrue(legacy.is_reference_base)
        self.assertEqual(sum(item.size for item in legacy.profile.free_prg_regions), 200 * 1024)

    def test_primary_codecs_decode_and_round_trip(self) -> None:
        unit_codec = UnitCodec(self.rom)
        weapon_codec = WeaponCodec(self.rom)
        name_codec = UnitNameReferenceCodec(self.rom)
        map_codec = MapCodec(self.rom)
        map_trigger_codec = MapTriggerCodec(self.rom)
        persuasion_codec = PersuasionRuleCodec(self.rom)
        scenario_codec = ScenarioLayoutCodec(self.rom)
        story_codec = StoryTextCodec(self.rom)
        chr_codec = ChrCodec(self.rom)
        chapter_event_codec = ChapterEventCodec(self.rom)
        character_name_codec = CharacterNameCodec(self.rom)
        unit_weapon_codec = UnitWeaponCodec(self.rom)
        weapon_name_codec = WeaponNameReferenceCodec(self.rom)

        for unit_id in (1, 4, 5, 0x13, 0x80, 0xFF):
            self.assertTrue(unit_codec.round_trip_record(unit_id))
            self.assertTrue(name_codec.source_ids(name_codec.pointer(unit_id)))
        for weapon_id in (1, 2, 0x40, 0x80, 0xFE):
            self.assertTrue(weapon_codec.round_trip_record(weapon_id))
            self.assertTrue(weapon_name_codec.round_trip(weapon_id))
        for character_id in (0, 1, 2, 4, 5, 0x13, 0xC7):
            self.assertTrue(character_name_codec.round_trip(character_id))
        for unit_id in (1, 0x25, 0x79, 0xFF):
            config = unit_weapon_codec.decode(unit_id)
            self.assertEqual(unit_weapon_codec.encode(config), bytes(config.weapon_ids))
        for map_id in (0, 1, 0x1F, 0x20, 0x63):
            self.assertTrue(map_codec.round_trip(map_id))
        for scenario_id in (0, 1, 0x10, 0x1F):
            self.assertTrue(scenario_codec.round_trip(scenario_id))
        trigger_layouts = map_trigger_codec.layouts()
        self.assertEqual(len(trigger_layouts), 0x20)
        self.assertTrue(all(not item.entries for item in trigger_layouts[:0x0F]))
        self.assertEqual(
            trigger_layouts[0x0F].entries,
            (MapTrigger(0x1F, 0x08, 0xFF, 0x00),),
        )
        self.assertEqual(
            tuple(
                (rule.scenario_id, rule.persuader_id, rule.target_id)
                for rule in persuasion_codec.editable_rules()
            ),
            (
                (0x01, 0x06, 0x45),
                (0x02, 0x06, 0x45),
                (0x05, 0x0E, 0x41),
                (0x09, 0x08, 0x42),
            ),
        )
        self.assertEqual(
            tuple(rule.script_address for rule in persuasion_codec.editable_rules()),
            (0xAABF, 0xAB7D, 0xAC03, 0xAC31),
        )
        for selector in story_codec.selectors:
            self.assertTrue(story_codec.round_trip(selector, 0))
        self.assertEqual(chr_codec.tile_count, 0x4000)

        for tile_index in (0, 1, 0x1FF, 0x200, 0x3FFF):
            pixels = chr_codec.decode_tile(tile_index)
            self.assertEqual(chr_codec.encode_tile(pixels), chr_codec.tile_bytes(tile_index))
        self.assertEqual(len(chapter_event_codec.instructions()), 2637)
        self.assertEqual(len(chapter_event_codec.actions()), 294)
        first_reinforcement = next(
            item for item in chapter_event_codec.actions() if item.opcode == 0x4B
        )
        self.assertEqual(first_reinforcement.address, 0xA11D)
        self.assertEqual(first_reinforcement.parameters, (0x16, 0x04, 0x2A, 0x5E, 0x07, 0x0E))
        self.assertEqual(
            first_reinforcement.field_labels,
            ("X", "Y", "人物ID", "机体ID", "等级", "AI/标志"),
        )
        self.assertFalse(
            any(
                item.action_label.startswith(("操作码", "未知操作码"))
                for item in chapter_event_codec.instructions()
            )
        )

    def test_legacy_terrain_partition_repack_uses_shared_bank_capacity(self) -> None:
        project = RomProject.load(LEGACY_ROM)
        original = bytes(project.working)
        map0 = project.get_map(0)
        map1 = project.get_map(1)

        project.set_map_tiles(
            0,
            map0.width,
            map0.height,
            tuple(0 for _ in map0.tiles),
        )
        pointer_after_shrink = project.map_codec.pointers[2]

        grown_tiles = list(map1.tiles)
        for index in range(10):
            grown_tiles[index] = index % 2
        grown = project.map_codec.encode(
            map1.width, map1.height, tuple(grown_tiles)
        )
        self.assertGreater(len(grown), project.map_codec.capacities[1])

        project.set_map_tiles(
            1, map1.width, map1.height, tuple(grown_tiles)
        )
        self.assertEqual(project.get_map(1).tiles, tuple(grown_tiles))
        self.assertEqual(
            project.map_codec.pointers[2],
            pointer_after_shrink + len(grown) - len(map1.raw),
        )
        used, capacity = project.map_resource_replacement_usage(
            1, map1.width, map1.height, tuple(grown_tiles)
        )
        self.assertLessEqual(used, capacity)

        project.undo()
        project.undo()
        self.assertEqual(bytes(project.working), original)

    def test_legacy_terrain_partition_can_use_verified_bank_tail(self) -> None:
        project = RomProject.load(LEGACY_ROM)
        original = bytes(project.working)
        map0 = project.get_map(0)
        map1_pointer = project.map_codec.pointers[1]
        tiles = list(map0.tiles)
        self.assertEqual((tiles[3], len(map0.raw)), (5, 324))
        tiles[3] = 0
        encoded = project.map_codec.encode(
            map0.width, map0.height, tuple(tiles)
        )
        self.assertEqual(len(encoded), len(map0.raw) + 2)

        used, capacity = project.map_resource_replacement_usage(
            0, map0.width, map0.height, tuple(tiles)
        )
        self.assertEqual((used, capacity), (6711, 6722))
        self.assertEqual(
            project.legacy_map_terrain_total_usage(
                0, map0.width, map0.height, tuple(tiles)
            ),
            (14476, 17730),
        )

        project.set_map_tiles(0, map0.width, map0.height, tuple(tiles))
        self.assertEqual(project.get_map(0).tiles, tuple(tiles))
        self.assertEqual(project.map_codec.pointers[1], map1_pointer + 2)
        with tempfile.TemporaryDirectory() as directory:
            saved_path = Path(directory) / "map-bank-tail.nes"
            project.save_as(saved_path, make_backup=False)
            reopened = RomProject.load(saved_path)
            self.assertEqual(reopened.get_map(0).tiles, tuple(tiles))
            self.assertEqual(
                reopened.map_codec.storage_usage(0, reopened.working),
                (6711, 6722),
            )
        project.undo()
        self.assertEqual(bytes(project.working), original)

    def test_legacy_terrain_growth_cascades_maps_across_dynamic_bank_boundaries(self) -> None:
        project = RomProject.load(LEGACY_ROM)
        original = bytes(project.working)
        map0 = project.get_map(0)
        map21 = project.get_map(0x21)
        map29 = project.get_map(0x29)
        map1_pointer = project.map_codec.pointers[1]
        tiles: list[int] = []
        for row in range(map0.height):
            start = row * map0.width
            tiles.extend(map0.tiles[start : start + map0.width])
            tiles.append(0)
        draft = tuple(tiles)

        self.assertEqual(
            project.map_resource_replacement_usage(0, 28, 26, draft),
            (6453, 6722),
        )
        self.assertEqual(
            project.legacy_map_terrain_total_usage(0, 28, 26, draft),
            (14520, 17730),
        )
        project.set_map_tiles(0, 28, 26, draft)

        self.assertEqual(project.working[0x5BA3], 0x21)
        self.assertEqual(project.working[0x5BB7], 0x29)
        self.assertEqual(
            tuple((item.first_id, item.end_id) for item in project.map_codec.storage_ranges),
            ((0x00, 0x21), (0x21, 0x29), (0x29, 0x64)),
        )
        self.assertEqual(project.map_codec.pointers[1], map1_pointer + 46)
        self.assertEqual(project.map_codec.pointers[0x21], 0xB500)
        self.assertEqual(project.map_codec.pointers[0x29], 0xA000)
        self.assertEqual(project.get_map(0x21).tiles, map21.tiles)
        self.assertEqual(project.get_map(0x29).tiles, map29.tiles)
        self.assertTrue(all(project.map_codec.round_trip(index) for index in range(100)))

        with tempfile.TemporaryDirectory() as directory:
            saved_path = Path(directory) / "map-dynamic-banks.nes"
            project.save_as(saved_path, make_backup=False)
            reopened = RomProject.load(saved_path)
            self.assertEqual(reopened.get_map(0).tiles, draft)
            self.assertEqual(reopened.get_map(0x21).tiles, map21.tiles)
            self.assertEqual(reopened.get_map(0x29).tiles, map29.tiles)
            self.assertEqual(
                tuple(
                    (item.first_id, item.end_id)
                    for item in reopened.map_codec.storage_ranges
                ),
                ((0x00, 0x21), (0x21, 0x29), (0x29, 0x64)),
            )
            project_path = Path(directory) / "map-dynamic-banks.dcmod"
            project.save_project(project_path)
            reopened_project = RomProject.load_project(project_path, LEGACY_ROM)
            self.assertEqual(reopened_project.get_map(0).tiles, draft)
            self.assertEqual(reopened_project.get_map(0x21).tiles, map21.tiles)
            self.assertEqual(reopened_project.get_map(0x29).tiles, map29.tiles)

        project.undo()
        self.assertEqual(bytes(project.working), original)

    def test_current_battle_music_bindings(self) -> None:
        codec = BattleMusicCodec(self.rom)
        lyune = codec.decode(0x04)
        shuu = codec.decode(0x05)
        self.assertEqual((lyune.attacker_command, lyune.defender_command), (0x9D, 0x9D))
        self.assertEqual((shuu.attacker_command, shuu.defender_command), (0x9F, 0x9F))

    def test_custom_music_banks_are_valid(self) -> None:
        codec = CustomMusicCodec(self.rom)
        self.assertEqual(tuple(codec.slot_by_command), (0x9D, 0x9E, 0x9F))
        for command in codec.slot_by_command:
            self.assertEqual(len(codec.bank_bytes(command)), 0x2000)
            self.assertGreaterEqual(codec.validate_bank(codec.bank_bytes(command)), 1)

    def test_empty_project_is_byte_identical(self) -> None:
        project = ProjectDocument.create(self.rom)
        self.assertEqual(project.materialize(self.rom), self.rom.data)
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "empty.dcmod"
            project.save(path)
            loaded = ProjectDocument.load(path)
            self.assertEqual(loaded.materialize(self.rom), self.rom.data)


class ResourceModelTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.rom = RomImage.load(TARGET_ROM)

    def test_graph_describes_tables_free_space_and_active_chr(self) -> None:
        graph = ResourceGraph.from_profile(self.rom.profile, self.rom.data)
        self.assertEqual(graph.node("units.pointer_table").offset, 0x4876F)
        self.assertEqual(graph.node("prg.free.0").size, 264 * 1024)
        self.assertEqual(graph.node("prg.free.1").size, 200 * 1024)
        self.assertEqual(graph.node("chr.active").offset, 0x100010)
        self.assertEqual(graph.node("chr.active").size, 256 * 1024)
        self.assertTrue(graph.node("chr.active").writable)
        self.assertTrue(graph.node("audio.custom.9D").writable)
        self.assertEqual(graph.node("audio.custom.9F").size, 0x2000)
        self.assertTrue(graph.node("events.chapter_data").writable)
        self.assertTrue(graph.node("map_triggers.pointer_table").writable)
        self.assertEqual(graph.node("map_triggers.pointer_table").offset, 0x1588E)
        self.assertTrue(graph.node("map_triggers.managed_pool").writable)
        self.assertEqual(graph.node("map_triggers.managed_pool").size, 300)
        self.assertEqual(graph.node("events.chapter_data").offset, 0x36010)
        self.assertEqual(graph.node("events.chapter_data").size, 0x1FDA)
        self.assertEqual(graph.node("events.persuasion_rules").offset, 0x3B73D)
        self.assertEqual(graph.node("events.persuasion_rules").size, 97)
        self.assertTrue(graph.node("events.persuasion_rules").writable)
        self.assertEqual(graph.node("events.persuasion_pointers").offset, 0x35DD0)
        self.assertFalse(graph.node("events.persuasion_pointers").writable)

    def test_allocator_is_deterministic_and_stays_in_free_banks(self) -> None:
        allocator = BankAllocator(self.rom.profile, self.rom.data)
        first = allocator.allocate("test.first", "测试资源一", 0x1F00, alignment=0x10)
        second = allocator.allocate("test.second", "测试资源二", 0x0200, alignment=0x10)
        self.assertEqual(first.first_bank, 0x40)
        self.assertEqual(second.first_bank, 0x41)
        self.assertEqual(allocator.capacity, 464 * 1024)
        self.assertEqual(allocator.used, 0x2100)

    def test_allocator_can_use_both_released_regions(self) -> None:
        allocator = BankAllocator(self.rom.profile, self.rom.data)
        first = allocator.allocate(
            "fill.reclaimed",
            "填满回收区",
            264 * 1024,
            single_bank=False,
        )
        second = allocator.allocate("next.region", "第二资源区", 32)
        self.assertEqual(first.first_bank, 0x40)
        self.assertEqual(second.first_bank, 0x65)
        self.assertEqual(allocator.available, 200 * 1024 - 32)

    def test_allocator_rejects_protected_or_overlapping_reservations(self) -> None:
        allocator = BankAllocator(self.rom.profile, self.rom.data)
        with self.assertRaises(ValueError):
            allocator.allocate("BAD ID", "格式错误", 16)
        with self.assertRaises(ValueError):
            allocator.reserve(Allocation("valid.id", "有效", 0x80010, 16, 3))
        with self.assertRaises(ValueError):
            allocator.reserve(Allocation("bad", "错误资源", 16 + 0x64 * 0x2000, 16, 1))
        first = allocator.allocate("kept", "已占用资源", 32)
        with self.assertRaises(ValueError):
            allocator.reserve(Allocation("overlap", "重叠资源", first.offset, 4, 1))


class TextTableTests(unittest.TestCase):
    def test_unicode_and_unknown_tokens_round_trip(self) -> None:
        table = TextTable.parse("C901=机\nC902=体\nFF=[结束]\n")
        raw = bytes.fromhex("C901 C902 F0 FF")
        decoded = table.decode(raw)
        self.assertEqual(decoded, "机体<F0>[结束]")
        self.assertEqual(table.encode(decoded), raw)

    def test_template_allows_partially_completed_mapping(self) -> None:
        template = TextTable.template({b"\xFF", b"\xC9\x01"})
        completed = template.replace("C901=", "C901=机")
        table = TextTable.parse(completed)
        self.assertEqual(table.decode(bytes.fromhex("C901 FF")), "机<FF>")

    def test_whitespace_glyph_is_not_discarded(self) -> None:
        table = TextTable.parse("CAAA=　\n20= \n")
        self.assertEqual(table.decode(bytes.fromhex("CAAA 20")), "　 ")

    def test_duplicate_glyphs_decode_and_use_first_code_for_encoding(self) -> None:
        table = TextTable.parse("01=A\n02=A\n")
        self.assertEqual(table.decode(bytes((1, 2))), "AA")
        self.assertEqual(table.encode("A"), bytes((1,)))

    def test_builtin_dc_table_decodes_real_dialogue_without_raw_glyphs(self) -> None:
        table = default_dc_text_table()
        self.assertGreaterEqual(len(table.byte_to_text), 2700)
        raw = bytes.fromhex(
            "C9 0D C9 10 C9 A8 C9 A8 2F F2 CB 0B CA D1 CA D3 "
            "CB 61 CA E0 DA FA DA FB C9 64 CB 10 2F F6 FF"
        )
        self.assertEqual(
            decode_dc_text(raw),
            "劝降拉拉！\n接下来可以选择机体！】⟦结束⟧",
        )
        encoded = table.encode(table.decode(raw))
        self.assertEqual(len(encoded), len(raw))
        self.assertEqual(table.decode(encoded), table.decode(raw))

    def test_every_story_token_has_a_reversible_display_mapping(self) -> None:
        project = RomProject.load(TARGET_ROM)
        table = default_dc_text_table()
        for group in project.story_text_groups:
            for index in range(group.count):
                record = project.get_story_text(group.selector, index)
                for token in project.story_text_codec.tokenize(record.raw):
                    self.assertIn(token.raw, table.byte_to_text)
                if record.raw:
                    rendered = table.decode(record.raw)
                    encoded = table.encode(rendered)
                    self.assertEqual(len(encoded), len(record.raw))
                    self.assertEqual(table.decode(encoded), rendered)

    def test_known_chapter_labels_are_not_generic(self) -> None:
        self.assertEqual(dc_map_label(0), "伏击之战")
        self.assertEqual(dc_map_label(0x0C), "白河愁的试炼")
        self.assertEqual(dc_map_label(0x0D), "未使用关卡槽位")
        self.assertEqual(dc_map_label(0x20), "备用地图 1")


class EditorProjectTests(unittest.TestCase):
    def test_render_caches_decode_once_per_project_revision(self) -> None:
        project = RomProject.load(TARGET_ROM)
        with patch.object(
            project.unit_name_codec,
            "record_bytes",
            wraps=project.unit_name_codec.record_bytes,
        ) as unit_decode:
            first = project.unit_display_name(1)
            self.assertEqual(project.unit_display_name(1), first)
            self.assertEqual(unit_decode.call_count, 1)
            project.set_hit_threshold(project.get_hit_threshold() + 1)
            self.assertEqual(project.unit_display_name(1), first)
            self.assertEqual(unit_decode.call_count, 2)

        with patch.object(
            project.chr_codec,
            "decode_tile",
            wraps=project.chr_codec.decode_tile,
        ) as tile_decode:
            pixels = project.chr_tile_pixels(0)
            self.assertEqual(project.chr_tile_pixels(0), pixels)
            self.assertEqual(tile_decode.call_count, 1)
            project.set_hit_threshold(project.get_hit_threshold() - 1)
            self.assertEqual(project.chr_tile_pixels(0), pixels)
            self.assertEqual(tile_decode.call_count, 2)

    def test_public_writers_reject_configured_read_only_roots(self) -> None:
        project = RomProject.load(TARGET_ROM)
        with tempfile.TemporaryDirectory() as directory:
            reference_root = Path(directory) / "references"
            project.set_read_only_output_roots((reference_root,))
            with self.assertRaisesRegex(ValueError, "只读参考目录"):
                project.save_as(reference_root / "blocked.nes")
            with self.assertRaisesRegex(ValueError, "只读参考目录"):
                project.export_ips(reference_root / "blocked.ips")
            with self.assertRaisesRegex(ValueError, "只读参考目录"):
                project.save_project(reference_root / "blocked.dcmod")
            with self.assertRaisesRegex(ValueError, "只读参考目录"):
                project.build_release(reference_root / "release", "blocked")
            self.assertFalse(reference_root.exists())

    def test_fast_derived_rom_saves_keep_distinct_recoverable_backups(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            derived_rom = Path(directory) / "m01-derived.nes"
            project = RomProject.load(TARGET_ROM)
            with self.assertRaisesRegex(ValueError, "不能覆盖当前载入"):
                project.save_as(TARGET_ROM, make_backup=False)
            project.set_hit_threshold(71)
            project.save_as(derived_rom)
            first_saved = derived_rom.read_bytes()
            project.set_hit_threshold(69)
            project.save_as(derived_rom)
            second_saved = derived_rom.read_bytes()
            project.set_hit_threshold(70)
            project.save_as(derived_rom)
            backups = sorted(derived_rom.parent.glob(derived_rom.name + ".*.bak"))
            self.assertEqual(len(backups), 2)
            self.assertEqual({path.read_bytes() for path in backups}, {first_saved, second_saved})
            self.assertEqual(RomProject.load(derived_rom).get_hit_threshold(), 70)

    def test_managed_resource_import_undo_validation_and_project_round_trip(self) -> None:
        project = RomProject.load(TARGET_ROM)
        payload = bytes((index * 17 + 3) & 0xFF for index in range(0x2100))
        allocation = project.import_expansion_resource(
            "units.prototype",
            "测试机体资源",
            payload,
            single_bank=False,
        )
        self.assertEqual(allocation.first_bank, 0x40)
        self.assertEqual(project.expansion_used, len(payload))
        self.assertEqual(project.expansion_resource_data(allocation.resource_id), payload)
        self.assertFalse(any(issue.severity == "error" for issue in project.validate()))
        self.assertIn("测试机体资源", project.change_description(allocation.offset))
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "managed-resource.dcmod"
            project.save_project(path)
            reopened = RomProject.load_project(path, TARGET_ROM)
            self.assertEqual(reopened.expansion_allocations, (allocation,))
            self.assertEqual(reopened.expansion_resource_data(allocation.resource_id), payload)
            self.assertFalse(any(issue.severity == "error" for issue in reopened.validate()))
        project.undo()
        self.assertEqual(project.expansion_used, 0)
        self.assertEqual(
            bytes(project.working[allocation.offset : allocation.end]),
            bytes(len(payload)),
        )
        project.redo()
        self.assertEqual(project.expansion_resource_data(allocation.resource_id), payload)
        project.remove_expansion_resource(allocation.resource_id)
        self.assertEqual(project.expansion_used, 0)

    def test_map_trigger_repack_is_bounded_and_project_round_trips(self) -> None:
        project = RomProject.load(TARGET_ROM)
        self.assertTrue(project.supports_map_triggers)
        self.assertEqual(project.get_map_triggers(0), ())
        original = bytes(project.working)
        entry = MapTrigger(3, 4, 0x12, 0xF2)
        self.assertTrue(entry.matches_character(0x12))
        self.assertFalse(entry.matches_character(0x11))
        self.assertTrue(MapTrigger(3, 4, 0xFF, 0).matches_character(0x00))
        self.assertTrue(MapTrigger(3, 4, 0xFF, 0).matches_character(0xFE))
        project.set_map_triggers(0, (entry,))
        self.assertEqual(project.get_map_triggers(0), (entry,))
        self.assertEqual(
            project.get_map_triggers(0x0F),
            (MapTrigger(0x1F, 0x08, 0xFF, 0x00),),
        )
        self.assertLessEqual(
            project.map_trigger_codec.storage_used(project.working),
            project.map_trigger_codec.pool_capacity,
        )
        self.assertEqual(TARGET_ROM.read_bytes(), original)
        self.assertFalse(any(issue.severity == "error" for issue in project.validate()))
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "map-triggers.dcmod"
            project.save_project(path)
            reopened = RomProject.load_project(path, TARGET_ROM)
            self.assertEqual(reopened.get_map_triggers(0), (entry,))
        project.undo()
        self.assertEqual(project.get_map_triggers(0), ())

    def test_map_trigger_character_gate_precedes_kind_and_uses_player_path(self) -> None:
        project = RomProject.load(TARGET_ROM)
        codec = project.map_trigger_codec
        self.assertIsNotNone(codec)
        assert codec is not None

        def bank10(cpu_address: int, size: int) -> bytes:
            offset = codec.cpu_to_file_offset(cpu_address)
            return bytes(project.working[offset : offset + size])

        # The active character comparison is executed before the fourth byte
        # is read and split into map-event (< F0) or shop (>= F0).
        self.assertEqual(bank10(0x95E0, 6), bytes.fromhex("B1 00 C9 FF F0 1E"))
        self.assertEqual(bank10(0x95E6, 7), bytes.fromhex("20 87 C0 C5 05 F0 17"))
        self.assertEqual(bank10(0x9605, 6), bytes.fromhex("B1 00 C9 F0 B0 0F"))
        # The caller-side selectors separate controllable player slots 00-0A
        # from the enemy path, whose valid slots begin at 0E.
        self.assertEqual(bank10(0x8288, 6), bytes.fromhex("29 1F C9 0B B0 E4"))
        self.assertEqual(bank10(0x82E2, 10), bytes.fromhex("A5 01 10 8C 29 1F C9 0E 90 86"))

    def test_map_trigger_validation_rejects_bad_coordinates_and_duplicates(self) -> None:
        project = RomProject.load(TARGET_ROM)
        record = project.get_map(0)
        with self.assertRaisesRegex(ValueError, "超出"):
            project.set_map_triggers(
                0, (MapTrigger(record.width, 0, 0xFF, 0),)
            )
        with self.assertRaisesRegex(ValueError, "重复"):
            project.set_map_triggers(
                0,
                (
                    MapTrigger(1, 1, 0xFF, 0),
                    MapTrigger(1, 1, 0xFF, 1),
                ),
            )

    def test_map_trigger_pool_boundary_rejects_overflow_without_writing(self) -> None:
        project = RomProject.load(TARGET_ROM)
        record = project.get_map(0)
        self.assertGreaterEqual(record.width * record.height, 74)
        codec = project.map_trigger_codec
        self.assertIsNotNone(codec)
        assert codec is not None
        self.assertEqual(codec.pool_capacity, 310)
        gap_start = codec.cpu_to_file_offset(codec.spec.original_data_end)
        gap_end = codec.cpu_to_file_offset(codec.spec.managed_data_start)
        protected_gap = bytes(project.working[gap_start:gap_end])
        accepted = tuple(
            MapTrigger(index % record.width, index // record.width, 0xFF, 0xF2)
            for index in range(74)
        )
        overflow = accepted + (
            MapTrigger(74 % record.width, 74 // record.width, 0xFF, 0xF2),
        )
        project.set_map_triggers(0, accepted)
        self.assertEqual(project.map_trigger_codec.storage_used(project.working), 307)
        self.assertEqual(bytes(project.working[gap_start:gap_end]), protected_gap)
        self.assertTrue(
            all(
                codec.spec.original_data_start <= codec.pointer(map_id, project.working)
                < codec.spec.original_data_end
                or codec.spec.managed_data_start <= codec.pointer(map_id, project.working)
                < codec.spec.managed_data_end
                for map_id in range(codec.spec.scenario_count)
            )
        )
        before_overflow = bytes(project.working)
        with self.assertRaisesRegex(ValueError, "分段共享池只有 310 字节"):
            project.set_map_triggers(0, overflow)
        self.assertEqual(bytes(project.working), before_overflow)
        self.assertEqual(project.get_map_triggers(0), accepted)
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "map-triggers-near-capacity.nes"
            project.save_as(path, make_backup=False)
            reopened = RomProject.load(path)
            self.assertEqual(reopened.get_map_triggers(0), accepted)
            self.assertEqual(reopened.map_trigger_codec.storage_used(reopened.working), 307)

    def test_scenario_shared_pool_repack_matches_reference_and_reopens(self) -> None:
        project = RomProject.load(TARGET_ROM)
        codec = project.scenario_layout_codec
        self.assertEqual(
            (codec.storage_used(project.working), codec.pool_capacity),
            (1236, 6891),
        )
        before = bytes(project.working)
        layout = project.get_scenario_layout(0)
        changed = replace(
            layout,
            enemies=(ScenarioEntity(0, 0, 1, 1, 1, 0),),
        )
        self.assertEqual(codec.storage_used_after(project.working, 0, changed), 1246)
        project.set_scenario_layout(changed)
        self.assertEqual(project.get_scenario_layout(0).enemies, changed.enemies)
        self.assertEqual(
            project.scenario_layout_codec.storage_used(project.working), 1246
        )
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "scenario-shared-pool.nes"
            project.save_as(path, make_backup=False)
            reopened = RomProject.load(path)
            self.assertEqual(reopened.get_scenario_layout(0).enemies, changed.enemies)
            self.assertEqual(
                reopened.scenario_layout_codec.storage_used(reopened.working), 1246
            )
            project_path = Path(directory) / "scenario-shared-pool.dcmod"
            project.save_project(project_path)
            replayed = RomProject.load_project(project_path, TARGET_ROM)
            self.assertEqual(replayed.get_scenario_layout(0).enemies, changed.enemies)
            self.assertEqual(
                replayed.scenario_layout_codec.storage_used(replayed.working), 1246
            )
        project.undo()
        self.assertEqual(bytes(project.working), before)

    def test_scenario_shared_pool_overflow_is_atomic(self) -> None:
        project = RomProject.load(TARGET_ROM)
        before = bytes(project.working)
        layout = project.get_scenario_layout(0)
        changed = replace(
            layout,
            prelude=(0,) * 6800,
        )
        self.assertGreater(
            project.scenario_layout_codec.storage_used_after(
                project.working, 0, changed
            ),
            project.scenario_layout_codec.pool_capacity,
        )
        with self.assertRaisesRegex(ValueError, "32.*共享池"):
            project.set_scenario_layout(changed)
        self.assertEqual(bytes(project.working), before)

    def test_scenario_can_grow_past_stock_end_then_link_expansion(self) -> None:
        project = RomProject.load(TARGET_ROM)
        layout = project.get_scenario_layout(0)
        changed = replace(
            layout,
            enemies=tuple(
                ScenarioEntity(index, 0, index + 1, index + 1, 1, 0)
                for index in range(4)
            ),
        )
        projected = project.scenario_layout_codec.storage_used_after(
            project.working, 0, changed
        )
        self.assertGreater(projected, 1259)
        self.assertLess(projected, project.scenario_layout_codec.pool_capacity)
        project.set_scenario_layout(changed)
        self.assertEqual(project.get_scenario_layout(0).enemies, changed.enemies)
        project.configure_expansion(288, 64, 112)
        self.assertEqual(project.get_scenario_layout(0).enemies, changed.enemies)

    def test_scenario_user_case_1258_to_1264_saves_and_reopens(self) -> None:
        project = RomProject.load(TARGET_ROM)
        layout = project.get_scenario_layout(0)
        staged = replace(
            layout,
            enemies=tuple(
                ScenarioEntity(index, 0, index + 1, index + 1, 1, 0)
                for index in range(3)
            ),
        )
        project.set_scenario_layout(staged)
        self.assertEqual(
            project.scenario_layout_codec.storage_used(project.working), 1258
        )
        changed = replace(
            staged,
            enemies=staged.enemies + (ScenarioEntity(4, 0, 4, 4, 1, 0),),
        )
        self.assertEqual(
            project.scenario_layout_codec.storage_used_after(
                project.working, 0, changed
            ),
            1264,
        )
        project.set_scenario_layout(changed)
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "scenario-1264.nes"
            project.save_as(path, make_backup=False)
            reopened = RomProject.load(path)
            self.assertEqual(reopened.get_scenario_layout(0).enemies, changed.enemies)
            self.assertEqual(
                reopened.scenario_layout_codec.storage_used(reopened.working),
                1264,
            )

    def test_campaign_map_tiles_render_from_active_chr(self) -> None:
        project = RomProject.load(TARGET_ROM)
        self.assertEqual(campaign_tileset_key(0), "D")
        self.assertEqual(campaign_tileset_key(6), "F")
        self.assertEqual(campaign_tileset_key(12), "G")
        self.assertEqual(campaign_tileset_key(31), "C")
        self.assertIsNone(campaign_tileset_key(32))
        background = render_map_tile(project, "D", 0)
        palette_one = render_map_tile(project, "D", 1)
        self.assertEqual((background.width(), background.height()), (16, 16))
        self.assertNotEqual(
            {background.pixelColor(x, y).name() for y in range(16) for x in range(16)},
            {palette_one.pixelColor(x, y).name() for y in range(16) for x in range(16)},
        )

    def test_weapon_character_and_music_names_are_resolved_from_rom(self) -> None:
        project = RomProject.load(TARGET_ROM)
        self.assertEqual(project.weapon_display_name(0x01), "光束军刀")
        self.assertEqual(project.weapon_display_name(0x0B), "交叉粉碎炮")
        self.assertEqual(project.weapon_display_name(0x40), "空白/未分配武器槽")
        self.assertEqual(project.character_display_name(0x02), "查理")
        self.assertEqual(project.character_display_name(0x13), "拉坎")
        self.assertEqual(project.character_display_name(0x17), "空白/未分配人物槽")
        self.assertEqual(
            project.character_display_name(0x1D),
            "？？？",
        )
        self.assertEqual(project.character_display_name(0x1E), "？？？")
        self.assertEqual(project.battle_music_selector_label(0x13), "睿智之神")
        self.assertNotEqual(project.profile.battle_music.tracks[1].label, "原曲 01")
        self.assertFalse(
            any(
                label in project.unit_display_name(unit_id)
                for unit_id in range(1, project.unit_count)
                for label in ("未知原生名称", "原生名称")
            )
        )
        self.assertFalse(
            any(
                project.weapon_display_name(weapon_id).startswith("武器记录")
                for weapon_id in range(1, project.weapon_count)
            )
        )
        self.assertFalse(
            any(
                project.character_display_name(character_id).startswith("超出")
                for character_id in range(project.profile.character_name_count)
            )
        )
        tracks = {track.command: track.label for track in project.profile.battle_music.tracks}
        self.assertEqual(set(range(0x80, 0xA4)), set(tracks) - {0x00})
        self.assertEqual(tracks[0x87], "地球我方音乐")
        self.assertEqual(tracks[0x93], "通关音乐")
        self.assertEqual(tracks[0x9D], "音乐9D（Ash to Ash）")
        self.assertTrue(any("用途未确认" in label for label in tracks.values()))

    def test_unit_weapon_and_weapon_name_project_round_trip(self) -> None:
        project = RomProject.load(TARGET_ROM)
        original_slots = project.get_unit_weapons(0x25)
        original_name = project.get_weapon_name_pointer(0x0B)
        project.set_unit_weapon(0x25, 0, 0x01)
        project.set_weapon_name_reference(0x0B, 0x01)
        self.assertEqual(project.get_unit_weapons(0x25)[0], 0x01)
        self.assertEqual(project.weapon_display_name(0x0B), "光束军刀")
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "names-and-weapons.dcmod"
            project.save_project(path)
            reopened = RomProject.load_project(path, TARGET_ROM)
            self.assertEqual(reopened.get_unit_weapons(0x25)[0], 0x01)
            self.assertEqual(reopened.weapon_display_name(0x0B), "光束军刀")
        project.reset_unit_weapons(0x25)
        project.reset_weapon_name(0x0B)
        self.assertEqual(project.get_unit_weapons(0x25), original_slots)
        self.assertEqual(project.get_weapon_name_pointer(0x0B), original_name)

    def test_clear_unit_bundle_empties_instead_of_restoring_original(self) -> None:
        project = RomProject.load(TARGET_ROM)
        unit_id = 0x09
        before = bytes(project.working)
        self.assertNotEqual(project.record_bytes(unit_id), bytes(16))
        self.assertNotEqual(project.unit_display_name(unit_id), "空白/未分配机体槽")
        self.assertNotEqual(project.get_unit_weapons(unit_id), (0, 0))

        project.clear_unit_bundle(unit_id)

        self.assertEqual(project.record_bytes(unit_id), bytes(16))
        self.assertEqual(project.unit_display_name(unit_id), "空白/未分配机体槽")
        self.assertEqual(project.get_unit_weapons(unit_id), (0, 0))
        self.assertEqual(len(project._undo_stack), 1)
        project.undo()
        self.assertEqual(bytes(project.working), before)

    def test_clear_all_unit_bundles_empties_every_slot_atomically(self) -> None:
        project = RomProject.load(TARGET_ROM)
        before = bytes(project.working)

        project.clear_all_unit_bundles()

        for unit_id in (0x01, 0x09, 0x25, 0x80, 0xFF):
            self.assertEqual(project.record_bytes(unit_id), bytes(16))
            self.assertEqual(
                project.unit_display_name(unit_id), "空白/未分配机体槽"
            )
            self.assertEqual(project.unit_name_record_bytes(unit_id), b"\xFF")
            self.assertEqual(project.get_unit_weapons(unit_id), (0, 0))
        self.assertEqual(len(project._undo_stack), 1)
        project.undo()
        self.assertEqual(bytes(project.working), before)

    def test_character_name_reference_project_round_trip(self) -> None:
        project = RomProject.load(TARGET_ROM)
        original_pointer = project.get_character_name_pointer(0x13)
        source_pointer = project.get_character_name_pointer(0x02)
        project.set_character_name_reference(0x13, 0x02)
        self.assertEqual(project.get_character_name_pointer(0x13), source_pointer)
        self.assertEqual(project.character_display_name(0x13), "查理")
        self.assertEqual(
            project.change_description(
                project.character_name_codec.pointer_offset(0x13)
            ),
            "人物 13 · 名称指针",
        )
        self.assertFalse(any(issue.severity == "error" for issue in project.validate()))
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "character-name.dcmod"
            project.save_project(path)
            reopened = RomProject.load_project(path, TARGET_ROM)
            self.assertEqual(reopened.get_character_name_pointer(0x13), source_pointer)
            self.assertEqual(reopened.character_display_name(0x13), "查理")
        project.reset_character_name(0x13)
        self.assertEqual(project.get_character_name_pointer(0x13), original_pointer)

    def test_direct_names_use_existing_slots_and_round_trip(self) -> None:
        project = RomProject.load(TARGET_ROM)
        project.set_unit_name_text(0x01, "查理")
        project.set_character_name_text(0x13, "查理")
        project.set_weapon_name_text(0x0B, "光束军刀")
        self.assertEqual(project.unit_display_name(0x01), "查理")
        self.assertEqual(project.character_display_name(0x13), "查理")
        self.assertEqual(project.weapon_display_name(0x0B), "光束军刀")
        self.assertEqual(project.unit_name_record_bytes(0x01)[-1], 0xFF)
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "direct-names.dcmod"
            project.save_project(path)
            reopened = RomProject.load_project(path, TARGET_ROM)
            self.assertEqual(reopened.unit_display_name(0x01), "查理")
            self.assertEqual(reopened.character_display_name(0x13), "查理")
            self.assertEqual(reopened.weapon_display_name(0x0B), "光束军刀")

    def test_weapon_name_shared_pool_allows_balanced_growth(self) -> None:
        project = RomProject.load(TARGET_ROM)
        first = project.weapon_display_name(0x0B)
        second = project.weapon_display_name(0x0D)
        aliases = project.weapon_name_source_ids(0x0B)
        before = bytes(project.working)

        project.set_weapon_name_text(0x0B, "A")
        project.set_weapon_name_text(0x0D, second + "A")
        self.assertEqual(project.weapon_display_name(0x0B), "A")
        self.assertEqual(project.weapon_display_name(0x0D), second + "A")
        self.assertEqual(project.weapon_name_source_ids(0x0B), aliases)
        self.assertFalse(any(issue.severity == "error" for issue in project.validate()))

        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "weapon-name-pool.dcmod"
            project.save_project(path)
            reopened = RomProject.load_project(path, TARGET_ROM)
            self.assertEqual(reopened.weapon_display_name(0x0B), "A")
            self.assertEqual(reopened.weapon_display_name(0x0D), second + "A")
        project.undo()
        project.undo()
        self.assertEqual(bytes(project.working), before)
        self.assertEqual(project.weapon_display_name(0x0B), first)

    def test_unit_name_extension_allows_independent_growth(self) -> None:
        project = RomProject.load(TARGET_ROM)
        first = project.unit_display_name(0x01)
        second = project.unit_display_name(0x02)
        before = bytes(project.working)

        project.set_unit_name_text(0x01, "A")
        project.set_unit_name_text(0x02, second + "A")
        self.assertEqual(project.unit_display_name(0x01), "A")
        self.assertEqual(project.unit_display_name(0x02), second + "A")
        self.assertEqual(project.unit_name_source_ids(0x01), (0x01,))
        self.assertFalse(any(issue.severity == "error" for issue in project.validate()))
        expected_source_ids = project.unit_name_codec.baseline_source_ids(
            project.unit_name_codec.original_pointers[0x02]
        )
        project.set_unit_name_reference(0x03, 0x02)
        self.assertEqual(project.unit_name_source_ids(0x03), expected_source_ids)
        project.undo()

        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "unit-name-pool.dcmod"
            project.save_project(path)
            reopened = RomProject.load_project(path, TARGET_ROM)
            self.assertEqual(reopened.unit_display_name(0x01), "A")
            self.assertEqual(reopened.unit_display_name(0x02), second + "A")
        project.undo()
        project.undo()
        self.assertEqual(bytes(project.working), before)
        self.assertEqual(project.unit_display_name(0x01), first)

    def test_unit_name_edit_restores_unreferenced_canonical_identity(self) -> None:
        project = RomProject.load(TARGET_ROM)
        unique_id = next(
            ids[0]
            for pointer, ids in project.unit_name_codec.ids_by_pointer.items()
            if pointer and len(ids) == 1 and ids[0] > 0
        )
        target_id = 0x02 if unique_id != 0x02 else 0x03
        project.set_unit_name_reference(unique_id, target_id)
        replacement = project.unit_display_name(target_id) + "A"
        project.set_unit_name_text(target_id, replacement)
        project.set_unit_name_text(unique_id, "B")
        self.assertEqual(project.unit_display_name(target_id), replacement)
        self.assertEqual(project.unit_display_name(unique_id), "B")
        self.assertEqual(project.unit_name_source_ids(unique_id), (unique_id,))

    def test_direct_name_rejects_overflow_without_mutation(self) -> None:
        project = RomProject.load(TARGET_ROM)
        before = bytes(project.working)
        with self.assertRaisesRegex(ValueError, "机体名称扩展池容量不足"):
            project.set_unit_name_text(0x01, "A" * 16000)
        self.assertEqual(bytes(project.working), before)

    def test_dc_unit_names_match_verified_labels_and_deduplicate_shared_pointers(self) -> None:
        project = RomProject.load(TARGET_ROM)
        expected = {
            0x01: "盖塔",
            0x25: "睿智之神",
            0x79: "里克·大魔",
            0x86: "里克·大魔",
            0xAB: "HIV高达",
            0xF1: "萨德兰",
        }
        for unit_id, name in expected.items():
            self.assertEqual(project.unit_display_name(unit_id), name)
        self.assertEqual(project.unit_display_name(0x26), "空白/未分配机体槽")
        self.assertFalse(
            any(
                "原生名称" in project.unit_display_name(unit_id)
                for unit_id in range(1, project.unit_count)
            )
        )
        options = project.unit_name_reference_options()
        self.assertEqual(len(options), len(set(project.unit_name_codec.original_pointers[1:])))
        self.assertLess(len(options), project.unit_count - 1)
        for _source_id, pointer, label, source_ids in options:
            self.assertEqual(project.unit_name_pointer_display_name(pointer), label)
            self.assertTrue(source_ids)

    def test_edit_undo_redo_and_release_round_trip(self) -> None:
        project = RomProject.load(TARGET_ROM)
        original_movement = project.get_value(1, "movement")
        changed_movement = (original_movement + 1) & 0xFF
        project.set_value(1, "movement", changed_movement)
        project.set_battle_music_binding(0x04, 0x9E, 0x9E)
        self.assertEqual(project.get_value(1, "movement"), changed_movement)
        self.assertTrue(project.can_undo)
        project.undo()
        self.assertEqual(
            (
                project.get_battle_music_binding(0x04).attacker_command,
                project.get_battle_music_binding(0x04).defender_command,
            ),
            (0x9D, 0x9D),
        )
        project.redo()
        self.assertEqual(project.get_battle_music_binding(0x04).attacker_command, 0x9E)
        self.assertFalse(any(issue.severity == "error" for issue in project.validate()))

        with tempfile.TemporaryDirectory() as directory:
            artifacts = project.build_release(directory, "test_release")
            self.assertEqual(artifacts.project.suffix, ".dcmod")
            self.assertEqual(apply_ips(project.original, artifacts.ips.read_bytes()), artifacts.rom.read_bytes())
            reopened = RomProject.load_project(artifacts.project, TARGET_ROM)
            self.assertEqual(bytes(reopened.working), artifacts.rom.read_bytes())
        self.assertEqual(hashlib.sha256(TARGET_ROM.read_bytes()).hexdigest().upper(), TARGET_SHA256)

    def test_core_refuses_to_overwrite_base_rom(self) -> None:
        project = RomProject.load(TARGET_ROM)
        with self.assertRaises(ValueError):
            project.save_as(TARGET_ROM)

    def test_chr_tile_edit_undo_and_project_round_trip(self) -> None:
        project = RomProject.load(TARGET_ROM)
        tile_index = next(
            index
            for index in range(project.chr_tile_count)
            if len(set(project.chr_tile_pixels(index))) > 1
        )
        original = project.chr_tile_pixels(tile_index)
        changed = list(original)
        changed[0] = (changed[0] + 1) % 4
        project.set_chr_tile_pixels(tile_index, changed)
        self.assertEqual(project.chr_tile_pixels(tile_index)[0], changed[0])
        self.assertEqual(
            project.change_description(project.chr_codec.tile_offset(tile_index)),
            f"CHR图块 ${tile_index:04X}",
        )
        self.assertFalse(any(issue.severity == "error" for issue in project.validate()))
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "chr.dcmod"
            project.save_project(path)
            reopened = RomProject.load_project(path, TARGET_ROM)
            self.assertEqual(reopened.chr_tile_pixels(tile_index), tuple(changed))
        project.undo()
        self.assertEqual(project.chr_tile_pixels(tile_index), original)

    def test_custom_music_replace_undo_and_project_round_trip(self) -> None:
        project = RomProject.load(TARGET_ROM)
        original = project.custom_music_bank(0x9D)
        replacement = project.custom_music_bank(0x9E)
        project.set_custom_music_bank(0x9D, replacement)
        self.assertEqual(project.custom_music_bank(0x9D), replacement)
        self.assertFalse(any(issue.severity == "error" for issue in project.validate()))
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "music.dcmod"
            project.save_project(path)
            reopened = RomProject.load_project(path, TARGET_ROM)
            self.assertEqual(reopened.custom_music_bank(0x9D), replacement)
        project.undo()
        self.assertEqual(project.custom_music_bank(0x9D), original)

    def test_famistudio_asm_and_binary_music_import(self) -> None:
        expected = ROOT / "output" / "build" / "asm" / "dc_dual_music_61.bin"
        source = ROOT / "src" / "asm" / "ash_to_ash_famistudio_asm6.asm"
        self.assertEqual(assemble_famistudio_music_source(source), expected.read_bytes())
        self.assertEqual(load_music_bank(expected), expected.read_bytes())
        with tempfile.TemporaryDirectory() as directory:
            invalid = Path(directory) / "invalid.bin"
            invalid.write_bytes(b"bad")
            with self.assertRaisesRegex(ValueError, "8192"):
                load_music_bank(invalid)

    def test_chapter_reinforcement_and_recruitment_templates_round_trip(self) -> None:
        project = RomProject.load(TARGET_ROM)
        reinforcement = next(
            item
            for item in project.chapter_event_instructions(actions_only=True)
            if item.opcode == 0x4B
        )
        replacement = bytes((0x4A, 0x10, 0x08, 0x3D, 0xA8, 0x20, 0x03))
        project.set_chapter_event_instruction(reinforcement.address, replacement)
        changed = project.chapter_event_codec.instruction_at(
            reinforcement.address, bytes(project.working)
        )
        self.assertEqual(changed.action_label, "客军增援")
        self.assertEqual(changed.raw, replacement)

        remove = next(
            item
            for item in project.chapter_event_instructions(actions_only=True)
            if item.opcode == 0x6B
        )
        project.set_chapter_event_instruction(remove.address, bytes((0x67,)))
        converted = project.chapter_event_codec.instruction_at(
            remove.address, bytes(project.working)
        )
        self.assertEqual(converted.action_label, "转为临时友军")
        self.assertFalse(any(issue.severity == "error" for issue in project.validate()))
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "events.dcmod"
            project.save_project(path)
            reopened = RomProject.load_project(path, TARGET_ROM)
            self.assertEqual(
                reopened.chapter_event_codec.instruction_at(
                    reinforcement.address, bytes(reopened.working)
                ).raw,
                replacement,
            )
            self.assertEqual(
                reopened.chapter_event_codec.instruction_at(
                    remove.address, bytes(reopened.working)
                ).opcode,
                0x67,
            )
        project.undo()
        self.assertEqual(
            project.chapter_event_codec.instruction_at(
                remove.address, bytes(project.working)
            ).opcode,
            0x6B,
        )

    def test_chapter_event_editor_rejects_length_changes(self) -> None:
        project = RomProject.load(TARGET_ROM)
        reinforcement = next(
            item
            for item in project.chapter_event_instructions(actions_only=True)
            if item.opcode == 0x4B
        )
        with self.assertRaisesRegex(ValueError, "保持 7 字节"):
            project.set_chapter_event_instruction(reinforcement.address, bytes((0x69, 0x01)))

    def test_persuasion_rule_edit_undo_and_project_round_trip(self) -> None:
        project = RomProject.load(TARGET_ROM)
        original = project.get_persuasion_rule(0)
        project.set_persuasion_rule(0, 0x02, 0x08, 0x42)
        changed = project.get_persuasion_rule(0)
        self.assertEqual(
            (changed.scenario_id, changed.persuader_id, changed.target_id),
            (0x02, 0x08, 0x42),
        )
        self.assertFalse(any(issue.severity == "error" for issue in project.validate()))
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "persuasion.dcmod"
            project.save_project(path)
            reopened = RomProject.load_project(path, TARGET_ROM)
            self.assertEqual(reopened.get_persuasion_rule(0).raw, changed.raw)
        project.undo()
        self.assertEqual(project.get_persuasion_rule(0).raw, original.raw)

        with self.assertRaisesRegex(ValueError, "没有独立安全脚本"):
            project.set_persuasion_rule(4, 0x02, 0x08, 0x42)


class UnitPackageTests(unittest.TestCase):
    def test_package_is_deterministic_and_round_trips(self) -> None:
        project = RomProject.load(TARGET_ROM)
        package = package_from_project(project, 1, chr_ranges=((0x20, 2),))
        self.assertEqual(package.to_bytes(), package.to_bytes())
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "test.dcunit"
            package.save(path)
            loaded = UnitPackage.load(path)
        self.assertEqual(loaded, package)
        self.assertEqual(loaded.unit_record, project.record_bytes(1))
        self.assertEqual(loaded.assets[0].metadata_map["firstTile"], 0x20)
        self.assertEqual(len(loaded.assets[0].data), 32)

    def test_apply_package_is_one_undoable_transaction(self) -> None:
        project = RomProject.load(TARGET_ROM)
        package = package_from_project(project, 1)
        target_id = next(
            unit_id
            for unit_id in range(2, project.unit_count)
            if project.pointer_by_id[unit_id] != project.pointer_by_id[1]
            and len(project.ids_by_pointer[project.pointer_by_id[unit_id]]) == 1
        )
        original_record = project.record_bytes(target_id)
        original_name_pointer = project.get_unit_name_pointer(target_id)
        affected = apply_unit_package(project, package, target_id)
        self.assertEqual(affected, (target_id,))
        self.assertEqual(project.record_bytes(target_id), package.unit_record)
        self.assertEqual(
            project.get_unit_name_pointer(target_id),
            project.get_unit_name_pointer(1),
        )
        self.assertIn("导入机体", project.undo_description)
        project.undo()
        self.assertEqual(project.record_bytes(target_id), original_record)
        self.assertEqual(project.get_unit_name_pointer(target_id), original_name_pointer)

    def test_shared_target_impact_is_reported(self) -> None:
        project = RomProject.load(TARGET_ROM)
        self.assertEqual(affected_unit_ids(project, 1), (1, 5, 72))

    def test_package_import_detaches_shared_target_record(self) -> None:
        project = RomProject.load(TARGET_ROM)
        package = package_from_project(project, 2)
        shared_ids = affected_unit_ids(project, 1)
        self.assertGreater(len(shared_ids), 1)
        untouched = {
            unit_id: project.record_bytes(unit_id)
            for unit_id in shared_ids if unit_id != 1
        }

        affected = apply_unit_package(project, package, 1)

        self.assertEqual(affected, (1,))
        self.assertEqual(project.record_bytes(1), package.unit_record)
        self.assertTrue(all(
            project.record_bytes(unit_id) == raw
            for unit_id, raw in untouched.items()
        ))

    def test_package_applies_chr_assets_and_undoes_everything_together(self) -> None:
        project = RomProject.load(TARGET_ROM)
        tile_index = 0x20
        original_tile = project.chr_codec.tile_bytes(tile_index, project.original)
        changed_tile = bytes((value ^ 0xFF) for value in original_tile)
        package = package_from_project(project, 1)
        package = UnitPackage(
            package.label,
            package.source_profile,
            package.source_rom_sha256,
            package.source_unit_id,
            package.unit_record,
            package.name_source_id,
            (
                UnitPackageAsset(
                    "chr.test",
                    "chr_tiles",
                    "chr_test.chr",
                    changed_tile,
                    (("firstTile", tile_index), ("tileCount", 1)),
                ),
            ),
        )
        target_record = project.record_bytes(9)
        apply_unit_package(project, package, 9)
        self.assertEqual(
            project.chr_codec.tile_bytes(tile_index, bytes(project.working)),
            changed_tile,
        )
        project.undo()
        self.assertEqual(project.record_bytes(9), target_record)
        self.assertEqual(
            project.chr_codec.tile_bytes(tile_index, bytes(project.working)),
            original_tile,
        )

    def test_package_rejects_tampered_asset_and_unsupported_asset_import(self) -> None:
        project = RomProject.load(TARGET_ROM)
        asset = UnitPackageAsset("portrait", "battle_graphics", "portrait.bin", b"1234")
        package = UnitPackage(
            label="测试资源机体",
            source_profile=project.profile.key,
            source_rom_sha256=project.source_sha256,
            source_unit_id=1,
            unit_record=project.record_bytes(1),
            name_source_id=1,
            assets=(asset,),
        )
        with self.assertRaisesRegex(ValueError, "尚未接通"):
            apply_unit_package(project, package, 9)
        self.assertFalse(project.is_dirty)

        manifest = package.to_manifest()
        manifest["assets"][0]["sha256"] = "0" * 64
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "tampered.dcunit"
            with zipfile.ZipFile(path, "w") as archive:
                archive.writestr("manifest.json", json.dumps(manifest))
                archive.writestr("assets/portrait.bin", asset.data)
            with self.assertRaisesRegex(Exception, "哈希不匹配"):
                UnitPackage.load(path)

    def test_package_rejects_unsafe_archive_path(self) -> None:
        project = RomProject.load(TARGET_ROM)
        manifest = package_from_project(project, 1).to_manifest()
        payload = io.BytesIO()
        with zipfile.ZipFile(payload, "w") as archive:
            archive.writestr("manifest.json", json.dumps(manifest))
            archive.writestr("../outside.bin", b"unsafe")
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "unsafe.dcunit"
            path.write_bytes(payload.getvalue())
            with self.assertRaisesRegex(Exception, "不安全路径"):
                UnitPackage.load(path)


if __name__ == "__main__":
    unittest.main(verbosity=2)
