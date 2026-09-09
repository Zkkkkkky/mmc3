from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QPoint, QRect, QSize, Qt, Signal
from PySide6.QtGui import QColor, QImage, QMouseEvent, QPainter, QPen
from PySide6.QtWidgets import (
    QComboBox,
    QFileDialog,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from .pages import ProjectPage


DISPLAY_COLORS = (
    QColor("#17212b"),
    QColor("#5f6b78"),
    QColor("#b8c1ca"),
    QColor("#f7f9fb"),
)


class ChrTileCanvas(QWidget):
    pixels_changed = Signal()

    def __init__(self) -> None:
        super().__init__()
        self.pixels = [0] * 64
        self.ink = 1
        self.cell_size = 34
        self.setMouseTracking(True)
        self.setFixedSize(self.sizeHint())

    def sizeHint(self) -> QSize:
        return QSize(self.cell_size * 8 + 1, self.cell_size * 8 + 1)

    def set_pixels(self, pixels: tuple[int, ...] | list[int]) -> None:
        self.pixels = list(pixels)
        self.update()

    def paintEvent(self, _event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, False)
        for y in range(8):
            for x in range(8):
                rect = QRect(
                    x * self.cell_size,
                    y * self.cell_size,
                    self.cell_size,
                    self.cell_size,
                )
                painter.fillRect(rect, DISPLAY_COLORS[self.pixels[y * 8 + x]])
                painter.setPen(QPen(QColor(25, 30, 35, 75), 1))
                painter.drawRect(rect)

    def _paint_at(self, position: QPoint) -> None:
        x = position.x() // self.cell_size
        y = position.y() // self.cell_size
        if not 0 <= x < 8 or not 0 <= y < 8:
            return
        index = y * 8 + x
        if self.pixels[index] == self.ink:
            return
        self.pixels[index] = self.ink
        self.pixels_changed.emit()
        self.update(QRect(x * self.cell_size, y * self.cell_size, self.cell_size + 1, self.cell_size + 1))

    def mousePressEvent(self, event: QMouseEvent) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self._paint_at(event.position().toPoint())
        elif event.button() == Qt.MouseButton.RightButton:
            x = event.position().toPoint().x() // self.cell_size
            y = event.position().toPoint().y() // self.cell_size
            if 0 <= x < 8 and 0 <= y < 8:
                self.ink = self.pixels[y * 8 + x]

    def mouseMoveEvent(self, event: QMouseEvent) -> None:
        if event.buttons() & Qt.MouseButton.LeftButton:
            self._paint_at(event.position().toPoint())


class ChrGraphicsWidget(ProjectPage):
    def __init__(self) -> None:
        super().__init__()
        self.current_tile = 0

        layout = QHBoxLayout(self)
        canvas_column = QVBoxLayout()
        self.canvas = ChrTileCanvas()
        canvas_column.addWidget(self.canvas, 0, Qt.AlignmentFlag.AlignHCenter)
        self.hex_preview = QLabel("00 " * 15 + "00")
        self.hex_preview.setObjectName("hintText")
        self.hex_preview.setWordWrap(True)
        self.hex_preview.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextSelectableByMouse
        )
        canvas_column.addWidget(self.hex_preview)
        canvas_column.addStretch()
        layout.addLayout(canvas_column)

        controls = QVBoxLayout()
        tile_group = QGroupBox("单个 8×8 NES 2bpp 图块")
        form = QFormLayout(tile_group)
        self.tile_index = QSpinBox()
        self.tile_index.setDisplayIntegerBase(16)
        self.tile_index.setPrefix("$")
        self.tile_index.valueChanged.connect(self._load_tile)
        self.location = QLabel("—")
        self.location.setObjectName("hintText")
        self.location.setWordWrap(True)
        self.ink = QComboBox()
        for index in range(4):
            self.ink.addItem(f"像素索引 {index}", index)
        self.ink.currentIndexChanged.connect(self._ink_changed)
        form.addRow("图块号", self.tile_index)
        form.addRow("位置", self.location)
        form.addRow("左键画笔", self.ink)
        single_buttons = QHBoxLayout()
        apply_button = QPushButton("应用图块")
        apply_button.setObjectName("primaryButton")
        apply_button.clicked.connect(self.apply_tile)
        reset_button = QPushButton("还原图块")
        reset_button.clicked.connect(self.reset_tile)
        import_png_button = QPushButton("导入PNG…")
        import_png_button.clicked.connect(self.import_png)
        export_png_button = QPushButton("导出PNG…")
        export_png_button.clicked.connect(self.export_png)
        for button in (apply_button, reset_button, import_png_button, export_png_button):
            single_buttons.addWidget(button)
        form.addRow(single_buttons)
        controls.addWidget(tile_group)

        range_group = QGroupBox("批量 CHR 图块")
        range_layout = QVBoxLayout(range_group)
        range_hint = QLabel(
            "从当前图块开始导入或导出连续的原生 .chr 数据；每个图块固定16字节。"
        )
        range_hint.setObjectName("hintText")
        range_hint.setWordWrap(True)
        self.range_count = QSpinBox()
        self.range_count.setRange(1, 256)
        self.range_count.setValue(16)
        range_row = QHBoxLayout()
        range_row.addWidget(QLabel("导出数量"))
        range_row.addWidget(self.range_count)
        range_row.addStretch()
        range_buttons = QHBoxLayout()
        import_chr_button = QPushButton("导入 .chr…")
        import_chr_button.clicked.connect(self.import_chr)
        export_chr_button = QPushButton("导出 .chr…")
        export_chr_button.clicked.connect(self.export_chr)
        range_buttons.addWidget(import_chr_button)
        range_buttons.addWidget(export_chr_button)
        range_buttons.addStretch()
        range_layout.addWidget(range_hint)
        range_layout.addLayout(range_row)
        range_layout.addLayout(range_buttons)
        controls.addWidget(range_group)

        note = QLabel(
            "CHR图块本身不含颜色，只保存0—3的像素索引。PNG颜色会按明度映射到四级；"
            "右键可吸取像素。当前尚不自动推断某个机体使用的图块范围。"
        )
        note.setObjectName("emptyState")
        note.setWordWrap(True)
        controls.addWidget(note)
        controls.addStretch()
        layout.addLayout(controls, 1)

        self.canvas.pixels_changed.connect(self._update_preview)

    def refresh(self) -> None:
        enabled = self.project is not None
        self.setEnabled(enabled)
        if not enabled:
            self.location.setText("尚未载入ROM。")
            return
        assert self.project is not None
        previous = min(self.current_tile, self.project.chr_tile_count - 1)
        self.tile_index.blockSignals(True)
        self.tile_index.setRange(0, self.project.chr_tile_count - 1)
        self.tile_index.setValue(previous)
        self.tile_index.blockSignals(False)
        self._load_tile(previous)

    def _load_tile(self, tile_index: int) -> None:
        self.current_tile = tile_index
        if self.project is None:
            return
        self.canvas.set_pixels(self.project.chr_tile_pixels(tile_index))
        offset = self.project.chr_codec.tile_offset(tile_index)
        bank = tile_index // 512
        within_bank = tile_index % 512
        self.location.setText(
            f"CHR 8 KiB Bank ${bank:02X} · Bank内图块 ${within_bank:03X} · "
            f"文件偏移 0x{offset:06X}"
        )
        self._update_preview()

    def _ink_changed(self) -> None:
        self.canvas.ink = int(self.ink.currentData())

    def _update_preview(self) -> None:
        if self.project is None:
            return
        raw = self.project.chr_codec.encode_tile(self.canvas.pixels)
        self.hex_preview.setText(raw.hex(" ").upper())

    def apply_tile(self) -> None:
        if self.project is None:
            return
        try:
            self.project.set_chr_tile_pixels(self.current_tile, self.canvas.pixels)
            self.project_changed.emit(f"已更新CHR图块 ${self.current_tile:04X}")
        except Exception as error:
            self.show_error(error)

    def reset_tile(self) -> None:
        if self.project is None:
            return
        try:
            self.project.reset_chr_range(self.current_tile)
            self.project_changed.emit(f"已还原CHR图块 ${self.current_tile:04X}")
        except Exception as error:
            self.show_error(error)

    @staticmethod
    def _image_pixels(image: QImage) -> list[int]:
        if image.isNull():
            raise ValueError("无法解码PNG图像。")
        image = image.scaled(
            8,
            8,
            Qt.AspectRatioMode.IgnoreAspectRatio,
            Qt.TransformationMode.FastTransformation,
        )
        colors = {
            (
                image.pixelColor(x, y).red(),
                image.pixelColor(x, y).green(),
                image.pixelColor(x, y).blue(),
                image.pixelColor(x, y).alpha(),
            )
            for y in range(8)
            for x in range(8)
        }
        if len(colors) <= 4:
            ordered = sorted(
                colors,
                key=lambda color: (
                    0 if color[3] < 128 else 1,
                    color[0] * 299 + color[1] * 587 + color[2] * 114,
                ),
            )
            mapping = {color: index for index, color in enumerate(ordered)}
            return [
                mapping[
                    (
                        image.pixelColor(x, y).red(),
                        image.pixelColor(x, y).green(),
                        image.pixelColor(x, y).blue(),
                        image.pixelColor(x, y).alpha(),
                    )
                ]
                for y in range(8)
                for x in range(8)
            ]
        result: list[int] = []
        for y in range(8):
            for x in range(8):
                color = image.pixelColor(x, y)
                if color.alpha() < 128:
                    result.append(0)
                else:
                    luminance = color.red() * 299 + color.green() * 587 + color.blue() * 114
                    result.append(min(3, luminance * 4 // 256000))
        return result

    def import_png(self) -> None:
        filename, _ = QFileDialog.getOpenFileName(
            self, "导入图块PNG", str(Path.cwd()), "PNG图像 (*.png);;所有文件 (*)"
        )
        if not filename:
            return
        try:
            self.canvas.set_pixels(self._image_pixels(QImage(filename)))
            self._update_preview()
        except Exception as error:
            self.show_error(error)

    def export_png(self) -> None:
        if self.project is None:
            return
        filename, _ = QFileDialog.getSaveFileName(
            self,
            "导出图块PNG",
            str(self.project.path.with_name(f"chr_{self.current_tile:04X}.png")),
            "PNG图像 (*.png)",
        )
        if not filename:
            return
        destination = Path(filename)
        if destination.suffix.lower() != ".png":
            destination = destination.with_suffix(".png")
        image = QImage(8, 8, QImage.Format.Format_ARGB32)
        for y in range(8):
            for x in range(8):
                image.setPixelColor(x, y, DISPLAY_COLORS[self.canvas.pixels[y * 8 + x]])
        if not image.save(str(destination), "PNG"):
            self.show_error(ValueError("PNG文件保存失败。"))

    def import_chr(self) -> None:
        if self.project is None:
            return
        filename, _ = QFileDialog.getOpenFileName(
            self, "导入CHR图块", str(Path.cwd()), "CHR图块数据 (*.chr *.bin);;所有文件 (*)"
        )
        if not filename:
            return
        try:
            source = Path(filename)
            payload = source.read_bytes()
            if not payload or len(payload) % 16:
                raise ValueError("文件长度必须是16字节的正整数倍。")
            tile_count = len(payload) // 16
            if self.current_tile + tile_count > self.project.chr_tile_count:
                raise ValueError("导入范围超出有效CHR-ROM。")
            answer = QMessageBox.question(
                self,
                "确认批量导入",
                f"将 {tile_count} 个图块写入 ${self.current_tile:04X}—"
                f"${self.current_tile + tile_count - 1:04X}。\n此操作可以撤销，是否继续？",
            )
            if answer != QMessageBox.StandardButton.Yes:
                return
            self.project.set_chr_range(self.current_tile, payload)
            self.project_changed.emit(
                f"已导入 {tile_count} 个CHR图块（起点 ${self.current_tile:04X}）"
            )
        except Exception as error:
            self.show_error(error)

    def export_chr(self) -> None:
        if self.project is None:
            return
        try:
            count = min(
                self.range_count.value(),
                self.project.chr_tile_count - self.current_tile,
            )
            payload = self.project.chr_codec.range_bytes(
                self.current_tile,
                count,
                bytes(self.project.working),
            )
            filename, _ = QFileDialog.getSaveFileName(
                self,
                "导出CHR图块",
                str(
                    self.project.path.with_name(
                        f"chr_{self.current_tile:04X}_{count}.chr"
                    )
                ),
                "CHR图块数据 (*.chr)",
            )
            if filename:
                destination = Path(filename)
                if destination.suffix.lower() != ".chr":
                    destination = destination.with_suffix(".chr")
                destination.write_bytes(payload)
        except Exception as error:
            self.show_error(error)
