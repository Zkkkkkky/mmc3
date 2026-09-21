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
from .workspace import default_export_path, writable_output_path


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


class ChrSheetCanvas(QWidget):
    """Compact 16x16 tile browser used to locate graphics before editing them."""

    tile_selected = Signal(int)

    def __init__(self) -> None:
        super().__init__()
        self.project = None
        self.page = 0
        self.selected_tile = 0
        self.cell_size = 18
        self.setFixedSize(self.sizeHint())
        self.setToolTip("单击图块即可在右侧放大编辑")

    def sizeHint(self) -> QSize:
        return QSize(self.cell_size * 16 + 1, self.cell_size * 16 + 1)

    def set_project(self, project) -> None:
        self.project = project
        self.update()

    def set_page(self, page: int) -> None:
        self.page = page
        self.update()

    def set_selected_tile(self, tile_index: int) -> None:
        self.selected_tile = tile_index
        self.update()

    def paintEvent(self, _event) -> None:
        painter = QPainter(self)
        painter.fillRect(self.rect(), QColor("#101820"))
        if self.project is None:
            return
        first_tile = self.page * 256
        last_tile = min(first_tile + 256, self.project.chr_tile_count)
        pixel_size = max(1, self.cell_size // 8)
        for tile_index in range(first_tile, last_tile):
            local = tile_index - first_tile
            tile_x = (local % 16) * self.cell_size + 1
            tile_y = (local // 16) * self.cell_size + 1
            pixels = self.project.chr_tile_pixels(tile_index)
            for y in range(8):
                for x in range(8):
                    painter.fillRect(
                        tile_x + x * pixel_size,
                        tile_y + y * pixel_size,
                        pixel_size,
                        pixel_size,
                        DISPLAY_COLORS[pixels[y * 8 + x]],
                    )
            if tile_index == self.selected_tile:
                painter.setPen(QPen(QColor("#19b5fe"), 2))
                painter.drawRect(
                    tile_x - 1,
                    tile_y - 1,
                    self.cell_size - 1,
                    self.cell_size - 1,
                )

    def mousePressEvent(self, event: QMouseEvent) -> None:
        if event.button() != Qt.MouseButton.LeftButton or self.project is None:
            return
        column = event.position().toPoint().x() // self.cell_size
        row = event.position().toPoint().y() // self.cell_size
        tile_index = self.page * 256 + row * 16 + column
        if 0 <= column < 16 and 0 <= row < 16 and tile_index < self.project.chr_tile_count:
            self.tile_selected.emit(tile_index)


class ChrGraphicsWidget(ProjectPage):
    def __init__(self) -> None:
        super().__init__()
        self.current_tile = 0

        layout = QHBoxLayout(self)
        browser_group = QGroupBox("CHR 图块浏览器")
        browser_layout = QVBoxLayout(browser_group)
        browser_row = QHBoxLayout()
        self.sheet_page = QSpinBox()
        self.sheet_page.setDisplayIntegerBase(16)
        self.sheet_page.setPrefix("$")
        self.sheet_page.valueChanged.connect(self._sheet_page_changed)
        browser_row.addWidget(QLabel("256图块页"))
        browser_row.addWidget(self.sheet_page)
        browser_row.addStretch()
        browser_layout.addLayout(browser_row)
        self.sheet = ChrSheetCanvas()
        self.sheet.tile_selected.connect(self._select_tile)
        browser_layout.addWidget(self.sheet, 0, Qt.AlignmentFlag.AlignHCenter)
        self.sheet_selection = QLabel("选择：—")
        self.sheet_selection.setObjectName("hintText")
        browser_layout.addWidget(self.sheet_selection)
        browser_layout.addStretch()
        layout.addWidget(browser_group)

        canvas_column = QVBoxLayout()
        canvas_label = QLabel("8×8 放大编辑")
        canvas_label.setObjectName("sectionTitle")
        canvas_column.addWidget(canvas_label)
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
        self.tile_index.valueChanged.connect(self._request_tile_change)
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
        self.sheet.set_project(self.project)
        if not enabled:
            self.location.setText("尚未载入ROM。")
            self.sheet_selection.setText("选择：—")
            return
        assert self.project is not None
        previous = min(self.current_tile, self.project.chr_tile_count - 1)
        page_count = max(1, (self.project.chr_tile_count + 255) // 256)
        self.sheet_page.blockSignals(True)
        self.sheet_page.setRange(0, page_count - 1)
        self.sheet_page.setValue(previous // 256)
        self.sheet_page.blockSignals(False)
        self.sheet.set_project(self.project)
        self.sheet.set_page(previous // 256)
        self.tile_index.blockSignals(True)
        self.tile_index.setRange(0, self.project.chr_tile_count - 1)
        self.tile_index.setValue(previous)
        self.tile_index.blockSignals(False)
        self._load_tile(previous)

    @property
    def has_pending_draft(self) -> bool:
        if self.project is None:
            return False
        return tuple(self.canvas.pixels) != self.project.chr_tile_pixels(
            self.current_tile
        )

    @property
    def pending_draft_error(self) -> str | None:
        if not self.has_pending_draft or self.project is None:
            return None
        try:
            self.project.chr_codec.encode_tile(self.canvas.pixels)
        except (TypeError, ValueError) as error:
            return str(error)
        return None

    def pending_draft_tile_bytes(self) -> tuple[int, bytes] | None:
        """Return the valid visible draft without mutating the project."""

        if not self.has_pending_draft or self.project is None:
            return None
        error = self.pending_draft_error
        if error is not None:
            raise ValueError(error)
        return (
            self.current_tile,
            self.project.chr_codec.encode_tile(self.canvas.pixels),
        )

    def range_bytes_with_pending_draft(
        self,
        first_tile: int,
        tile_count: int,
    ) -> bytes:
        """Read a CHR range and overlay the valid visible draft in memory."""

        if self.project is None:
            raise ValueError("尚未载入ROM。")
        payload = bytearray(
            self.project.chr_codec.range_bytes(
                first_tile,
                tile_count,
                bytes(self.project.working),
            )
        )
        draft = self.pending_draft_tile_bytes()
        if draft is not None:
            tile_index, tile_bytes = draft
            if first_tile <= tile_index < first_tile + tile_count:
                offset = (tile_index - first_tile) * 16
                payload[offset : offset + 16] = tile_bytes
        return bytes(payload)

    def commit_pending_changes(self) -> bool:
        if not self.has_pending_draft:
            return True
        if self.pending_draft_error is not None:
            return False
        return self.apply_tile()

    def _sync_selection_controls(self, tile_index: int) -> None:
        """Keep both selectors aligned without replacing the canvas draft."""

        page = tile_index // 256
        tile_was_blocked = self.tile_index.blockSignals(True)
        self.tile_index.setValue(tile_index)
        self.tile_index.blockSignals(tile_was_blocked)
        page_was_blocked = self.sheet_page.blockSignals(True)
        self.sheet_page.setValue(page)
        self.sheet_page.blockSignals(page_was_blocked)
        self.sheet.set_page(page)
        self.sheet.set_selected_tile(tile_index)

    def _request_tile_change(self, tile_index: int) -> bool:
        if tile_index == self.current_tile:
            self._sync_selection_controls(tile_index)
            return True
        if self.project is not None and self.has_pending_draft:
            # QSpinBox has already changed by the time this slot runs. Restore
            # the visible selection while the old tile draft is validated and
            # committed so a failed commit cannot strand mismatched controls.
            self._sync_selection_controls(self.current_tile)
            error = self.pending_draft_error
            if error is not None or not self.commit_pending_changes():
                self.show_error(
                    ValueError(
                        error
                        or self.pending_draft_error
                        or "当前CHR图块草稿提交失败，请修正后再切换。"
                    )
                )
                return False
        self._load_tile(tile_index)
        return True

    def _load_tile(self, tile_index: int) -> None:
        self.current_tile = tile_index
        if self.project is None:
            return
        self.canvas.set_pixels(self.project.chr_tile_pixels(tile_index))
        self._sync_selection_controls(tile_index)
        self.sheet_selection.setText(f"选择：图块 ${tile_index:04X}")
        offset = self.project.chr_codec.tile_offset(tile_index)
        bank = tile_index // 512
        within_bank = tile_index % 512
        self.location.setText(
            f"CHR 8 KiB Bank ${bank:02X} · Bank内图块 ${within_bank:03X} · "
            f"文件偏移 0x{offset:06X}"
        )
        self._update_preview()

    def _sheet_page_changed(self, page: int) -> None:
        if self.project is not None:
            self._select_tile(min(page * 256, self.project.chr_tile_count - 1))
        else:
            self.sheet.set_page(page)

    def _select_tile(self, tile_index: int) -> bool:
        if self.tile_index.value() == tile_index:
            return self._request_tile_change(tile_index)
        self.tile_index.setValue(tile_index)
        return self.current_tile == tile_index

    def _ink_changed(self) -> None:
        self.canvas.ink = int(self.ink.currentData())

    def _update_preview(self) -> None:
        if self.project is None:
            return
        try:
            raw = self.project.chr_codec.encode_tile(self.canvas.pixels)
        except (TypeError, ValueError) as error:
            self.hex_preview.setText(f"无效图块：{error}")
            return
        self.hex_preview.setText(raw.hex(" ").upper())

    def apply_tile(self) -> bool:
        if self.project is None:
            return False
        try:
            self.project.set_chr_tile_pixels(self.current_tile, self.canvas.pixels)
            self.sheet.update()
            self.project_changed.emit(f"已更新CHR图块 ${self.current_tile:04X}")
            return not self.has_pending_draft
        except Exception as error:
            self.show_error(error)
            return False

    def reset_tile(self) -> None:
        if self.project is None:
            return
        try:
            self.project.reset_chr_range(self.current_tile)
            self._load_tile(self.current_tile)
            self.sheet.update()
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
            str(default_export_path(f"chr_{self.current_tile:04X}.png")),
            "PNG图像 (*.png)",
        )
        if not filename:
            return
        destination = Path(filename)
        if destination.suffix.lower() != ".png":
            destination = destination.with_suffix(".png")
        try:
            destination = writable_output_path(destination)
        except Exception as error:
            self.show_error(error)
            return
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
            self.pending_draft_tile_bytes()
            answer = QMessageBox.question(
                self,
                "确认批量导入",
                f"将 {tile_count} 个图块写入 ${self.current_tile:04X}—"
                f"${self.current_tile + tile_count - 1:04X}。\n此操作可以撤销，是否继续？",
            )
            if answer != QMessageBox.StandardButton.Yes:
                return
            self._commit_pending_draft_for_range_import()
            self.project.set_chr_range(self.current_tile, payload)
            self._load_tile(self.current_tile)
            self.sheet.update()
            self.project_changed.emit(
                f"已导入 {tile_count} 个CHR图块（起点 ${self.current_tile:04X}）"
            )
        except Exception as error:
            self.show_error(error)

    def _commit_pending_draft_for_range_import(self) -> None:
        """Preserve a valid draft as the undo baseline before overwriting it."""

        draft = self.pending_draft_tile_bytes()
        if draft is None:
            return
        if not self.commit_pending_changes():
            raise ValueError(
                self.pending_draft_error
                or "当前CHR图块草稿无法提交，请修正后重试。"
            )

    def export_chr(self) -> None:
        if self.project is None:
            return
        try:
            count = min(
                self.range_count.value(),
                self.project.chr_tile_count - self.current_tile,
            )
            filename, _ = QFileDialog.getSaveFileName(
                self,
                "导出CHR图块",
                str(
                    default_export_path(f"chr_{self.current_tile:04X}_{count}.chr")
                ),
                "CHR图块数据 (*.chr)",
            )
            if not filename:
                return
            destination = Path(filename)
            if destination.suffix.lower() != ".chr":
                destination = destination.with_suffix(".chr")
            destination = writable_output_path(destination)
            payload = self.range_bytes_with_pending_draft(
                self.current_tile,
                count,
            )
            destination.write_bytes(payload)
            if not self.commit_pending_changes():
                raise ValueError(
                    self.pending_draft_error
                    or "当前CHR图块草稿无法提交，请修正后重试。"
                )
        except Exception as error:
            self.show_error(error)
