from __future__ import annotations

from pathlib import Path
import re

from fc_editor.codecs.character_attributes import CharacterAttributesCodec
from fc_editor.legacy_bitmap import LEGACY_MATERIAL_PALETTE_RGB, encode_legacy_bmp24


PORTRAIT_SIZE = 32
PORTRAIT_TILE_COUNT = 16
PORTRAIT_FILENAMES = {
    "back": "[背面].bmp",
    "front": "[正面].bmp",
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


def portrait_export_paths(project, character_id: int, root: str | Path) -> tuple[Path, Path]:
    codec = CharacterAttributesCodec(project)
    codec.read_portrait(character_id)
    directory = Path(root) / safe_portrait_directory_name(
        character_id, project.character_display_name(character_id)
    )
    return directory / PORTRAIT_FILENAMES["back"], directory / PORTRAIT_FILENAMES["front"]


def portrait_layer_pixels(project, character_id: int, layer: str) -> tuple[tuple[int, int, int], ...]:
    """Render one verified 4x4 portrait layer with the legacy material palette."""

    if layer not in PORTRAIT_FILENAMES:
        raise ValueError("头像层必须是 front 或 back。")
    record = CharacterAttributesCodec(project).read_portrait(character_id)
    first_tile = (
        record.front_bank * 64 + record.front_slot * 16
        if layer == "front"
        else (record.back_bank & 0xFE) * 64 + record.back_slot * 16
    )
    project.chr_codec.range_bytes(first_tile, PORTRAIT_TILE_COUNT, bytes(project.working))
    pixels = [LEGACY_MATERIAL_PALETTE_RGB[0]] * (PORTRAIT_SIZE * PORTRAIT_SIZE)
    for tile_index in range(PORTRAIT_TILE_COUNT):
        tile = project.chr_tile_pixels(first_tile + tile_index)
        tile_x = tile_index % 4 * 8
        tile_y = tile_index // 4 * 8
        for y in range(8):
            for x in range(8):
                pixels[(tile_y + y) * PORTRAIT_SIZE + tile_x + x] = (
                    LEGACY_MATERIAL_PALETTE_RGB[tile[y * 8 + x]]
                )
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
) -> tuple[Path, Path]:
    """Export the legacy ``[背面].bmp`` and ``[正面].bmp`` files."""

    back_path, front_path = portrait_export_paths(project, character_id, root)
    payloads = (
        (back_path, portrait_bitmap_bytes(project, character_id, "back")),
        (front_path, portrait_bitmap_bytes(project, character_id, "front")),
    )
    back_path.parent.mkdir(parents=True, exist_ok=True)
    for destination, payload in payloads:
        temporary = destination.with_name(destination.name + ".tmp")
        temporary.write_bytes(payload)
        temporary.replace(destination)
    return back_path, front_path
