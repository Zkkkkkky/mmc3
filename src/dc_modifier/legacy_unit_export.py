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

from .database_graphics import palette_color, read_unit_appearance, render_unit_battle_preview
from .map_page import MAP_ICON_PALETTES_NES
from .unit_appearance_dialog import WORK_PALETTE


LEGACY_UNIT_EXPORT_DIRECTORY = "导出的机体"
LEGACY_UNIT_EXPORT_SUFFIXES = ("效果", "机体", "碎片", "图标1", "图标2")
_BLACK = QColor(0, 0, 0)
_INVALID_FILENAME_CHARACTERS = '<>:"/\\|?*'


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


def _is_black(image: QImage) -> bool:
    return all(
        image.pixelColor(x, y).rgb() == _BLACK.rgb()
        for y in range(image.height())
        for x in range(image.width())
    )


def _blank_image(width: int, height: int) -> QImage:
    image = QImage(width, height, QImage.Format.Format_RGB32)
    image.fill(_BLACK)
    return image


def _legacy_effect_image(project, appearance, body_material: QImage) -> tuple[QImage, QImage]:
    """Return material fragments and the legacy game-colour composition.

    The legacy exporter treats a unit with an empty body as an entirely empty
    appearance, even if a stale/shared fragment script remains addressable.
    During composition it treats rendered black as transparent.  The latter
    matters for the two slots whose fragment palette explicitly maps a
    non-zero CHR pixel value to NES black.
    """

    if _is_black(body_material):
        blank = _blank_image(128, 128)
        return blank, blank.copy()
    fragments_material = render_unit_battle_preview(
        project,
        appearance,
        show_body=False,
        display_palette=WORK_PALETTE,
    )
    body = render_unit_battle_preview(project, appearance, show_fragments=False)
    fragments = render_unit_battle_preview(project, appearance, show_body=False)
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
    side = "敌" if appearance.configuration[0] & 0x40 else "我"
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
