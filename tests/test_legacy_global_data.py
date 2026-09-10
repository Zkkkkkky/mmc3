from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from fc_editor.codecs import LegacyGlobalDataCodec
from fc_editor.errors import RomFormatError
from fc_editor.profiles import (
    DC_EXPANDED_MMC3_LEGACY_PROFILE,
    DC_EXPANDED_MMC3_PROFILE,
    MMC5_PROFILE,
    ORIGINAL_PROFILE,
    V51_PROFILE,
)
from fc_rom_editor_core import RomProject


ROOT = Path(__file__).resolve().parents[1]
TARGET_ROM = ROOT / "output" / "rom" / "DC_kuorong_464K.nes"
CONTEXT_BASELINES = (
    ROOT / "references" / "rom" / "source" / "新DC.nes",
    ROOT / "references" / "rom" / "baselines" / "DC_kuorong.nes",
    TARGET_ROM,
)
EXPECTED_DISTANCE_HIT_CORRECTIONS = (
    (100,) * 16,
    (100, 98, 96, 94, 92, 90, 88, 86, 84, 82, 80, 78, 76, 74, 72, 70),
    (100, 95, 90, 85, 80, 75, 70, 65, 60, 55, 50, 45, 40, 35, 30, 25),
    (100, 90, 80, 70, 60, 50, 40, 30, 20, 10, 9, 8, 7, 6, 5, 4),
)

EXPECTED_EXPERIENCE_TOTALS = (
    20, 60, 120, 200, 300, 420, 560, 720, 900, 1100,
    1220, 1360, 1520, 1700, 1900, 2120, 2360, 2620, 2900, 3100,
    3320, 3560, 3820, 4100, 4400, 4720, 5060, 5420, 5800, 6100,
    6420, 6760, 7120, 7500, 7900, 8320, 8760, 9220, 9700, 10100,
    10520, 10960, 11420, 11900, 12400, 12920, 13460, 14020, 14600, 15200,
    15820, 16460, 17120, 17800, 18500, 19220, 19960, 20720, 21500, 22300,
    23120, 23960, 24820, 25700, 26600, 27520, 28460, 29420, 30400, 31400,
    32420, 33460, 34520, 35600, 36700, 37820, 38960, 40120, 41300, 42500,
    43720, 44960, 46220, 47500, 48800, 50120, 51460, 52820, 54200, 55250,
    56350, 57500, 58700, 59800, 60920, 62040, 63180, 64350, 65535,
)

EXPECTED_ITEM_NAME_RECORDS = tuple(
    bytes.fromhex(value)
    for value in (
        "d8a6c952c953",
        "c955c956c957c958",
        "c935c959c95a",
        "82c95cc95d",
        "c951c952c953",
        "c961caf8c95a",
        "86ca95c983",
        "c935c959c95ac966",
        "c955c956c957c958c966",
        "c968c969c96a",
        "c93cc93d",
        "c971c934",
        "c972c973",
        "8d93cb8acac7c86cda71",
        "cbaac80dd8a5",
        "cab7cb61c888c959cb52c86cda71",
        "dad9cb59c87aca23",
        "d818c90ad9accafc",
        "c9e6c996d9acc91d",
        "c8d7c986",
        "c953c986",
        "cbaac80dca25",
        "cbaac80dd8a7",
        "d855d817d9accbe4",
    )
)

EXPECTED_ITEM_PRICES = (
    400, 500, 400, 500, 1200, 2000, 1888, 1200,
    1500, 1000, 2800, 600, 2000, 1800, 1200, 100,
    400, 1000, 100, 500, 9999, 9999, 9999, 9999,
)


class LegacyGlobalDataTests(unittest.TestCase):
    def setUp(self) -> None:
        self.project = RomProject.load(TARGET_ROM)

    def test_only_verified_dc_profiles_expose_the_spec(self) -> None:
        self.assertIsNotNone(MMC5_PROFILE.legacy_global_data)
        self.assertIs(
            DC_EXPANDED_MMC3_LEGACY_PROFILE.legacy_global_data,
            MMC5_PROFILE.legacy_global_data,
        )
        self.assertIs(
            DC_EXPANDED_MMC3_PROFILE.legacy_global_data,
            MMC5_PROFILE.legacy_global_data,
        )
        self.assertIsNone(ORIGINAL_PROFILE.legacy_global_data)
        self.assertIsNone(V51_PROFILE.legacy_global_data)
        self.assertTrue(self.project.supports_legacy_global_data)

        unsupported = object.__new__(RomProject)
        unsupported.legacy_global_data_codec = None
        self.assertFalse(unsupported.supports_legacy_global_data)
        with self.assertRaisesRegex(ValueError, "尚未验证"):
            unsupported.get_experience_totals()

    def test_decodes_all_verified_default_values(self) -> None:
        self.assertEqual(self.project.get_double_hit_values(), (70, 90, 20))
        self.assertEqual(
            self.project.get_damage_formula_values(), (13, 10, 10, 1, 1)
        )
        self.assertEqual(self.project.get_hit_threshold(), 70)
        self.assertEqual(
            self.project.get_item_effect_values(),
            (1, 1, 1, 5, 3, 1, 3, 3, 25, 25, 50),
        )
        self.assertEqual(
            self.project.get_initial_roster(),
            ((4, 9), (5, 13), (6, 15), (7, 17), (8, 19), (9, 23)),
        )
        self.assertEqual(
            self.project.get_distance_hit_corrections(),
            EXPECTED_DISTANCE_HIT_CORRECTIONS,
        )
        self.assertEqual(
            self.project.get_experience_totals(), EXPECTED_EXPERIENCE_TOTALS
        )
        self.assertEqual(
            self.project.get_item_name_records(), EXPECTED_ITEM_NAME_RECORDS
        )
        self.assertEqual(self.project.get_item_prices(), EXPECTED_ITEM_PRICES)
        self.assertEqual(len(self.project.get_experience_totals()), 99)
        self.assertEqual(self.project.get_experience_totals()[49], 15200)
        self.assertEqual(self.project.get_experience_totals()[97:], (64350, 65535))

    def test_code_context_signatures_match_all_three_verified_roms(self) -> None:
        codec = self.project.legacy_global_data_codec
        self.assertIsNotNone(codec)
        assert codec is not None

        for path in CONTEXT_BASELINES:
            with self.subTest(path=path):
                self.assertTrue(path.is_file(), f"缺少交叉核对 ROM：{path}")
                codec._validate_all_code_contexts(path.read_bytes())

    def test_rejects_each_corrupted_operand_opcode_during_initialization(self) -> None:
        codec = self.project.legacy_global_data_codec
        self.assertIsNotNone(codec)
        assert codec is not None
        grouped_contexts = (
            ("双击公式", codec.DOUBLE_HIT_CONTEXTS),
            ("伤害公式", codec.DAMAGE_FORMULA_CONTEXTS),
            ("命中阈值", codec.HIT_THRESHOLD_CONTEXTS),
            ("道具效果", codec.ITEM_EFFECT_CONTEXTS),
        )

        for label, contexts in grouped_contexts:
            for operand_offset, _prefix, _suffix in contexts:
                opcode_offset = operand_offset - 1
                malformed = bytearray(self.project.working)
                malformed[opcode_offset] ^= 0x01
                with self.subTest(label=label, operand=operand_offset):
                    with self.assertRaisesRegex(
                        RomFormatError,
                        rf"{label}操作数 0x{operand_offset:X}.*0x{opcode_offset:X}",
                    ):
                        LegacyGlobalDataCodec(self.project.rom_image, malformed)

    def test_each_formula_write_revalidates_fixed_context(self) -> None:
        codec = self.project.legacy_global_data_codec
        self.assertIsNotNone(codec)
        assert codec is not None
        cases = (
            (
                "双击公式",
                codec.DOUBLE_HIT_CONTEXTS[0][0],
                lambda data: codec.double_hit_patches(data, (71, 91, 21)),
            ),
            (
                "伤害公式",
                codec.DAMAGE_FORMULA_CONTEXTS[0][0],
                lambda data: codec.damage_formula_patches(data, (14, 11, 12, 2, 3)),
            ),
            (
                "命中阈值",
                codec.HIT_THRESHOLD_CONTEXTS[0][0],
                lambda data: codec.hit_threshold_patches(data, 71),
            ),
            (
                "道具效果",
                codec.ITEM_EFFECT_CONTEXTS[0][0],
                lambda data: codec.item_effect_patches(data, (2,) * 11),
            ),
        )

        for label, operand_offset, make_patches in cases:
            fixed_offset = operand_offset + 1
            malformed = bytearray(self.project.working)
            malformed[fixed_offset] ^= 0x01
            with self.subTest(label=label):
                with self.assertRaisesRegex(
                    RomFormatError,
                    rf"{label}操作数 0x{operand_offset:X}.*0x{fixed_offset:X}",
                ):
                    make_patches(malformed)

    def test_all_editable_operands_are_ignored_by_context_signatures(self) -> None:
        spec = self.project.profile.legacy_global_data
        codec = self.project.legacy_global_data_codec
        self.assertIsNotNone(spec)
        self.assertIsNotNone(codec)
        assert spec is not None
        assert codec is not None
        modified = bytearray(self.project.working)

        double_values = (0x31, 0x32, 0x33)
        for value, pair in zip(double_values, spec.double_hit_operand_pairs):
            for offset in pair:
                modified[offset] = value
        damage_values = (0x41, 0x42, 0x43, 0x44, 0x45)
        for offset, value in zip(spec.damage_formula_operand_offsets, damage_values):
            modified[offset] = value
        modified[spec.hit_threshold_operand_offset] = 0x51
        item_values = tuple(range(0x61, 0x61 + 11))
        for offset, value in zip(spec.item_effect_operand_offsets, item_values):
            modified[offset] = value

        edited_codec = LegacyGlobalDataCodec(self.project.rom_image, modified)
        self.assertEqual(edited_codec.double_hit_values(modified), double_values)
        self.assertEqual(edited_codec.damage_formula_values(modified), damage_values)
        self.assertEqual(edited_codec.hit_threshold(modified), 0x51)
        self.assertEqual(edited_codec.item_effect_values(modified), item_values)
        edited_codec.double_hit_patches(modified, (71, 91, 21))
        edited_codec.damage_formula_patches(modified, (14, 11, 12, 2, 3))
        edited_codec.hit_threshold_patches(modified, 71)
        edited_codec.item_effect_patches(modified, (2,) * 11)

    def test_item_names_repack_and_prices_write_only_verified_ranges(self) -> None:
        new_names = tuple(bytes((0x10 + index,)) for index in range(24))
        new_prices = tuple(1000 + index for index in range(24))

        with self.project.transaction("道具名称与价格"):
            self.project.set_item_name_records(new_names)
            self.project.set_item_prices(new_prices)

        self.assertEqual(self.project.get_item_name_records(), new_names)
        self.assertEqual(
            self.project.get_item_name_records(original=True),
            EXPECTED_ITEM_NAME_RECORDS,
        )
        self.assertEqual(self.project.get_item_prices(), new_prices)
        self.assertEqual(
            self.project.get_item_prices(original=True), EXPECTED_ITEM_PRICES
        )

        pointers = tuple(
            int.from_bytes(self.project.working[offset : offset + 2], "little")
            for offset in range(0xCD5A, 0xCD8A, 2)
        )
        self.assertEqual(
            pointers, tuple(0x8D7A + index * 2 for index in range(24))
        )
        self.assertEqual(
            bytes(self.project.working[0xCD8A : 0xCD8A + 48]),
            b"".join(record + b"\xFF" for record in new_names),
        )
        self.assertEqual(
            bytes(self.project.working[0xCD8A + 48 : 0xCE42]),
            b"\xFF" * (0xCE42 - (0xCD8A + 48)),
        )

        actual_offsets = {
            offset
            for offset, (before, after) in enumerate(
                zip(self.project.original, self.project.working)
            )
            if before != after
        }
        allowed_offsets = set(range(0xCD5A, 0xCE42))
        allowed_offsets.update(range(0x15723, 0x15723 + 24 * 2))
        self.assertTrue(actual_offsets)
        self.assertLessEqual(actual_offsets, allowed_offsets)

    def test_item_names_and_prices_reset_undo_and_redo(self) -> None:
        original = bytes(self.project.working)
        new_names = tuple(bytes((index,)) for index in range(24))
        self.project.set_item_name_records(new_names)
        changed_names = bytes(self.project.working)
        self.assertEqual(self.project.undo_description, "道具名称")
        self.assertEqual(self.project.undo(), "道具名称")
        self.assertEqual(bytes(self.project.working), original)
        self.assertEqual(self.project.redo(), "道具名称")
        self.assertEqual(bytes(self.project.working), changed_names)

        self.project.reset_item_name_records()
        self.assertEqual(bytes(self.project.working), original)
        self.assertEqual(self.project.undo(), "道具名称 · 还原")
        self.assertEqual(bytes(self.project.working), changed_names)
        self.assertEqual(self.project.redo(), "道具名称 · 还原")
        self.assertEqual(bytes(self.project.working), original)

        new_prices = tuple(range(24))
        self.project.set_item_prices(new_prices)
        changed_prices = bytes(self.project.working)
        self.assertEqual(self.project.undo(), "道具价格")
        self.assertEqual(bytes(self.project.working), original)
        self.assertEqual(self.project.redo(), "道具价格")
        self.assertEqual(bytes(self.project.working), changed_prices)
        self.project.reset_item_prices()
        self.assertEqual(bytes(self.project.working), original)

    def test_item_name_reset_restores_exact_pointer_and_pool_layout(self) -> None:
        codec = self.project.legacy_global_data_codec
        self.assertIsNotNone(codec)
        assert codec is not None
        spec = codec.spec
        source = bytearray(self.project.original)
        records = list(codec.item_name_records(source))
        self.assertGreaterEqual(len(records[0]), 2)
        records[0] = records[0][:-2]
        table_start = spec.item_name_pointer_table_offset
        table_end = table_start + spec.item_count * 2
        pool_start = spec.item_name_pool_start_offset
        pool_end = spec.item_name_pool_end_offset

        # Build a valid but deliberately non-canonical layout: one leading
        # gap and non-$FF tail bytes.  Semantic decode/repack cannot preserve
        # either detail, while an exact reset must.
        source[pool_start:pool_end] = bytes((0xA5,)) * (pool_end - pool_start)
        source[pool_start] = 0x42
        cursor = pool_start + 1
        pointers: list[int] = []
        for record in records:
            pointers.append(codec._item_name_cpu_pointer(cursor))
            payload = record + bytes((codec.ITEM_NAME_TERMINATOR,))
            source[cursor : cursor + len(payload)] = payload
            cursor += len(payload)
        self.assertLessEqual(cursor, pool_end)
        source[table_start:table_end] = b"".join(
            pointer.to_bytes(2, "little") for pointer in pointers
        )
        codec.item_name_records(source)

        self.project.original = bytes(source)
        # Also prove reset can repair an invalid current pointer table.
        self.project.working[table_start : table_start + 2] = b"\x00\x00"
        self.project.reset_item_name_records()

        self.assertEqual(
            bytes(self.project.working[table_start:table_end]),
            bytes(source[table_start:table_end]),
        )
        self.assertEqual(
            bytes(self.project.working[pool_start:pool_end]),
            bytes(source[pool_start:pool_end]),
        )

    def test_item_name_and_price_input_validation(self) -> None:
        with self.assertRaisesRegex(ValueError, "24 条"):
            self.project.set_item_name_records(EXPECTED_ITEM_NAME_RECORDS[:-1])

        invalid_names = list(EXPECTED_ITEM_NAME_RECORDS)
        invalid_names[0] = b"\x01\xFF\x02"
        with self.assertRaisesRegex(ValueError, r"\$FF"):
            self.project.set_item_name_records(invalid_names)

        oversized_names = [b""] * 24
        oversized_names[0] = b"\x01" * 161
        with self.assertRaisesRegex(ValueError, "超过文本池 184"):
            self.project.set_item_name_records(oversized_names)

        with self.assertRaisesRegex(ValueError, "24 个"):
            self.project.set_item_prices(EXPECTED_ITEM_PRICES[:-1])
        for invalid_price in (-1, 0x10000):
            prices = list(EXPECTED_ITEM_PRICES)
            prices[0] = invalid_price
            with self.subTest(invalid_price=invalid_price), self.assertRaisesRegex(
                ValueError, "0—65535"
            ):
                self.project.set_item_prices(prices)

    def test_malformed_item_name_pointers_and_terminators_are_rejected(self) -> None:
        codec = self.project.legacy_global_data_codec
        self.assertIsNotNone(codec)

        malformed = bytearray(self.project.working)
        malformed[0xCD5A : 0xCD5C] = (0x8000).to_bytes(2, "little")
        with self.assertRaisesRegex(RomFormatError, "超出文本池"):
            codec.item_name_records(malformed)

        malformed = bytearray(self.project.working)
        malformed[0xCD5C : 0xCD5E] = malformed[0xCD5A : 0xCD5C]
        with self.assertRaisesRegex(RomFormatError, "重复指针"):
            codec.item_name_records(malformed)

        malformed = bytearray(self.project.working)
        second_pointer = int.from_bytes(
            malformed[0xCD5C : 0xCD5E], "little"
        )
        malformed[0xCD5E : 0xCD60] = (second_pointer - 1).to_bytes(2, "little")
        with self.assertRaisesRegex(RomFormatError, "不是严格递增"):
            codec.item_name_records(malformed)

        malformed = bytearray(self.project.working)
        malformed[0xCD90] = 0
        with self.assertRaisesRegex(RomFormatError, r"缺少 \$FF"):
            codec.item_name_records(malformed)

    def test_writes_only_the_verified_file_offsets(self) -> None:
        new_double = (71, 91, 21)
        new_damage = (14, 11, 12, 2, 3)
        new_items = (2, 2, 2, 6, 4, 2, 4, 4, 26, 26, 51)
        new_roster = tuple((0x10 + index, 0x40 + index) for index in range(6))
        new_distance = tuple(
            tuple((value + 1) & 0xFF for value in row)
            for row in EXPECTED_DISTANCE_HIT_CORRECTIONS
        )
        new_experience = tuple(value ^ 0xFFFF for value in EXPECTED_EXPERIENCE_TOTALS)

        with self.project.transaction("所有全局表"):
            self.project.set_double_hit_values(new_double)
            self.project.set_damage_formula_values(new_damage)
            self.project.set_hit_threshold(71)
            self.project.set_item_effect_values(new_items)
            self.project.set_initial_roster(new_roster)
            self.project.set_distance_hit_corrections(new_distance)
            self.project.set_experience_totals(new_experience)

        spec = self.project.profile.legacy_global_data
        self.assertIsNotNone(spec)
        expected_offsets = set(range(0xB4D8, 0xB4D8 + 64))
        expected_offsets.update(range(0xB530, 0xB530 + 99 * 2))
        expected_offsets.update(range(0x3965D, 0x3965D + 12))
        expected_offsets.add(0xA44E)
        expected_offsets.update((0x780E4, 0x780C5, 0x780EB, 0x9999, 0x99A0))
        expected_offsets.update(
            (0x140CF, 0x140D6, 0x140DD, 0x140E4, 0x140EB, 0x140F2,
             0x140F9, 0x14100, 0x14107, 0x1410E, 0x14115)
        )
        expected_offsets.update(
            (0x78109, 0x7815A, 0x78127, 0x78178, 0x78138, 0x78189)
        )
        actual_offsets = {
            offset
            for offset, (before, after) in enumerate(
                zip(self.project.original, self.project.working)
            )
            if before != after
        }
        self.assertEqual(actual_offsets, expected_offsets)
        self.assertEqual(self.project.working[0x3965D + 12], 0xFF)
        for value, pair in zip(new_double, spec.double_hit_operand_pairs):
            self.assertEqual(
                tuple(self.project.working[offset] for offset in pair),
                (value, value),
            )

    def test_all_verified_global_tables_survive_rom_save_and_reopen(self) -> None:
        names = list(self.project.get_item_name_records())
        names[0], names[1] = names[1], names[0]
        prices = list(self.project.get_item_prices())
        prices[0] += 1
        experience = list(self.project.get_experience_totals())
        experience[0] += 1
        corrections = [list(row) for row in self.project.get_distance_hit_corrections()]
        corrections[3][15] += 1

        with self.project.transaction("全局表落盘回归"):
            self.project.set_double_hit_values((71, 91, 21))
            self.project.set_damage_formula_values((14, 11, 12, 2, 3))
            self.project.set_hit_threshold(69)
            self.project.set_item_effect_values((2, 2, 2, 6, 4, 2, 4, 4, 26, 26, 51))
            self.project.set_initial_roster(((0, 0), (5, 13), (6, 15), (7, 17), (8, 19), (9, 23)))
            self.project.set_distance_hit_corrections(corrections)
            self.project.set_experience_totals(experience)
            self.project.set_item_name_records(names)
            self.project.set_item_prices(prices)

        with tempfile.TemporaryDirectory() as directory:
            destination = Path(directory) / "global-roundtrip.nes"
            self.project.save_as(destination, make_backup=False)
            reopened = RomProject.load(destination)

        self.assertEqual(reopened.get_double_hit_values(), (71, 91, 21))
        self.assertEqual(reopened.get_damage_formula_values(), (14, 11, 12, 2, 3))
        self.assertEqual(reopened.get_hit_threshold(), 69)
        self.assertEqual(
            reopened.get_item_effect_values(),
            (2, 2, 2, 6, 4, 2, 4, 4, 26, 26, 51),
        )
        self.assertEqual(reopened.get_initial_roster()[0], (0, 0))
        self.assertEqual(reopened.get_distance_hit_corrections()[3][15], corrections[3][15])
        self.assertEqual(reopened.get_experience_totals()[0], experience[0])
        self.assertEqual(reopened.get_item_name_records(), tuple(names))
        self.assertEqual(reopened.get_item_prices(), tuple(prices))

    def test_rejects_zero_divisors_and_out_of_range_roster_ids(self) -> None:
        for index in (2, 4):
            values = list(self.project.get_damage_formula_values())
            values[index] = 0
            with self.subTest(index=index), self.assertRaisesRegex(ValueError, "不能为 0"):
                self.project.set_damage_formula_values(values)

        roster = list(self.project.get_initial_roster())
        roster[0] = (self.project.profile.character_name_count, roster[0][1])
        with self.assertRaisesRegex(ValueError, "人物 ID"):
            self.project.set_initial_roster(roster)

        roster = list(self.project.get_initial_roster())
        roster[0] = (roster[0][0], self.project.unit_count)
        with self.assertRaisesRegex(ValueError, "机体 ID"):
            self.project.set_initial_roster(roster)

    def test_grouped_changes_and_resets_are_undoable_and_redoable(self) -> None:
        original = bytes(self.project.working)
        with self.project.transaction("全局表测试修改"):
            self.project.set_double_hit_values((71, 91, 21))
            self.project.set_damage_formula_values((14, 11, 12, 2, 3))
            self.project.set_hit_threshold(0)
            self.project.set_item_effect_values((2,) * 11)
            self.project.set_initial_roster(((1, 1),) * 6)
            self.project.set_distance_hit_corrections(((1,) * 16,) * 4)
            self.project.set_experience_totals(tuple(range(99)))
        changed = bytes(self.project.working)
        self.assertNotEqual(changed, original)
        self.assertEqual(self.project.undo(), "全局表测试修改")
        self.assertEqual(bytes(self.project.working), original)
        self.assertEqual(self.project.redo(), "全局表测试修改")
        self.assertEqual(bytes(self.project.working), changed)

        with self.project.transaction("全局表测试还原"):
            self.project.reset_double_hit_values()
            self.project.reset_damage_formula_values()
            self.project.reset_hit_threshold()
            self.project.reset_item_effect_values()
            self.project.reset_initial_roster()
            self.project.reset_distance_hit_corrections()
            self.project.reset_experience_totals()
        self.assertEqual(bytes(self.project.working), original)
        self.assertEqual(self.project.undo(), "全局表测试还原")
        self.assertEqual(bytes(self.project.working), changed)
        self.assertEqual(self.project.redo(), "全局表测试还原")
        self.assertEqual(bytes(self.project.working), original)

    def test_malformed_mirrors_sentinel_and_boundaries_are_rejected(self) -> None:
        self.project.working[0x7815A] ^= 1
        with self.assertRaisesRegex(RomFormatError, "镜像操作数不一致"):
            self.project.get_double_hit_values()
        self.project.working[0x7815A] ^= 1

        self.project.working[0x3965D + 12] = 0
        with self.assertRaisesRegex(RomFormatError, r"\$FF"):
            self.project.get_initial_roster()

        with self.assertRaisesRegex(RomFormatError, "超出 ROM"):
            LegacyGlobalDataCodec(self.project.rom_image, b"")


if __name__ == "__main__":
    unittest.main()
