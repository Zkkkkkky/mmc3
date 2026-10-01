from __future__ import annotations

import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

from dc_modifier.app import DEFAULT_ROM
from dc_modifier.database_memory import (
    DatabaseMemoryDialog,
    DatabaseModuleMemoryPanel,
    build_database_memory_report,
    cached_database_memory_report,
)
from dc_modifier.pages import UnitPage
from fc_editor.expansion_unit import (
    LEGACY_UNIT_NAME_GROWTH_BUDGET,
    STANDALONE_UNIT_ATTRIBUTE_RESOURCE_ID,
    STANDALONE_UNIT_NAME_MAGIC,
    STANDALONE_UNIT_NAME_MAGIC_V1,
    STANDALONE_UNIT_NAME_RESOURCE_ID,
    standalone_unit_attribute_bank,
    standalone_unit_name_bank,
    standalone_unit_name_capacity,
)
from fc_editor.constants import INES_HEADER_SIZE, PRG_BANK_SIZE
from fc_rom_editor_core import RomProject, native_unit_name_spill_span
from tests.qt_test_case import QtTestCase


class DatabaseMemoryReportTests(QtTestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.application = QApplication.instance() or QApplication([])
        if not DEFAULT_ROM.is_file():
            raise unittest.SkipTest(f"缺少界面测试ROM：{DEFAULT_ROM}")

    def setUp(self) -> None:
        self.project = RomProject.load(DEFAULT_ROM)

    def test_report_covers_all_database_modules(self) -> None:
        report = build_database_memory_report(self.project)
        self.assertEqual(
            {region.module for region in report.regions},
            {"机体修改", "人物修改", "武器修改", "战斗对话", "其他修改1", "其他修改2"},
        )
        self.assertTrue(all(region.capacity > 0 for region in report.regions))
        self.assertTrue(all(0 <= region.used <= region.capacity for region in report.regions))
        self.assertTrue(all(region.shared_with != "无" for region in report.regions))

    def test_report_survives_scenario_expansion_outside_native_bank24_tail(self) -> None:
        self.project.configure_expansion(288, 64, 112)

        report = build_database_memory_report(self.project)

        self.assertTrue(report.for_module("机体修改").regions)
        self.assertTrue(report.for_module("人物修改").regions)
        self.assertTrue(any(
            region.resource == "普通名称指针表"
            for region in report.for_module("人物修改").regions
        ))

    def test_complete_report_is_reused_until_project_revision_changes(self) -> None:
        with patch(
            "dc_modifier.database_memory.build_database_memory_report",
            wraps=build_database_memory_report,
        ) as build:
            first = cached_database_memory_report(self.project)
            second = cached_database_memory_report(self.project)
            self.assertIs(first, second)
            self.assertEqual(build.call_count, 1)

            self.project.invalidate_derived_caches()
            third = cached_database_memory_report(self.project)
            self.assertIsNot(third, first)
            self.assertEqual(build.call_count, 2)

    def test_fast_rom_diff_preserves_exact_runs_across_block_edges(self) -> None:
        before = bytes(9000)
        changed = bytearray(before)
        changed[4094:4098] = b"ABCD"
        changed[7000] = 0x7F

        patches = RomProject._diff_patches(before, bytes(changed))

        self.assertEqual(
            [(patch.offset, patch.before, patch.after) for patch in patches],
            [
                (4094, b"\x00\x00\x00\x00", b"ABCD"),
                (7000, b"\x00", b"\x7f"),
            ],
        )

    def test_unit_name_report_does_not_attribute_current_aliases_to_legacy_editor(self) -> None:
        report = build_database_memory_report(self.project)
        pointer_table = next(
            region for region in report.regions
            if region.module == "机体修改" and region.resource == "机体名称指针表"
        )
        self.assertIn("当前ROM含重复名称指针", pointer_table.shared_with)
        self.assertIn("不代表旧修改器采用共用名称规则", pointer_table.note)

    def test_shared_unit_attribute_edit_detaches_only_target_id(self) -> None:
        before = bytes(self.project.working)
        allocations_before = self.project.expansion_allocations
        shared_ids = next(
            ids for ids in self.project.unit_codec.ids_by_pointer.values()
            if len(ids) > 1
        )
        target_id, other_id = shared_ids[:2]
        old_target = self.project.get_value(target_id, "movement")
        old_other = self.project.get_value(other_id, "movement")
        new_value = old_target + 1 if old_target < 0xFF else old_target - 1

        self.project.set_value(target_id, "movement", new_value)

        self.assertEqual(self.project.get_value(target_id, "movement"), new_value)
        self.assertEqual(self.project.get_value(other_id, "movement"), old_other)
        self.assertEqual(
            self.project.unit_codec.decode_record(
                target_id, bytes(self.project.working)
            ).ids,
            (target_id,),
        )
        self.assertIsNone(standalone_unit_attribute_bank(self.project.working))
        self.assertFalse(any(
            allocation.resource_id == STANDALONE_UNIT_ATTRIBUTE_RESOURCE_ID
            for allocation in self.project.expansion_allocations
        ))
        self.assertFalse(any(
            issue.severity == "error" for issue in self.project.validate()
        ))

        reopened = RomProject(self.project.path, bytes(self.project.working))
        self.assertEqual(reopened.get_value(target_id, "movement"), new_value)
        self.assertEqual(reopened.get_value(other_id, "movement"), old_other)
        with tempfile.TemporaryDirectory() as directory:
            project_path = Path(directory) / "unit-attribute-cow.dcmod"
            self.project.save_project(project_path)
            project_reopened = RomProject.load_project(project_path, DEFAULT_ROM)
            self.assertEqual(
                project_reopened.get_value(target_id, "movement"), new_value
            )
            self.assertEqual(
                project_reopened.get_value(other_id, "movement"), old_other
            )
        self.project.undo()
        self.assertEqual(bytes(self.project.working), before)
        self.assertEqual(self.project.expansion_allocations, allocations_before)

    def test_unchanged_unit_name_reference_does_not_install_expansion(self) -> None:
        before = bytes(self.project.working)
        unit_id = 1
        source_id = self.project.unit_name_source_ids(unit_id)[0]

        self.project.set_unit_name_reference(unit_id, source_id)

        self.assertEqual(bytes(self.project.working), before)
        self.assertIsNone(standalone_unit_name_bank(self.project.working))
        self.assertFalse(self.project.expansion_allocations)

    def test_changed_unit_name_reference_stays_in_native_pointer_table(self) -> None:
        unit_id = 1
        source_id = next(
            candidate
            for candidate in range(2, self.project.unit_count)
            if self.project.get_unit_name_pointer(candidate)
            != self.project.get_unit_name_pointer(unit_id)
        )
        expected_name = self.project.unit_display_name(source_id)

        self.project.set_unit_name_reference(unit_id, source_id)

        self.assertEqual(self.project.unit_display_name(unit_id), expected_name)
        self.assertIsNone(standalone_unit_name_bank(self.project.working))
        self.assertFalse(self.project.expansion_allocations)
        self.assertFalse(any(
            issue.severity == "error" for issue in self.project.validate()
        ))

    def test_standalone_unit_attributes_migrate_into_full_unit_plan(self) -> None:
        shared_ids = next(
            ids for ids in self.project.unit_codec.ids_by_pointer.values()
            if len(ids) > 1
        )
        target_id, other_id = shared_ids[:2]
        old_target = self.project.get_value(target_id, "movement")
        old_other = self.project.get_value(other_id, "movement")
        new_value = old_target + 1 if old_target < 0xFF else old_target - 1
        self.project.set_value(target_id, "movement", new_value)

        self.project.configure_expansion(304, 48, 112)

        self.assertIsNone(standalone_unit_attribute_bank(self.project.working))
        self.assertEqual(self.project.get_value(target_id, "movement"), new_value)
        self.assertEqual(self.project.get_value(other_id, "movement"), old_other)
        self.assertFalse(any(
            issue.severity == "error" for issue in self.project.validate()
        ))

    def test_stock_unit_name_report_preserves_legacy_growth_budget(self) -> None:
        report = build_database_memory_report(self.project)
        unit_names = next(
            region for region in report.regions
            if region.module == "机体修改" and region.resource == "机体名称"
        )
        self.assertEqual(unit_names.used, 1456)
        self.assertEqual(unit_names.capacity, 8157)
        self.assertEqual(unit_names.remaining, LEGACY_UNIT_NAME_GROWTH_BUDGET)
        self.assertIn("按旧修改器保留 6701 B", unit_names.shared_with)

    def test_shared_pools_are_counted_once_in_summary(self) -> None:
        report = build_database_memory_report(self.project)
        keys = [region.pool_key for region in report.repackable_regions]
        self.assertEqual(len(keys), len(set(keys)))
        self.assertEqual(report.pool_capacity, sum(region.capacity for region in report.repackable_regions))
        self.assertEqual(report.pool_remaining, report.pool_capacity - report.pool_used)

    def test_known_text_pool_boundaries_and_usage(self) -> None:
        report = build_database_memory_report(self.project)
        by_key = {region.pool_key: region for region in report.repackable_regions}
        self.assertEqual((by_key["system-text"].capacity, by_key["system-text"].remaining), (1758, 249))
        self.assertEqual((by_key["battle-text-2a"].capacity, by_key["battle-text-2a"].remaining), (5432, 0))
        self.assertEqual((by_key["battle-text-0e"].capacity, by_key["battle-text-0e"].remaining), (6294, 0))

    def test_portrait_capacity_is_reported_as_shared_dynamic_tail(self) -> None:
        report = build_database_memory_report(self.project)
        tail = next(
            region for region in report.regions
            if region.resource == "头像配置＋机体战斗外观共享尾区"
        )

        self.assertEqual((tail.used, tail.capacity, tail.remaining), (2194, 2992, 798))
        self.assertEqual(tail.kind, "可重排共享尾区")
        self.assertEqual(tail.pool_key, "portrait-unit-configuration-tail")
        self.assertIn("头像当前 71 条唯一记录、497 B", tail.shared_with)
        self.assertIn("同步后移机体战斗外观", tail.note)

    def test_character_memory_reports_writable_bank24_composite(self) -> None:
        report = build_database_memory_report(self.project).for_module("人物修改")
        by_key = {
            region.pool_key: region
            for region in report.regions
            if region.pool_key is not None
        }
        bank24 = by_key["bank24-eight-resource-composite"]

        self.assertEqual((bank24.used, bank24.capacity, bank24.remaining), (9529, 15184, 5655))
        self.assertFalse(bank24.is_observed_pool)
        self.assertTrue(bank24.is_repackable)
        self.assertIn("32关初始配置", bank24.shared_with)
        self.assertIn("人物普通名、战斗名与人物属性保存均已接通", bank24.note)
        self.assertIn(bank24, report.repackable_regions)
        self.assertNotIn("character-names-current-gate", by_key)
        self.assertNotIn("character-attributes-current-gate", by_key)

    def test_dialog_filters_without_rebuilding_database_pages(self) -> None:
        dialog = DatabaseMemoryDialog(self.project)
        try:
            self.assertEqual(dialog.table.rowCount(), len(dialog.report.regions))
            dialog.module_filter.setCurrentText("人物修改")
            self.application.processEvents()
            self.assertGreater(dialog.table.rowCount(), 0)
            self.assertTrue(
                all(dialog.table.item(row, 0).text() == "人物修改" for row in range(dialog.table.rowCount()))
            )
        finally:
            dialog.deleteLater()
            self.application.processEvents()

    def test_shared_unit_name_growth_uses_isolated_expansion_after_native_pool(self) -> None:
        original_09 = self.project.unit_display_name(0x09)
        original_0a = self.project.unit_display_name(0x0A)
        self.assertEqual(original_09, original_0a)
        before = bytes(self.project.working)

        self.project.set_unit_name_text(0x09, original_09 + "R")

        self.assertEqual(self.project.unit_display_name(0x09), original_09 + "R")
        self.assertEqual(self.project.unit_display_name(0x0A), original_0a)
        self.assertEqual(self.project.unit_name_source_ids(0x09), (0x09,))
        self.assertEqual(self.project.unit_name_source_ids(0x0A), (0x0A,))
        self.assertIsNotNone(standalone_unit_name_bank(self.project.working))
        self.assertIsNone(
            native_unit_name_spill_span(self.project.rom_image, self.project.working)
        )
        self.assertIn(
            STANDALONE_UNIT_NAME_RESOURCE_ID,
            {item.resource_id for item in self.project.expansion_allocations},
        )
        self.assertFalse(
            any(issue.severity == "error" for issue in self.project.validate())
        )

        self.project.undo()
        self.assertEqual(bytes(self.project.working), before)
        self.assertNotIn(
            STANDALONE_UNIT_NAME_RESOURCE_ID,
            {item.resource_id for item in self.project.expansion_allocations},
        )

    def test_unit_page_detaches_shared_name_without_confirmation(self) -> None:
        page = UnitPage()
        try:
            page.set_project(self.project)
            self.assertTrue(page.select_record_id(0x09))
            original_09 = self.project.unit_display_name(0x09)
            original_0a = self.project.unit_display_name(0x0A)
            self.assertEqual(original_09, original_0a)
            page.name_text.setText(original_09 + "R")
            with patch("dc_modifier.pages.QMessageBox.question") as prompt, patch.object(
                page, "show_error"
            ) as error:
                page.apply_record()
            prompt.assert_not_called()
            error.assert_not_called()
            self.assertEqual(self.project.unit_display_name(0x09), original_09 + "R")
            self.assertEqual(self.project.unit_display_name(0x0A), original_0a)
            self.assertEqual(self.project.unit_name_source_ids(0x09), (0x09,))
            self.assertEqual(self.project.unit_name_source_ids(0x0A), (0x0A,))
        finally:
            page.deleteLater()
            self.application.processEvents()

    def test_standalone_unit_name_pool_survives_direct_reopen(self) -> None:
        original = self.project.unit_display_name(0x09)
        self.project.set_unit_name_text(0x09, original + "R")

        reopened = RomProject(DEFAULT_ROM, bytes(self.project.working))
        self.assertEqual(reopened.unit_display_name(0x09), original + "R")
        self.assertEqual(reopened.unit_display_name(0x0A), original)
        reopened.set_unit_name_text(0x0A, original + "S")
        self.assertEqual(reopened.unit_display_name(0x09), original + "R")
        self.assertEqual(reopened.unit_display_name(0x0A), original + "S")
        self.assertFalse(any(issue.severity == "error" for issue in reopened.validate()))

    def test_legacy_native_spill_migrates_on_next_name_edit(self) -> None:
        original_09 = self.project.unit_display_name(0x09)
        original_0a = self.project.unit_display_name(0x0A)
        patches = self.project._native_unit_name_repack_patches(
            0x09, original_09 + "R"
        )
        self.assertIsNotNone(patches)
        assert patches is not None
        self.project._apply_unit_name_patches(patches)
        self.project._refresh_dynamic_codecs()
        self.assertIsNotNone(
            native_unit_name_spill_span(self.project.rom_image, self.project.working)
        )

        self.project.set_unit_name_text(0x0A, original_0a + "S")

        self.assertEqual(self.project.unit_display_name(0x09), original_09 + "R")
        self.assertEqual(self.project.unit_display_name(0x0A), original_0a + "S")
        self.assertIsNotNone(standalone_unit_name_bank(self.project.working))
        self.assertIsNone(
            native_unit_name_spill_span(self.project.rom_image, self.project.working)
        )
        self.assertFalse(any(issue.severity == "error" for issue in self.project.validate()))

    def test_unit_name_edit_keeps_scenario_capacity_unchanged(self) -> None:
        original_09 = self.project.unit_display_name(0x09)
        original_0a = self.project.unit_display_name(0x0A)
        stock_scenario_capacity = self.project.scenario_layout_codec.pool_capacity
        self.project.set_unit_name_text(0x09, original_09 + "R")
        self.assertEqual(
            self.project.scenario_layout_codec.pool_capacity,
            stock_scenario_capacity,
        )

        self.project.configure_expansion(304, 48, 112)

        self.assertEqual(self.project.unit_display_name(0x09), original_09 + "R")
        self.assertEqual(self.project.unit_display_name(0x0A), original_0a)
        self.assertFalse(any(issue.severity == "error" for issue in self.project.validate()))

    def test_memory_report_uses_expanded_unit_name_capacity(self) -> None:
        original = self.project.unit_display_name(0x09)
        self.project.set_unit_name_text(0x09, original + "R")
        report = build_database_memory_report(self.project)
        unit_names = next(
            region for region in report.regions
            if region.module == "机体修改" and region.resource == "机体名称"
        )
        self.assertEqual(unit_names.remaining, LEGACY_UNIT_NAME_GROWTH_BUDGET - 1)
        self.assertIn("独立扩展池", unit_names.shared_with)

        saved = bytes(self.project.working)
        reopened = RomProject(self.project.path, saved)
        reopened_names = next(
            region for region in build_database_memory_report(reopened).regions
            if region.module == "机体修改" and region.resource == "机体名称"
        )
        self.assertEqual(reopened_names.capacity, unit_names.capacity)
        self.assertEqual(
            reopened_names.remaining,
            LEGACY_UNIT_NAME_GROWTH_BUDGET - 1,
        )

    def test_v1_standalone_unit_name_pool_remains_readable(self) -> None:
        original = self.project.unit_display_name(0x09)
        self.project.set_unit_name_text(0x09, original + "R")
        bank = standalone_unit_name_bank(self.project.working)
        self.assertIsNotNone(bank)
        assert bank is not None
        image_offset = INES_HEADER_SIZE + bank * PRG_BANK_SIZE
        self.assertEqual(
            bytes(self.project.working[image_offset : image_offset + 8]),
            STANDALONE_UNIT_NAME_MAGIC,
        )
        self.project.working[image_offset : image_offset + 8] = (
            STANDALONE_UNIT_NAME_MAGIC_V1
        )

        reopened = RomProject(self.project.path, bytes(self.project.working))

        self.assertEqual(reopened.unit_display_name(0x09), original + "R")
        self.assertEqual(
            standalone_unit_name_capacity(reopened.working),
            0xC000 - 0x8410,
        )

    def test_fixed_regions_are_reported_as_editable_not_out_of_memory(self) -> None:
        report = build_database_memory_report(self.project)
        fixed = tuple(region for region in report.regions if region.pool_key is None)
        self.assertTrue(fixed)
        self.assertTrue(all("可改" in region.kind for region in fixed))
        dialog = DatabaseMemoryDialog(self.project)
        try:
            fixed_rows = [
                row
                for row in range(dialog.table.rowCount())
                if "固定" in dialog.table.item(row, 3).text()
            ]
            self.assertTrue(fixed_rows)
            self.assertTrue(
                all(dialog.table.item(row, 7).text() == "可改值" for row in fixed_rows)
            )
        finally:
            dialog.deleteLater()
            self.application.processEvents()

    def test_unit_composition_reports_native_shared_pool(self) -> None:
        report = build_database_memory_report(self.project)
        pool = next(
            region
            for region in report.regions
            if region.module == "机体修改"
            and region.resource == "主体＋碎片拼图脚本"
        )
        self.assertEqual((pool.used, pool.capacity, pool.remaining), (7148, 15344, 8196))
        self.assertEqual(pool.pool_key, "unit-composition-shared")
        self.assertIn("主体与碎片", pool.shared_with)
        self.assertIn("不与机体名称", pool.shared_with)

    def test_module_panel_never_combines_unrelated_pool_capacity(self) -> None:
        panel = DatabaseModuleMemoryPanel(self.project, "人物修改")
        try:
            report = build_database_memory_report(self.project).for_module("人物修改")
            for region in report.repackable_regions:
                self.assertIn(region.resource, panel.summary.toolTip())
            self.assertNotIn("总剩余", panel.summary.text())
            self.assertIn("共享余量 5,655 B", panel.summary.text())
            self.assertIn("人物名称与属性已接通", panel.summary.text())
            self.assertNotIn("当前写入门禁", panel.summary.text())
        finally:
            panel.deleteLater()
            self.application.processEvents()

    def test_module_dialog_contains_only_its_own_regions(self) -> None:
        dialog = DatabaseMemoryDialog(self.project, module="武器修改")
        try:
            self.assertGreater(dialog.table.rowCount(), 0)
            self.assertTrue(
                all(
                    dialog.table.item(row, 0).text() == "武器修改"
                    for row in range(dialog.table.rowCount())
                )
            )
            self.assertFalse(dialog.module_filter.isEnabled())
        finally:
            dialog.deleteLater()
            self.application.processEvents()

    def test_unit_name_copy_on_write_does_not_change_scenario_pool(self) -> None:
        before = bytes(self.project.working)
        scenario_start = self.project.scenario_layout_codec.pool_offset
        scenario_end = scenario_start + self.project.scenario_layout_codec.pool_capacity
        scenario_before = before[scenario_start:scenario_end]
        original = self.project.unit_display_name(0x09)
        self.project.set_unit_name_text(0x09, original + "R")
        after = bytes(self.project.working)
        changed = {index for index, pair in enumerate(zip(before, after)) if pair[0] != pair[1]}
        self.assertTrue(changed)
        self.assertEqual(after[scenario_start:scenario_end], scenario_before)
        self.assertIsNotNone(standalone_unit_name_bank(self.project.working))
        self.assertIsNone(native_unit_name_spill_span(self.project.rom_image, self.project.working))
        self.assertFalse(any(issue.severity == "error" for issue in self.project.validate()))

if __name__ == "__main__":
    unittest.main()
