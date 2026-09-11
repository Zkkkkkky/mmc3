from __future__ import annotations

from dataclasses import dataclass
import struct

from ..errors import RomFormatError


SPIRIT_NAMES = (
    "毅力", "疾风", "共感", "防守", "强攻", "友情", "速行", "魂",
    "回避", "觉醒", "热血", "再动", "奇迹", "援助", "破击", "斗志",
    "干扰", "激励", "爱心", "直击", "努力", "狙击", "援攻", "援防",
)
CORRECTION_KEYS = ("movement", "strength", "defense", "speed", "hp")
WEAPON_SKILLS = (
    "无", "加固定火力", "直线地图炮2", "范围修理", "加固定火力并隐藏",
    "抛射地图炮3", "距离衰减地图炮", "普通地图炮3", "直线地图炮1",
    "抛射地图炮1", "十字地图炮", "突击（移动远程）", "抛射地图炮2",
    "普通地图炮2", "普通地图炮1", "单体修理",
)
BytePatch = tuple[int, bytes, bytes]


def _byte(value: int, label: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or not 0 <= value <= 255:
        raise ValueError(f"{label}必须是 0—255 的整数。")
    return value


@dataclass(frozen=True)
class CharacterAttributes:
    spirit: int
    growth: int
    spirit_mask: int
    corrections: tuple[int, int, int, int, int]
    reserved_flags: int = 0

    def encode(self) -> bytes:
        _byte(self.spirit, "精神值")
        _byte(self.growth, "精神成长")
        if self.growth > 250:
            raise ValueError("精神成长必须在 0—250 之间（201—250 对应 50 条成长曲线）。")
        if not isinstance(self.spirit_mask, int) or not 0 <= self.spirit_mask <= 0xFFFFFF:
            raise ValueError("人物精神配置必须为 24 位掩码。")
        if len(self.corrections) != 5:
            raise ValueError("人物属性必须包含五项修正。")
        if not 0 <= self.reserved_flags <= 7:
            raise ValueError("人物保留标志必须保持低三位。")
        flags = self.reserved_flags
        extra = bytearray()
        for index, value in enumerate(self.corrections):
            _byte(value, CORRECTION_KEYS[index])
            if value:
                flags |= 0x80 >> index
                extra.append(value)
        return bytes((self.spirit, self.growth)) + self.spirit_mask.to_bytes(3, "big") + bytes((flags,)) + extra


@dataclass(frozen=True)
class PortraitRecord:
    colors: tuple[int, int, int]
    front_bank: int
    back_bank: int
    front_slot: int
    back_slot: int

    def encode(self) -> bytes:
        if len(self.colors) != 3 or any(type(value) is not int or not 0 <= value <= 63 for value in self.colors):
            raise ValueError("头像颜色必须是三个 00—3F 的调色板索引。")
        _byte(self.front_bank, "正面图库")
        _byte(self.back_bank, "背景图库")
        if not 0 <= self.front_slot <= 3 or not 0 <= self.back_slot <= 7:
            raise ValueError("正面头像位置必须在 1—4，背景位置必须在 1—8 之间。")
        return bytes((*self.colors, self.front_bank, self.back_bank,
                      0xC0 + self.front_slot * 16, 0x80 + self.back_slot * 16))


class CharacterAttributesCodec:
    """Current DC tables, verified against their 6502 consumers (see research note)."""

    TABLE = 0x48400
    COUNT = 201  # Includes the final reserved $C8 pointer, which must survive writes.
    POOL_START = 0x48592
    POOL_END = 0x4876F
    POINTER_BIAS = 0x40010
    PORTRAIT_TABLE = 0xAA46
    PORTRAIT_POOL_START = 0xABD8
    PORTRAIT_POOL_END = 0xADC9
    COSTS = 0x39B48
    CONTEXTS = (
        (0x48030, "a96f8518ade0048519200bc1a000b1188de304c8b118850fc8b11899e204c8c005d0f6b118850ea200a900060e9003c8b1189de704e8e005d0ef4c9081"),
        (0x9058, "a9708518a5ef8519200bc1a000b1188d7304c8b1188d7404c8b1188d7504c8b1188de604c8b1188de704c8b118203cc0c8b1188dbd0660"),
        (0x39B32, "0ee6042ee5042ee4049044a507d9389b903d984c7db6"),
        (0x39B6E, "a606b9389b9df004989df804e8e006f01a8606c8c018d0ac"),
    )

    def __init__(self, project) -> None:
        self.project = project
        if project.profile.key not in ("dc-kuorong-mmc3-v1", "dc-kuorong-mmc3-v2"):
            raise RomFormatError("当前 ROM 的人物属性与头像格式尚未验证。")
        self.validate(project.working)

    def validate(self, data: bytes | bytearray) -> None:
        for offset, expected in self.CONTEXTS:
            if data[offset:offset + len(bytes.fromhex(expected))] != bytes.fromhex(expected):
                raise RomFormatError(f"人物数据加载代码 0x{offset:X} 与已验证格式不同。")
        if data[0x48012:0x48014] != bytes.fromhex("f083") or data[0x8014:0x8016] != bytes.fromhex("36aa"):
            raise RomFormatError("人物属性/头像的表入口发生变化。")
        if data[self.TABLE:self.TABLE + 2] != b"\x00\x00" or data[self.PORTRAIT_TABLE:self.PORTRAIT_TABLE + 2] != b"\x00\x00":
            raise RomFormatError("人物属性/头像指针表起始标记无效。")

    def _source(self, original: bool) -> bytes | bytearray:
        return self.project.original if original else self.project.working

    def _offset(self, character_id: int, *, portrait: bool = False, original: bool = False) -> int:
        if type(character_id) is not int or not 1 <= character_id < self.COUNT:
            raise ValueError("人物 ID 必须在 01—C8 之间。")
        source = self._source(original)
        table = self.PORTRAIT_TABLE if portrait else self.TABLE
        pointer = int.from_bytes(source[table + character_id * 2:table + character_id * 2 + 2], "little")
        offset = pointer + (16 if portrait else self.POINTER_BIAS)
        start, end = (self.PORTRAIT_POOL_START, self.PORTRAIT_POOL_END) if portrait else (self.POOL_START, self.POOL_END)
        if not start <= offset < end:
            raise RomFormatError(f"人物 ${character_id:02X} 的记录指针超出已验证数据池。")
        return offset

    def shared_ids(self, character_id: int, *, portrait: bool = False) -> tuple[int, ...]:
        offset = self._offset(character_id, portrait=portrait)
        return tuple(index for index in range(1, self.COUNT)
                     if self._offset(index, portrait=portrait) == offset)

    def read(self, character_id: int, *, original: bool = False) -> CharacterAttributes:
        source = self._source(original)
        offset = self._offset(character_id, original=original)
        flags = source[offset + 5]
        end = offset + 6 + (flags & 0xF8).bit_count()
        if end > self.POOL_END:
            raise RomFormatError("人物修正记录越过属性数据池。")
        cursor = offset + 6
        corrections = []
        for index in range(5):
            present = bool(flags & (0x80 >> index))
            corrections.append(source[cursor] if present else 0)
            cursor += present
        return CharacterAttributes(source[offset], source[offset + 1],
                                   int.from_bytes(source[offset + 2:offset + 5], "big"),
                                   tuple(corrections), flags & 7)

    def read_portrait(self, character_id: int, *, original: bool = False) -> PortraitRecord:
        source = self._source(original)
        offset = self._offset(character_id, portrait=True, original=original)
        raw = bytes(source[offset:offset + 7])
        if offset + 7 > self.PORTRAIT_POOL_END or raw[5] not in (0xC0, 0xD0, 0xE0, 0xF0) or raw[6] not in range(0x80, 0x100, 0x10):
            raise RomFormatError("头像记录的位置编码不在已验证范围内。")
        result = PortraitRecord(tuple(raw[:3]), raw[3], raw[4], (raw[5] - 0xC0) // 16, (raw[6] - 0x80) // 16)
        result.encode()
        return result

    def costs(self, *, original: bool = False) -> tuple[int, ...]:
        return tuple(self._source(original)[self.COSTS:self.COSTS + 24])

    def cost_patch(self, values: tuple[int, ...]) -> BytePatch:
        if len(values) != 24:
            raise ValueError("精神消耗必须包含 24 项。")
        after = bytes(_byte(value, "精神消耗") for value in values)
        return self.COSTS, bytes(self.project.working[self.COSTS:self.COSTS + 24]), after

    def patches(self, character_id: int, record: CharacterAttributes, *, shared: bool = False) -> tuple[BytePatch, ...]:
        self.validate(self.project.working)
        after = record.encode()
        return self._record_patches(character_id, after, portrait=False, shared=shared)

    def portrait_patches(self, character_id: int, record: PortraitRecord, *, shared: bool = False) -> tuple[BytePatch, ...]:
        self.validate(self.project.working)
        return self._record_patches(character_id, record.encode(), portrait=True, shared=shared)

    def _record_patches(self, character_id: int, after: bytes, *, portrait: bool, shared: bool) -> tuple[BytePatch, ...]:
        source = self.project.working
        offset = self._offset(character_id, portrait=portrait)
        size = 7 if portrait else 6 + (source[offset + 5] & 0xF8).bit_count()
        if bytes(source[offset:offset + size]) == after:
            return ()
        ids = self.shared_ids(character_id, portrait=portrait)
        if len(after) == size and (shared or len(ids) == 1):
            return ((offset, bytes(source[offset:offset + size]), after),)
        # Repack only the bounded original pool, deduplicating identical records.
        # No code gap, CHR bank, or unrelated resource is treated as free space.
        table = self.PORTRAIT_TABLE if portrait else self.TABLE
        start, end = (self.PORTRAIT_POOL_START, self.PORTRAIT_POOL_END) if portrait else (self.POOL_START, self.POOL_END)
        bias = 16 if portrait else self.POINTER_BIAS
        pool = bytearray()
        pointers = bytearray(b"\x00\x00")
        destinations: dict[bytes, int] = {}
        for index in range(1, self.COUNT):
            current_offset = self._offset(index, portrait=portrait)
            current_size = 7 if portrait else 6 + (source[current_offset + 5] & 0xF8).bit_count()
            if current_offset + current_size > end:
                raise RomFormatError("人物记录越过数据池。")
            raw = bytes(source[current_offset:current_offset + current_size])
            if index == character_id or (shared and index in ids):
                raw = after
            if raw not in destinations:
                destinations[raw] = start + len(pool) - bias
                pool.extend(raw)
            pointers.extend(struct.pack("<H", destinations[raw]))
        if len(pool) > end - start:
            raise ValueError(f"{'头像' if portrait else '人物属性'}数据池容量不足：需要 {len(pool)} 字节，容量 {end - start} 字节。"
                             "可选择已有记录、先减少修正字段，或勾选“同时修改共用记录”。")
        # Leave unused tail bytes untouched, so no unrelated historical data is erased.
        return ((table, bytes(source[table:table + len(pointers)]), bytes(pointers)),
                (start, bytes(source[start:start + len(pool)]), bytes(pool)))


def weapon_extra_values(project, weapon_id: int) -> tuple[int, int]:
    offset = project.weapon_codec.record_offset(weapon_id)
    return project.working[offset] >> 4, project.working[offset + 2] & 15


def weapon_extra_patches(project, weapon_id: int, skill: int, distance: int) -> tuple[BytePatch, ...]:
    if type(skill) is not int or not 0 <= skill < 16:
        raise ValueError("武器特技必须在 00—15 之间。")
    if type(distance) is not int or not 0 <= distance < 4:
        raise ValueError("距离补正必须选择已验证的 0—3 号表。")
    if project.profile.key not in ("dc-kuorong-mmc3-v1", "dc-kuorong-mmc3-v2"):
        raise RomFormatError("当前 ROM 的武器特技格式尚未验证。")
    if project.working[0x8A79:0x8A88] != bytes.fromhex("ade304290f0a0a0a0a0507a8b9c8b4"):
        raise RomFormatError("武器距离命中修正的加载代码发生变化。")
    if project.working[0xA040:0xA050] != bytes.fromhex("c9e0f013c9a0f015c990f04ec980f04d"):
        raise RomFormatError("武器特技的分派代码发生变化。")
    offset = project.weapon_codec.record_offset(weapon_id)
    source = project.working
    return ((offset, bytes(source[offset:offset + 1]), bytes(((source[offset] & 15) | skill << 4,))),
            (offset + 2, bytes(source[offset + 2:offset + 3]), bytes(((source[offset + 2] & 0xF0) | distance,))))


def apply_verified_patches(project, patches: tuple[BytePatch, ...], description: str) -> None:
    project._apply_legacy_global_patches(patches, description)
