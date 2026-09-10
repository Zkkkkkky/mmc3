from __future__ import annotations

from PySide6.QtCore import QPoint, QRect, QSize, Qt, Signal
from PySide6.QtGui import QColor, QIcon, QImage, QMouseEvent, QPainter, QPen, QPixmap
from PySide6.QtWidgets import (
    QAbstractItemView,
    QButtonGroup,
    QComboBox,
    QCheckBox,
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
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from fc_editor.dc_text import dc_map_label
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


class MapCanvas(QWidget):
    tile_painted = Signal(int, int, int)
    tile_picked = Signal(int)
    coordinate_changed = Signal(int, int)
    overlay_moved = Signal(str, int, int, int)

    def __init__(self) -> None:
        super().__init__()
        self.map_width = 1
        self.map_height = 1
        self.tiles = [0]
        self.cell_size = 24
        self.selected_tile = 0
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

    def _paint_at(self, position: QPoint) -> None:
        cell = self._cell_at(position)
        if cell is None:
            return
        x, y = cell
        index = y * self.map_width + x
        if self.tiles[index] == self.selected_tile:
            return
        self.tiles[index] = self.selected_tile
        self.tile_painted.emit(x, y, self.selected_tile)
        self.update(QRect(x * self.cell_size, y * self.cell_size, self.cell_size + 1, self.cell_size + 1))

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
                self._paint_at(event.position().toPoint())
        elif event.button() == Qt.MouseButton.RightButton:
            cell = self._cell_at(event.position().toPoint())
            if cell is not None:
                x, y = cell
                self.selected_tile = self.tiles[y * self.map_width + x]
                self.tile_picked.emit(self.selected_tile)

    def mouseMoveEvent(self, event: QMouseEvent) -> None:
        cell = self._cell_at(event.position().toPoint())
        if cell is not None:
            self.coordinate_changed.emit(*cell)
        if (
            event.buttons() & Qt.MouseButton.LeftButton
            and self.dragged_overlay is None
        ):
            self._paint_at(event.position().toPoint())

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
    def __init__(self) -> None:
        super().__init__()
        self.current_map_id: int | None = None
        self.staged_tiles: list[int] = []
        self.staged_width = 1
        self.staged_height = 1
        self.hovered_cell: tuple[int, int] | None = None
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
        brush_layout = QVBoxLayout(brush_group)
        tileset_row = QHBoxLayout()
        self.tileset = QComboBox()
        for key, bank in TILESET_BANKS.items():
            self.tileset.addItem(f"位图{key} · CHR图库 ${bank:02X}", key)
        self.tileset.currentIndexChanged.connect(self._refresh_tile_visuals)
        self.tileset_meta = QLabel("—")
        self.tileset_meta.setObjectName("hintText")
        tileset_row.addWidget(QLabel("真实位图"))
        tileset_row.addWidget(self.tileset, 1)
        brush_layout.addLayout(tileset_row)
        brush_layout.addWidget(self.tileset_meta)
        self.terrain = QComboBox()
        for tile in range(16):
            self.terrain.addItem(f"位置 {tile:X} · ROM逻辑图块", tile)
        self.terrain.currentIndexChanged.connect(self._terrain_selected)
        brush_layout.addWidget(self.terrain)
        palette = QGridLayout()
        palette.setSpacing(5)
        self.terrain_buttons = QButtonGroup(self)
        self.terrain_buttons.setExclusive(True)
        for tile, color in enumerate(TERRAIN_COLORS):
            button = QPushButton(f"{tile:X}")
            button.setObjectName("terrainButton")
            button.setCheckable(True)
            button.setIconSize(QSize(38, 38))
            button.setToolTip(f"逻辑图块 ${tile:X}；左键绘制，右键从地图吸取")
            button.setStyleSheet(
                "QPushButton { background: %s; color: %s; }"
                "QPushButton:checked { border: 3px solid #082f49; }"
                % (color.name(), "#ffffff" if color.lightness() < 135 else "#13293a")
            )
            self.terrain_buttons.addButton(button, tile)
            button.clicked.connect(lambda _checked=False, value=tile: self.terrain.setCurrentIndex(value))
            palette.addWidget(button, tile // 8, tile % 8)
        self.terrain_buttons.button(0).setChecked(True)
        brush_layout.addLayout(palette)
        self.show_ids = QCheckBox("在地图格左上角显示逻辑编号")
        self.show_ids.toggled.connect(self._show_ids_changed)
        brush_layout.addWidget(self.show_ids)
        brush_hint = QLabel("左键连续绘制；右键吸取图块；地图上的圆点表示部署。")
        brush_hint.setObjectName("hintText")
        brush_hint.setWordWrap(True)
        brush_layout.addWidget(brush_hint)
        tile_layout.addWidget(brush_group)

        dimensions = QGroupBox("地图尺寸与场景数据")
        dimensions_form = QFormLayout(dimensions)
        self.width_editor = QSpinBox()
        self.width_editor.setRange(1, 32)
        self.height_editor = QSpinBox()
        self.height_editor.setRange(1, 32)
        resize_button = QPushButton("调整尺寸")
        resize_button.clicked.connect(self._resize_map)
        dimensions_form.addRow("宽", self.width_editor)
        dimensions_form.addRow("高", self.height_editor)
        dimensions_form.addRow("尺寸", resize_button)
        self.prelude = QLineEdit()
        self.prelude.setPlaceholderText("前导字节，例如 01 02；不含 FF")
        self.prelude.textChanged.connect(self._update_size_label)
        dimensions_form.addRow("场景前导", self.prelude)
        tile_layout.addWidget(dimensions)
        tile_layout.addStretch()
        self.editor_tabs.addTab(tile_tab, "战场地图")

        deployment_tab = QWidget()
        deployment_layout = QVBoxLayout(deployment_tab)
        deployment_layout.setContentsMargins(8, 8, 8, 8)
        deployment_hint = QLabel("分别编辑敌军、客军和我方出击位；机体与人物均显示真实名称。")
        deployment_hint.setObjectName("hintText")
        deployment_hint.setWordWrap(True)
        deployment_layout.addWidget(deployment_hint)
        deployment_tabs = QTabWidget()
        deployment_tabs.setObjectName("subTabs")
        enemy_host = QWidget()
        enemy_layout = QVBoxLayout(enemy_host)
        self.enemy_table = self._deployment_group(
            enemy_layout,
            "敌军",
            ("X", "Y", "机体", "驾驶员", "等级", "标志"),
            {2: self._unit_choice_label, 3: self._character_choice_label},
            max_rows=18,
        )
        deployment_tabs.addTab(enemy_host, "敌军")
        guest_host = QWidget()
        guest_layout = QVBoxLayout(guest_host)
        self.guest_table = self._deployment_group(
            guest_layout,
            "客军",
            ("X", "Y", "机体", "驾驶员", "等级", "标志"),
            {2: self._unit_choice_label, 3: self._character_choice_label},
            max_rows=3,
        )
        deployment_tabs.addTab(guest_host, "客军")
        player_host = QWidget()
        player_layout = QVBoxLayout(player_host)
        self.player_table = self._deployment_group(
            player_layout,
            "我方出击位",
            ("X", "Y", "名单位", "标志"),
            max_rows=11,
        )
        deployment_tabs.addTab(player_host, "我方出击位")
        deployment_layout.addWidget(deployment_tabs, 1)
        self.editor_tabs.addTab(deployment_tab, "初始配置")

        trigger_tab = QWidget()
        trigger_layout = QVBoxLayout(trigger_tab)
        trigger_layout.setContentsMargins(8, 8, 8, 8)
        trigger_hint = QLabel(
            "编辑踩点触发的剧情事件或商店。限定人物为 $FF 时任何人物都可触发；"
            "事件号 $F0—$FF 表示商店 0—15。地图上的紫色“事”和绿色“店”圆点可拖动。"
        )
        trigger_hint.setObjectName("hintText")
        trigger_hint.setWordWrap(True)
        trigger_layout.addWidget(trigger_hint)
        self.trigger_table = self._deployment_group(
            trigger_layout,
            "地图事件与商店",
            ("X", "Y", "限定人物", "事件/商店"),
            {2: self._trigger_character_label, 3: self._trigger_event_label},
            default_values=(0, 0, 0xFF, 0),
        )
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
        inspector_layout.addWidget(self.editor_tabs, 3)
        inspector_layout.addWidget(self.chapter_group, 2)
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
        self.position_label = QLabel("坐标：—")
        self.size_label = QLabel("—")
        self.size_label.setObjectName("hintText")
        self.canvas = MapCanvas()
        self.canvas.tile_painted.connect(self._tile_painted)
        self.canvas.tile_picked.connect(self.terrain.setCurrentIndex)
        self.canvas.coordinate_changed.connect(self._canvas_coordinate_changed)
        self.canvas.overlay_moved.connect(self._overlay_moved)
        self.map_scroll = MapScrollArea()
        self.map_scroll.setObjectName("mapScrollArea")
        self.map_scroll.setWidget(self.canvas)
        self.map_scroll.setWidgetResizable(False)
        self.map_scroll.setAlignment(
            Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignTop
        )
        self.map_scroll.viewport_resized.connect(self._fit_map_to_viewport)
        canvas_layout.addWidget(self.map_scroll, 1)

        info_row = QHBoxLayout()
        info_row.addWidget(self.size_label, 1)
        info_row.addWidget(self.position_label)
        info_row.addWidget(self.fit_view)
        info_row.addWidget(QLabel("缩放"))
        info_row.addWidget(self.zoom)
        canvas_layout.addLayout(info_row)

        footer = QHBoxLayout()
        self.pending_state = QLabel("选择地图后可编辑。")
        self.pending_state.setObjectName("editState")
        footer.addWidget(self.pending_state, 1)
        buttons = QHBoxLayout()
        self.apply_button = QPushButton("应用地图、部署与事件")
        self.apply_button.setObjectName("primaryButton")
        self.apply_button.clicked.connect(self.apply_changes)
        self.apply_button.setEnabled(False)
        reset_button = QPushButton("还原")
        reset_button.clicked.connect(self.reset_current)
        buttons.addWidget(self.apply_button)
        buttons.addWidget(reset_button)
        footer.addLayout(buttons)
        canvas_layout.addLayout(footer)
        self.main_splitter.addWidget(self.canvas_host)

        self.main_splitter.setStretchFactor(0, 0)
        self.main_splitter.setStretchFactor(1, 1)
        self.main_splitter.setSizes([440, 920])
        outer.addWidget(self.main_splitter, 1)

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
        self.position_label.setText(f"坐标：({x}, {y})")

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
        self.map_list.blockSignals(True)
        self.map_list.clear()
        if self.project is not None:
            for map_id in range(self.project.map_count):
                record = self.project.get_map(map_id)
                item = QListWidgetItem(
                    f"${map_id:02X}  {dc_map_label(map_id)}  ·  "
                    f"{record.width}×{record.height}"
                )
                item.setData(Qt.ItemDataRole.UserRole, map_id)
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
            return
        self.current_map_id = int(item.data(Qt.ItemDataRole.UserRole))
        record = self.project.get_map(self.current_map_id)
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
        self._update_size_label()

    def _terrain_selected(self) -> None:
        self.canvas.selected_tile = int(self.terrain.currentData())
        button = self.terrain_buttons.button(self.canvas.selected_tile)
        if button is not None:
            button.setChecked(True)

    def _refresh_tile_visuals(self) -> None:
        if self.project is None or self.tileset.currentData() is None:
            self.canvas.set_tile_images(())
            return
        key = str(self.tileset.currentData())
        images = render_tileset(self.project, key)
        self.canvas.set_tile_images(images)
        for tile, image in enumerate(images):
            button = self.terrain_buttons.button(tile)
            if button is not None:
                button.setIcon(QIcon(QPixmap.fromImage(image)))
                button.setStyleSheet(
                    "QPushButton { background: #f8fbfd; color: #13293a; }"
                    "QPushButton:checked { border: 3px solid #082f49; }"
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
        self._update_overlays()
        self._update_size_label()

    def _update_overlays(self) -> None:
        overlays: list[tuple[str, int, int, str, int]] = []
        for row, values in enumerate(self.enemy_table.rows()):
            overlays.append(("敌", values[0], values[1], f"{values[2]:X}"[-1], row))
        for row, values in enumerate(self.guest_table.rows()):
            overlays.append(("客", values[0], values[1], f"{values[2]:X}"[-1], row))
        for row, values in enumerate(self.player_table.rows()):
            overlays.append(("我", values[0], values[1], str(values[2] % 10), row))
        if self.trigger_table.isEnabled():
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

    def _update_size_label(self) -> None:
        if self.project is None or self.current_map_id is None:
            self.size_label.setText("—")
            self.pending_state.setText("选择地图后可编辑。")
            self.apply_button.setEnabled(False)
            return
        try:
            encoded = self.project.map_codec.encode(
                self.staged_width,
                self.staged_height,
                tuple(self.staged_tiles),
            )
            capacity = self.project.map_codec.capacities[self.current_map_id]
            size_ok = len(encoded) <= capacity
            details = f"地图RLE {len(encoded)} / {capacity} B"
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
            status = "可保存" if size_ok else "超出固定容量"
            self.size_label.setText(
                f"地图 ${self.current_map_id:02X} · {dc_map_label(self.current_map_id)} · "
                f"{details} · {status}"
            )
            self.apply_button.setEnabled(size_ok and changed)
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
            self.apply_button.setEnabled(False)
        self.pending_state.style().unpolish(self.pending_state)
        self.pending_state.style().polish(self.pending_state)

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
        if self.project is None or self.current_map_id is None:
            return
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
                        self.current_map_id, self._staged_triggers()
                    )
            self.project_changed.emit(
                f"已更新地图 ${self.current_map_id:02X}、部署与事件"
            )
        except Exception as error:
            self.show_error(error)

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
            self.project_changed.emit(
                f"已还原地图 ${self.current_map_id:02X}、部署与事件"
            )
        except Exception as error:
            self.show_error(error)
