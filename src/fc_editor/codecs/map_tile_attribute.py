from __future__ import annotations

from dataclasses import dataclass

from ..errors import RomFormatError


BytePatch = tuple[int, bytes, bytes]


@dataclass(frozen=True)
class MapTileAttribute:
    palette: int
    defense: int
    sea: bool
    air_move: int
    land_move: int
    sea_move: int
    heal: bool = False


@dataclass(frozen=True)
class MapTilesetAttributes:
    colors: tuple[int, int, int]
    graphic_selector: int
    tiles: tuple[MapTileAttribute, ...]
    heal_ratio: int = 30


class MapTileAttributeCodec:
    """Verified A-G terrain-property records used by the expanded DC ROM."""

    RECORD_START = 0x6060
    RECORD_SIZE = 0x54
    TILE_COUNT = 16
    KEYS = tuple("ABCDEFG")
    EXPECTED_GRAPHIC_SELECTORS = {
        "A": 0x04, "B": 0x05, "C": 0x06, "D": 0x3D,
        "E": 0x3F, "F": 0x07, "G": 0x41,
    }
    PALETTE_BYTES = (0x00, 0x55, 0xAA, 0xFF)
    MAX_MOVE = 0x10
    # Bank $0A:$8FA0-$9009 performs end-of-turn recovery. It reads the map
    # tile's low nibble at $8FC6-$8FCA, compares it with one global tile index,
    # then calculates max HP * $1E / $64. Carried units enter the same
    # calculation at $8FBE, so the percentage is shared by terrain and carrier
    # recovery. $10 can never match the masked 0-$0F tile and represents off.
    HEAL_TILE_OPERAND = 0x14FCB
    HEAL_RATIO_OPERAND = 0x14FD9
    HEAL_NONE = 0x10
    HEAL_TILE_PREFIX = bytes.fromhex("B1 08 29 0F C9")
    HEAL_TILE_SUFFIX = bytes.fromhex("D0 46 BD F7 76 85 00 BD 17 77 85 01 A9")
    HEAL_RATIO_SUFFIX = bytes.fromhex("85 08 20 0C C0 A9 64 85 08 20 12 C0")
    # Tile 5 in A and D uses the exact same four CHR water tiles. Archived
    # ROMs saved by the legacy modifier additionally prove the high-bit sea
    # flag for C5 and D5; B5 has the same water silhouette. Some expanded
    # ROMs omitted those flags, so surface the game terrain instead of
    # presenting a misleading all-empty Sea column. Applying the dialog
    # repairs the missing high bit in the normal defence byte.
    VISUAL_SEA_TILES = {
        "A": frozenset((5,)),
        "B": frozenset((5,)),
        "C": frozenset((5,)),
        "D": frozenset((5,)),
    }

    @classmethod
    def is_visual_sea(cls, key: str, tile_index: int) -> bool:
        return tile_index in cls.VISUAL_SEA_TILES.get(key.upper(), ())

    @classmethod
    def record_offset(cls, key: str) -> int:
        normalized = key.upper()
        if normalized not in cls.KEYS:
            raise ValueError("仅图库 A—G 的图块属性完成了差分验证。")
        return cls.RECORD_START + cls.KEYS.index(normalized) * cls.RECORD_SIZE

    @classmethod
    def supports(cls, data: bytes | bytearray) -> bool:
        try:
            for key in cls.KEYS:
                cls.decode(data, key)
        except (ValueError, RomFormatError):
            return False
        return True

    @classmethod
    def _decode_heal_settings(cls, data: bytes | bytearray) -> tuple[int | None, int]:
        tile_offset = cls.HEAL_TILE_OPERAND
        ratio_offset = cls.HEAL_RATIO_OPERAND
        if ratio_offset + 1 + len(cls.HEAL_RATIO_SUFFIX) > len(data):
            raise RomFormatError("图块回血运行时代码超出 ROM。")
        if (
            bytes(data[tile_offset - len(cls.HEAL_TILE_PREFIX) : tile_offset])
            != cls.HEAL_TILE_PREFIX
            or bytes(data[tile_offset + 1 : tile_offset + 1 + len(cls.HEAL_TILE_SUFFIX)])
            != cls.HEAL_TILE_SUFFIX
            or bytes(data[ratio_offset + 1 : ratio_offset + 1 + len(cls.HEAL_RATIO_SUFFIX)])
            != cls.HEAL_RATIO_SUFFIX
        ):
            raise RomFormatError("图块回血运行时代码与已验证结构不符。")
        tile_index = int(data[tile_offset])
        ratio = int(data[ratio_offset])
        if not 0 <= tile_index <= cls.HEAL_NONE:
            raise RomFormatError("图块回血索引超出已验证范围。")
        if not 1 <= ratio <= 100:
            raise RomFormatError("图块/母舰回血比例必须为 1%—100%。")
        return (None if tile_index == cls.HEAL_NONE else tile_index), ratio

    @classmethod
    def decode(cls, data: bytes | bytearray, key: str) -> MapTilesetAttributes:
        normalized = key.upper()
        offset = cls.record_offset(normalized)
        if offset + cls.RECORD_SIZE > len(data):
            raise RomFormatError("图块属性记录超出 ROM。")
        graphic_selector = data[offset + 3]
        expected = cls.EXPECTED_GRAPHIC_SELECTORS[normalized]
        if graphic_selector != expected:
            raise RomFormatError(
                f"图库 {normalized} 的图形选择器应为 ${expected:02X}，"
                f"实际为 ${graphic_selector:02X}。"
            )
        palette_raw = tuple(data[offset + 4 : offset + 20])
        if any(value not in cls.PALETTE_BYTES for value in palette_raw):
            raise RomFormatError(f"图库 {normalized} 含未验证的颜色表编码。")
        move_groups = (
            tuple(data[offset + 36 : offset + 52]),
            tuple(data[offset + 52 : offset + 68]),
            tuple(data[offset + 68 : offset + 84]),
        )
        if any(value > cls.MAX_MOVE for group in move_groups for value in group):
            raise RomFormatError(f"图库 {normalized} 含未验证的移动补正编码。")
        heal_tile, heal_ratio = cls._decode_heal_settings(data)
        tiles = tuple(
            MapTileAttribute(
                palette=palette_raw[index] // 0x55,
                defense=data[offset + 20 + index] & 0x7F,
                sea=bool(data[offset + 20 + index] & 0x80),
                air_move=move_groups[0][index],
                land_move=move_groups[1][index],
                sea_move=move_groups[2][index],
                heal=index == heal_tile,
            )
            for index in range(cls.TILE_COUNT)
        )
        colors = tuple(data[offset : offset + 3])
        return MapTilesetAttributes(  # type: ignore[arg-type]
            colors, graphic_selector, tiles, heal_ratio
        )

    @classmethod
    def _normalize(cls, key: str, value: MapTilesetAttributes) -> MapTilesetAttributes:
        normalized = key.upper()
        cls.record_offset(normalized)
        colors = tuple(value.colors)
        tiles = tuple(value.tiles)
        if len(colors) != 3 or any(
            not isinstance(color, int) or not 0 <= color <= 0x3F for color in colors
        ):
            raise ValueError("颜色表1必须包含 3 个 $00—$3F 的 NES 色号。")
        if value.graphic_selector != cls.EXPECTED_GRAPHIC_SELECTORS[normalized]:
            raise ValueError("图形选择器不允许通过图块属性窗口修改。")
        if len(tiles) != cls.TILE_COUNT:
            raise ValueError("图块属性必须包含 16 个图块。")
        for index, tile in enumerate(tiles):
            if not 0 <= tile.palette <= 3:
                raise ValueError(f"位图{index:X}的颜色表必须在 0—3 之间。")
            if not 0 <= tile.defense <= 0x7F:
                raise ValueError(f"位图{index:X}的防御补正必须在 0—127 之间。")
            if any(not 0 <= move <= cls.MAX_MOVE for move in
                   (tile.air_move, tile.land_move, tile.sea_move)):
                raise ValueError(f"位图{index:X}的移动补正必须在 0—16 之间。")
        heal_tiles = [index for index, tile in enumerate(tiles) if tile.heal]
        if len(heal_tiles) > 1:
            raise ValueError("游戏运行时只支持一个全图库共用的回血图块。")
        if not 1 <= value.heal_ratio <= 100:
            raise ValueError("图块/母舰回血比例必须为 1%—100%。")
        return MapTilesetAttributes(  # type: ignore[arg-type]
            colors, value.graphic_selector, tiles, value.heal_ratio
        )

    @classmethod
    def patches(
        cls, data: bytes | bytearray, key: str, value: MapTilesetAttributes
    ) -> tuple[BytePatch, ...]:
        current = cls.decode(data, key)
        normalized = cls._normalize(key, value)
        if normalized.graphic_selector != current.graphic_selector:
            raise ValueError("图形选择器必须保持不变。")
        offset = cls.record_offset(key)
        encoded = bytearray(data[offset : offset + cls.RECORD_SIZE])
        encoded[0:3] = bytes(normalized.colors)
        for index, tile in enumerate(normalized.tiles):
            encoded[4 + index] = cls.PALETTE_BYTES[tile.palette]
            encoded[20 + index] = tile.defense | (0x80 if tile.sea else 0)
            encoded[36 + index] = tile.air_move
            encoded[52 + index] = tile.land_move
            encoded[68 + index] = tile.sea_move
        patches = [
            (offset + index, bytes((before,)), bytes((after,)))
            for index, (before, after) in enumerate(
                zip(data[offset : offset + cls.RECORD_SIZE], encoded, strict=True)
            )
            if before != after
        ]
        heal_tiles = [
            index for index, tile in enumerate(normalized.tiles) if tile.heal
        ]
        global_values = (
            (cls.HEAL_TILE_OPERAND, heal_tiles[0] if heal_tiles else cls.HEAL_NONE),
            (cls.HEAL_RATIO_OPERAND, normalized.heal_ratio),
        )
        patches.extend(
            (global_offset, bytes((data[global_offset],)), bytes((after,)))
            for global_offset, after in global_values
            if data[global_offset] != after
        )
        return tuple(patches)
