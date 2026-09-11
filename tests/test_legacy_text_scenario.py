from __future__ import annotations

import os
from pathlib import Path
import unittest
from tempfile import TemporaryDirectory

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

from dc_modifier.legacy_text_pages import LegacyGrowthPage, LegacyScenarioEventsPage, LegacyShopPage, LegacyTextPage
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

    def test_growth_reader_nibble_order_shared_records_and_last_padding(self) -> None:
        codec = LegacyGrowthCodec(self.data)
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

    def test_event_page_uses_real_bank_and_dialogue_previews(self) -> None:
        page = LegacyScenarioEventsPage(0)
        self.widgets.append(page)
        page.set_project(self.project)
        self.assertIn("播放我方地图音乐", page.record_list.item(0).text())
        self.assertIn("请你选择琉妮驾驶的机体", page.record_list.item(10).text())
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
        record = text.record("battle_00", 0)
        values = list(growth.record(201).values)
        values[0] = 3
        patches = (
            text.replacement_patch("battle_00", 0, 0, record.text.replace("嘿嘿", "哈哈")),
            growth.replacement_patch(201, values),
            shops.replacement_patch(0xF0, 2, 48, (12, 5, 15, 16)),
            events.replacement_patch(events.instructions(0, 0)[0], b"\x59\x87"),
        )
        self.project._apply_legacy_global_patches(patches, "验证文字与事件")
        with TemporaryDirectory() as directory:
            path = self.project.save_project(Path(directory) / "legacy.dcproject")
            reloaded = RomProject.load_project(path, ROM)
            self.assertEqual(bytes(reloaded.working), bytes(self.project.working))


if __name__ == "__main__":
    unittest.main()
