from __future__ import annotations

import os
from pathlib import Path
import unittest
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

from dc_modifier.legacy_windows import DatabaseDialog
from fc_editor.dc_text import default_dc_text_table
from fc_rom_editor_core import RomProject


ROOT = Path(__file__).resolve().parents[1]
ROM_PATH = ROOT / "output" / "rom" / "DC_kuorong_464K.nes"


class LegacyItemUiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.application = QApplication.instance() or QApplication([])
        if not ROM_PATH.is_file():
            raise unittest.SkipTest(f"缺少界面测试ROM：{ROM_PATH}")

    def setUp(self) -> None:
        self.project = RomProject.load(ROM_PATH)
        self.dialog = DatabaseDialog(self.project)
        self.dialog.show()
        self.application.processEvents()

    def tearDown(self) -> None:
        self.dialog.hide()
        self.dialog.deleteLater()
        self.application.processEvents()

    def test_item_page_loads_24_verified_names_and_display_prices(self) -> None:
        page = self.dialog.other_page_2
        self.assertEqual(page.item_table.rowCount(), 24)
        self.assertEqual(page.item_table.item(0, 0).text(), "01")
        self.assertEqual(page.item_table.item(0, 1).text(), "碳合金")
        self.assertEqual(page.item_table.item(0, 2).text(), "4000")
        self.assertEqual(page.item_table.item(23, 1).text(), "钢铁之魂")
        self.assertEqual(page.item_table.item(23, 2).text(), "99990")
        self.assertEqual(
            tuple(
                int(page.item_table.item(row, 2).text()) // 10
                for row in range(24)
            ),
            self.project.get_item_prices(),
        )

    def test_database_ok_repackages_names_and_prices_as_one_undo_entry(self) -> None:
        page = self.dialog.other_page_2
        original = bytes(self.project.working)
        original_undo_count = len(self.project._undo_stack)
        first_name = page.item_table.item(0, 1).text()
        second_name = page.item_table.item(1, 1).text()
        page.item_table.item(0, 1).setText(second_name)
        page.item_table.item(1, 1).setText(first_name)
        page.item_table.item(0, 2).setText("4010")
        self.application.processEvents()
        self.assertTrue(page.has_pending_draft)
        self.assertIsNone(page.pending_draft_error)

        self.dialog.accept()

        table = default_dc_text_table()
        self.assertEqual(self.dialog.result(), self.dialog.DialogCode.Accepted)
        self.assertEqual(self.project.get_item_name_records()[0], table.encode(second_name))
        self.assertEqual(self.project.get_item_name_records()[1], table.encode(first_name))
        self.assertEqual(self.project.get_item_prices()[0], 401)
        self.assertEqual(len(self.project._undo_stack), original_undo_count + 1)
        self.assertEqual(self.project.undo_description, "道具名称与价格")
        self.assertEqual(self.project.undo(), "道具名称与价格")
        self.assertEqual(bytes(self.project.working), original)

    def test_invalid_display_price_blocks_ok_and_preserves_the_draft(self) -> None:
        page = self.dialog.other_page_2
        before = bytes(self.project.working)
        page.item_table.item(0, 2).setText("4001")
        self.application.processEvents()
        self.assertTrue(page.has_pending_draft)
        self.assertIn("10的倍数", page.pending_draft_error or "")

        with patch("dc_modifier.legacy_windows.QMessageBox.warning") as warning:
            self.dialog.accept()

        warning.assert_called_once()
        self.assertTrue(self.dialog.isVisible())
        self.assertEqual(page.item_table.item(0, 2).text(), "4001")
        self.assertEqual(bytes(self.project.working), before)

    def test_unencodable_name_blocks_ok_without_replacing_the_text(self) -> None:
        page = self.dialog.other_page_2
        before = bytes(self.project.working)
        invalid = page.item_table.item(0, 1).text() + "🙂"
        page.item_table.item(0, 1).setText(invalid)
        self.application.processEvents()
        self.assertTrue(page.has_pending_draft)
        self.assertIn("没有字库编码", page.pending_draft_error or "")

        with patch("dc_modifier.legacy_windows.QMessageBox.warning") as warning:
            self.dialog.accept()

        warning.assert_called_once()
        self.assertTrue(self.dialog.isVisible())
        self.assertEqual(page.item_table.item(0, 1).text(), invalid)
        self.assertEqual(bytes(self.project.working), before)

    def test_editing_one_glyph_preserves_untouched_name_token_aliases(self) -> None:
        page = self.dialog.other_page_2
        table = default_dc_text_table()
        row = 15
        original_raw = self.project.get_item_name_records()[row]
        self.assertIn(b"\xC8\x88", original_raw)
        original_text = page.item_table.item(row, 1).text()
        replacement = page.item_table.item(0, 1).text()[0]
        replacement_raw = table.encode(replacement)
        self.assertEqual(len(replacement_raw), 2)
        self.assertNotEqual(original_text[-1], replacement)

        page.item_table.item(row, 1).setText(original_text[:-1] + replacement)
        names, _prices = page._draft_values()

        self.assertEqual(names[row], original_raw[:-2] + replacement_raw)
        self.assertIn(b"\xC8\x88", names[row])

    def test_price_only_edit_preserves_noncanonical_name_storage_exactly(self) -> None:
        codec = self.project.legacy_global_data_codec
        self.assertIsNotNone(codec)
        assert codec is not None
        spec = codec.spec
        records = list(self.project.get_item_name_records())
        records[0] = records[0][:-2]
        table_start = spec.item_name_pointer_table_offset
        table_end = table_start + spec.item_count * 2
        pool_start = spec.item_name_pool_start_offset
        pool_end = spec.item_name_pool_end_offset
        self.project.working[pool_start:pool_end] = bytes((0xA5,)) * (
            pool_end - pool_start
        )
        self.project.working[pool_start] = 0x42
        cursor = pool_start + 1
        pointers: list[int] = []
        for record in records:
            pointers.append(codec._item_name_cpu_pointer(cursor))
            payload = record + bytes((codec.ITEM_NAME_TERMINATOR,))
            self.project.working[cursor : cursor + len(payload)] = payload
            cursor += len(payload)
        self.project.working[table_start:table_end] = b"".join(
            pointer.to_bytes(2, "little") for pointer in pointers
        )
        codec.item_name_records(self.project.working)
        self.dialog.other_page_2.refresh()
        storage_before = bytes(self.project.working[table_start:pool_end])
        old_price = self.project.get_item_prices()[0]

        self.dialog.other_page_2.item_table.item(0, 2).setText(
            str((old_price + 1) * 10)
        )
        self.dialog.accept()

        self.assertEqual(self.project.get_item_prices()[0], old_price + 1)
        self.assertEqual(
            bytes(self.project.working[table_start:pool_end]),
            storage_before,
        )


if __name__ == "__main__":
    unittest.main()
