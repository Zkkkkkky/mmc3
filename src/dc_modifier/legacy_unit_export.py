"""Reference-compatible five-BMP unit export.

The rendering rules in this module are backed by the user's complete legacy
export (255 unit directories, 1,275 bitmaps).  It deliberately stays separate
from the ``.dcunit`` interchange format, which remains an editor extension.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from PySide6.QtGui import QColor, QImage

from fc_editor.dc_text import concise_dc_text
from fc_editor.legacy_bitmap import LEGACY_MATERIAL_PALETTE_RGB, encode_legacy_bmp24

from .database_graphics import (
    decode_unit_fragment_script,
    palette_color,
    read_unit_appearance,
    render_unit_battle_preview,
)
from .map_page import MAP_ICON_PALETTES_NES
from .unit_appearance_dialog import WORK_PALETTE


LEGACY_UNIT_EXPORT_DIRECTORY = "导出的机体"
LEGACY_UNIT_EXPORT_SUFFIXES = ("效果", "机体", "碎片", "图标1", "图标2")
_BLACK = QColor(0, 0, 0)
_INVALID_FILENAME_CHARACTERS = '<>:"/\\|?*'
# The stock exporter does not derive map-icon colours from the battle-picture
# direction bit.  Its 255-slot catalogue has a fixed enemy-colour lookup.  The
# complete B3 export gives a unique palette match for every slot, including
# duplicates and otherwise empty records, so keep that exact slot protocol.
LEGACY_ENEMY_ICON_UNIT_IDS = frozenset((
    *range(9, 13), *range(15, 21), 23, 25, *range(27, 31), *range(33, 38),
    82, 83, 85, 86, 88, 89, 91, 92, 94, 96, 97, *range(99, 102),
    *range(104, 107), *range(108, 113), 115, 118, 120, *range(124, 127),
    128, 129, 138, 139, 141, *range(146, 150), *range(152, 155), 156,
    158, 159, 161, 162, 164, 165, 167, 168, *range(171, 176),
    *range(177, 180), *range(182, 187),
))


@dataclass(frozen=True)
class LegacyUnitExportResult:
    root: Path
    written_files: tuple[Path, ...]
    failures: tuple[tuple[int, str], ...]


def legacy_unit_export_name(project, unit_id: int) -> str:
    """Return the raw legacy name, preserving empty slots 246--255."""

    text = concise_dc_text(project.unit_name_record_bytes(unit_id))
    return "".join("_" if character in _INVALID_FILENAME_CHARACTERS else character for character in text)


def _image_to_bmp(image: QImage) -> bytes:
    return encode_legacy_bmp24(
        image.width(),
        image.height(),
        (
            (color.red(), color.green(), color.blue())
            for y in range(image.height())
            for x in range(image.width())
            for color in (image.pixelColor(x, y),)
        ),
    )


def _blank_image(width: int, height: int) -> QImage:
    image = QImage(width, height, QImage.Format.Format_RGB32)
    image.fill(_BLACK)
    return image


def _legacy_fragment_image(
    project,
    appearance,
    display_palette: tuple[QColor, QColor, QColor, QColor] | None = None,
) -> QImage:
    """Render fragments with the stock exporter's whole-tile clipping rule."""

    background = display_palette[0] if display_palette is not None else palette_color(0x0F)
    colors = display_palette or (
        background,
        *(palette_color(value) for value in appearance.second_palette),
    )
    image = QImage(128, 128, QImage.Format.Format_RGB32)
    image.fill(background)
    fragment_bank = appearance.primary_bank & 0xFE
    origin_x = 0x78 if appearance.configuration[0] & 0x40 else 0
    for placement in decode_unit_fragment_script(appearance.fragment_script):
        target_x = placement.x + origin_x
        target_y = placement.y
        # The reference BMP path rejects a tile whose origin lies outside the
        # 128x128 canvas instead of clipping its visible tail.  Slots 009/010
        # prove this distinction with their first placement at X=-1.
        if not (0 <= target_x < 128 and 0 <= target_y < 128):
            continue
        bank_index, local_tile = divmod(placement.tile_index, 64)
        pixels = project.chr_tile_pixels((fragment_bank + bank_index) * 64 + local_tile)
        for y in range(8):
            source_y = 7 - y if placement.flip_vertical else y
            for x in range(8):
                source_x = 7 - x if placement.flip_horizontal else x
                color_index = pixels[source_y * 8 + source_x]
                x_at = target_x + x
                y_at = target_y + y
                if color_index and x_at < 128 and y_at < 128:
                    image.setPixelColor(x_at, y_at, colors[color_index])
    return image


def _legacy_effect_image(project, appearance, body_material: QImage) -> tuple[QImage, QImage]:
    """Return material fragments and the legacy game-colour composition.

    The reference path skips a whole fragment tile when its origin is outside
    the canvas, while the shared game renderer clips it pixel-by-pixel.  During
    composition it also treats rendered black as transparent.  The latter
    matters for the two slots whose fragment palette explicitly maps a
    non-zero CHR pixel value to NES black.
    """

    body = render_unit_battle_preview(project, appearance, show_fragments=False)
    fragments_material = _legacy_fragment_image(project, appearance, WORK_PALETTE)
    fragments = _legacy_fragment_image(project, appearance)
    effect = body.copy()
    for y in range(128):
        for x in range(128):
            color = fragments.pixelColor(x, y)
            if color.rgb() != _BLACK.rgb():
                effect.setPixelColor(x, y, color)
    return fragments_material, effect


def _legacy_third_icon_bank(unit_id: int) -> int:
    """Select the stock editor's changing third 16-icon page.

    The first two pages are fixed at $34/$35.  The third page follows the
    stock unit catalogue's chapter groups; the full B3 export proves these
    boundaries.  Slot $24 is a shared icon that the reference export reads
    from the later $3A page, and slot $BC returns to the $3E group.
    """

    if unit_id == 0x24:
        return 0x3A
    if unit_id <= 0x72:
        return 0x36
    if unit_id <= 0x89:
        return 0x3A
    if unit_id <= 0xA1:
        return 0x3C
    if unit_id <= 0xA9 or unit_id == 0xBC:
        return 0x3E
    if unit_id <= 0xB9:
        return 0x40
    return 0x36


def legacy_unit_icon_bank(project, unit_id: int) -> tuple[int, int]:
    raw_icon = project.record_bytes(unit_id)[2]
    page, local_tile = divmod(raw_icon, 0x40)
    if page == 0:
        bank = 0x34
    elif page == 1:
        bank = 0x35
    else:
        bank = _legacy_third_icon_bank(unit_id)
    if local_tile % 4 or local_tile + 4 > 0x40:
        raise ValueError(f"机体 ${unit_id:02X} 图标编号 ${raw_icon:02X} 不是有效的 2×2 图块起点。")
    if (bank + 1) * 64 > project.chr_tile_count:
        raise ValueError(f"机体 ${unit_id:02X} 图标图库 ${bank:02X} 超出当前 CHR。")
    return bank, local_tile


def legacy_unit_icon_side(unit_id: int) -> str:
    if not 1 <= unit_id <= 0xFF:
        raise ValueError("旧版机体图标编号必须在 001—255。")
    return "敌" if unit_id in LEGACY_ENEMY_ICON_UNIT_IDS else "我"


def _legacy_icon_image(project, unit_id: int, colors: tuple[QColor, ...]) -> QImage:
    bank, local_tile = legacy_unit_icon_bank(project, unit_id)
    image = _blank_image(16, 16)
    for quadrant in range(4):
        pixels = project.chr_tile_pixels(bank * 64 + local_tile + quadrant)
        x0 = quadrant % 2 * 8
        y0 = quadrant // 2 * 8
        for y in range(8):
            for x in range(8):
                image.setPixelColor(x0 + x, y0 + y, colors[pixels[y * 8 + x]])
    return image


def legacy_unit_export_bitmaps(project, unit_id: int) -> dict[str, bytes]:
    if not 1 <= unit_id < min(project.unit_count, 0x100):
        raise ValueError("旧版机体导出编号必须在 001—255。")
    appearance = read_unit_appearance(project, unit_id)
    body_material = render_unit_battle_preview(
        project,
        appearance,
        show_fragments=False,
        display_palette=WORK_PALETTE,
    )
    fragments_material, effect = _legacy_effect_image(project, appearance, body_material)
    side = legacy_unit_icon_side(unit_id)
    icon_game_colors = tuple(palette_color(value) for value in MAP_ICON_PALETTES_NES[side])
    icon_material_colors = tuple(QColor(*rgb) for rgb in LEGACY_MATERIAL_PALETTE_RGB)
    images = {
        "效果": effect,
        "机体": body_material,
        "碎片": fragments_material,
        "图标1": _legacy_icon_image(project, unit_id, icon_game_colors),
        "图标2": _legacy_icon_image(project, unit_id, icon_material_colors),
    }
    return {kind: _image_to_bmp(images[kind]) for kind in LEGACY_UNIT_EXPORT_SUFFIXES}


def export_legacy_unit_bitmaps(
    project,
    destination: Path,
    *,
    progress: Callable[[int, int], None] | None = None,
) -> LegacyUnitExportResult:
    """Export 001--255 sequentially and retain a per-unit failure list."""

    root = Path(destination) / LEGACY_UNIT_EXPORT_DIRECTORY
    root.mkdir(parents=True, exist_ok=True)
    written: list[Path] = []
    failures: list[tuple[int, str]] = []
    total = min(project.unit_count - 1, 0xFF)
    for unit_id in range(1, total + 1):
        try:
            name = legacy_unit_export_name(project, unit_id)
            directory = root / f"{unit_id:03d}：{name}"
            directory.mkdir(parents=True, exist_ok=True)
            for kind, payload in legacy_unit_export_bitmaps(project, unit_id).items():
                path = directory / f"{name}[{kind}].bmp"
                path.write_bytes(payload)
                written.append(path)
        except (OSError, TypeError, ValueError, IndexError) as error:
            failures.append((unit_id, str(error)))
        if progress is not None:
            progress(unit_id, total)
    return LegacyUnitExportResult(root, tuple(written), tuple(failures))
