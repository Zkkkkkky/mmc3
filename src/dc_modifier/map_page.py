from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QPoint, QRect, QSize, Qt, QTimer, Signal
from PySide6.QtGui import (
    QColor, QFont, QFontDatabase, QIcon, QImage, QMouseEvent, QPainter,
    QPen, QPixmap, QPolygon, QStandardItemModel,
)
from PySide6.QtWidgets import (
    QAbstractSpinBox,
    QAbstractItemView,
    QButtonGroup,
    QComboBox,
    QCheckBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QListView,
    QListWidget,
    QListWidgetItem,
    QMenu,
    QMessageBox,
    QPushButton,
    QRadioButton,
    QScrollArea,
    QSpinBox,
    QSplitter,
    QTableWidget,
    QTableWidgetItem,
    QTabWidget,
    QToolButton,
    QToolTip,
    QVBoxLayout,
    QWidget,
)

from fc_editor.dc_text import dc_map_label
from fc_editor.errors import RomFormatError
from fc_editor.expansion import FLAG_MAPS
from fc_editor.codecs.character_attributes import (
    CharacterAttributesCodec,
    weapon_extra_values,
)
from fc_editor.codecs.legacy_text_growth import LegacyGrowthCodec
from fc_editor.codecs.legacy_scenario import LegacyScenarioCodec
from fc_editor.codecs.map_trigger import MapTrigger
from fc_editor.codecs.map_tile_attribute import (
    MapTileAttribute,
    MapTileAttributeCodec,
    MapTilesetAttributes,
)

from fc_editor.models import PlayerPlacement, ScenarioEntity, ScenarioLayout

from .pages import ProjectPage
from .map_tiles import (
    TILESET_BANKS,
    TILESET_PALETTE_ROUTES,
    VERIFIED_BATTLEFIELD_PALETTES,
    campaign_tileset_key,
    render_tileset,
)
from .database_graphics import palette_color


TERRAIN_COLORS = (
    QColor("#7ebc67"),
    QColor("#4f8f54"),
    QColor("#9ba36a"),
    QColor("#9b8061"),
    QColor("#c9b56d"),
    QColor("#63a7c5"),
    QColor("#397ba7"),
    QColor("#aeb9c5"),
    QColor("#66707b"),
    QColor("#c47d66"),
    QColor("#a66f99"),
    QColor("#7371a8"),
    QColor("#c2c5ca"),
    QColor("#8e654c"),
    QColor("#d3d88b"),
    QColor("#4c5b67"),
)


# Verified battlefield blue icon palette. The CHR pixel indices must retain this
# exact NES order; the earlier hand-picked RGB tuple contained the same broad
# colours but swapped the white and dark-blue indices.
ICON_PALETTE_NES = (0x0F, 0x30, 0x21, 0x02)
ICON_PALETTE = tuple(palette_color(value) for value in ICON_PALETTE_NES)
MAP_ICON_PALETTES_NES = {
    "敌": (0x0F, 0x37, 0x27, 0x16),
    "客": (0x0F, 0x30, 0x2A, 0x1A),
    "我": ICON_PALETTE_NES,
}


class TopAnchoredComboBox(QComboBox):
    """Keep large ROM catalogs compact and expose their first item immediately."""

    def __init__(self, visible_rows: int, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setView(QListView(self))
        self.setMaxVisibleItems(visible_rows)
        # Windows' native popup style ignores maxVisibleItems for non-editable
        # combo boxes.  Opt this control into Qt's bounded list popup.
        self.setStyleSheet("QComboBox { combobox-popup: 0; }")

    def showPopup(self) -> None:
        super().showPopup()
        # QComboBox normally centres the current item.  Event IDs can contain
        # hundreds of entries, which made “地图事件 1” inaccessible without a
        # long upward scroll.  Re-anchor after Qt has laid out the popup.
        self.view().scrollToTop()
        QTimer.singleShot(0, self.view().scrollToTop)


class VisibleArrowComboBox(QComboBox):
    """Compact combo box whose arrow remains visible under the app theme."""

    def paintEvent(self, event) -> None:
        super().paintEvent(event)
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor("#40535D" if self.isEnabled() else "#9AA5AB"))
        center_x = self.width() - 10
        center_y = self.height() // 2
        painter.drawPolygon(
            QPolygon(
                (
                    QPoint(center_x - 4, center_y - 2),
                    QPoint(center_x + 4, center_y - 2),
                    QPoint(center_x, center_y + 3),
                )
            )
        )
        painter.end()

def _legacy_dpi_tile_pixmap(
    image: QImage, logical_size: int, device_pixel_ratio: float
) -> QPixmap:
    """Reproduce the reference editor's two-stage pixel-art DPI scaling."""

    base = QPixmap.fromImage(image).scaled(
        logical_size,
        logical_size,
        Qt.AspectRatioMode.IgnoreAspectRatio,
        Qt.TransformationMode.FastTransformation,
    )
    ratio = max(1.0, float(device_pixel_ratio))
    physical_size = max(logical_size, round(logical_size * ratio))
    if physical_size != logical_size:
        base = base.scaled(
            physical_size,
            physical_size,
            Qt.AspectRatioMode.IgnoreAspectRatio,
            Qt.TransformationMode.SmoothTransformation,
        )
        base.setDevicePixelRatio(ratio)
    return base

# The reference title renderer maps nonzero CHR indices from light to dark.
# The paired screenshots show index 1 as the white main stroke and index 3 as
# its darkest edge, matching the portrait-background material convention.
CHAPTER_TITLE_PALETTE_NES = (0x0F, 0x20, 0x10, 0x00)
# The three map-icon windows are switched by the scenario loader.  These routes
# were read row-by-row from the reference editor; they must not be collapsed to
# one global tuple (in particular, the third page is not always $36 or $3A).
SCENARIO_MAP_ICON_BANKS = (
    (0x34, 0x35, 0x36), (0x34, 0x35, 0x36),
    (0x34, 0x35, 0x36), (0x34, 0x35, 0x3A),
    (0x34, 0x35, 0x3A), (0x34, 0x35, 0x3C),
    (0x34, 0x35, 0x3C), (0x34, 0x35, 0x3C),
    (0x34, 0x35, 0x3C), (0x34, 0x35, 0x3E),
    (0x34, 0x35, 0x40), (0x34, 0x35, 0x3E),
    (0x34, 0x35, 0x3E), (0x34, 0x35, 0x36),
    (0x34, 0x35, 0x36), (0x34, 0x35, 0x3A),
    (0x34, 0x35, 0x3C), (0x34, 0x35, 0x3C),
    (0x34, 0x35, 0x3C), (0x34, 0x35, 0x3E),
    (0x34, 0x35, 0x3E), (0x34, 0x35, 0x3E),
    (0x34, 0x35, 0x40), (0x34, 0x35, 0x40),
    (0x34, 0x35, 0x3A), (0x34, 0x35, 0x40),
    (0x34, 0x35, 0x44), (0x46, 0x47, 0x3C),
    (0x46, 0x47, 0x48), (0x46, 0x47, 0x48),
    (0x46, 0x47, 0x48), (0x46, 0x47, 0x48),
)
MAP_ICON_BANK_CANDIDATES = tuple(
    sorted({bank for route in SCENARIO_MAP_ICON_BANKS for bank in route})
)


def scenario_map_icon_banks(map_id: int) -> tuple[int, int, int]:
    """Return the reference runtime CHR route for one playable scenario."""

    if not 0 <= map_id < len(SCENARIO_MAP_ICON_BANKS):
        raise IndexError(f"没有地图 ${map_id:02X} 的机体图标路由")
    return SCENARIO_MAP_ICON_BANKS[map_id]


def _load_action_names() -> tuple[str, ...]:
    """Load the reference action labels while keeping every byte value valid."""

    path = (
        Path(__file__).resolve().parents[1]
        / "resources"
        / "default_config"
        / "行动名称.ini"
    )
    labels: list[str] = []
    if path.is_file():
        for encoding in ("utf-8-sig", "gb18030"):
            try:
                labels = [line.strip() for line in path.read_text(encoding=encoding).splitlines()]
                break
            except UnicodeError:
                continue
    return tuple(
        labels[index] if index < len(labels) and labels[index] else "未命名/保留值"
        for index in range(256)
    )


ACTION_NAMES = _load_action_names()


class TerrainButton(QPushButton):
    """One legacy palette cell with independent left/right brush selection."""

    right_clicked = Signal(int)

    def __init__(self, tile: int) -> None:
        super().__init__("")
        self.tile = tile
        self._tile_pixmap = QPixmap()
        self.setAccessibleName(f"位图{tile:X}")

    def set_tile_pixmap(self, pixmap: QPixmap) -> None:
        self._tile_pixmap = pixmap
        self.update()

    def paintEvent(self, event) -> None:
        if self._tile_pixmap.isNull():
            super().paintEvent(event)
            return
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, False)
        painter.drawPixmap(QPoint(0, 0), self._tile_pixmap)
        if self.isChecked():
            painter.setPen(QPen(QColor("#2b769b"), 1))
            painter.drawRect(self.rect().adjusted(0, 0, -1, -1))
        painter.end()

    def mousePressEvent(self, event: QMouseEvent) -> None:
        if event.button() == Qt.MouseButton.RightButton:
            self.right_clicked.emit(self.tile)
            event.accept()
            return
        super().mousePressEvent(event)


class DimensionArrowButton(QToolButton):
    """One consistently styled direction button for both map dimensions."""

    def __init__(self, direction: Qt.ArrowType) -> None:
        super().__init__()
        self.direction = direction
        self.setArrowType(Qt.ArrowType.NoArrow)

    def paintEvent(self, event) -> None:
        super().paintEvent(event)
        center_x = self.width() // 2
        center_y = self.height() // 2
        if self.direction == Qt.ArrowType.UpArrow:
            points = ((center_x, center_y - 3),
                      (center_x - 3, center_y + 2),
                      (center_x + 3, center_y + 2))
        elif self.direction == Qt.ArrowType.DownArrow:
            points = ((center_x - 3, center_y - 2),
                      (center_x + 3, center_y - 2),
                      (center_x, center_y + 3))
        elif self.direction == Qt.ArrowType.LeftArrow:
            points = ((center_x - 3, center_y),
                      (center_x + 2, center_y - 3),
                      (center_x + 2, center_y + 3))
        else:
            points = ((center_x + 3, center_y),
                      (center_x - 2, center_y - 3),
                      (center_x - 2, center_y + 3))
        painter = QPainter(self)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor("#42677a"))
        painter.drawPolygon(QPolygon([QPoint(x, y) for x, y in points]))
        painter.end()


def render_unit_icon_bank(
    project,
    bank: int,
    palette_values: tuple[int, int, int, int] = ICON_PALETTE_NES,
) -> QImage:
    """Render a raw CHR bank as sixteen 2×2-tile map-icon candidates.

    This is a bank preview, not a claimed unit-ID or chapter binding.  The
    legacy BMP evidence establishes four 8×8 tiles per 16×16 icon.
    """

    colors = tuple(palette_color(value) for value in palette_values)
    image = QImage(256, 16, QImage.Format.Format_RGB32)
    image.fill(colors[0])
    first_tile = bank * 64
    for icon in range(16):
        for quadrant in range(4):
            pixels = project.chr_tile_pixels(first_tile + icon * 4 + quadrant)
            origin_x = icon * 16 + quadrant % 2 * 8
            origin_y = quadrant // 2 * 8
            for y in range(8):
                for x in range(8):
                    image.setPixelColor(
                        origin_x + x,
                        origin_y + y,
                        colors[pixels[y * 8 + x]],
                    )
    return image


def render_unit_map_icon(
    project,
    unit_id: int,
    side: str,
    icon_banks: tuple[int, int, int],
) -> QImage:
    """Render the unit's verified four-tile map icon with its faction palette."""

    if not 1 <= unit_id < project.unit_count:
        return QImage()
    first_tile = project.record_bytes(unit_id)[2]
    if first_tile % 4 or first_tile >= len(icon_banks) * 64:
        return QImage()
    bank = icon_banks[first_tile // 64]
    chr_first_tile = bank * 64 + first_tile % 64
    colors = tuple(
        palette_color(value)
        for value in MAP_ICON_PALETTES_NES.get(side, ICON_PALETTE_NES)
    )
    image = QImage(16, 16, QImage.Format.Format_ARGB32)
    image.fill(Qt.GlobalColor.transparent)
    for quadrant in range(4):
        pixels = project.chr_tile_pixels(chr_first_tile + quadrant)
        origin_x = quadrant % 2 * 8
        origin_y = quadrant // 2 * 8
        for y in range(8):
            for x in range(8):
                pixel = pixels[y * 8 + x]
                if pixel:
                    image.setPixelColor(origin_x + x, origin_y + y, colors[pixel])
    return image


def _glyph_file_offset(token: bytes) -> int | None:
    """Return the verified file offset of one legacy packed 12x12 glyph."""

    if len(token) != 2:
        return None
    lead, index = token
    if 0xB8 <= lead <= 0xBB:
        base = 0x6C010
        page = lead - 0xB8
    elif 0xC8 <= lead <= 0xCB:
        base = 0x70010
        page = lead - 0xC8
    elif 0xD8 <= lead <= 0xDB:
        base = 0x74010
        page = lead - 0xD8
    else:
        return None
    # Each lead owns one 0x1000-byte page.  A displayed row is 0x100
    # bytes wide and contains fourteen 18-byte 12x12 glyphs; token columns
    # E/F alias column 0 in the verified legacy address table.
    row, column = divmod(index, 0x10)
    glyph_column = column if column < 0x0E else 0
    return base + page * 0x1000 + row * 0x100 + glyph_column * 18


_TITLE_FONT_FAMILY: str | None = None


def _title_font_family() -> str:
    """Load the legacy title face explicitly so every Windows renderer agrees."""

    global _TITLE_FONT_FAMILY
    if _TITLE_FONT_FAMILY is not None:
        return _TITLE_FONT_FAMILY
    for filename in (
        "C:/Windows/Fonts/simsun.ttc",
        "C:/Windows/Fonts/simsun.ttf",
    ):
        font_id = QFontDatabase.addApplicationFont(filename)
        if font_id >= 0:
            families = QFontDatabase.applicationFontFamilies(font_id)
            if families:
                _TITLE_FONT_FAMILY = families[0]
                return _TITLE_FONT_FAMILY
    available = set(QFontDatabase.families())
    for family in ("SimSun", "NSimSun", "Microsoft YaHei UI"):
        if family in available:
            _TITLE_FONT_FAMILY = family
            return family
    _TITLE_FONT_FAMILY = QFont().defaultFamily()
    return _TITLE_FONT_FAMILY


def render_map_title(_project, title: str, *, scale: float = 10 / 3) -> QPixmap:
    """Render every chapter label with the legacy game's thin title face."""

    advance = round(12 * scale)
    margin = 8
    pixmap = QPixmap(max(1, margin * 2 + len(title) * advance), advance + margin)
    pixmap.fill(QColor("#000000"))
    painter = QPainter(pixmap)
    painter.setPen(QColor("#d8d8d8"))
    font = QFont(_title_font_family())
    # SimSun's em box contains extra vertical metrics.  A 43 px face inside
    # the game's 40 px title cell reproduces the captured 40 px ink height.
    font.setPixelSize(round(advance * 43 / 40))
    font.setStyleStrategy(QFont.StyleStrategy.NoAntialias)
    painter.setFont(font)
    for character_index, character in enumerate(title):
        origin_x = margin + character_index * advance
        painter.drawText(
            QRect(origin_x, 0, advance, pixmap.height()),
            Qt.AlignmentFlag.AlignCenter,
            character,
        )
    painter.end()
    return pixmap


def render_title_segment(
    project,
    chr_banks: tuple[int, int, int],
    segment,
    *,
    scale: int = 3,
) -> QPixmap:
    """Render one two-row title segment against its three 64-tile pages."""

    image = QImage(
        segment.width * 8,
        16,
        QImage.Format.Format_ARGB32,
    )
    image.fill(QColor("#000000"))
    colors = tuple(palette_color(value) for value in CHAPTER_TITLE_PALETTE_NES)
    for index, tile_code in enumerate(segment.tiles):
        # The title runtime leaves 00-3F on its shared episode-number page
        # and maps the three per-chapter pages to 40-7F/80-BF/C0-FF.
        bank_index = max(0, tile_code // 0x40 - 1)
        bank = chr_banks[bank_index]
        pixels = project.chr_tile_pixels(bank * 0x40 + tile_code % 0x40)
        origin_x = (index % segment.width) * 8
        origin_y = (index // segment.width) * 8
        for y in range(8):
            for x in range(8):
                image.setPixelColor(
                    origin_x + x,
                    origin_y + y,
                    colors[pixels[y * 8 + x]],
                )
    pixmap = QPixmap.fromImage(image)
    return pixmap.scaled(
        image.width() * scale,
        image.height() * scale,
        Qt.AspectRatioMode.IgnoreAspectRatio,
        Qt.TransformationMode.FastTransformation,
    )


def render_chapter_title(project, scenario_id: int, *, scale: int = 3) -> QPixmap:
    """Render the verified in-ROM title tile script for one chapter.

    The legacy preview intentionally shows the last draw segment: the earlier
    segment is the episode-number art, while the final segment is the actual
    chapter title displayed in the black preview box.
    """

    if not getattr(project, "supports_chapter_titles", False):
        return render_map_title(project, dc_map_label(scenario_id))
    try:
        record = project.get_chapter_title(scenario_id)
    except (IndexError, RomFormatError, ValueError):
        return render_map_title(project, dc_map_label(scenario_id))
    return render_title_segment(
        project,
        record.chr_banks,
        record.title_segment,
        scale=scale,
    )


class NesPaletteDialog(QDialog):
    """Four rows of sixteen colors, matching the legacy palette layout."""

    def __init__(self, current: int, parent=None) -> None:
        super().__init__(parent)
        self.selected_value = current
        self.setWindowTitle("调色板选择")
        # Keep the same dense 16 x 4 rhythm as the reference editor.  At
        # 125% Windows scaling this produces a roughly 680 x 210 px dialog:
        # large enough to read, without turning a tiny palette into a panel.
        self.setFixedSize(544, 150)
        grid = QGridLayout(self)
        grid.setContentsMargins(8, 8, 8, 8)
        grid.setHorizontalSpacing(1)
        grid.setVerticalSpacing(2)
        for value in range(0x40):
            color = palette_color(value)
            button = QPushButton(f"{value:02X}")
            button.setFixedSize(32, 30)
            button.setToolTip(
                f"NES 色号 ${value:02X} · RGB {color.name().upper()}（FCEUX.pal）"
            )
            button.setAccessibleName(f"NES颜色{value:02X}")
            foreground = "#000000" if color.lightness() >= 128 else "#FFFFFF"
            border = "2px solid #087F99" if value == current else "1px solid #59636E"
            button.setStyleSheet(
                f"background:{color.name()}; color:{foreground}; border:{border};"
                "border-radius:1px; padding:0; font-weight:600;"
            )
            button.clicked.connect(
                lambda _checked=False, selected=value: self._select(selected)
            )
            grid.addWidget(button, value // 16, value % 16)

    def _select(self, value: int) -> None:
        self.selected_value = value
        self.accept()


class NesColorButton(QPushButton):
    """A live color swatch that opens the complete NES palette."""

    value_changed = Signal(int)

    def __init__(self, value: int = 0, parent=None) -> None:
        super().__init__(parent)
        self._value = 0
        self.setMinimumSize(88, 38)
        self.clicked.connect(self.choose_color)
        self.set_value(value)

    @property
    def value(self) -> int:
        return self._value

    def set_value(self, value: int) -> None:
        normalized = max(0, min(0x3F, int(value)))
        changed = normalized != self._value
        self._value = normalized
        color = palette_color(normalized)
        foreground = "#000000" if color.lightness() >= 128 else "#FFFFFF"
        self.setText(f"${normalized:02X}")
        self.setStyleSheet(
            f"QPushButton {{ background:{color.name()}; color:{foreground}; "
            "border:2px solid #59636E; font-weight:bold; }}"
            "QPushButton:hover { border:3px solid #00A3E0; }"
        )
        self.setToolTip(
            f"NES 色号 ${normalized:02X} · RGB {color.name().upper()}（点击展开64色）"
        )
        if changed:
            self.value_changed.emit(normalized)

    def choose_color(self, _checked: bool = False) -> None:
        dialog = NesPaletteDialog(self._value, self)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            self.set_value(dialog.selected_value)


class CompactNesColorField(QWidget):
    """Reference-style small swatch plus a compact clickable NES color code."""

    value_changed = Signal(int)

    def __init__(self, value: int = 0, parent=None) -> None:
        super().__init__(parent)
        self._value = 0
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)
        self.swatch = QPushButton(self)
        self.swatch.setObjectName("compactNesSwatch")
        self.swatch.setFixedSize(25, 24)
        self.code_button = QPushButton(self)
        self.code_button.setObjectName("compactNesCode")
        self.code_button.setFixedSize(43, 24)
        layout.addWidget(self.swatch)
        layout.addWidget(self.code_button)
        self.setFixedSize(72, 24)
        self.swatch.clicked.connect(self.choose_color)
        self.code_button.clicked.connect(self.choose_color)
        self.set_value(value)

    @property
    def value(self) -> int:
        return self._value

    def set_value(self, value: int) -> None:
        normalized = max(0, min(0x3F, int(value)))
        changed = normalized != self._value
        self._value = normalized
        color = palette_color(normalized)
        tooltip = (
            f"NES 色号 ${normalized:02X} · RGB {color.name().upper()}（点击展开64色）"
        )
        self.swatch.setText("")
        self.swatch.setStyleSheet(
            f"QPushButton {{ background:{color.name()}; border:1px solid #64727A; "
            "border-radius:1px; padding:0; }}"
            "QPushButton:hover { border:2px solid #087F99; }"
        )
        self.code_button.setText(f"{normalized:02X}")
        self.code_button.setStyleSheet(
            "QPushButton { background:#F8FBFC; color:#0A6680; "
            "border:1px solid #83AFC0; border-radius:1px; padding:0; font-weight:600; }"
            "QPushButton:hover { background:#E8F5F9; border-color:#087F99; }"
        )
        self.setToolTip(tooltip)
        self.swatch.setToolTip(tooltip)
        self.code_button.setToolTip(tooltip)
        if changed:
            self.value_changed.emit(normalized)

    def choose_color(self, _checked: bool = False) -> None:
        dialog = NesPaletteDialog(self._value, self)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            self.set_value(dialog.selected_value)


class TileAttributeDialog(QDialog):
    """Editor for the verified 84-byte terrain-property record."""

    MOVE_LABELS = (
        "不能移动", "不补正", *(f"补正{value}格" for value in range(1, 16))
    )
    AIR_PASSABILITY_LABELS = ("不能通行", "可以通行")

    def __init__(self, project, tileset_key: str, images: tuple[QImage, ...], parent=None) -> None:
        super().__init__(parent)
        self.project = project
        self.tileset_key = tileset_key.upper()
        self._supported = bool(
            project is not None and project.supports_map_tile_attributes
            and self.tileset_key in MapTileAttributeCodec.KEYS
        )
        self._loading = False
        self._drafts = (
            {
                key: project.get_map_tileset_attributes(key)
                for key in MapTileAttributeCodec.KEYS
            }
            if self._supported else {}
        )
        self.setWindowTitle("编辑图块属性")
        self.setObjectName("tileAttributeDialog")
        self.resize(920, 600)
        self.setMinimumSize(860, 540)
        self.setStyleSheet(
            "QDialog#tileAttributeDialog { background: #f4f7f9; }"
            "QDialog#tileAttributeDialog QGroupBox {"
            "  background: #ffffff; border: 1px solid #b7c8d2;"
            "  border-radius: 6px; margin-top: 9px; font-weight: 600; }"
            "QDialog#tileAttributeDialog QGroupBox::title {"
            "  subcontrol-origin: margin; left: 10px; padding: 0 5px;"
            "  color: #24566a; }"
            "QDialog#tileAttributeDialog QTableWidget {"
            "  background: #ffffff; border: 1px solid #b7c8d2;"
            "  gridline-color: #d5e0e6; selection-background-color: #dceff5; }"
            "QDialog#tileAttributeDialog QHeaderView::section {"
            "  background: #e6f1f5; color: #244b5b; padding: 4px;"
            "  border: 0; border-right: 1px solid #c4d4dc;"
            "  border-bottom: 1px solid #aebfc8; font-weight: 600; }"
        )
        root = QVBoxLayout(self)
        root.setContentsMargins(10, 7, 10, 8)
        root.setSpacing(5)

        self.tileset_group = QGroupBox("图库切换")
        tileset_layout = QHBoxLayout(self.tileset_group)
        tileset_layout.setContentsMargins(9, 12, 9, 6)
        tileset_layout.setSpacing(5)
        tileset_layout.addWidget(QLabel("当前图库"))
        self.tileset_button_group = QButtonGroup(self)
        self.tileset_button_group.setExclusive(True)
        self.tileset_buttons: dict[str, QPushButton] = {}
        for key in MapTileAttributeCodec.KEYS:
            button = QPushButton(f"图库 {key}")
            button.setCheckable(True)
            button.setFixedSize(68, 27)
            button.setAccessibleName(f"切换到图库{key}")
            button.setStyleSheet(
                "QPushButton { border: 1px solid #9fb5c0; border-radius: 4px;"
                " background: #f8fbfc; color: #294c5a; }"
                "QPushButton:hover { background: #e5f3f7; border-color: #5d9caf; }"
                "QPushButton:checked { background: #287f96; color: white;"
                " border-color: #216b7d; font-weight: bold; }"
            )
            button.clicked.connect(
                lambda checked, selected=key: self._switch_tileset(selected)
                if checked else None
            )
            self.tileset_button_group.addButton(button)
            self.tileset_buttons[key] = button
            tileset_layout.addWidget(button)
        tileset_layout.addStretch(1)
        preview_title = QLabel("公共预览")
        preview_title.setStyleSheet("color: #456574; font-weight: 600;")
        tileset_layout.addWidget(preview_title)
        self.shared_palette_previews: dict[int, QLabel] = {}
        for palette_index in (2, 3):
            tileset_layout.addWidget(QLabel(f"表{palette_index}"))
            preview = QLabel()
            preview.setFixedSize(64, 24)
            preview.setAlignment(Qt.AlignmentFlag.AlignCenter)
            preview.setAccessibleName(f"颜色表{palette_index}组合预览")
            self.shared_palette_previews[palette_index] = preview
            tileset_layout.addWidget(preview)
        root.addWidget(self.tileset_group)

        self.notice = QLabel()
        self.notice.setWordWrap(True)
        self.notice.setContentsMargins(4, 0, 4, 0)
        root.addWidget(self.notice)

        self.color_group = QGroupBox("颜色表1（NES 色号）")
        color_layout = QHBoxLayout(self.color_group)
        color_layout.setContentsMargins(8, 12, 8, 6)
        color_layout.setSpacing(6)
        self.color_buttons: list[NesColorButton] = []
        for index in range(3):
            color_layout.addWidget(QLabel(f"颜色{index + 1}"))
            color_button = NesColorButton()
            color_button.setFixedSize(72, 28)
            color_button.setAccessibleName(f"颜色表1颜色{index + 1}色块")
            color_button.setToolTip("点击选择 NES 色号")
            self.color_buttons.append(color_button)
            color_layout.addWidget(color_button)
            color_button.value_changed.connect(self._refresh_color_visuals)
        color_layout.addStretch(1)
        self.palette_preview = QLabel()
        self.palette_preview.setFixedSize(104, 28)
        self.palette_preview.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.palette_preview.setAccessibleName("颜色表1四色预览")
        color_layout.addWidget(QLabel("组合预览"))
        color_layout.addWidget(self.palette_preview)

        self.shared_palette_group = QGroupBox("公共颜色表引用（只读）")
        shared_layout = QVBoxLayout(self.shared_palette_group)
        shared_layout.setContentsMargins(9, 12, 9, 6)
        shared_layout.setSpacing(2)
        self.shared_palette_tiles: dict[int, QLabel] = {}
        for palette_index in (2, 3):
            tiles = QLabel()
            tiles.setAccessibleName(f"颜色表{palette_index}引用位图")
            tiles.setWordWrap(True)
            self.shared_palette_tiles[palette_index] = tiles
            shared_layout.addWidget(tiles)
        palette_row = QHBoxLayout()
        palette_row.setSpacing(5)
        palette_row.addWidget(self.color_group, 3)
        palette_row.addWidget(self.shared_palette_group, 2)
        root.addLayout(palette_row)

        self.table = QTableWidget(16, 9)
        self.table.setIconSize(QSize(18, 18))
        self.table.setHorizontalHeaderLabels(
            (
                "位图", "颜色表", "防御补正", "海", "回血",
                "回复%", "空中通行", "陆地移动", "海上移动",
            )
        )
        self.table.verticalHeader().setVisible(False)
        self.table.verticalHeader().setDefaultSectionSize(27)
        self.table.horizontalHeader().setFixedHeight(29)
        self.table.horizontalHeader().setSectionResizeMode(
            0, QHeaderView.ResizeMode.ResizeToContents
        )
        for column, width in (
            (1, 92), (2, 86), (3, 44), (4, 48), (5, 66),
        ):
            self.table.horizontalHeader().setSectionResizeMode(
                column, QHeaderView.ResizeMode.Fixed
            )
            self.table.setColumnWidth(column, width)
        self.table.horizontalHeader().setStretchLastSection(False)
        for column in (6, 7, 8):
            self.table.horizontalHeader().setSectionResizeMode(
                column, QHeaderView.ResizeMode.Stretch
            )
        self.palette_boxes: list[QComboBox] = []
        self.defense_spins: list[QSpinBox] = []
        self.sea_checks: list[QCheckBox] = []
        self.heal_checks: list[QCheckBox] = []
        self.heal_ratio_spins: list[QSpinBox] = []
        self.air_boxes: list[QComboBox] = []
        self.land_boxes: list[QComboBox] = []
        self.sea_boxes: list[QComboBox] = []
        self._syncing_heal_controls = False
        for tile_index in range(16):
            tile_item = QTableWidgetItem(f"位图{tile_index:X}")
            if tile_index < len(images):
                tile_item.setIcon(QIcon(QPixmap.fromImage(images[tile_index])))
            tile_item.setFlags(tile_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
            self.table.setItem(tile_index, 0, tile_item)
            palette = VisibleArrowComboBox()
            palette.setFixedHeight(24)
            palette.addItems(("背景色", "颜色表1", "颜色表2", "颜色表3"))
            palette.setAccessibleName(f"位图{tile_index:X}颜色表")
            palette.setToolTip(
                "属性记录中的颜色表编号；颜色表2、3仅显示引用位图。"
            )
            palette.currentIndexChanged.connect(self._refresh_color_visuals)
            self.table.setCellWidget(tile_index, 1, palette)
            self.palette_boxes.append(palette)
            defense = QSpinBox()
            defense.setFixedHeight(24)
            defense.setRange(0, 127)
            defense.setSuffix("%")
            defense.setAccessibleName(f"位图{tile_index:X}防御补正")
            self.table.setCellWidget(tile_index, 2, defense)
            self.defense_spins.append(defense)
            sea = QCheckBox("是")
            sea.setFixedHeight(24)
            sea.setAccessibleName(f"位图{tile_index:X}海属性")
            self.table.setCellWidget(tile_index, 3, sea)
            self.sea_checks.append(sea)
            heal = QCheckBox("是")
            heal.setFixedHeight(24)
            heal.setAccessibleName(f"位图{tile_index:X}回血属性")
            heal.setToolTip(
                "游戏按图块低四位判断回血，因此全图库共用且只能选择一个图块。"
            )
            heal.toggled.connect(
                lambda checked, index=tile_index: self._set_heal_tile(index, checked)
            )
            self.table.setCellWidget(tile_index, 4, heal)
            self.heal_checks.append(heal)
            heal_ratio = QSpinBox()
            heal_ratio.setRange(1, 100)
            heal_ratio.setSuffix("%")
            heal_ratio.setFixedHeight(24)
            heal_ratio.setAccessibleName(f"位图{tile_index:X}血量回复比例")
            heal_ratio.setToolTip(
                "地形回血与母舰搭载共用 ROM 中的同一个全局比例。"
            )
            heal_ratio.valueChanged.connect(self._set_heal_ratio)
            self.table.setCellWidget(tile_index, 5, heal_ratio)
            self.heal_ratio_spins.append(heal_ratio)
            movement_boxes: list[QComboBox] = []
            for column, label in ((6, "空中"), (7, "陆地"), (8, "海上")):
                movement = VisibleArrowComboBox()
                movement.setFixedHeight(24)
                if column == 6:
                    movement.addItems(self.AIR_PASSABILITY_LABELS)
                    movement.setAccessibleName(f"位图{tile_index:X}空中通行")
                    movement.setToolTip(
                        "ROM 空中字段只允许 $00/$01：$00 不能通行，$01 可以通行。"
                    )
                else:
                    movement.addItems(self.MOVE_LABELS)
                    movement.setAccessibleName(f"位图{tile_index:X}{label}移动补正")
                    movement.setToolTip(
                        "ROM 移动编码：$00 不能移动，$01 不补正，"
                        "$02—$10 分别补正 1—15 格。"
                    )
                self.table.setCellWidget(tile_index, column, movement)
                movement_boxes.append(movement)
            self.air_boxes.append(movement_boxes[0])
            self.land_boxes.append(movement_boxes[1])
            self.sea_boxes.append(movement_boxes[2])
        root.addWidget(self.table, 1)

        self.buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Save
            | QDialogButtonBox.StandardButton.Cancel
            | QDialogButtonBox.StandardButton.RestoreDefaults
        )
        self.buttons.button(QDialogButtonBox.StandardButton.Save).setText("应用")
        self.buttons.button(QDialogButtonBox.StandardButton.Cancel).setText("取消")
        self.buttons.button(QDialogButtonBox.StandardButton.RestoreDefaults).setText(
            "还原当前图库"
        )
        for button in self.buttons.buttons():
            button.setMinimumWidth(82)
            button.setFixedHeight(29)
        self.buttons.button(QDialogButtonBox.StandardButton.Save).setStyleSheet(
            "QPushButton { background: #287f96; color: white; border: 1px solid #216b7d;"
            " border-radius: 4px; font-weight: bold; padding: 0 16px; }"
            "QPushButton:hover { background: #3295ad; }"
        )
        self.buttons.accepted.connect(self.accept)
        self.buttons.rejected.connect(self.reject)
        self.buttons.button(QDialogButtonBox.StandardButton.RestoreDefaults).clicked.connect(self._load_original)
        root.addWidget(self.buttons)

        if self._supported:
            self.tileset_buttons[self.tileset_key].setChecked(True)
            self._update_notice()
            self.notice.setToolTip(
                "海属性只读取防御字节最高位，不再根据图形猜测或自动补写；"
                "空中通行只接受 $00/$01，陆地和海上移动接受 $00—$10。"
            )
            self._load(self._drafts[self.tileset_key])
        else:
            self.notice.setText(
                f"图库 {self.tileset_key} 没有已验证的图块属性记录，当前仅显示图块预览。"
            )
            self.color_group.setEnabled(False)
            self.table.setEnabled(False)
            self.tileset_group.setEnabled(False)
            self.buttons.button(QDialogButtonBox.StandardButton.Save).setEnabled(False)
            self.buttons.button(QDialogButtonBox.StandardButton.RestoreDefaults).setEnabled(False)
        self._refresh_shared_palette_references()
        self._refresh_color_visuals()

    def _load(self, value: MapTilesetAttributes) -> None:
        self._loading = True
        try:
            for button, color in zip(self.color_buttons, value.colors, strict=True):
                button.blockSignals(True)
                button.set_value(color)
                button.blockSignals(False)
            for index, tile in enumerate(value.tiles):
                self.palette_boxes[index].setCurrentIndex(tile.palette)
                self.defense_spins[index].setValue(tile.defense)
                self.sea_checks[index].setChecked(tile.sea)
                self.sea_checks[index].setToolTip(
                    f"ROM 海属性位：{'1（是）' if tile.sea else '0（否）'}；"
                    "不根据图形推断。"
                )
                self.heal_checks[index].blockSignals(True)
                self.heal_checks[index].setChecked(tile.heal)
                self.heal_checks[index].blockSignals(False)
                self.heal_ratio_spins[index].blockSignals(True)
                self.heal_ratio_spins[index].setValue(value.heal_ratio)
                self.heal_ratio_spins[index].blockSignals(False)
                self.air_boxes[index].setCurrentIndex(tile.air_move)
                self.land_boxes[index].setCurrentIndex(tile.land_move)
                self.sea_boxes[index].setCurrentIndex(tile.sea_move)
        finally:
            self._loading = False
        self._sync_heal_enabled_state()
        self._refresh_color_visuals()

    def _set_heal_tile(self, tile_index: int, checked: bool) -> None:
        if self._syncing_heal_controls:
            return
        self._syncing_heal_controls = True
        try:
            if checked:
                for index, checkbox in enumerate(self.heal_checks):
                    if index == tile_index or not checkbox.isChecked():
                        continue
                    checkbox.blockSignals(True)
                    checkbox.setChecked(False)
                    checkbox.blockSignals(False)
            self._sync_heal_enabled_state()
        finally:
            self._syncing_heal_controls = False

    def _set_heal_ratio(self, value: int) -> None:
        if self._syncing_heal_controls:
            return
        self._syncing_heal_controls = True
        try:
            for spin in self.heal_ratio_spins:
                if spin.value() == value:
                    continue
                spin.blockSignals(True)
                spin.setValue(value)
                spin.blockSignals(False)
        finally:
            self._syncing_heal_controls = False

    def _sync_heal_enabled_state(self) -> None:
        for checkbox, spin in zip(
            self.heal_checks, self.heal_ratio_spins, strict=True
        ):
            spin.setEnabled(checkbox.isChecked())

    def _refresh_color_visuals(self, _value: int | None = None) -> None:
        if self._loading:
            return
        colors = tuple(button.value for button in self.color_buttons)
        preview_colors = (palette_color(0x0F), *(palette_color(value) for value in colors))
        preview = self._palette_strip(
            preview_colors, self.palette_preview.width(), self.palette_preview.height()
        )
        self.palette_preview.setPixmap(preview)
        self.palette_preview.setToolTip(
            "共同背景色 $0F + " + " / ".join(f"${value:02X}" for value in colors)
        )
        if not getattr(self, "_supported", False):
            return
        attributes = self._value()
        self._refresh_shared_palette_references(attributes)
        images = render_tileset(
            self.project, self.tileset_key, attributes=attributes
        )
        for tile_index, image in enumerate(images):
            item = self.table.item(tile_index, 0)
            if item is not None:
                item.setIcon(QIcon(QPixmap.fromImage(image)))

    @staticmethod
    def _palette_strip(colors, width: int, height: int) -> QPixmap:
        normalized = tuple(QColor(color) for color in colors)
        pixmap = QPixmap(width, height)
        painter = QPainter(pixmap)
        cell_width = width / max(1, len(normalized))
        for index, color in enumerate(normalized):
            left = round(index * cell_width)
            right = round((index + 1) * cell_width)
            painter.fillRect(left, 0, right - left, height, color)
        painter.setPen(QPen(QColor("#59636E"), 1))
        painter.drawRect(0, 0, width - 1, height - 1)
        painter.end()
        return pixmap

    def _refresh_shared_palette_references(
        self, attributes: MapTilesetAttributes | None = None
    ) -> None:
        if self.tileset_key not in TILESET_PALETTE_ROUTES:
            return
        if attributes is None and self._supported:
            attributes = self._drafts[self.tileset_key]
        for palette_index in (2, 3):
            preview = self.shared_palette_previews[palette_index]
            preview.setPixmap(
                self._palette_strip(
                    tuple(
                        palette_color(value)
                        for value in VERIFIED_BATTLEFIELD_PALETTES[palette_index]
                    ),
                    preview.width(),
                    preview.height(),
                )
            )
            preview.setToolTip(f"公共颜色表{palette_index}组合预览（只读）")
            used = (
                [index for index, tile in enumerate(attributes.tiles)
                 if tile.palette == palette_index]
                if attributes is not None
                else []
            )
            text = f"颜色表{palette_index}　引用位图：" + (
                "、".join(f"{index:X}" for index in used) if used else "无"
            )
            self.shared_palette_tiles[palette_index].setText(text)
            self.shared_palette_tiles[palette_index].setToolTip(
                "公用颜色表仅标明当前图库的引用关系，不在此窗口显示或修改色号。"
            )

    def _update_notice(self) -> None:
        self.notice.setText(
            f"图库 {self.tileset_key}：颜色表、防御、海属性及移动限制均按 ROM 原码读取；"
            "回血图块与回复比例为全图库共用。"
        )

    def _store_current_draft(self) -> None:
        if not self._supported:
            return
        current = self._value()
        heal_tiles = [
            index for index, tile in enumerate(current.tiles) if tile.heal
        ]
        heal_index = heal_tiles[0] if heal_tiles else None
        for key, draft in tuple(self._drafts.items()):
            base = current if key == self.tileset_key else draft
            tiles = tuple(
                MapTileAttribute(
                    tile.palette,
                    tile.defense,
                    tile.sea,
                    tile.air_move,
                    tile.land_move,
                    tile.sea_move,
                    index == heal_index,
                )
                for index, tile in enumerate(base.tiles)
            )
            self._drafts[key] = MapTilesetAttributes(
                base.colors,
                base.graphic_selector,
                tiles,
                current.heal_ratio,
            )

    def _switch_tileset(self, key: str) -> None:
        normalized = key.upper()
        if not self._supported or normalized == self.tileset_key:
            return
        self._store_current_draft()
        self.tileset_key = normalized
        self.tileset_buttons[normalized].setChecked(True)
        self._update_notice()
        self._load(self._drafts[normalized])

    def _load_original(self) -> None:
        if self._supported:
            original = self.project.get_map_tileset_attributes(
                self.tileset_key, original=True
            )
            self._drafts[self.tileset_key] = original
            self._load(original)
            self._store_current_draft()

    def _value(self) -> MapTilesetAttributes:
        current = self.project.get_map_tileset_attributes(self.tileset_key)
        tiles = tuple(
            MapTileAttribute(
                self.palette_boxes[index].currentIndex(),
                self.defense_spins[index].value(),
                self.sea_checks[index].isChecked(),
                self.air_boxes[index].currentIndex(),
                self.land_boxes[index].currentIndex(),
                self.sea_boxes[index].currentIndex(),
                self.heal_checks[index].isChecked(),
            )
            for index in range(16)
        )
        colors = tuple(button.value for button in self.color_buttons)
        return MapTilesetAttributes(  # type: ignore[arg-type]
            colors,
            current.graphic_selector,
            tiles,
            self.heal_ratio_spins[0].value(),
        )

    def accept(self) -> None:
        if not self._supported:
            return
        try:
            self._store_current_draft()
            with self.project.transaction("图库 A—H 图块属性"):
                for key in MapTileAttributeCodec.KEYS:
                    desired = self._drafts[key]
                    if desired != self.project.get_map_tileset_attributes(key):
                        self.project.set_map_tileset_attributes(key, desired)
        except (ValueError, RuntimeError) as error:
            QMessageBox.warning(self, "图块属性未应用", str(error))
            return
        super().accept()


class MapCanvas(QWidget):
    tile_painted = Signal(int, int, int)
    tile_picked = Signal(int)
    right_tile_picked = Signal(int)
    coordinate_changed = Signal(int, int)
    overlay_moved = Signal(str, int, int, int)
    overlay_selected = Signal(str, int)
    overlay_activated = Signal(str, int)
    deployment_context_requested = Signal(int, int, QPoint)
    trigger_context_requested = Signal(int, int, QPoint)

    def __init__(self) -> None:
        super().__init__()
        # A new session has no map data; do not render a synthetic green tile.
        self.map_width = 0
        self.map_height = 0
        self.tiles: list[int] = []
        self.cell_size = 24
        # The reference editor opens with the green ground tile as the left
        # brush and the four-quadrant tile as the right brush.
        self.selected_tile = 1
        self.right_selected_tile = 0
        self.tile_images: tuple[QImage, ...] = ()
        self.show_tile_ids = False
        self.overlays: list[tuple[str, int, int, str, int]] = []
        self.dragged_overlay: tuple[str, int] | None = None
        self.drag_position: QPoint | None = None
        self.drag_offset = QPoint()
        self.selected_overlay: tuple[str, int] | None = None
        self.overlay_descriptions: dict[tuple[str, int], str] = {}
        self.overlay_images: dict[tuple[str, int], QImage] = {}
        self._visible_tooltip_key: tuple[tuple[int, int], str] | None = None
        self.paint_enabled = True
        self.deployment_edit_enabled = False
        self.trigger_edit_enabled = False
        self.overlay_move_enabled = False
        self.setMouseTracking(True)

    def sizeHint(self) -> QSize:
        return QSize(self.map_width * self.cell_size, self.map_height * self.cell_size)

    def set_content(
        self,
        width: int,
        height: int,
        tiles: list[int],
        overlays: list[tuple[str, int, int, str, int]],
    ) -> None:
        self.map_width = width
        self.map_height = height
        self.tiles = tiles
        self.overlays = overlays
        self.setFixedSize(self.sizeHint())
        self.update()

    def set_cell_size(self, size: int) -> None:
        self.cell_size = size
        self.setFixedSize(self.sizeHint())
        self.update()

    def set_tile_images(self, images: tuple[QImage, ...]) -> None:
        self.tile_images = images
        self.update()

    def set_overlay_images(self, images: dict[tuple[str, int], QImage]) -> None:
        self.overlay_images = images
        self.update()

    def paintEvent(self, _event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, False)
        # The legacy Win32 editor is DPI-virtualized by Windows, so its 16 px
        # terrain cells acquire a softly interpolated 20 px presentation at
        # 125% scaling.  Use the same interpolation deliberately; nearest-
        # neighbour scaling preserves the ROM colours but makes the cyan sea
        # highlights look substantially brighter and harsher than reference.
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, True)
        for y in range(self.map_height):
            for x in range(self.map_width):
                tile = self.tiles[y * self.map_width + x]
                rect = QRect(
                    x * self.cell_size,
                    y * self.cell_size,
                    self.cell_size,
                    self.cell_size,
                )
                if len(self.tile_images) == 16:
                    painter.drawImage(rect, self.tile_images[tile])
                else:
                    painter.fillRect(rect, TERRAIN_COLORS[tile])
                if self.show_tile_ids and self.cell_size >= 25:
                    badge = QRect(rect.left() + 1, rect.top() + 1, 12, 12)
                    painter.fillRect(badge, QColor(255, 255, 255, 190))
                    painter.setPen(QColor(10, 25, 35))
                    painter.drawText(badge, Qt.AlignmentFlag.AlignCenter, f"{tile:X}")
        side_colors = {
            "敌": QColor("#d94b45"),
            "客": QColor("#e49d28"),
            "我": QColor("#2d75d2"),
            "事": QColor("#7b4dd8"),
            "店": QColor("#07866f"),
        }
        overlay_font = QFont(painter.font())
        overlays = self.overlays
        if self.dragged_overlay is not None:
            # Always paint the object being dragged last so it remains under
            # the pointer instead of disappearing behind another marker.
            overlays = sorted(
                overlays,
                key=lambda item: (item[0], item[4]) == self.dragged_overlay,
            )
        for side, x, y, label, row in overlays:
            if not 0 <= x < self.map_width or not 0 <= y < self.map_height:
                continue
            dragging = (
                self.dragged_overlay == (side, row)
                and self.drag_position is not None
            )
            if dragging:
                cell_rect = QRect(
                    self.drag_position.x() - self.drag_offset.x(),
                    self.drag_position.y() - self.drag_offset.y(),
                    self.cell_size,
                    self.cell_size,
                )
            else:
                cell_rect = QRect(
                    x * self.cell_size,
                    y * self.cell_size,
                    self.cell_size,
                    self.cell_size,
                )
            icon = self.overlay_images.get((side, row))
            if icon is not None and not icon.isNull():
                icon_rect = cell_rect
                # Keep the dark plate for visibility on detailed terrain, but
                # omit permanent faction rims and use the full map cell for
                # the authentic four-tile sprite.
                painter.fillRect(icon_rect, QColor(0, 0, 0, 235))
                painter.drawImage(icon_rect, icon)
                if self.selected_overlay == (side, row):
                    painter.setBrush(Qt.BrushStyle.NoBrush)
                    painter.setPen(
                        QPen(
                            self._drag_border_color(side, row)
                            if dragging
                            else QColor("#ffe45e"),
                            3,
                        )
                    )
                    painter.drawRect(icon_rect.adjusted(1, 1, -1, -1))
                continue
            # Empty runtime party slots do not create a unit in the game.
            # Keep them in the hit-test collection for right-click editing,
            # but do not invent a numbered machine marker on the battlefield.
            if side == "我":
                continue
            margin = max(1, self.cell_size // 16)
            rect = cell_rect.adjusted(margin, margin, -margin, -margin)
            if side in ("事", "店"):
                # Match the reference editor: a full-cell white placard with a
                # red “事”/“商” remains obvious on every terrain texture.
                painter.fillRect(rect, QColor("#fffdf7"))
                painter.setBrush(Qt.BrushStyle.NoBrush)
                painter.setPen(QPen(QColor("#d72525"), 1))
                painter.drawRect(rect.adjusted(0, 0, -1, -1))
                marker_font = QFont(painter.font())
                marker_font.setBold(True)
                marker_font.setPixelSize(max(10, self.cell_size - 6))
                painter.setFont(marker_font)
                painter.drawText(
                    rect,
                    Qt.AlignmentFlag.AlignCenter,
                    "商" if side == "店" else "事",
                )
                painter.setFont(overlay_font)
            else:
                painter.setBrush(side_colors[side])
                painter.setPen(QPen(Qt.GlobalColor.white, 2))
                painter.drawEllipse(rect)
            if self.selected_overlay == (side, row):
                painter.setBrush(Qt.BrushStyle.NoBrush)
                painter.setPen(
                    QPen(
                        self._drag_border_color(side, row)
                        if dragging
                        else QColor("#ffe45e"),
                        3,
                    )
                )
                painter.drawRect(rect.adjusted(-2, -2, 2, 2))
                painter.setPen(Qt.GlobalColor.white)
            if side not in ("事", "店") and self.cell_size >= 20:
                painter.drawText(rect, Qt.AlignmentFlag.AlignCenter, label)

    def _drag_border_color(self, side: str, row: int) -> QColor:
        """Use red over an occupied deployment cell and cyan otherwise."""

        if self.drag_position is None or side not in ("敌", "客", "我"):
            return QColor("#39c6e6")
        cell = self._cell_at(self.drag_position)
        if cell is None:
            return QColor("#d94b45")
        occupied = any(
            other_side in ("敌", "客", "我")
            and (other_side, other_row) != (side, row)
            and (other_x, other_y) == cell
            for other_side, other_x, other_y, _label, other_row in self.overlays
        )
        return QColor("#d94b45" if occupied else "#39c6e6")

    def _cell_at(self, position: QPoint) -> tuple[int, int] | None:
        x = position.x() // self.cell_size
        y = position.y() // self.cell_size
        if 0 <= x < self.map_width and 0 <= y < self.map_height:
            return x, y
        return None

    def _paint_at(self, position: QPoint, tile: int) -> None:
        if not self.paint_enabled:
            return
        cell = self._cell_at(position)
        if cell is None:
            return
        x, y = cell
        index = y * self.map_width + x
        if self.tiles[index] == tile:
            return
        self.tiles[index] = tile
        self.tile_painted.emit(x, y, tile)
        self.update(QRect(x * self.cell_size, y * self.cell_size, self.cell_size + 1, self.cell_size + 1))

    def _pick_at(self, position: QPoint, *, right: bool) -> None:
        cell = self._cell_at(position)
        if cell is None:
            return
        x, y = cell
        tile = self.tiles[y * self.map_width + x]
        if right:
            self.right_selected_tile = tile
            self.right_tile_picked.emit(tile)
        else:
            self.selected_tile = tile
            self.tile_picked.emit(tile)

    def mousePressEvent(self, event: QMouseEvent) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            cell = self._cell_at(event.position().toPoint())
            overlay = next(
                (
                    (side, row)
                    for side, x, y, _label, row in reversed(self.overlays)
                    if cell == (x, y)
                ),
                None,
            )
            if overlay is not None:
                self.dragged_overlay = overlay if self.overlay_move_enabled else None
                if self.dragged_overlay is not None and cell is not None:
                    position = event.position().toPoint()
                    self.drag_position = position
                    self.drag_offset = QPoint(
                        position.x() - cell[0] * self.cell_size,
                        position.y() - cell[1] * self.cell_size,
                    )
                    self.setCursor(Qt.CursorShape.ClosedHandCursor)
                self.selected_overlay = overlay
                self.overlay_selected.emit(*overlay)
                self.update()
            else:
                self._paint_at(event.position().toPoint(), self.selected_tile)
        elif event.button() == Qt.MouseButton.RightButton:
            cell = self._cell_at(event.position().toPoint())
            if self.deployment_edit_enabled and cell is not None:
                self.deployment_context_requested.emit(
                    cell[0], cell[1], event.globalPosition().toPoint()
                )
                event.accept()
                return
            if self.trigger_edit_enabled and cell is not None:
                self.trigger_context_requested.emit(
                    cell[0], cell[1], event.globalPosition().toPoint()
                )
                event.accept()
                return
            if event.modifiers() & Qt.KeyboardModifier.ShiftModifier:
                self._pick_at(event.position().toPoint(), right=True)
            else:
                self._paint_at(event.position().toPoint(), self.right_selected_tile)
        elif event.button() == Qt.MouseButton.MiddleButton:
            self._pick_at(event.position().toPoint(), right=False)

    def mouseMoveEvent(self, event: QMouseEvent) -> None:
        cell = self._cell_at(event.position().toPoint())
        dragging = bool(
            event.buttons() & Qt.MouseButton.LeftButton
            and self.dragged_overlay is not None
        )
        if dragging:
            self.drag_position = event.position().toPoint()
            QToolTip.hideText()
            self._visible_tooltip_key = None
            self.setToolTip("")
            self.update()
        if cell is not None:
            self.coordinate_changed.emit(*cell)
            descriptions = [] if dragging else [
                self.overlay_descriptions.get((side, row), f"{side} #{row + 1}")
                for side, x, y, _label, row in self.overlays if cell == (x, y)
            ]
            tooltip = "\n\n".join(descriptions)
            self.setToolTip(tooltip)
            tooltip_key = (cell, tooltip)
            if tooltip and tooltip_key != self._visible_tooltip_key:
                # QWidget.toolTip() is updated inside this same move event, so
                # Windows does not always start Qt's delayed tooltip timer.
                QToolTip.showText(event.globalPosition().toPoint(), tooltip, self)
                self._visible_tooltip_key = tooltip_key
            elif not tooltip and self._visible_tooltip_key is not None:
                QToolTip.hideText()
                self._visible_tooltip_key = None
        elif self._visible_tooltip_key is not None:
            QToolTip.hideText()
            self._visible_tooltip_key = None
        if event.buttons() & Qt.MouseButton.LeftButton and self.dragged_overlay is None:
            self._paint_at(event.position().toPoint(), self.selected_tile)
        elif event.buttons() & Qt.MouseButton.RightButton:
            self._paint_at(event.position().toPoint(), self.right_selected_tile)

    def leaveEvent(self, event) -> None:
        QToolTip.hideText()
        self._visible_tooltip_key = None
        self.setToolTip("")
        super().leaveEvent(event)

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:
        if event.button() == Qt.MouseButton.LeftButton and self.dragged_overlay is not None:
            cell = self._cell_at(event.position().toPoint())
            side, row = self.dragged_overlay
            self.dragged_overlay = None
            self.drag_position = None
            self.unsetCursor()
            self.update()
            if cell is not None:
                original = next(
                    ((x, y) for item_side, x, y, _label, item_row in self.overlays
                     if (item_side, item_row) == (side, row)), None
                )
                if cell != original:
                    self.overlay_moved.emit(side, row, cell[0], cell[1])

    def mouseDoubleClickEvent(self, event: QMouseEvent) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            cell = self._cell_at(event.position().toPoint())
            for side, x, y, _label, row in reversed(self.overlays):
                if cell == (x, y):
                    self.dragged_overlay = None
                    self.drag_position = None
                    self.unsetCursor()
                    self.overlay_activated.emit(side, row)
                    event.accept()
                    return
        super().mouseDoubleClickEvent(event)


class MapScrollArea(QScrollArea):
    """Notify the map page whenever the visible preview area changes size."""

    viewport_resized = Signal()

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self.viewport_resized.emit()


class ByteEntryTable(QTableWidget):
    values_changed = Signal()

    def __init__(
        self,
        headers: tuple[str, ...],
        label_providers=None,
        *,
        max_rows: int | None = None,
    ) -> None:
        super().__init__(0, len(headers))
        self.headers = headers
        self.label_providers = dict(label_providers or {})
        self.max_rows = max_rows
        self.clipboard_row: tuple[int, ...] | None = None
        self.editing_enabled = True
        self.editing_buttons: tuple[QPushButton, ...] = ()
        self._active_row_count = 0
        self._choice_labels: dict[int, tuple[str, ...]] = {}
        self._choice_models: dict[int, QStandardItemModel] = {}
        self.setHorizontalHeaderLabels(headers)
        header = self.horizontalHeader()
        header.setSectionResizeMode(QHeaderView.ResizeMode.Interactive)
        for column in range(len(headers)):
            self.setColumnWidth(column, 150 if column in self.label_providers else 62)
        self.verticalHeader().setVisible(False)
        self.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.setAlternatingRowColors(True)

    def set_rows(self, rows: list[tuple[int, ...]]) -> None:
        previous = self.blockSignals(True)
        self.setUpdatesEnabled(False)
        try:
            while QTableWidget.rowCount(self) < len(rows):
                self._append_editor_row()
            self._active_row_count = len(rows)
            for row in range(QTableWidget.rowCount(self)):
                self.setRowHidden(row, row >= self._active_row_count)
            for row, values in enumerate(rows):
                for column, value in enumerate(values):
                    editor = self.cellWidget(row, column)
                    provider = self.label_providers.get(column)
                    if editor is not None:
                        editor_previous = editor.blockSignals(True)
                        try:
                            if isinstance(editor, QComboBox) and provider is not None:
                                model = self._choice_model(column, provider)
                                if editor.model() is not model:
                                    editor.setModel(model)
                                editor.setCurrentIndex(editor.findData(value))
                            elif isinstance(editor, QSpinBox):
                                editor.setValue(value)
                        finally:
                            editor.blockSignals(editor_previous)
            if rows:
                self.setCurrentCell(0, 0)
        finally:
            self.setUpdatesEnabled(True)
            self.blockSignals(previous)
        self.values_changed.emit()
        self.set_editing_enabled(self.editing_enabled)

    def rowCount(self) -> int:  # noqa: N802
        """Return logical rows while retaining hidden editor rows for reuse."""

        return getattr(self, "_active_row_count", 0)

    def _append_editor_row(self) -> None:
        """Create one reusable physical row without changing logical data."""

        row = QTableWidget.rowCount(self)
        QTableWidget.insertRow(self, row)
        for column in range(self.columnCount()):
            provider = self.label_providers.get(column)
            editor = self._take_editor(column, provider)
            editor_previous = editor.blockSignals(True)
            if provider is not None:
                assert isinstance(editor, QComboBox)
                editor.setModel(self._choice_model(column, provider))
            self.setCellWidget(row, column, editor)
            editor.setEnabled(self.editing_enabled)
            editor.blockSignals(editor_previous)
        self.setRowHidden(row, True)

    def _take_editor(self, column: int, provider) -> QWidget:
        if provider is not None:
            editor = QComboBox()
            editor.setMaxVisibleItems(24)
            editor.currentIndexChanged.connect(self.values_changed)
            return editor
        editor = QSpinBox()
        editor.setRange(0, 255)
        hexadecimal = self.headers[column] not in ("X", "Y", "等级")
        editor.setDisplayIntegerBase(16 if hexadecimal else 10)
        editor.setPrefix("$" if hexadecimal else "")
        editor.valueChanged.connect(self.values_changed)
        return editor

    def set_editing_enabled(self, enabled: bool) -> None:
        """Keep row selection available while locking unverified record fields."""

        self.editing_enabled = enabled
        for row in range(self.rowCount()):
            for column in range(self.columnCount()):
                editor = self.cellWidget(row, column)
                if editor is not None:
                    editor.setEnabled(enabled)
        for button in self.editing_buttons:
            button.setEnabled(enabled)

    def _choice_model(self, column: int, provider) -> QStandardItemModel:
        if column not in self._choice_labels:
            self._choice_labels[column] = tuple(provider(value) for value in range(256))
        if column not in self._choice_models:
            model = QStandardItemModel(256, 1, self)
            for item_value, label in enumerate(self._choice_labels[column]):
                index = model.index(item_value, 0)
                model.setData(index, label, Qt.ItemDataRole.DisplayRole)
                model.setData(index, item_value, Qt.ItemDataRole.UserRole)
            self._choice_models[column] = model
        return self._choice_models[column]

    def add_row(
        self,
        values: tuple[int, ...] | None = None,
        *,
        row: int | None = None,
    ) -> bool:
        if self.max_rows is not None and self.rowCount() >= self.max_rows:
            return False
        values = values or tuple(0 for _ in self.headers)
        row = self.rowCount() if row is None else max(0, min(row, self.rowCount()))
        updated = self.rows()
        updated.insert(row, values)
        self.set_rows(updated)
        self.setCurrentCell(row, 0)
        return True

    def invalidate_choice_models(self) -> None:
        """Drop shared choice data after the project or scenario context changes."""

        self._choice_labels.clear()
        for model in self._choice_models.values():
            model.deleteLater()
        self._choice_models.clear()

    def refresh_choice_labels(self, column: int) -> None:
        """Refresh one context-sensitive shared model without replacing widgets."""

        provider = self.label_providers.get(column)
        if provider is None:
            return
        labels = tuple(provider(value) for value in range(256))
        self._choice_labels[column] = labels
        model = self._choice_models.get(column)
        if model is None:
            return
        for item_value, label in enumerate(labels):
            model.setData(model.index(item_value, 0), label, Qt.ItemDataRole.DisplayRole)

    def remove_selected(self) -> None:
        row = self.currentRow()
        if 0 <= row < self.rowCount():
            self.remove_row(row)

    def remove_row(self, row: int) -> None:
        if not 0 <= row < self.rowCount():
            return
        updated = self.rows()
        updated.pop(row)
        self.set_rows(updated)

    def rows(self) -> list[tuple[int, ...]]:
        result: list[tuple[int, ...]] = []
        for row in range(self.rowCount()):
            result.append(
                tuple(
                    int(
                        self.cellWidget(row, column).currentData()
                        if isinstance(self.cellWidget(row, column), QComboBox)
                        else self.cellWidget(row, column).value()
                    )
                    for column in range(self.columnCount())
                )
            )
        return result

    def copy_selected(self) -> None:
        row = self.currentRow()
        if row >= 0:
            self.clipboard_row = self.rows()[row]

    def paste_row(self) -> bool:
        if self.clipboard_row is None:
            return False
        row = self.currentRow()
        return self.add_row(
            self.clipboard_row,
            row=self.rowCount() if row < 0 else row + 1,
        )

    def duplicate_selected(self) -> bool:
        row = self.currentRow()
        if row < 0:
            return False
        return self.add_row(self.rows()[row], row=row + 1)

    def move_selected(self, direction: int) -> None:
        row = self.currentRow()
        target = row + direction
        if row < 0 or not 0 <= target < self.rowCount():
            return
        values = self.rows()
        values[row], values[target] = values[target], values[row]
        self.set_rows(values)
        self.setCurrentCell(target, 0)
        self.values_changed.emit()

    def set_row_coordinates(self, row: int, x: int, y: int) -> None:
        if not 0 <= row < self.rowCount():
            return
        previous = self.blockSignals(True)
        try:
            for column, value in ((0, x), (1, y)):
                editor = self.cellWidget(row, column)
                if isinstance(editor, QSpinBox):
                    editor.setValue(value)
            self.setCurrentCell(row, 0)
        finally:
            self.blockSignals(previous)
        self.values_changed.emit()

    def set_row_values(self, row: int, values: tuple[int, ...]) -> None:
        if not 0 <= row < self.rowCount() or len(values) != self.columnCount():
            return
        previous = self.blockSignals(True)
        try:
            for column, value in enumerate(values):
                editor = self.cellWidget(row, column)
                if isinstance(editor, QComboBox):
                    editor.setCurrentIndex(editor.findData(value))
                elif isinstance(editor, QSpinBox):
                    editor.setValue(value)
            self.setCurrentCell(row, 0)
        finally:
            self.blockSignals(previous)
        self.values_changed.emit()


class MapPage(ProjectPage):
    draft_state_changed = Signal()
    attribute_calculator_requested = Signal(int, int, int)
    database_record_requested = Signal(str, int)
    defeat_experience_requested = Signal(int, int)

    def __init__(self) -> None:
        super().__init__()
        self.setObjectName("mapPage")
        self.setStyleSheet(
            "QWidget#mapPage QGroupBox {"
            " border: 1px solid #9eafb8; border-radius: 7px; background: #ffffff; }"
            "QWidget#mapPage QTabWidget#subTabs::pane {"
            " border: 1px solid #9eafb8; border-radius: 7px; background: #ffffff; }"
            "QWidget#mapPage QComboBox, QWidget#mapPage QSpinBox, "
            "QWidget#mapPage QListWidget { border-color: #a7b7bf; }"
            "QWidget#mapPage QComboBox#mapTilesetCombo {"
            " min-height: 22px; padding-left: 4px; "
            "font-size: 11px; "
            "border: 1px solid #9fb1ba; background: #ffffff; }"
            "QWidget#mapPage QWidget#mapDimensionsRow {"
            " border: 1px solid #a7b7bf; border-radius: 6px; background: #f7f9fa; }"
            "QWidget#mapPage QPushButton, QWidget#mapPage QToolButton {"
            " border-color: #9fb1ba; }"
            "QWidget#mapPage QToolButton#mapDimensionArrow {"
            " padding: 0; margin: 0; border: 1px solid #b5c5cd; "
            "border-radius: 2px; background: #eef3f5; }"
            "QWidget#mapPage QToolButton#mapDimensionArrow:hover {"
            " background: #e1ecef; border-color: #7d9faa; }"
            "QWidget#mapPage QToolButton#mapDimensionArrow:pressed {"
            " background: #d2e2e6; }"
            "QWidget#mapPage QScrollArea#mapScrollArea {"
            " border: 1px solid #9eafb8; border-radius: 5px; background: #e9eef0; }"
            "QWidget#mapPage QListWidget#mapChapterList {"
            " border: 1px solid #9eafb8; border-radius: 5px; font-size: 13px; }"
            "QWidget#mapPage QListWidget#mapChapterList::item {"
            " min-height: 18px; padding: 1px 6px; border-radius: 3px; }"
            "QWidget#mapPage QListWidget#mapChapterList::item:alternate {"
            " background: #f5f7f8; }"
            "QWidget#mapPage QListWidget#mapChapterList::item:hover {"
            " background: #eaf1f3; color: #26343d; }"
            "QWidget#mapPage QListWidget#mapChapterList::item:selected {"
            " background: #4b8290; color: white; }"
            "QToolTip { color: #24333d; background-color: #fffdf5; "
            "border: 1px solid #c3b98e; padding: 5px; }"
        )
        self.current_map_id: int | None = None
        self.staged_tiles: list[int] = []
        self.staged_width = 1
        self.staged_height = 1
        self.hovered_cell: tuple[int, int] | None = None
        self._loaded_draft_signature: tuple | None = None
        self._commit_error: tuple[tuple, str] | None = None
        self._last_draft_state: tuple[bool, str | None] | None = None
        self._loading_map = False
        self._selecting_object = False
        self._trigger_edit_row: int | None = None
        self._deployment_edit_source: tuple[str, int] | None = None
        self._deployment_clipboard: tuple[str, tuple[int, ...]] | None = None
        # Deployment remains guarded.  Trigger/event fields have completed the
        # reference save/reopen audit and are safe to edit in the shipped UI.
        # M03 direct fields (1380/1380) and representative add/delete structure
        # saves now have reference-editor evidence.  Fixed layouts still pass
        # through _ensure_deployment_growth; expanded layouts use the shared
        # map-resource packer, so opening the editor does not weaken capacity
        # or coordinate guards.
        self._deployment_write_verified = True
        self._trigger_write_verified = True
        self._player_slot_cache_key: tuple | None = None
        self._player_slot_snapshots: tuple[dict[int, tuple[int, int]], ...] = ()
        self._chapter_title_cache: dict[tuple[int, int, int], QPixmap] = {}
        self._icon_sheet_cache: dict[int, QImage] = {}
        self._map_icon_cache: dict[
            tuple[tuple[int, int, int], str, int], QImage
        ] = {}
        self._tileset_image_cache: dict[str, tuple[QImage, ...]] = {}
        self._unit_choice_cache: dict[int, str] = {}
        self._character_choice_cache: dict[int, str] = {}
        self._deployment_description_cache: dict[
            tuple[int, str, tuple[int, ...]], str
        ] = {}
        self._weapon_description_cache: dict[int, str] = {}
        self._growth_codec_cache: LegacyGrowthCodec | None = None
        self._trigger_payload_cache: tuple[bytes, ...] | None = None
        outer = QVBoxLayout(self)
        outer.setContentsMargins(3, 8, 5, 8)
        self.main_splitter = QSplitter(Qt.Orientation.Horizontal)
        self.main_splitter.setObjectName("mapMainSplitter")
        self.main_splitter.setChildrenCollapsible(False)

        # Match the original SRW2 editor: editing tabs above the chapter list
        # on the left, with the complete battlefield occupying the right side.
        self.navigator = QWidget()
        self.navigator.setObjectName("mapLeftPane")
        self.navigator.setMinimumWidth(285)
        self.navigator.setMaximumWidth(430)
        inspector_layout = QVBoxLayout(self.navigator)
        inspector_layout.setContentsMargins(0, 0, 0, 0)
        inspector_layout.setSpacing(8)

        self.editor_tabs = QTabWidget()
        self.editor_tabs.setObjectName("subTabs")
        tile_tab = QWidget()
        tile_layout = QVBoxLayout(tile_tab)
        tile_layout.setContentsMargins(8, 8, 8, 8)
        self.brush_group = QGroupBox("地图图块设置")
        # Keep the border close to its contents instead of leaving a large
        # empty block above the bottom edge.
        self.brush_group.setMinimumHeight(195)
        brush_layout = QVBoxLayout(self.brush_group)
        brush_layout.setContentsMargins(8, 8, 8, 8)
        brush_layout.setSpacing(4)
        bitmap_row = QHBoxLayout()
        self.bitmap_selector = QComboBox()
        for key in TILESET_BANKS:
            self.bitmap_selector.addItem(f"位图{key}", key)
        self.bitmap_selector.currentIndexChanged.connect(
            self._bitmap_selector_changed
        )
        bitmap_row.addWidget(QLabel("位图选择"))
        bitmap_row.addWidget(self.bitmap_selector, 1)
        self.terrain = QComboBox(self)
        for tile in range(16):
            self.terrain.addItem(f"位图{tile:X}", tile)
        self.terrain.setCurrentIndex(1)
        self.terrain.currentIndexChanged.connect(self._terrain_selected)
        self.terrain.hide()
        self.tile_attribute_button = QPushButton("编辑图块属性")
        self.tile_attribute_button.clicked.connect(self._open_tile_attributes)
        bitmap_row.addWidget(self.tile_attribute_button)
        brush_layout.addLayout(bitmap_row)

        self.terrain_palette = QWidget()
        self.terrain_palette.setObjectName("terrainPalette")
        self.terrain_palette.setFixedSize(256, 65)
        self.terrain_palette.setStyleSheet(
            "QWidget#terrainPalette { background: #000000; border: none; }"
        )
        palette = QGridLayout(self.terrain_palette)
        palette.setContentsMargins(0, 0, 0, 0)
        palette.setHorizontalSpacing(0)
        # A dedicated black row cannot be swallowed by either tile's paint
        # path or by fractional Windows DPI scaling.
        palette.setVerticalSpacing(1)
        palette.setAlignment(
            Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop
        )
        self.terrain_buttons = QButtonGroup(self)
        self.terrain_buttons.setExclusive(True)
        for tile in range(16):
            button = TerrainButton(tile)
            button.setObjectName("terrainButton")
            button.setCheckable(True)
            button.setFixedSize(32, 32)
            button.setIconSize(QSize(32, 32))
            button.setToolTip(
                f"位图{tile:X}：左键设为左键画笔，右键设为右键画笔"
            )
            button.setStyleSheet(
                "QPushButton#terrainButton { border: none; border-radius: 0; "
                "padding: 0; margin: 0; min-width: 32px; max-width: 32px; "
                "min-height: 32px; max-height: 32px; "
                "background: transparent; }"
                "QPushButton#terrainButton:hover, "
                "QPushButton#terrainButton:pressed, "
                "QPushButton#terrainButton:focus { border: none; "
                "background: transparent; }"
                "QPushButton#terrainButton:checked { border: 1px solid #2b769b; "
                "background: transparent; }"
            )
            self.terrain_buttons.addButton(button, tile)
            button.clicked.connect(lambda _checked=False, value=tile: self.terrain.setCurrentIndex(value))
            button.right_clicked.connect(self._select_right_brush)
            palette.addWidget(button, tile // 8, tile % 8)
        self.terrain_buttons.button(1).setChecked(True)
        brush_layout.addWidget(
            self.terrain_palette,
            0,
            Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop,
        )
        # Restore the reference editor's breathing room between the 8×2 tile
        # sheet and the left/library/right brush summary row.
        brush_layout.addSpacing(8)

        brush_row = QHBoxLayout()
        brush_row.setSpacing(4)
        left_brush = QVBoxLayout()
        left_brush.setSpacing(2)
        left_brush.setAlignment(Qt.AlignmentFlag.AlignTop)
        left_caption = QLabel("左键")
        left_caption.setAlignment(Qt.AlignmentFlag.AlignCenter)
        left_caption.setFixedHeight(18)
        self.left_brush_preview = QLabel("暂无图块")
        self.left_brush_preview.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.left_brush_preview.setFixedSize(32, 32)
        self.left_brush_preview.setStyleSheet(
            "background: #edf1f3; color: #52636d; border: 1px solid #9eabb2;"
        )
        left_brush.addWidget(left_caption)
        left_brush.addWidget(self.left_brush_preview)
        brush_row.addLayout(left_brush, 3)

        library = QVBoxLayout()
        library.setSpacing(2)
        library_caption = QLabel("图库选择")
        library_caption.setAlignment(Qt.AlignmentFlag.AlignCenter)
        library_caption.setFixedHeight(18)
        self.tileset = QComboBox()
        self.tileset.setObjectName("mapTilesetCombo")
        # Keep the complete bank/address text visible beside the drop-down arrow.
        self.tileset.setFixedSize(128, 24)
        # Keep the closed selector compact like the reference editor, while
        # allowing every real six-digit CHR address to remain visible in the
        # popup list.
        self.tileset.view().setMinimumWidth(180)
        for key, bank in TILESET_BANKS.items():
            self.tileset.addItem(f"[{bank:02X}]{bank:03d}: 图库{key}", key)
        self.tileset.currentIndexChanged.connect(self._refresh_tile_visuals)
        library.addWidget(library_caption)
        library.addWidget(self.tileset)
        library.addStretch()
        brush_row.addLayout(library, 5)

        right_brush = QVBoxLayout()
        right_brush.setSpacing(2)
        right_brush.setAlignment(Qt.AlignmentFlag.AlignTop)
        right_caption = QLabel("右键")
        right_caption.setAlignment(Qt.AlignmentFlag.AlignCenter)
        right_caption.setFixedHeight(18)
        self.right_brush_preview = QLabel("暂无图块")
        self.right_brush_preview.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.right_brush_preview.setFixedSize(32, 32)
        self.right_brush_preview.setStyleSheet(
            "background: #edf1f3; color: #52636d; border: 1px solid #9eabb2;"
        )
        right_brush.addWidget(right_caption)
        right_brush.addWidget(self.right_brush_preview)
        brush_row.addLayout(right_brush, 3)
        brush_layout.addLayout(brush_row)

        self.right_terrain = QComboBox(self)
        for tile in range(16):
            self.right_terrain.addItem(f"位图{tile:X}", tile)
        self.right_terrain.currentIndexChanged.connect(self._right_terrain_selected)
        self.right_terrain.hide()

        self.tileset_meta = QLabel("—")
        self.tileset_meta.setObjectName("hintText")
        self.tileset_meta.setWordWrap(True)
        self.show_ids = QCheckBox("在地图格左上角显示逻辑编号")
        self.show_ids.toggled.connect(self._show_ids_changed)
        self.brush_hint = QLabel(
            "在图块上用左右键分别选择画笔；地图上左右键均可连续绘制，中键吸取左键画笔。"
        )
        brush_hint = self.brush_hint
        brush_hint.setObjectName("hintText")
        brush_hint.setWordWrap(True)
        tile_layout.addWidget(self.brush_group)

        dimensions = QWidget()
        dimensions.setObjectName("mapDimensionsRow")
        dimensions_layout = QGridLayout(dimensions)
        dimensions_layout.setContentsMargins(10, 6, 10, 6)
        self.width_editor = QSpinBox()
        self.width_editor.setRange(1, 32)
        self.height_editor = QSpinBox()
        self.height_editor.setRange(1, 32)
        self.width_display = QSpinBox()
        self.width_display.setRange(1, 32)
        self.width_display.setButtonSymbols(
            QAbstractSpinBox.ButtonSymbols.NoButtons
        )
        self.width_display.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.height_display = QSpinBox()
        self.height_display.setObjectName("mapHeightSpin")
        self.height_display.setRange(1, 32)
        self.height_display.setButtonSymbols(
            QAbstractSpinBox.ButtonSymbols.NoButtons
        )
        self.height_display.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.width_display.setAccessibleName("地图宽度")
        self.height_display.setAccessibleName("地图高度")
        self.width_display.valueChanged.connect(self._resize_map_from_main)
        self.height_display.valueChanged.connect(self._resize_map_from_main)
        self.resize_button = QPushButton("调整尺寸")
        self.resize_button.clicked.connect(self._resize_map)
        self.width_decrease_button = DimensionArrowButton(Qt.ArrowType.LeftArrow)
        self.width_decrease_button.setObjectName("mapDimensionArrow")
        self.width_decrease_button.setAutoRepeat(True)
        self.width_decrease_button.setFixedSize(15, 28)
        self.width_decrease_button.setToolTip("地图宽度减 1")
        self.width_decrease_button.clicked.connect(self.width_display.stepDown)
        self.width_increase_button = DimensionArrowButton(Qt.ArrowType.RightArrow)
        self.width_increase_button.setObjectName("mapDimensionArrow")
        self.width_increase_button.setAutoRepeat(True)
        self.width_increase_button.setFixedSize(15, 28)
        self.width_increase_button.setToolTip("地图宽度加 1")
        self.width_increase_button.clicked.connect(self.width_display.stepUp)
        self.height_decrease_button = DimensionArrowButton(Qt.ArrowType.DownArrow)
        self.height_decrease_button.setObjectName("mapDimensionArrow")
        self.height_decrease_button.setAutoRepeat(True)
        self.height_decrease_button.setFixedSize(15, 14)
        self.height_decrease_button.setToolTip("地图高度减 1")
        self.height_decrease_button.clicked.connect(self.height_display.stepDown)
        self.height_increase_button = DimensionArrowButton(Qt.ArrowType.UpArrow)
        self.height_increase_button.setObjectName("mapDimensionArrow")
        self.height_increase_button.setAutoRepeat(True)
        self.height_increase_button.setFixedSize(15, 14)
        self.height_increase_button.setToolTip("地图高度加 1")
        self.height_increase_button.clicked.connect(self.height_display.stepUp)
        height_control = QWidget()
        height_control.setFixedWidth(68)
        height_control_layout = QHBoxLayout(height_control)
        height_control_layout.setContentsMargins(0, 0, 0, 0)
        height_control_layout.setSpacing(0)
        self.height_display.setFixedHeight(28)
        height_control_layout.addWidget(self.height_display, 1)
        height_arrow_column = QWidget()
        height_arrow_column.setFixedSize(15, 28)
        height_arrow_layout = QVBoxLayout(height_arrow_column)
        height_arrow_layout.setContentsMargins(0, 0, 0, 0)
        height_arrow_layout.setSpacing(0)
        height_arrow_layout.addWidget(self.height_increase_button)
        height_arrow_layout.addWidget(self.height_decrease_button)
        height_control_layout.addWidget(height_arrow_column)
        width_control = QWidget()
        width_control.setFixedWidth(68)
        width_control_layout = QHBoxLayout(width_control)
        width_control_layout.setContentsMargins(0, 0, 0, 0)
        width_control_layout.setSpacing(0)
        self.width_display.setFixedHeight(28)
        width_control_layout.addWidget(self.width_display, 1)
        width_control_layout.addWidget(self.width_decrease_button)
        width_control_layout.addWidget(self.width_increase_button)
        dimensions_layout.addWidget(QLabel("地图高度"), 0, 0)
        dimensions_layout.addWidget(height_control, 0, 1)
        dimensions_layout.addWidget(QLabel("地图宽度"), 0, 2)
        dimensions_layout.addWidget(width_control, 0, 3)
        self.prelude = QLineEdit()
        self.prelude.setPlaceholderText("前导字节，例如 01 02；不含 FF")
        self.prelude.textChanged.connect(self._update_size_label)
        tile_layout.addWidget(dimensions)
        # The reference editor deliberately leaves one compact separator row
        # between the size controls and the black title strip.  Keeping that
        # rhythm also prevents the chapter selector from visually merging into
        # the map-block controls on high-DPI Windows displays.
        tile_layout.addSpacing(8)

        self.title_preview = QLabel("未载入ROM")
        self.title_preview.setObjectName("legacyMapTitlePreview")
        self.title_preview.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.title_preview.setMinimumHeight(48)
        self.title_preview.setMaximumHeight(64)
        self.title_preview.setStyleSheet(
            "background: #111719; color: #dce6f0; border: 1px solid #2c373c; "
            "border-radius: 5px;"
        )
        tile_layout.addWidget(self.title_preview)
        self.open_map_advanced_button = QPushButton("高级地图数据…")
        self.open_map_advanced_button.clicked.connect(self._show_map_advanced)
        self.capacity_help_button = QPushButton("容量规划…")
        self.capacity_help_button.setToolTip(
            "原记录容量不足时，可在464 KiB版本中规划并接通地图共享池；保留当前地图草稿。"
        )
        self.capacity_help_button.clicked.connect(self._open_capacity_planner)
        tile_layout.addStretch()
        self.editor_tabs.addTab(tile_tab, "战场地图")

        initial_tab = QWidget()
        initial_layout = QVBoxLayout(initial_tab)
        initial_layout.setContentsMargins(8, 8, 8, 8)
        # Keep the semantic summary available to diagnostics, but do not show
        # the explanatory paragraph in the reference-style initial tab.
        self.deployment_summary = QLabel("选择地图以查看实际部署", initial_tab)
        self.deployment_summary.setWordWrap(True)
        self.deployment_summary.hide()
        self.deployment_objects = QListWidget(initial_tab)
        self.deployment_objects.setAlternatingRowColors(True)
        self.deployment_objects.currentItemChanged.connect(self._object_list_selected)
        self.deployment_objects.itemClicked.connect(self._object_list_selected)
        self.deployment_objects.itemDoubleClicked.connect(self._object_list_activated)
        self.deployment_objects.setMinimumHeight(65)
        self.deployment_objects.setMaximumHeight(120)
        self.deployment_objects.hide()
        icon_group = QGroupBox("机体图标")
        icon_group.setFixedHeight(325)
        self.icon_preview_group = icon_group
        icon_group_layout = QGridLayout(icon_group)
        icon_group_layout.setContentsMargins(8, 6, 8, 6)
        icon_group_layout.setHorizontalSpacing(6)
        icon_group_layout.setVerticalSpacing(3)
        self.icon_bank_selectors: list[QComboBox] = []
        self.icon_sheet_labels: list[QLabel] = []
        for slot, default_bank in enumerate(SCENARIO_MAP_ICON_BANKS[0], start=1):
            address_label = QLabel(f"图标地址{slot}:")
            address_label.setAlignment(
                Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter
            )
            selector = QComboBox()
            selector.setFixedWidth(180)
            selector.setMaxVisibleItems(20)
            selector.setToolTip(
                "只读兼容选择：切换活动CHR图标预览，不改写关卡图标绑定。"
            )
            for bank in range(0x100):
                selector.addItem(f"[{bank:02X}]{bank:03d}", bank)
            selector.setCurrentIndex(selector.findData(default_bank))
            selector.currentIndexChanged.connect(self._refresh_icon_sheets)
            preview = QLabel("尚未载入 ROM")
            preview.setObjectName("legacyIconSheet")
            preview.setAlignment(
                Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter
            )
            preview.setFixedSize(256, 64)
            preview.setStyleSheet("background: transparent; border: none;")
            row = (slot - 1) * 2
            icon_group_layout.addWidget(address_label, row, 0)
            icon_group_layout.addWidget(selector, row, 1, 1, 2)
            icon_group_layout.addWidget(preview, row + 1, 0, 1, 3)
            self.icon_bank_selectors.append(selector)
            self.icon_sheet_labels.append(preview)
        icon_group_layout.setColumnStretch(2, 1)
        initial_layout.addWidget(icon_group)
        icon_group.setVisible(True)
        initial_layout.addStretch()

        self.edit_deployment_button = QPushButton("编辑")
        self.edit_deployment_button.setToolTip("编辑地图上当前选中的部署机体")
        self.edit_deployment_button.clicked.connect(self._edit_selected_deployment)
        self.add_deployment_button = QPushButton("添加")
        self.add_deployment_button.setToolTip(
            "在鼠标当前所在地图格添加部署；未指向地图时从 (0,0) 开始设置"
        )
        self.add_deployment_button.clicked.connect(self._add_deployment_from_toolbar)
        self.copy_deployment_button = QPushButton("复制")
        self.copy_deployment_button.setToolTip("复制地图上当前选中的部署机体")
        self.copy_deployment_button.clicked.connect(self._duplicate_selected_deployment)
        for button in (
            self.edit_deployment_button,
            self.add_deployment_button,
            self.copy_deployment_button,
        ):
            button.setVisible(False)

        # Keep the editable tables as an internal data model for the map and the
        # three direct action buttons.  The former expandable/detail dialog is
        # intentionally gone from the product UI.
        self.deployment_model_host = QWidget(initial_tab)
        self.deployment_model_host.hide()
        deployment_layout = QVBoxLayout(self.deployment_model_host)
        self.deployment_tabs = QTabWidget()
        self.deployment_tabs.setObjectName("subTabs")
        enemy_host = QWidget()
        enemy_layout = QVBoxLayout(enemy_host)
        self.enemy_table = self._deployment_group(
            enemy_layout,
            "敌军",
            ("X", "Y", "驾驶员", "机体", "等级", "标志"),
            {
                2: self._character_choice_label,
                3: self._unit_choice_label,
                5: self._action_choice_label,
            },
            max_rows=18,
        )
        self.deployment_tabs.addTab(enemy_host, "敌军")
        guest_host = QWidget()
        guest_layout = QVBoxLayout(guest_host)
        self.guest_table = self._deployment_group(
            guest_layout,
            "客军",
            ("X", "Y", "驾驶员", "机体", "等级", "标志"),
            {
                2: self._character_choice_label,
                3: self._unit_choice_label,
                5: self._action_choice_label,
            },
            max_rows=3,
        )
        self.deployment_tabs.addTab(guest_host, "客军")
        player_host = QWidget()
        player_layout = QVBoxLayout(player_host)
        self.player_table = self._deployment_group(
            player_layout,
            "我方出击位",
            ("X", "Y", "队伍槽", "行动"),
            {2: self._player_slot_choice_label, 3: self._action_choice_label},
            max_rows=11,
        )
        self.deployment_tabs.addTab(player_host, "我方出击位")
        deployment_layout.addWidget(self.deployment_tabs, 1)
        self._build_deployment_cell_dialog()
        self.editor_tabs.addTab(initial_tab, "初始配置")

        trigger_tab = QWidget()
        trigger_layout = QVBoxLayout(trigger_tab)
        trigger_layout.setContentsMargins(8, 8, 8, 8)
        self.trigger_summary = QLabel("选择关卡后，可查看地图事件和商店入口")
        self.trigger_summary.setWordWrap(True)
        trigger_layout.addWidget(self.trigger_summary)
        self.trigger_objects = QListWidget()
        self.trigger_objects.setObjectName("triggerObjectList")
        self.trigger_objects.setAlternatingRowColors(True)
        self.trigger_objects.setContextMenuPolicy(
            Qt.ContextMenuPolicy.CustomContextMenu
        )
        self.trigger_objects.currentItemChanged.connect(self._object_list_selected)
        self.trigger_objects.itemClicked.connect(self._object_list_selected)
        self.trigger_objects.itemDoubleClicked.connect(self._object_list_activated)
        self.trigger_objects.customContextMenuRequested.connect(
            self._show_trigger_list_context_menu
        )
        trigger_layout.addWidget(self.trigger_objects, 1)
        self.trigger_dialog = QDialog(self)
        self.trigger_dialog.setWindowTitle("全部地图事件与商店")
        self.trigger_dialog.setModal(False)
        self.trigger_dialog.resize(900, 580)
        trigger_dialog_layout = QVBoxLayout(self.trigger_dialog)
        trigger_hint = QLabel(
            "这里列出人物走到指定格子时触发的内容。地图上的白底红字“事”表示地图事件，"
            "白底红字“商”表示商店入口；选择“任意我方人物”时，任意我方单位走到该格都能触发。"
        )
        trigger_hint.setObjectName("hintText")
        trigger_hint.setWordWrap(True)
        trigger_dialog_layout.addWidget(trigger_hint)
        self.trigger_table = self._deployment_group(
            trigger_dialog_layout,
            "地图事件与商店入口",
            ("X", "Y", "触发人物", "触发内容"),
            {2: self._trigger_character_label, 3: self._trigger_event_label},
            default_values=(0, 0, 0xFF, 0),
        )
        trigger_close = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        trigger_close.button(QDialogButtonBox.StandardButton.Close).setText("关闭")
        trigger_close.rejected.connect(self.trigger_dialog.close)
        trigger_dialog_layout.addWidget(trigger_close)

        self.trigger_cell_dialog = QDialog(self)
        self.trigger_cell_dialog.setObjectName("embeddedEditorDialog")
        self.trigger_cell_dialog.setWindowTitle("设置地图事件")
        self.trigger_cell_dialog.setModal(True)
        self.trigger_cell_dialog.setMinimumWidth(430)
        trigger_cell_layout = QVBoxLayout(self.trigger_cell_dialog)
        trigger_cell_layout.setContentsMargins(16, 14, 16, 14)
        trigger_cell_layout.setSpacing(10)
        trigger_condition_group = QGroupBox("触发条件")
        trigger_condition_form = QFormLayout(trigger_condition_group)
        trigger_condition_form.setContentsMargins(12, 16, 12, 10)
        trigger_condition_form.setHorizontalSpacing(12)
        trigger_condition_form.setVerticalSpacing(8)
        self.trigger_x_editor = QSpinBox()
        self.trigger_y_editor = QSpinBox()
        for editor in (self.trigger_x_editor, self.trigger_y_editor):
            editor.setRange(0, 255)
        self.trigger_character_combo = TopAnchoredComboBox(10)
        self.trigger_character_combo.setToolTip(
            "ROM 会在我方人物走到该格时比较人物编号；选择“任意我方人物”会写入 $FF，"
            "游戏遇到 $FF 会直接通过人物判断。这个判断位于事件/商店分流之前，"
            "所以地图事件同样可以限定人物；旧修改器只是没有开放这项能力。"
            "敌方单位走另一条行动路径，不会因 $FF 获得触发资格。"
        )
        trigger_condition_form.addRow("谁可以触发", self.trigger_character_combo)
        kind_widget = QWidget()
        kind_widget.setObjectName("transparentHost")
        kind_row = QHBoxLayout(kind_widget)
        kind_row.setContentsMargins(0, 0, 0, 0)
        self.trigger_shop_radio = QRadioButton("进入商店")
        self.trigger_event_radio = QRadioButton("触发地图事件")
        self.trigger_event_radio.setChecked(True)
        self.trigger_shop_radio.toggled.connect(self._trigger_kind_changed)
        self.trigger_event_radio.toggled.connect(self._trigger_kind_changed)
        kind_row.addWidget(self.trigger_event_radio)
        kind_row.addWidget(self.trigger_shop_radio)
        kind_row.addStretch()
        trigger_condition_form.addRow("触发后", kind_widget)
        trigger_cell_layout.addWidget(trigger_condition_group)

        trigger_target_group = QGroupBox("触发内容")
        trigger_cell_form = QFormLayout(trigger_target_group)
        trigger_cell_form.setContentsMargins(12, 16, 12, 10)
        trigger_cell_form.setHorizontalSpacing(12)
        trigger_cell_form.setVerticalSpacing(8)
        self.trigger_shop_combo = QComboBox()
        self.trigger_shop_combo.setMaxVisibleItems(5)
        for shop_id in range(0xF0, 0xF5):
            self.trigger_shop_combo.addItem(
                f"商店 {shop_id - 0xF0 + 1}",
                shop_id,
            )
        trigger_cell_form.addRow("进入哪家商店", self.trigger_shop_combo)
        self.trigger_event_combo = TopAnchoredComboBox(10)
        for event_id in range(0xF0):
            self.trigger_event_combo.addItem(
                self._trigger_event_label(event_id),
                event_id,
            )
        trigger_cell_form.addRow("执行哪个事件", self.trigger_event_combo)
        trigger_cell_layout.addWidget(trigger_target_group)
        self.trigger_kind_hint = QLabel()
        self.trigger_kind_hint.setObjectName("infoPanel")
        self.trigger_kind_hint.setWordWrap(True)
        trigger_cell_layout.addWidget(self.trigger_kind_hint)
        self.trigger_cell_buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok
            | QDialogButtonBox.StandardButton.Cancel
        )
        self.trigger_cell_buttons.button(
            QDialogButtonBox.StandardButton.Ok
        ).setText("确定")
        self.trigger_cell_buttons.button(
            QDialogButtonBox.StandardButton.Cancel
        ).setText("取消")
        self.trigger_delete_button = self.trigger_cell_buttons.addButton(
            "删除地图事件", QDialogButtonBox.ButtonRole.DestructiveRole
        )
        self.trigger_cell_buttons.button(
            QDialogButtonBox.StandardButton.Ok
        ).setObjectName("primaryButton")
        self.trigger_delete_button.setObjectName("destructiveButton")
        self.trigger_cell_buttons.accepted.connect(self._save_trigger_cell_editor)
        self.trigger_cell_buttons.rejected.connect(self.trigger_cell_dialog.reject)
        self.trigger_delete_button.clicked.connect(self._delete_edited_trigger)
        trigger_cell_layout.addWidget(self.trigger_cell_buttons)
        self._trigger_kind_changed()
        self.editor_tabs.addTab(trigger_tab, "地图事件/商店")

        self.chapter_group = QGroupBox("关卡选择")
        chapter_layout = QVBoxLayout(self.chapter_group)
        # Reserve the title band instead of letting the first list row crowd
        # or cover the group-box caption at Windows fractional DPI values.
        chapter_layout.setContentsMargins(8, 18, 8, 8)
        chapter_layout.setSpacing(0)
        self.map_list = QListWidget()
        self.map_list.setObjectName("mapChapterList")
        chapter_font = QFont(self.map_list.font())
        chapter_font.setPixelSize(13)
        self.map_list.setFont(chapter_font)
        self.map_list.setAlternatingRowColors(True)
        self.map_list.setUniformItemSizes(True)
        self.map_list.currentItemChanged.connect(self._map_selected)
        chapter_layout.addWidget(self.map_list)
        self.chapter_group.setMinimumHeight(235)
        inspector_layout.addWidget(self.editor_tabs, 2)
        inspector_layout.addWidget(self.chapter_group, 3)
        self.editor_tabs.currentChanged.connect(self._editor_mode_changed)
        self.main_splitter.addWidget(self.navigator)

        self.canvas_host = QWidget()
        self.canvas_host.setObjectName("mapPreviewPane")
        self.canvas_host.setMinimumWidth(360)
        canvas_layout = QVBoxLayout(self.canvas_host)
        canvas_layout.setContentsMargins(0, 0, 0, 0)
        self.zoom = QSpinBox()
        self.zoom.setRange(8, 40)
        self.zoom.setValue(24)
        self.zoom.setSuffix(" px")
        self.zoom.valueChanged.connect(self._zoom_changed)
        self.fit_view = QCheckBox("全景适应")
        self.fit_view.setToolTip("自动缩放地图，使全部地图格始终位于可视区域内")
        self.fit_view.setChecked(True)
        self.fit_view.toggled.connect(self._fit_view_changed)
        self.zoom.setEnabled(False)
        self.position_label = QLabel("X坐标：—")
        self.y_position_label = QLabel("Y坐标：—")
        for coordinate_label in (self.position_label, self.y_position_label):
            coordinate_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
            coordinate_label.hide()
        self.size_label = QLabel("—")
        self.size_label.setObjectName("hintText")
        self.canvas = MapCanvas()
        self.canvas.tile_painted.connect(self._tile_painted)
        self.canvas.tile_picked.connect(self.terrain.setCurrentIndex)
        self.canvas.right_tile_picked.connect(self.right_terrain.setCurrentIndex)
        self.canvas.coordinate_changed.connect(self._canvas_coordinate_changed)
        self.canvas.overlay_moved.connect(self._overlay_moved)
        self.canvas.overlay_selected.connect(self._select_object)
        self.canvas.overlay_activated.connect(self._activate_object)
        self.canvas.deployment_context_requested.connect(
            self._show_deployment_context_menu
        )
        self.canvas.trigger_context_requested.connect(self._show_trigger_context_menu)
        self.map_scroll = MapScrollArea()
        self.map_scroll.setObjectName("mapScrollArea")
        self.map_scroll.setWidget(self.canvas)
        self.map_scroll.setWidgetResizable(False)
        self.map_scroll.setHorizontalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAsNeeded
        )
        self.map_scroll.setVerticalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAsNeeded
        )
        self.map_scroll.setAlignment(
            Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop
        )
        self.map_scroll.viewport_resized.connect(self._fit_map_to_viewport)
        self.show_all_objects = QCheckBox("叠加全部对象")
        self.show_all_objects.setToolTip("在地形页同时显示部署、事件和商店；编辑对象页不会误画地形。")
        self.show_all_objects.toggled.connect(self._update_overlays)
        canvas_layout.addWidget(self.map_scroll, 1)

        self.deployment_selection_preview = QLabel(
            "配置预览：左键选择地图上的已配置单位"
        )
        self.deployment_selection_preview.setObjectName("deploymentSelectionPreview")
        self.deployment_selection_preview.setWordWrap(True)
        self.deployment_selection_preview.setMinimumHeight(42)
        self.deployment_selection_preview.setMaximumHeight(54)
        self.deployment_selection_preview.setToolTip(
            "左键选择单位后显示配置摘要；双击或点击“编辑”可修改。"
        )
        self.deployment_selection_preview.hide()
        canvas_layout.addWidget(self.deployment_selection_preview)

        deployment_action_row = QHBoxLayout()
        deployment_action_row.setContentsMargins(0, 2, 0, 0)
        deployment_action_row.addWidget(self.edit_deployment_button)
        deployment_action_row.addWidget(self.add_deployment_button)
        deployment_action_row.addWidget(self.copy_deployment_button)
        deployment_action_row.addStretch()
        canvas_layout.addLayout(deployment_action_row)

        self.reset_button = QPushButton("还原当前地图")
        self.reset_button.clicked.connect(self.reset_current)
        self.reset_button.setToolTip("将当前地图、部署和事件恢复为打开工程时的内容")
        map_action_row = QHBoxLayout()
        map_action_row.setContentsMargins(0, 2, 0, 0)
        map_action_row.addWidget(self.reset_button)
        map_action_row.addStretch()
        map_action_row.addWidget(self.open_map_advanced_button)
        map_action_row.addWidget(self.capacity_help_button)
        canvas_layout.addLayout(map_action_row)

        self.pending_state = QLabel("尚未载入ROM：按 Ctrl+O 或“文件→打开”选择基准ROM。")
        self.pending_state.setObjectName("editState")
        self.apply_button = QPushButton("应用地图、部署与事件")
        self.apply_button.setObjectName("primaryButton")
        self.apply_button.clicked.connect(self.apply_changes)
        self.apply_button.setEnabled(False)
        self.size_label.setWordWrap(False)
        self.pending_state.setWordWrap(True)
        canvas_layout.addWidget(self.size_label)
        status_row = QHBoxLayout()
        status_row.addWidget(self.pending_state, 1)
        status_row.addWidget(self.apply_button)
        canvas_layout.addLayout(status_row)
        for side, table in (("敌", self.enemy_table), ("客", self.guest_table),
                            ("我", self.player_table), ("事", self.trigger_table)):
            table.currentCellChanged.connect(
                lambda row, _column, _old_row, _old_column, kind=side:
                    self._table_selection_changed(kind, row)
            )
        self.main_splitter.addWidget(self.canvas_host)

        self.main_splitter.setStretchFactor(0, 0)
        self.main_splitter.setStretchFactor(1, 1)
        self.main_splitter.setSizes([305, 680])
        outer.addWidget(self.main_splitter, 1)
        self._create_map_advanced_dialog()

    def _create_map_advanced_dialog(self) -> None:
        self.map_advanced_dialog = QDialog(self)
        self.map_advanced_dialog.setWindowTitle("高级地图数据")
        self.map_advanced_dialog.setModal(True)
        self.map_advanced_dialog.resize(650, 520)
        root = QVBoxLayout(self.map_advanced_dialog)

        data_group = QGroupBox("地图尺寸与场景数据")
        data_form = QFormLayout(data_group)
        width_row = QHBoxLayout()
        width_row.addWidget(self.width_editor)
        width_row.addWidget(QLabel("×"))
        width_row.addWidget(self.height_editor)
        width_row.addWidget(self.resize_button)
        data_form.addRow("宽 × 高", width_row)
        data_form.addRow("场景前导", self.prelude)
        root.addWidget(data_group)

        display_group = QGroupBox("预览与兼容工具")
        display_layout = QVBoxLayout(display_group)
        preview_controls = QHBoxLayout()
        preview_controls.addWidget(self.fit_view)
        preview_controls.addWidget(QLabel("缩放"))
        preview_controls.addWidget(self.zoom)
        preview_controls.addWidget(self.show_all_objects)
        preview_controls.addStretch()
        display_layout.addLayout(preview_controls)
        display_layout.addWidget(self.show_ids)
        display_layout.addWidget(self.tileset_meta)
        display_layout.addWidget(self.brush_hint)
        root.addWidget(display_group)

        notice = QLabel("缩放、容量和应用按钮位于地图主界面。调整尺寸后会检查部署坐标；超出边界不会直接写入ROM。")
        notice.setWordWrap(True)
        root.addWidget(notice)
        root.addStretch()

        buttons = QHBoxLayout()
        buttons.addStretch()
        close_buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        close_buttons.button(QDialogButtonBox.StandardButton.Close).setText("关闭")
        close_buttons.rejected.connect(self.map_advanced_dialog.close)
        buttons.addWidget(close_buttons)
        root.addLayout(buttons)

    def _show_map_advanced(self) -> None:
        self.map_advanced_dialog.show()
        self.map_advanced_dialog.raise_()
        self.map_advanced_dialog.activateWindow()

    def _open_capacity_planner(self) -> None:
        self.navigation_requested.emit("resources")
        # The shell opens a modal planner and intentionally preserves this
        # page's draft.  Its capacities may have changed while it was open.
        self._commit_error = None
        self._update_size_label()

    def _selected_deployment(self) -> tuple[str, int] | None:
        selected = self.canvas.selected_overlay
        if selected is None or selected[0] not in ("敌", "客", "我"):
            return None
        side, row = selected
        if not 0 <= row < self._object_table(side).rowCount():
            return None
        return side, row

    def _sync_deployment_action_buttons(self) -> None:
        visible = self.editor_tabs.currentIndex() == 1
        enabled = (
            visible
            and self.project is not None
            and self._deployment_write_verified
            and self.current_map_id is not None
            and self.current_map_id < self.project.scenario_count
        )
        selected = self._selected_deployment()
        for button in (
            self.edit_deployment_button,
            self.add_deployment_button,
            self.copy_deployment_button,
        ):
            button.setVisible(visible)
        self.add_deployment_button.setEnabled(enabled)
        self.edit_deployment_button.setEnabled(enabled and selected is not None)
        self.copy_deployment_button.setEnabled(enabled and selected is not None)
        self._update_deployment_selection_preview(visible, selected)

    def _update_deployment_selection_preview(
        self,
        visible: bool | None = None,
        selected: tuple[str, int] | None = None,
    ) -> None:
        """Keep a persistent compact preview for the map's selected deployment."""

        if visible is None:
            visible = self.editor_tabs.currentIndex() == 1
        self.deployment_selection_preview.setVisible(visible)
        if not visible:
            return
        if selected is None:
            selected = self._selected_deployment()
        if selected is None:
            self.deployment_selection_preview.setText(
                "配置预览：左键选择地图上的已配置单位"
            )
            self.deployment_selection_preview.setToolTip(
                "左键选择单位后显示配置摘要；双击或点击“编辑”可修改。"
            )
            return

        side, row = selected
        values = self._object_table(side).rows()[row]
        x, y = values[:2]
        side_name = {"敌": "敌军", "客": "客军", "我": "我方出击位"}[side]
        header = f"配置预览｜{side_name} {row + 1:02d}｜坐标 ({x:02d},{y:02d})"
        action_id = values[3] if side == "我" else values[5]
        action = self._action_choice_label(action_id).split(" · ")[0]
        if side == "我":
            roster_index = values[2]
            player = self._player_slot_state().get(roster_index)
            if player is None:
                details = (
                    f"等级：队伍槽 ${roster_index:02X}（当前关卡无机体）｜"
                    "行动：玩家自控"
                )
            else:
                pilot_id, unit_id = player
                details = (
                    f"驾驶员 {self._character_choice_label(pilot_id).split(' · ')[0]}｜"
                    f"机体 {self._unit_choice_label(unit_id).split(' · ')[0]}｜"
                    f"等级：队伍槽 ${roster_index:02X}｜行动：玩家自控"
                )
        else:
            pilot_id, unit_id, level = values[2:5]
            details = (
                f"驾驶员 {self._character_choice_label(pilot_id).split(' · ')[0]}｜"
                f"机体 {self._unit_choice_label(unit_id).split(' · ')[0]}｜"
                f"等级 {level}｜行动 {action}"
            )
        self.deployment_selection_preview.setText(f"{header}\n{details}")
        self.deployment_selection_preview.setToolTip(
            self._deployment_description(side, values)
            + "\n\n双击单位或点击“编辑”可修改；左键拖动可调整坐标。"
        )

    def _edit_selected_deployment(self) -> None:
        selected = self._selected_deployment()
        if selected is not None:
            self._open_deployment_record(*selected)

    def _add_deployment_from_toolbar(self) -> None:
        selected = self._selected_deployment()
        side = selected[0] if selected is not None else "敌"
        if self.hovered_cell is not None:
            x, y = self.hovered_cell
        elif selected is not None:
            x, y = self._object_table(side).rows()[selected[1]][:2]
        else:
            x, y = (0, 0)
        self._open_deployment_cell_editor(side, x, y)

    def _duplicate_selected_deployment(self) -> None:
        selected = self._selected_deployment()
        if selected is None:
            return
        side, row = selected
        table = self._object_table(side)
        table.setCurrentCell(row, 0)
        before = table.rowCount()
        self._duplicate_deployment(table)
        if table.rowCount() > before:
            self._open_deployment_record(side, row + 1)

    def _build_deployment_cell_dialog(self) -> None:
        """Build the compact reference-style editor used from the map menu."""

        self.deployment_cell_dialog = QDialog(self)
        self.deployment_cell_dialog.setWindowTitle("配置设置")
        self.deployment_cell_dialog.setModal(False)
        self.deployment_cell_dialog.setMinimumWidth(430)
        root = QVBoxLayout(self.deployment_cell_dialog)
        root.setContentsMargins(10, 10, 10, 10)
        root.setSpacing(8)

        self.deployment_side_combo = QComboBox()
        for side, label in (("我", "我方配置"), ("敌", "敌方配置"), ("客", "客军配置")):
            self.deployment_side_combo.addItem(label, side)
        self.deployment_x_editor = QSpinBox()
        self.deployment_y_editor = QSpinBox()
        for editor in (self.deployment_x_editor, self.deployment_y_editor):
            editor.setRange(0, 255)
        self.deployment_character_combo = QComboBox()
        self.deployment_unit_combo = QComboBox()
        self.deployment_level_editor = QComboBox()
        self.deployment_level_editor.setMaxVisibleItems(24)
        self._deployment_level_cap = 99
        for level in range(1, self._deployment_level_cap + 1):
            self.deployment_level_editor.addItem(f"等级：{level:02d}", level)
        self.deployment_action_combo = QComboBox()
        self.deployment_action_combo.setMaxVisibleItems(24)
        for action_id, label in enumerate(ACTION_NAMES):
            self.deployment_action_combo.addItem(
                f"{action_id:03d}: {label}", action_id
            )
        self.deployment_roster_combo = QComboBox()
        self.deployment_roster_combo.setMaxVisibleItems(24)

        # The reference editor keeps this window deliberately dense: type on
        # top, then pilot/unit and level/action in two columns.  Limiting the
        # combo size hint prevents a long database label from widening the
        # complete dialog after the first open.
        for combo in (
            self.deployment_side_combo,
            self.deployment_character_combo,
            self.deployment_unit_combo,
            self.deployment_level_editor,
            self.deployment_action_combo,
            self.deployment_roster_combo,
        ):
            combo.setSizeAdjustPolicy(
                QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon
            )
            combo.setMinimumContentsLength(14)

        type_group = QGroupBox("选择类型")
        type_layout = QHBoxLayout(type_group)
        type_layout.setContentsMargins(10, 14, 10, 8)
        type_layout.addWidget(QLabel("类型："))
        type_layout.addWidget(self.deployment_side_combo, 1)
        root.addWidget(type_group)

        self.deployment_details_group = QGroupBox("配置信息")
        details = QGridLayout(self.deployment_details_group)
        details.setContentsMargins(10, 14, 10, 8)
        details.setHorizontalSpacing(10)
        details.setVerticalSpacing(5)
        details.addWidget(QLabel("机师："), 0, 0)
        details.addWidget(QLabel("机体："), 0, 1)
        details.addWidget(self.deployment_character_combo, 1, 0)
        details.addWidget(self.deployment_unit_combo, 1, 1)
        details.addWidget(QLabel("等级："), 2, 0)
        details.addWidget(QLabel("行动："), 2, 1)
        details.addWidget(self.deployment_level_editor, 3, 0)
        details.addWidget(self.deployment_action_combo, 3, 1)
        details.setColumnStretch(0, 1)
        details.setColumnStretch(1, 1)
        root.addWidget(self.deployment_details_group)

        self.deployment_player_group = QGroupBox("我方机组编号")
        player_layout = QHBoxLayout(self.deployment_player_group)
        player_layout.setContentsMargins(10, 14, 10, 8)
        player_layout.addWidget(self.deployment_roster_combo, 1)
        root.addWidget(self.deployment_player_group)

        self.deployment_editor_status = QLabel()
        self.deployment_editor_status.setObjectName("hintText")
        self.deployment_editor_status.setWordWrap(True)
        self.deployment_editor_status.hide()
        root.addWidget(self.deployment_editor_status)
        self.deployment_capacity_button = QPushButton("容量不足时打开容量规划…")
        self.deployment_capacity_button.clicked.connect(self._open_capacity_planner)
        self.deployment_capacity_button.hide()
        root.addWidget(
            self.deployment_capacity_button,
            0,
            Qt.AlignmentFlag.AlignRight,
        )
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Save
            | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.button(QDialogButtonBox.StandardButton.Save).setText("确定")
        buttons.button(QDialogButtonBox.StandardButton.Cancel).setText("取消")
        buttons.accepted.connect(self._save_deployment_cell_editor)
        buttons.rejected.connect(self.deployment_cell_dialog.reject)
        root.addWidget(buttons)
        self.deployment_cell_buttons = buttons
        self.deployment_side_combo.currentIndexChanged.connect(
            self._deployment_editor_side_changed
        )

    def _refresh_deployment_editor_choices(self) -> None:
        level_cap = 99
        if self.project is not None:
            level_cap = self.project.get_verified_level_cap()
        if level_cap != self._deployment_level_cap:
            selected_level = self.deployment_level_editor.currentData()
            self.deployment_level_editor.blockSignals(True)
            self.deployment_level_editor.clear()
            for level in range(1, level_cap + 1):
                self.deployment_level_editor.addItem(f"等级：{level:02d}", level)
            target_level = min(
                level_cap,
                max(1, int(selected_level) if selected_level is not None else 1),
            )
            self.deployment_level_editor.setCurrentIndex(
                self.deployment_level_editor.findData(target_level)
            )
            self.deployment_level_editor.blockSignals(False)
            self._deployment_level_cap = level_cap

        # The reference deployment editor maps combo index 0 to ROM id 1 for
        # both fields.  Id 0 is a sentinel in generic character/unit helpers,
        # not a valid enemy/guest deployment choice.
        for combo, labeler in (
            (
                self.deployment_character_combo,
                self._deployment_character_choice_label,
            ),
            (self.deployment_unit_combo, self._deployment_unit_choice_label),
        ):
            selected = combo.currentData()
            combo.blockSignals(True)
            combo.clear()
            for record_id in range(1, 256):
                combo.addItem(labeler(record_id), record_id)
            combo.setCurrentIndex(combo.findData(selected if selected is not None else 1))
            combo.blockSignals(False)

        selected_slot = self.deployment_roster_combo.currentData()
        self.deployment_roster_combo.clear()
        for slot in range(256):
            self.deployment_roster_combo.addItem(
                self._deployment_player_slot_choice_label(slot), slot
            )
        self.deployment_roster_combo.setCurrentIndex(
            self.deployment_roster_combo.findData(
                selected_slot if selected_slot is not None else 0
            )
        )

    def _deployment_editor_side_changed(self) -> None:
        player = self.deployment_side_combo.currentData() == "我"
        for widget in (
            self.deployment_character_combo,
            self.deployment_unit_combo,
            self.deployment_level_editor,
        ):
            widget.setEnabled(self._deployment_write_verified and not player)
        self.deployment_roster_combo.setEnabled(
            self._deployment_write_verified and player
        )
        self.deployment_details_group.setEnabled(
            self._deployment_write_verified and not player
        )
        self.deployment_player_group.setEnabled(
            self._deployment_write_verified and player
        )
        if not self._deployment_write_verified:
            self.deployment_editor_status.setText(
                "当前仅供核对；逐字段黄金对照完成前不能修改或写回部署记录。"
            )
            self.deployment_editor_status.show()
        else:
            self.deployment_side_combo.setToolTip(
                "我方记录保存队伍槽和行动；驾驶员、机体由当前关卡的队伍状态自动解析。"
                if player
                else "敌军/客军记录保存驾驶员、机体、等级和行动；全部选项按原始字节写回。"
            )
            self.deployment_editor_status.clear()
            self.deployment_editor_status.hide()
            self.deployment_capacity_button.hide()
        self.deployment_editor_status.setStyleSheet("")

    def _open_deployment_cell_editor(
        self,
        side: str,
        x: int,
        y: int,
        row: int | None = None,
    ) -> None:
        self._refresh_deployment_editor_choices()
        self.deployment_editor_status.clear()
        self.deployment_editor_status.hide()
        self.deployment_capacity_button.hide()
        self._deployment_edit_source = None if row is None else (side, row)
        values = None
        if row is not None:
            table = self._object_table(side)
            if not 0 <= row < table.rowCount():
                return
            values = table.rows()[row]
        self.deployment_side_combo.setCurrentIndex(
            self.deployment_side_combo.findData(side)
        )
        self.deployment_x_editor.setValue(x)
        self.deployment_y_editor.setValue(y)
        if side == "我":
            roster_index, action_id = (values[2], values[3]) if values else (0, 0)
            self.deployment_roster_combo.setCurrentIndex(
                self.deployment_roster_combo.findData(roster_index)
            )
            player = self._player_slot_state().get(roster_index)
            if player is not None:
                self.deployment_character_combo.setCurrentIndex(
                    self.deployment_character_combo.findData(player[0])
                )
                self.deployment_unit_combo.setCurrentIndex(
                    self.deployment_unit_combo.findData(player[1])
                )
        else:
            pilot_id, unit_id, level, action_id = (
                values[2], values[3], values[4], values[5]
            ) if values else (1, 1, 1, 0)
            self.deployment_character_combo.setCurrentIndex(
                self.deployment_character_combo.findData(pilot_id)
            )
            self.deployment_unit_combo.setCurrentIndex(
                self.deployment_unit_combo.findData(unit_id)
            )
            self.deployment_level_editor.setCurrentIndex(
                self.deployment_level_editor.findData(level)
            )
        self.deployment_action_combo.setCurrentIndex(
            self.deployment_action_combo.findData(action_id)
        )
        self._deployment_editor_side_changed()
        if side != "我" and (
            self.deployment_character_combo.currentData() is None
            or self.deployment_unit_combo.currentData() is None
        ):
            invalid_fields = []
            if self.deployment_character_combo.currentData() is None:
                invalid_fields.append(f"机师编号 {pilot_id:02X}")
            if self.deployment_unit_combo.currentData() is None:
                invalid_fields.append(f"机体编号 {unit_id:02X}")
            self.deployment_editor_status.setText(
                f"当前记录的{'、'.join(invalid_fields)}不是有效部署编号；"
                "请选择 01—FF 后再确定。"
            )
            self.deployment_editor_status.show()
        self.deployment_cell_dialog.adjustSize()
        self.deployment_cell_dialog.show()
        self.deployment_cell_dialog.raise_()
        self.deployment_cell_dialog.activateWindow()

    def _deployment_editor_values(self, side: str) -> tuple[int, ...]:
        x = self.deployment_x_editor.value()
        y = self.deployment_y_editor.value()
        action_id = int(self.deployment_action_combo.currentData())
        if side == "我":
            return (
                x,
                y,
                int(self.deployment_roster_combo.currentData()),
                action_id,
            )
        return (
            x,
            y,
            int(self.deployment_character_combo.currentData()),
            int(self.deployment_unit_combo.currentData()),
            int(self.deployment_level_editor.currentData()),
            action_id,
        )

    def _save_deployment_cell_editor(self) -> None:
        if not self._deployment_write_verified:
            return
        side = str(self.deployment_side_combo.currentData())
        if side != "我" and (
            self.deployment_character_combo.currentData() is None
            or self.deployment_unit_combo.currentData() is None
        ):
            self.deployment_editor_status.setText(
                "机师和机体必须选择有效的 01—FF 编号。"
            )
            self.deployment_editor_status.show()
            return
        target = self._object_table(side)
        values = self._deployment_editor_values(side)
        source = self._deployment_edit_source
        conflict = self._deployment_coordinate_conflict(
            values[0], values[1], exclude=source
        )
        if conflict is not None:
            message = self._deployment_coordinate_conflict_message(
                values[0], values[1], conflict
            )
            self.deployment_editor_status.setText(message)
            self.deployment_editor_status.setStyleSheet(
                "color:#b42318; font-weight:600;"
            )
            self.deployment_editor_status.show()
            self.deployment_cell_dialog.adjustSize()
            return
        if source is None:
            if not self._ensure_deployment_growth(len(values)):
                return
            if not target.add_row(values):
                self.show_error(ValueError(f"此阵营最多允许 {target.max_rows} 个部署记录。"))
                return
            row = target.rowCount() - 1
        elif source[0] == side:
            row = source[1]
            target.set_row_values(row, values)
        else:
            delta = len(values) - len(self._object_table(source[0]).rows()[source[1]])
            if not self._ensure_deployment_growth(delta):
                return
            if not target.add_row(values):
                self.show_error(ValueError(f"此阵营最多允许 {target.max_rows} 个部署记录。"))
                return
            row = target.rowCount() - 1
            source_table = self._object_table(source[0])
            source_table.remove_row(source[1])
        self._deployment_edit_source = (side, row)
        self._select_object(side, row)
        self.deployment_cell_dialog.accept()

    def _ensure_deployment_growth(self, extra_bytes: int) -> bool:
        """Keep the shared deployment pool from ending with an unsavable draft."""

        if (
            extra_bytes <= 0
            or self.project is None
            or self.current_map_id is None
            or self.current_map_id >= self.project.scenario_count
        ):
            return True
        plan = self.project.expansion_plan
        if plan is not None and plan.flags & FLAG_MAPS:
            return True
        layout = self._staged_layout()
        codec = self.project.scenario_layout_codec
        encoded = codec.encode(layout)
        used = codec.storage_used_after_payload(
            self.project.working,
            self.current_map_id,
            encoded + bytes(extra_bytes),
        )
        capacity = codec.pool_capacity
        if used <= capacity:
            return True
        message = (
            f"32 关初始配置自动重排后需要 {used} 字节，"
            f"共享池只有 {capacity} 字节。请先打开“容量规划”并应用地图扩展容量，"
            "再保存这条配置。"
        )
        self.deployment_editor_status.setText(message)
        self.deployment_editor_status.setStyleSheet("color:#b42318; font-weight:600;")
        self.deployment_editor_status.show()
        self.deployment_capacity_button.show()
        self.deployment_cell_dialog.adjustSize()
        self.show_error(ValueError(message))
        return False

    def _trigger_kind_changed(self, _checked: bool = False) -> None:
        is_shop = self.trigger_shop_radio.isChecked()
        self.trigger_shop_combo.setEnabled(self._trigger_write_verified and is_shop)
        self.trigger_event_combo.setEnabled(
            self._trigger_write_verified and not is_shop
        )
        self.trigger_kind_hint.setText(
            "符合上方人物条件的我方单位走到这个格子时，打开所选商店。"
            if is_shop
            else "符合上方人物条件的我方单位走到这个格子时，执行所选地图事件。"
        )

    def _refresh_trigger_character_choices(self) -> None:
        selected = self.trigger_character_combo.currentData()
        self.trigger_character_combo.blockSignals(True)
        self.trigger_character_combo.clear()
        # “不限人物”是地图事件最常用的限定条件，固定放在下拉框首项，
        # 避免每次都要滚动到 256 项列表末尾选择 $FF。
        for character_id in (0xFF, *range(0xFF)):
            self.trigger_character_combo.addItem(
                self._trigger_character_label(character_id), character_id
            )
        target = 0xFF if selected is None else int(selected)
        self.trigger_character_combo.setCurrentIndex(
            self.trigger_character_combo.findData(target)
        )
        self.trigger_character_combo.blockSignals(False)

    def _open_trigger_cell_editor(
        self,
        x: int,
        y: int,
        row: int | None = None,
        *,
        shop: bool = False,
    ) -> None:
        if not self.trigger_table.isEnabled():
            self.show_error(ValueError("当前地图没有可写的事件记录区。"))
            return
        self._trigger_edit_row = row
        self.trigger_x_editor.setMaximum(max(0, self.staged_width - 1))
        self.trigger_y_editor.setMaximum(max(0, self.staged_height - 1))
        if row is not None and 0 <= row < self.trigger_table.rowCount():
            x, y, character_id, event_id = self.trigger_table.rows()[row]
            shop = event_id >= 0xF0
        else:
            character_id = 0xFF
            event_id = 0xF0 if shop else 0
        self.trigger_x_editor.setValue(x)
        self.trigger_y_editor.setValue(y)
        self.trigger_character_combo.setCurrentIndex(
            self.trigger_character_combo.findData(character_id)
        )
        self.trigger_shop_radio.setChecked(shop)
        self.trigger_event_radio.setChecked(not shop)
        selector = self.trigger_shop_combo if shop else self.trigger_event_combo
        selector_index = selector.findData(event_id)
        if selector_index < 0:
            self.show_error(
                ValueError(
                    f"商店编号 ${event_id:02X} 不是有效商店；ROM 仅定义了 $F0—$F4。"
                )
            )
            return
        selector.setCurrentIndex(selector_index)
        self.trigger_delete_button.setVisible(row is not None)
        self.trigger_delete_button.setText(
            "删除商店入口" if shop else "删除地图事件"
        )
        self.trigger_cell_dialog.setWindowTitle(
            "设置商店入口" if shop else "设置地图事件"
        )
        self._trigger_kind_changed()
        self.trigger_cell_dialog.show()
        self.trigger_cell_dialog.raise_()
        self.trigger_cell_dialog.activateWindow()

    def _save_trigger_cell_editor(self) -> None:
        if not self._trigger_write_verified:
            return
        event_data = (
            self.trigger_shop_combo.currentData()
            if self.trigger_shop_radio.isChecked()
            else self.trigger_event_combo.currentData()
        )
        if event_data is None:
            self.show_error(ValueError("请先选择有效的商店或地图事件。"))
            return
        event_id = int(event_data)
        values = (
            self.trigger_x_editor.value(),
            self.trigger_y_editor.value(),
            int(self.trigger_character_combo.currentData()),
            event_id,
        )
        row = self._trigger_edit_row
        if row is None:
            row = self.trigger_table.rowCount()
            if not self.trigger_table.add_row(values):
                self.show_error(ValueError("地图事件记录已达到当前容量上限。"))
                return
        else:
            self.trigger_table.set_row_values(row, values)
        self._trigger_edit_row = row
        self._select_object("店" if event_id >= 0xF0 else "事", row)
        self.trigger_cell_dialog.accept()

    def _remove_trigger_row(self, row: int) -> None:
        if not self._trigger_write_verified:
            return
        if not 0 <= row < self.trigger_table.rowCount():
            return
        self.trigger_table.remove_row(row)
        self.canvas.selected_overlay = None

    def _delete_edited_trigger(self) -> None:
        if self._trigger_edit_row is not None:
            self._remove_trigger_row(self._trigger_edit_row)
        self._trigger_edit_row = None
        self.trigger_cell_dialog.accept()

    def _show_trigger_context_menu(
        self, x: int, y: int, global_position: QPoint
    ) -> None:
        if (
            self.editor_tabs.currentIndex() != 2
            or not self._trigger_write_verified
            or not self.trigger_table.isEnabled()
        ):
            return
        rows = [
            row
            for row, values in enumerate(self.trigger_table.rows())
            if values[:2] == (x, y)
        ]
        menu = QMenu(self.canvas)
        self._trigger_context_menu = menu
        if len(rows) == 1:
            row = rows[0]
            event_id = self.trigger_table.rows()[row][3]
            edit = menu.addAction(
                "编辑商店入口" if event_id >= 0xF0 else "编辑地图事件"
            )
            edit.triggered.connect(
                lambda _checked=False, row=row: self._open_trigger_cell_editor(x, y, row)
            )
        elif rows:
            edit_menu = menu.addMenu("编辑此格记录")
            for row in rows:
                event_id = self.trigger_table.rows()[row][3]
                action = edit_menu.addAction(
                    f"第 {row + 1} 条 · {self._trigger_event_label(event_id)}"
                )
                action.triggered.connect(
                    lambda _checked=False, row=row: self._open_trigger_cell_editor(x, y, row)
                )
        add = menu.addAction("添加地图事件")
        add.triggered.connect(
            lambda _checked=False: self._open_trigger_cell_editor(x, y)
        )
        add_shop = menu.addAction("添加商店入口")
        add_shop.triggered.connect(
            lambda _checked=False: self._open_trigger_cell_editor(x, y, shop=True)
        )
        if len(rows) == 1:
            row = rows[0]
            event_id = self.trigger_table.rows()[row][3]
            delete = menu.addAction(
                "删除商店入口" if event_id >= 0xF0 else "删除地图事件"
            )
            delete.triggered.connect(
                lambda _checked=False, row=row: self._remove_trigger_row(row)
            )
        elif rows:
            delete_menu = menu.addMenu("删除地图事件")
            for row in reversed(rows):
                event_id = self.trigger_table.rows()[row][3]
                action = delete_menu.addAction(
                    f"第 {row + 1} 条 · {self._trigger_event_label(event_id)}"
                )
                action.triggered.connect(
                    lambda _checked=False, row=row: self._remove_trigger_row(row)
                )
        else:
            delete = menu.addAction("删除地图事件")
            delete.setEnabled(False)
        menu.popup(global_position)

    def _show_trigger_list_context_menu(self, position: QPoint) -> None:
        """Edit or delete the event/shop row right-clicked in the side list."""

        if (
            self.editor_tabs.currentIndex() != 2
            or not self._trigger_write_verified
            or not self.trigger_table.isEnabled()
        ):
            return
        item = self.trigger_objects.itemAt(position)
        if item is None:
            return
        side, row = item.data(Qt.ItemDataRole.UserRole)
        row = int(row)
        if side not in ("事", "店") or not 0 <= row < self.trigger_table.rowCount():
            return
        self.trigger_objects.setCurrentItem(item)
        self._select_object(side, row)
        x, y, _character_id, event_id = self.trigger_table.rows()[row]
        shop = event_id >= 0xF0
        menu = QMenu(self.trigger_objects)
        self._trigger_list_context_menu = menu
        edit = menu.addAction("编辑商店入口" if shop else "编辑地图事件")
        edit.triggered.connect(
            lambda _checked=False, x=x, y=y, row=row: self._open_trigger_cell_editor(
                x, y, row
            )
        )
        delete = menu.addAction("删除商店入口" if shop else "删除地图事件")
        delete.triggered.connect(
            lambda _checked=False, row=row: self._remove_trigger_row(row)
        )
        menu.popup(self.trigger_objects.viewport().mapToGlobal(position))

    def _open_deployment_record(self, side: str, row: int) -> None:
        """Open the exact initial-configuration row chosen on the map."""

        table = self._object_table(side)
        if not 0 <= row < table.rowCount():
            return
        self._select_object(side, row)
        values = table.rows()[row]
        self._open_deployment_cell_editor(side, values[0], values[1], row)

    def _add_deployment_at(self, side: str, x: int, y: int) -> None:
        self._open_deployment_cell_editor(side, x, y)

    def _copy_deployment_record(self, side: str, row: int, *, cut: bool = False) -> None:
        table = self._object_table(side)
        if not 0 <= row < table.rowCount():
            return
        self._deployment_clipboard = (side, table.rows()[row])
        if cut:
            self._remove_deployment_row(side, row)

    def _paste_deployment_at(self, x: int, y: int) -> None:
        if self._deployment_clipboard is None:
            return
        conflict = self._deployment_coordinate_conflict(x, y)
        if conflict is not None:
            self.show_error(
                ValueError(self._deployment_coordinate_conflict_message(x, y, conflict))
            )
            return
        side, source = self._deployment_clipboard
        values = (x, y, *source[2:])
        table = self._object_table(side)
        if not self._ensure_deployment_growth(len(values)):
            return
        if not table.add_row(values):
            self.show_error(ValueError(f"此阵营最多允许 {table.max_rows} 个部署记录。"))
            return
        self._select_object(side, table.rowCount() - 1)

    def _open_deployment_attributes(self, side: str, row: int) -> None:
        identity = self._deployment_record_identity(side, row)
        if identity is None:
            return
        pilot_id, unit_id, level = identity
        self.attribute_calculator_requested.emit(pilot_id, unit_id, level)

    def _deployment_record_identity(
        self, side: str, row: int
    ) -> tuple[int, int, int] | None:
        table = self._object_table(side)
        if not 0 <= row < table.rowCount():
            return None
        values = table.rows()[row]
        if side == "我":
            roster_index = values[2]
            player = self._player_slot_state().get(roster_index)
            if player is None:
                self.show_error(ValueError("当前队伍槽没有可解析的驾驶员和机体。"))
                return None
            pilot_id, unit_id = player
            level = 1
        else:
            pilot_id, unit_id, level = values[2:5]
        return pilot_id, unit_id, level

    def _open_deployment_database_record(self, side: str, row: int) -> None:
        identity = self._deployment_record_identity(side, row)
        if identity is not None:
            self.database_record_requested.emit("units", identity[1])

    def _open_deployment_experience(self, side: str, row: int) -> None:
        identity = self._deployment_record_identity(side, row)
        if identity is not None:
            _pilot_id, unit_id, level = identity
            self.defeat_experience_requested.emit(unit_id, level)

    def _remove_deployment_row(self, side: str, row: int) -> None:
        if not self._deployment_write_verified:
            return
        table = self._object_table(side)
        if not 0 <= row < table.rowCount():
            return
        table.remove_row(row)
        self.canvas.selected_overlay = None

    def _show_deployment_context_menu(
        self, x: int, y: int, global_position: QPoint
    ) -> None:
        """Legacy-style map context menu for initial configurations."""

        if self.editor_tabs.currentIndex() != 1:
            return
        if not self._deployment_write_verified:
            return
        if not all(
            table.isEnabled()
            for table in (self.enemy_table, self.guest_table, self.player_table)
        ):
            return
        records = [
            (side, row, values)
            for side, table in (
                ("敌", self.enemy_table),
                ("客", self.guest_table),
                ("我", self.player_table),
            )
            for row, values in enumerate(table.rows())
            if values[:2] == (x, y)
        ]
        menu = QMenu(self.canvas)
        self._deployment_context_menu = menu

        # Match the reference editor's one-step flow: “添加配置” opens the
        # common editor immediately and the type is chosen inside that dialog.
        # The previous side submenu made the same operation take an extra
        # pointer movement and duplicated the dialog's type selector.
        default_side = records[0][0] if len(records) == 1 else "敌"
        add = menu.addAction("添加配置")
        add.setEnabled(
            not records
            and
            any(
                table.max_rows is None or table.rowCount() < table.max_rows
                for table in (self.enemy_table, self.guest_table, self.player_table)
            )
        )
        add.triggered.connect(
            lambda _checked=False, side=default_side: self._add_deployment_at(
                side, x, y
            )
        )

        if len(records) == 1:
            side, row, _values = records[0]
            edit = menu.addAction("更改配置")
            edit.triggered.connect(
                lambda _checked=False, side=side, row=row:
                self._open_deployment_record(side, row)
            )
        elif records:
            edit_menu = menu.addMenu("更改配置")
            for side, row, _values in records:
                action = edit_menu.addAction(
                    self.canvas.overlay_descriptions.get(
                        (side, row), f"{side}军第 {row + 1} 条"
                    )
                )
                action.triggered.connect(
                    lambda _checked=False, side=side, row=row:
                    self._open_deployment_record(side, row)
                )
        else:
            edit = menu.addAction("更改配置")
            edit.setEnabled(False)
        if len(records) == 1:
            side, row, _values = records[0]
            database = menu.addAction("更改属性")
            database.triggered.connect(
                lambda _checked=False, side=side, row=row:
                self._open_deployment_database_record(side, row)
            )
            experience = menu.addAction("击杀经验计算器")
            experience.triggered.connect(
                lambda _checked=False, side=side, row=row:
                self._open_deployment_experience(side, row)
            )
            attributes = menu.addAction("加到属性计算器")
            attributes.triggered.connect(
                lambda _checked=False, side=side, row=row:
                self._open_deployment_attributes(side, row)
            )
            copy = menu.addAction("复制")
            copy.triggered.connect(
                lambda _checked=False, side=side, row=row:
                self._copy_deployment_record(side, row)
            )
            cut = menu.addAction("剪切")
            cut.triggered.connect(
                lambda _checked=False, side=side, row=row:
                self._copy_deployment_record(side, row, cut=True)
            )
        else:
            database = menu.addAction("更改属性")
            database.setEnabled(False)
            experience = menu.addAction("击杀经验计算器")
            experience.setEnabled(False)
            attributes = menu.addAction("加到属性计算器")
            attributes.setEnabled(False)
            copy = menu.addAction("复制")
            copy.setEnabled(False)
            cut = menu.addAction("剪切")
            cut.setEnabled(False)
        paste = menu.addAction("粘贴")
        # Empty ground only accepts a new record or a previously copied/cut
        # record.  Record-specific operations still require an exact hit.
        paste.setEnabled(self._deployment_clipboard is not None and not records)
        paste.triggered.connect(
            lambda _checked=False: self._paste_deployment_at(x, y)
        )

        if len(records) == 1:
            side, row, _values = records[0]
            delete = menu.addAction("删除配置")
            delete.triggered.connect(
                lambda _checked=False, side=side, row=row:
                self._remove_deployment_row(side, row)
            )
        elif records:
            delete_menu = menu.addMenu("删除配置")
            for side, row, _values in reversed(records):
                action = delete_menu.addAction(
                    self.canvas.overlay_descriptions.get(
                        (side, row), f"{side}军第 {row + 1} 条"
                    )
                )
                action.triggered.connect(
                    lambda _checked=False, side=side, row=row:
                    self._remove_deployment_row(side, row)
                )
        else:
            delete = menu.addAction("删除配置")
            delete.setEnabled(False)
        menu.popup(global_position)

    def _deployment_group(
        self,
        layout: QVBoxLayout,
        title: str,
        headers: tuple[str, ...],
        label_providers=None,
        *,
        max_rows: int | None = None,
        default_values: tuple[int, ...] | None = None,
    ) -> ByteEntryTable:
        group = QGroupBox(title)
        group_layout = QVBoxLayout(group)
        table = ByteEntryTable(headers, label_providers, max_rows=max_rows)
        table.setMinimumHeight(230)
        table.values_changed.connect(self._update_overlays)
        buttons = QGridLayout()
        add_button = QPushButton("添加")
        add_button.clicked.connect(
            lambda: self._add_deployment(table, default_values)
        )
        duplicate_button = QPushButton("复制一份")
        duplicate_button.clicked.connect(lambda: self._duplicate_deployment(table))
        copy_button = QPushButton("复制")
        copy_button.clicked.connect(table.copy_selected)
        paste_button = QPushButton("粘贴")
        paste_button.clicked.connect(lambda: self._paste_deployment(table))
        remove_button = QPushButton("删除选中")
        remove_button.clicked.connect(table.remove_selected)
        up_button = QPushButton("上移")
        up_button.clicked.connect(lambda: table.move_selected(-1))
        down_button = QPushButton("下移")
        down_button.clicked.connect(lambda: table.move_selected(1))
        cursor_button = QPushButton("移到地图光标")
        cursor_button.clicked.connect(lambda: self._move_selected_to_hover(table))
        for index, button in enumerate(
            (
                add_button,
                duplicate_button,
                remove_button,
                copy_button,
                paste_button,
                cursor_button,
                up_button,
                down_button,
            )
        ):
            buttons.addWidget(button, index // 3, index % 3)
        table.editing_buttons = (
            add_button, duplicate_button, paste_button, remove_button,
            cursor_button, up_button, down_button,
        )
        group_layout.addWidget(table)
        group_layout.addLayout(buttons)
        layout.addWidget(group, 1)
        return table

    def _duplicate_deployment(self, table: ByteEntryTable) -> None:
        if table.currentRow() < 0:
            self.show_error(ValueError("请先选择要复制的记录。"))
        elif table.max_rows is not None and table.rowCount() >= table.max_rows:
            self.show_error(ValueError(f"此列表最多允许 {table.max_rows} 条记录。"))
        elif not self._ensure_deployment_growth(table.columnCount()):
            return
        else:
            row = table.currentRow()
            source = table.rows()[row]
            coordinate = self._nearest_free_deployment_coordinate(*source[:2])
            if coordinate is None:
                self.show_error(ValueError("当前地图没有可用于复制配置的空格。"))
                return
            values = (*coordinate, *source[2:])
            if not table.add_row(values, row=row + 1):
                self.show_error(ValueError(f"此列表最多允许 {table.max_rows} 条记录。"))

    def _paste_deployment(self, table: ByteEntryTable) -> None:
        if table.clipboard_row is None:
            self.show_error(ValueError("请先在此列表复制一条记录。"))
        elif table.max_rows is not None and table.rowCount() >= table.max_rows:
            self.show_error(ValueError(f"此列表最多允许 {table.max_rows} 条记录。"))
        elif not self._ensure_deployment_growth(table.columnCount()):
            return
        else:
            assert table.clipboard_row is not None
            coordinate = self._nearest_free_deployment_coordinate(
                *table.clipboard_row[:2]
            )
            if coordinate is None:
                self.show_error(ValueError("当前地图没有可用于粘贴配置的空格。"))
                return
            row = table.currentRow()
            values = (*coordinate, *table.clipboard_row[2:])
            if not table.add_row(
                values, row=table.rowCount() if row < 0 else row + 1
            ):
                self.show_error(ValueError(f"此列表最多允许 {table.max_rows} 条记录。"))

    @staticmethod
    def _deployment_side_name(side: str) -> str:
        return {"敌": "敌军", "客": "客军", "我": "我方出击位"}[side]

    def _deployment_side_for_table(self, table: ByteEntryTable) -> str:
        for side, candidate in (
            ("敌", self.enemy_table),
            ("客", self.guest_table),
            ("我", self.player_table),
        ):
            if table is candidate:
                return side
        raise ValueError("该列表不是初始配置部署表。")

    def _deployment_coordinate_conflict(
        self,
        x: int,
        y: int,
        *,
        exclude: tuple[str, int] | None = None,
    ) -> tuple[str, int] | None:
        """Return the first deployment already occupying one map cell."""

        for side, table in (
            ("敌", self.enemy_table),
            ("客", self.guest_table),
            ("我", self.player_table),
        ):
            for row, values in enumerate(table.rows()):
                if exclude == (side, row):
                    continue
                if values[:2] == (x, y):
                    return side, row
        return None

    def _deployment_coordinate_conflict_message(
        self, x: int, y: int, conflict: tuple[str, int]
    ) -> str:
        side, row = conflict
        return (
            f"坐标 ({x:02d},{y:02d}) 已被"
            f"{self._deployment_side_name(side)}配置 {row + 1:02d} 占用；"
            "同一格不能放置多个配置，请改用空格。"
        )

    def _validate_deployment_coordinate_uniqueness(self) -> None:
        seen: dict[tuple[int, int], tuple[str, int]] = {}
        for side, table in (
            ("敌", self.enemy_table),
            ("客", self.guest_table),
            ("我", self.player_table),
        ):
            for row, values in enumerate(table.rows()):
                coordinate = values[:2]
                conflict = seen.get(coordinate)
                if conflict is not None:
                    raise ValueError(
                        self._deployment_coordinate_conflict_message(
                            coordinate[0], coordinate[1], conflict
                        )
                    )
                seen[coordinate] = (side, row)

    def _nearest_free_deployment_coordinate(
        self, x: int, y: int
    ) -> tuple[int, int] | None:
        """Find the closest free cell for duplicate/paste convenience actions."""

        if self._deployment_coordinate_conflict(x, y) is None:
            return x, y
        max_distance = self.staged_width + self.staged_height
        for distance in range(1, max_distance + 1):
            candidates: list[tuple[int, int]] = []
            for delta_y in range(-distance, distance + 1):
                delta_x = distance - abs(delta_y)
                for candidate_x in (x + delta_x, x - delta_x):
                    candidate = (candidate_x, y + delta_y)
                    if candidate not in candidates:
                        candidates.append(candidate)
            for candidate_x, candidate_y in candidates:
                if not (
                    0 <= candidate_x < self.staged_width
                    and 0 <= candidate_y < self.staged_height
                ):
                    continue
                if self._deployment_coordinate_conflict(
                    candidate_x, candidate_y
                ) is None:
                    return candidate_x, candidate_y
        return None

    def _object_table(self, side: str) -> ByteEntryTable:
        return {"敌": self.enemy_table, "客": self.guest_table,
                "我": self.player_table, "事": self.trigger_table,
                "店": self.trigger_table}[side]

    def _object_list_selected(self, item: QListWidgetItem | None, _previous=None) -> None:
        if item is not None and not self._selecting_object:
            self._select_object(*item.data(Qt.ItemDataRole.UserRole))

    def _object_list_activated(self, item: QListWidgetItem) -> None:
        self._activate_object(*item.data(Qt.ItemDataRole.UserRole))

    def _table_selection_changed(self, side: str, row: int) -> None:
        if self._loading_map or self._selecting_object or row < 0:
            return
        table = self._object_table(side)
        if side == "事" and row < table.rowCount():
            side = "店" if table.rows()[row][3] >= 0xF0 else "事"
        self._select_object(side, row)

    def _select_object(self, side: str, row: int) -> None:
        table = self._object_table(side)
        if self._selecting_object or not 0 <= row < table.rowCount():
            return
        self._selecting_object = True
        try:
            table.setCurrentCell(row, 0)
            table.scrollTo(table.model().index(row, 0))
            object_list = self.trigger_objects if side in ("事", "店") else self.deployment_objects
            for index in range(object_list.count()):
                item = object_list.item(index)
                if tuple(item.data(Qt.ItemDataRole.UserRole)) == (side, row):
                    object_list.setCurrentItem(item)
                    object_list.scrollToItem(item)
                    break
            self.canvas.selected_overlay = (side, row)
            x, y = table.rows()[row][:2]
            self.map_scroll.ensureVisible(
                x * self.canvas.cell_size + self.canvas.cell_size // 2,
                y * self.canvas.cell_size + self.canvas.cell_size // 2,
                self.canvas.cell_size, self.canvas.cell_size,
            )
            self.canvas.update()
        finally:
            self._selecting_object = False
        self._sync_deployment_action_buttons()

    def _activate_object(self, side: str, row: int) -> None:
        if side in ("事", "店"):
            self.editor_tabs.setCurrentIndex(2)
            values = self.trigger_table.rows()[row]
            self._open_trigger_cell_editor(values[0], values[1], row)
        else:
            self.editor_tabs.setCurrentIndex(1)
            values = self._object_table(side).rows()[row]
            self._open_deployment_cell_editor(side, values[0], values[1], row)
        self._select_object(side, row)

    def _player_slot_state(self) -> dict[int, tuple[int, int]]:
        """Resolve the player party at the selected chapter's entrance.

        The old editor does not simulate the runtime party.  It starts with the
        six editable initial members and accumulates only $6F “join member”
        records from the three banked chapter-event partitions.  Those records
        expose slot, pilot and machine to this configuration view.  Leave and
        transfer opcodes are deliberately ignored: legacy probes show that the
        configuration combo keeps joined members after those runtime events.
        Shared physical instructions are applied once at their earliest
        chapter/phase, and the selected chapter sees the preceding snapshots.
        """

        if self.project is None or self.current_map_id is None:
            return {}
        roster = tuple(self.project.get_initial_roster())
        source = self.project.working
        pointer_start = min(LegacyScenarioCodec.POINTER_TABLES)
        pointer_end = max(LegacyScenarioCodec.POINTER_TABLES) + 64
        event_signature = (
            bytes(source[pointer_start:pointer_end]),
            *(
                bytes(
                    source[
                        LegacyScenarioCodec._bank_offset(bank):
                        LegacyScenarioCodec._bank_offset(bank, end)
                    ]
                )
                for bank, end in sorted(LegacyScenarioCodec.BANK_ENDS.items())
            ),
        )
        cache_key = (id(self.project), roster, event_signature)
        if cache_key != self._player_slot_cache_key:
            slots = {
                index: pair
                for index, pair in enumerate(roster[:6])
                if pair != (0, 0)
            }
            scheduled: dict[int, list] = {
                scenario_id: []
                for scenario_id in range(self.project.scenario_count)
            }
            codec = LegacyScenarioCodec(source)
            physical_instructions = {}
            for scenario_id in range(self.project.scenario_count):
                for phase in range(3):
                    for instruction in codec.instructions(scenario_id, phase):
                        physical_instructions.setdefault(
                            instruction.file_offset,
                            instruction,
                        )
            for instruction in physical_instructions.values():
                scheduled[instruction.scenario_id].append(
                    (instruction.phase, instruction.file_offset, instruction)
                )

            snapshots: list[dict[int, tuple[int, int]]] = []
            for scenario_id in range(self.project.scenario_count):
                snapshots.append(dict(slots))
                for _phase, _address, instruction in sorted(scheduled[scenario_id]):
                    parameters = instruction.raw[1:]
                    if instruction.opcode == 0x6F and len(parameters) >= 3:
                        slot, character_id, unit_id = parameters[:3]
                        if 0 <= slot < 11:
                            slots[slot] = (character_id, unit_id)
            self._player_slot_cache_key = cache_key
            self._player_slot_snapshots = tuple(snapshots)
        if 0 <= self.current_map_id < len(self._player_slot_snapshots):
            return self._player_slot_snapshots[self.current_map_id]
        return {}

    def _refresh_object_lists(self) -> None:
        descriptions: dict[tuple[str, int], str] = {}
        selected = self.canvas.selected_overlay
        player_slots = self._player_slot_state()
        for object_list in (self.deployment_objects, self.trigger_objects):
            object_list.blockSignals(True)
            object_list.clear()
        for side, table in (("敌", self.enemy_table), ("客", self.guest_table),
                            ("我", self.player_table), ("事", self.trigger_table)):
            for row, values in enumerate(table.rows()):
                x, y = values[:2]
                kind = "店" if side == "事" and values[3] >= 0xF0 else side
                if side in ("敌", "客"):
                    pilot = self._character_choice_label(values[2]).split(" · ")[0]
                    name = self._unit_choice_label(values[3]).split(" · ")[0]
                    text = (
                        f"{kind}{row + 1:02d}  ({x:02d},{y:02d})  "
                        f"{name} / {pilot}  Lv.{values[4]} · "
                        f"{ACTION_NAMES[values[5]]}"
                    )
                elif side == "我":
                    roster_index = values[2]
                    if roster_index in player_slots:
                        character_id, unit_id = player_slots[roster_index]
                        text = (
                            f"我{row + 1:02d}  ({x:02d},{y:02d})  "
                            f"{self._unit_choice_label(unit_id).split(' · ')[0]} / "
                            f"{self._character_choice_label(character_id).split(' · ')[0]}"
                        )
                    else:
                        text = (
                            f"我{row + 1:02d}  ({x:02d},{y:02d})  "
                            f"空队伍槽 ${roster_index:02X}（当前ROM无机体）"
                        )
                else:
                    text = (f"{kind}{row + 1:02d}  ({x:02d},{y:02d})  "
                            f"{self._trigger_event_label(values[3])} / {self._trigger_character_label(values[2])}")
                description = (
                    self._deployment_description(side, values)
                    if side in ("敌", "客", "我")
                    else text
                )
                descriptions[(kind, row)] = description
                item = QListWidgetItem(text)
                if side == "事":
                    item_font = item.font()
                    item_font.setBold(True)
                    item.setFont(item_font)
                    if kind == "店":
                        item.setForeground(QColor("#145c3a"))
                    else:
                        item.setForeground(QColor("#5930a8"))
                item.setToolTip(
                    description
                    + (
                        "\n单击联动定位；双击可查看原始记录。"
                        if (
                            side in ("敌", "客", "我")
                            and not self._deployment_write_verified
                        ) or (side == "事" and not self._trigger_write_verified)
                        else "\n单击联动定位；双击，或在列表/地图上右键打开编辑；图标可拖动。"
                    )
                )
                item.setData(Qt.ItemDataRole.UserRole, (kind, row))
                object_list = self.trigger_objects if side == "事" else self.deployment_objects
                object_list.addItem(item)
                if selected == (kind, row):
                    object_list.setCurrentItem(item)
        for object_list in (self.deployment_objects, self.trigger_objects):
            object_list.blockSignals(False)
        self.canvas.overlay_descriptions = descriptions
        if selected not in descriptions:
            self.canvas.selected_overlay = None
        deployment_count = sum(
            table.rowCount()
            for table in (self.enemy_table, self.guest_table, self.player_table)
        )
        if (
            self.project is not None
            and self.current_map_id is not None
            and self.current_map_id >= self.project.scenario_count
        ):
            self.deployment_summary.setText(
                f"地图 ${self.current_map_id:02X} 不属于ROM中的 "
                f"{self.project.scenario_count} 个关卡初始配置表，没有独立部署记录。"
            )
        elif deployment_count == 0:
            self.deployment_summary.setText(
                "本关初始配置表为空；出场单位由关卡事件生成，不在这里伪造部署。"
            )
        else:
            self.deployment_summary.setText(
                f"敌军 {self.enemy_table.rowCount()}/18 · 客军 {self.guest_table.rowCount()}/3 · "
                f"我方出击位 {self.player_table.rowCount()}/11\n"
                "地图显示ROM四图块机体图标；"
                + (
                    "右键可编辑、新增或删除，左键拖动可改坐标。"
                    if self._deployment_write_verified
                    else "部署记录只读；单击可定位，双击可查看原码。"
                )
            )
        count = self.trigger_table.rowCount()
        shop_count = sum(
            values[3] >= 0xF0 for values in self.trigger_table.rows()
        )
        event_count = count - shop_count
        self.trigger_summary.setText(
            (
                f"本关有 {event_count} 个地图事件、{shop_count} 个商店入口。"
                "地图上的白底红字“事”是地图事件，白底红字“商”是商店入口；"
                + (
                    "在地图上右键可添加；在地图或左侧列表右键可编辑、删除。"
                    if self._trigger_write_verified
                    else "记录只读；选择条目可定位。"
                )
            ) if count else (
                "本关ROM中没有地图事件或商店记录。"
                + (
                    "在右侧地图任意格右键即可添加。"
                    if self._trigger_write_verified
                    else "空表不代表读取失败；当前仅可查看。"
                )
            )
        )
        self._sync_deployment_action_buttons()

    def _add_deployment(
        self,
        table: ByteEntryTable,
        default_values: tuple[int, ...] | None = None,
    ) -> None:
        if not self._deployment_write_verified:
            return
        values = list(default_values or (0 for _ in table.headers))
        if len(values) != len(table.headers):
            raise ValueError("新增记录的默认字节数与表列数不一致。")
        if self.hovered_cell is not None:
            values[0], values[1] = self.hovered_cell
        conflict = self._deployment_coordinate_conflict(values[0], values[1])
        if conflict is not None:
            self.show_error(
                ValueError(
                    self._deployment_coordinate_conflict_message(
                        values[0], values[1], conflict
                    )
                )
            )
            return
        if not self._ensure_deployment_growth(len(values)):
            return
        if not table.add_row(tuple(values)):
            self.show_error(
                ValueError(f"此阵营最多允许 {table.max_rows} 个部署记录。")
            )

    def _move_selected_to_hover(self, table: ByteEntryTable) -> None:
        if self.hovered_cell is None:
            self.show_error(ValueError("请先把鼠标移动到地图中的目标格。"))
            return
        row = table.currentRow()
        if row < 0:
            self.show_error(ValueError("请先选择一条部署记录。"))
            return
        if any(
            table is candidate
            for candidate in (self.enemy_table, self.guest_table, self.player_table)
        ):
            side = self._deployment_side_for_table(table)
            conflict = self._deployment_coordinate_conflict(
                *self.hovered_cell, exclude=(side, row)
            )
            if conflict is not None:
                self.show_error(
                    ValueError(
                        self._deployment_coordinate_conflict_message(
                            *self.hovered_cell, conflict
                        )
                    )
                )
                return
        table.set_row_coordinates(row, *self.hovered_cell)

    def _canvas_coordinate_changed(self, x: int, y: int) -> None:
        self.hovered_cell = (x, y)
        self.position_label.setText(f"X坐标：{x}")
        self.y_position_label.setText(f"Y坐标：{y}")

    def _overlay_moved(self, side: str, row: int, x: int, y: int) -> None:
        if side in ("敌", "客", "我") and not self._deployment_write_verified:
            return
        if side in ("事", "店") and not self._trigger_write_verified:
            return
        if side in ("敌", "客", "我"):
            conflict = self._deployment_coordinate_conflict(
                x, y, exclude=(side, row)
            )
            if conflict is not None:
                self.show_error(
                    ValueError(
                        self._deployment_coordinate_conflict_message(x, y, conflict)
                    )
                )
                self._update_overlays()
                return
        table = {
            "敌": self.enemy_table,
            "客": self.guest_table,
            "我": self.player_table,
            "事": self.trigger_table,
            "店": self.trigger_table,
        }[side]
        table.set_row_coordinates(row, x, y)

    def _unit_choice_label(self, unit_id: int) -> str:
        cached = self._unit_choice_cache.get(unit_id)
        if cached is not None:
            return cached
        if unit_id == 0:
            label = "无机体/特殊值"
        elif self.project is not None and unit_id < self.project.unit_count:
            label = self.project.unit_display_name(unit_id)
        else:
            label = "超出已验证机体表"
        result = f"{label} · ${unit_id:02X}"
        self._unit_choice_cache[unit_id] = result
        return result

    def _deployment_unit_choice_label(self, unit_id: int) -> str:
        """Format one unit exactly like the reference configuration combo."""

        name = self._unit_choice_label(unit_id).split(" · ")[0]
        return f"[{unit_id:02X}]{unit_id:03d}: {name}"

    @staticmethod
    def _action_choice_label(action_id: int) -> str:
        return f"{ACTION_NAMES[action_id]} · ${action_id:02X}"

    def _player_slot_choice_label(self, roster_index: int) -> str:
        player = self._player_slot_state().get(roster_index)
        if player is None:
            return f"空队伍槽 · ${roster_index:02X}"
        character_id, unit_id = player
        return (
            f"{self._character_choice_label(character_id).split(' · ')[0]} / "
            f"{self._unit_choice_label(unit_id).split(' · ')[0]} · ${roster_index:02X}"
        )

    def _deployment_player_slot_choice_label(self, roster_index: int) -> str:
        """Use the compact reference wording inside “配置设置”."""

        player = self._player_slot_state().get(roster_index)
        if player is None:
            # The reference combo leaves unused rows empty after the colon.
            # Keep the explanatory “空队伍槽” wording in tooltips/previews,
            # but do not add it to this 1:1 dropdown surface.
            return f"编号{roster_index:02X}:"
        character_id, unit_id = player
        character = self._character_choice_label(character_id).split(" · ")[0]
        unit = self._unit_choice_label(unit_id).split(" · ")[0]
        return f"编号{roster_index:02X}: {character}  {unit}"

    def _character_choice_label(self, character_id: int) -> str:
        cached = self._character_choice_cache.get(character_id)
        if cached is not None:
            return cached
        label = (
            self.project.character_display_name(character_id)
            if self.project is not None
            else "尚未载入 ROM"
        )
        result = f"{label} · ${character_id:02X}"
        self._character_choice_cache[character_id] = result
        return result

    def _deployment_character_choice_label(self, character_id: int) -> str:
        """Format one pilot exactly like the reference configuration combo."""

        name = self._character_choice_label(character_id).split(" · ")[0]
        return f"[{character_id:02X}]{character_id:03d}: {name}"

    def _trigger_character_label(self, character_id: int) -> str:
        if character_id == 0xFF:
            return "任意我方人物"
        if self.project is not None and character_id < self.project.profile.character_name_count:
            return f"仅限 {self.project.character_display_name(character_id)}"
        return f"未知人物（编号 ${character_id:02X}）"

    def _deployment_description(self, side: str, values: tuple[int, ...]) -> str:
        """Return a reference-style, ROM-backed battlefield tooltip."""

        if self.project is None:
            return "尚未载入ROM"
        cache_key = (self.current_map_id or 0, side, values)
        cached = self._deployment_description_cache.get(cache_key)
        if cached is not None:
            return cached
        action = (
            "玩家自控"
            if side == "我"
            else self._action_choice_label(values[5])
        )
        if side == "我":
            roster_index = values[2]
            player = self._player_slot_state().get(roster_index)
            if player is None:
                result = (
                    f"我方出击位 ${roster_index:02X}\n"
                    "当前关卡队伍状态中没有驾驶员或机体\n"
                    f"行动：{action}"
                )
                self._deployment_description_cache[cache_key] = result
                return result
            pilot_id, unit_id = player
            level = None
            level_text = "等级：由运行时队伍状态决定"
        else:
            pilot_id, unit_id, level = values[2:5]
            level_text = f"等级：{level}"
        pilot = self._character_choice_label(pilot_id)
        unit = self._unit_choice_label(unit_id)
        lines = [f"驾驶员：{pilot}"]
        corrections = (0, 0, 0, 0, 0)
        if 0 <= pilot_id < self.project.profile.character_name_count:
            try:
                corrections = CharacterAttributesCodec(self.project).read(
                    pilot_id
                ).corrections
            except (IndexError, ValueError):
                pass
        lines.append(
            "人物补正 机/强/防/速/HP："
            + "/".join(str(value) for value in corrections)
        )
        lines.extend((f"机体：{unit}", level_text))
        if 0 <= unit_id < self.project.unit_count:
            stat_values = {
                key: self.project.get_value(unit_id, key)
                for key in ("hp", "strength", "defense", "speed", "movement")
            }
            lines.append(
                "机体基础属性："
                f"HP {stat_values['hp']} · 强度 {stat_values['strength']} · "
                f"防御 {stat_values['defense']} · 速度 {stat_values['speed']} · "
                f"移动 {stat_values['movement']}"
            )
            if level is not None:
                if self._growth_codec_cache is None:
                    self._growth_codec_cache = LegacyGrowthCodec(
                        self.project.working
                    )
                growth_codec = self._growth_codec_cache

                def growth_delta(field: str) -> int:
                    growth = self.project.get_value(unit_id, f"{field}_growth")
                    count = max(0, min(98, level - 1))
                    if growth <= 200:
                        return growth * count
                    if 201 <= growth <= 253:
                        return sum(growth_codec.record(growth).values[:count])
                    return 0

                final_values = {
                    "movement": stat_values["movement"] + corrections[0],
                    "strength": stat_values["strength"]
                    + growth_delta("strength") + corrections[1],
                    "defense": stat_values["defense"]
                    + growth_delta("defense") + corrections[2],
                    "speed": stat_values["speed"]
                    + growth_delta("speed") + corrections[3],
                    "hp": stat_values["hp"]
                    + growth_delta("hp") + corrections[4],
                }
                lines.append(
                    f"Lv.{level} 游戏成长属性：HP {final_values['hp']} · "
                    f"强度 {final_values['strength']} · 防御 {final_values['defense']} · "
                    f"速度 {final_values['speed']} · 移动 {final_values['movement']}"
                )
            try:
                weapon_ids = self.project.get_unit_weapons(unit_id)
            except ValueError:
                weapon_ids = ()
            for slot in (1, 2):
                weapon_id = weapon_ids[slot - 1] if slot <= len(weapon_ids) else 0
                if weapon_id == 0:
                    lines.append(f"武器{slot}：无")
                    continue
                if not 0 < weapon_id < self.project.weapon_count:
                    lines.append(f"武器{slot}：无效编号 ${weapon_id:02X}")
                    continue
                weapon = self.project.weapon_codec.decode_record(
                    weapon_id, self.project.working
                )
                weapon_skill, distance = weapon_extra_values(
                    self.project, weapon_id
                )
                weapon_description = self._weapon_description_cache.get(weapon_id)
                if weapon_description is None:
                    weapon_description = (
                        f"{self.project.weapon_display_name(weapon_id)} · ${weapon_id:02X} "
                        f"射程 {weapon.get('max_range')} · 命中 {weapon.get('hit')} · "
                        f"特技 {weapon_skill} · 距离补正表 {distance} · "
                        f"火力 空/陆/海 {weapon.get('power_air')}/"
                        f"{weapon.get('power_land')}/{weapon.get('power_sea')}"
                    )
                    self._weapon_description_cache[weapon_id] = weapon_description
                lines.append(
                    f"武器{slot}：{weapon_description}"
                )
        lines.append(f"行动：{action}")
        result = "\n".join(lines)
        self._deployment_description_cache[cache_key] = result
        return result

    @staticmethod
    def _trigger_event_label(event_id: int) -> str:
        if 0xF5 <= event_id <= 0xFE:
            return f"不可使用的商店编号（${event_id:02X}）"
        if event_id >= 0xF0:
            return f"商店 {event_id - 0xF0 + 1}"
        return f"地图事件 {event_id + 1}"

    def refresh(self) -> None:
        previous = self.current_map_id
        self._icon_sheet_cache.clear()
        self._map_icon_cache.clear()
        self._tileset_image_cache.clear()
        self._unit_choice_cache.clear()
        self._character_choice_cache.clear()
        self._deployment_description_cache.clear()
        self._weapon_description_cache.clear()
        self._growth_codec_cache = None
        self._trigger_payload_cache = None
        self._chapter_title_cache.clear()
        self._refresh_trigger_character_choices()
        for table in (self.enemy_table, self.guest_table, self.player_table, self.trigger_table):
            table.invalidate_choice_models()
        self._refresh_icon_sheets()
        self.map_list.blockSignals(True)
        self.map_list.clear()
        if self.project is not None:
            for map_id in range(self.project.map_count):
                record = self.project.get_map(map_id)
                item = QListWidgetItem(
                    f"{map_id + 1:03d}：{dc_map_label(map_id)}"
                )
                item.setData(Qt.ItemDataRole.UserRole, map_id)
                item.setToolTip(
                    f"地图ID ${map_id:02X} · {record.width}×{record.height}"
                )
                self.map_list.addItem(item)
        self.map_list.blockSignals(False)
        if self.map_list.count():
            row = min(previous or 0, self.map_list.count() - 1)
            self.map_list.blockSignals(True)
            self.map_list.setCurrentRow(row)
            self.map_list.blockSignals(False)
            self._map_selected(self.map_list.currentItem(), None)

    def _map_selected(self, item: QListWidgetItem | None, _previous: QListWidgetItem | None) -> None:
        if self.project is None or item is None:
            self.current_map_id = None
            self._loaded_draft_signature = None
            return
        next_map_id = int(item.data(Qt.ItemDataRole.UserRole))
        committed_previous = False
        previous_map_id = self.current_map_id
        if (
            previous_map_id is not None
            and next_map_id != previous_map_id
            and self.has_pending_draft
        ):
            if not self._commit_pending_changes(emit_signal=False):
                error = self.pending_draft_error or "当前地图草稿无法提交。"
                self.map_list.blockSignals(True)
                for row in range(self.map_list.count()):
                    if int(
                        self.map_list.item(row).data(Qt.ItemDataRole.UserRole)
                    ) == previous_map_id:
                        self.map_list.setCurrentRow(row)
                        break
                self.map_list.blockSignals(False)
                self.show_error(ValueError(error))
                return
            committed_previous = True
        self.current_map_id = next_map_id
        self._loading_map = True
        try:
            self._load_map_record()
        finally:
            self._loading_map = False
        self.canvas.selected_overlay = None
        self._loaded_draft_signature = self._draft_signature()
        self._update_overlays()
        self._commit_error = None
        if committed_previous:
            self.project_changed.emit(
                f"已更新地图 ${previous_map_id:02X}、部署与事件"
            )

    def _load_map_record(self) -> None:
        assert self.project is not None and self.current_map_id is not None
        record = self.project.get_map(self.current_map_id)
        self.title_preview.setText("")
        title_key = (id(self.project), self.project.revision, self.current_map_id)
        title = self._chapter_title_cache.get(title_key)
        if title is None:
            # The map page keeps the compact in-panel preview used by the old
            # editor; the standalone scenario dialog uses the larger default.
            title = render_chapter_title(
                self.project, self.current_map_id, scale=2
            )
            self._chapter_title_cache[title_key] = title
        self.title_preview.setPixmap(title)
        self.staged_width = record.width
        self.staged_height = record.height
        self.staged_tiles = list(record.tiles)
        suggested_tileset = campaign_tileset_key(self.current_map_id) or "A"
        self.tileset.blockSignals(True)
        self.tileset.setCurrentIndex(self.tileset.findData(suggested_tileset))
        self.tileset.blockSignals(False)
        self._refresh_tile_visuals()
        self.width_editor.setValue(record.width)
        self.height_editor.setValue(record.height)
        self.width_display.setValue(record.width)
        self.height_display.setValue(record.height)
        if self.current_map_id < len(SCENARIO_MAP_ICON_BANKS):
            for selector, bank in zip(
                self.icon_bank_selectors,
                scenario_map_icon_banks(self.current_map_id),
                strict=True,
            ):
                selector.blockSignals(True)
                selector.setCurrentIndex(selector.findData(bank))
                selector.blockSignals(False)
        self._refresh_icon_sheets()
        if self.current_map_id < self.project.scenario_count:
            layout = self.project.get_scenario_layout(self.current_map_id)
            self.prelude.setEnabled(True)
            self.prelude.setText(bytes(layout.prelude).hex(" ").upper())
            # Player-slot labels are chapter-dependent; only this small shared
            # model needs rebuilding when the selected chapter changes.
            self.player_table.refresh_choice_labels(2)
            self.enemy_table.set_rows([tuple(entry.to_bytes()) for entry in layout.enemies])
            self.guest_table.set_rows([tuple(entry.to_bytes()) for entry in layout.guests])
            self.player_table.set_rows([tuple(entry.to_bytes()) for entry in layout.player_placements])
            for table in (self.enemy_table, self.guest_table, self.player_table):
                table.setEnabled(True)
        else:
            self.prelude.clear()
            self.prelude.setEnabled(False)
            for table in (self.enemy_table, self.guest_table, self.player_table):
                table.set_rows([])
                table.setEnabled(False)
        if (
            self.project.map_trigger_codec is not None
            and self.current_map_id < self.project.map_trigger_codec.spec.scenario_count
        ):
            self.trigger_table.set_rows(
                [tuple(entry.to_bytes()) for entry in self.project.get_map_triggers(self.current_map_id)]
            )
            self.trigger_table.setEnabled(True)
        else:
            self.trigger_table.set_rows([])
            self.trigger_table.setEnabled(False)
        self._sync_record_write_state()

    def _sync_record_write_state(self) -> None:
        """Apply D3 to the visible editor while preserving record inspection."""

        deployment_enabled = (
            self.project is not None and self._deployment_write_verified
        )
        trigger_enabled = self.project is not None and self._trigger_write_verified
        for table in (self.enemy_table, self.guest_table, self.player_table):
            table.set_editing_enabled(deployment_enabled and table.isEnabled())
        self.trigger_table.set_editing_enabled(
            trigger_enabled and self.trigger_table.isEnabled()
        )
        self.prelude.setEnabled(
            deployment_enabled
            and self.current_map_id is not None
            and self.current_map_id < self.project.scenario_count
        )
        self.deployment_cell_buttons.button(
            QDialogButtonBox.StandardButton.Save
        ).setEnabled(deployment_enabled)
        self.trigger_cell_buttons.button(
            QDialogButtonBox.StandardButton.Ok
        ).setEnabled(trigger_enabled)
        self.trigger_delete_button.setEnabled(trigger_enabled)
        for widget in (
            self.deployment_side_combo, self.deployment_x_editor,
            self.deployment_y_editor, self.deployment_action_combo,
        ):
            widget.setEnabled(deployment_enabled)
        self._deployment_editor_side_changed()
        self._sync_deployment_action_buttons()
        for widget in (
            self.trigger_x_editor, self.trigger_y_editor,
            self.trigger_character_combo, self.trigger_shop_radio,
            self.trigger_event_radio,
        ):
            widget.setEnabled(trigger_enabled)
        self._trigger_kind_changed()
    def _bitmap_selector_changed(self, _index: int) -> None:
        key = self.bitmap_selector.currentData()
        target = self.tileset.findData(key)
        if target >= 0 and target != self.tileset.currentIndex():
            self.tileset.setCurrentIndex(target)

    def _terrain_selected(self) -> None:
        if self.terrain.currentData() is None:
            return
        self.canvas.selected_tile = int(self.terrain.currentData())
        button = self.terrain_buttons.button(self.canvas.selected_tile)
        if button is not None:
            button.setChecked(True)
        self._update_brush_previews()

    def _right_terrain_selected(self) -> None:
        if self.right_terrain.currentData() is None:
            return
        self.canvas.right_selected_tile = int(self.right_terrain.currentData())
        self._update_brush_previews()

    def _select_right_brush(self, tile: int) -> None:
        self.right_terrain.setCurrentIndex(self.right_terrain.findData(tile))

    def _tile_attribute_tooltip(self, key: str, tile: int) -> str:
        if (
            self.project is None
            or not self.project.supports_map_tile_attributes
            or key not in MapTileAttributeCodec.KEYS
        ):
            return f"位图{tile:X}\n图库 {key} 的图块属性尚未完成验证，仅提供图形预览。"
        value = self.project.get_map_tileset_attributes(key).tiles[tile]
        return (
            f"位图{tile:X} · 图库 {key}\n"
            f"颜色表：{value.palette}    防御补正：{value.defense}\n"
            f"海属性：{'是' if value.sea else '否'}\n"
            f"空中通行：{'可以' if value.air_move else '不能'}    "
            f"移动补正：陆 {value.land_move} / 海 {value.sea_move}"
        )

    def _update_brush_previews(self) -> None:
        images = self.canvas.tile_images
        key = str(self.tileset.currentData() or "—")
        for label, tile in (
            (self.left_brush_preview, self.canvas.selected_tile),
            (self.right_brush_preview, self.canvas.right_selected_tile),
        ):
            if 0 <= tile < len(images):
                pixmap = QPixmap.fromImage(images[tile]).scaled(
                    32,
                    32,
                    Qt.AspectRatioMode.KeepAspectRatio,
                    Qt.TransformationMode.FastTransformation,
                )
                label.setPixmap(pixmap)
                label.setToolTip(self._tile_attribute_tooltip(key, tile))
                label.setStyleSheet(
                    "background: #f8fafb; border: 1px solid #7d8790;"
                )
            else:
                label.setPixmap(QPixmap())
                label.setText("暂无图块" if self.project is None else f"位图{tile:X}")

    def _open_tile_attributes(self) -> None:
        key = str(self.tileset.currentData() or "—")
        self._tile_attribute_dialog = TileAttributeDialog(
            self.project,
            key,
            self.canvas.tile_images,
            self,
        )
        self._tile_attribute_dialog.accepted.connect(
            self._tile_attributes_applied
        )
        self._tile_attribute_dialog.show()

    def _tile_attributes_applied(self) -> None:
        self._refresh_tile_visuals()
        self.project_changed.emit("已更新图库 A—H 图块属性")

    def _refresh_icon_sheets(self, _index: int | None = None) -> None:
        if self.project is None:
            for preview in self.icon_sheet_labels:
                preview.setPixmap(QPixmap())
                preview.setText("尚未载入 ROM")
            return
        bank_count = self.project.chr_tile_count // 64
        for selector, preview in zip(
            self.icon_bank_selectors,
            self.icon_sheet_labels,
            strict=True,
        ):
            for bank in range(min(selector.count(), bank_count)):
                offset = self.project.chr_codec.offset + bank * 0x400
                selector.setItemText(bank, f"[{bank:02X}]{bank:03d}: {offset:06X}")
            bank = int(selector.currentData())
            if not 0 <= bank < bank_count:
                preview.setPixmap(QPixmap())
                preview.setText("地址超出活动 CHR")
                continue
            if not self.icon_preview_group.isVisible():
                continue
            strip = self._icon_sheet_cache.get(bank)
            if strip is None:
                strip = render_unit_icon_bank(self.project, bank)
                self._icon_sheet_cache[bank] = strip
            image = QImage(128, 32, QImage.Format.Format_RGB32)
            painter = QPainter(image)
            painter.drawImage(0, 0, strip.copy(0, 0, 128, 16))
            painter.drawImage(0, 16, strip.copy(128, 0, 128, 16))
            painter.end()
            preview.setText("")
            preview.setPixmap(
                QPixmap.fromImage(image).scaled(
                    256,
                    64,
                    Qt.AspectRatioMode.KeepAspectRatio,
                    Qt.TransformationMode.FastTransformation,
                )
            )

    def _editor_mode_changed(self, index: int) -> None:
        if index == 1:
            self._refresh_icon_sheets()
        self._sync_deployment_action_buttons()
        self._update_overlays()

    def _refresh_tile_visuals(self) -> None:
        if self.project is None or self.tileset.currentData() is None:
            self.canvas.set_tile_images(())
            self._update_brush_previews()
            return
        key = str(self.tileset.currentData())
        previous = self.bitmap_selector.blockSignals(True)
        self.bitmap_selector.setCurrentIndex(self.bitmap_selector.findData(key))
        self.bitmap_selector.blockSignals(previous)
        images = self._tileset_image_cache.get(key)
        if images is None:
            images = render_tileset(self.project, key)
            self._tileset_image_cache[key] = images
        self.canvas.set_tile_images(images)
        for tile, image in enumerate(images):
            button = self.terrain_buttons.button(tile)
            if button is not None:
                pixmap = _legacy_dpi_tile_pixmap(
                    image, 32, button.devicePixelRatioF()
                )
                # Draw the DPR-aware pixmap directly.  Passing it through
                # QIcon makes Qt choose and rescale another representation,
                # which discards the reference editor's DPI interpolation.
                button.setIcon(QIcon())
                button.set_tile_pixmap(pixmap)
                button.setToolTip(self._tile_attribute_tooltip(key, tile))
        self._update_brush_previews()
        # Use one information format for the closed combo and every popup row.
        # Previously only the selected item received its real CHR address.
        for index in range(self.tileset.count()):
            item_key = str(self.tileset.itemData(index))
            item_bank = TILESET_BANKS[item_key]
            item_offset = self.project.chr_codec.offset + item_bank * 0x400
            self.tileset.setItemText(
                index,
                f"[{item_bank:02X}]{item_bank:03d}: {item_offset:06X}",
            )
        automatic = (
            self.current_map_id is not None
            and campaign_tileset_key(self.current_map_id) == key
        )
        self.tileset_meta.setText(
            f"{'前32关已核对' if automatic else '手动预览'}：位图{key}，"
            f"活动CHR 1 KiB Bank ${TILESET_BANKS[key]:02X}。"
            "切换这里只改变预览，不会猜写尚未确认的关卡位图绑定。"
        )

    def _show_ids_changed(self, checked: bool) -> None:
        self.canvas.show_tile_ids = checked
        self.canvas.update()

    def _zoom_changed(self, value: int) -> None:
        if not self.fit_view.isChecked():
            self.canvas.set_cell_size(value)

    def _fit_view_changed(self, checked: bool) -> None:
        self.zoom.setEnabled(not checked)
        if checked:
            self._fit_map_to_viewport()
        else:
            self.canvas.set_cell_size(self.zoom.value())

    def _fit_map_to_viewport(self) -> None:
        if not self.fit_view.isChecked():
            return
        viewport = self.map_scroll.viewport()
        available_width = max(1, viewport.width() - 3)
        available_height = max(1, viewport.height() - 3)
        # The reference editor displays one logical 16x16 metatile at roughly
        # 20 physical screen pixels.  Qt sizes are device-independent, so a
        # fixed logical cap of 20 becomes 25 pixels at the user's 125% Windows
        # scale and makes the same palette look much harsher.  Cap the physical
        # size instead; any remaining preview area intentionally stays empty,
        # as it does in the reference editor.
        device_ratio = max(1.0, float(viewport.devicePixelRatioF()))
        reference_cell_limit = max(8, int(20 / device_ratio))
        cell_size = min(
            reference_cell_limit,
            max(
                8,
                min(
                    (available_width - 1) // max(1, self.staged_width),
                    (available_height - 1) // max(1, self.staged_height),
                ),
            ),
        )
        previous = self.zoom.blockSignals(True)
        self.zoom.setValue(cell_size)
        self.zoom.blockSignals(previous)
        self.canvas.set_cell_size(cell_size)

    def _tile_painted(self, _x: int, _y: int, _tile: int) -> None:
        self._update_size_label()

    def _resize_map_from_main(self, _value: int) -> None:
        if self._loading_map or self.project is None or self.current_map_id is None:
            return
        width = self.width_display.value()
        height = self.height_display.value()
        if (width, height) == (self.staged_width, self.staged_height):
            return
        self.width_editor.setValue(width)
        self.height_editor.setValue(height)
        self._resize_map()

    def _resize_map(self) -> None:
        new_width = self.width_editor.value()
        new_height = self.height_editor.value()
        resized = [0] * (new_width * new_height)
        for y in range(min(self.staged_height, new_height)):
            for x in range(min(self.staged_width, new_width)):
                resized[y * new_width + x] = self.staged_tiles[y * self.staged_width + x]
        self.staged_width = new_width
        self.staged_height = new_height
        self.staged_tiles = resized
        previous_width = self.width_display.blockSignals(True)
        previous_height = self.height_display.blockSignals(True)
        self.width_display.setValue(new_width)
        self.height_display.setValue(new_height)
        self.width_display.blockSignals(previous_width)
        self.height_display.blockSignals(previous_height)
        self._update_overlays()
        self._update_size_label()

    def _update_overlays(self) -> None:
        if self._loading_map:
            return
        overlays: list[tuple[str, int, int, str, int]] = []
        overlay_images: dict[tuple[str, int], QImage] = {}
        icon_cache = self._map_icon_cache
        mode = self.editor_tabs.currentIndex()
        show_all = self.show_all_objects.isChecked()
        self.canvas.paint_enabled = mode == 0
        self.canvas.deployment_edit_enabled = (
            mode == 1 and self._deployment_write_verified
        )
        self.canvas.trigger_edit_enabled = (
            mode == 2 and self._trigger_write_verified
        )
        self.canvas.overlay_move_enabled = (
            (mode == 1 and self._deployment_write_verified)
            or (mode == 2 and self._trigger_write_verified)
        )
        icon_banks = (
            scenario_map_icon_banks(self.current_map_id)
            if self.current_map_id is not None
            and self.current_map_id < len(SCENARIO_MAP_ICON_BANKS)
            else None
        )
        if mode == 1 or show_all:
            for side, table in (("敌", self.enemy_table), ("客", self.guest_table)):
                for row, values in enumerate(table.rows()):
                    overlays.append((side, values[0], values[1], str(row + 1), row))
                    if self.project is not None:
                        unit_id = values[3]
                        key = (icon_banks, side, unit_id)
                        if key not in icon_cache and icon_banks is not None:
                            icon_cache[key] = render_unit_map_icon(
                                self.project, unit_id, side, icon_banks
                            )
                        if key in icon_cache:
                            overlay_images[(side, row)] = icon_cache[key]
            player_slots = self._player_slot_state()
            for row, values in enumerate(self.player_table.rows()):
                overlays.append(("我", values[0], values[1], str(row + 1), row))
                roster_index = values[2]
                if roster_index in player_slots:
                    unit_id = player_slots[roster_index][1]
                    key = (icon_banks, "我", unit_id)
                    if key not in icon_cache and icon_banks is not None:
                        icon_cache[key] = render_unit_map_icon(
                            self.project, unit_id, "我", icon_banks
                        )
                    if key in icon_cache:
                        overlay_images[("我", row)] = icon_cache[key]
        if (mode == 2 or show_all) and self.trigger_table.isEnabled():
            for row, values in enumerate(self.trigger_table.rows()):
                side = "店" if values[3] >= 0xF0 else "事"
                overlays.append((side, values[0], values[1], side, row))
        self._refresh_object_lists()
        self.canvas.set_overlay_images(overlay_images)
        self.canvas.set_content(
            self.staged_width,
            self.staged_height,
            self.staged_tiles,
            overlays,
        )
        self._fit_map_to_viewport()
        if hasattr(self, "pending_state"):
            self._update_size_label()

    def _draft_signature(self) -> tuple | None:
        if self.project is None or self.current_map_id is None:
            return None
        return (
            self.current_map_id,
            self.staged_width,
            self.staged_height,
            tuple(self.staged_tiles),
            self.prelude.text(),
            tuple(self.enemy_table.rows()),
            tuple(self.guest_table.rows()),
            tuple(self.player_table.rows()),
            tuple(self.trigger_table.rows()),
        )

    def _trigger_storage_used_after(
        self, entries: tuple[MapTrigger, ...]
    ) -> int:
        """Measure the trigger pool without decoding every chapter repeatedly."""

        assert self.project is not None and self.current_map_id is not None
        codec = self.project.map_trigger_codec
        assert codec is not None
        return codec.storage_used_after(
            None, self.current_map_id, entries
        )

    @property
    def has_pending_draft(self) -> bool:
        """Return whether the map page owns edits not yet in the project buffer."""

        signature = self._draft_signature()
        return signature is not None and signature != self._loaded_draft_signature

    def _validate_pending_draft(self) -> None:
        if self.project is None or self.current_map_id is None:
            return
        if self.current_map_id < self.project.scenario_count:
            self._validate_deployment_coordinate_uniqueness()
            if (
                not self._deployment_write_verified
                and self._staged_layout()
                != self.project.get_scenario_layout(self.current_map_id)
            ):
                raise ValueError("初始配置写入须先完成控件枚举与逐字段黄金对照。")
        if (
            self.project.map_trigger_codec is not None
            and self.current_map_id
            < self.project.map_trigger_codec.spec.scenario_count
            and not self._trigger_write_verified
            and self._staged_triggers()
            != self.project.get_map_triggers(self.current_map_id)
        ):
            raise ValueError("商店事件写入须先完成控件枚举与逐字段黄金对照。")
        encoded = self.project.map_codec.encode(
            self.staged_width,
            self.staged_height,
            tuple(self.staged_tiles),
        )
        plan = self.project.expansion_plan
        expanded = bool(plan is not None and plan.flags & FLAG_MAPS)
        if not expanded:
            self.project.map_resource_replacement_usage(
                self.current_map_id,
                self.staged_width,
                self.staged_height,
                tuple(self.staged_tiles),
            )

        staged_layout = None
        staged_triggers = None
        if self.current_map_id < self.project.scenario_count:
            staged_layout = self._staged_layout()
            self.project.scenario_layout_codec.validate_layout(
                staged_layout,
                self.staged_width,
                self.staged_height,
            )
            scenario_encoded = self.project.scenario_layout_codec.encode(staged_layout)
            if not expanded:
                scenario_used = self.project.scenario_layout_codec.storage_used_after(
                    None,
                    self.current_map_id,
                    staged_layout,
                )
                if scenario_used > self.project.scenario_layout_codec.pool_capacity:
                    raise ValueError("初始配置超出 32 关共享池容量。")

        if (
            self.project.map_trigger_codec is not None
            and self.current_map_id
            < self.project.map_trigger_codec.spec.scenario_count
        ):
            staged_triggers = self._staged_triggers()
            self.project.map_trigger_codec.validate_entries(
                staged_triggers,
                self.staged_width,
                self.staged_height,
            )
            if not expanded:
                trigger_used = self._trigger_storage_used_after(staged_triggers)
                if trigger_used > self.project.map_trigger_codec.pool_capacity:
                    raise ValueError("地图事件与商店数据超出全局池容量。")

        if expanded:
            self.project.map_resource_replacement_usage(
                self.current_map_id,
                self.staged_width,
                self.staged_height,
                tuple(self.staged_tiles),
                staged_layout,
                staged_triggers,
            )

    @property
    def pending_draft_error(self) -> str | None:
        """Return a blocking validation error for the current pending draft."""

        if not self.has_pending_draft:
            return None
        try:
            self._validate_pending_draft()
        except Exception as error:
            return str(error)
        signature = self._draft_signature()
        if self._commit_error is not None and self._commit_error[0] == signature:
            return self._commit_error[1]
        return None

    def _commit_pending_changes(self, *, emit_signal: bool) -> bool:
        if self.project is None or self.current_map_id is None:
            return True
        if not self.has_pending_draft:
            return True
        error = self.pending_draft_error
        if error is not None:
            return False
        signature = self._draft_signature()
        assert signature is not None
        try:
            with self.project.transaction(
                f"地图 ${self.current_map_id:02X} · 地形、部署与事件"
            ):
                self.project.set_map_tiles(
                    self.current_map_id,
                    self.staged_width,
                    self.staged_height,
                    tuple(self.staged_tiles),
                )
                if (
                    self._deployment_write_verified
                    and self.current_map_id < self.project.scenario_count
                ):
                    self.project.set_scenario_layout(self._staged_layout())
                if (
                    self._trigger_write_verified
                    and
                    self.project.map_trigger_codec is not None
                    and self.current_map_id
                    < self.project.map_trigger_codec.spec.scenario_count
                ):
                    self.project.set_map_triggers(
                        self.current_map_id,
                        self._staged_triggers(),
                    )
        except Exception as error:  # project transaction provides atomic rollback
            self._commit_error = (signature, str(error))
            self._update_size_label()
            return False
        self._loaded_draft_signature = self._draft_signature()
        self._commit_error = None
        self._update_size_label()
        if emit_signal:
            self.project_changed.emit(
                f"已更新地图 ${self.current_map_id:02X}、部署与事件"
            )
        return True

    def commit_pending_changes(self) -> bool:
        """Validate and atomically commit the current draft to the ROM project."""

        return self._commit_pending_changes(emit_signal=True)

    def _update_size_label(self) -> None:
        if self._loading_map:
            return
        if self.project is None or self.current_map_id is None:
            self.size_label.setText("—")
            self.pending_state.setText(
                "尚未载入ROM：按 Ctrl+O 或“文件→打开”选择基准ROM。"
                if self.project is None
                else "选择地图后可编辑。"
            )
            self.apply_button.setEnabled(False)
            self.pending_state.setVisible(False)
            self.apply_button.setVisible(False)
            self.capacity_help_button.setEnabled(False)
            self._emit_draft_state_changed()
            return
        try:
            self.capacity_help_button.setEnabled(
                self.project.profile.key == "dc-kuorong-mmc3-v2"
            )
            encoded = self.project.map_codec.encode(
                self.staged_width,
                self.staged_height,
                tuple(self.staged_tiles),
            )
            plan = self.project.expansion_plan
            expanded = bool(plan is not None and plan.flags & FLAG_MAPS)
            used, terrain_capacity = self.project.map_resource_replacement_usage(
                self.current_map_id,
                self.staged_width,
                self.staged_height,
                tuple(self.staged_tiles),
            )
            size_ok = used <= terrain_capacity
            terrain_details = f"地图RLE {len(encoded)} B"
            total_used = total_capacity = 0
            if not expanded:
                total_used, total_capacity = (
                    self.project.legacy_map_terrain_total_usage(
                        self.current_map_id,
                        self.staged_width,
                        self.staged_height,
                        tuple(self.staged_tiles),
                    )
                )
                terrain_details += (
                    f" · 所在Bank {used} / {terrain_capacity} B"
                    " · 共用对象：同一Bank内的地图RLE记录"
                    " · 限制：单图不可跨Bank"
                    f" · 三Bank合计 {total_used} / {total_capacity} B"
                    " · 限制：三个Bank彼此独立，余量不能互相拼接"
                )
            staged_layout = None
            staged_triggers = None
            scenario_bytes = scenario_used = scenario_capacity = scenario_remaining = None
            trigger_bytes = trigger_used = trigger_capacity = None
            scenario_details = None
            trigger_details = None
            current_map = self.project.get_map(self.current_map_id)
            changed = (
                self.staged_width != current_map.width
                or self.staged_height != current_map.height
                or tuple(self.staged_tiles) != current_map.tiles
            )
            if self.current_map_id < self.project.scenario_count:
                self._validate_deployment_coordinate_uniqueness()
                staged_layout = self._staged_layout()
                self.project.scenario_layout_codec.validate_layout(
                    staged_layout, self.staged_width, self.staged_height
                )
                scenario_encoded = self.project.scenario_layout_codec.encode(staged_layout)
                scenario_bytes = len(scenario_encoded)
                if not expanded:
                    scenario_used = (
                        self.project.scenario_layout_codec.storage_used_after(
                            None,
                            self.current_map_id,
                            staged_layout,
                        )
                    )
                    scenario_capacity = self.project.scenario_layout_codec.pool_capacity
                    scenario_remaining = scenario_capacity - scenario_used
                    size_ok = size_ok and scenario_used <= scenario_capacity
                    scenario_details = (
                        f"初始配置本关 {scenario_bytes} B"
                        f" · 32关部署正文 {scenario_used} B"
                        f" · Bank $24 八资源共享剩余 {scenario_remaining} B"
                        " · 共用对象：人物属性、机体属性、武器属性"
                        " · 共用对象：人物普通名称、人物战斗名称"
                        " · 共用对象：机体名称、武器名称、初始配置"
                        f" · 当前部署上限 {scenario_capacity} B（其他七项不变时）"
                    )
                current_layout = self.project.get_scenario_layout(self.current_map_id)
                changed = changed or (
                    scenario_encoded
                    != self.project.scenario_layout_codec.encode(current_layout)
                )
            if (
                self.project.map_trigger_codec is not None
                and self.current_map_id < self.project.map_trigger_codec.spec.scenario_count
            ):
                staged_triggers = self._staged_triggers()
                self.project.map_trigger_codec.validate_entries(
                    staged_triggers, self.staged_width, self.staged_height
                )
                trigger_bytes = len(
                    self.project.map_trigger_codec.encode_entries(staged_triggers)
                )
                if not expanded:
                    trigger_used = self._trigger_storage_used_after(staged_triggers)
                    trigger_capacity = self.project.map_trigger_codec.pool_capacity
                    size_ok = size_ok and trigger_used <= trigger_capacity
                    trigger_details = (
                        f"事件/商店本关 {len(staged_triggers)} 条/{trigger_bytes} B"
                        f" · 32关事件/商店列表共享池 {trigger_used} / {trigger_capacity} B"
                        " · 共用对象：32关地图事件与商店列表"
                        " · 独立于地图RLE和初始配置"
                    )
                changed = changed or (
                    staged_triggers
                    != self.project.get_map_triggers(self.current_map_id)
                )
            if expanded:
                used, shared_capacity = self.project.map_resource_replacement_usage(
                    self.current_map_id,
                    self.staged_width,
                    self.staged_height,
                    tuple(self.staged_tiles),
                    staged_layout,
                    staged_triggers,
                )
                if staged_layout is not None and staged_triggers is not None:
                    (
                        _terrain_used,
                        scenario_used,
                        trigger_used,
                        used,
                        shared_capacity,
                    ) = self.project.map_resource_usage_breakdown(
                        self.current_map_id,
                        self.staged_width,
                        self.staged_height,
                        tuple(self.staged_tiles),
                        staged_layout,
                        staged_triggers,
                    )
                    scenario_details = (
                        f"初始配置本关 {scenario_bytes} B"
                        f" · 32关部署合计 {scenario_used} B"
                        f" · 地图共享池 {used} / {shared_capacity} B"
                        " · 共用对象：地图RLE、初始配置、事件/商店"
                    )
                    trigger_details = (
                        f"事件/商店本关 {len(staged_triggers)} 条/{trigger_bytes} B"
                        f" · 32关触发合计 {trigger_used} B"
                        f" · 地图共享池 {used} / {shared_capacity} B"
                        " · 共用对象：地图RLE、初始配置、事件/商店"
                    )
                size_ok = size_ok and used <= shared_capacity
                terrain_details += f" · 地图共享池 {used} / {shared_capacity} B"
            status = (
                (
                    "可保存（共享池自动重排）"
                    if expanded
                    else "可保存（必要时整图迁移）"
                )
                if size_ok
                else (
                    "共享池无法容纳"
                    if expanded
                    else "三级Bank无法容纳"
                )
            )
            # Keep the permanent line readable at the reference window width.
            # Exact byte accounting remains available on hover and in the
            # capacity planner instead of being visibly clipped.
            mode = self.editor_tabs.currentIndex()
            if mode == 1:
                if scenario_bytes is None:
                    compact = f"初始配置 ${self.current_map_id:02X}｜无独立部署记录"
                elif expanded:
                    compact = (
                        f"初始${self.current_map_id:02X}｜本关{scenario_bytes} B｜"
                        f"部署共{scenario_used} B｜共享池{used}/{shared_capacity} B"
                    )
                else:
                    compact = (
                        f"初始${self.current_map_id:02X}｜本关{scenario_bytes} B｜"
                        f"部署正文{scenario_used} B｜"
                        f"Bank$24八资源共享余量{scenario_remaining} B｜自动重排"
                    )
            elif mode == 2:
                if trigger_bytes is None:
                    compact = f"商店事件 ${self.current_map_id:02X}｜无独立触发记录"
                elif expanded:
                    compact = (
                        f"商店事件${self.current_map_id:02X}｜本关{len(staged_triggers)}条/{trigger_bytes} B｜"
                        f"触发共{trigger_used} B｜共享池{used}/{shared_capacity} B"
                    )
                else:
                    compact = (
                        f"商店事件${self.current_map_id:02X}｜本关{len(staged_triggers)}条/{trigger_bytes} B｜"
                        f"32关事件/商店共享{trigger_used}/{trigger_capacity} B｜自动重排"
                    )
            elif expanded:
                compact_status = "共享池重排" if size_ok else status
                compact = (
                    f"地图 ${self.current_map_id:02X} · "
                    f"共享池 {used} / {shared_capacity} B · {compact_status}"
                )
            else:
                compact_status = "可迁移" if size_ok else status
                compact = (
                    f"图${self.current_map_id:02X}｜Bank共享{used}/{terrain_capacity}｜"
                    f"三Bank独立{total_used}/{total_capacity}｜{compact_status}"
                )
            if mode == 1 and scenario_details is not None:
                selected_details = scenario_details
                selected_status = (
                    "可保存（地图共享池自动重排）"
                    if expanded
                    else "可保存（部署记录自动重排）"
                )
            elif mode == 2 and trigger_details is not None:
                selected_details = trigger_details
                selected_status = (
                    "可保存（地图共享池自动重排）"
                    if expanded
                    else "可保存（事件/商店自动重排）"
                )
            else:
                selected_details = terrain_details
                selected_status = status
            if not size_ok:
                selected_status = status
            full_details = (
                f"地图 ${self.current_map_id:02X} · {dc_map_label(self.current_map_id)} · "
                f"{selected_details} · {selected_status}"
            )
            self.size_label.setText(compact if size_ok else f"{compact}｜{status}")
            # Native Windows tooltips do not wrap long plain text reliably.
            # Split the detailed accounting into short semantic lines so the
            # popup stays inside the editor instead of spanning the desktop.
            self.size_label.setToolTip(full_details.replace(" · ", "\n"))
            # Keep the hidden compatibility apply action enabled for every
            # pending draft.  MainWindow uses this button as its save guard;
            # disabling it on invalid input would let that draft be ignored.
            self.apply_button.setEnabled(changed)
            self.pending_state.setText(
                "● 有尚未应用的地图/部署/事件改动"
                if changed
                else "✓ 地图、部署与事件已应用到当前工程"
            )
            self.pending_state.setProperty("pending", changed)
            self.pending_state.setVisible(changed)
            self.apply_button.setVisible(changed)
        except (ValueError, TypeError) as error:
            self.size_label.setText(f"当前输入无法保存：{error}")
            self.pending_state.setText("● 请修正输入或容量问题")
            self.pending_state.setProperty("pending", True)
            self.apply_button.setEnabled(self.has_pending_draft)
            self.pending_state.setVisible(True)
            self.apply_button.setVisible(True)
        self.pending_state.style().unpolish(self.pending_state)
        self.pending_state.style().polish(self.pending_state)
        self._emit_draft_state_changed()

    def _emit_draft_state_changed(self) -> None:
        """Notify the shell when this page-local draft or its validity changes."""

        state = (self.has_pending_draft, self.pending_draft_error)
        if state == self._last_draft_state:
            return
        self._last_draft_state = state
        self.draft_state_changed.emit()

    def _staged_layout(self) -> ScenarioLayout:
        assert self.project is not None and self.current_map_id is not None
        current = self.project.get_scenario_layout(self.current_map_id)
        return ScenarioLayout(
            self.current_map_id,
            current.pointer,
            self._parse_hex_bytes(self.prelude.text()),
            tuple(ScenarioEntity(*values) for values in self.enemy_table.rows()),
            tuple(ScenarioEntity(*values) for values in self.guest_table.rows()),
            tuple(PlayerPlacement(*values) for values in self.player_table.rows()),
            current.raw,
            current.capacity,
        )

    def _staged_triggers(self) -> tuple[MapTrigger, ...]:
        return tuple(MapTrigger(*values) for values in self.trigger_table.rows())

    @staticmethod
    def _parse_hex_bytes(text: str) -> tuple[int, ...]:
        compact = "".join(character for character in text if character not in " \t\r\n,-_")
        if not compact:
            return ()
        if len(compact) % 2:
            raise ValueError("前导字节必须是完整的两位十六进制数。")
        result = tuple(bytes.fromhex(compact))
        if 0xFF in result:
            raise ValueError("前导列表不需要手工填写结束标记 FF。")
        return result

    def apply_changes(self) -> None:
        if not self.commit_pending_changes():
            self.show_error(
                ValueError(
                    self.pending_draft_error or "当前地图草稿无法提交。"
                )
            )

    def reset_current(self) -> None:
        if self.project is None or self.current_map_id is None:
            return
        try:
            with self.project.transaction(f"地图 ${self.current_map_id:02X} · 完整还原"):
                self.project.reset_map(self.current_map_id)
                if (
                    self._deployment_write_verified
                    and self.current_map_id < self.project.scenario_count
                ):
                    self.project.reset_scenario_layout(self.current_map_id)
                if (
                    self._trigger_write_verified
                    and
                    self.project.map_trigger_codec is not None
                    and self.current_map_id
                    < self.project.map_trigger_codec.spec.scenario_count
                ):
                    self.project.reset_map_triggers(self.current_map_id)
            self._map_selected(self.map_list.currentItem(), None)
            self.project_changed.emit(
                f"已还原地图 ${self.current_map_id:02X}、部署与事件"
            )
        except Exception as error:
            self.show_error(error)
