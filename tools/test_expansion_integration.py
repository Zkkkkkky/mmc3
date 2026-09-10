from __future__ import annotations

import hashlib
import json
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path

from fc_editor.expansion import (
    FLAG_MAPS,
    FLAG_MAP_TRIGGERS,
    FLAG_SCENARIOS,
    FLAG_UNITS,
)
from fc_editor.codecs.map_trigger import MapTrigger
from fc_editor.expansion_unit import PACKED_BODY_TABLE
from fc_rom_editor_core import RomProject


ROOT = Path(__file__).resolve().parents[1]
TARGET_ROM = ROOT / "FC模拟器" / "DC_kuorong_464K.nes"


class ExpansionIntegrationTests(unittest.TestCase):
    """End-to-end checks for the automatic map/unit/story capacity split."""

    @staticmethod
    def _configured(
        map_kib: int = 304,
        unit_kib: int = 48,
        story_kib: int = 112,
    ) -> RomProject:
        project = RomProject.load(TARGET_ROM)
        project.configure_expansion(map_kib, unit_kib, story_kib)
        return project

    @staticmethod
    def _longer_story(project: RomProject, selector: int, index: int) -> bytes:
        raw = project.get_story_text(selector, index, original=True).raw
        # Keep the required standalone FF terminator while adding one ordinary
        # byte before it.  This exercises the variable-length relocation path.
        return raw[:-1] + b"\x01\xFF"

    def test_recommended_split_is_disjoint_and_validates(self) -> None:
        source = TARGET_ROM.read_bytes()
        project = self._configured()
        plan = project.expansion_plan
        self.assertIsNotNone(plan)
        assert plan is not None
        self.assertEqual(plan.total_kib, 464)
        self.assertEqual(plan.unassigned_kib, 0)
        self.assertEqual(
            plan.flags,
            FLAG_MAPS | FLAG_UNITS | FLAG_SCENARIOS | FLAG_MAP_TRIGGERS,
        )
        self.assertEqual(
            hashlib.sha256(TARGET_ROM.read_bytes()).digest(),
            hashlib.sha256(source).digest(),
        )

        assigned = plan.unit_banks + plan.map_banks + plan.story_banks
        self.assertEqual(len(assigned), len(set(assigned)))
        allocations = project.expansion_allocations
        self.assertTrue(allocations)
        for left_index, left in enumerate(allocations):
            self.assertTrue(left.resource_id.startswith("auto.partition."))
            for right in allocations[left_index + 1 :]:
                self.assertTrue(
                    left.end <= right.offset or right.end <= left.offset
                )
        self.assertFalse(any(issue.severity == "error" for issue in project.validate()))

    def test_first_link_preserves_representative_original_semantics(self) -> None:
        baseline = RomProject.load(TARGET_ROM)
        project = self._configured()

        for unit_id in (1, 4, 5, 0x13, 0x80, 0xFF):
            self.assertEqual(
                project.record_bytes(unit_id),
                baseline.record_bytes(unit_id, original=True),
            )
            self.assertEqual(
                project.unit_display_name(unit_id),
                baseline.unit_display_name(unit_id),
            )
        for map_id in (0, 1, 0x1F, 0x20, 0x63):
            current = project.get_map(map_id)
            original = baseline.get_map(map_id)
            self.assertEqual((current.width, current.height, current.tiles), (original.width, original.height, original.tiles))
        for selector in project.story_text_codec.selectors:
            for index in (0, project.story_text_codec.group_by_selector[selector].count - 1):
                self.assertEqual(
                    project.get_story_text(selector, index).raw,
                    baseline.get_story_text(selector, index).raw,
                )

    def test_linking_after_existing_edits_preserves_all_current_semantics(self) -> None:
        """The first linker must snapshot the edited source, not only the ROM base."""

        project = RomProject.load(TARGET_ROM)
        original_hp = project.get_value(1, "hp")
        project.set_value(1, "hp", 0 if original_hp else original_hp + 1)
        project.set_unit_name_reference(1, 2)
        original_weapons = project.get_unit_weapons(0x25)
        project.set_unit_weapon(
            0x25,
            0,
            1 if original_weapons[0] != 1 else 2,
        )

        map_before = project.get_map(0)
        map_tiles = list(map_before.tiles)
        map_tiles[0] = (map_tiles[0] + 1) & 0x0F
        project.set_map_tiles(
            0,
            map_before.width,
            map_before.height,
            tuple(map_tiles),
        )

        scenario_before = project.get_scenario_layout(4)
        first_enemy = scenario_before.enemies[0]
        changed_enemy = replace(first_enemy, flags=(first_enemy.flags + 1) & 0xFF)
        scenario_changed = replace(
            scenario_before,
            enemies=(changed_enemy,) + scenario_before.enemies[1:],
        )
        project.set_scenario_layout(scenario_changed)

        triggers_changed = (MapTrigger(0, 0, 0xFF, 0x01),)
        project.set_map_triggers(0, triggers_changed)

        expected_hp = project.get_value(1, "hp")
        expected_weapons = project.get_unit_weapons(0x25)
        expected_map = project.get_map(0)
        expected_scenario = project.get_scenario_layout(4)
        expected_triggers = project.get_map_triggers(0)

        project.configure_expansion(304, 48, 112)
        self.assertEqual(project.get_value(1, "hp"), expected_hp)
        self.assertEqual(project.unit_name_source_ids(1), (2,))
        self.assertEqual(project.get_unit_weapons(0x25), expected_weapons)
        self.assertEqual(project.get_map(0).tiles, expected_map.tiles)
        self.assertEqual(
            project.get_scenario_layout(4).enemies[0].flags,
            expected_scenario.enemies[0].flags,
        )
        self.assertEqual(project.get_map_triggers(0), expected_triggers)

        # A later map repack rebuilds dynamic codecs; name reset must still use
        # the immutable post-link identity table rather than relearning aliases.
        linked_map = project.get_map(0)
        project.set_map_tiles(
            0, linked_map.width, linked_map.height, linked_map.tiles
        )
        project.reset_unit_name(1)
        self.assertEqual(project.unit_name_source_ids(1), (1,))

    def test_unit_weapon_editor_targets_the_runtime_configuration_pair(self) -> None:
        project = self._configured(288, 64, 112)
        plan = project.expansion_plan
        assert plan is not None
        runtime_offset = project.unit_weapon_codec.record_offset(0x25)
        stock_offset = project.profile.unit_weapon_table_offset + 0x25 * 2
        self.assertNotEqual(runtime_offset, stock_offset)
        self.assertEqual((runtime_offset - 16) // 0x2000, plan.unit_banks[3])

        stock_before = bytes(project.working[stock_offset : stock_offset + 2])
        current = project.get_unit_weapons(0x25)
        replacement = 1 if current[0] != 1 else 2
        project.set_unit_weapon(0x25, 0, replacement)
        self.assertEqual(project.get_unit_weapons(0x25)[0], replacement)
        self.assertEqual(
            bytes(project.working[stock_offset : stock_offset + 2]), stock_before
        )
        self.assertFalse(any(issue.severity == "error" for issue in project.validate()))

    def test_corrupt_runtime_unit_code_mirror_is_rejected(self) -> None:
        project = self._configured()
        plan = project.expansion_plan
        assert plan is not None
        # $806D is a verified JSR in the mirrored Bank $24/$25 loader.
        offset = 16 + plan.unit_banks[0] * 0x2000 + 0x006D
        self.assertEqual(project.working[offset], 0x20)
        project.working[offset] = 0x00
        errors = [issue for issue in project.validate() if issue.severity == "error"]
        self.assertTrue(
            any("代码镜像" in issue.message and "$806D" in issue.message for issue in errors)
        )

    def test_corrupt_runtime_unit_payload_is_rejected_at_every_quota(self) -> None:
        for map_kib, unit_kib in ((304, 48), (288, 64), (272, 80)):
            project = self._configured(map_kib, unit_kib, 112)
            plan = project.expansion_plan
            assert plan is not None
            body_bank = plan.unit_banks[4]
            pointer_offset = (
                16
                + body_bank * 0x2000
                + PACKED_BODY_TABLE
                - 0x8000
                + 2
            )
            project.working[pointer_offset : pointer_offset + 2] = b"\x00\x00"
            # Reopen the damaged output as its own baseline.  This proves the
            # payload check does not rely on a working-vs-original diff.
            reopened = RomProject(
                Path(f"damaged-unit-{unit_kib}.nes"),
                bytes(project.working),
            )
            errors = [
                issue for issue in reopened.validate() if issue.severity == "error"
            ]
            with self.subTest(unit_kib=unit_kib):
                self.assertTrue(
                    any(
                        issue.module == "机体扩展" and "主体拼图" in issue.message
                        for issue in errors
                    )
                )

    def test_extended_edits_undo_and_redo(self) -> None:
        project = self._configured()

        old_hp = project.get_value(1, "hp")
        new_hp = 0 if old_hp else old_hp + 1
        before = bytes(project.working)
        project.set_value(1, "hp", new_hp)
        after = bytes(project.working)
        self.assertNotEqual(before, after)
        project.undo()
        self.assertEqual(bytes(project.working), before)
        project.redo()
        self.assertEqual(bytes(project.working), after)

        record = project.get_map(0)
        tiles = list(record.tiles)
        tiles[0] = (tiles[0] + 1) & 0x0F
        before = bytes(project.working)
        project.set_map_tiles(0, record.width, record.height, tuple(tiles))
        after = bytes(project.working)
        self.assertEqual(project.get_map(0).tiles[0], tiles[0])
        project.undo()
        self.assertEqual(bytes(project.working), before)
        project.redo()
        self.assertEqual(bytes(project.working), after)

        replacement = self._longer_story(project, 0x32, 0)
        before = bytes(project.working)
        project.set_story_text_raw(0x32, 0, replacement)
        after = bytes(project.working)
        self.assertEqual(project.get_story_text(0x32, 0).raw, replacement)
        self.assertIsNotNone(project.expansion_plan.story_pair_for(0x32))
        project.undo()
        self.assertEqual(bytes(project.working), before)
        project.redo()
        self.assertEqual(bytes(project.working), after)

    def test_project_round_trip_and_direct_output_reopen(self) -> None:
        project = self._configured()
        project.set_value(1, "hp", (project.get_value(1, "hp") + 1) & 0xFFFF)
        project.set_unit_name_reference(1, 2)
        project.set_unit_weapon(0x25, 0, 1)
        record = project.get_map(0)
        tiles = list(record.tiles)
        tiles[0] = (tiles[0] + 1) & 0x0F
        project.set_map_tiles(0, record.width, record.height, tuple(tiles))
        project.set_story_text_raw(0x32, 0, self._longer_story(project, 0x32, 0))

        with tempfile.TemporaryDirectory() as directory:
            directory_path = Path(directory)
            project_path = directory_path / "roundtrip.dcmod"
            project.save_project(project_path)
            reopened = RomProject.load_project(project_path, TARGET_ROM)
            self.assertEqual(bytes(reopened.working), bytes(project.working))
            self.assertEqual(reopened.unit_name_source_ids(1), (2,))
            self.assertEqual(reopened.get_unit_weapons(0x25)[0], 1)
            self.assertFalse(any(issue.severity == "error" for issue in reopened.validate()))

            artifacts = project.build_release(directory_path, "linked")
            direct = RomProject.load(artifacts.rom)
            self.assertEqual(bytes(direct.working), artifacts.rom.read_bytes())
            self.assertEqual(bytes(direct.working), bytes(project.working))
            self.assertFalse(any(issue.severity == "error" for issue in direct.validate()))

            loaded_pointer = direct.get_unit_name_pointer(1, original=True)
            direct.set_unit_name_reference(1, 3)
            direct.reset_unit_name(1)
            self.assertEqual(direct.get_unit_name_pointer(1), loaded_pointer)

            direct_project_path = directory_path / "direct-roundtrip.dcmod"
            direct.save_project(direct_project_path)
            direct_reopened = RomProject.load_project(
                direct_project_path, artifacts.rom
            )
            self.assertEqual(
                bytes(direct_reopened.working), bytes(direct.working)
            )

    def test_build_report_excludes_managed_protected_descriptors(self) -> None:
        project = self._configured()
        with tempfile.TemporaryDirectory() as directory:
            artifacts = project.build_release(directory, "protected-report")
            report = json.loads(artifacts.report.read_text(encoding="utf-8"))
            regions = report["romLayout"]["protectedRegions"]

            self.assertTrue(regions)
            self.assertTrue(
                all(region["unmanagedBytesUnchanged"] for region in regions)
            )
            self.assertTrue(all("unchanged" not in region for region in regions))

            fixed_region = next(
                region for region in regions if region["label"] == "固定程序银行"
            )
            self.assertEqual(fixed_region["banks"], "$7E—$7F")
            fixed_start = 16 + 0x7E * 0x2000
            fixed_end = 16 + 0x80 * 0x2000
            self.assertNotEqual(
                project.original[fixed_start:fixed_end],
                artifacts.rom.read_bytes()[fixed_start:fixed_end],
            )

    def test_generic_allocator_stays_outside_partial_and_full_plans(self) -> None:
        partial = self._configured(16, 48, 16)
        plan = partial.expansion_plan
        assert plan is not None
        allocation = partial.import_expansion_resource(
            "test.unassigned", "测试未分配资源", b"free" * 64
        )
        self.assertIn(allocation.first_bank, plan.unassigned_banks)
        for reserved in partial.expansion_allocations:
            if reserved.resource_id == allocation.resource_id:
                continue
            self.assertTrue(
                allocation.end <= reserved.offset or reserved.end <= allocation.offset
            )

        full = self._configured()
        with self.assertRaisesRegex(ValueError, "没有足够|容量|可用"):
            full.import_expansion_resource("test.none", "无可用区", b"x")

        with self.assertRaisesRegex(ValueError, "auto\\. 前缀"):
            partial.import_expansion_resource(
                "auto.partition.fake", "伪造内部区", b"x"
            )

    def test_direct_partial_output_guards_unregistered_space(self) -> None:
        project = self._configured(16, 48, 16)
        project.import_expansion_resource(
            "manual.before-save", "工程手工资源", b"registered payload"
        )
        with tempfile.TemporaryDirectory() as directory:
            project_path = Path(directory) / "partial.dcmod"
            project.save_project(project_path)
            project_reopened = RomProject.load_project(project_path, TARGET_ROM)
            self.assertGreater(project_reopened.expansion_available, 0)
            self.assertFalse(
                any(
                    allocation.resource_id.startswith("auto.reopen_guard.")
                    for allocation in project_reopened.expansion_allocations
                )
            )

            artifacts = project.build_release(directory, "partial")
            direct = RomProject.load(artifacts.rom)
            guards = tuple(
                allocation
                for allocation in direct.expansion_allocations
                if allocation.resource_id.startswith("auto.reopen_guard.")
            )
            self.assertTrue(guards)
            self.assertEqual(direct.expansion_available, 0)
            with self.assertRaisesRegex(ValueError, "没有足够"):
                direct.import_expansion_resource(
                    "manual.after-reopen", "重开后资源", b"payload"
                )

            direct.reset_all()
            self.assertTrue(
                any(
                    allocation.resource_id.startswith("auto.reopen_guard.")
                    for allocation in direct.expansion_allocations
                )
            )
            self.assertEqual(direct.expansion_available, 0)

    def test_complete_unit_loader_code_is_validated(self) -> None:
        cases = (
            (0, 0x8095, "核心"),
            (2, 0x8458, "战斗配置"),
            (2, 0x94D7, "战斗配置"),
        )
        for bank_index, cpu_address, label in cases:
            with self.subTest(cpu_address=f"${cpu_address:04X}"):
                project = self._configured()
                plan = project.expansion_plan
                assert plan is not None
                offset = (
                    16
                    + plan.unit_banks[bank_index] * 0x2000
                    + cpu_address
                    - 0x8000
                )
                project.working[offset] ^= 0xFF
                errors = tuple(
                    issue
                    for issue in project.validate()
                    if issue.severity == "error"
                )
                self.assertTrue(
                    any(
                        issue.module == "机体扩展"
                        and label in issue.message
                        and f"${cpu_address:04X}" in issue.message
                        for issue in errors
                    )
                )

    def test_rom_and_ips_output_are_blocked_on_validation_error(self) -> None:
        project = self._configured()
        plan = project.expansion_plan
        assert plan is not None
        offset = 16 + plan.unit_banks[0] * 0x2000 + 0x006D
        project.working[offset] = 0
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaisesRegex(ValueError, "完整性检查失败"):
                project.save_as(Path(directory) / "bad.nes")
            with self.assertRaisesRegex(ValueError, "完整性检查失败"):
                project.export_ips(Path(directory) / "bad.ips")

    def test_capacity_overflow_and_story_slot_exhaustion_are_reported(self) -> None:
        project = self._configured(16, 48, 16)
        map_record = project.get_map(0)
        huge_tiles = tuple(index & 0x0F for index in range(32 * 32))
        with self.assertRaisesRegex(ValueError, "地图池至少需要"):
            project.map_resource_replacement_usage(
                0, 32, 32, huge_tiles
            )

        project.set_story_text_raw(0x32, 0, self._longer_story(project, 0x32, 0))
        with self.assertRaisesRegex(ValueError, "剧情配额已用完"):
            project.set_story_text_raw(0x33, 0, self._longer_story(project, 0x33, 0))


if __name__ == "__main__":
    unittest.main(verbosity=2)
