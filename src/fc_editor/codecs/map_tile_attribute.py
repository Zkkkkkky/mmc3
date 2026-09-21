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


@dataclass(frozen=True)
class MapTilesetAttributes:
    colors: tuple[int, int, int]
    graphic_selector: int
    tiles: tuple[MapTileAttribute, ...]


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
        tiles = tuple(
            MapTileAttribute(
                palette=palette_raw[index] // 0x55,
                defense=data[offset + 20 + index] & 0x7F,
                sea=bool(data[offset + 20 + index] & 0x80),
                air_move=move_groups[0][index],
                land_move=move_groups[1][index],
                sea_move=move_groups[2][index],
            )
            for index in range(cls.TILE_COUNT)
        )
        colors = tuple(data[offset : offset + 3])
        return MapTilesetAttributes(colors, graphic_selector, tiles)  # type: ignore[arg-type]

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
        return MapTilesetAttributes(colors, value.graphic_selector, tiles)  # type: ignore[arg-type]

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
        return tuple(
            (offset + index, bytes((before,)), bytes((after,)))
            for index, (before, after) in enumerate(
                zip(data[offset : offset + cls.RECORD_SIZE], encoded, strict=True)
            )
            if before != after
        )
