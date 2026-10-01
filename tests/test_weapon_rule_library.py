from __future__ import annotations

import os
import hashlib
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from dc_modifier.app import DEFAULT_ROM
from dc_modifier.weapon_rule_library import (
    WEAPON_RULE_TABLES,
    BeamRuleParts,
    WeaponRuleCatalog,
    WeaponRuleLibraryDialog,
    WeaponMovementSimulatorDialog,
    decode_axis_preview,
    increment_weapon_rule_tiles,
    replace_weapon_rule_record,
    join_beam_rule,
    split_beam_rule,
)
from dc_modifier.animation_editor import SpritePuzzlePreviewDialog
from fc_editor.codecs.animation import (
    decode_legacy_beam_composition,
    encode_legacy_beam_composition,
)
from fc_rom_editor_core import RomProject
from tests.qt_test_case import QtTestCase


class WeaponRuleCatalogTests(unittest.TestCase):
    def setUp(self) -> None:
        self.project = RomProject.load(DEFAULT_ROM)
        self.catalog = WeaponRuleCatalog(self.project.working)

    def test_four_reference_tables_have_verified_counts_and_first_codes(self) -> None:
        self.assertEqual(
            tuple(table.count for table in WEAPON_RULE_TABLES),
            (255, 252, 250, 255),
        )
        expected = (
            "FD 20 20 F8 FF 00 FF",
            "00 83 F0 FC 00 83 F0 FC",
            "00 83 F0 FC 00 83 F0 FC",
            "01 00 00 08 F0 00 00 00 28 04 E8 80 80 80 A8 01 E8 80 80 80 FF",
        )
        for table, code in zip(WEAPON_RULE_TABLES, expected, strict=True):
            _offset, raw, _aliases = self.catalog.record(table, 1)
            self.assertEqual(raw.hex(" ").upper(), code)

    def test_beam_page_hides_optional_initial_and_terminal_coordinate_controls(self) -> None:
        cases = (
            (
                "FE 06 10 FD 20 20 F8 FF 00 FF",
                BeamRuleParts((0x10, 0x06), bytes.fromhex("FD 20 20 F8 FF 00 FF"), None),
            ),
            (
                "78 F3 00 FE FF",
                BeamRuleParts(None, bytes.fromhex("78 FF"), (-2, 0)),
            ),
            (
                "FE 0A 10 78 F3 00 00 FF",
                BeamRuleParts((0x10, 0x0A), bytes.fromhex("78 FF"), (0, 0)),
            ),
        )
        for text, expected in cases:
            with self.subTest(text=text):
                raw = bytes.fromhex(text)
                self.assertEqual(split_beam_rule(raw), expected)
                self.assertEqual(join_beam_rule(expected), raw)

    def test_invalid_pointer_signature_fails_closed(self) -> None:
        broken = bytearray(self.project.working)
        broken[WEAPON_RULE_TABLES[0].pointer_table + 2] ^= 1
        with self.assertRaisesRegex(ValueError, "指针表"):
            WeaponRuleCatalog(broken)

    def test_hidden_prefix_can_be_included_for_complete_inspection(self) -> None:
        table = WEAPON_RULE_TABLES[0]
        offset, visible, aliases = self.catalog.record(table, 1)
        full_offset, complete, full_aliases = self.catalog.record(
            table, 1, include_hidden=True
        )
        self.assertEqual(full_offset, offset)
        self.assertEqual(full_aliases, aliases)
        self.assertEqual(complete[table.hidden_prefix:], visible)
        self.assertEqual(len(complete), len(visible) + table.hidden_prefix)

    def test_shared_pool_repack_matches_three_reference_variable_length_goldens(self) -> None:
        source = bytes(self.project.working)
        cases = (
            (
                "weapon_movement_1",
                bytes.fromhex("01 83 F0 FC 00 83 F0 FC 00"),
                2836,
                "0B58AF7021CFA9B4CDB4BC55218D503AF486EBFDE46FD31514360D0997B09D95",
            ),
            (
                "weapon_beam",
                bytes.fromhex("FD 20 20 F8 FF 00 00 FF"),
                6715,
                "AF47E8459BD35CB0FEF229B6962F1E7C2B9A1148858885843AFC3A018EBDB01C",
            ),
            (
                "weapon_picture",
                bytes.fromhex(
                    "01 00 00 08 F0 00 00 00 28 04 E8 80 80 80 "
                    "A8 01 E8 80 80 80 00 FF"
                ),
                10568,
                "42235F9C0C09CE77DAF0EB21B83D3E043027F2D67EB1838AFD378E251448C101",
            ),
            (
                "weapon_movement_2",
                bytes.fromhex("01 83 F0 FC 00 83 F0 FC 00"),
                746,
                "1638E46946533845FDB03D26B3F60F6B0F4D536F5B03E9754485762A0C0FAAB0",
            ),
        )
        for key, replacement, diff_count, expected_sha in cases:
            with self.subTest(key=key):
                output = replace_weapon_rule_record(
                    source, key, 1, replacement
                )
                self.assertEqual(
                    sum(a != b for a, b in zip(source, output)),
                    diff_count,
                )
                self.assertEqual(
                    hashlib.sha256(output).hexdigest().upper(), expected_sha
                )
                reopened = WeaponRuleCatalog(output)
                table = next(item for item in WEAPON_RULE_TABLES if item.key == key)
                self.assertEqual(reopened.record(table, 1)[1], replacement)

    def test_aliased_rule_edit_uses_reference_copy_on_write_golden(self) -> None:
        source = bytes(self.project.working)
        table = WEAPON_RULE_TABLES[0]
        self.assertEqual(
            self.catalog.record(table, 214, include_hidden=True)[2],
            (225, 226),
        )

        output = replace_weapon_rule_record(
            source,
            "weapon_beam",
            214,
            bytes.fromhex("FE 07 81 FF"),
            include_hidden=True,
        )
        reopened = WeaponRuleCatalog(output)

        self.assertEqual(
            hashlib.sha256(output).hexdigest().upper(),
            "0D27AAFE466E85A092339920473307A8D79ACAEF9AD6A06F86D1860F2184D26C",
        )
        self.assertEqual(
            reopened.record(table, 214, include_hidden=True)[1],
            bytes.fromhex("FE 07 81 FF"),
        )
        self.assertEqual(reopened.record(table, 214, include_hidden=True)[2], ())
        self.assertEqual(
            reopened.record(table, 225, include_hidden=True)[1],
            bytes.fromhex("FE 07 80 FF"),
        )
        self.assertEqual(
            reopened.record(table, 225, include_hidden=True)[2],
            (226,),
        )

    def test_same_length_hidden_coordinate_edits_match_reference_goldens(self) -> None:
        source = bytes(self.project.working)
        beam = self.catalog.record(
            WEAPON_RULE_TABLES[0], 1, include_hidden=True
        )[1]
        beam_output = replace_weapon_rule_record(
            source,
            "weapon_beam",
            1,
            bytes((0xFE, 7, 18)) + beam[3:],
            include_hidden=True,
        )
        self.assertEqual(
            hashlib.sha256(beam_output).hexdigest().upper(),
            "DF7E778781EE2822BE7D545F4A76FD3E4412A870C0252471497A59ACF98AAA37",
        )
        picture = self.catalog.record(
            WEAPON_RULE_TABLES[3], 1, include_hidden=True
        )[1]
        picture_output = replace_weapon_rule_record(
            source,
            "weapon_picture",
            1,
            bytes((2, 3)) + picture[2:],
            include_hidden=True,
        )
        self.assertEqual(
            hashlib.sha256(picture_output).hexdigest().upper(),
            "5BB95F83DB08BD98DEE24C51BD6758C2F985218A73375BBC0A2BBDF9B70F0E98",
        )

    def test_beam_puzzle_two_tile_edit_matches_reference_record_75_golden(self) -> None:
        source = bytes(self.project.working)
        table = WEAPON_RULE_TABLES[0]
        raw = self.catalog.record(table, 75, include_hidden=True)[1]
        decoded = decode_legacy_beam_composition(raw)
        self.assertTrue(decoded.editable)
        first = decoded.placements[0]
        replacement = encode_legacy_beam_composition(
            (
                type(first)(
                    first.command_offset, first.x, first.y, 0xB8, 0xB8, 0
                ),
                type(first)(
                    first.command_offset, first.x + 4, first.y + 5,
                    0xA4, 0xA4, 0,
                ),
            ),
            anchor_x=decoded.anchor_x,
            anchor_y=decoded.anchor_y,
        )
        self.assertEqual(
            replacement,
            bytes.fromhex("FE 0A 10 B8 F3 05 03 A4 F3 00 00 FF"),
        )
        output = replace_weapon_rule_record(
            source,
            "weapon_beam",
            75,
            replacement,
            include_hidden=True,
        )
        self.assertEqual(
            hashlib.sha256(output).hexdigest().upper(),
            "837412D511C940B28FE32F937D5B319CF57D797DD155AFD603776F78896EEAA2",
        )

    def test_all_complete_beam_records_round_trip_through_compact_encoder(self) -> None:
        table = WEAPON_RULE_TABLES[0]
        verified = 0
        for record_id in range(1, table.count + 1):
            raw = self.catalog.record(
                table, record_id, include_hidden=True
            )[1]
            decoded = decode_legacy_beam_composition(raw)
            if not decoded.complete:
                continue
            with self.subTest(record_id=record_id):
                encoded = encode_legacy_beam_composition(
                    decoded.placements,
                    anchor_x=decoded.anchor_x,
                    anchor_y=decoded.anchor_y,
                )
                rebuilt = decode_legacy_beam_composition(encoded)
                self.assertTrue(rebuilt.complete, rebuilt.error)
                self.assertEqual(
                    [
                        (item.x, item.y, item.tile_token)
                        for item in rebuilt.placements
                    ],
                    [
                        (item.x, item.y, item.tile_token)
                        for item in decoded.placements
                    ],
                )
                # The largest no-op normalisation in the stock table grows by
                # 27 bytes, safely below the verified 115-byte shared-pool
                # headroom.  Untouched records are not normalised by the UI.
                self.assertLessEqual(len(encoded) - len(raw), 27)
            verified += 1
        self.assertEqual(verified, 193)

    def test_tile_increment_matches_both_reference_goldens(self) -> None:
        source = bytes(self.project.working)
        cases = (
            (
                WEAPON_RULE_TABLES[1],
                "weapon_movement_1",
                "5C0D1A710F982D5B4566F7AE8ED3ACA9E3774EB842FA0DFE828858678E6F0514",
            ),
            (
                WEAPON_RULE_TABLES[2],
                "weapon_movement_2",
                "4C73C6419D50535F8B70315DC6B932DC1F9308B8F358013A12D4078FDC0B36D2",
            ),
        )
        for table, key, expected_sha in cases:
            with self.subTest(key=key):
                raw = self.catalog.record(table, 2, include_hidden=True)[1]
                changed = increment_weapon_rule_tiles(raw, 1)
                output = replace_weapon_rule_record(
                    source, key, 2, changed, include_hidden=True
                )
                self.assertEqual(
                    hashlib.sha256(output).hexdigest().upper(), expected_sha
                )

    def test_shared_pool_shrinking_matches_all_four_reference_goldens(self) -> None:
        source = bytes(self.project.working)
        cases = (
            (
                "weapon_movement_1",
                "01 83 F0 FC 00 83 F0",
                2835,
                "817315F58F2D6C7456024869A7239A99BCFB08D3251A67A0911A5978780D3A26",
            ),
            (
                "weapon_movement_2",
                "01 83 F0 FC 00 83 F0",
                746,
                "3D558901E6893F7D0DC15FE67B4878CDDF2D3AC2D451539A7AD84E002BF298F6",
            ),
            (
                "weapon_beam",
                "FD 20 20 F8 FF FF",
                6718,
                "72ACBBBEE397E4B5E67DCFD60D60984BA40D220F578ADBC2D88F6425055085D9",
            ),
            (
                "weapon_picture",
                "01 00 00 08 F0 00 00 00 28 04 E8 80 80 80 A8 01 E8 80 80 FF",
                10569,
                "C5181FB7E19FB8294814B719577636B2DC2B7832A9C3BCAE35832697AFC2F023",
            ),
        )
        for key, code, diff_count, expected_sha in cases:
            with self.subTest(key=key):
                output = replace_weapon_rule_record(
                    source, key, 1, bytes.fromhex(code)
                )
                self.assertEqual(
                    sum(a != b for a, b in zip(source, output)), diff_count
                )
                self.assertEqual(
                    hashlib.sha256(output).hexdigest().upper(), expected_sha
                )


class WeaponRuleLibraryUiTests(QtTestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = QApplication.instance() or QApplication([])

    def test_dialog_exposes_four_independent_reference_tabs(self) -> None:
        project = RomProject.load(DEFAULT_ROM)
        dialog = WeaponRuleLibraryDialog(project)
        self.addCleanup(dialog.deleteLater)
        self.assertEqual(
            [dialog.tabs.tabText(index) for index in range(dialog.tabs.count())],
            ["光束组图规律", "物理运行规律1", "物理运行规律2", "物理图片规律"],
        )
        self.assertEqual(
            [dialog.lists[table.key].count() for table in WEAPON_RULE_TABLES],
            [255, 252, 250, 255],
        )
        self.assertIn("FD 20 20", dialog.codes["weapon_beam"].toPlainText())
        self.assertFalse(dialog.codes["weapon_beam"].isReadOnly())
        self.assertFalse(dialog.names["weapon_beam"].isReadOnly())
        self.assertEqual(
            set(dialog.simulator_buttons),
            {table.key for table in WEAPON_RULE_TABLES},
        )
        self.assertEqual(
            set(dialog.puzzle_buttons), {"weapon_beam", "weapon_picture"}
        )
        dialog.lists["weapon_beam"].setCurrentRow(6)
        self.assertEqual(dialog.codes["weapon_beam"].toPlainText(), "78 FF")
        initial, initial_x, initial_y, following, next_x, next_y = (
            dialog.beam_coordinate_controls["weapon_beam"]
        )
        self.assertFalse(initial.isChecked())
        self.assertFalse(initial_x.isEnabled())
        self.assertFalse(initial_y.isEnabled())
        self.assertTrue(following.isChecked())
        self.assertEqual((next_x.value(), next_y.value()), (-2, 0))

    def test_rule_lists_keep_legacy_mouse_and_keyboard_navigation(self) -> None:
        project = RomProject.load(DEFAULT_ROM)
        dialog = WeaponRuleLibraryDialog(project)
        self.addCleanup(dialog.deleteLater)
        dialog.show()
        self.app.processEvents()

        for table in WEAPON_RULE_TABLES:
            listing = dialog.lists[table.key]
            listing.setCurrentRow(0)
            listing.setFocus()
            QTest.keyClick(listing, Qt.Key.Key_End)
            self.assertEqual(listing.currentRow(), listing.count() - 1)
            QTest.keyClick(listing, Qt.Key.Key_Home)
            self.assertEqual(listing.currentRow(), 0)

            last_item = listing.item(listing.count() - 1)
            listing.scrollToItem(last_item)
            listing.setCurrentItem(last_item)
            self.app.processEvents()
            point = listing.visualItemRect(last_item).center()
            visible_before = {
                widget for widget in self.app.topLevelWidgets()
                if widget.isVisible()
            }
            QTest.mouseDClick(
                listing.viewport(), Qt.MouseButton.LeftButton, pos=point
            )
            QTest.mouseClick(
                listing.viewport(), Qt.MouseButton.RightButton, pos=point
            )
            self.app.processEvents()
            self.assertEqual(listing.currentRow(), listing.count() - 1)
            self.assertEqual(
                {
                    widget for widget in self.app.topLevelWidgets()
                    if widget.isVisible()
                },
                visible_before,
            )

    def test_axis_preview_expands_reference_static_480_frame_rule(self) -> None:
        values = decode_axis_preview(bytes.fromhex("00 83 F0 FC 00 83 F0 FC"))
        self.assertEqual(len(values), 480)
        self.assertEqual(set(values), {0})

    def test_movement_simulator_parses_codes_without_writing_project(self) -> None:
        dialog = WeaponMovementSimulatorDialog(bytes.fromhex("01 02"), b"")
        self.addCleanup(dialog.deleteLater)
        dialog._preview()
        self.assertEqual(dialog.x_values, (1, 2))
        self.assertTrue(dialog.timer.isActive())
        dialog._advance()
        self.assertEqual(dialog.x_spin.value(), 1)
        dialog._stop()
        self.assertFalse(dialog.timer.isActive())

    def test_movement_simulator_keeps_freeform_code_draft_until_use(self) -> None:
        dialog = WeaponMovementSimulatorDialog()
        self.addCleanup(dialog.deleteLater)
        draft = "GG\n12 345"
        dialog.x_code.setPlainText(draft)
        dialog.y_code.setPlainText(draft)

        self.assertEqual(dialog.x_code.toPlainText(), draft)
        self.assertEqual(dialog.y_code.toPlainText(), draft)
        with self.assertRaises(ValueError):
            dialog._parse_code(dialog.x_code)

    def test_movement_simulator_restores_legacy_create_and_record_state(self) -> None:
        dialog = WeaponMovementSimulatorDialog()
        self.addCleanup(dialog.deleteLater)
        messages: list[str] = []
        dialog._show_information = messages.append  # type: ignore[method-assign]

        self.assertFalse(dialog.canvas.object_created)
        self.assertEqual(dialog.width_spin.minimum(), 0)
        self.assertEqual(dialog.width_spin.maximum(), 100)
        self.assertEqual(dialog.height_spin.minimum(), 0)
        self.assertEqual(dialog.height_spin.maximum(), 100)
        dialog._start()
        self.assertEqual(messages, ["请使用鼠标左键点击屏幕创建物体"])
        self.assertTrue(dialog.awaiting_object)
        self.assertFalse(dialog.recording)

        dialog._canvas_clicked(10, 20)
        self.assertTrue(dialog.canvas.object_created)
        self.assertEqual((dialog.canvas.x, dialog.canvas.y), (10, 20))
        dialog._start()
        self.assertTrue(dialog.recording)

        dialog.x_spin.setValue(12)
        dialog.y_spin.setValue(13)
        dialog.move_button.click()
        self.assertEqual(dialog.x_code.toPlainText(), "0C")
        self.assertEqual(dialog.y_code.toPlainText(), "0D")
        self.assertEqual((dialog.canvas.x, dialog.canvas.y), (22, 33))
        dialog._stop()
        self.assertFalse(dialog.recording)
        self.assertFalse(dialog.mouse_check.isChecked())

    def test_movement_simulator_move_requires_start_and_sampling_is_counted(self) -> None:
        dialog = WeaponMovementSimulatorDialog()
        self.addCleanup(dialog.deleteLater)
        messages: list[str] = []
        dialog._show_information = messages.append  # type: ignore[method-assign]
        dialog.move_button.click()
        self.assertEqual(messages, ["请先点击开始"])
        self.assertEqual(dialog.x_code.toPlainText(), "")

        dialog.awaiting_object = True
        dialog._canvas_clicked(0, 0)
        dialog._start()
        dialog.sample_spin.setValue(2)
        dialog.x_spin.setValue(-1)
        dialog.y_spin.setValue(2)
        dialog.move_button.click()
        self.assertEqual(dialog.x_code.toPlainText(), "")
        dialog.move_button.click()
        self.assertEqual(dialog.x_code.toPlainText(), "FF")
        self.assertEqual(dialog.y_code.toPlainText(), "02")

    def test_movement_simulator_keeps_reference_unrestricted_inputs(self) -> None:
        dialog = WeaponMovementSimulatorDialog()
        self.addCleanup(dialog.deleteLater)
        dialog.width_spin.setValue(101)
        dialog.height_spin.setValue(-1)
        self.assertEqual((dialog.width_spin.value(), dialog.height_spin.value()), (101, -1))
        dialog.width_spin.setValue(2_147_483_648)
        dialog.height_spin.setValue(-2_147_483_649)
        self.assertEqual(
            (dialog.width_spin.value(), dialog.height_spin.value()),
            (2_147_483_648, -2_147_483_649),
        )

        dialog.awaiting_object = True
        dialog._canvas_clicked(0, 0)
        dialog._start()
        dialog.sample_spin.setValue(0)
        dialog.x_spin.setValue(-129)
        dialog.y_spin.setValue(128)
        dialog.move_button.click()
        self.assertEqual(dialog.x_code.toPlainText(), "7F")
        self.assertEqual(dialog.y_code.toPlainText(), "80")

    def test_movement_simulator_spinner_arrows_use_legacy_zero_to_hundred_cycle(self) -> None:
        dialog = WeaponMovementSimulatorDialog()
        self.addCleanup(dialog.deleteLater)
        spin = dialog.width_spin

        spin.setValue(37)
        spin.stepUp()
        self.assertEqual(spin.value(), 38)
        spin.stepDown()
        self.assertEqual(spin.value(), 37)

        spin.setValue(0x7FFFFFFF)
        spin.stepUp()
        self.assertEqual(spin.value(), 0)
        spin.setValue(-0x80000000)
        spin.stepDown()
        self.assertEqual(spin.value(), 100)

    def test_movement_simulator_buttons_keep_legacy_keyboard_and_right_clicks(self) -> None:
        dialog = WeaponMovementSimulatorDialog()
        self.addCleanup(dialog.deleteLater)
        dialog.awaiting_object = True
        dialog._canvas_clicked(0, 0)
        dialog.show()
        self.app.processEvents()

        dialog.start_button.setFocus()
        QTest.keyClick(dialog.start_button, Qt.Key.Key_Space)
        self.assertTrue(dialog.recording)
        dialog.mouse_check.setFocus()
        QTest.keyClick(dialog.mouse_check, Qt.Key.Key_Space)
        self.assertTrue(dialog.mouse_check.isChecked())
        QTest.keyClick(dialog.mouse_check, Qt.Key.Key_Space)
        self.assertFalse(dialog.mouse_check.isChecked())
        dialog.stop_button.setFocus()
        QTest.keyClick(dialog.stop_button, Qt.Key.Key_Space)
        self.assertFalse(dialog.recording)

        before = (
            dialog.recording,
            dialog.mouse_check.isChecked(),
            dialog.x_code.toPlainText(),
            dialog.y_code.toPlainText(),
        )
        for target in (
            dialog.move_button, dialog.mouse_check,
            dialog.start_button, dialog.stop_button,
        ):
            QTest.mouseClick(target, Qt.MouseButton.RightButton)
        self.assertEqual(
            before,
            (
                dialog.recording,
                dialog.mouse_check.isChecked(),
                dialog.x_code.toPlainText(),
                dialog.y_code.toPlainText(),
            ),
        )

    def test_legacy_simulator_entry_opens_as_blank_independent_tool(self) -> None:
        project = RomProject.load(DEFAULT_ROM)
        dialog = WeaponRuleLibraryDialog(project)
        self.addCleanup(dialog.deleteLater)
        opened: list[tuple[bytes, bytes]] = []

        class FakeSimulator:
            def __init__(self, x_code=b"", y_code=b"", parent=None):
                opened.append((x_code, y_code))

            def exec(self) -> int:
                return 0

        with patch(
            "dc_modifier.weapon_rule_library.WeaponMovementSimulatorDialog",
            FakeSimulator,
        ):
            for table in WEAPON_RULE_TABLES:
                dialog._open_simulator(table)
        self.assertEqual(opened, [(b"", b"")] * 4)

    def test_legacy_simulator_and_two_puzzle_entries_are_reachable(self) -> None:
        project = RomProject.load(DEFAULT_ROM)
        dialog = WeaponRuleLibraryDialog(project)
        self.addCleanup(dialog.deleteLater)
        opened: list[tuple[str, bytes]] = []

        class FakePuzzle:
            def __init__(self, record, _project, _codec, _parent, **_kwargs):
                self.record = record
                self.title = ""

            def setWindowTitle(self, title: str) -> None:
                self.title = title

            def exec(self) -> int:
                opened.append((self.title, self.record.raw))
                return 0

        with patch(
            "dc_modifier.weapon_rule_library.SpritePuzzlePreviewDialog",
            FakePuzzle,
        ):
            dialog._open_puzzle(WEAPON_RULE_TABLES[0])
            dialog._open_puzzle(WEAPON_RULE_TABLES[3])
        self.assertEqual([item[0] for item in opened], ["光束拼图", "物理拼图"])
        self.assertEqual(opened[0][1][:2], bytes((0x10, 0x06)))
        self.assertEqual(opened[1][1][:3], bytes.fromhex("00 00 01"))

        with patch.object(SpritePuzzlePreviewDialog, "exec", return_value=0):
            dialog._open_puzzle(WEAPON_RULE_TABLES[0])
            dialog._open_puzzle(WEAPON_RULE_TABLES[3])

    def test_puzzle_accept_updates_beam_and_picture_drafts(self) -> None:
        project = RomProject.load(DEFAULT_ROM)
        dialog = WeaponRuleLibraryDialog(project)
        self.addCleanup(dialog.deleteLater)
        opened: list[tuple[str, bool]] = []

        class FakePuzzle:
            def __init__(self, record, _project, _codec, _parent, **kwargs):
                self.record = record
                self.title = ""
                opened.append((record.kind, kwargs.get("editable", False)))

            def setWindowTitle(self, title: str) -> None:
                self.title = title

            def exec(self) -> int:
                return 1

            def edited_raw(self) -> bytes:
                if self.title == "光束拼图":
                    return bytes.fromhex("11 22 00 FF")
                return bytes.fromhex("33 44 01 00 FF")

        with patch(
            "dc_modifier.weapon_rule_library.SpritePuzzlePreviewDialog",
            FakePuzzle,
        ):
            dialog._open_puzzle(WEAPON_RULE_TABLES[0])
            dialog._open_puzzle(WEAPON_RULE_TABLES[3])

        self.assertEqual(opened, [("sprite", True), ("sprite", True)])
        self.assertEqual(
            dialog.rule_overrides[("weapon_beam", 1)],
            bytes.fromhex("FE 22 11 00 FF"),
        )
        self.assertEqual(
            dialog.rule_overrides[("weapon_picture", 1)],
            bytes.fromhex("33 44 01 00 FF"),
        )

    def test_search_complete_copy_and_full_page_export_text(self) -> None:
        project = RomProject.load(DEFAULT_ROM)
        dialog = WeaponRuleLibraryDialog(project)
        self.addCleanup(dialog.deleteLater)
        table = WEAPON_RULE_TABLES[0]

        dialog.searches[table.key].setText("2")
        dialog._find_next(table)
        self.assertEqual(dialog.lists[table.key].currentRow(), 1)

        visible = dialog.codes[table.key].toPlainText()
        dialog.complete_checks[table.key].setChecked(True)
        complete = dialog.codes[table.key].toPlainText()
        self.assertGreater(len(complete), len(visible))
        self.assertIn("完整记录", dialog.statuses[table.key].text())

        dialog._copy_current(table)
        copied = QApplication.clipboard().text()
        self.assertIn("光束组图规律 $02", copied)
        self.assertIn("文件地址：0x", copied)
        self.assertIn("代码：", copied)

        exported = dialog._all_text(table)
        self.assertIn("# 记录数：255", exported)
        self.assertIn("$EF\t0x0120B5", exported)
        self.assertEqual(
            len([line for line in exported.splitlines() if line.startswith("$")]),
            table.count,
        )

        dialog.lists[table.key].setCurrentRow(0xEF - 1)
        self.assertEqual(dialog.codes[table.key].toPlainText(), "FE 0B 10 FF")
        self.assertIn("4 字节", dialog.statuses[table.key].text())

    def test_weapon_rule_name_accept_cancel_undo_and_project_reopen(self) -> None:
        project = RomProject.load(DEFAULT_ROM)
        cancelled = WeaponRuleLibraryDialog(project)
        self.addCleanup(cancelled.deleteLater)
        cancelled.names["weapon_beam"].setText("取消名称")
        cancelled.names["weapon_beam"].textEdited.emit("取消名称")
        cancelled.reject()
        self.assertFalse(project.animation_label_overrides)

        dialog = WeaponRuleLibraryDialog(project)
        self.addCleanup(dialog.deleteLater)
        dialog.names["weapon_beam"].setText("光束测试名称")
        dialog.names["weapon_beam"].textEdited.emit("光束测试名称")
        dialog.accept()
        self.assertEqual(
            project.animation_label_overrides[("weapon_beam", 1)],
            "光束测试名称",
        )
        self.assertTrue(project.can_undo)

        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "weapon-rule-name.dcmod"
            project.save_project(path)
            reopened = RomProject.load_project(path, DEFAULT_ROM)
        self.assertEqual(
            reopened.animation_label_overrides[("weapon_beam", 1)],
            "光束测试名称",
        )
        project.undo()
        self.assertFalse(project.animation_label_overrides)

    def test_code_repack_cancel_accept_and_undo_match_reference_golden(self) -> None:
        project = RomProject.load(DEFAULT_ROM)
        before = bytes(project.working)
        replacement = "01 83 F0 FC 00 83 F0 FC 00"

        cancelled = WeaponRuleLibraryDialog(project)
        self.addCleanup(cancelled.deleteLater)
        cancelled.codes["weapon_movement_1"].setPlainText(replacement)
        cancelled.reject()
        self.assertEqual(bytes(project.working), before)

        dialog = WeaponRuleLibraryDialog(project)
        self.addCleanup(dialog.deleteLater)
        dialog.codes["weapon_movement_1"].setPlainText(replacement)
        dialog.accept()
        self.assertEqual(
            hashlib.sha256(project.working).hexdigest().upper(),
            "0B58AF7021CFA9B4CDB4BC55218D503AF486EBFDE46FD31514360D0997B09D95",
        )
        reopened = WeaponRuleCatalog(project.working)
        self.assertEqual(
            reopened.record(WEAPON_RULE_TABLES[1], 1)[1].hex(" ").upper(),
            replacement,
        )
        project.undo()
        self.assertEqual(bytes(project.working), before)

    def test_copy_and_export_use_unsaved_repacked_draft(self) -> None:
        project = RomProject.load(DEFAULT_ROM)
        dialog = WeaponRuleLibraryDialog(project)
        self.addCleanup(dialog.deleteLater)
        replacement = "01 83 F0 FC 00 83 F0 FC 00"
        dialog.codes["weapon_movement_1"].setPlainText(replacement)

        current = dialog._current_text(WEAPON_RULE_TABLES[1])
        exported = dialog._all_text(WEAPON_RULE_TABLES[1])

        self.assertIn(f"代码：{replacement}", current)
        self.assertIn(replacement, exported.splitlines()[3])
        self.assertEqual(bytes(project.working), bytes(dialog.base))

    def test_coordinate_controls_commit_exact_hidden_prefix_bytes(self) -> None:
        project = RomProject.load(DEFAULT_ROM)
        dialog = WeaponRuleLibraryDialog(project)
        self.addCleanup(dialog.deleteLater)
        _initial, x_spin, y_spin, _next, _next_x, _next_y = (
            dialog.beam_coordinate_controls["weapon_beam"]
        )
        x_spin.setValue(18)
        y_spin.setValue(7)
        dialog.accept()
        self.assertEqual(
            hashlib.sha256(project.working).hexdigest().upper(),
            "DF7E778781EE2822BE7D545F4A76FD3E4412A870C0252471497A59ACF98AAA37",
        )


if __name__ == "__main__":
    unittest.main()
