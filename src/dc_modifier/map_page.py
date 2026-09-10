from __future__ import annotations

from PySide6.QtCore import QPoint, QRect, QSize, Qt, Signal
from PySide6.QtGui import QColor, QFont, QIcon, QImage, QMouseEvent, QPainter, QPen, QPixmap
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
    QPushButton,
    QScrollArea,
    QSpinBox,
    QSplitter,
    QTableWidget,
    QTableWidgetItem,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from fc_editor.dc_text import dc_map_label, default_dc_text_table
from fc_editor.codecs.map_trigger import MapTrigger

from fc_editor.models import PlayerPlacement, ScenarioEntity, ScenarioLayout

from .pages import ProjectPage
from .map_tiles import TILESET_BANKS, campaign_tileset_key, render_tileset


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


ICON_PALETTE = (
    QColor("#000000"),
    QColor("#173a83"),
    QColor("#38a9ef"),
    QColor("#ffffff"),
)


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
    """Render one verified active 1 KiB CHR bank as 32 legacy map icons."""

    image = QImage(256, 32, QImage.Format.Format_RGB32)
    image.fill(ICON_PALETTE[0])
    first_tile = bank * 64
    for icon in range(32):
        column = icon % 16
        row = icon // 16
        for half in range(2):
            pixels = project.chr_tile_pixels(first_tile + icon * 2 + half)
            origin_x = column * 16 + 4
            origin_y = row * 16 + half * 8
            for y in range(8):
                for x in range(8):
                    image.setPixelColor(
                        origin_x + x,
                        origin_y + y,
                        ICON_PALETTE[pixels[y * 8 + x]],
                    )
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


def render_map_title(project, title: str, *, scale: int = 4) -> QPixmap:
    """Render a readable chapter title using verified token/address mappings."""

    advance = 12 * scale
    margin = 8
    pixmap = QPixmap(max(1, margin * 2 + len(title) * advance), 12 * scale + margin)
    pixmap.fill(QColor("#000000"))
    painter = QPainter(pixmap)
    painter.setPen(QColor("#d8d8d8"))
    font = QFont("SimSun")
    font.setPixelSize(10 * scale)
    font.setStyleStrategy(QFont.StyleStrategy.NoAntialias)
    painter.setFont(font)
    table = default_dc_text_table()
    for character_index, character in enumerate(title):
        try:
            token = table.encode(character)
        except ValueError:
            continue
        offset = _glyph_file_offset(token)
        if offset is None or offset + 18 > len(project.working):
            continue
        origin_x = margin + character_index * advance
        painter.drawText(
            QRect(origin_x, 0, advance, pixmap.height()),
            Qt.AlignmentFlag.AlignCenter,
            character,
        )
    painter.end()
    return pixmap


class TileAttributeDialog(QDialog):
    """Safe compatibility view for the legacy unverified tile-attribute dialog."""

    def __init__(self, tileset_key: str, images: tuple[QImage, ...], parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("编辑图块属性")
        self.resize(520, 500)
        root = QVBoxLayout(self)
        notice = QLabel(
            "兼容查看模式：当前ROM的图块属性写入格式尚未完成差分验证，"
            "这里显示活动CHR中的真实图块，不会猜测写入地址。"
        )
        notice.setWordWrap(True)
        root.addWidget(notice)
        table = QTableWidget(16, 3)
        table.setHorizontalHeaderLabels(("位图", "当前图库", "状态"))
        table.verticalHeader().setVisible(False)
        table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
        table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        for tile in range(16):
            tile_item = QTableWidgetItem(f"位图{tile:X}")
            if tile < len(images):
                tile_item.setIcon(QIcon(QPixmap.fromImage(images[tile])))
            table.setItem(tile, 0, tile_item)
            table.setItem(tile, 1, QTableWidgetItem(f"图库 {tileset_key}"))
            table.setItem(tile, 2, QTableWidgetItem("只读兼容视图"))
        root.addWidget(table, 1)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        buttons.rejected.connect(self.close)
        root.addWidget(buttons)


class MapCanvas(QWidget):
    tile_painted = Signal(int, int, int)
    tile_picked = Signal(int)
    right_tile_picked = Signal(int)
    coordinate_changed = Signal(int, int)
    overlay_moved = Signal(str, int, int, int)

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
        for side, x, y, label, _row in self.overlays:
            if not 0 <= x < self.map_width or not 0 <= y < self.map_height:
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
            if self.cell_size >= 20:
                painter.drawText(rect, Qt.AlignmentFlag.AlignCenter, label)

    def _cell_at(self, position: QPoint) -> tuple[int, int] | None:
        x = position.x() // self.cell_size
        y = position.y() // self.cell_size
        if 0 <= x < self.map_width and 0 <= y < self.map_height:
            return x, y
        return None

    def _paint_at(self, position: QPoint, tile: int) -> None:
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
            else:
                self._paint_at(event.position().toPoint(), self.selected_tile)
        elif event.button() == Qt.MouseButton.RightButton:
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
        if event.buttons() & Qt.MouseButton.LeftButton and self.dragged_overlay is None:
            self._paint_at(event.position().toPoint(), self.selected_tile)
        elif event.buttons() & Qt.MouseButton.RightButton:
            self._paint_at(event.position().toPoint(), self.right_selected_tile)

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:
        if event.button() == Qt.MouseButton.LeftButton and self.dragged_overlay is not None:
            cell = self._cell_at(event.position().toPoint())
            side, row = self.dragged_overlay
            self.dragged_overlay = None
            if cell is not None:
                self.overlay_moved.emit(side, row, cell[0], cell[1])


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
        self.setRowCount(0)
        for values in rows:
            self.add_row(values)

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
                for item_value in range(256):
                    editor.addItem(provider(item_value), item_value)
                editor.setCurrentIndex(editor.findData(value))
                editor.currentIndexChanged.connect(self.values_changed)
            else:
                editor = QSpinBox()
                editor.setRange(0, 255)
                editor.setDisplayIntegerBase(16 if column >= 2 else 10)
                editor.setPrefix("$" if column >= 2 else "")
                editor.setValue(value)
                editor.valueChanged.connect(self.values_changed)
            self.setCellWidget(row, column, editor)
        self.setCurrentCell(row, 0)
        self.values_changed.emit()
        return True

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
        for column, value in ((0, x), (1, y)):
            editor = self.cellWidget(row, column)
            if isinstance(editor, QSpinBox):
                editor.setValue(value)
        self.setCurrentCell(row, 0)
        self.values_changed.emit()


class MapPage(ProjectPage):
    draft_state_changed = Signal()

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
        outer = QVBoxLayout(self)
        outer.setContentsMargins(8, 8, 8, 8)
        self.main_splitter = QSplitter(Qt.Orientation.Horizontal)
        self.main_splitter.setObjectName("mapMainSplitter")
        self.main_splitter.setChildrenCollapsible(False)

        # Match the original SRW2 editor: editing tabs above the chapter list
        # on the left, with the complete battlefield occupying the right side.
        self.navigator = QWidget()
        self.navigator.setObjectName("mapLeftPane")
        self.navigator.setMinimumWidth(390)
        self.navigator.setMaximumWidth(490)
        inspector_layout = QVBoxLayout(self.navigator)
        inspector_layout.setContentsMargins(0, 0, 8, 0)

        self.editor_tabs = QTabWidget()
        self.editor_tabs.setObjectName("subTabs")
        tile_tab = QWidget()
        tile_layout = QVBoxLayout(tile_tab)
        tile_layout.setContentsMargins(8, 8, 8, 8)

        brush_group = QGroupBox("地图图块设置")
        brush_group.setMinimumHeight(285)
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
            button.setMinimumSize(42, 42)
            button.setIconSize(QSize(40, 40))
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
        self.title_preview.setMinimumHeight(72)
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
        icon_group = QGroupBox("机体图标")
        icon_group_layout = QVBoxLayout(icon_group)
        self.icon_bank_selectors: list[QComboBox] = []
        self.icon_sheet_labels: list[QLabel] = []
        for slot, default_bank in enumerate((0x34, 0x35, 0x36), start=1):
            address_row = QHBoxLayout()
            address_row.addWidget(QLabel(f"图标地址{slot}"))
            selector = QComboBox()
            selector.setMaxVisibleItems(20)
            selector.setToolTip(
                "只读兼容选择：切换活动CHR图标预览，不改写关卡图标绑定。"
            )
            for bank in range(0x100):
                selector.addItem(f"[{bank:02X}]{bank:03d}", bank)
            selector.setCurrentIndex(selector.findData(default_bank))
            selector.currentIndexChanged.connect(self._refresh_icon_sheets)
            address_row.addWidget(selector, 1)
            icon_group_layout.addLayout(address_row)
            preview = QLabel("尚未载入 ROM")
            preview.setObjectName("legacyIconSheet")
            preview.setAlignment(Qt.AlignmentFlag.AlignCenter)
            preview.setFixedHeight(64)
            preview.setStyleSheet("background: #000000; border: 1px solid #4d555c;")
            icon_group_layout.addWidget(preview)
            self.icon_bank_selectors.append(selector)
            self.icon_sheet_labels.append(preview)
        icon_group.setMinimumHeight(420)
        initial_layout.addWidget(icon_group)
        self.open_deployment_button = QPushButton("高级部署编辑…")
        self.open_deployment_button.setToolTip(
            "扩展功能；图标地址选择本身仍为只读兼容预览，不会猜写绑定。"
        )
        self.open_deployment_button.clicked.connect(self._show_deployment_advanced)
        initial_layout.addWidget(
            self.open_deployment_button,
            0,
            Qt.AlignmentFlag.AlignRight,
        )
        initial_layout.addStretch()

        self.deployment_dialog = QDialog(self)
        self.deployment_dialog.setWindowTitle("高级部署编辑")
        self.deployment_dialog.setModal(True)
        self.deployment_dialog.resize(1020, 650)
        deployment_layout = QVBoxLayout(self.deployment_dialog)
        deployment_hint = QLabel(
            "扩展功能：编辑敌军、客军和我方出击位；机体与人物均显示真实名称。"
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
            ("X", "Y", "机体", "驾驶员", "等级", "标志"),
            {2: self._unit_choice_label, 3: self._character_choice_label},
            max_rows=18,
        )
        self.deployment_tabs.addTab(enemy_host, "敌军")
        guest_host = QWidget()
        guest_layout = QVBoxLayout(guest_host)
        self.guest_table = self._deployment_group(
            guest_layout,
            "客军",
            ("X", "Y", "机体", "驾驶员", "等级", "标志"),
            {2: self._unit_choice_label, 3: self._character_choice_label},
            max_rows=3,
        )
        self.deployment_tabs.addTab(guest_host, "客军")
        player_host = QWidget()
        player_layout = QVBoxLayout(player_host)
        self.player_table = self._deployment_group(
            player_layout,
            "我方出击位",
            ("X", "Y", "名单位", "标志"),
            max_rows=11,
        )
        self.deployment_tabs.addTab(player_host, "我方出击位")
        deployment_layout.addWidget(self.deployment_tabs, 1)
        deployment_close = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        deployment_close.rejected.connect(self.deployment_dialog.close)
        deployment_layout.addWidget(deployment_close)
        self.editor_tabs.addTab(initial_tab, "初始配置")

        trigger_tab = QWidget()
        trigger_layout = QVBoxLayout(trigger_tab)
        trigger_layout.setContentsMargins(8, 8, 8, 8)
        trigger_layout.addStretch()
        self.open_trigger_button = QPushButton("高级事件编辑…")
        self.open_trigger_button.clicked.connect(self._show_trigger_advanced)
        trigger_layout.addWidget(
            self.open_trigger_button,
            0,
            Qt.AlignmentFlag.AlignRight,
        )

        self.trigger_dialog = QDialog(self)
        self.trigger_dialog.setWindowTitle("高级地图事件与商店编辑")
        self.trigger_dialog.setModal(True)
        self.trigger_dialog.resize(900, 580)
        trigger_dialog_layout = QVBoxLayout(self.trigger_dialog)
        trigger_hint = QLabel(
            "编辑踩点触发的剧情事件或商店。限定人物为 $FF 时任何人物都可触发；"
            "事件号 $F0—$FF 表示商店 0—15。地图上的紫色“事”和绿色“店”圆点可拖动。"
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
        trigger_close.rejected.connect(self.trigger_dialog.close)
        trigger_dialog_layout.addWidget(trigger_close)
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
        self.search.hide()
        self.map_count_label.hide()
        self.map_list = QListWidget()
        self.map_list.setAlternatingRowColors(True)
        self.map_list.setUniformItemSizes(True)
        self.map_list.currentItemChanged.connect(self._map_selected)
        chapter_layout.addWidget(self.map_list)
        inspector_layout.addWidget(self.editor_tabs, 3)
        inspector_layout.addWidget(self.chapter_group, 2)
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
        self.map_scroll = MapScrollArea()
        self.map_scroll.setObjectName("mapScrollArea")
        self.map_scroll.setWidget(self.canvas)
        self.map_scroll.setWidgetResizable(False)
        self.map_scroll.setHorizontalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAlwaysOff
        )
        self.map_scroll.setVerticalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAlwaysOff
        )
        self.map_scroll.setAlignment(
            Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignTop
        )
        self.map_scroll.viewport_resized.connect(self._fit_map_to_viewport)
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
        zoom_row = QHBoxLayout()
        zoom_row.addWidget(self.fit_view)
        zoom_row.addWidget(QLabel("缩放"))
        zoom_row.addWidget(self.zoom)
        zoom_row.addStretch()
        display_layout.addLayout(zoom_row)
        display_layout.addWidget(self.tileset_meta)
        display_layout.addWidget(self.brush_hint)
        root.addWidget(display_group)

        status_group = QGroupBox("草稿状态")
        status_layout = QVBoxLayout(status_group)
        self.size_label.setWordWrap(True)
        self.pending_state.setWordWrap(True)
        status_layout.addWidget(self.size_label)
        status_layout.addWidget(self.pending_state)
        root.addWidget(status_group)
        root.addStretch()

        buttons = QHBoxLayout()
        buttons.addWidget(self.apply_button)
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

    def _show_deployment_advanced(self) -> None:
        self.deployment_dialog.show()
        self.deployment_dialog.raise_()
        self.deployment_dialog.activateWindow()

    def _show_trigger_advanced(self) -> None:
        self.trigger_dialog.show()
        self.trigger_dialog.raise_()
        self.trigger_dialog.activateWindow()

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
        duplicate_button.clicked.connect(table.duplicate_selected)
        copy_button = QPushButton("复制")
        copy_button.clicked.connect(table.copy_selected)
        paste_button = QPushButton("粘贴")
        paste_button.clicked.connect(table.paste_row)
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
        if unit_id == 0:
            label = "无机体/特殊值"
        elif self.project is not None and unit_id < self.project.unit_count:
            label = self.project.unit_display_name(unit_id)
        else:
            label = "超出已验证机体表"
        return f"{label} · ${unit_id:02X}"

    def _character_choice_label(self, character_id: int) -> str:
        label = (
            self.project.character_display_name(character_id)
            if self.project is not None
            else "尚未载入 ROM"
        )
        return f"{label} · ${character_id:02X}"

    def _trigger_character_label(self, character_id: int) -> str:
        if character_id == 0xFF:
            return "任何人物 · $FF"
        if self.project is not None and character_id < self.project.profile.character_name_count:
            return f"{self.project.character_display_name(character_id)} · ${character_id:02X}"
        return f"无效人物ID · ${character_id:02X}"

    @staticmethod
    def _trigger_event_label(event_id: int) -> str:
        if event_id >= 0xF0:
            return f"商店 {event_id & 0x0F} · ${event_id:02X}"
        return f"地图事件 ${event_id:02X}"

    def refresh(self) -> None:
        previous = self.current_map_id
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
            self.map_list.setCurrentRow(row)
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
        if self.current_map_id < self.project.scenario_count:
            layout = self.project.get_scenario_layout(self.current_map_id)
            self.prelude.setEnabled(True)
            self.prelude.setText(bytes(layout.prelude).hex(" ").upper())
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
        self._update_overlays()
        self._loaded_draft_signature = self._draft_signature()
        self._commit_error = None
        self._update_size_label()
        if committed_previous:
            self.project_changed.emit(
                f"已更新地图 ${previous_map_id:02X}、部署与事件"
            )

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
                composite = QImage(32, 32, QImage.Format.Format_RGB32)
                composite.fill(QColor("#000000"))
                painter = QPainter(composite)
                for y in (0, 16):
                    for x in (0, 16):
                        painter.drawImage(x, y, images[tile])
                painter.end()
                pixmap = QPixmap.fromImage(composite).scaled(
                    56,
                    56,
                    Qt.AspectRatioMode.IgnoreAspectRatio,
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
            key,
            self.canvas.tile_images,
            self,
        )
        self._tile_attribute_dialog.show()

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
            image = render_unit_icon_bank(self.project, bank)
            preview.setText("")
            preview.setPixmap(
                QPixmap.fromImage(image).scaled(
                    384,
                    48,
                    Qt.AspectRatioMode.IgnoreAspectRatio,
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
        images = render_tileset(self.project, key)
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
        overlays: list[tuple[str, int, int, str, int]] = []
        mode = self.editor_tabs.currentIndex()
        if mode == 1:
            for row, values in enumerate(self.enemy_table.rows()):
                overlays.append(("敌", values[0], values[1], f"{values[2]:X}"[-1], row))
            for row, values in enumerate(self.guest_table.rows()):
                overlays.append(("客", values[0], values[1], f"{values[2]:X}"[-1], row))
            for row, values in enumerate(self.player_table.rows()):
                overlays.append(("我", values[0], values[1], str(values[2] % 10), row))
        elif mode == 2 and self.trigger_table.isEnabled():
            for row, values in enumerate(self.trigger_table.rows()):
                side = "店" if values[3] >= 0xF0 else "事"
                overlays.append((side, values[0], values[1], side, row))
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
                trigger_used = self.project.map_trigger_codec.storage_used_after(
                    self.project.working,
                    self.current_map_id,
                    staged_triggers,
                )
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
        if self.project is None or self.current_map_id is None:
            self.size_label.setText("—")
            self.pending_state.setText("选择地图后可编辑。")
            self.apply_button.setEnabled(False)
            self._emit_draft_state_changed()
            return
        try:
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
                    trigger_used = self.project.map_trigger_codec.storage_used_after(
                        self.project.working, self.current_map_id, staged_triggers
                    )
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
