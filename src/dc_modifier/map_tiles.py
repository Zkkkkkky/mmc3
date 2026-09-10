from __future__ import annotations

from PySide6.QtGui import QColor, QImage


# Verified against the loaded target ROM in the established SRW2 editor.
# Tuple index 0 is chapter/map $00 (displayed as chapter 1).
CAMPAIGN_TILESET_KEYS = tuple("DDAAAAFBBDBBGCFCCFCCFEAAAFEAACCC")

# One library is 1 KiB / 64 NES 2bpp tiles.  Each logical map tile consumes
# four consecutive 8x8 tiles from that library.
TILESET_BANKS = {
    "A": 0x04,
    "B": 0x05,
    "C": 0x06,
    "D": 0x3D,
    "E": 0x3F,
    "F": 0x07,
    "G": 0x41,
    "H": 0x45,
}

GRASS = ("#071807", "#000000", "#32C035", "#07980A")
FOREST = ("#072A08", "#44331F", "#35B936", "#127616")
MOUNTAIN = ("#4B1308", "#E0A475", "#CF8050", "#A64E28")
WATER = ("#05083B", "#7394E5", "#3B5FC7", "#15299F")
SAND = ("#2B1C0A", "#E7BD8A", "#E0A05F", "#D1833D")
STONE = ("#202221", "#D2D2D2", "#9A9C9A", "#666867")
SPACE = ("#05064D", "#4D59A0", "#293D8E", "#080954")
ASTEROID = ("#3E2E08", "#A78B28", "#7C6513", "#120D03")
ICE = ("#0A124C", "#B8DDEC", "#5A8FB8", "#071052")
PURPLE = ("#16032D", "#4E1978", "#7415C3", "#47088E")
ORANGE = ("#3D1509", "#E09A4B", "#C5682B", "#A42D0B")
BLACK = ("#050506", "#1D1D20", "#4B4B50", "#85858B")


def _palette_row(*values: tuple[str, str, str, str]) -> tuple:
    if len(values) != 16:
        raise ValueError("地图调色板必须包含16个逻辑图块。")
    return values


TILESET_PALETTES = {
    "A": _palette_row(
        GRASS, GRASS, GRASS, MOUNTAIN, MOUNTAIN, WATER, FOREST, FOREST,
        SAND, STONE, STONE, STONE, STONE, STONE, STONE, STONE,
    ),
    "B": _palette_row(
        GRASS, GRASS, GRASS, MOUNTAIN, WATER, WATER, FOREST, WATER,
        SAND, STONE, STONE, STONE, STONE, STONE, STONE, STONE,
    ),
    "C": _palette_row(
        SPACE, SPACE, SPACE, ASTEROID, STONE, STONE, SPACE, ASTEROID,
        ASTEROID, STONE, MOUNTAIN, WATER, ASTEROID, ASTEROID, STONE, STONE,
    ),
    "D": _palette_row(
        GRASS, GRASS, STONE, STONE, MOUNTAIN, WATER, FOREST, FOREST,
        SAND, STONE, STONE, STONE, STONE, STONE, STONE, STONE,
    ),
    "E": _palette_row(
        SPACE, SPACE, SPACE, ASTEROID, ASTEROID, BLACK, WATER, ICE,
        ICE, STONE, ASTEROID, WATER, ICE, ICE, ICE, ICE,
    ),
    "F": _palette_row(
        PURPLE, PURPLE, PURPLE, PURPLE, ORANGE, ORANGE, STONE, STONE,
        STONE, STONE, STONE, STONE, BLACK, BLACK, BLACK, BLACK,
    ),
    "G": _palette_row(
        PURPLE, PURPLE, PURPLE, PURPLE, STONE, STONE, STONE, BLACK,
        STONE, STONE, STONE, STONE, PURPLE, BLACK, BLACK, STONE,
    ),
    "H": _palette_row(
        PURPLE, PURPLE, PURPLE, PURPLE, ORANGE, ORANGE, STONE, BLACK,
        BLACK, STONE, STONE, STONE, PURPLE, BLACK, PURPLE, STONE,
    ),
}


def campaign_tileset_key(map_id: int) -> str | None:
    if 0 <= map_id < len(CAMPAIGN_TILESET_KEYS):
        return CAMPAIGN_TILESET_KEYS[map_id]
    return None


def render_map_tile(project, tileset_key: str, logical_tile: int) -> QImage:
    """Render one 16x16 logical map tile from the ROM's active CHR stream."""

    key = tileset_key.upper()
    if key not in TILESET_BANKS:
        raise ValueError(f"未知地图位图：{tileset_key}")
    if not 0 <= logical_tile <= 0x0F:
        raise ValueError("逻辑地图图块必须在 $0—$F 之间。")
    palette = tuple(QColor(value) for value in TILESET_PALETTES[key][logical_tile])
    first_tile = TILESET_BANKS[key] * 64 + logical_tile * 4
    image = QImage(16, 16, QImage.Format.Format_RGB32)
    for quadrant in range(4):
        pixels = project.chr_tile_pixels(first_tile + quadrant)
        origin_x = (quadrant % 2) * 8
        origin_y = (quadrant // 2) * 8
        for y in range(8):
            for x in range(8):
                image.setPixelColor(
                    origin_x + x,
                    origin_y + y,
                    palette[pixels[y * 8 + x]],
                )
    return image


def render_tileset(project, tileset_key: str) -> tuple[QImage, ...]:
    return tuple(render_map_tile(project, tileset_key, tile) for tile in range(16))
