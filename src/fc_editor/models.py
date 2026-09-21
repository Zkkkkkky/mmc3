from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Literal, Mapping

from .constants import UNIT_RECORD_SIZE, WEAPON_RECORD_SIZE


EvidenceLevel = Literal["confirmed", "candidate", "unknown"]
ByteOrder = Literal["little", "big"]


@dataclass(frozen=True)
class FieldSpec:
    key: str
    label: str
    record_offset: int
    width: int
    minimum: int
    maximum: int
    description: str
    byte_order: ByteOrder = "little"
    mask: int | None = None
    shift: int = 0
    display_scale: int = 1
    choices: Mapping[int, str] | None = None
    evidence: EvidenceLevel = "confirmed"

    def __post_init__(self) -> None:
        if self.width <= 0:
            raise ValueError("字段宽度必须大于零。")
        if self.record_offset < 0 or self.record_offset + self.width > UNIT_RECORD_SIZE:
            raise ValueError(f"字段 {self.key} 超出机体记录。")
        if self.minimum > self.maximum:
            raise ValueError(f"字段 {self.key} 的数值范围无效。")

    def decode(self, raw: bytes) -> int:
        encoded = int.from_bytes(
            raw[self.record_offset : self.record_offset + self.width],
            self.byte_order,
        )
        if self.mask is not None:
            encoded = (encoded & self.mask) >> self.shift
        return encoded

    def encode_into(self, raw: bytes, value: int) -> bytes:
        if not self.minimum <= value <= self.maximum:
            raise ValueError(f"{self.label}必须在 {self.minimum}—{self.maximum} 之间。")
        result = bytearray(raw)
        start = self.record_offset
        end = start + self.width
        if self.mask is None:
            result[start:end] = value.to_bytes(self.width, self.byte_order)
        else:
            encoded = int.from_bytes(result[start:end], self.byte_order)
            encoded = (encoded & ~self.mask) | ((value << self.shift) & self.mask)
            result[start:end] = encoded.to_bytes(self.width, self.byte_order)
        return bytes(result)


UNIT_FIELDS = (
    FieldSpec("movement", "移动力", 0x03, 1, 0, 255, "状态画面的“移动”数值。"),
    FieldSpec("speed", "速度", 0x04, 1, 0, 255, "状态画面的“速度”数值。"),
    FieldSpec("strength", "强度", 0x05, 1, 0, 255, "状态画面的“强度”数值。"),
    FieldSpec("defense", "防卫", 0x06, 1, 0, 255, "状态画面的“防卫”数值。"),
    # Keep the historical project-operation key for existing .dcmod files.
    FieldSpec(
        "upgrade", "基础金钱", 0x07, 1, 0, 255,
        "击坠金钱；ROM 以十位为单位存储，界面按游戏数值显示。",
        display_scale=10,
    ),
    FieldSpec("experience", "基础经验", 0x0A, 1, 0, 255, "击坠经验基值；等级差和精神效果另由运行时计算。"),
    FieldSpec("special", "特殊技能", 0x01, 1, 0, 255, "完整特技字节；保留当前 ROM 自定义的组合位。"),
    FieldSpec("terrain", "适应地形", 0x00, 1, 0, 3, "机体类型低两位：0空、1陆、2海；3为原码保留值。", mask=0x03),
    FieldSpec(
        "transform",
        "变形关系",
        0x00,
        1,
        0,
        63,
        "机体类型高六位；按旧修改器的二段、三段、四段变形编码显示。",
        mask=0xFC,
        shift=2,
        choices={
            0: "无",
            1: "二段变形1号机",
            5: "二段变形2号机",
            2: "三段变形总机（慎用）",
            6: "三段变形1号机（慎用）",
            10: "三段变形2号机（慎用）",
            14: "三段变形3号机（慎用）",
            3: "四段变形1号机",
            7: "四段变形2号机",
            11: "四段变形3号机",
            15: "四段变形4号机",
        },
    ),
    FieldSpec("hp", "基础 HP", 0x08, 2, 0, 65535, "16 位小端 HP；魔神Z原值为 360。"),
    FieldSpec(
        "speed_growth",
        "速度成长型",
        0x0C,
        1,
        0,
        49,
        "成长曲线 ID；升级时由代码累加到速度。",
    ),
    FieldSpec(
        "strength_growth",
        "强度成长型",
        0x0D,
        1,
        0,
        49,
        "成长曲线 ID；升级时由代码累加到强度。",
    ),
    FieldSpec(
        "defense_growth",
        "防卫成长型",
        0x0E,
        1,
        0,
        49,
        "成长曲线 ID；升级时由代码累加到防卫。",
    ),
    FieldSpec(
        "hp_growth",
        "HP 成长型",
        0x0F,
        1,
        0,
        49,
        "成长曲线 ID；升级时由代码累加到 16 位 HP。",
    ),
)
UNIT_CANDIDATE_FIELDS = (
    FieldSpec(
        "candidate_00",
        "候选：特殊标志",
        0x00,
        1,
        0,
        255,
        "疑似包含特殊能力或形态标志，尚未确认。",
        evidence="candidate",
    ),
    FieldSpec(
        "candidate_01",
        "候选：扩展标志",
        0x01,
        1,
        0,
        255,
        "部分高等级敌机使用高位，含义尚未确认。",
        evidence="candidate",
    ),
    FieldSpec(
        "candidate_02",
        "地图小图标",
        0x02,
        1,
        0,
        255,
        "地图小图标的首个 8×8 图块编号；每个图标连续使用四块。",
        evidence="confirmed",
    ),
    FieldSpec(
        "candidate_0a",
        "候选：击坠金钱",
        0x0A,
        1,
        0,
        255,
        "疑似击坠金钱的存储值，显示倍率尚待验证。",
        evidence="candidate",
    ),
    FieldSpec(
        "candidate_0b",
        "保留：全零字节",
        0x0B,
        1,
        0,
        255,
        "基准 ROM 的全部 94 条唯一机体记录均为 00；用途未知。",
        evidence="candidate",
    ),
)
ALL_UNIT_FIELDS = UNIT_FIELDS + UNIT_CANDIDATE_FIELDS
UNIT_FIELD_BY_KEY = {field.key: field for field in ALL_UNIT_FIELDS}


@dataclass(frozen=True)
class UnitRecord:
    pointer: int
    ids: tuple[int, ...]
    raw: bytes

    def __post_init__(self) -> None:
        if len(self.raw) != UNIT_RECORD_SIZE:
            raise ValueError(f"机体记录必须为 {UNIT_RECORD_SIZE} 字节。")
        if not self.ids:
            raise ValueError("机体记录至少需要一个 ID。")

    def get(self, field_key: str) -> int:
        return UNIT_FIELD_BY_KEY[field_key].decode(self.raw)

    def with_field(self, field_key: str, value: int) -> "UnitRecord":
        field = UNIT_FIELD_BY_KEY[field_key]
        return replace(self, raw=field.encode_into(self.raw, value))


@dataclass(frozen=True)
class WeaponRecord:
    weapon_id: int
    pointer: int
    raw: bytes

    def __post_init__(self) -> None:
        if len(self.raw) != WEAPON_RECORD_SIZE:
            raise ValueError(f"武器记录必须为 {WEAPON_RECORD_SIZE} 字节。")
        if not 1 <= self.weapon_id <= 0xFF:
            raise ValueError("武器 ID 必须在 01—FF 之间。")

    def get(self, field_key: str) -> int:
        return WEAPON_FIELD_BY_KEY[field_key].decode(self.raw)

    def with_field(self, field_key: str, value: int) -> "WeaponRecord":
        field = WEAPON_FIELD_BY_KEY[field_key]
        return replace(self, raw=field.encode_into(self.raw, value))


@dataclass(frozen=True)
class WeaponFieldSpec:
    key: str
    label: str
    record_offset: int
    minimum: int
    maximum: int
    description: str
    evidence: EvidenceLevel = "confirmed"
    mask: int | None = None
    shift: int = 0
    value_bias: int = 0

    def __post_init__(self) -> None:
        if not 0 <= self.record_offset < WEAPON_RECORD_SIZE:
            raise ValueError(f"字段 {self.key} 超出武器记录。")
        if self.minimum > self.maximum:
            raise ValueError(f"字段 {self.key} 的数值范围无效。")

    def decode(self, raw: bytes) -> int:
        encoded = raw[self.record_offset]
        if self.mask is not None:
            encoded = (encoded & self.mask) >> self.shift
        return encoded + self.value_bias

    def encode_into(self, raw: bytes, value: int) -> bytes:
        if not self.minimum <= value <= self.maximum:
            raise ValueError(f"{self.label}必须在 {self.minimum}—{self.maximum} 之间。")
        result = bytearray(raw)
        encoded_value = value - self.value_bias
        if self.mask is None:
            result[self.record_offset] = encoded_value
        else:
            current = result[self.record_offset]
            result[self.record_offset] = (
                current & ~self.mask
            ) | ((encoded_value << self.shift) & self.mask)
        return bytes(result)


WEAPON_FIELDS = (
    WeaponFieldSpec(
        "max_range",
        "最大射程",
        0x00,
        1,
        16,
        "低半字节加 1；战斗代码直接用它检查目标距离上限。",
        mask=0x0F,
        value_bias=1,
    ),
    WeaponFieldSpec("hit", "命中", 0x01, 0, 255, "直接进入战斗命中率计算。"),
    WeaponFieldSpec("power_air", "对空攻击", 0x03, 0, 255, "目标为空中单位时使用的攻击值。"),
    WeaponFieldSpec("power_land", "对陆攻击", 0x04, 0, 255, "目标位于陆地时使用的攻击值。"),
    WeaponFieldSpec("power_sea", "对海攻击", 0x05, 0, 255, "目标位于水域时使用的攻击值。"),
)
WEAPON_CANDIDATE_FIELDS = (
    WeaponFieldSpec(
        "attack_type_flags",
        "候选：攻击类型标志",
        0x00,
        0,
        15,
        "记录第 1 字节的高半字节；已见 0、1、E、F，具体位义待验证。",
        evidence="candidate",
        mask=0xF0,
        shift=4,
    ),
    WeaponFieldSpec(
        "close_range_code",
        "候选：近程修正代码",
        0x02,
        0,
        15,
        "低半字节选择随距离变化的命中修正表；基准版只使用 0 或 1。",
        evidence="candidate",
        mask=0x0F,
    ),
)
ALL_WEAPON_FIELDS = WEAPON_FIELDS + WEAPON_CANDIDATE_FIELDS
WEAPON_FIELD_BY_KEY = {field.key: field for field in ALL_WEAPON_FIELDS}


@dataclass(frozen=True)
class UnitWeaponConfig:
    unit_id: int
    weapon_ids: tuple[int, int]

    def __post_init__(self) -> None:
        if not 1 <= self.unit_id <= 0xFF:
            raise ValueError("机体 ID 必须在 01—FF 之间。")
        if len(self.weapon_ids) != 2:
            raise ValueError("机体武器配置必须正好包含两个槽位。")
        if any(not 0 <= weapon_id <= 0xFF for weapon_id in self.weapon_ids):
            raise ValueError("武器 ID 必须在 00—FF 之间。")

    def with_slot(self, slot: int, weapon_id: int) -> "UnitWeaponConfig":
        if slot not in (0, 1):
            raise IndexError("武器槽位必须为 0 或 1。")
        values = list(self.weapon_ids)
        values[slot] = weapon_id
        return replace(self, weapon_ids=(values[0], values[1]))


@dataclass(frozen=True)
class MapRecord:
    map_id: int
    pointer: int
    width: int
    height: int
    tiles: tuple[int, ...]
    raw: bytes
    capacity: int

    def __post_init__(self) -> None:
        if not 0 <= self.map_id <= 0xFF:
            raise ValueError("地图 ID 必须在 00—FF 之间。")
        if not 1 <= self.width <= 32 or not 1 <= self.height <= 32:
            raise ValueError("地图宽高必须在 1—32 之间。")
        if len(self.tiles) != self.width * self.height:
            raise ValueError("地图图块数量与宽高不一致。")
        if any(not 0 <= tile <= 0x0F for tile in self.tiles):
            raise ValueError("逻辑地形编号必须在 0—15 之间。")
        if not 2 <= len(self.raw) <= self.capacity:
            raise ValueError("地图压缩数据长度无效。")

    def tile_at(self, x: int, y: int) -> int:
        if not 0 <= x < self.width or not 0 <= y < self.height:
            raise IndexError("地图坐标超出范围。")
        return self.tiles[y * self.width + x]

    def with_tile(self, x: int, y: int, tile: int) -> "MapRecord":
        if not 0 <= tile <= 0x0F:
            raise ValueError("逻辑地形编号必须在 0—15 之间。")
        values = list(self.tiles)
        values[y * self.width + x] = tile
        return replace(self, tiles=tuple(values))


@dataclass(frozen=True)
class ScenarioEntity:
    x: int
    y: int
    pilot_id: int
    unit_id: int
    level: int
    flags: int

    def __post_init__(self) -> None:
        if any(
            not 0 <= value <= 0xFF
            for value in (self.x, self.y, self.pilot_id, self.unit_id, self.level, self.flags)
        ):
            raise ValueError("部署对象的所有字段必须是 0—255 的字节。")

    def to_bytes(self) -> bytes:
        return bytes((self.x, self.y, self.pilot_id, self.unit_id, self.level, self.flags))


@dataclass(frozen=True)
class PlayerPlacement:
    x: int
    y: int
    roster_index: int
    flags: int

    def __post_init__(self) -> None:
        if any(
            not 0 <= value <= 0xFF
            for value in (self.x, self.y, self.roster_index, self.flags)
        ):
            raise ValueError("我方部署记录的所有字段必须是 0—255 的字节。")

    def to_bytes(self) -> bytes:
        return bytes((self.x, self.y, self.roster_index, self.flags))


@dataclass(frozen=True)
class ScenarioLayout:
    map_id: int
    pointer: int
    prelude: tuple[int, ...]
    enemies: tuple[ScenarioEntity, ...]
    guests: tuple[ScenarioEntity, ...]
    player_placements: tuple[PlayerPlacement, ...]
    raw: bytes
    capacity: int

    def __post_init__(self) -> None:
        if not 0 <= self.map_id <= 0xFF:
            raise ValueError("场景 ID 必须在 00—FF 之间。")
        if any(not 0 <= value < 0xFF for value in self.prelude):
            raise ValueError("场景前导列表不能包含哨兵 FF。")
        if not 4 <= len(self.raw) <= self.capacity:
            raise ValueError("场景部署数据长度无效。")


@dataclass(frozen=True)
class TextToken:
    record_offset: int
    raw: bytes
    category: str

    @property
    def code(self) -> str:
        return self.raw.hex(" ").upper()


@dataclass(frozen=True)
class StoryTextRecord:
    selector: int
    indices: tuple[int, ...]
    pointer: int
    raw: bytes
    capacity: int

    def __post_init__(self) -> None:
        if not self.indices:
            raise ValueError("剧情文本记录至少需要一个索引。")
        if self.capacity < 0 or len(self.raw) != self.capacity:
            raise ValueError("剧情文本记录容量无效。")
