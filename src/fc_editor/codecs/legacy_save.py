from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable


class LegacySaveFormatError(ValueError):
    """Raised when an SRAM file does not match the verified DC save layout."""


@dataclass(frozen=True)
class LegacySaveRosterEntry:
    index: int
    character_id: int
    unit_id: int
    level: int
    movement_bonus: int
    strength_bonus: int
    defense_bonus: int
    speed_bonus: int
    hp_bonus: int
    type_flags: int
    spirit_bonus: int
    experience: int

    @property
    def occupied(self) -> bool:
        return self.character_id not in (0x00, 0xFF)


@dataclass(frozen=True)
class LegacySaveSlot:
    number: int
    data_offset: int
    checksum_offset: int | None
    raw: bytes
    stored_checksum: int | None
    calculated_checksum: int
    checksum_valid: bool
    chapter_raw: int
    money: int
    roster: tuple[LegacySaveRosterEntry, ...]

    @property
    def chapter_number(self) -> int | None:
        if 0 <= self.chapter_raw < LegacySaveCodec.CHAPTER_COUNT:
            return self.chapter_raw + 1
        return None

    @property
    def occupied(self) -> bool:
        return (
            self.checksum_valid
            and self.chapter_number is not None
            and any(entry.occupied for entry in self.roster)
        )

    @property
    def occupied_roster(self) -> tuple[LegacySaveRosterEntry, ...]:
        return tuple(entry for entry in self.roster if entry.occupied)


@dataclass(frozen=True)
class LegacyBattleEntry:
    index: int
    team: str
    character_id: int
    unit_image: int
    level: int
    movement: int
    strength: int
    defense: int
    speed: int
    hp: int
    max_hp: int

    @property
    def occupied(self) -> bool:
        return self.character_id not in (0x00, 0xFF)


@dataclass(frozen=True)
class LegacySaveDocument:
    raw: bytes
    active: LegacySaveSlot
    slots: tuple[LegacySaveSlot, ...]
    allies: tuple[LegacyBattleEntry, ...]
    enemies: tuple[LegacyBattleEntry, ...]


class LegacySaveCodec:
    """Codec for the verified 8 KiB battery-backed SRAM layout.

    The three persistent save slots are 0xFB-byte records followed by a
    little-endian 16-bit sum.  The active 0x437-byte battle block has no
    adjacent checksum; the game keeps a second checked copy separately.
    """

    SAVE_SIZE = 0x2000
    CHAPTER_COUNT = 32
    ROSTER_COUNT = 16
    ACTIVE_OFFSET = 0x1411
    ACTIVE_LENGTH = 0x0437
    BACKUP_OFFSET = 0x1848
    BACKUP_CHECKSUM_OFFSET = 0x1C7F
    SLOT_LENGTH = 0x00FB
    SLOT_DATA_OFFSETS = (0x1C81, 0x1D7E, 0x1E7B)
    SLOT_CHECKSUM_OFFSETS = (0x1D7C, 0x1E79, 0x1F76)

    CHAPTER_OFFSET = 0x00
    MONEY_OFFSET = 0x29
    CHARACTER_OFFSET = 0x2B
    UNIT_OFFSET = 0x3B
    LEVEL_OFFSET = 0x4B
    MOVEMENT_BONUS_OFFSET = 0x5B
    STRENGTH_BONUS_OFFSET = 0x6B
    DEFENSE_BONUS_OFFSET = 0x7B
    SPEED_BONUS_OFFSET = 0x8B
    HP_BONUS_LOW_OFFSET = 0x9B
    HP_BONUS_HIGH_OFFSET = 0xAB
    TYPE_FLAGS_OFFSET = 0xBB
    SPIRIT_BONUS_OFFSET = 0xCB
    EXP_LOW_OFFSET = 0xDB
    EXP_HIGH_OFFSET = 0xEB

    _BATTLE_LAYOUT = {
        "ally": {
            "count": 14,
            "character": 0x126,
            "unit_image": 0x146,
            "level": 0x166,
            "movement": 0x226,
            "strength": 0x246,
            "defense": 0x266,
            "speed": 0x286,
            "hp_low": 0x2A6,
            "hp_high": 0x2C6,
            "max_hp_low": 0x2E6,
            "max_hp_high": 0x306,
        },
        "enemy": {
            "count": 18,
            "character": 0x134,
            "unit_image": 0x154,
            "level": 0x174,
            "movement": 0x234,
            "strength": 0x254,
            "defense": 0x274,
            "speed": 0x294,
            "hp_low": 0x2B4,
            "hp_high": 0x2D4,
            "max_hp_low": 0x2F4,
            "max_hp_high": 0x314,
        },
    }

    @classmethod
    def validate_size(cls, data: bytes | bytearray) -> None:
        if len(data) != cls.SAVE_SIZE:
            raise LegacySaveFormatError(
                f"存档必须恰好为 {cls.SAVE_SIZE} 字节，当前为 {len(data)} 字节。"
            )

    @staticmethod
    def checksum(raw: bytes | bytearray) -> int:
        return sum(raw) & 0xFFFF

    @classmethod
    def _decode_roster(cls, raw: bytes) -> tuple[LegacySaveRosterEntry, ...]:
        entries: list[LegacySaveRosterEntry] = []
        for index in range(cls.ROSTER_COUNT):
            entries.append(
                LegacySaveRosterEntry(
                    index=index,
                    character_id=raw[cls.CHARACTER_OFFSET + index],
                    unit_id=raw[cls.UNIT_OFFSET + index],
                    level=raw[cls.LEVEL_OFFSET + index],
                    movement_bonus=raw[cls.MOVEMENT_BONUS_OFFSET + index],
                    strength_bonus=raw[cls.STRENGTH_BONUS_OFFSET + index],
                    defense_bonus=raw[cls.DEFENSE_BONUS_OFFSET + index],
                    speed_bonus=raw[cls.SPEED_BONUS_OFFSET + index],
                    hp_bonus=(
                        raw[cls.HP_BONUS_LOW_OFFSET + index]
                        | raw[cls.HP_BONUS_HIGH_OFFSET + index] << 8
                    ),
                    type_flags=raw[cls.TYPE_FLAGS_OFFSET + index],
                    spirit_bonus=raw[cls.SPIRIT_BONUS_OFFSET + index],
                    experience=(
                        raw[cls.EXP_LOW_OFFSET + index]
                        | raw[cls.EXP_HIGH_OFFSET + index] << 8
                    ),
                )
            )
        return tuple(entries)

    @classmethod
    def _decode_slot(
        cls,
        data: bytes,
        *,
        number: int,
        data_offset: int,
        checksum_offset: int | None,
    ) -> LegacySaveSlot:
        raw = data[data_offset : data_offset + cls.SLOT_LENGTH]
        if len(raw) != cls.SLOT_LENGTH:
            raise LegacySaveFormatError(f"存档 {number} 数据块不完整。")
        calculated = cls.checksum(raw)
        if checksum_offset is None:
            stored = None
            valid = True
        else:
            checksum_raw = data[checksum_offset : checksum_offset + 2]
            if len(checksum_raw) != 2:
                raise LegacySaveFormatError(f"存档 {number} 校验和不完整。")
            stored = int.from_bytes(checksum_raw, "little")
            valid = stored == calculated
        return LegacySaveSlot(
            number=number,
            data_offset=data_offset,
            checksum_offset=checksum_offset,
            raw=raw,
            stored_checksum=stored,
            calculated_checksum=calculated,
            checksum_valid=valid,
            chapter_raw=raw[cls.CHAPTER_OFFSET],
            money=int.from_bytes(
                raw[cls.MONEY_OFFSET : cls.MONEY_OFFSET + 2], "little"
            ),
            roster=cls._decode_roster(raw),
        )

    @classmethod
    def _decode_battle_entries(
        cls, data: bytes, team: str
    ) -> tuple[LegacyBattleEntry, ...]:
        layout = cls._BATTLE_LAYOUT[team]
        base = cls.ACTIVE_OFFSET
        entries: list[LegacyBattleEntry] = []
        for index in range(layout["count"]):
            character_id = data[base + layout["character"] + index]
            entry = LegacyBattleEntry(
                index=index,
                team=team,
                character_id=character_id,
                unit_image=data[base + layout["unit_image"] + index],
                level=data[base + layout["level"] + index],
                movement=data[base + layout["movement"] + index],
                strength=data[base + layout["strength"] + index],
                defense=data[base + layout["defense"] + index],
                speed=data[base + layout["speed"] + index],
                hp=(
                    data[base + layout["hp_low"] + index]
                    | data[base + layout["hp_high"] + index] << 8
                ),
                max_hp=(
                    data[base + layout["max_hp_low"] + index]
                    | data[base + layout["max_hp_high"] + index] << 8
                ),
            )
            if entry.occupied:
                entries.append(entry)
        return tuple(entries)

    @classmethod
    def decode(cls, data: bytes | bytearray) -> LegacySaveDocument:
        cls.validate_size(data)
        source = bytes(data)
        active = cls._decode_slot(
            source,
            number=0,
            data_offset=cls.ACTIVE_OFFSET,
            checksum_offset=None,
        )
        slots = tuple(
            cls._decode_slot(
                source,
                number=index + 1,
                data_offset=data_offset,
                checksum_offset=checksum_offset,
            )
            for index, (data_offset, checksum_offset) in enumerate(
                zip(cls.SLOT_DATA_OFFSETS, cls.SLOT_CHECKSUM_OFFSETS, strict=True)
            )
        )
        return LegacySaveDocument(
            raw=source,
            active=active,
            slots=slots,
            allies=cls._decode_battle_entries(source, "ally"),
            enemies=cls._decode_battle_entries(source, "enemy"),
        )

    @staticmethod
    def _byte(value: int, label: str) -> int:
        if not isinstance(value, int) or not 0 <= value <= 0xFF:
            raise ValueError(f"{label}必须为 0—255 的整数。")
        return value

    @staticmethod
    def _word(value: int, label: str) -> int:
        if not isinstance(value, int) or not 0 <= value <= 0xFFFF:
            raise ValueError(f"{label}必须为 0—65535 的整数。")
        return value

    @classmethod
    def _encode_roster(
        cls, raw: bytearray, entries: Iterable[LegacySaveRosterEntry]
    ) -> None:
        seen: set[int] = set()
        for entry in entries:
            if not 0 <= entry.index < cls.ROSTER_COUNT:
                raise ValueError("队伍序号必须在 0—15 之间。")
            if entry.index in seen:
                raise ValueError(f"队伍序号 {entry.index} 重复。")
            seen.add(entry.index)
            index = entry.index
            raw[cls.CHARACTER_OFFSET + index] = cls._byte(
                entry.character_id, "人物编号"
            )
            raw[cls.UNIT_OFFSET + index] = cls._byte(entry.unit_id, "机体编号")
            raw[cls.LEVEL_OFFSET + index] = cls._byte(entry.level, "等级")
            raw[cls.MOVEMENT_BONUS_OFFSET + index] = cls._byte(
                entry.movement_bonus, "机动附加"
            )
            raw[cls.STRENGTH_BONUS_OFFSET + index] = cls._byte(
                entry.strength_bonus, "强度附加"
            )
            raw[cls.DEFENSE_BONUS_OFFSET + index] = cls._byte(
                entry.defense_bonus, "防御附加"
            )
            raw[cls.SPEED_BONUS_OFFSET + index] = cls._byte(
                entry.speed_bonus, "速度附加"
            )
            hp_bonus = cls._word(entry.hp_bonus, "HP 附加")
            raw[cls.HP_BONUS_LOW_OFFSET + index] = hp_bonus & 0xFF
            raw[cls.HP_BONUS_HIGH_OFFSET + index] = hp_bonus >> 8
            raw[cls.TYPE_FLAGS_OFFSET + index] = cls._byte(
                entry.type_flags, "队伍状态"
            )
            raw[cls.SPIRIT_BONUS_OFFSET + index] = cls._byte(
                entry.spirit_bonus, "精神附加"
            )
            experience = cls._word(entry.experience, "EXP")
            raw[cls.EXP_LOW_OFFSET + index] = experience & 0xFF
            raw[cls.EXP_HIGH_OFFSET + index] = experience >> 8

    @classmethod
    def replace_slot(
        cls,
        data: bytes | bytearray,
        slot_number: int,
        *,
        chapter_number: int,
        roster: Iterable[LegacySaveRosterEntry],
        money: int | None = None,
    ) -> bytes:
        document = cls.decode(data)
        if not 1 <= slot_number <= len(document.slots):
            raise ValueError("存档槽必须为 1、2 或 3。")
        if not 1 <= chapter_number <= cls.CHAPTER_COUNT:
            raise ValueError(f"关卡必须在 1—{cls.CHAPTER_COUNT} 之间。")
        slot = document.slots[slot_number - 1]
        source = slot.raw if slot.occupied else document.active.raw
        raw = bytearray(source)
        raw[cls.CHAPTER_OFFSET] = chapter_number - 1
        if money is not None:
            normalized_money = cls._word(money, "金钱")
            raw[cls.MONEY_OFFSET : cls.MONEY_OFFSET + 2] = normalized_money.to_bytes(
                2, "little"
            )
        cls._encode_roster(raw, roster)

        staged = bytearray(document.raw)
        staged[slot.data_offset : slot.data_offset + cls.SLOT_LENGTH] = raw
        assert slot.checksum_offset is not None
        staged[slot.checksum_offset : slot.checksum_offset + 2] = cls.checksum(
            raw
        ).to_bytes(2, "little")
        return bytes(staged)

    @classmethod
    def replace_battle_entries(
        cls,
        data: bytes | bytearray,
        team: str,
        entries: Iterable[LegacyBattleEntry],
    ) -> bytes:
        cls.validate_size(data)
        if team not in cls._BATTLE_LAYOUT:
            raise ValueError("战场阵营必须为 ally 或 enemy。")
        layout = cls._BATTLE_LAYOUT[team]
        staged = bytearray(data)
        base = cls.ACTIVE_OFFSET
        seen: set[int] = set()
        for entry in entries:
            if entry.team != team:
                raise ValueError("战场记录阵营与目标阵营不一致。")
            if not 0 <= entry.index < layout["count"]:
                raise ValueError("战场记录序号超出固定容量。")
            if entry.index in seen:
                raise ValueError(f"战场记录序号 {entry.index} 重复。")
            seen.add(entry.index)
            index = entry.index
            for key, label in (
                ("character_id", "人物编号"),
                ("unit_image", "机体图像"),
                ("level", "等级"),
                ("movement", "机动"),
                ("strength", "强度"),
                ("defense", "防御"),
                ("speed", "速度"),
            ):
                staged[base + layout[key.replace("character_id", "character")] + index] = cls._byte(
                    getattr(entry, key), label
                )
            hp = cls._word(entry.hp, "当前 HP")
            maximum = cls._word(entry.max_hp, "最大 HP")
            staged[base + layout["hp_low"] + index] = hp & 0xFF
            staged[base + layout["hp_high"] + index] = hp >> 8
            staged[base + layout["max_hp_low"] + index] = maximum & 0xFF
            staged[base + layout["max_hp_high"] + index] = maximum >> 8
        return bytes(staged)
