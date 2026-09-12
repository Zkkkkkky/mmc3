from __future__ import annotations

from PySide6.QtGui import QImage

from .database_graphics import palette_color


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

# Verified from the battlefield palette template at file offset $3B2C0 and
# runtime palette RAM $0490-$049F. Palette 1's last three values are supplied
# by the active A-G tileset record, so only the fixed palettes live here.
VERIFIED_BATTLEFIELD_PALETTES = {
    0: (0x0F, 0x30, 0x10, 0x00),
    2: (0x0F, 0x30, 0x21, 0x02),
    3: (0x0F, 0x37, 0x27, 0x16),
}

# Palette 1 is the only terrain palette whose three visible colors vary by
# tileset. A-G come from their verified 84-byte records; H uses the matching
# late-game purple set because no writable H attribute record has been found.
TILESET_PALETTE_ONE_VALUES = {
    "A": (0x0F, 0x27, 0x2A, 0x1A),
    "B": (0x0F, 0x27, 0x2A, 0x1A),
    "C": (0x0F, 0x28, 0x18, 0x02),
    "D": (0x0F, 0x27, 0x2A, 0x1A),
    "E": (0x0F, 0x28, 0x18, 0x02),
    "F": (0x0F, 0x23, 0x13, 0x03),
    "G": (0x0F, 0x23, 0x13, 0x03),
    "H": (0x0F, 0x23, 0x13, 0x03),
}


def _palette_route(*values: int) -> tuple[int, ...]:
    if len(values) != 16:
        raise ValueError("地图调色板路由必须包含16个逻辑图块。")
    if any(value not in range(4) for value in values):
        raise ValueError("地图调色板路由只能使用颜色表0—3。")
    return tuple(values)


TILESET_PALETTE_ROUTES = {
    "A": _palette_route(
        0, 1, 1, 3, 3, 2, 1, 1, 3, 0, 0, 0, 0, 0, 0, 0,
    ),
    "B": _palette_route(
        0, 1, 1, 3, 2, 2, 1, 2, 3, 0, 0, 0, 0, 0, 0, 0,
    ),
    "C": _palette_route(
        0, 1, 1, 3, 0, 0, 1, 3, 3, 0, 3, 2, 3, 3, 0, 0,
    ),
    "D": _palette_route(
        0, 1, 0, 0, 3, 2, 1, 1, 3, 0, 0, 0, 0, 0, 0, 0,
    ),
    "E": _palette_route(
        0, 1, 1, 3, 3, 0, 2, 2, 2, 0, 3, 2, 2, 2, 2, 2,
    ),
    "F": _palette_route(
        0, 1, 1, 1, 3, 3, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0,
    ),
    "G": _palette_route(
        0, 1, 1, 1, 0, 0, 0, 0, 0, 0, 0, 0, 1, 0, 0, 0,
    ),
    "H": _palette_route(
        0, 1, 1, 1, 3, 3, 0, 0, 0, 0, 0, 0, 1, 0, 1, 0,
    ),
}

def battlefield_palette_values(
    project, tileset_key: str, palette_index: int, *, attributes=None
) -> tuple[int, int, int, int]:
    """Return the exact NES color numbers used by one map preview palette."""

    key = tileset_key.upper()
    if palette_index != 1:
        return VERIFIED_BATTLEFIELD_PALETTES[palette_index]
    if key in "ABCDEFG" and project.supports_map_tile_attributes:
        active_attributes = (
            project.get_map_tileset_attributes(key)
            if attributes is None
            else attributes
        )
        return (0x0F, *active_attributes.colors)
    return TILESET_PALETTE_ONE_VALUES[key]


def campaign_tileset_key(map_id: int) -> str | None:
    if 0 <= map_id < len(CAMPAIGN_TILESET_KEYS):
        return CAMPAIGN_TILESET_KEYS[map_id]
    return None


def render_map_tile(
    project,
    tileset_key: str,
    logical_tile: int,
    *,
    attributes=None,
) -> QImage:
    """Render one 16x16 logical map tile from the ROM's active CHR stream."""

    key = tileset_key.upper()
    if key not in TILESET_BANKS:
        raise ValueError(f"未知地图位图：{tileset_key}")
    if not 0 <= logical_tile <= 0x0F:
        raise ValueError("逻辑地图图块必须在 $0—$F 之间。")
    # The legacy 00/55/AA/FF property field is editable, but reference-editor
    # and emulator screenshots prove that it is not a whole-metatile preview
    # palette selector. All visual surfaces use the in-game terrain route.
    palette_index = TILESET_PALETTE_ROUTES[key][logical_tile]
    palette = tuple(
        palette_color(value)
        for value in battlefield_palette_values(
            project, key, palette_index, attributes=attributes
        )
    )
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


def render_tileset(project, tileset_key: str, *, attributes=None) -> tuple[QImage, ...]:
    return tuple(
        render_map_tile(project, tileset_key, tile, attributes=attributes)
        for tile in range(16)
    )
