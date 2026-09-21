from __future__ import annotations

from pathlib import Path
import re

from fc_editor.codecs.character_attributes import CharacterAttributesCodec
from fc_editor.legacy_bitmap import RgbColor, encode_legacy_bmp24

from .database_graphics import FCEUX_RGB


PORTRAIT_SIZE = 32
PORTRAIT_TILE_COUNT = 16
PORTRAIT_BACKGROUND_PALETTE_NES = (0x0F, 0x20, 0x10, 0x00)
PORTRAIT_FILENAMES = {
    "back": "[背面].bmp",
    "front": "[正面].bmp",
    "effect": "[效果].bmp",
}
_INVALID_FILENAME_CHARACTERS = re.compile(r'[<>:"/\\|?*\x00-\x1F]')
_RESERVED_WINDOWS_NAMES = {
    "CON", "PRN", "AUX", "NUL",
    *(f"COM{index}" for index in range(1, 10)),
    *(f"LPT{index}" for index in range(1, 10)),
}


def safe_portrait_directory_name(character_id: int, name: str) -> str:
    """Return the legacy ``decimal ID：name`` directory without unsafe paths."""

    cleaned = _INVALID_FILENAME_CHARACTERS.sub("_", name).strip(" .") or "未命名"
    if cleaned.upper() in _RESERVED_WINDOWS_NAMES:
        cleaned = f"_{cleaned}"
    return f"{character_id}：{cleaned}"


def portrait_export_paths(
    project,
    character_id: int,
    root: str | Path,
) -> tuple[Path, Path, Path]:
    codec = CharacterAttributesCodec(project)
    codec.read_portrait(character_id)
    directory = Path(root) / safe_portrait_directory_name(
        character_id, project.character_display_name(character_id)
    )
    return tuple(directory / filename for filename in PORTRAIT_FILENAMES.values())


def portrait_layer_pixels(project, character_id: int, layer: str) -> tuple[tuple[int, int, int], ...]:
    """Render one verified 4x4 portrait layer with its ROM-defined palette."""

    if layer not in PORTRAIT_FILENAMES:
        raise ValueError("头像层必须是 front、back 或 effect。")
    record = CharacterAttributesCodec(project).read_portrait(character_id)
    front_palette = tuple(
        _nes_palette_rgb(color)
        for color in (0x0F, *record.colors)
    )
    back_palette = tuple(
        _nes_palette_rgb(color)
        for color in PORTRAIT_BACKGROUND_PALETTE_NES
    )
    if layer == "effect":
        back = _portrait_layer_indices(project, character_id, "back")
        front = _portrait_layer_indices(project, character_id, "front")
        return tuple(
            front_palette[front_pixel] if front_pixel else back_palette[back_pixel]
            for back_pixel, front_pixel in zip(back, front, strict=True)
        )
    palette = front_palette if layer == "front" else back_palette
    return tuple(
        palette[index]
        for index in _portrait_layer_indices(project, character_id, layer)
    )


def _nes_palette_rgb(index: int) -> RgbColor:
    start = (index & 0x3F) * 3
    return tuple(FCEUX_RGB[start:start + 3])


def _portrait_layer_indices(
    project,
    character_id: int,
    layer: str,
) -> tuple[int, ...]:
    record = CharacterAttributesCodec(project).read_portrait(character_id)
    first_tile = (
        record.front_bank * 64 + record.front_slot * 16
        if layer == "front"
        else record.back_bank * 64 + record.back_slot * 16
    )
    project.chr_codec.range_bytes(first_tile, PORTRAIT_TILE_COUNT, bytes(project.working))
    pixels = [0] * (PORTRAIT_SIZE * PORTRAIT_SIZE)
    for tile_index in range(PORTRAIT_TILE_COUNT):
        tile = project.chr_tile_pixels(first_tile + tile_index)
        tile_x = tile_index % 4 * 8
        tile_y = tile_index // 4 * 8
        for y in range(8):
            for x in range(8):
                pixels[(tile_y + y) * PORTRAIT_SIZE + tile_x + x] = tile[y * 8 + x]
    return tuple(pixels)


def portrait_bitmap_bytes(project, character_id: int, layer: str) -> bytes:
    return encode_legacy_bmp24(
        PORTRAIT_SIZE,
        PORTRAIT_SIZE,
        portrait_layer_pixels(project, character_id, layer),
    )


def export_portrait_bitmaps(
    project,
    character_id: int,
    root: str | Path,
) -> tuple[Path, Path, Path]:
    """Export the back, front, and composited 32x32 portrait BMP files."""

    paths = portrait_export_paths(project, character_id, root)
    payloads = tuple(
        (path, portrait_bitmap_bytes(project, character_id, layer))
        for layer, path in zip(PORTRAIT_FILENAMES, paths, strict=True)
    )
    paths[0].parent.mkdir(parents=True, exist_ok=True)
    for destination, payload in payloads:
        temporary = destination.with_name(destination.name + ".tmp")
        temporary.write_bytes(payload)
        temporary.replace(destination)
    return paths
