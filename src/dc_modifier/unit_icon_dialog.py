from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QPoint, QRect, QSize, Qt, Signal
from PySide6.QtGui import QColor, QIcon, QImage, QMouseEvent, QPainter, QPen, QPixmap
from PySide6.QtWidgets import (
    QButtonGroup,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from fc_editor.dc_text import dc_map_label
from fc_editor.legacy_bitmap import LEGACY_MATERIAL_PALETTE_RGB, encode_legacy_bmp24

from .database_graphics import palette_color
from .map_page import render_unit_icon_bank, scenario_map_icon_banks


class UnitIconBindingDialog(QDialog):
    """Choose a map icon through the same per-scenario route as the game."""

    def __init__(
        self,
        project,
        raw_icon_value: int,
        palette_values: tuple[int, int, int, int],
        parent=None,
    ) -> None:
        super().__init__(parent)
        self.project = project
        self.palette_values = palette_values
        self.raw_icon_value = raw_icon_value if raw_icon_value % 4 == 0 else 0
        self.selected_bank = 0
        self.selected_icon_index = 0
        self.setWindowTitle("机体图标设置")
        self.setMinimumWidth(680)

        root = QVBoxLayout(self)
        hint = QLabel(
            "机体图标图库会随关卡动态切换。先选择机体出现关卡，再从该关卡实际加载的48个图标中选择。"
        )
        hint.setWordWrap(True)
        root.addWidget(hint)

        selector_box = QGroupBox("图标选择")
        selectors = QGridLayout(selector_box)
        selectors.setContentsMargins(8, 7, 8, 7)
        selectors.setHorizontalSpacing(18)
        selectors.setVerticalSpacing(4)
        selectors.addWidget(QLabel("机体出现关卡"), 0, 0)
        self.scenario = QComboBox()
        for map_id in range(32):
            self.scenario.addItem(f"{map_id + 1:03d}：{dc_map_label(map_id)}", map_id)
        self.scenario.currentIndexChanged.connect(self._refresh_route)
        selectors.addWidget(self.scenario, 1, 0)
        selectors.addWidget(QLabel("图标编号"), 0, 1)
        self.icon_number = QComboBox()
        for position in range(48):
            self.icon_number.addItem(f"图标：{position + 1:02d}", position)
        self.icon_number.currentIndexChanged.connect(self._select_number)
        selectors.addWidget(self.icon_number, 1, 1)
        selectors.setColumnStretch(0, 1)
        selectors.setColumnStretch(1, 1)
        root.addWidget(selector_box)

        # Match the legacy editor: three continuous black icon strips with the
        # 01-48 labels above them, rather than oversized boxed buttons.
        self.icon_grid = QWidget()
        self.icon_grid.setObjectName("unitIconRouteGrid")
        grid = QGridLayout(self.icon_grid)
        grid.setContentsMargins(0, 2, 0, 2)
        grid.setHorizontalSpacing(1)
        grid.setVerticalSpacing(1)
        self.icon_buttons: list[QToolButton] = []
        for position in range(48):
            row, column = divmod(position, 16)
            number = QLabel(f"{position + 1:02d}")
            number.setAlignment(Qt.AlignmentFlag.AlignCenter)
            number.setFixedSize(39, 18)
            grid.addWidget(number, row * 2, column)
            button = QToolButton()
            button.setCheckable(True)
            button.setAutoExclusive(True)
            button.setAutoRaise(True)
            button.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonIconOnly)
            button.setIconSize(QSize(32, 32))
            button.setFixedSize(39, 34)
            button.setStyleSheet(
                "QToolButton { background:#000; border:none; padding:1px; }"
                "QToolButton:checked { border:2px solid #FF3333; padding:0; }"
            )
            button.clicked.connect(
                lambda _checked=False, value=position: self.icon_number.setCurrentIndex(value)
            )
            grid.addWidget(button, row * 2 + 1, column)
            self.icon_buttons.append(button)
        self.icon_grid.setFixedHeight(164)
        root.addWidget(self.icon_grid)

        self.route_status = QLabel()
        root.addWidget(self.route_status)
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok
            | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        buttons.button(QDialogButtonBox.StandardButton.Ok).setText("确定")
        buttons.button(QDialogButtonBox.StandardButton.Cancel).setText("取消")
        root.addWidget(buttons)

        position = min(47, self.raw_icon_value // 4)
        self.icon_number.setCurrentIndex(position)
        self._refresh_route()

    def _refresh_route(self) -> None:
        map_id = int(self.scenario.currentData())
        route = scenario_map_icon_banks(map_id)
        for row, bank in enumerate(route):
            image = render_unit_icon_bank(self.project, bank, self.palette_values)
            for column in range(16):
                position = row * 16 + column
                icon = image.copy(column * 16, 0, 16, 16).scaled(
                    32,
                    32,
                    Qt.AspectRatioMode.KeepAspectRatio,
                    Qt.TransformationMode.FastTransformation,
                )
                button = self.icon_buttons[position]
                button.setIcon(QIcon(QPixmap.fromImage(icon)))
                button.setToolTip(
                    f"图标 {position + 1:02d} · 图库 ${bank:02X} · 库内 {column:X}"
                )
        self._select_number()
        self.route_status.setText(
            f"本关路由：${route[0]:02X} / ${route[1]:02X} / ${route[2]:02X}；"
            "绑定写入的是动态路由位置，不会固定为当前关卡的图库地址。"
        )

    def _select_number(self) -> None:
        position = max(0, self.icon_number.currentIndex())
        row, column = divmod(position, 16)
        self.icon_buttons[position].setChecked(True)
        route = scenario_map_icon_banks(int(self.scenario.currentData()))
        self.selected_bank = route[row]
        self.selected_icon_index = column
        self.raw_icon_value = position * 4

    def _select_cell(self, row: int, column: int) -> None:
        self.icon_number.setCurrentIndex(row * 16 + column)


class UnitIconCanvas(QWidget):
    pixels_changed = Signal()

    def __init__(self, palette_values: tuple[int, int, int, int]) -> None:
        super().__init__()
        self.pixels = [0] * 256
        self.ink = 1
        self.cell_size = 17
        self.colors = tuple(palette_color(value) for value in palette_values)
        self.setMouseTracking(True)
        self.setFixedSize(self.sizeHint())

    def sizeHint(self) -> QSize:
        return QSize(self.cell_size * 16 + 1, self.cell_size * 16 + 1)

    def set_pixels(self, pixels: list[int]) -> None:
        if len(pixels) != 256:
            raise ValueError("机体图标必须是16×16像素。")
        self.pixels = list(pixels)
        self.update()

    def paintEvent(self, _event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, False)
        for y in range(16):
            for x in range(16):
                rect = QRect(
                    x * self.cell_size,
                    y * self.cell_size,
                    self.cell_size,
                    self.cell_size,
                )
                painter.fillRect(rect, self.colors[self.pixels[y * 16 + x]])
                painter.setPen(QPen(QColor(25, 30, 35, 70), 1))
                painter.drawRect(rect)

    def _cell(self, position: QPoint) -> tuple[int, int]:
        return position.x() // self.cell_size, position.y() // self.cell_size

    def _paint_at(self, position: QPoint) -> None:
        x, y = self._cell(position)
        if not 0 <= x < 16 or not 0 <= y < 16:
            return
        offset = y * 16 + x
        if self.pixels[offset] == self.ink:
            return
        self.pixels[offset] = self.ink
        self.pixels_changed.emit()
        self.update(QRect(
            x * self.cell_size,
            y * self.cell_size,
            self.cell_size + 1,
            self.cell_size + 1,
        ))

    def mousePressEvent(self, event: QMouseEvent) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self._paint_at(event.position().toPoint())
        elif event.button() == Qt.MouseButton.RightButton:
            x, y = self._cell(event.position().toPoint())
            if 0 <= x < 16 and 0 <= y < 16:
                self.ink = self.pixels[y * 16 + x]

    def mouseMoveEvent(self, event: QMouseEvent) -> None:
        if event.buttons() & Qt.MouseButton.LeftButton:
            self._paint_at(event.position().toPoint())


class UnitIconDialog(QDialog):
    """Edit the four real CHR tiles backing one 16×16 map icon."""

    def __init__(
        self,
        project,
        bank: int,
        icon_index: int,
        palette_values: tuple[int, int, int, int],
        parent=None,
    ) -> None:
        super().__init__(parent)
        self.project = project
        self.bank = bank
        self.icon_index = icon_index
        self.palette_values = palette_values
        self.first_tile = bank * 64 + icon_index * 4
        self.original_pixels = self._read_pixels()
        self.changed = False
        self.setWindowTitle(
            f"编辑机体图标 · 图库 ${bank:02X} · 图标 {icon_index:X}"
        )

        root = QVBoxLayout(self)
        hint = QLabel(
            "直接编辑游戏使用的四块CHR图块。左键绘制，右键吸色；"
            "颜色按钮代表当前阵营的游戏内色表。"
        )
        hint.setWordWrap(True)
        root.addWidget(hint)
        editor_row = QHBoxLayout()
        editor_row.setSpacing(12)
        self.canvas = UnitIconCanvas(palette_values)
        self.canvas.set_pixels(self.original_pixels)
        editor_row.addWidget(
            self.canvas,
            0,
            Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop,
        )

        self.palette_box = QGroupBox("画笔")
        self.palette_box.setFixedWidth(126)
        palette_column = QVBoxLayout(self.palette_box)
        palette_column.setContentsMargins(7, 8, 7, 8)
        palette_column.setSpacing(6)
        self.palette_buttons: list[QPushButton] = []
        self.palette_button_group = QButtonGroup(self)
        self.palette_button_group.setExclusive(True)
        for index, value in enumerate(palette_values):
            button = QPushButton(f"{index}  ·  ${value:02X}")
            button.setCheckable(True)
            button.setFixedSize(110, 42)
            color = palette_color(value)
            foreground = "#000000" if color.lightness() >= 128 else "#FFFFFF"
            button.setStyleSheet(
                f"QPushButton {{ background:{color.name()}; color:{foreground};"
                "border:1px solid #555; font-weight:600; }"
                "QPushButton:checked { border:3px solid #FFD400; }"
            )
            button.clicked.connect(
                lambda _checked=False, ink=index: self._set_ink(ink)
            )
            self.palette_button_group.addButton(button, index)
            self.palette_buttons.append(button)
            palette_column.addWidget(button)
        self.palette_buttons[self.canvas.ink].setChecked(True)
        palette_column.addStretch(1)
        editor_row.addWidget(
            self.palette_box,
            0,
            Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignTop,
        )
        root.addLayout(editor_row)

        actions = QHBoxLayout()
        self.import_button = QPushButton("导入BMP…")
        self.import_button.clicked.connect(self._import_bitmap)
        export_button = QPushButton("导出BMP…")
        export_button.clicked.connect(self._export_bitmap)
        reset_button = QPushButton("还原打开时")
        reset_button.clicked.connect(
            lambda: self.canvas.set_pixels(self.original_pixels)
        )
        actions.addWidget(self.import_button)
        actions.addWidget(export_button)
        actions.addWidget(reset_button)
        actions.addStretch(1)
        root.addLayout(actions)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok
            | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        root.addWidget(buttons)

    def _read_pixels(self) -> list[int]:
        result = [0] * 256
        for quadrant in range(4):
            tile = self.project.chr_tile_pixels(self.first_tile + quadrant)
            origin_x = quadrant % 2 * 8
            origin_y = quadrant // 2 * 8
            for y in range(8):
                for x in range(8):
                    result[(origin_y + y) * 16 + origin_x + x] = tile[y * 8 + x]
        return result

    def _set_ink(self, ink: int) -> None:
        self.canvas.ink = ink

    def _image(self) -> QImage:
        image = QImage(16, 16, QImage.Format.Format_ARGB32)
        image.fill(Qt.GlobalColor.transparent)
        colors = tuple(palette_color(value) for value in self.palette_values)
        for y in range(16):
            for x in range(16):
                index = self.canvas.pixels[y * 16 + x]
                if index:
                    image.setPixelColor(x, y, colors[index])
        return image

    def _pixels_from_image(self, image: QImage) -> list[int]:
        image = image.scaled(
            16, 16,
            Qt.AspectRatioMode.IgnoreAspectRatio,
            Qt.TransformationMode.FastTransformation,
        )
        game_colors = tuple(palette_color(value) for value in self.palette_values)
        material_colors = tuple(QColor(*value) for value in LEGACY_MATERIAL_PALETTE_RGB)
        opaque_pixels = [
            image.pixelColor(x, y)
            for y in range(16)
            for x in range(16)
            if image.pixelColor(x, y).alpha() >= 128
        ]

        def palette_error(colors: tuple[QColor, ...]) -> int:
            return sum(
                min(
                    (pixel.red() - color.red()) ** 2
                    + (pixel.green() - color.green()) ** 2
                    + (pixel.blue() - color.blue()) ** 2
                    for color in colors
                )
                for pixel in opaque_pixels
            )

        colors = min((game_colors, material_colors), key=palette_error)
        pixels: list[int] = []
        for y in range(16):
            for x in range(16):
                pixel = image.pixelColor(x, y)
                if pixel.alpha() < 128:
                    pixels.append(0)
                    continue
                pixels.append(min(
                    range(4),
                    key=lambda index: (
                        (pixel.red() - colors[index].red()) ** 2
                        + (pixel.green() - colors[index].green()) ** 2
                        + (pixel.blue() - colors[index].blue()) ** 2
                    ),
                ))
        return pixels

    def _import_bitmap(self) -> None:
        path, _filter = QFileDialog.getOpenFileName(
            self,
            "导入16×16机体图标",
            "",
            "BMP 位图 (*.bmp);;PNG 图像 (*.png);;所有图像 (*.bmp *.png)",
        )
        if not path:
            return
        image = QImage(path)
        if image.isNull():
            QMessageBox.warning(self, "无法导入", "无法读取所选BMP或PNG图像。")
            return
        if image.width() != 16 or image.height() != 16:
            QMessageBox.warning(
                self,
                "无法导入",
                f"机体图标必须是16×16像素；当前图像为"
                f"{image.width()}×{image.height()}像素。",
            )
            return
        self.canvas.set_pixels(self._pixels_from_image(image))

    def _bitmap_bytes(self) -> bytes:
        colors = tuple(palette_color(value) for value in self.palette_values)
        pixels = (
            (colors[index].red(), colors[index].green(), colors[index].blue())
            for index in self.canvas.pixels
        )
        return encode_legacy_bmp24(16, 16, pixels)

    def _export_bitmap(self) -> None:
        path, _filter = QFileDialog.getSaveFileName(
            self, "导出机体图标", "unit-icon.bmp", "BMP 位图 (*.bmp)"
        )
        if not path:
            return
        destination = Path(path)
        if destination.suffix.lower() != ".bmp":
            destination = destination.with_suffix(".bmp")
        try:
            destination.write_bytes(self._bitmap_bytes())
        except OSError as error:
            QMessageBox.warning(self, "无法导出", f"无法写入BMP文件：{error}")

    def accept(self) -> None:
        try:
            payload = bytearray()
            for quadrant in range(4):
                origin_x = quadrant % 2 * 8
                origin_y = quadrant // 2 * 8
                tile = [
                    self.canvas.pixels[(origin_y + y) * 16 + origin_x + x]
                    for y in range(8)
                    for x in range(8)
                ]
                payload.extend(self.project.chr_codec.encode_tile(tile))
            self.changed = self.canvas.pixels != self.original_pixels
            if self.changed:
                self.project.set_chr_range(self.first_tile, bytes(payload))
        except (TypeError, ValueError, IndexError) as error:
            QMessageBox.warning(self, "无法保存机体图标", str(error))
            return
        super().accept()
