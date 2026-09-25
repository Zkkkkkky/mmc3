from __future__ import annotations

import os
from pathlib import Path
import unittest
from tempfile import TemporaryDirectory

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication, QDialogButtonBox

from dc_modifier.legacy_text_pages import (
    GrowthHexDialog,
    LegacyGrowthPage,
    LegacyScenarioEventsPage,
    LegacyShopPage,
    LegacyTextPage,
)
from fc_editor.codecs.legacy_scenario import LegacyScenarioCodec
from fc_editor.codecs.legacy_text import LegacyTextCodec
from fc_editor.codecs.legacy_text_growth import LegacyGrowthCodec
from fc_editor.codecs.legacy_text_shop import LegacyShopCodec
from fc_rom_editor_core import RomProject
from tests.qt_test_case import QtTestCase

ROOT = Path(__file__).resolve().parents[1]
ROM = ROOT / "output/rom/DC_kuorong_464K.nes"


class LegacyTextScenarioCodecTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.data = ROM.read_bytes()

    def test_all_1258_text_variants_roundtrip_preserving_aliases_and_control_operands(self) -> None:
        codec = LegacyTextCodec(self.data)
        count = 0
        for group in codec.groups:
            for index in range(group.count):
                for variant in range(codec.variant_count(group.key, index)):
                    record = codec.record(group.key, index, variant)
                    offset, before, after = codec.replacement_patch(group.key, index, variant, record.text)
                    self.assertEqual(before, after)
                    self.assertEqual(self.data[offset:offset + len(after)], after)
                    count += 1
        self.assertEqual(count, 1258)

    def test_battle_screenshot_first_record_resolves_six_random_variants(self) -> None:
        codec = LegacyTextCodec(self.data)
        self.assertEqual(codec.variant_count("battle_00", 0), 6)
        record = codec.record("battle_00", 0)
        self.assertEqual(record.file_offset, 0x54020)
        self.assertIn("嘿嘿！小毛贼！往哪", record.text)
        self.assertIn("投靠我们联邦不好吗", codec.record("battle_00", 0, 5).text)

    def test_battle_group_boundaries_roundtrip_in_original_capacity(self) -> None:
        codec = LegacyTextCodec(self.data)
        for key, last_index in (
            ("battle_00", 255),
            ("battle_01", 15),
            ("battle_04", 255),
            ("battle_05", 63),
        ):
            for variant in range(codec.variant_count(key, last_index)):
                record = codec.record(key, last_index, variant)
                offset, before, after = codec.replacement_patch(
                    key, last_index, variant, record.text
                )
                self.assertEqual(before, after)
                self.assertEqual(
                    self.data[offset : offset + len(before)],
                    before,
                    (key, last_index, variant),
                )

    @staticmethod
    def _apply_patches(data: bytes, patches) -> bytes:
        result = bytearray(data)
        for offset, before, after in patches:
            if bytes(result[offset : offset + len(before)]) != before:
                raise AssertionError(f"stale patch at {offset:#x}")
            result[offset : offset + len(after)] = after
        return bytes(result)

    @staticmethod
    def _battle_alias_signature(codec: LegacyTextCodec, keys: tuple[str, ...]):
        aliases: dict[int, list[tuple[str, int, int]]] = {}
        for key in keys:
            group = codec.group_by_key[key]
            for index in range(group.count):
                for variant in range(codec.variant_count(key, index)):
                    record = codec.record(key, index, variant)
                    aliases.setdefault(record.pointer, []).append(
                        (key, index, variant)
                    )
        return tuple(sorted(tuple(values) for values in aliases.values()))

    def test_battle_2a_pool_repack_reuses_shortened_bytes_and_preserves_aliases(self) -> None:
        codec = LegacyTextCodec(self.data)
        shorter_id = ("battle_00", 0, 0)
        longer_id = ("battle_00", 0, 1)
        shorter = codec.record(*shorter_id).text.replace("小毛贼", "贼")
        longer = codec.record(*longer_id).text.replace(
            "你们", "你们你们", 1
        )
        before_records = {
            (key, index, variant): codec.record(key, index, variant).raw
            for key in ("battle_00", "battle_01")
            for index in range(codec.group_by_key[key].count)
            for variant in range(codec.variant_count(key, index))
        }
        before_aliases = self._battle_alias_signature(
            codec, ("battle_00", "battle_01")
        )
        usage = codec.battle_usage(
            0x2A, {shorter_id: shorter, longer_id: longer}
        )
        self.assertEqual((usage.used, usage.capacity, usage.free), (5432, 5432, 0))

        patches = codec.battle_repack_patches(
            {shorter_id: shorter, longer_id: longer}
        )
        self.assertGreaterEqual(len(patches), 2)
        self.assertLess(
            sum(
                sum(left != right for left, right in zip(before, after))
                for _offset, before, after in patches
            ),
            100,
        )
        repacked_data = self._apply_patches(self.data, patches)
        repacked = LegacyTextCodec(repacked_data)
        self.assertEqual(repacked.record(*shorter_id).text, shorter)
        self.assertEqual(repacked.record(*longer_id).text, longer)
        self.assertNotEqual(
            repacked.record(*longer_id).pointer,
            codec.record(*longer_id).pointer,
        )
        for identity, raw in before_records.items():
            if identity not in (shorter_id, longer_id):
                self.assertEqual(repacked.record(*identity).raw, raw, identity)
        self.assertEqual(
            self._battle_alias_signature(
                repacked, ("battle_00", "battle_01")
            ),
            before_aliases,
        )
        system_start = LegacyTextCodec.offset(0x2A, 0x9768)
        system_end = LegacyTextCodec.offset(0x2A, 0xA000)
        self.assertEqual(
            repacked_data[system_start:system_end],
            self.data[system_start:system_end],
        )
        self.assertEqual(
            repacked.battle_repack_patches(
                {shorter_id: shorter, longer_id: longer}
            ),
            (),
        )

    def test_battle_repack_survives_reopen_and_preserves_0e_non_text_gaps(self) -> None:
        codec = LegacyTextCodec(self.data)
        shorter_id = ("battle_04", 0, 0)
        longer_id = ("battle_04", 0, 1)
        shorter = codec.record(*shorter_id).text.replace("小毛贼", "贼")
        first = self._apply_patches(
            self.data,
            codec.battle_repack_patches({shorter_id: shorter}),
        )
        reopened = LegacyTextCodec(first)
        self.assertEqual(reopened.battle_usage(0x0E).free, 4)
        longer = reopened.record(*longer_id).text.replace(
            "敌人", "敌人敌人", 1
        )
        second = self._apply_patches(
            first,
            reopened.battle_repack_patches({longer_id: longer}),
        )
        final = LegacyTextCodec(second)
        self.assertEqual(final.record(*shorter_id).text, shorter)
        self.assertEqual(final.record(*longer_id).text, longer)
        self.assertEqual(final.battle_usage(0x0E).free, 0)
        for start, end in ((0x97E4, 0x97FB), (0x9B3D, 0x9E28)):
            offset = LegacyTextCodec.offset(0x0E, start)
            size = end - start
            self.assertEqual(second[offset : offset + size], self.data[offset : offset + size])

    def test_battle_repack_rejects_total_capacity_overflow_atomically(self) -> None:
        codec = LegacyTextCodec(self.data)
        identity = ("battle_00", 0, 0)
        longer = codec.record(*identity).text.replace("嘿嘿", "嘿嘿嘿", 1)
        usage = codec.battle_usage(0x2A, {identity: longer})
        self.assertEqual(usage.used - usage.capacity, 2)
        with self.assertRaisesRegex(ValueError, r"超出 2 字节.*缩短"):
            codec.battle_repack_patches({identity: longer})

    def test_battle_repack_rejects_divergent_drafts_for_shared_text(self) -> None:
        codec = LegacyTextCodec(self.data)
        key = "battle_00"
        record = next(
            codec.record(key, index, variant)
            for index in range(codec.group_by_key[key].count)
            for variant in range(codec.variant_count(key, index))
            if len(codec.record(key, index, variant).shared_by) >= 2
        )
        first, second = record.shared_by[:2]
        changed = record.text.replace("⟦结束⟧", "我⟦结束⟧")
        with self.assertRaisesRegex(ValueError, "不同草稿"):
            codec.battle_repack_patches(
                {
                    (key, first[0], first[1]): record.text,
                    (key, second[0], second[1]): changed,
                }
            )

    def test_system_ff_operands_are_preserved_and_not_record_terminators(self) -> None:
        codec = LegacyTextCodec(self.data)
        record = codec.record("system", 2)
        self.assertEqual(len(record.raw), 44)
        self.assertEqual(record.text.count("<FCFFFF>"), 5)
        offset, before, after = codec.replacement_patch("system", 2, 0, record.text.replace("水平", "精神"))
        self.assertEqual(offset, 0x55945)
        self.assertEqual(len(before), len(after))
        self.assertEqual(after.count(bytes.fromhex("FC FF FF")), 5)
        with self.assertRaisesRegex(ValueError, "控制码"):
            codec.replacement_patch("system", 2, 0, record.text.replace("<FCFFFF>", "", 1))

    def test_system_shared_pool_allows_growth_and_preserves_aliases(self) -> None:
        codec = LegacyTextCodec(self.data)
        identity = ("system", 2, 0)
        record = codec.record(*identity)
        replacement = record.text.replace("⟦结束⟧", "机⟦结束⟧")
        usage = codec.simple_group_usage("system", {identity: replacement})
        self.assertGreater(usage.free, 0)
        patches = codec.simple_group_repack_patches(
            "system", {identity: replacement}
        )
        repacked_data = self._apply_patches(self.data, patches)
        reopened = LegacyTextCodec(repacked_data)
        self.assertEqual(reopened.record(*identity).text, replacement)
        self.assertEqual(
            reopened.record(*identity).shared_by,
            record.shared_by,
        )

    def test_item_description_pool_balances_shrink_and_growth(self) -> None:
        codec = LegacyTextCodec(self.data)
        shorter_id = ("item_description", 0, 0)
        longer_id = ("item_description", 1, 0)
        shorter = codec.record(*shorter_id).text.replace("防御力增加1点", "防御")
        longer = codec.record(*longer_id).text.replace("速度", "反应速度")
        usage = codec.simple_group_usage(
            "item_description",
            {shorter_id: shorter, longer_id: longer},
        )
        self.assertLessEqual(usage.used, usage.capacity)
        patches = codec.simple_group_repack_patches(
            "item_description",
            {shorter_id: shorter, longer_id: longer},
        )
        reopened = LegacyTextCodec(self._apply_patches(self.data, patches))
        self.assertEqual(reopened.record(*shorter_id).text, shorter)
        self.assertEqual(reopened.record(*longer_id).text, longer)

        with self.assertRaisesRegex(ValueError, "共享池容量不足"):
            codec.simple_group_repack_patches(
                "item_description",
                {longer_id: longer},
            )

    def test_item_descriptions_match_source_and_preserve_shared_empty_slots(self) -> None:
        codec = LegacyTextCodec(self.data)
        self.assertIn("防御力增加1点", codec.record("item_description", 0).text)
        self.assertEqual(codec.record("item_description", 0).file_offset, 0x170EE)
        self.assertEqual(codec.record("item_description", 20).shared_by, ((20, 0), (21, 0), (22, 0), (23, 0)))
        with self.assertRaisesRegex(ValueError, "容量"):
            codec.replacement_patch("item_description", 20, 0, "机⟦结束⟧")

    def test_damaged_pointer_or_random_count_is_rejected(self) -> None:
        for offset, value in ((0x54010, 0), (0x55243, 0), (0x55042, 0)):
            data = bytearray(self.data)
            data[offset] = value
            with self.assertRaises(ValueError):
                LegacyTextCodec(data)

    def test_scenario_banks_and_complete_first_chapter_match_screenshot(self) -> None:
        codec = LegacyScenarioCodec(self.data)
        opening = codec.instructions(0, 0)
        self.assertEqual(opening[0].file_offset, 0x3C010)
        self.assertEqual(opening[0].raw, bytes.fromhex("59 88"))
        self.assertEqual(opening[1].raw, bytes.fromhex("5A 87"))
        self.assertEqual(opening[7].raw, bytes.fromhex("5C 15 74 00 80"))
        self.assertGreater(len(opening), 100)
        self.assertEqual(codec.instructions(0, 1)[0].raw, b"\xDF")
        self.assertEqual(codec.instructions(0, 2)[0].file_offset, 0x36010)
        self.assertEqual(codec.instructions(10, 2)[0].file_offset, 0x3E010)
        self.assertEqual(sum(len(codec.instructions(ch, phase)) for ch in range(32) for phase in range(3)), 4274)

    def test_event_patch_stays_in_actual_bank_and_validates_size(self) -> None:
        codec = LegacyScenarioCodec(self.data)
        item = codec.instructions(0, 0)[0]
        offset, before, after = codec.replacement_patch(item, bytes.fromhex("59 87"))
        self.assertEqual((offset, before, after), (0x3C010, b"\x59\x88", b"\x59\x87"))
        with self.assertRaises(ValueError):
            codec.replacement_patch(item, b"")
        data = bytearray(self.data)
        data[0x355B1] = 0x1B
        with self.assertRaisesRegex(ValueError, "调度"):
            LegacyScenarioCodec(data)

    def test_scenario_structural_edit_relocates_pointers_and_jumps_and_reopens(self) -> None:
        codec = LegacyScenarioCodec(self.data)
        selected = codec.instructions(0, 0)[0]
        jump = next(
            item
            for chapter in range(32)
            for item in codec.instructions(chapter, 0)
            if item.opcode in codec.JUMP_OPCODES
            and int.from_bytes(item.raw[1:3], "little") > selected.address
        )
        old_target = int.from_bytes(jump.raw[1:3], "little")
        shrunk = self._apply_patches(
            self.data, codec.replacement_patches(selected, b"\xDF")
        )
        reopened = LegacyScenarioCodec(shrunk)
        self.assertEqual(reopened.instructions(0, 0)[0].raw, b"\xDF")
        moved_jump = next(
            item
            for chapter in range(32)
            for item in reopened.instructions(chapter, 0)
            if item.address == jump.address - 1
        )
        self.assertEqual(
            int.from_bytes(moved_jump.raw[1:3], "little"), old_target - 1
        )

        restored = self._apply_patches(
            shrunk,
            reopened.replacement_patches(
                reopened.instructions(0, 0)[0], selected.raw
            ),
        )
        self.assertEqual(restored, self.data)

    def test_scenario_structural_edit_rejects_overlapping_branch_view(self) -> None:
        codec = LegacyScenarioCodec(self.data)
        selected = next(
            item
            for item in codec.instructions(9, 2)
            if item.address == 0xBE9A
        )
        with self.assertRaisesRegex(ValueError, "同时属于.*分支解释"):
            codec.replacement_patches(selected, b"\xDF")

    def test_growth_reader_nibble_order_shared_records_and_last_padding(self) -> None:
        codec = LegacyGrowthCodec(self.data)
        self.assertEqual(codec.verified_level_cap, 99)
        self.assertEqual(codec.LEVEL_CAPACITY, 99)
        for growth_id in range(201, 254):
            record = codec.record(growth_id)
            self.assertEqual(codec.replacement_patch(growth_id, record.values)[1:], (record.raw, record.raw))
        record = codec.record(201)
        self.assertEqual(record.values[:6], (1, 2, 1, 2, 1, 2))
        self.assertEqual(record.file_offset, 0xA78A)
        values = list(record.values)
        values[1] = 7
        patch = codec.replacement_patch(201, values)
        self.assertEqual(patch[2][0], 0x17)
        self.assertEqual(patch[2][-1] & 15, record.raw[-1] & 15)
        self.assertEqual(codec.record(214).shared_ids, tuple(range(214, 254)))
        with self.assertRaises(ValueError):
            codec.replacement_patch(201, [16] * 99)

    def test_growth_reader_rejects_runtime_cap_that_does_not_match_records(self) -> None:
        data = bytearray(self.data)
        data[LegacyGrowthCodec.LEVEL_CAP_COMPARE_OFFSET + 1] = 0x3B
        codec = LegacyGrowthCodec(data)

        with self.assertRaisesRegex(ValueError, "运行时等级上限60.*容量99"):
            _ = codec.verified_level_cap

    def test_shop_metadata_matches_screenshot_and_unused_pointers_cannot_write(self) -> None:
        codec = LegacyShopCodec(self.data)
        record = codec.record(0xF0)
        self.assertEqual((record.clerk_id, record.dialogue_id, record.items), (2, 48, (13, 5, 15, 16)))
        self.assertEqual(record.file_offset, 0x15773)
        offset, before, after = codec.replacement_patch(0xF0, 2, 48, (12, 5, 15, 16))
        self.assertEqual(after[:4], before[:4])
        self.assertEqual(after[4], 11)
        self.assertEqual(after[5:], before[5:])
        self.assertEqual(len(codec.record(0xF4).items), 1)
        with self.assertRaises(ValueError):
            codec.replacement_patch(0xF4, 190, 203, (1, 2, 3, 4))
        for shop_id in range(0xF5, 0xFF):
            with self.assertRaisesRegex(ValueError, "地图事件"):
                codec.record(shop_id)

    def test_all_m10_text_and_shop_records_roundtrip_without_hidden_changes(self) -> None:
        text_codec = LegacyTextCodec(self.data)
        for index in range(24):
            for variant in range(text_codec.variant_count("item_description", index)):
                record = text_codec.record("item_description", index, variant)
                offset, before, after = text_codec.replacement_patch(
                    "item_description", index, variant, record.text
                )
                self.assertEqual(before, after, (index, variant))
                self.assertEqual(self.data[offset : offset + len(before)], before)

        shop_codec = LegacyShopCodec(self.data)
        for shop_id in range(0xF0, 0xF5):
            record = shop_codec.record(shop_id)
            offset, before, after = shop_codec.replacement_patch(
                shop_id,
                record.clerk_id,
                record.dialogue_id,
                record.items,
            )
            self.assertEqual(before, after, shop_id)
            self.assertEqual(self.data[offset : offset + len(before)], before)
            for dialogue_index in range(7):
                text_id = record.dialogue_id + dialogue_index
                dialogue = text_codec.record("system", text_id)
                patch = text_codec.replacement_patch(
                    "system", text_id, 0, dialogue.text
                )
                self.assertEqual(patch[1], patch[2], (shop_id, dialogue_index))


class LegacyTextScenarioUiTests(QtTestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.application = QApplication.instance() or QApplication([])

    def setUp(self) -> None:
        self.project = RomProject.load(ROM)
        self.widgets = []

    def tearDown(self) -> None:
        for widget in self.widgets:
            widget.deleteLater()
        self.application.processEvents()

    def test_battle_draft_survives_selection_and_undo_restores_exact_rom(self) -> None:
        page = LegacyTextPage()
        self.widgets.append(page)
        page.set_project(self.project)
        before = bytes(self.project.working)
        page.text_edit.setPlainText(page.text_edit.toPlainText().replace("嘿嘿", "哈哈"))
        page.record_list.setCurrentRow(1)
        self.assertTrue(page.has_pending_draft)
        page.record_list.setCurrentRow(0)
        self.assertIn("哈哈", page.text_edit.toPlainText())
        self.assertTrue(page.commit_pending_changes())
        self.assertIn("哈哈", LegacyTextCodec(self.project.working).record("battle_00", 0).text)
        self.project.undo()
        self.assertEqual(bytes(self.project.working), before)

    def test_battle_page_exposes_reference_list_and_content_views(self) -> None:
        page = LegacyTextPage()
        self.widgets.append(page)
        page.set_project(self.project)
        self.assertEqual(
            [page.view_tabs.tabText(index) for index in range(page.view_tabs.count())],
            ["按列表", "按内容"],
        )
        self.assertEqual(page.group_combo.count(), 4)
        self.assertEqual(page.variant_list.count(), 6)
        self.assertEqual(page.content_edit.toPlainText().count("++"), 5)
        self.assertIn("嘿嘿！小毛贼", page.content_edit.toPlainText())
        self.assertIn("投靠我们联邦不好吗", page.content_edit.toPlainText())
        page.text_edit.setPlainText(page.text_edit.toPlainText().replace("嘿嘿", "哈哈"))
        self.assertIn("哈哈！小毛贼", page.content_edit.toPlainText())
        self.assertIn("哈哈！小毛贼", page.variant_list.item(0).text())
        self.assertIn("哈哈！小毛贼", page.record_list.item(0).text())

    def test_battle_page_relocates_longer_text_using_same_bank_draft_space(self) -> None:
        page = LegacyTextPage()
        self.widgets.append(page)
        page.set_project(self.project)
        before = bytes(self.project.working)
        page.text_edit.setPlainText(
            page.text_edit.toPlainText().replace("小毛贼", "贼")
        )
        self.assertIsNone(page.pending_draft_error)
        self.assertIn("剩余 4 字节", page.status_label.text())
        page.variant_list.setCurrentRow(1)
        page.text_edit.setPlainText(
            page.text_edit.toPlainText().replace("你们", "你们你们", 1)
        )
        self.assertIsNone(page.pending_draft_error)
        self.assertIn("剩余 0 字节", page.status_label.text())
        self.assertTrue(page.commit_pending_changes())
        codec = LegacyTextCodec(self.project.working)
        self.assertIn("嘿嘿！贼！", codec.record("battle_00", 0, 0).text)
        self.assertIn("你们你们为什么", codec.record("battle_00", 0, 1).text)
        self.project.undo()
        self.assertEqual(bytes(self.project.working), before)

    def test_system_text_page_shows_reference_escape_note_and_capacity_entry(self) -> None:
        page = LegacyTextPage(("system",))
        self.widgets.append(page)
        page.set_project(self.project)
        self.assertTrue(page.system_note.isVisibleTo(page))
        self.assertIn('"{"加3字节16进制', page.system_note.text())
        self.assertTrue(page.add_button.isVisibleTo(page))
        self.assertTrue(page.add_button.isEnabled())
        self.assertIn("容量说明", page.add_button.toolTip())

    def test_growth_hex_dialog_edits_first_60_values_and_preserves_tail(self) -> None:
        values = tuple(index % 16 for index in range(99))
        dialog = GrowthHexDialog(values)
        self.widgets.append(dialog)
        self.assertEqual(dialog.hex_edit.text(), "".join(f"{value:X}" for value in values[:60]))
        self.assertEqual(dialog.values(), values)
        dialog.hex_edit.setText("F" * 60)
        self.assertEqual(dialog.values()[:60], (15,) * 60)
        self.assertEqual(dialog.values()[60:], values[60:])
        dialog.hex_edit.setText("F" * 59)
        self.assertFalse(
            dialog.buttons.button(QDialogButtonBox.StandardButton.Ok).isEnabled()
        )
        with self.assertRaisesRegex(ValueError, "60位"):
            dialog.values()

    def test_event_page_uses_real_bank_and_dialogue_previews(self) -> None:
        page = LegacyScenarioEventsPage(0)
        self.widgets.append(page)
        page.set_project(self.project)
        self.assertEqual(
            page.record_list.item(0).text(),
            "000: 播放我方地图音乐：地球我方音乐",
        )
        self.assertIn("请你选择琉妮驾驶的机体", page.record_list.item(10).text())
        end_page = LegacyScenarioEventsPage(1)
        self.widgets.append(end_page)
        end_page.set_project(self.project)
        self.assertEqual(end_page.record_list.item(0).text(), "000: 事件结束")
        live_page = LegacyScenarioEventsPage(2)
        self.widgets.append(live_page)
        live_page.set_project(self.project)
        self.assertEqual(live_page.record_list.item(2).text(), "002: 判断：第3回合？")
        page.raw_edit.setText("59 87")
        self.assertTrue(page.has_pending_draft)
        self.assertTrue(page.commit_pending_changes())
        self.assertEqual(self.project.working[0x3C011], 0x87)
        self.assertEqual(self.project.working[0x36011], self.project.original[0x36011])

    def test_invalid_event_hex_survives_record_navigation_verbatim(self) -> None:
        page = LegacyScenarioEventsPage(0)
        self.widgets.append(page)
        page.set_project(self.project)
        page.raw_edit.setText("GG")
        self.assertIn("十六进制", page.pending_draft_error)
        page.record_list.setCurrentRow(1)
        page.record_list.setCurrentRow(0)
        self.assertEqual(page.raw_edit.text(), "GG")
        self.assertTrue(page.has_pending_draft)

    def test_foreign_change_blocks_stale_text_draft(self) -> None:
        page = LegacyTextPage()
        self.widgets.append(page)
        page.set_project(self.project)
        page.text_edit.setPlainText(page.text_edit.toPlainText().replace("嘿嘿", "哈哈"))
        self.project.working[0x54021] ^= 1
        self.assertIn("其他页面", page.pending_draft_error)

    def test_shortened_text_can_be_restored_using_original_reserved_capacity(self) -> None:
        page = LegacyTextPage(("item_description",))
        self.widgets.append(page)
        page.set_project(self.project)
        original = bytes(self.project.working)
        page.text_edit.setPlainText("防御力增加1点。⟦结束⟧")
        self.assertTrue(page.commit_pending_changes())
        page.reset_current()
        self.assertIsNone(page.pending_draft_error)
        self.assertTrue(page.commit_pending_changes())
        self.assertEqual(bytes(self.project.working), original)

    def test_growth_ui_and_shop_ui_write_only_verified_records(self) -> None:
        growth = LegacyGrowthPage()
        shop = LegacyShopPage()
        self.widgets.extend((growth, shop))
        growth.set_project(self.project)
        shop.set_project(self.project)
        self.assertEqual(growth.growth_table.item(0, 1).text(), "1")
        growth.growth_table.item(0, 1).setText("3")
        self.assertTrue(growth.commit_pending_changes())
        self.assertEqual(self.project.working[0xA78A], 0x32)
        self.assertEqual([combo.currentData() for combo in shop.item_combos], [13, 5, 15, 16])
        self.assertIn("欢迎光临道具商店", shop.dialogue_edits[0].toPlainText())
        shop.item_combos[0].setCurrentIndex(11)
        shop.dialogue_edits[0].setPlainText(shop.dialogue_edits[0].toPlainText().replace("欢迎", "感谢"))
        self.assertTrue(shop.commit_pending_changes())
        self.assertEqual(self.project.working[0x15777], 11)
        self.assertIn("感谢光临", LegacyTextCodec(self.project.working).record("system", 48).text)
        shop.shop_combo.setCurrentIndex(5)
        self.assertFalse(shop.fields.isEnabled())
        self.assertIn("地图事件", shop.status_label.text())

    def test_shop_dialogue_can_restore_original_capacity_after_shortening(self) -> None:
        page = LegacyShopPage()
        self.widgets.append(page)
        page.set_project(self.project)
        original = bytes(self.project.working)
        original_text = page.dialogue_edits[0].toPlainText()
        page.dialogue_edits[0].setPlainText(original_text.replace("欢迎光临道具商店", "欢迎光临"))
        self.assertIsNone(page.pending_draft_error)
        self.assertTrue(page.commit_pending_changes())
        self.assertNotEqual(bytes(self.project.working), original)
        page.dialogue_edits[0].setPlainText(original_text)
        self.assertIsNone(page.pending_draft_error)
        self.assertTrue(page.commit_pending_changes())
        self.assertEqual(bytes(self.project.working), original)

    def test_text_growth_shop_and_event_project_save_reload_preserve_exact_bytes(self) -> None:
        data = self.project.working
        text = LegacyTextCodec(data)
        growth = LegacyGrowthCodec(data)
        shops = LegacyShopCodec(data)
        events = LegacyScenarioCodec(data)
        shorter_id = ("battle_00", 0, 0)
        longer_id = ("battle_00", 0, 1)
        shorter = text.record(*shorter_id).text.replace("小毛贼", "贼")
        longer = text.record(*longer_id).text.replace("你们", "你们你们", 1)
        values = list(growth.record(201).values)
        values[0] = 3
        patches = (
            *text.battle_repack_patches(
                {shorter_id: shorter, longer_id: longer}
            ),
            growth.replacement_patch(201, values),
            shops.replacement_patch(0xF0, 2, 48, (12, 5, 15, 16)),
            events.replacement_patch(events.instructions(0, 0)[0], b"\x59\x87"),
        )
        self.project._apply_legacy_global_patches(patches, "验证文字与事件")
        with TemporaryDirectory() as directory:
            path = self.project.save_project(Path(directory) / "legacy.dcproject")
            reloaded = RomProject.load_project(path, ROM)
            self.assertEqual(bytes(reloaded.working), bytes(self.project.working))
            reopened = LegacyTextCodec(reloaded.working)
            self.assertEqual(reopened.record(*shorter_id).text, shorter)
            self.assertEqual(reopened.record(*longer_id).text, longer)


if __name__ == "__main__":
    unittest.main()
