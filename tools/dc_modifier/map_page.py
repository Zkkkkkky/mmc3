from __future__ import annotations

from PySide6.QtCore import QPoint, QRect, QSize, Qt, Signal
from PySide6.QtGui import QColor, QMouseEvent, QPainter, QPen
from PySide6.QtWidgets import (
    QAbstractItemView,
    QComboBox,
    QFormLayout,
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
    QVBoxLayout,
    QWidget,
)

from fc_editor.dc_text import dc_map_label

from fc_editor.models import PlayerPlacement, ScenarioEntity, ScenarioLayout

from .pages import ProjectPage, page_title


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
    coordinate_changed = Signal(int, int)

    def __init__(self) -> None:
        super().__init__()
        self.map_width = 1
        self.map_height = 1
        self.tiles = [0]
        self.cell_size = 24
        self.selected_tile = 0
        self.overlays: list[tuple[str, int, int, str]] = []
        self.setMouseTracking(True)

    def sizeHint(self) -> QSize:
        return QSize(self.map_width * self.cell_size + 1, self.map_height * self.cell_size + 1)

    def set_content(
        self,
        width: int,
        height: int,
        tiles: list[int],
        overlays: list[tuple[str, int, int, str]],
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
                painter.fillRect(rect, TERRAIN_COLORS[tile])
                painter.setPen(QPen(QColor(0, 0, 0, 45), 1))
                painter.drawRect(rect)
                if self.cell_size >= 25:
                    painter.setPen(QColor(20, 25, 30, 150))
                    painter.drawText(rect, Qt.AlignmentFlag.AlignCenter, f"{tile:X}")
        side_colors = {
            "敌": QColor("#d94b45"),
            "客": QColor("#e49d28"),
            "我": QColor("#2d75d2"),
        }
        for side, x, y, label in self.overlays:
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
            self._paint_at(event.position().toPoint())
        elif event.button() == Qt.MouseButton.RightButton:
            cell = self._cell_at(event.position().toPoint())
            if cell is not None:
                x, y = cell
                self.selected_tile = self.tiles[y * self.map_width + x]

    def mouseMoveEvent(self, event: QMouseEvent) -> None:
        cell = self._cell_at(event.position().toPoint())
        if cell is not None:
            self.coordinate_changed.emit(*cell)
        if event.buttons() & Qt.MouseButton.LeftButton:
            self._paint_at(event.position().toPoint())


class ByteEntryTable(QTableWidget):
    values_changed = Signal()

    def __init__(self, headers: tuple[str, ...], label_providers=None) -> None:
        super().__init__(0, len(headers))
        self.headers = headers
        self.label_providers = dict(label_providers or {})
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

    def add_row(self, values: tuple[int, ...] | None = None) -> None:
        values = values or tuple(0 for _ in self.headers)
        row = self.rowCount()
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


class MapPage(ProjectPage):
    def __init__(self) -> None:
        super().__init__()
        self.current_map_id: int | None = None
        self.staged_tiles: list[int] = []
        self.staged_width = 1
        self.staged_height = 1
        outer = QVBoxLayout(self)
        title, subtitle = page_title(
            "地图与部署",
            "左键绘制逻辑图块，右键吸取；颜色只区分ROM中的0—F编号，不虚构未验证的地形语义。",
        )
        outer.addWidget(title)
        outer.addWidget(subtitle)
        splitter = QSplitter()

        left = QWidget()
        left.setMinimumWidth(205)
        left_layout = QVBoxLayout(left)
        left_layout.setContentsMargins(0, 0, 0, 0)
        self.search = QLineEdit()
        self.search.setPlaceholderText("搜索关卡名、地图ID…")
        self.search.setClearButtonEnabled(True)
        self.search.textChanged.connect(self._filter_maps)
        self.map_list = QListWidget()
        self.map_list.setAlternatingRowColors(True)
        self.map_list.currentItemChanged.connect(self._map_selected)
        left_layout.addWidget(self.search)
        left_layout.addWidget(self.map_list)
        splitter.addWidget(left)

        center = QWidget()
        center_layout = QVBoxLayout(center)
        center_layout.setContentsMargins(8, 0, 8, 0)
        tools = QHBoxLayout()
        self.terrain = QComboBox()
        for tile in range(16):
            self.terrain.addItem(f"逻辑图块 ${tile:X} · ROM原值", tile)
        self.terrain.currentIndexChanged.connect(self._terrain_selected)
        self.zoom = QSpinBox()
        self.zoom.setRange(14, 40)
        self.zoom.setValue(24)
        self.zoom.setSuffix(" px")
        self.zoom.valueChanged.connect(self._zoom_changed)
        self.position_label = QLabel("坐标：—")
        self.size_label = QLabel("—")
        self.size_label.setObjectName("hintText")
        tools.addWidget(QLabel("画笔"))
        tools.addWidget(self.terrain)
        tools.addWidget(QLabel("缩放"))
        tools.addWidget(self.zoom)
        tools.addStretch()
        tools.addWidget(self.position_label)
        center_layout.addLayout(tools)
        self.canvas = MapCanvas()
        self.canvas.tile_painted.connect(self._tile_painted)
        self.canvas.coordinate_changed.connect(
            lambda x, y: self.position_label.setText(f"坐标：({x}, {y})")
        )
        scroll = QScrollArea()
        scroll.setWidget(self.canvas)
        scroll.setWidgetResizable(False)
        scroll.setAlignment(Qt.AlignmentFlag.AlignCenter)
        center_layout.addWidget(scroll, 1)
        center_layout.addWidget(self.size_label)
        splitter.addWidget(center)

        right = QWidget()
        # Deployment rows contain resolved machine and pilot names.  Keep enough
        # room for those names instead of collapsing every editor to an ID stub.
        right.setMinimumWidth(540)
        right_layout = QVBoxLayout(right)
        right_layout.setContentsMargins(0, 0, 0, 0)
        dimensions = QGroupBox("地图尺寸")
        dimensions_form = QFormLayout(dimensions)
        self.width_editor = QSpinBox()
        self.width_editor.setRange(1, 32)
        self.height_editor = QSpinBox()
        self.height_editor.setRange(1, 32)
        resize_button = QPushButton("调整尺寸")
        resize_button.clicked.connect(self._resize_map)
        dimensions_form.addRow("宽", self.width_editor)
        dimensions_form.addRow("高", self.height_editor)
        dimensions_form.addRow(resize_button)
        right_layout.addWidget(dimensions)

        self.prelude = QLineEdit()
        self.prelude.setPlaceholderText("前导字节，例如 01 02；不含 FF")
        right_layout.addWidget(QLabel("场景前导列表"))
        right_layout.addWidget(self.prelude)
        self.enemy_table = self._deployment_group(
            right_layout,
            "敌军",
            ("X", "Y", "机体", "驾驶员", "等级", "标志"),
            {2: self._unit_choice_label, 3: self._character_choice_label},
        )
        self.guest_table = self._deployment_group(
            right_layout,
            "客军",
            ("X", "Y", "机体", "驾驶员", "等级", "标志"),
            {2: self._unit_choice_label, 3: self._character_choice_label},
        )
        self.player_table = self._deployment_group(
            right_layout, "我方出击位", ("X", "Y", "名单位", "标志")
        )
        buttons = QHBoxLayout()
        apply_button = QPushButton("应用地图与部署")
        apply_button.setObjectName("primaryButton")
        apply_button.clicked.connect(self.apply_changes)
        reset_button = QPushButton("还原")
        reset_button.clicked.connect(self.reset_current)
        buttons.addWidget(apply_button)
        buttons.addWidget(reset_button)
        right_layout.addLayout(buttons)
        splitter.addWidget(right)
        splitter.setSizes([180, 500, 540])
        outer.addWidget(splitter, 1)

    def _deployment_group(
        self,
        layout: QVBoxLayout,
        title: str,
        headers: tuple[str, ...],
        label_providers=None,
    ) -> ByteEntryTable:
        group = QGroupBox(title)
        group_layout = QVBoxLayout(group)
        table = ByteEntryTable(headers, label_providers)
        table.setMinimumHeight(105)
        table.values_changed.connect(self._update_overlays)
        buttons = QHBoxLayout()
        add_button = QPushButton("添加")
        add_button.clicked.connect(table.add_row)
        remove_button = QPushButton("删除选中")
        remove_button.clicked.connect(table.remove_selected)
        buttons.addWidget(add_button)
        buttons.addWidget(remove_button)
        buttons.addStretch()
        group_layout.addWidget(table)
        group_layout.addLayout(buttons)
        layout.addWidget(group, 1)
        return table

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
        for row in range(self.map_list.count()):
            item = self.map_list.item(row)
            map_id = int(item.data(Qt.ItemDataRole.UserRole))
            item.setHidden(bool(query) and query not in item.text().lower() and query not in (str(map_id), f"{map_id:02x}"))

    def _map_selected(self, item: QListWidgetItem | None, _previous: QListWidgetItem | None) -> None:
        if self.project is None or item is None:
            self.current_map_id = None
            return
        self.current_map_id = int(item.data(Qt.ItemDataRole.UserRole))
        record = self.project.get_map(self.current_map_id)
        self.staged_width = record.width
        self.staged_height = record.height
        self.staged_tiles = list(record.tiles)
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
        self._update_overlays()
        self._update_size_label()

    def _terrain_selected(self) -> None:
        self.canvas.selected_tile = int(self.terrain.currentData())

    def _zoom_changed(self, value: int) -> None:
        self.canvas.set_cell_size(value)

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
        overlays: list[tuple[str, int, int, str]] = []
        for values in self.enemy_table.rows():
            overlays.append(("敌", values[0], values[1], f"{values[2]:X}"[-1]))
        for values in self.guest_table.rows():
            overlays.append(("客", values[0], values[1], f"{values[2]:X}"[-1]))
        for values in self.player_table.rows():
            overlays.append(("我", values[0], values[1], str(values[2] % 10)))
        self.canvas.set_content(
            self.staged_width,
            self.staged_height,
            self.staged_tiles,
            overlays,
        )

    def _update_size_label(self) -> None:
        if self.project is None or self.current_map_id is None:
            self.size_label.setText("—")
            return
        encoded = self.project.map_codec.encode(
            self.staged_width,
            self.staged_height,
            tuple(self.staged_tiles),
        )
        capacity = self.project.map_codec.capacities[self.current_map_id]
        status = "可保存" if len(encoded) <= capacity else "超出容量"
        self.size_label.setText(
            f"地图 ${self.current_map_id:02X} · {dc_map_label(self.current_map_id)} · "
            f"RLE {len(encoded)} / {capacity} 字节 · {status}"
        )

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
            with self.project.transaction(f"地图 ${self.current_map_id:02X} · 地形与部署"):
                self.project.set_map_tiles(
                    self.current_map_id,
                    self.staged_width,
                    self.staged_height,
                    tuple(self.staged_tiles),
                )
                if self.current_map_id < self.project.scenario_count:
                    current = self.project.get_scenario_layout(self.current_map_id)
                    layout = ScenarioLayout(
                        self.current_map_id,
                        current.pointer,
                        self._parse_hex_bytes(self.prelude.text()),
                        tuple(ScenarioEntity(*values) for values in self.enemy_table.rows()),
                        tuple(ScenarioEntity(*values) for values in self.guest_table.rows()),
                        tuple(PlayerPlacement(*values) for values in self.player_table.rows()),
                        current.raw,
                        current.capacity,
                    )
                    self.project.set_scenario_layout(layout)
            self.project_changed.emit(f"已更新地图 ${self.current_map_id:02X} 与部署")
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
            self.project_changed.emit(f"已还原地图 ${self.current_map_id:02X} 与部署")
        except Exception as error:
            self.show_error(error)
