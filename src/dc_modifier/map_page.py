from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QPoint, QRect, QSize, Qt, Signal
from PySide6.QtGui import (
    QColor, QFont, QFontDatabase, QIcon, QImage, QMouseEvent, QPainter,
    QPen, QPixmap, QStandardItemModel,
)
from PySide6.QtWidgets import (
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
    QToolTip,
    QVBoxLayout,
    QWidget,
)

from fc_editor.dc_text import dc_map_label
from fc_editor.codecs.character_attributes import (
    CharacterAttributesCodec,
    weapon_extra_values,
)
from fc_editor.codecs.legacy_text_growth import LegacyGrowthCodec
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
        self.setAccessibleName(f"位图{tile:X}")

    def mousePressEvent(self, event: QMouseEvent) -> None:
        if event.button() == Qt.MouseButton.RightButton:
            self.right_clicked.emit(self.tile)
            event.accept()
            return
        super().mousePressEvent(event)


def render_unit_icon_bank(project, bank: int) -> QImage:
    """Render a raw CHR bank as sixteen 2×2-tile map-icon candidates.

    This is a bank preview, not a claimed unit-ID or chapter binding.  The
    legacy BMP evidence establishes four 8×8 tiles per 16×16 icon.
    """

    image = QImage(256, 16, QImage.Format.Format_RGB32)
    image.fill(ICON_PALETTE[0])
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
                        ICON_PALETTE[pixels[y * 8 + x]],
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


class NesPaletteDialog(QDialog):
    """Four rows of sixteen colors, matching the legacy palette layout."""

    def __init__(self, current: int, parent=None) -> None:
        super().__init__(parent)
        self.selected_value = current
        self.setWindowTitle("选择 NES 颜色")
        grid = QGridLayout(self)
        grid.setSpacing(3)
        for value in range(0x40):
            color = palette_color(value)
            button = QPushButton(f"{value:02X}")
            button.setFixedSize(40, 38)
            button.setToolTip(
                f"NES 色号 ${value:02X} · RGB {color.name().upper()}（FCEUX.pal）"
            )
            button.setAccessibleName(f"NES颜色{value:02X}")
            foreground = "#000000" if color.lightness() >= 128 else "#FFFFFF"
            border = "3px solid #00A3E0" if value == current else "1px solid #555555"
            button.setStyleSheet(
                f"background:{color.name()}; color:{foreground}; border:{border};"
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


class TileAttributeDialog(QDialog):
    """Editor for the verified 84-byte terrain-property record."""

    MOVE_LABELS = (
        "不能移动", "不补正", *(f"补正{value}格" for value in range(1, 16))
    )

    def __init__(self, project, tileset_key: str, images: tuple[QImage, ...], parent=None) -> None:
        super().__init__(parent)
        self.project = project
        self.tileset_key = tileset_key.upper()
        self.setWindowTitle("编辑图块属性")
        self.resize(1040, 700)
        root = QVBoxLayout(self)
        self.notice = QLabel()
        self.notice.setWordWrap(True)
        root.addWidget(self.notice)

        self.color_group = QGroupBox("颜色表1（NES 色号）")
        color_layout = QHBoxLayout(self.color_group)
        self.color_spins: list[QSpinBox] = []
        self.color_buttons: list[NesColorButton] = []
        for index in range(3):
            color_layout.addWidget(QLabel(f"颜色{index + 1}"))
            color_button = NesColorButton()
            color_button.setAccessibleName(f"颜色表1颜色{index + 1}色块")
            self.color_buttons.append(color_button)
            color_layout.addWidget(color_button)
            spin = QSpinBox()
            spin.setRange(0, 0x3F)
            spin.setDisplayIntegerBase(16)
            spin.setPrefix("$")
            spin.setAccessibleName(f"颜色表1颜色{index + 1}")
            spin.setToolTip("可直接输入十六进制色号；也可点击左侧色块选择")
            self.color_spins.append(spin)
            color_layout.addWidget(spin)
            spin.valueChanged.connect(color_button.set_value)
            color_button.value_changed.connect(spin.setValue)
        color_layout.addStretch(1)
        self.palette_preview = QLabel()
        self.palette_preview.setFixedSize(144, 40)
        self.palette_preview.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.palette_preview.setAccessibleName("颜色表1四色预览")
        color_layout.addWidget(QLabel("组合预览"))
        color_layout.addWidget(self.palette_preview)
        root.addWidget(self.color_group)

        self.shared_palette_group = QGroupBox("颜色表2、3（公用真实色号，只读）")
        shared_layout = QGridLayout(self.shared_palette_group)
        shared_hint = QLabel(
            "已用基准 ROM 的地图加载流程和运行时调色板完成验证；公用表不属于图库属性记录，因此只读。"
        )
        shared_hint.setWordWrap(True)
        shared_layout.addWidget(shared_hint, 0, 0, 1, 3)
        self.shared_palette_previews: dict[int, QLabel] = {}
        self.shared_palette_tiles: dict[int, QLabel] = {}
        for row, palette_index in enumerate((2, 3), start=1):
            shared_layout.addWidget(QLabel(f"颜色表{palette_index}"), row, 0)
            preview = QLabel()
            preview.setFixedSize(144, 32)
            preview.setAccessibleName(f"颜色表{palette_index}只读预览")
            self.shared_palette_previews[palette_index] = preview
            shared_layout.addWidget(preview, row, 1)
            tiles = QLabel()
            tiles.setWordWrap(True)
            self.shared_palette_tiles[palette_index] = tiles
            shared_layout.addWidget(tiles, row, 2)
        shared_layout.setColumnStretch(2, 1)
        root.addWidget(self.shared_palette_group)

        self.table = QTableWidget(16, 7)
        self.table.setHorizontalHeaderLabels(
            ("位图", "属性颜色表（原码）", "防御补正", "海", "空中移动", "陆地移动", "海上移动")
        )
        self.table.verticalHeader().setVisible(False)
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        for column in range(1, 7):
            self.table.horizontalHeader().setSectionResizeMode(column, QHeaderView.ResizeMode.Stretch)
        self.palette_boxes: list[QComboBox] = []
        self.defense_spins: list[QSpinBox] = []
        self.sea_checks: list[QCheckBox] = []
        self.air_boxes: list[QComboBox] = []
        self.land_boxes: list[QComboBox] = []
        self.sea_boxes: list[QComboBox] = []
        for tile_index in range(16):
            tile_item = QTableWidgetItem(f"位图{tile_index:X}")
            if tile_index < len(images):
                tile_item.setIcon(QIcon(QPixmap.fromImage(images[tile_index])))
            tile_item.setFlags(tile_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
            self.table.setItem(tile_index, 0, tile_item)
            palette = QComboBox()
            palette.addItems(("背景色", "颜色表1", "颜色表2（公用）", "颜色表3（公用）"))
            palette.setIconSize(QSize(56, 14))
            palette.setAccessibleName(f"位图{tile_index:X}颜色表")
            palette.setToolTip(
                "旧版属性记录中的颜色表原码；保留显示和写回，但图块预览以游戏内地形效果为准。"
            )
            palette.currentIndexChanged.connect(self._refresh_color_visuals)
            self.table.setCellWidget(tile_index, 1, palette)
            self.palette_boxes.append(palette)
            defense = QSpinBox()
            defense.setRange(0, 127)
            defense.setSuffix("%")
            defense.setAccessibleName(f"位图{tile_index:X}防御补正")
            self.table.setCellWidget(tile_index, 2, defense)
            self.defense_spins.append(defense)
            sea = QCheckBox("是")
            sea.setAccessibleName(f"位图{tile_index:X}海属性")
            self.table.setCellWidget(tile_index, 3, sea)
            self.sea_checks.append(sea)
            movement_boxes: list[QComboBox] = []
            for column, label in ((4, "空中"), (5, "陆地"), (6, "海上")):
                movement = QComboBox()
                movement.addItems(self.MOVE_LABELS)
                movement.setAccessibleName(f"位图{tile_index:X}{label}移动补正")
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
        self.buttons.button(QDialogButtonBox.StandardButton.RestoreDefaults).setText("还原为打开 ROM 时的值")
        self.buttons.accepted.connect(self.accept)
        self.buttons.rejected.connect(self.reject)
        self.buttons.button(QDialogButtonBox.StandardButton.RestoreDefaults).clicked.connect(self._load_original)
        root.addWidget(self.buttons)

        self._supported = bool(
            project is not None and project.supports_map_tile_attributes
            and self.tileset_key in "ABCDEFG"
        )
        if self._supported:
            self.notice.setText(
                f"图库 {self.tileset_key}：颜色表、防御补正、海属性及空/陆/海移动补正"
                "已完成字段级差分验证。颜色表2、3为公用表，本窗口只修改颜色表1。"
                "属性颜色表列保留旧版原码。若扩展 ROM 漏写已确认水面图块的海属性，"
                "界面会勾选提示，应用时补写。所有图块预览均按游戏内地形效果显示。"
            )
            self._load(project.get_map_tileset_attributes(self.tileset_key))
        else:
            self.notice.setText(
                f"图库 {self.tileset_key} 没有已验证的图块属性记录，当前仅显示图块预览。"
            )
            self.color_group.setEnabled(False)
            self.table.setEnabled(False)
            self.buttons.button(QDialogButtonBox.StandardButton.Save).setEnabled(False)
            self.buttons.button(QDialogButtonBox.StandardButton.RestoreDefaults).setEnabled(False)
        for spin in self.color_spins:
            spin.valueChanged.connect(self._refresh_color_visuals)
        self._refresh_shared_palette_visuals()
        self._refresh_color_visuals()

    def _load(self, value: MapTilesetAttributes) -> None:
        for spin, color in zip(self.color_spins, value.colors, strict=True):
            spin.setValue(color)
        for index, tile in enumerate(value.tiles):
            self.palette_boxes[index].setCurrentIndex(tile.palette)
            self.defense_spins[index].setValue(tile.defense)
            inferred_sea = (
                not tile.sea
                and MapTileAttributeCodec.is_visual_sea(
                    self.tileset_key, index
                )
            )
            self.sea_checks[index].setChecked(tile.sea or inferred_sea)
            self.sea_checks[index].setToolTip(
                "ROM 海属性标志已读取。"
                if not inferred_sea
                else "ROM 漏写海属性；已按旧修改器备份与相同水面 CHR 识别。应用后会补写标志。"
            )
            self.air_boxes[index].setCurrentIndex(tile.air_move)
            self.land_boxes[index].setCurrentIndex(tile.land_move)
            self.sea_boxes[index].setCurrentIndex(tile.sea_move)
        self._refresh_color_visuals()

    def _refresh_color_visuals(self, _value: int | None = None) -> None:
        colors = tuple(spin.value() for spin in self.color_spins)
        preview_colors = (palette_color(0x0F), *(palette_color(value) for value in colors))
        preview = self._palette_strip(preview_colors, 144, 40)
        self.palette_preview.setPixmap(preview)
        self.palette_preview.setToolTip(
            "共同背景色 $0F + " + " / ".join(f"${value:02X}" for value in colors)
        )
        if not getattr(self, "_supported", False):
            return
        attributes = self._value()
        self._refresh_shared_palette_visuals()
        palette_icons = {
            0: self._palette_strip(self._verified_palette(0), 56, 14),
            1: self._palette_strip(preview_colors, 56, 14),
        }
        for palette_index in (2, 3):
            palette_icons[palette_index] = self._palette_strip(
                self._verified_palette(palette_index), 56, 14
            )
        for box in self.palette_boxes:
            for palette_index, icon in palette_icons.items():
                box.setItemIcon(palette_index, QIcon(icon))
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

    @staticmethod
    def _verified_palette(palette_index: int) -> tuple[QColor, ...]:
        return tuple(
            palette_color(value)
            for value in VERIFIED_BATTLEFIELD_PALETTES[palette_index]
        )

    def _refresh_shared_palette_visuals(self) -> None:
        if self.tileset_key not in TILESET_PALETTE_ROUTES:
            return
        attributes = (
            self.project.get_map_tileset_attributes(self.tileset_key)
            if self._supported
            else None
        )
        for palette_index in (2, 3):
            values = VERIFIED_BATTLEFIELD_PALETTES[palette_index]
            colors = self._verified_palette(palette_index)
            preview = self.shared_palette_previews[palette_index]
            preview.setPixmap(self._palette_strip(colors, 144, 32))
            preview.setToolTip(
                f"颜色表{palette_index}真实 NES 色号："
                + " / ".join(f"${value:02X}" for value in values)
                + "；只读"
            )
            used = (
                [index for index, tile in enumerate(attributes.tiles)
                 if tile.palette == palette_index]
                if attributes is not None
                else []
            )
            text = "色号：" + " · ".join(f"${value:02X}" for value in values)
            text += "\n属性原码引用图块：" + (
                "、".join(f"{index:X}" for index in used) if used else "未确认"
            )
            self.shared_palette_tiles[palette_index].setText(text)

    def _load_original(self) -> None:
        if self._supported:
            self._load(self.project.get_map_tileset_attributes(self.tileset_key, original=True))

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
            )
            for index in range(16)
        )
        colors = tuple(spin.value() for spin in self.color_spins)
        return MapTilesetAttributes(colors, current.graphic_selector, tiles)  # type: ignore[arg-type]

    def accept(self) -> None:
        if not self._supported:
            return
        try:
            self.project.set_map_tileset_attributes(self.tileset_key, self._value())
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
        self.map_width = 1
        self.map_height = 1
        self.tiles = [0]
        self.cell_size = 24
        self.selected_tile = 0
        self.right_selected_tile = 0
        self.tile_images: tuple[QImage, ...] = ()
        self.show_tile_ids = False
        self.overlays: list[tuple[str, int, int, str, int]] = []
        self.dragged_overlay: tuple[str, int] | None = None
        self.selected_overlay: tuple[str, int] | None = None
        self.overlay_descriptions: dict[tuple[str, int], str] = {}
        self.overlay_images: dict[tuple[str, int], QImage] = {}
        self._visible_tooltip_key: tuple[tuple[int, int], str] | None = None
        self.paint_enabled = True
        self.deployment_edit_enabled = False
        self.trigger_edit_enabled = False
        self.setMouseTracking(True)

    def sizeHint(self) -> QSize:
        return QSize(self.map_width * self.cell_size + 1, self.map_height * self.cell_size + 1)

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
                painter.setPen(QPen(QColor(0, 0, 0, 45), 1))
                painter.drawRect(rect)
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
        for side, x, y, label, row in self.overlays:
            if not 0 <= x < self.map_width or not 0 <= y < self.map_height:
                continue
            icon = self.overlay_images.get((side, row))
            if icon is not None and not icon.isNull():
                icon_rect = QRect(
                    x * self.cell_size,
                    y * self.cell_size,
                    self.cell_size,
                    self.cell_size,
                )
                # Keep the dark plate for visibility on detailed terrain, but
                # omit permanent faction rims and use the full map cell for
                # the authentic four-tile sprite.
                painter.fillRect(icon_rect, QColor(0, 0, 0, 235))
                painter.drawImage(icon_rect, icon)
                if self.selected_overlay == (side, row):
                    painter.setBrush(Qt.BrushStyle.NoBrush)
                    painter.setPen(QPen(QColor("#ffe45e"), 3))
                    painter.drawRect(icon_rect.adjusted(1, 1, -1, -1))
                continue
            # Empty runtime party slots do not create a unit in the game.
            # Keep them in the hit-test collection for right-click editing,
            # but do not invent a numbered machine marker on the battlefield.
            if side == "我":
                continue
            margin = max(2, self.cell_size // 7)
            rect = QRect(
                x * self.cell_size + margin,
                y * self.cell_size + margin,
                self.cell_size - margin * 2,
                self.cell_size - margin * 2,
            )
            painter.setBrush(side_colors[side])
            painter.setPen(QPen(Qt.GlobalColor.white, 1))
            painter.drawEllipse(rect)
            if self.selected_overlay == (side, row):
                painter.setBrush(Qt.BrushStyle.NoBrush)
                painter.setPen(QPen(QColor("#ffe45e"), 3))
                painter.drawRect(rect.adjusted(-2, -2, 2, 2))
                painter.setPen(Qt.GlobalColor.white)
            if self.cell_size >= 20:
                painter.drawText(rect, Qt.AlignmentFlag.AlignCenter, label)

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
                self.dragged_overlay = overlay
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
        if cell is not None:
            self.coordinate_changed.emit(*cell)
            descriptions = [
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
            while self.rowCount() > len(rows):
                self.removeRow(self.rowCount() - 1)
            while self.rowCount() < len(rows):
                self.add_row(rows[self.rowCount()])
            for row, values in enumerate(rows):
                for column, value in enumerate(values):
                    editor = self.cellWidget(row, column)
                    provider = self.label_providers.get(column)
                    if isinstance(editor, QComboBox) and provider is not None:
                        model = self._choice_model(column, provider)
                        if editor.model() is not model:
                            editor.setModel(model)
                        editor.setCurrentIndex(editor.findData(value))
                    elif isinstance(editor, QSpinBox):
                        editor.setValue(value)
            if rows:
                self.setCurrentCell(0, 0)
        finally:
            self.setUpdatesEnabled(True)
            self.blockSignals(previous)
        self.values_changed.emit()

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
        self.insertRow(row)
        for column, value in enumerate(values):
            provider = self.label_providers.get(column)
            if provider is not None:
                editor = QComboBox()
                editor.setMaxVisibleItems(24)
                editor.setModel(self._choice_model(column, provider))
                editor.setCurrentIndex(editor.findData(value))
                editor.currentIndexChanged.connect(self.values_changed)
            else:
                editor = QSpinBox()
                editor.setRange(0, 255)
                hexadecimal = self.headers[column] not in ("X", "Y", "等级")
                editor.setDisplayIntegerBase(16 if hexadecimal else 10)
                editor.setPrefix("$" if hexadecimal else "")
                editor.setValue(value)
                editor.valueChanged.connect(self.values_changed)
            self.setCellWidget(row, column, editor)
        self.setCurrentCell(row, 0)
        self.values_changed.emit()
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
        if row >= 0:
            self.removeRow(row)
            self.values_changed.emit()

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
        self._player_slot_cache_key: tuple | None = None
        self._player_slot_snapshots: tuple[dict[int, tuple[int, int]], ...] = ()
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
        self._trigger_payload_cache: tuple[bytes, ...] | None = None
        outer = QVBoxLayout(self)
        outer.setContentsMargins(8, 8, 8, 8)
        self.main_splitter = QSplitter(Qt.Orientation.Horizontal)
        self.main_splitter.setObjectName("mapMainSplitter")
        self.main_splitter.setChildrenCollapsible(False)

        # Match the original SRW2 editor: editing tabs above the chapter list
        # on the left, with the complete battlefield occupying the right side.
        self.navigator = QWidget()
        self.navigator.setObjectName("mapLeftPane")
        self.navigator.setMinimumWidth(330)
        self.navigator.setMaximumWidth(620)
        inspector_layout = QVBoxLayout(self.navigator)
        inspector_layout.setContentsMargins(0, 0, 8, 0)

        self.editor_tabs = QTabWidget()
        self.editor_tabs.setObjectName("subTabs")
        tile_tab = QWidget()
        tile_layout = QVBoxLayout(tile_tab)
        tile_layout.setContentsMargins(8, 8, 8, 8)

        brush_group = QGroupBox("地图图块设置")
        brush_group.setMinimumHeight(210)
        brush_layout = QVBoxLayout(brush_group)
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
        self.terrain.currentIndexChanged.connect(self._terrain_selected)
        self.terrain.hide()
        self.tile_attribute_button = QPushButton("编辑图块属性")
        self.tile_attribute_button.clicked.connect(self._open_tile_attributes)
        bitmap_row.addWidget(self.tile_attribute_button)
        brush_layout.addLayout(bitmap_row)

        palette = QGridLayout()
        palette.setSpacing(2)
        self.terrain_buttons = QButtonGroup(self)
        self.terrain_buttons.setExclusive(True)
        for tile, color in enumerate(TERRAIN_COLORS):
            button = TerrainButton(tile)
            button.setObjectName("terrainButton")
            button.setCheckable(True)
            button.setMinimumSize(34, 34)
            button.setIconSize(QSize(30, 30))
            button.setToolTip(
                f"位图{tile:X}：左键设为左键画笔，右键设为右键画笔"
            )
            button.setStyleSheet(
                "QPushButton { background: %s; color: %s; }"
                "QPushButton:checked { border: 3px solid #082f49; }"
                % (color.name(), "#ffffff" if color.lightness() < 135 else "#13293a")
            )
            self.terrain_buttons.addButton(button, tile)
            button.clicked.connect(lambda _checked=False, value=tile: self.terrain.setCurrentIndex(value))
            button.right_clicked.connect(self._select_right_brush)
            palette.addWidget(button, tile // 8, tile % 8)
        self.terrain_buttons.button(0).setChecked(True)
        brush_layout.addLayout(palette)

        brush_row = QHBoxLayout()
        left_brush = QVBoxLayout()
        left_caption = QLabel("左键")
        left_caption.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.left_brush_preview = QLabel("位图0")
        self.left_brush_preview.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.left_brush_preview.setFixedSize(64, 64)
        self.left_brush_preview.setStyleSheet("background: black; border: 1px solid #7d8790;")
        left_brush.addWidget(left_caption)
        left_brush.addWidget(self.left_brush_preview)
        brush_row.addLayout(left_brush)

        library = QVBoxLayout()
        library_caption = QLabel("图库选择")
        library_caption.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.tileset = QComboBox()
        for key, bank in TILESET_BANKS.items():
            self.tileset.addItem(f"[{bank:02X}]{bank:03d}: 图库{key}", key)
        self.tileset.currentIndexChanged.connect(self._refresh_tile_visuals)
        library.addWidget(library_caption)
        library.addWidget(self.tileset)
        library.addStretch()
        brush_row.addLayout(library, 1)

        right_brush = QVBoxLayout()
        right_caption = QLabel("右键")
        right_caption.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.right_brush_preview = QLabel("位图0")
        self.right_brush_preview.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.right_brush_preview.setFixedSize(64, 64)
        self.right_brush_preview.setStyleSheet("background: black; border: 1px solid #7d8790;")
        right_brush.addWidget(right_caption)
        right_brush.addWidget(self.right_brush_preview)
        brush_row.addLayout(right_brush)
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
        tile_layout.addWidget(brush_group)

        dimensions = QWidget()
        dimensions_layout = QGridLayout(dimensions)
        dimensions_layout.setContentsMargins(8, 0, 8, 0)
        self.width_editor = QSpinBox()
        self.width_editor.setRange(1, 32)
        self.height_editor = QSpinBox()
        self.height_editor.setRange(1, 32)
        self.width_display = QSpinBox()
        self.width_display.setRange(1, 32)
        self.width_display.setReadOnly(True)
        self.width_display.setButtonSymbols(QSpinBox.ButtonSymbols.NoButtons)
        self.height_display = QSpinBox()
        self.height_display.setRange(1, 32)
        self.height_display.setReadOnly(True)
        self.height_display.setButtonSymbols(QSpinBox.ButtonSymbols.NoButtons)
        self.resize_button = QPushButton("调整尺寸")
        self.resize_button.clicked.connect(self._resize_map)
        dimensions_layout.addWidget(QLabel("地图高度"), 0, 0)
        dimensions_layout.addWidget(self.height_display, 0, 1)
        dimensions_layout.addWidget(QLabel("地图宽度"), 0, 2)
        dimensions_layout.addWidget(self.width_display, 0, 3)
        self.prelude = QLineEdit()
        self.prelude.setPlaceholderText("前导字节，例如 01 02；不含 FF")
        self.prelude.textChanged.connect(self._update_size_label)
        tile_layout.addWidget(dimensions)

        self.title_preview = QLabel("")
        self.title_preview.setObjectName("legacyMapTitlePreview")
        self.title_preview.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.title_preview.setMinimumHeight(48)
        self.title_preview.setMaximumHeight(64)
        self.title_preview.setStyleSheet(
            "background: #000000; border: 1px solid #202020;"
        )
        tile_layout.addWidget(self.title_preview)
        self.open_map_advanced_button = QPushButton("高级地图数据…")
        self.open_map_advanced_button.clicked.connect(self._show_map_advanced)
        tile_layout.addWidget(
            self.open_map_advanced_button,
            0,
            Qt.AlignmentFlag.AlignRight,
        )
        tile_layout.addStretch()
        self.editor_tabs.addTab(tile_tab, "战场地图")

        initial_tab = QWidget()
        initial_layout = QVBoxLayout(initial_tab)
        initial_layout.setContentsMargins(8, 8, 8, 8)
        self.deployment_summary = QLabel("选择地图以查看实际部署")
        self.deployment_summary.setWordWrap(True)
        initial_layout.addWidget(self.deployment_summary)
        self.deployment_objects = QListWidget()
        self.deployment_objects.setAlternatingRowColors(True)
        self.deployment_objects.currentItemChanged.connect(self._object_list_selected)
        self.deployment_objects.itemClicked.connect(self._object_list_selected)
        self.deployment_objects.itemDoubleClicked.connect(self._object_list_activated)
        self.deployment_objects.setMinimumHeight(65)
        self.deployment_objects.setMaximumHeight(120)
        self.icon_preview_toggle = QPushButton("展开机体图标库（只读）")
        self.icon_preview_toggle.setCheckable(True)
        self.icon_preview_toggle.setMaximumSize(220, 30)
        icon_group = QGroupBox("机体图标（对应地图小图标编号，只读）")
        icon_group.setMaximumHeight(195)
        self.icon_preview_group = icon_group
        self.icon_preview_toggle.toggled.connect(self._toggle_icon_preview)
        initial_layout.addWidget(
            self.icon_preview_toggle,
            0,
            Qt.AlignmentFlag.AlignRight,
        )
        icon_group_layout = QGridLayout(icon_group)
        icon_group_layout.setContentsMargins(8, 6, 8, 6)
        icon_group_layout.setHorizontalSpacing(6)
        icon_group_layout.setVerticalSpacing(3)
        self.icon_bank_selectors: list[QComboBox] = []
        self.icon_sheet_labels: list[QLabel] = []
        for slot, default_bank in enumerate(SCENARIO_MAP_ICON_BANKS[0], start=1):
            address_label = QLabel(f"地址{slot}")
            address_label.setAlignment(
                Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter
            )
            selector = QComboBox()
            selector.setFixedWidth(150)
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
            preview.setFixedSize(192, 48)
            preview.setToolTip(
                "16 个 2×2 图块图标，按战场运行时蓝色表 $0F $30 $21 $02 显示。"
            )
            preview.setStyleSheet("background: transparent; border: none;")
            row = slot - 1
            icon_group_layout.addWidget(address_label, row, 0)
            icon_group_layout.addWidget(selector, row, 1)
            icon_group_layout.addWidget(preview, row, 2)
            self.icon_bank_selectors.append(selector)
            self.icon_sheet_labels.append(preview)
        icon_group_layout.setColumnStretch(3, 1)
        initial_layout.addWidget(icon_group)
        self.icon_preview_toggle.setChecked(False)
        icon_group.setVisible(False)
        initial_layout.addWidget(self.deployment_objects, 1)
        self.deployment_list_toggle = QPushButton("展开部署明细列表")
        self.deployment_list_toggle.setCheckable(True)
        self.deployment_list_toggle.setMaximumSize(180, 30)
        self.deployment_list_toggle.toggled.connect(
            self._toggle_deployment_list
        )
        initial_layout.insertWidget(
            initial_layout.indexOf(self.deployment_objects),
            self.deployment_list_toggle,
            0,
            Qt.AlignmentFlag.AlignRight,
        )
        self.deployment_list_toggle.setChecked(True)
        self.deployment_objects.setVisible(True)
        self.open_deployment_button = QPushButton("编辑部署 / 添加 / 复制…")
        self.open_deployment_button.setMaximumSize(210, 30)
        self.open_deployment_button.setToolTip(
            "扩展功能；图标地址选择本身仍为只读兼容预览，不会猜写绑定。"
        )
        self.open_deployment_button.clicked.connect(self._show_deployment_advanced)
        initial_layout.addWidget(
            self.open_deployment_button,
            0,
            Qt.AlignmentFlag.AlignRight,
        )

        self.deployment_dialog = QDialog(self)
        self.deployment_dialog.setWindowTitle("部署编辑 · 可同时操作地图")
        self.deployment_dialog.setModal(False)
        self.deployment_dialog.resize(1020, 650)
        deployment_layout = QVBoxLayout(self.deployment_dialog)
        deployment_hint = QLabel(
            "选择列表或地图机体图标可联动定位；地图右键直接编辑、新增或删除，"
            "双击图标也可编辑，左键拖动修改坐标。"
            "敌军最多18、客军3、我方出击位11；黄色边框表示选中对象。关闭窗口保留草稿。"
        )
        deployment_hint.setObjectName("hintText")
        deployment_hint.setWordWrap(True)
        deployment_layout.addWidget(deployment_hint)
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
        deployment_close = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        deployment_close.rejected.connect(self.deployment_dialog.close)
        deployment_layout.addWidget(deployment_close)
        self._build_deployment_cell_dialog()
        self.editor_tabs.addTab(initial_tab, "初始配置")

        trigger_tab = QWidget()
        trigger_layout = QVBoxLayout(trigger_tab)
        trigger_layout.setContentsMargins(8, 8, 8, 8)
        self.trigger_summary = QLabel("选择地图以查看商店与事件")
        self.trigger_summary.setWordWrap(True)
        trigger_layout.addWidget(self.trigger_summary)
        self.trigger_objects = QListWidget()
        self.trigger_objects.setAlternatingRowColors(True)
        self.trigger_objects.currentItemChanged.connect(self._object_list_selected)
        self.trigger_objects.itemClicked.connect(self._object_list_selected)
        self.trigger_objects.itemDoubleClicked.connect(self._object_list_activated)
        trigger_layout.addWidget(self.trigger_objects, 1)
        self.open_trigger_button = QPushButton("打开全部事件记录…")
        self.open_trigger_button.clicked.connect(self._show_trigger_advanced)
        self.open_trigger_button.setToolTip(
            "地图上的常用编辑已移到右键菜单；这里用于批量查看和调整全部记录。"
        )
        trigger_layout.addWidget(
            self.open_trigger_button,
            0,
            Qt.AlignmentFlag.AlignRight,
        )

        self.trigger_dialog = QDialog(self)
        self.trigger_dialog.setWindowTitle("高级地图事件与商店编辑")
        self.trigger_dialog.setModal(False)
        self.trigger_dialog.resize(900, 580)
        trigger_dialog_layout = QVBoxLayout(self.trigger_dialog)
        trigger_hint = QLabel(
            "编辑踩点触发的剧情事件或商店。限定人物为 $FF 时任何人物都可触发；"
            "事件号 $F0—$FF 表示商店 0—15。常用操作可直接在地图上右键完成；"
            "紫色“事”和绿色“店”圆点仍可拖动定位。"
        )
        trigger_hint.setObjectName("hintText")
        trigger_hint.setWordWrap(True)
        trigger_dialog_layout.addWidget(trigger_hint)
        self.trigger_table = self._deployment_group(
            trigger_dialog_layout,
            "地图事件与商店",
            ("X", "Y", "限定人物", "事件/商店"),
            {2: self._trigger_character_label, 3: self._trigger_event_label},
            default_values=(0, 0, 0xFF, 0),
        )
        trigger_close = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        trigger_close.button(QDialogButtonBox.StandardButton.Close).setText("关闭")
        trigger_close.rejected.connect(self.trigger_dialog.close)
        trigger_dialog_layout.addWidget(trigger_close)

        self.trigger_cell_dialog = QDialog(self)
        self.trigger_cell_dialog.setWindowTitle("商店设置")
        self.trigger_cell_dialog.setModal(True)
        trigger_cell_layout = QVBoxLayout(self.trigger_cell_dialog)
        trigger_cell_form = QFormLayout()
        coordinate_row = QHBoxLayout()
        self.trigger_x_editor = QSpinBox()
        self.trigger_y_editor = QSpinBox()
        for editor in (self.trigger_x_editor, self.trigger_y_editor):
            editor.setRange(0, 255)
        coordinate_row.addWidget(QLabel("X"))
        coordinate_row.addWidget(self.trigger_x_editor)
        coordinate_row.addWidget(QLabel("Y"))
        coordinate_row.addWidget(self.trigger_y_editor)
        coordinate_row.addStretch()
        trigger_cell_form.addRow("地图坐标", coordinate_row)
        self.trigger_character_combo = QComboBox()
        self.trigger_character_combo.setMaxVisibleItems(24)
        trigger_cell_form.addRow("限定人物", self.trigger_character_combo)
        self.trigger_shop_combo = QComboBox()
        for shop_id in range(0xF0, 0x100):
            self.trigger_shop_combo.addItem(
                f"{shop_id - 0xEF:02d}：商店 ${shop_id:02X}", shop_id
            )
        trigger_cell_form.addRow("商店选择", self.trigger_shop_combo)
        self.trigger_event_combo = QComboBox()
        self.trigger_event_combo.setMaxVisibleItems(24)
        for event_id in range(0xF0):
            self.trigger_event_combo.addItem(
                f"{event_id + 1:03d}：{self._trigger_event_label(event_id)}",
                event_id,
            )
        trigger_cell_form.addRow("地图事件", self.trigger_event_combo)
        trigger_cell_layout.addLayout(trigger_cell_form)
        kind_row = QHBoxLayout()
        self.trigger_shop_radio = QRadioButton("商店")
        self.trigger_event_radio = QRadioButton("事件")
        self.trigger_event_radio.setChecked(True)
        self.trigger_shop_radio.toggled.connect(self._trigger_kind_changed)
        self.trigger_event_radio.toggled.connect(self._trigger_kind_changed)
        kind_row.addWidget(self.trigger_shop_radio)
        kind_row.addWidget(self.trigger_event_radio)
        kind_row.addStretch()
        trigger_cell_layout.addLayout(kind_row)
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
        self.trigger_cell_buttons.accepted.connect(self._save_trigger_cell_editor)
        self.trigger_cell_buttons.rejected.connect(self.trigger_cell_dialog.reject)
        self.trigger_delete_button.clicked.connect(self._delete_edited_trigger)
        trigger_cell_layout.addWidget(self.trigger_cell_buttons)
        self._trigger_kind_changed()
        self.editor_tabs.addTab(trigger_tab, "商店事件")

        self.chapter_group = QGroupBox("关卡选择")
        chapter_layout = QVBoxLayout(self.chapter_group)
        self.search = QLineEdit()
        self.search.setPlaceholderText("搜索关卡名、地图ID…")
        self.search.setClearButtonEnabled(True)
        self.search.textChanged.connect(self._filter_maps)
        self.map_count_label = QLabel("0 个地图")
        self.map_count_label.setObjectName("countBadge")
        search_row = QHBoxLayout()
        search_row.addWidget(self.search, 1)
        search_row.addWidget(self.map_count_label)
        chapter_layout.addLayout(search_row)
        self.map_list = QListWidget()
        self.map_list.setAlternatingRowColors(True)
        self.map_list.setUniformItemSizes(True)
        self.map_list.currentItemChanged.connect(self._map_selected)
        chapter_layout.addWidget(self.map_list)
        self.chapter_group.setMinimumHeight(260)
        inspector_layout.addWidget(self.editor_tabs, 2)
        inspector_layout.addWidget(self.chapter_group, 3)
        self.editor_tabs.currentChanged.connect(self._editor_mode_changed)
        self.main_splitter.addWidget(self.navigator)

        self.canvas_host = QWidget()
        self.canvas_host.setObjectName("mapPreviewPane")
        self.canvas_host.setMinimumWidth(360)
        canvas_layout = QVBoxLayout(self.canvas_host)
        canvas_layout.setContentsMargins(8, 0, 0, 0)
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
            Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignTop
        )
        self.map_scroll.viewport_resized.connect(self._fit_map_to_viewport)
        preview_toolbar = QHBoxLayout()
        preview_toolbar.addWidget(self.fit_view)
        preview_toolbar.addWidget(QLabel("缩放"))
        preview_toolbar.addWidget(self.zoom)
        self.show_all_objects = QCheckBox("叠加全部对象")
        self.show_all_objects.setToolTip("在地形页同时显示部署、事件和商店；编辑对象页不会误画地形。")
        self.show_all_objects.toggled.connect(self._update_overlays)
        preview_toolbar.addWidget(self.show_all_objects)
        preview_toolbar.addStretch()
        self.capacity_help_button = QPushButton("容量规划…")
        self.capacity_help_button.setToolTip(
            "原记录容量不足时，可在464 KiB版本中规划并接通地图共享池；保留当前地图草稿。"
        )
        self.capacity_help_button.clicked.connect(self._open_capacity_planner)
        preview_toolbar.addWidget(self.capacity_help_button)
        canvas_layout.addLayout(preview_toolbar)
        canvas_layout.addWidget(self.map_scroll, 1)

        info_row = QHBoxLayout()
        info_row.addWidget(self.position_label, 1)
        info_row.addWidget(self.y_position_label, 1)
        canvas_layout.addLayout(info_row)

        self.pending_state = QLabel("选择地图后可编辑。")
        self.pending_state.setObjectName("editState")
        self.apply_button = QPushButton("应用地图、部署与事件")
        self.apply_button.setObjectName("primaryButton")
        self.apply_button.clicked.connect(self.apply_changes)
        self.apply_button.setEnabled(False)
        self.reset_button = QPushButton("还原")
        self.reset_button.clicked.connect(self.reset_current)
        self.size_label.setWordWrap(True)
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
        self.main_splitter.setSizes([440, 920])
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
        display_layout.addWidget(self.show_ids)
        display_layout.addWidget(self.tileset_meta)
        display_layout.addWidget(self.brush_hint)
        root.addWidget(display_group)

        notice = QLabel("缩放、容量和应用按钮位于地图主界面。调整尺寸后会检查部署坐标；超出边界不会直接写入ROM。")
        notice.setWordWrap(True)
        root.addWidget(notice)
        root.addStretch()

        buttons = QHBoxLayout()
        buttons.addWidget(self.reset_button)
        buttons.addStretch()
        close_buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
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

    def _show_deployment_advanced(self) -> None:
        self.deployment_dialog.show()
        self.deployment_dialog.raise_()
        self.deployment_dialog.activateWindow()

    def _build_deployment_cell_dialog(self) -> None:
        """Build the compact reference-style editor used from the map menu."""

        self.deployment_cell_dialog = QDialog(self)
        self.deployment_cell_dialog.setWindowTitle("配置设置")
        self.deployment_cell_dialog.setModal(False)
        self.deployment_cell_dialog.setMinimumWidth(500)
        root = QVBoxLayout(self.deployment_cell_dialog)
        form = QFormLayout()

        self.deployment_side_combo = QComboBox()
        for side, label in (("我", "我方配置"), ("敌", "敌方配置"), ("客", "客军配置")):
            self.deployment_side_combo.addItem(label, side)
        self.deployment_x_editor = QSpinBox()
        self.deployment_y_editor = QSpinBox()
        for editor in (self.deployment_x_editor, self.deployment_y_editor):
            editor.setRange(0, 255)
        coordinate_row = QWidget()
        coordinate_layout = QHBoxLayout(coordinate_row)
        coordinate_layout.setContentsMargins(0, 0, 0, 0)
        coordinate_layout.addWidget(QLabel("X"))
        coordinate_layout.addWidget(self.deployment_x_editor)
        coordinate_layout.addWidget(QLabel("Y"))
        coordinate_layout.addWidget(self.deployment_y_editor)

        self.deployment_character_combo = QComboBox()
        self.deployment_unit_combo = QComboBox()
        self.deployment_level_editor = QSpinBox()
        self.deployment_level_editor.setRange(1, 255)
        self.deployment_action_combo = QComboBox()
        self.deployment_action_combo.setMaxVisibleItems(24)
        for action_id, label in enumerate(ACTION_NAMES):
            self.deployment_action_combo.addItem(
                f"{action_id:03d}: {label}", action_id
            )
        self.deployment_roster_combo = QComboBox()
        self.deployment_roster_combo.setMaxVisibleItems(24)

        form.addRow("类型", self.deployment_side_combo)
        form.addRow("坐标", coordinate_row)
        form.addRow("驾驶员", self.deployment_character_combo)
        form.addRow("机体", self.deployment_unit_combo)
        form.addRow("等级", self.deployment_level_editor)
        form.addRow("行动", self.deployment_action_combo)
        form.addRow("我方队伍槽", self.deployment_roster_combo)
        root.addLayout(form)

        self.deployment_editor_status = QLabel()
        self.deployment_editor_status.setObjectName("hintText")
        self.deployment_editor_status.setWordWrap(True)
        root.addWidget(self.deployment_editor_status)
        self.deployment_capacity_button = QPushButton("容量不足时打开容量规划…")
        self.deployment_capacity_button.clicked.connect(self._open_capacity_planner)
        root.addWidget(
            self.deployment_capacity_button,
            0,
            Qt.AlignmentFlag.AlignRight,
        )
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Save
            | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.button(QDialogButtonBox.StandardButton.Save).setText("保存配置")
        buttons.button(QDialogButtonBox.StandardButton.Cancel).setText("取消")
        buttons.accepted.connect(self._save_deployment_cell_editor)
        buttons.rejected.connect(self.deployment_cell_dialog.reject)
        root.addWidget(buttons)
        self.deployment_side_combo.currentIndexChanged.connect(
            self._deployment_editor_side_changed
        )

    def _refresh_deployment_editor_choices(self) -> None:
        for combo, provider in (
            (self.deployment_character_combo, self._character_choice_label),
            (self.deployment_unit_combo, self._unit_choice_label),
        ):
            selected = combo.currentData()
            combo.blockSignals(True)
            combo.clear()
            for record_id in range(256):
                combo.addItem(provider(record_id), record_id)
            combo.setCurrentIndex(combo.findData(selected if selected is not None else 0))
            combo.blockSignals(False)

        selected_slot = self.deployment_roster_combo.currentData()
        self.deployment_roster_combo.clear()
        for slot in range(256):
            self.deployment_roster_combo.addItem(
                self._player_slot_choice_label(slot), slot
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
            widget.setEnabled(not player)
        self.deployment_roster_combo.setEnabled(player)
        self.deployment_editor_status.setText(
            "我方记录保存队伍槽和行动；驾驶员、机体由当前关卡的队伍状态自动解析。"
            if player
            else "敌军/客军记录保存驾驶员、机体、等级和行动；全部选项按原始字节写回。"
        )
        self.deployment_editor_status.setStyleSheet("")

    def _open_deployment_cell_editor(
        self,
        side: str,
        x: int,
        y: int,
        row: int | None = None,
    ) -> None:
        self._refresh_deployment_editor_choices()
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
            ) if values else (0, 1, 1, 0)
            self.deployment_character_combo.setCurrentIndex(
                self.deployment_character_combo.findData(pilot_id)
            )
            self.deployment_unit_combo.setCurrentIndex(
                self.deployment_unit_combo.findData(unit_id)
            )
            self.deployment_level_editor.setValue(level)
        self.deployment_action_combo.setCurrentIndex(
            self.deployment_action_combo.findData(action_id)
        )
        self._deployment_editor_side_changed()
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
            self.deployment_level_editor.value(),
            action_id,
        )

    def _save_deployment_cell_editor(self) -> None:
        side = str(self.deployment_side_combo.currentData())
        target = self._object_table(side)
        values = self._deployment_editor_values(side)
        source = self._deployment_edit_source
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
            source_table.removeRow(source[1])
            source_table.values_changed.emit()
        self._deployment_edit_source = (side, row)
        self._select_object(side, row)
        self.deployment_cell_dialog.accept()

    def _ensure_deployment_growth(self, extra_bytes: int) -> bool:
        """Keep fixed-layout ROMs from ending with an unsavable deployment draft."""

        if (
            extra_bytes <= 0
            or self.project is None
            or self.project.expansion_plan is not None
            or self.current_map_id is None
            or self.current_map_id >= self.project.scenario_count
        ):
            return True
        layout = self._staged_layout()
        used = len(self.project.scenario_layout_codec.encode(layout))
        capacity = self.project.scenario_layout_codec.capacities[self.current_map_id]
        if used + extra_bytes <= capacity:
            return True
        message = (
            f"本关部署固定槽为 {capacity} 字节，当前已用 {used} 字节；"
            f"新增记录还需要 {extra_bytes} 字节。请先打开“容量规划”并应用地图扩展容量，"
            "再保存这条配置。"
        )
        self.deployment_editor_status.setText(message)
        self.deployment_editor_status.setStyleSheet("color:#b42318; font-weight:600;")
        self.show_error(ValueError(message))
        return False

    def _toggle_icon_preview(self, expanded: bool) -> None:
        self.icon_preview_group.setVisible(expanded)
        self.icon_preview_toggle.setText(
            "收起机体图标库（只读）"
            if expanded
            else "展开机体图标库（只读）"
        )
        if expanded:
            self._refresh_icon_sheets()

    def _toggle_deployment_list(self, expanded: bool) -> None:
        self.deployment_objects.setVisible(expanded)
        self.deployment_list_toggle.setText(
            "收起部署明细列表" if expanded else "展开部署明细列表"
        )

    def _show_trigger_advanced(self) -> None:
        self.trigger_dialog.show()
        self.trigger_dialog.raise_()
        self.trigger_dialog.activateWindow()

    def _trigger_kind_changed(self, _checked: bool = False) -> None:
        is_shop = self.trigger_shop_radio.isChecked()
        self.trigger_shop_combo.setEnabled(is_shop)
        self.trigger_event_combo.setEnabled(not is_shop)

    def _refresh_trigger_character_choices(self) -> None:
        selected = self.trigger_character_combo.currentData()
        self.trigger_character_combo.blockSignals(True)
        self.trigger_character_combo.clear()
        for character_id in range(256):
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
        selector.setCurrentIndex(selector.findData(event_id))
        self.trigger_delete_button.setVisible(row is not None)
        self.trigger_delete_button.setText(
            "删除商店" if shop else "删除地图事件"
        )
        self.trigger_cell_dialog.setWindowTitle(
            "商店设置" if shop else "地图事件设置"
        )
        self._trigger_kind_changed()
        self.trigger_cell_dialog.show()
        self.trigger_cell_dialog.raise_()
        self.trigger_cell_dialog.activateWindow()

    def _save_trigger_cell_editor(self) -> None:
        event_id = int(
            self.trigger_shop_combo.currentData()
            if self.trigger_shop_radio.isChecked()
            else self.trigger_event_combo.currentData()
        )
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
        if not 0 <= row < self.trigger_table.rowCount():
            return
        self.trigger_table.removeRow(row)
        self.trigger_table.values_changed.emit()
        self.canvas.selected_overlay = None

    def _delete_edited_trigger(self) -> None:
        if self._trigger_edit_row is not None:
            self._remove_trigger_row(self._trigger_edit_row)
        self._trigger_edit_row = None
        self.trigger_cell_dialog.accept()

    def _show_trigger_context_menu(
        self, x: int, y: int, global_position: QPoint
    ) -> None:
        if self.editor_tabs.currentIndex() != 2 or not self.trigger_table.isEnabled():
            return
        rows = [
            row
            for row, values in enumerate(self.trigger_table.rows())
            if values[:2] == (x, y)
        ]
        menu = QMenu(self.canvas)
        self._trigger_context_menu = menu
        coordinate = menu.addAction(f"坐标 X:{x}  Y:{y}")
        coordinate.setEnabled(False)
        menu.addSeparator()
        if len(rows) == 1:
            row = rows[0]
            event_id = self.trigger_table.rows()[row][3]
            edit = menu.addAction(
                "编辑商店" if event_id >= 0xF0 else "编辑地图事件"
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
        if len(rows) == 1:
            row = rows[0]
            delete = menu.addAction("删除地图事件")
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
            player = self._player_slot_state().get(values[2])
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
        table = self._object_table(side)
        if not 0 <= row < table.rowCount():
            return
        table.removeRow(row)
        table.values_changed.emit()
        self.canvas.selected_overlay = None

    def _show_deployment_context_menu(
        self, x: int, y: int, global_position: QPoint
    ) -> None:
        """Legacy-style map context menu for initial configurations."""

        if self.editor_tabs.currentIndex() != 1:
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
        coordinate = menu.addAction(f"坐标 X:{x}  Y:{y}")
        coordinate.setEnabled(False)
        menu.addSeparator()

        if len(records) == 1:
            side, row, _values = records[0]
            edit = menu.addAction(f"更改{side}军初始配置")
            edit.triggered.connect(
                lambda _checked=False, side=side, row=row:
                self._open_deployment_record(side, row)
            )
        elif records:
            edit_menu = menu.addMenu("编辑此格初始配置")
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

        add_menu = menu.addMenu("在此格添加配置")
        for side, label in (("敌", "敌军"), ("客", "客军"), ("我", "我方出击位")):
            table = self._object_table(side)
            action = add_menu.addAction(label)
            action.setEnabled(
                table.max_rows is None or table.rowCount() < table.max_rows
            )
            action.triggered.connect(
                lambda _checked=False, side=side: self._add_deployment_at(
                    side, x, y
                )
            )

        menu.addSeparator()
        if len(records) == 1:
            side, row, _values = records[0]
            database = menu.addAction("更改属性")
            database.triggered.connect(
                lambda _checked=False, side=side, row=row:
                self._open_deployment_database_record(side, row)
            )
            experience = menu.addAction("击落经验计算器")
            experience.triggered.connect(
                lambda _checked=False, side=side, row=row:
                self._open_deployment_experience(side, row)
            )
            attributes = menu.addAction("加到属性计算器")
            attributes.triggered.connect(
                lambda _checked=False, side=side, row=row:
                self._open_deployment_attributes(side, row)
            )
            copy = menu.addAction("复制配置")
            copy.triggered.connect(
                lambda _checked=False, side=side, row=row:
                self._copy_deployment_record(side, row)
            )
            cut = menu.addAction("剪切配置")
            cut.triggered.connect(
                lambda _checked=False, side=side, row=row:
                self._copy_deployment_record(side, row, cut=True)
            )
        else:
            database = menu.addAction("更改属性")
            database.setEnabled(False)
            experience = menu.addAction("击落经验计算器")
            experience.setEnabled(False)
            attributes = menu.addAction("加到属性计算器")
            attributes.setEnabled(False)
            copy = menu.addAction("复制配置")
            copy.setEnabled(False)
            cut = menu.addAction("剪切配置")
            cut.setEnabled(False)
        paste = menu.addAction("粘贴配置")
        paste.setEnabled(self._deployment_clipboard is not None)
        paste.triggered.connect(
            lambda _checked=False: self._paste_deployment_at(x, y)
        )

        if len(records) == 1:
            side, row, _values = records[0]
            delete = menu.addAction(f"删除{side}军初始配置")
            delete.triggered.connect(
                lambda _checked=False, side=side, row=row:
                self._remove_deployment_row(side, row)
            )
        elif records:
            delete_menu = menu.addMenu("删除此格初始配置")
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
            delete = menu.addAction("删除初始配置")
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
        elif not table.duplicate_selected():
            self.show_error(ValueError(f"此列表最多允许 {table.max_rows} 条记录。"))

    def _paste_deployment(self, table: ByteEntryTable) -> None:
        if table.clipboard_row is None:
            self.show_error(ValueError("请先在此列表复制一条记录。"))
        elif table.max_rows is not None and table.rowCount() >= table.max_rows:
            self.show_error(ValueError(f"此列表最多允许 {table.max_rows} 条记录。"))
        elif not self._ensure_deployment_growth(table.columnCount()):
            return
        elif not table.paste_row():
            self.show_error(ValueError(f"此列表最多允许 {table.max_rows} 条记录。"))

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
        """Resolve the ROM-defined player party at the current chapter start.

        The six-entry initial table is only the starting state.  Chapter event
        opcodes $6F/$6E add and remove runtime party slots, while $4D/$4E can
        replace their pilot or machine.  Replaying those records up to (but
        not including) the selected chapter prevents later real machines from
        falling back to numbered circles.
        """

        if self.project is None or self.current_map_id is None:
            return {}
        roster = tuple(self.project.get_initial_roster())
        codec = self.project.chapter_event_codec
        event_bytes = b""
        if codec is not None:
            start = codec.data_address_to_file_offset(codec.spec.data_start)
            size = codec.spec.data_end - codec.spec.data_start
            event_bytes = bytes(self.project.working[start : start + size])
        cache_key = (id(self.project), roster, event_bytes)
        if cache_key != self._player_slot_cache_key:
            slots = {index: pair for index, pair in enumerate(roster)}
            snapshots: list[dict[int, tuple[int, int]]] = []
            instructions = (
                self.project.chapter_event_instructions()
                if codec is not None
                else ()
            )
            for scenario_id in range(self.project.scenario_count):
                snapshots.append(dict(slots))
                for phase in range(3):
                    for instruction in instructions:
                        if not any(
                            context.scenario_id == scenario_id
                            and context.phase == phase
                            for context in instruction.contexts
                        ):
                            continue
                        parameters = instruction.parameters
                        if instruction.opcode == 0x6F and len(parameters) >= 3:
                            slots[parameters[0]] = (parameters[1], parameters[2])
                        elif instruction.opcode == 0x6E and parameters:
                            slots.pop(parameters[0], None)
                        elif instruction.opcode == 0x4D and len(parameters) >= 3:
                            target, pilot_id, unit_id = parameters[:3]
                            for slot, (current_pilot, _unit) in tuple(slots.items()):
                                if current_pilot == target:
                                    slots[slot] = (pilot_id, unit_id)
                        elif instruction.opcode == 0x4E and len(parameters) >= 2:
                            target, unit_id = parameters[:2]
                            for slot, (pilot_id, _unit) in tuple(slots.items()):
                                if pilot_id == target:
                                    slots[slot] = (pilot_id, unit_id)
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
                item.setToolTip(
                    description
                    + "\n单击联动定位；双击或在地图上右键打开编辑；图标可拖动。"
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
                "地图显示ROM四图块机体图标；右键可编辑、新增或删除，左键拖动可改坐标。"
            )
        count = self.trigger_table.rowCount()
        self.trigger_summary.setText(
            f"本关共 {count} 条地图触发记录。紫色=事件，绿色=商店；在地图上右键添加、编辑或删除。"
            if count else "本关ROM中没有地图事件或商店记录。在右侧地图任意格右键即可添加。"
        )

    def _add_deployment(
        self,
        table: ByteEntryTable,
        default_values: tuple[int, ...] | None = None,
    ) -> None:
        values = list(default_values or (0 for _ in table.headers))
        if len(values) != len(table.headers):
            raise ValueError("新增记录的默认字节数与表列数不一致。")
        if self.hovered_cell is not None:
            values[0], values[1] = self.hovered_cell
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
        table.set_row_coordinates(row, *self.hovered_cell)

    def _canvas_coordinate_changed(self, x: int, y: int) -> None:
        self.hovered_cell = (x, y)
        self.position_label.setText(f"X坐标：{x}")
        self.y_position_label.setText(f"Y坐标：{y}")

    def _overlay_moved(self, side: str, row: int, x: int, y: int) -> None:
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

    def _trigger_character_label(self, character_id: int) -> str:
        if character_id == 0xFF:
            return "任何人物 · $FF"
        if self.project is not None and character_id < self.project.profile.character_name_count:
            return f"{self.project.character_display_name(character_id)} · ${character_id:02X}"
        return f"无效人物ID · ${character_id:02X}"

    def _deployment_description(self, side: str, values: tuple[int, ...]) -> str:
        """Return a reference-style, ROM-backed battlefield tooltip."""

        if self.project is None:
            return "尚未载入ROM"
        cache_key = (self.current_map_id or 0, side, values)
        cached = self._deployment_description_cache.get(cache_key)
        if cached is not None:
            return cached
        action_id = values[3] if side == "我" else values[5]
        action = self._action_choice_label(action_id)
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
                growth_codec = LegacyGrowthCodec(bytes(self.project.working))

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
            for slot, weapon_id in enumerate(weapon_ids, start=1):
                if not 0 < weapon_id < self.project.weapon_count:
                    continue
                weapon = self.project.weapon_codec.decode_record(
                    weapon_id, bytes(self.project.working)
                )
                weapon_skill, _distance = weapon_extra_values(
                    self.project, weapon_id
                )
                weapon_description = self._weapon_description_cache.get(weapon_id)
                if weapon_description is None:
                    weapon_description = (
                        f"{self.project.weapon_display_name(weapon_id)} · ${weapon_id:02X} "
                        f"射程 {weapon.get('max_range')} · 命中 {weapon.get('hit')} · "
                        f"特技 {weapon_skill} · "
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
        if event_id >= 0xF0:
            return f"商店 {event_id & 0x0F} · ${event_id:02X}"
        return f"地图事件 ${event_id:02X}"

    def refresh(self) -> None:
        previous = self.current_map_id
        self._icon_sheet_cache.clear()
        self._map_icon_cache.clear()
        self._tileset_image_cache.clear()
        self._unit_choice_cache.clear()
        self._character_choice_cache.clear()
        self._deployment_description_cache.clear()
        self._weapon_description_cache.clear()
        self._trigger_payload_cache = None
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
        self._filter_maps(self.search.text())
        if self.map_list.count():
            row = min(previous or 0, self.map_list.count() - 1)
            self.map_list.blockSignals(True)
            self.map_list.setCurrentRow(row)
            self.map_list.blockSignals(False)
            self._map_selected(self.map_list.currentItem(), None)

    def _filter_maps(self, text: str) -> None:
        query = text.strip().lower()
        visible_count = 0
        for row in range(self.map_list.count()):
            item = self.map_list.item(row)
            map_id = int(item.data(Qt.ItemDataRole.UserRole))
            visible = not (
                bool(query)
                and query not in item.text().lower()
                and query not in (str(map_id), f"{map_id:02x}")
            )
            item.setHidden(not visible)
            visible_count += int(visible)
        self.map_count_label.setText(f"{visible_count} 个地图")

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
        self.title_preview.setPixmap(
            render_map_title(self.project, dc_map_label(self.current_map_id))
        )
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

    def _update_brush_previews(self) -> None:
        images = self.canvas.tile_images
        for label, tile in (
            (self.left_brush_preview, self.canvas.selected_tile),
            (self.right_brush_preview, self.canvas.right_selected_tile),
        ):
            if 0 <= tile < len(images):
                pixmap = QPixmap.fromImage(images[tile]).scaled(
                    56,
                    56,
                    Qt.AspectRatioMode.KeepAspectRatio,
                    Qt.TransformationMode.FastTransformation,
                )
                label.setPixmap(pixmap)
                label.setToolTip(f"位图{tile:X}")
            else:
                label.setPixmap(QPixmap())
                label.setText(f"位图{tile:X}")

    def _open_tile_attributes(self) -> None:
        key = str(self.tileset.currentData() or "—")
        self._tile_attribute_dialog = TileAttributeDialog(
            self.project,
            key,
            self.canvas.tile_images,
            self,
        )
        self._tile_attribute_dialog.accepted.connect(
            lambda: self._tile_attributes_applied(key)
        )
        self._tile_attribute_dialog.show()

    def _tile_attributes_applied(self, key: str) -> None:
        self._refresh_tile_visuals()
        self.project_changed.emit(f"已更新图库 {key} 图块属性")

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
                    192,
                    48,
                    Qt.AspectRatioMode.KeepAspectRatio,
                    Qt.TransformationMode.FastTransformation,
                )
            )

    def _editor_mode_changed(self, _index: int) -> None:
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
                button.setIcon(
                    QIcon(
                        QPixmap.fromImage(image).scaled(
                            40,
                            40,
                            Qt.AspectRatioMode.IgnoreAspectRatio,
                            Qt.TransformationMode.FastTransformation,
                        )
                    )
                )
                button.setStyleSheet(
                    "QPushButton { background: #f8fbfd; color: #13293a; }"
                    "QPushButton:checked { border: 3px solid #082f49; }"
                )
        self._update_brush_previews()
        bank = TILESET_BANKS[key]
        bank_offset = self.project.chr_codec.offset + bank * 0x400
        self.tileset.setItemText(
            self.tileset.currentIndex(),
            f"[{bank:02X}]{bank:03d}: {bank_offset:06X}",
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
        cell_size = min(
            24,
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
        self.width_display.setValue(new_width)
        self.height_display.setValue(new_height)
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
        self.canvas.deployment_edit_enabled = mode == 1
        self.canvas.trigger_edit_enabled = mode == 2
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
        if self._trigger_payload_cache is None:
            self._trigger_payload_cache = tuple(
                codec.encode_entries(layout.entries)
                for layout in codec.layouts(self.project.working)
            )
        payloads = list(self._trigger_payload_cache)
        payloads[self.current_map_id] = codec.encode_entries(entries)
        used = sum(len(payload) for payload in set(payloads))
        if used > codec.pool_capacity:
            raise ValueError(
                f"地图触发器压缩后需要 {used} 字节，"
                f"托管池只有 {codec.pool_capacity} 字节。"
            )
        return used

    @property
    def has_pending_draft(self) -> bool:
        """Return whether the map page owns edits not yet in the project buffer."""

        signature = self._draft_signature()
        return signature is not None and signature != self._loaded_draft_signature

    def _validate_pending_draft(self) -> None:
        if self.project is None or self.current_map_id is None:
            return
        encoded = self.project.map_codec.encode(
            self.staged_width,
            self.staged_height,
            tuple(self.staged_tiles),
        )
        expanded = self.project.expansion_plan is not None
        if (
            not expanded
            and len(encoded)
            > self.project.map_codec.capacities[self.current_map_id]
        ):
            raise ValueError("地图RLE数据超出当前记录的固定容量。")

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
            if (
                not expanded
                and len(scenario_encoded)
                > self.project.scenario_layout_codec.capacities[self.current_map_id]
            ):
                raise ValueError("部署数据超出当前记录的固定容量。")

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
                if self.current_map_id < self.project.scenario_count:
                    self.project.set_scenario_layout(self._staged_layout())
                if (
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
            self.pending_state.setText("选择地图后可编辑。")
            self.apply_button.setEnabled(False)
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
            expanded = self.project.expansion_plan is not None
            capacity = self.project.map_codec.capacities[self.current_map_id]
            size_ok = expanded or len(encoded) <= capacity
            details = (
                f"地图RLE {len(encoded)} B"
                if expanded
                else f"地图RLE {len(encoded)} / {capacity} B"
            )
            staged_layout = None
            staged_triggers = None
            current_map = self.project.get_map(self.current_map_id)
            changed = (
                self.staged_width != current_map.width
                or self.staged_height != current_map.height
                or tuple(self.staged_tiles) != current_map.tiles
            )
            if self.current_map_id < self.project.scenario_count:
                staged_layout = self._staged_layout()
                self.project.scenario_layout_codec.validate_layout(
                    staged_layout, self.staged_width, self.staged_height
                )
                scenario_encoded = self.project.scenario_layout_codec.encode(staged_layout)
                scenario_capacity = self.project.scenario_layout_codec.capacities[
                    self.current_map_id
                ]
                if expanded:
                    details += f" · 部署 {len(scenario_encoded)} B"
                else:
                    size_ok = size_ok and len(scenario_encoded) <= scenario_capacity
                    details += f" · 部署 {len(scenario_encoded)} / {scenario_capacity} B"
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
                if expanded:
                    details += f" · 事件/商店 {len(staged_triggers)} 条"
                else:
                    trigger_used = self._trigger_storage_used_after(staged_triggers)
                    trigger_capacity = self.project.map_trigger_codec.pool_capacity
                    details += (
                        f" · 事件/商店 {len(staged_triggers)} 条 · "
                        f"全局池 {trigger_used} / {trigger_capacity} B"
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
                details += f" · 地图共享池 {used} / {shared_capacity} B"
            status = (
                "可保存（自动重排）"
                if expanded and size_ok
                else ("可保存" if size_ok else "超出固定容量")
            )
            self.size_label.setText(
                f"地图 ${self.current_map_id:02X} · {dc_map_label(self.current_map_id)} · "
                f"{details} · {status}"
            )
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
        except (ValueError, TypeError) as error:
            self.size_label.setText(f"当前输入无法保存：{error}")
            self.pending_state.setText("● 请修正输入或容量问题")
            self.pending_state.setProperty("pending", True)
            self.apply_button.setEnabled(self.has_pending_draft)
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
                if self.current_map_id < self.project.scenario_count:
                    self.project.reset_scenario_layout(self.current_map_id)
                if (
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
