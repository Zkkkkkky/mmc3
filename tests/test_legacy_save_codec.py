from __future__ import annotations

from dataclasses import replace
import unittest

from fc_editor.codecs.legacy_save import (
    LegacyBattleEntry,
    LegacySaveCodec,
    LegacySaveFormatError,
)


def _sample_save() -> bytes:
    data = bytearray(LegacySaveCodec.SAVE_SIZE)
    active = bytearray(LegacySaveCodec.SLOT_LENGTH)
    active[LegacySaveCodec.CHAPTER_OFFSET] = 4
    active[LegacySaveCodec.MONEY_OFFSET : LegacySaveCodec.MONEY_OFFSET + 2] = (
        4321
    ).to_bytes(2, "little")
    active[LegacySaveCodec.CHARACTER_OFFSET] = 4
    active[LegacySaveCodec.UNIT_OFFSET] = 9
    active[LegacySaveCodec.LEVEL_OFFSET] = 8
    active[LegacySaveCodec.MOVEMENT_BONUS_OFFSET] = 1
    active[LegacySaveCodec.STRENGTH_BONUS_OFFSET] = 2
    active[LegacySaveCodec.DEFENSE_BONUS_OFFSET] = 3
    active[LegacySaveCodec.SPEED_BONUS_OFFSET] = 4
    active[LegacySaveCodec.HP_BONUS_LOW_OFFSET] = 0x34
    active[LegacySaveCodec.HP_BONUS_HIGH_OFFSET] = 0x12
    active[LegacySaveCodec.TYPE_FLAGS_OFFSET] = 0x80
    active[LegacySaveCodec.SPIRIT_BONUS_OFFSET] = 6
    active[LegacySaveCodec.EXP_LOW_OFFSET] = 0x78
    active[LegacySaveCodec.EXP_HIGH_OFFSET] = 0x56
    data[
        LegacySaveCodec.ACTIVE_OFFSET : LegacySaveCodec.ACTIVE_OFFSET
        + LegacySaveCodec.SLOT_LENGTH
    ] = active

    first = bytearray(active)
    first[LegacySaveCodec.CHAPTER_OFFSET] = 6
    first_offset = LegacySaveCodec.SLOT_DATA_OFFSETS[0]
    first_checksum = LegacySaveCodec.SLOT_CHECKSUM_OFFSETS[0]
    data[first_offset : first_offset + LegacySaveCodec.SLOT_LENGTH] = first
    data[first_checksum : first_checksum + 2] = LegacySaveCodec.checksum(first).to_bytes(
        2, "little"
    )

    second_offset = LegacySaveCodec.SLOT_DATA_OFFSETS[1]
    data[second_offset] = 0xFF

    enemy_layout = LegacySaveCodec._BATTLE_LAYOUT["enemy"]
    base = LegacySaveCodec.ACTIVE_OFFSET
    data[base + enemy_layout["character"]] = 0x2F
    data[base + enemy_layout["unit_image"]] = 3
    data[base + enemy_layout["level"]] = 12
    data[base + enemy_layout["movement"]] = 7
    data[base + enemy_layout["strength"]] = 80
    data[base + enemy_layout["defense"]] = 70
    data[base + enemy_layout["speed"]] = 60
    data[base + enemy_layout["hp_low"]] = 0xE8
    data[base + enemy_layout["hp_high"]] = 0x03
    data[base + enemy_layout["max_hp_low"]] = 0xD0
    data[base + enemy_layout["max_hp_high"]] = 0x07
    return bytes(data)


class LegacySaveCodecTests(unittest.TestCase):
    def test_decode_checks_slots_roster_and_active_enemy(self) -> None:
        document = LegacySaveCodec.decode(_sample_save())
        self.assertEqual(document.active.chapter_number, 5)
        self.assertEqual(document.active.money, 4321)
        self.assertEqual(len(document.active.occupied_roster), 1)
        entry = document.active.occupied_roster[0]
        self.assertEqual(
            (
                entry.character_id,
                entry.unit_id,
                entry.level,
                entry.movement_bonus,
                entry.strength_bonus,
                entry.defense_bonus,
                entry.speed_bonus,
                entry.hp_bonus,
                entry.type_flags,
                entry.spirit_bonus,
                entry.experience,
            ),
            (4, 9, 8, 1, 2, 3, 4, 0x1234, 0x80, 6, 0x5678),
        )
        self.assertTrue(document.slots[0].occupied)
        self.assertEqual(document.slots[0].chapter_number, 7)
        self.assertFalse(document.slots[1].occupied)
        self.assertFalse(document.slots[1].checksum_valid)
        self.assertEqual(len(document.enemies), 1)
        self.assertEqual(document.enemies[0].character_id, 0x2F)
        self.assertEqual(document.enemies[0].hp, 1000)
        self.assertEqual(document.enemies[0].max_hp, 2000)

    def test_replace_slot_preserves_every_unrelated_byte_and_updates_checksum(self) -> None:
        before = _sample_save()
        document = LegacySaveCodec.decode(before)
        changed_entry = replace(
            document.slots[0].roster[0],
            level=22,
            speed_bonus=9,
            experience=60000,
        )
        after = LegacySaveCodec.replace_slot(
            before,
            1,
            chapter_number=9,
            roster=(changed_entry,),
        )
        decoded = LegacySaveCodec.decode(after)
        self.assertTrue(decoded.slots[0].checksum_valid)
        self.assertEqual(decoded.slots[0].chapter_number, 9)
        self.assertEqual(decoded.slots[0].roster[0].level, 22)
        self.assertEqual(decoded.slots[0].roster[0].speed_bonus, 9)
        self.assertEqual(decoded.slots[0].roster[0].experience, 60000)

        allowed = {
            LegacySaveCodec.SLOT_DATA_OFFSETS[0] + LegacySaveCodec.CHAPTER_OFFSET,
            LegacySaveCodec.SLOT_DATA_OFFSETS[0] + LegacySaveCodec.LEVEL_OFFSET,
            LegacySaveCodec.SLOT_DATA_OFFSETS[0]
            + LegacySaveCodec.SPEED_BONUS_OFFSET,
            LegacySaveCodec.SLOT_DATA_OFFSETS[0] + LegacySaveCodec.EXP_LOW_OFFSET,
            LegacySaveCodec.SLOT_DATA_OFFSETS[0] + LegacySaveCodec.EXP_HIGH_OFFSET,
            LegacySaveCodec.SLOT_CHECKSUM_OFFSETS[0],
            LegacySaveCodec.SLOT_CHECKSUM_OFFSETS[0] + 1,
        }
        changed = {index for index, pair in enumerate(zip(before, after)) if pair[0] != pair[1]}
        self.assertLessEqual(changed, allowed)

    def test_replace_empty_slot_uses_active_record_as_the_safe_template(self) -> None:
        before = _sample_save()
        active = LegacySaveCodec.decode(before).active
        after = LegacySaveCodec.replace_slot(
            before,
            2,
            chapter_number=10,
            roster=active.roster,
        )
        slot = LegacySaveCodec.decode(after).slots[1]
        self.assertTrue(slot.occupied)
        self.assertTrue(slot.checksum_valid)
        self.assertEqual(slot.chapter_number, 10)
        self.assertEqual(slot.roster[0], active.roster[0])

    def test_replace_enemy_changes_only_verified_active_arrays(self) -> None:
        before = _sample_save()
        enemy = LegacySaveCodec.decode(before).enemies[0]
        changed = replace(enemy, level=13, speed=61, hp=999, max_hp=1999)
        after = LegacySaveCodec.replace_battle_entries(before, "enemy", (changed,))
        decoded = LegacySaveCodec.decode(after).enemies[0]
        self.assertEqual((decoded.level, decoded.speed, decoded.hp, decoded.max_hp), (13, 61, 999, 1999))
        self.assertEqual(
            before[
                LegacySaveCodec.SLOT_DATA_OFFSETS[0] : LegacySaveCodec.SLOT_CHECKSUM_OFFSETS[0]
                + 2
            ],
            after[
                LegacySaveCodec.SLOT_DATA_OFFSETS[0] : LegacySaveCodec.SLOT_CHECKSUM_OFFSETS[0]
                + 2
            ],
        )

    def test_prepare_weapon_animation_fixture_updates_active_and_checked_backup(self) -> None:
        prepared = bytearray(_sample_save())
        ally_layout = LegacySaveCodec._BATTLE_LAYOUT["ally"]
        prepared[
            LegacySaveCodec.ACTIVE_OFFSET + ally_layout["character"]
        ] = 0x04
        before = bytes(prepared)
        after = LegacySaveCodec.prepare_weapon_animation_fixture(before, unit_id=0x11)
        changed = {
            index
            for index, (old, new) in enumerate(zip(before, after, strict=True))
            if old != new
        }
        expected_data = {
            LegacySaveCodec.ACTIVE_OFFSET + LegacySaveCodec.DEPLOYED_UNIT_OFFSET,
            LegacySaveCodec.ACTIVE_OFFSET + LegacySaveCodec.ENEMY_Y_OFFSET,
            LegacySaveCodec.BACKUP_OFFSET + LegacySaveCodec.DEPLOYED_UNIT_OFFSET,
            LegacySaveCodec.BACKUP_OFFSET + LegacySaveCodec.ENEMY_Y_OFFSET,
        }
        self.assertLessEqual(
            changed,
            expected_data
            | {
                LegacySaveCodec.BACKUP_CHECKSUM_OFFSET,
                LegacySaveCodec.BACKUP_CHECKSUM_OFFSET + 1,
            },
        )
        self.assertTrue(expected_data <= changed)
        self.assertEqual(
            after[LegacySaveCodec.ACTIVE_OFFSET + LegacySaveCodec.DEPLOYED_UNIT_OFFSET],
            0x11,
        )
        backup = after[
            LegacySaveCodec.BACKUP_OFFSET : LegacySaveCodec.BACKUP_CHECKSUM_OFFSET
        ]
        stored = int.from_bytes(
            after[
                LegacySaveCodec.BACKUP_CHECKSUM_OFFSET :
                LegacySaveCodec.BACKUP_CHECKSUM_OFFSET + 2
            ],
            "little",
        )
        self.assertEqual(LegacySaveCodec.checksum(backup), stored)

    def test_rejects_non_8k_files(self) -> None:
        with self.assertRaisesRegex(LegacySaveFormatError, "8192"):
            LegacySaveCodec.decode(bytes(256))


if __name__ == "__main__":
    unittest.main()
