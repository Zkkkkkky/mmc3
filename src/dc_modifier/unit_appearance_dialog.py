from __future__ import annotations

from dataclasses import replace
from pathlib import Path

from PySide6.QtCore import QPoint, QRect, QSize, Qt, Signal
from PySide6.QtGui import QColor, QImage, QMouseEvent, QPainter, QPen, QPixmap
from PySide6.QtWidgets import (
    QApplication, QButtonGroup, QCheckBox, QComboBox, QDialog, QDialogButtonBox, QFileDialog, QGridLayout,
    QGroupBox, QHBoxLayout, QLabel, QMenu, QMessageBox, QPlainTextEdit,
    QPushButton, QSizePolicy, QSpinBox, QTabWidget, QVBoxLayout, QWidget,
)
from fc_editor.legacy_bitmap import LEGACY_MATERIAL_PALETTE_RGB, encode_legacy_bmp24

from .database_graphics import (
    decode_unit_body_script,
    decode_unit_fragment_script,
    palette_color,
    read_unit_appearance,
    render_chr_banks,
    render_tile_grid,
    render_unit_battle_preview,
)


WORK_PALETTE = tuple(QColor(*rgb) for rgb in LEGACY_MATERIAL_PALETTE_RGB)


def appearance_patch(project, unit_id: int, values: tuple[int, ...]):
    """Patch only the six palette bytes and the existing CHR references.

    The small record's following byte belongs to its neighbour; never write
    the normalised tenth byte from the expansion extractor into that slot.
    """
    appearance = read_unit_appearance(project, unit_id)
    count = 9 if appearance.configuration[0] & 0x80 else 8
    if len(values) != count:
        raise ValueError("配色/图库字段数与当前机体类型不符。")
    if any(type(value) is not int or not 0 <= value <= 0x3F for value in values[:6]):
        raise ValueError("配色索引必须在 $00—$3F 之间。")
    bank_count = project.chr_tile_count // 64
    if any(type(value) is not int or not 0 <= value < bank_count for value in values[6:]):
        raise ValueError("图库编号超出活动 CHR。")
    offset = appearance.file_offset + 1
    before = bytes(project.working[offset:offset + count])
    return offset, before, bytes(values)


class HexByteSpinBox(QSpinBox):
    def textFromValue(self, value: int) -> str:
        return f"{value:02X}"


def chr_bank_description(project, bank: int) -> str:
    """Show one CHR page in the three forms used by the legacy editor."""

    offset = project.chr_codec.tile_offset(bank * 64)
    return f"[${bank:02X}] 十进制 {bank:03d} · 文件偏移 0x{offset:06X}"


class ChrBankComboBox(QComboBox):
    """Legacy-style CHR address selector with all address forms in one field."""

    valueChanged = Signal(int)

    def __init__(self, project, maximum: int) -> None:
        super().__init__()
        self.project = project
        for bank in range(maximum + 1):
            offset = project.chr_codec.tile_offset(bank * 64)
            self.addItem(f"[{bank:02X}]{bank:03d}: {offset:06X}", bank)
        self.currentIndexChanged.connect(lambda _index: self.valueChanged.emit(self.value()))

    def value(self) -> int:
        return int(self.currentData())

    def setValue(self, value: int) -> None:
        index = self.findData(value)
        if index >= 0:
            self.setCurrentIndex(index)


class InteractivePreviewLabel(QLabel):
    """A scaled preview that reports positions in the unscaled game image."""

    image_pressed = Signal(int, int, int)
    menu_requested = Signal(QPoint)

    def __init__(self) -> None:
        super().__init__()
        self.source_width = 0
        self.source_height = 0

    def set_source_pixmap(self, pixmap: QPixmap, width: int, height: int) -> None:
        self.source_width = width
        self.source_height = height
        self.setPixmap(pixmap)

    def _source_position(self, event: QMouseEvent) -> tuple[int, int] | None:
        pixmap = self.pixmap()
        if pixmap is None or pixmap.isNull() or not self.source_width or not self.source_height:
            return None
        left = (self.width() - pixmap.width()) // 2
        top = (self.height() - pixmap.height()) // 2
        point = event.position().toPoint()
        if not (left <= point.x() < left + pixmap.width() and top <= point.y() < top + pixmap.height()):
            return None
        x = (point.x() - left) * self.source_width // pixmap.width()
        y = (point.y() - top) * self.source_height // pixmap.height()
        return x, y

    def mousePressEvent(self, event: QMouseEvent) -> None:
        position = self._source_position(event)
        if position is not None:
            self.image_pressed.emit(position[0], position[1], event.button().value)
        super().mousePressEvent(event)

    def contextMenuEvent(self, event) -> None:
        self.menu_requested.emit(event.globalPos())
        event.accept()


class CompactPageTabs(QTabWidget):
    """Hidden page switcher whose inactive tools do not enlarge the dialog."""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.currentChanged.connect(lambda _index: self.updateGeometry())

    def sizeHint(self) -> QSize:
        current = self.currentWidget()
        if current is None:
            return super().sizeHint()
        return current.sizeHint()

    def minimumSizeHint(self) -> QSize:
        current = self.currentWidget()
        if current is None:
            return super().minimumSizeHint()
        return current.minimumSizeHint()


class ChrTileCanvas(QWidget):
    """Small four-colour 8×8 editor matching the legacy CHR workflow."""

    def __init__(self, pixels: tuple[int, ...]) -> None:
        super().__init__()
        if len(pixels) != 64:
            raise ValueError("CHR 图块必须包含 64 个像素。")
        self.pixels = list(pixels)
        self.ink = 1
        self.cell_size = 30
        self.setFixedSize(self.sizeHint())

    def sizeHint(self) -> QSize:
        return QSize(self.cell_size * 8 + 1, self.cell_size * 8 + 1)

    def set_pixels(self, pixels) -> None:
        pixels = list(pixels)
        if len(pixels) != 64 or any(pixel not in range(4) for pixel in pixels):
            raise ValueError("导入图块必须是 8×8 四色像素。")
        self.pixels = pixels
        self.update()

    def paintEvent(self, _event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, False)
        for y in range(8):
            for x in range(8):
                rect = QRect(x * self.cell_size, y * self.cell_size, self.cell_size, self.cell_size)
                painter.fillRect(rect, WORK_PALETTE[self.pixels[y * 8 + x]])
                painter.setPen(QPen(QColor(70, 80, 90), 1))
                painter.drawRect(rect)

    def _cell(self, point: QPoint) -> tuple[int, int]:
        return point.x() // self.cell_size, point.y() // self.cell_size

    def _paint_at(self, point: QPoint) -> None:
        x, y = self._cell(point)
        if 0 <= x < 8 and 0 <= y < 8:
            self.pixels[y * 8 + x] = self.ink
            self.update(QRect(x * self.cell_size, y * self.cell_size, self.cell_size + 1, self.cell_size + 1))

    def mousePressEvent(self, event: QMouseEvent) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self._paint_at(event.position().toPoint())
        elif event.button() == Qt.MouseButton.RightButton:
            x, y = self._cell(event.position().toPoint())
            if 0 <= x < 8 and 0 <= y < 8:
                self.ink = self.pixels[y * 8 + x]

    def mouseMoveEvent(self, event: QMouseEvent) -> None:
        if event.buttons() & Qt.MouseButton.LeftButton:
            self._paint_at(event.position().toPoint())


class ChrTileEditorDialog(QDialog):
    """Edit/import/export one draft CHR tile without writing the ROM early."""

    def __init__(self, pixels: tuple[int, ...], title: str, parent=None) -> None:
        super().__init__(parent)
        self.original_pixels = tuple(pixels)
        self.setWindowTitle(title)
        root = QVBoxLayout(self)
        hint = QLabel("左键绘制，右键吸色；四色与旧修改器的图库工作色一致。")
        root.addWidget(hint)
        editor_row = QHBoxLayout()
        self.canvas = ChrTileCanvas(self.original_pixels)
        editor_row.addWidget(self.canvas)
        palette_group = QGroupBox("画笔")
        palette_layout = QVBoxLayout(palette_group)
        buttons = QButtonGroup(self)
        buttons.setExclusive(True)
        for index, color in enumerate(WORK_PALETTE):
            button = QPushButton(str(index))
            button.setCheckable(True)
            button.setFixedSize(84, 42)
            foreground = "#000000" if color.lightness() >= 128 else "#ffffff"
            button.setStyleSheet(
                f"QPushButton {{ background:{color.name()}; color:{foreground}; border:1px solid #555; }}"
                "QPushButton:checked { border:3px solid #ffd400; }"
            )
            button.clicked.connect(lambda _checked=False, ink=index: setattr(self.canvas, "ink", ink))
            buttons.addButton(button, index)
            palette_layout.addWidget(button)
        buttons.button(self.canvas.ink).setChecked(True)
        palette_layout.addStretch()
        editor_row.addWidget(palette_group)
        root.addLayout(editor_row)
        actions = QHBoxLayout()
        import_button = QPushButton("导入BMP…")
        export_button = QPushButton("导出BMP…")
        reset_button = QPushButton("还原打开时")
        import_button.clicked.connect(self._import_bitmap)
        export_button.clicked.connect(self._export_bitmap)
        reset_button.clicked.connect(lambda: self.canvas.set_pixels(self.original_pixels))
        actions.addWidget(import_button)
        actions.addWidget(export_button)
        actions.addWidget(reset_button)
        actions.addStretch()
        root.addLayout(actions)
        dialog_buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        dialog_buttons.button(QDialogButtonBox.StandardButton.Ok).setText("确定")
        dialog_buttons.button(QDialogButtonBox.StandardButton.Cancel).setText("取消")
        dialog_buttons.accepted.connect(self.accept)
        dialog_buttons.rejected.connect(self.reject)
        root.addWidget(dialog_buttons)

    def pixels(self) -> tuple[int, ...]:
        return tuple(self.canvas.pixels)

    def _import_bitmap(self) -> None:
        path, _filter = QFileDialog.getOpenFileName(
            self, "导入 8×8 图块", "", "BMP 图片 (*.bmp);;图片 (*.bmp *.png)"
        )
        if not path:
            return
        image = QImage(path)
        if image.isNull() or (image.width(), image.height()) != (8, 8):
            QMessageBox.warning(self, "无法导入", "单图块必须是 8×8 像素的 BMP 或 PNG。")
            return
        self.canvas.set_pixels(image_to_palette_pixels(image, WORK_PALETTE))

    def _export_bitmap(self) -> None:
        path, _filter = QFileDialog.getSaveFileName(
            self, "导出 8×8 图块", "chr-tile.bmp", "BMP 图片 (*.bmp)"
        )
        if not path:
            return
        destination = Path(path)
        if destination.suffix.lower() != ".bmp":
            destination = destination.with_suffix(".bmp")
        try:
            destination.write_bytes(self._bitmap_bytes())
        except OSError as error:
            QMessageBox.warning(self, "无法导出", f"无法写入 BMP：{error}")

    def _bitmap_bytes(self) -> bytes:
        pixels = (LEGACY_MATERIAL_PALETTE_RGB[index] for index in self.canvas.pixels)
        return encode_legacy_bmp24(8, 8, pixels)


class _DraftChrProject:
    def __init__(self, project, draft_tiles: dict[int, tuple[int, ...]]) -> None:
        self._project = project
        self._draft_tiles = draft_tiles

    def __getattr__(self, name):
        return getattr(self._project, name)

    def chr_tile_pixels(self, tile_index: int, *, original: bool = False):
        if not original and tile_index in self._draft_tiles:
            return self._draft_tiles[tile_index]
        return self._project.chr_tile_pixels(tile_index, original=original)


def encode_body_placements(placements) -> bytes:
    """Encode placements without changing their decoded coordinates or order."""

    if not placements:
        return b"\xFF"
    result = bytearray()
    cursor_x = cursor_y = 0
    for placement in placements:
        dx = placement.x - cursor_x
        dy = placement.y - cursor_y
        if not -128 <= dx <= 127 or not -128 <= dy <= 127:
            raise ValueError("主体图块间距超出拼图脚本的单字节范围。")
        result.extend((0xF3, dy & 0xFF, dx & 0xFF, placement.tile_index))
        cursor_x = placement.x + 1
        cursor_y = placement.y
    result.append(0xFF)
    return bytes(result)


def encode_fragment_placements(placements) -> bytes:
    """Encode absolute fragment placements using the verified $2E command."""

    if not placements:
        return bytes.fromhex("00 F0 00 00 FF")
    first = placements[0]
    raw_y = first.y - 0x80 - 1
    if not -128 <= first.x <= 127 or not -128 <= raw_y <= 127:
        raise ValueError("碎片起始坐标超出拼图脚本的单字节范围。")
    result = bytearray((first.x & 0xFF, raw_y & 0xFF, first.tile_index))
    for index, placement in enumerate(placements):
        flags = (0x40 if placement.flip_horizontal else 0) | (
            0x80 if placement.flip_vertical else 0
        )
        if index + 1 == len(placements):
            result.append(flags | 0x02)
            break
        following = placements[index + 1]
        dx = following.x - placement.x
        dy = following.y - placement.y
        if not -128 <= dx <= 127 or not -128 <= dy <= 127:
            raise ValueError("碎片图块间距超出拼图脚本的单字节范围。")
        result.extend((flags | 0x2E, following.tile_index, dx & 0xFF, dy & 0xFF))
    result.append(0xFF)
    return bytes(result)


def image_to_chr_pixels(image: QImage, colors: tuple[int, ...]) -> tuple[int, ...]:
    """Quantise an image to the active NES background plus three colours."""

    palette = (palette_color(0x0F), *(palette_color(value) for value in colors))
    return image_to_palette_pixels(image, palette)


def image_to_palette_pixels(image: QImage, palette) -> tuple[int, ...]:
    result: list[int] = []
    for y in range(image.height()):
        for x in range(image.width()):
            source = image.pixelColor(x, y)
            if source.alpha() < 128:
                result.append(0)
                continue
            result.append(min(range(4), key=lambda index: (
                (source.red() - palette[index].red()) ** 2
                + (source.green() - palette[index].green()) ** 2
                + (source.blue() - palette[index].blue()) ** 2
            )))
    return tuple(result)


def compress_image_for_chr(image: QImage, width: int, height: int) -> QImage:
    """Fit an arbitrary bitmap onto one fixed CHR sheet without distortion."""

    if image.isNull() or width <= 0 or height <= 0:
        raise ValueError("压缩上传需要有效图片和目标尺寸。")
    scaled = image.scaled(
        width,
        height,
        Qt.AspectRatioMode.KeepAspectRatio,
        Qt.TransformationMode.SmoothTransformation,
    )
    result = QImage(width, height, QImage.Format.Format_ARGB32)
    result.fill(palette_color(0x0F))
    painter = QPainter(result)
    painter.drawImage((width - scaled.width()) // 2, (height - scaled.height()) // 2, scaled)
    painter.end()
    return result


def choose_body_layout(width: int, height: int) -> tuple[int, int]:
    """Choose the legacy body grid whose aspect ratio best matches an image."""

    if width <= 0 or height <= 0:
        raise ValueError("图片尺寸无效。")
    layouts = ((8, 8), (7, 9), (9, 7), (10, 6))
    return min(
        layouts,
        key=lambda layout: abs(width * layout[1] - height * layout[0])
        / (width * layout[1] + height * layout[0]),
    )


def _draw_scaled_grid(painter: QPainter, width: int, height: int, spacing: int) -> None:
    painter.setPen(QPen(QColor(196, 210, 220, 220), 1))
    for x in range(0, width, spacing):
        painter.drawLine(x, 0, x, height - 1)
    for y in range(0, height, spacing):
        painter.drawLine(0, y, width - 1, y)


def _scaled_tile_grid(image: QImage, target_size: int) -> QImage:
    result = image.scaled(
        target_size,
        target_size,
        Qt.AspectRatioMode.IgnoreAspectRatio,
        Qt.TransformationMode.FastTransformation,
    )
    painter = QPainter(result)
    _draw_scaled_grid(painter, target_size, target_size, target_size // 16)
    painter.end()
    return result


def numbered_library_image(image: QImage, selected_tile: int) -> QImage:
    """Scale a raw vertical library and overlay readable local tile numbers."""

    scale = 3
    result = image.scaled(
        image.width() * scale,
        image.height() * scale,
        Qt.AspectRatioMode.IgnoreAspectRatio,
        Qt.TransformationMode.FastTransformation,
    )
    painter = QPainter(result)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing, False)
    font = painter.font()
    font.setPixelSize(8)
    font.setBold(True)
    painter.setFont(font)
    tile_count = image.width() // 8 * (image.height() // 8)
    columns = image.width() // 8
    for tile in range(tile_count):
        x = tile % columns * 8 * scale
        y = tile // columns * 8 * scale
        painter.fillRect(x, y, 16, 10, QColor(0, 0, 0, 72))
        painter.setPen(QColor("#ffffff"))
        painter.drawText(x + 1, y + 8, f"{tile:02X}")
    _draw_scaled_grid(painter, result.width(), result.height(), 8 * scale)
    selected_x = selected_tile % columns * 8 * scale
    selected_y = selected_tile // columns * 8 * scale
    painter.setPen(QPen(QColor("#ff3048"), 2))
    painter.drawRect(selected_x, selected_y, 8 * scale - 1, 8 * scale - 1)
    painter.end()
    return result


def selected_library_image(image: QImage, selected_tile: int) -> QImage:
    result = render_tile_grid(image)
    columns = image.width() // 8
    painter = QPainter(result)
    painter.setPen(QPen(QColor("#ff3048"), 1))
    painter.drawRect(
        selected_tile % columns * 8,
        selected_tile // columns * 8,
        7,
        7,
    )
    painter.end()
    return result


def legacy_body_library_image(
    image: QImage, selected_tile: int, *, show_numbers: bool
) -> QImage:
    """Render the body banks as two joined legacy 8×8 library pages."""

    scale = 3
    tile_size = 8 * scale
    result = QImage(64 * scale, 128 * scale, QImage.Format.Format_RGB32)
    result.fill(WORK_PALETTE[0])
    painter = QPainter(result)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing, False)
    painter.drawImage(
        0,
        0,
        image.scaled(
            64 * scale,
            min(image.height(), 128) * scale,
            Qt.AspectRatioMode.IgnoreAspectRatio,
            Qt.TransformationMode.FastTransformation,
        ),
    )
    if show_numbers:
        font = painter.font()
        font.setPixelSize(8)
        font.setBold(True)
        painter.setFont(font)
        for tile in range(min(128, image.width() // 8 * image.height() // 8)):
            x = tile % 8 * tile_size
            y = tile // 8 * tile_size
            painter.fillRect(x, y, 16, 10, QColor(0, 0, 0, 72))
            painter.setPen(QColor("#ffffff"))
            painter.drawText(x + 1, y + 8, f"{tile:02X}")
    _draw_scaled_grid(painter, result.width(), result.height(), tile_size)
    selected_x = selected_tile % 8 * tile_size
    selected_y = selected_tile // 8 * tile_size
    painter.setPen(QPen(QColor("#ff3048"), 2))
    painter.drawRect(selected_x, selected_y, tile_size - 1, tile_size - 1)
    painter.end()
    return result


def numbered_composition_image(
    image: QImage,
    appearance,
    target_size: int = 384,
    *,
    include_fragments: bool = True,
) -> QImage:
    """Overlay the actual body/fragment tile IDs like the legacy inspector."""

    source_width = image.width()
    source_height = image.height()
    result = image.scaled(
        target_size,
        target_size,
        Qt.AspectRatioMode.IgnoreAspectRatio,
        Qt.TransformationMode.FastTransformation,
    )
    scale_x = result.width() / source_width
    scale_y = result.height() / source_height
    painter = QPainter(result)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing, False)
    font = painter.font()
    font.setPixelSize(8)
    font.setBold(True)
    painter.setFont(font)

    def draw_number(tile_index: int, x: int, y: int) -> None:
        if x <= -8 or y <= -7 or x >= source_width or y >= source_height:
            return
        label_rect = QRect(
            max(0, round(x * scale_x)),
            max(0, round(y * scale_y)),
            18,
            11,
        )
        painter.fillRect(label_rect, QColor(0, 0, 0, 72))
        painter.setPen(QColor("#ffdf00"))
        painter.drawText(
            label_rect,
            Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignVCenter,
            f"{tile_index:02X}",
        )

    body_origin_x = 15 if appearance.configuration[0] & 0x40 else 0
    for placement in decode_unit_body_script(
        appearance.body_script, len(appearance.secondary_banks) * 64
    ):
        draw_number(
            placement.tile_index,
            (placement.x + body_origin_x) * 8,
            (placement.y + 15) * 8,
        )
    if include_fragments:
        fragment_origin_x = 0x78 if appearance.configuration[0] & 0x40 else 0
        for placement in decode_unit_fragment_script(appearance.fragment_script):
            draw_number(
                placement.tile_index,
                placement.x + fragment_origin_x,
                placement.y,
            )
    _draw_scaled_grid(painter, result.width(), result.height(), target_size // 16)
    painter.end()
    return result


def legacy_composition_image(
    image: QImage,
    appearance,
    *,
    show_numbers: bool,
    include_fragments: bool = True,
    target_size: int = 384,
) -> QImage:
    """Render the old modifier's square grid and red battle-origin guides."""

    if show_numbers:
        result = numbered_composition_image(
            image,
            appearance,
            target_size,
            include_fragments=include_fragments,
        )
    else:
        result = _scaled_tile_grid(image, target_size)
    painter = QPainter(result)
    painter.setPen(QPen(QColor("#ff2038"), 2))
    guide_x = round(104 * target_size / image.width())
    guide_y = round(24 * target_size / image.height())
    painter.drawLine(guide_x, 0, guide_x, target_size - 1)
    painter.drawLine(0, guide_y, target_size - 1, guide_y)
    painter.end()
    return result


def parse_hex_script(text: str, label: str) -> bytes:
    compact = text.replace(",", " ").replace("\n", " ").strip()
    try:
        values = bytes(int(part.removeprefix("$").removeprefix("0x"), 16)
                       for part in compact.split())
    except ValueError as error:
        raise ValueError(f"{label}只能包含以空格分隔的两位十六进制字节。") from error
    if not values:
        raise ValueError(f"{label}不能为空。")
    return values


def move_body_script(script: bytes, dx: int, dy: int) -> bytes:
    """Adjust or prepend one verified F3 move without rewriting tile commands."""

    if not -128 <= dx <= 127 or not -128 <= dy <= 127:
        raise ValueError("主体移动量超出单字节范围。")
    if script.startswith(b"\xF3") and len(script) >= 4:
        current_y = ((script[1] + 128) % 256) - 128
        current_x = ((script[2] + 128) % 256) - 128
        new_x, new_y = current_x + dx, current_y + dy
        if not -128 <= new_x <= 127 or not -128 <= new_y <= 127:
            raise ValueError("主体移动后坐标超出单字节范围。")
        return bytes((0xF3, new_y & 0xFF, new_x & 0xFF)) + script[3:]
    prefix = bytes((0xF3, dy & 0xFF, dx & 0xFF))
    return prefix + script


def move_fragment_script(script: bytes, dx: int, dy: int) -> bytes:
    if len(script) < 4:
        raise ValueError("碎片拼图脚本不完整。")
    x = ((script[0] + 128) % 256) - 128 + dx
    y = ((script[1] + 128) % 256) - 128 + dy
    if not -128 <= x <= 127 or not -128 <= y <= 127:
        raise ValueError("碎片移动后坐标超出单字节范围。")
    return bytes((x & 0xFF, y & 0xFF)) + script[2:]


def flip_fragment_script(script: bytes, mask: int) -> bytes:
    """Toggle the renderer flags on every draw command, preserving parameters."""

    result = bytearray(script)
    cursor = 3
    parameter_counts = {
        0x02: 0, 0x03: 0, 0x06: 1, 0x07: 1, 0x0A: 1, 0x0B: 1,
        0x0E: 2, 0x0F: 2, 0x22: 1, 0x23: 1, 0x26: 2, 0x27: 2,
        0x2A: 2, 0x2B: 2, 0x2E: 3, 0x2F: 3,
    }
    while cursor < len(result):
        command = result[cursor]
        if command == 0xFF:
            return bytes(result)
        count = parameter_counts.get(command & 0x3F)
        if count is None or cursor + count >= len(result):
            raise ValueError(f"碎片拼图包含未验证指令 ${command:02X}。")
        result[cursor] ^= mask
        cursor += count + 1
    raise ValueError("碎片拼图缺少 FF 结束码。")


class UnitAppearanceDialog(QDialog):
    """A local draft; writing on OK remains part of the database transaction."""

    _tile_clipboard: tuple[int, ...] | None = None
    _library_clipboard: tuple[tuple[int, ...], ...] | None = None

    def __init__(self, project, unit_id: int, parent=None) -> None:
        super().__init__(parent)
        self.project = project
        self.unit_id = unit_id
        self.appearance = read_unit_appearance(project, unit_id)
        self.body_script = self.appearance.body_script
        self.fragment_script = self.appearance.fragment_script
        self._draft_tiles: dict[int, tuple[int, ...]] = {}
        self._original_draft_tiles: dict[int, tuple[int, ...]] = {}
        self._selected_body_tile = 0
        self._selected_fragment_tile = 0
        self.setWindowTitle("机体拼图")
        self.setFixedSize(730, 708)
        self.setWindowFlag(Qt.WindowType.WindowMaximizeButtonHint, False)
        self.changed = False
        root = QVBoxLayout(self)
        hint = QLabel(
            "修改当前外观记录的图库与拼图脚本；颜色请在数据库机体页调整。"
            "共用这条外观记录的机体会一起变化，碎片与物理武器仍共用图库。"
        )
        hint.setWordWrap(True)
        hint.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        self.hint = hint
        hint.hide()
        self.palette_values = tuple(self.appearance.configuration[1:7])
        self.editors: list[QSpinBox] = []
        self.color_swatches = []
        self.color_buttons = self.color_swatches
        reference_code_row = QHBoxLayout()
        reference_group = QGroupBox("参考设置")
        bank_form = QGridLayout(reference_group)
        bank_form.setHorizontalSpacing(6)
        bank_form.setVerticalSpacing(4)
        bank_form.addWidget(QLabel("机体类型"), 0, 0)
        self.unit_type_editor = QComboBox()
        self.unit_type_editor.setEditable(False)
        for label, code in (
            ("我方小型机", 0x00), ("敌方小型机", 0x40),
            ("我方大型机", 0x80), ("敌方大型机", 0xC0),
        ):
            self.unit_type_editor.addItem(label, code)
        self.unit_type_editor.setCurrentIndex(
            self.unit_type_editor.findData(self.appearance.configuration[0] & 0xC0)
        )
        self.unit_type_editor.setToolTip("控制敌我方向及主体图库数量；大型机启用图库2。")
        bank_form.addWidget(self.unit_type_editor, 0, 1, 1, 2)
        labels = ("碎片图库（2 KiB 偶数页对）", "图库地址1", "图库地址2")
        self.bank_labels: list[QLabel] = []
        self.bank_descriptions: list[QLabel] = []
        self.bank_editors: list[ChrBankComboBox] = []
        bank_max = min(255, project.chr_tile_count // 64 - 1)
        for index in range(7, 10):
            editor = ChrBankComboBox(project, bank_max)
            initial = (
                self.appearance.configuration[index]
                if index < 9 or self.appearance.configuration[0] & 0x80
                else 0
            )
            editor.setValue(initial)
            label = QLabel(labels[index - 7])
            description = QLabel(chr_bank_description(project, editor.value()))
            description.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
            description.setToolTip(chr_bank_description(project, editor.value()))
            description.hide()
            if index > 7:
                row_index = index - 7
                bank_form.addWidget(label, row_index, 0)
                bank_form.addWidget(editor, row_index, 1, 1, 2)
            self.bank_labels.append(label)
            self.bank_descriptions.append(description)
            self.bank_editors.append(editor)
            self.editors.append(editor)
        for editor in (self.unit_type_editor, *self.bank_editors[1:]):
            editor.setFixedSize(128, 22)
        reference_group.setFixedWidth(218)
        reference_code_row.addWidget(reference_group, 2)

        body_code_group = QGroupBox("代码编辑")
        body_code_layout = QVBoxLayout(body_code_group)
        self.body_script_view = QPlainTextEdit()
        self.body_script_view.setLineWrapMode(QPlainTextEdit.LineWrapMode.WidgetWidth)
        self.body_script_view.setPlainText(self.appearance.body_script.hex(" ").upper())
        self.body_script_view.setMaximumHeight(66)
        body_script_font = self.body_script_view.font()
        body_script_font.setPointSize(8)
        self.body_script_view.setFont(body_script_font)
        body_code_layout.addWidget(self.body_script_view)
        body_code_actions = QHBoxLayout()
        clear_body_quick = QPushButton("清除")
        clear_body_quick.setFixedSize(44, 22)
        clear_body_quick.clicked.connect(lambda: self._replace_script("body", b"\xFF"))
        body_code_actions.addWidget(clear_body_quick)
        for width, height in ((8, 8), (7, 9), (9, 7), (10, 6)):
            button = QPushButton(f"{width}×{height}")
            button.setFixedSize(44, 22)
            button.setToolTip("按旧版模板用当前图库的连续图块重建主体拼图")
            button.clicked.connect(
                lambda _checked=False, w=width, h=height: self._apply_body_grid(w, h)
            )
            body_code_actions.addWidget(button)
        validate_body = QPushButton("查看效果")
        validate_body.setFixedSize(56, 22)
        validate_body.clicked.connect(self.apply_script_text)
        body_code_actions.addWidget(validate_body)
        body_code_layout.addLayout(body_code_actions)
        reference_code_row.addWidget(body_code_group, 3)
        root.addLayout(reference_code_row)
        preview_tabs = CompactPageTabs()
        preview_tabs.tabBar().hide()
        preview_tabs.setDocumentMode(True)
        preview_tabs.setStyleSheet("QTabWidget::pane { border: 0; }")
        preview_tabs.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Expanding)
        root.addWidget(preview_tabs, 1)

        body_tab = QWidget()
        body_grid = QGridLayout(body_tab)
        body_grid.setContentsMargins(0, 0, 0, 0)
        body_grid.setHorizontalSpacing(4)
        body_grid.setVerticalSpacing(0)

        library_group = QGroupBox("图库（提示：左键选择图块）")
        legacy_frame_style = (
            "QGroupBox { border:1px solid #249fd7; margin-top:8px; }"
            "QGroupBox::title { subcontrol-origin:margin; left:8px; padding:0 3px; }"
        )
        library_group.setStyleSheet(legacy_frame_style)
        library_group.setFixedSize(210, 523)
        library_layout = QVBoxLayout(library_group)
        library_layout.setContentsMargins(4, 5, 4, 7)
        library_layout.setSpacing(4)
        library_layout.setAlignment(Qt.AlignmentFlag.AlignTop)
        self.body_selection = QLabel("当前选择的图块编号：00")
        self.body_selection.setStyleSheet("color:#d00000; font-weight:600;")
        library_layout.addWidget(self.body_selection)
        library_layout.addSpacing(43)
        self.body_library_preview = InteractivePreviewLabel()
        self.body_composition_preview = InteractivePreviewLabel()
        for preview in (self.body_library_preview, self.body_composition_preview):
            preview.setAlignment(Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignTop)
            preview.setStyleSheet("background:black; border:1px solid #333;")
        self.body_library_preview.setFixedSize(192, 384)
        self.body_composition_preview.setFixedSize(384, 384)
        library_layout.addWidget(
            self.body_library_preview, 0, Qt.AlignmentFlag.AlignHCenter
        )
        body_tools = QHBoxLayout()
        body_tools.setSpacing(8)
        self.show_tile_numbers = QCheckBox("显示图块编号")
        self.show_tile_numbers.toggled.connect(self.refresh_preview)
        body_tools.addWidget(self.show_tile_numbers)
        self.swap_body_library = QCheckBox("调换图库拼图")
        self.swap_body_library.setEnabled(self._is_large())
        self.swap_body_library.setToolTip(
            "大型机勾选后切换到机体图库2；图块编号自动使用 $40—$7F。"
        )
        self.swap_body_library.toggled.connect(self._swap_body_library_toggled)
        body_tools.addWidget(self.swap_body_library)
        library_layout.addLayout(body_tools)
        self.body_library_group = library_group
        body_grid.addWidget(library_group, 0, 0)

        composition_group = QGroupBox("效果图（提示：左键编辑图块，右键删除图块）")
        composition_group.setStyleSheet(legacy_frame_style)
        composition_group.setFixedSize(478, 523)
        composition_grid = QGridLayout(composition_group)
        composition_grid.setContentsMargins(4, 5, 4, 7)
        composition_grid.setHorizontalSpacing(8)
        composition_grid.setVerticalSpacing(4)
        composition_grid.setRowMinimumHeight(0, 24)
        composition_grid.setRowMinimumHeight(1, 384)
        composition_grid.setRowMinimumHeight(2, 24)
        composition_grid.setColumnMinimumWidth(0, 24)
        composition_grid.setColumnMinimumWidth(1, 384)
        composition_grid.setColumnMinimumWidth(2, 24)
        composition_grid.addWidget(self.body_composition_preview, 1, 1)
        self.body_move_buttons: dict[str, QPushButton] = {}
        for key, caption, dx, dy, row_index, column_index in (
            ("up", "向上移动", 0, -1, 0, 1),
            ("left", "向\n左\n移\n动", -1, 0, 1, 0),
            ("right", "向\n右\n移\n动", 1, 0, 1, 2),
            ("down", "向下移动", 0, 1, 2, 1),
        ):
            button = QPushButton(caption)
            button.setToolTip("按一个 8×8 图块移动主体拼图")
            button.clicked.connect(
                lambda _checked=False, x=dx, y=dy: self._move_body(x, y)
            )
            if key in ("left", "right"):
                button.setFixedSize(24, 168)
                button.setStyleSheet("padding:0;")
            else:
                button.setFixedSize(134, 24)
            composition_grid.addWidget(
                button, row_index, column_index, Qt.AlignmentFlag.AlignCenter
            )
            self.body_move_buttons[key] = button
        self.body_composition_group = composition_group
        body_grid.addWidget(composition_group, 0, 1)
        self.body_import_button = QPushButton("导入BMP…")
        self.body_import_button.setToolTip("导入任意尺寸图片，自动压缩、切分图块并生成主体拼图代码")
        self.body_import_button.clicked.connect(lambda: self._import_library("body"))
        self.body_import_button.hide()
        self.body_export_button = QPushButton("导出BMP…")
        self.body_export_button.setToolTip("导出当前显示的 64×64 主体图库")
        self.body_export_button.clicked.connect(lambda: self._export_library("body"))
        self.body_export_button.hide()
        body_grid.setColumnStretch(0, 0)
        body_grid.setColumnStretch(1, 1)
        preview_tabs.addTab(body_tab, "战斗合成")

        fragment_tab = QWidget()
        fragment_layout = QVBoxLayout(fragment_tab)
        fragment_reference = QGroupBox("碎片图库设置")
        fragment_reference_layout = QHBoxLayout(fragment_reference)
        fragment_reference_layout.addWidget(self.bank_labels[0])
        fragment_reference_layout.addWidget(self.bank_editors[0])
        fragment_reference_layout.addStretch()
        fragment_layout.addWidget(fragment_reference)
        fragment_hint = QLabel(
            "这里仅显示碎片图库的全部原始图块，并使用碎片三色；"
            "左键选择图块，右键导入、复制、粘贴、删除或清空。"
            "它不是机体主体的一部分，也不应与主体三色逐项相同。"
        )
        fragment_hint.setWordWrap(True)
        fragment_layout.addWidget(fragment_hint)
        self.fragment_library_preview = InteractivePreviewLabel()
        self.fragment_library_preview.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.fragment_library_preview.setStyleSheet("background:black; border:1px solid #333;")
        self.fragment_library_preview.setMinimumHeight(360)
        fragment_layout.addWidget(self.fragment_library_preview, 1)
        self.fragment_placements_view = QPlainTextEdit()
        self.fragment_placements_view.setReadOnly(True)
        self.fragment_placements_view.setMaximumHeight(116)
        self.fragment_placements_view.setToolTip("由当前碎片脚本实时解码的图块、坐标与翻转状态")
        fragment_layout.addWidget(self.fragment_placements_view)
        fragment_tools = QGridLayout()
        self.show_fragment_numbers = QCheckBox("显示图块编号")
        self.show_fragment_numbers.toggled.connect(self.refresh_preview)
        fragment_tools.addWidget(self.show_fragment_numbers, 0, 0)
        self.fragment_selection = QLabel("已选碎片图块 $00")
        fragment_tools.addWidget(self.fragment_selection, 0, 1, 1, 3)
        for column, (caption, dx, dy) in enumerate(
            (("←", -1, 0), ("→", 1, 0), ("↑", 0, -1), ("↓", 0, 1))
        ):
            button = QPushButton(caption)
            button.setFixedWidth(42)
            button.setToolTip("按 1 像素移动整组碎片")
            button.clicked.connect(lambda _checked=False, x=dx, y=dy: self._move_fragment(x, y))
            fragment_tools.addWidget(button, 1, column)
        horizontal_quick = QPushButton("水平翻转")
        vertical_quick = QPushButton("垂直翻转")
        horizontal_quick.clicked.connect(lambda: self._flip_fragment(0x40))
        vertical_quick.clicked.connect(lambda: self._flip_fragment(0x80))
        fragment_tools.addWidget(horizontal_quick, 1, 4)
        fragment_tools.addWidget(vertical_quick, 1, 5)
        self.fragment_import_button = QPushButton("导入BMP…")
        self.fragment_import_button.setToolTip("导入图块或完整碎片图库，其他尺寸会自动压缩")
        self.fragment_import_button.clicked.connect(lambda: self._import_library("fragment"))
        fragment_tools.addWidget(self.fragment_import_button, 1, 6)
        self.fragment_export_button = QPushButton("导出BMP…")
        self.fragment_export_button.setToolTip("导出完整 64×128 碎片图库")
        self.fragment_export_button.clicked.connect(lambda: self._export_library("fragment"))
        fragment_tools.addWidget(self.fragment_export_button, 1, 7)
        fragment_tools.setColumnStretch(8, 1)
        fragment_layout.addLayout(fragment_tools)
        preview_tabs.addTab(fragment_tab, "碎片原始图库")

        script_tab = QWidget()
        script_layout = QGridLayout(script_tab)
        script_layout.addWidget(QLabel("主体拼图脚本已移到窗口顶部，可与效果图同时查看。"), 0, 0)
        script_layout.addWidget(QLabel("碎片拼图脚本"), 0, 1)
        body_script_note = QLabel("使用顶部“主体代码编辑”及其模板按钮。")
        body_script_note.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.fragment_script_view = QPlainTextEdit()
        self.fragment_script_view.setLineWrapMode(QPlainTextEdit.LineWrapMode.WidgetWidth)
        self.fragment_script_view.setPlainText(self.appearance.fragment_script.hex(" ").upper())
        script_layout.addWidget(body_script_note, 1, 0)
        script_layout.addWidget(self.fragment_script_view, 1, 1)
        fragment_actions = QHBoxLayout()
        refresh_scripts = QPushButton("验证脚本并刷新效果")
        refresh_scripts.clicked.connect(self.apply_script_text)
        script_layout.addWidget(refresh_scripts, 2, 0)
        clear_fragment = QPushButton("清除碎片")
        clear_fragment.clicked.connect(
            lambda: self._replace_script("fragment", bytes.fromhex("00 F0 00 00 FF"))
        )
        fragment_actions.addWidget(clear_fragment)
        for caption, dx, dy in (("←", -1, 0), ("→", 1, 0), ("↑", 0, -1), ("↓", 0, 1)):
            button = QPushButton(caption)
            button.setToolTip("碎片按 1 像素移动")
            button.clicked.connect(
                lambda _checked=False, x=dx, y=dy: self._move_fragment(x, y)
            )
            fragment_actions.addWidget(button)
        horizontal = QPushButton("水平翻转")
        vertical = QPushButton("垂直翻转")
        horizontal.clicked.connect(lambda: self._flip_fragment(0x40))
        vertical.clicked.connect(lambda: self._flip_fragment(0x80))
        fragment_actions.addWidget(horizontal)
        fragment_actions.addWidget(vertical)
        fragment_actions.addStretch()
        script_layout.addLayout(fragment_actions, 2, 1)
        preview_tabs.addTab(script_tab, "拼图脚本原码")
        self.preview_tabs = preview_tabs
        self.previews = (
            self.body_library_preview,
            self.body_composition_preview,
            self.fragment_library_preview,
        )
        self.status = QLabel()
        self.status.setWordWrap(True)
        self.status.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        self.status.hide()
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.button(QDialogButtonBox.StandardButton.Ok).setText("确定")
        buttons.button(QDialogButtonBox.StandardButton.Cancel).setText("取消")
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        root.addWidget(buttons)
        for editor in self.editors:
            editor.valueChanged.connect(self.refresh_preview)
        self.unit_type_editor.currentIndexChanged.connect(self._type_changed)
        self.body_library_preview.image_pressed.connect(
            lambda x, y, _button: self._select_library_tile("body", x, y)
        )
        self.fragment_library_preview.image_pressed.connect(
            lambda x, y, _button: self._select_library_tile("fragment", x, y)
        )
        self.body_library_preview.menu_requested.connect(
            lambda point: self._show_library_menu("body", point)
        )
        self.fragment_library_preview.menu_requested.connect(
            lambda point: self._show_library_menu("fragment", point)
        )
        self.body_composition_preview.image_pressed.connect(self._composition_pressed)
        self._last_composition_point = (0, 0)
        self._type_changed()
        self.refresh_preview()

    def values(self) -> tuple[int, ...]:
        bank_values = tuple(editor.value() for editor in self.bank_editors)
        return (*self.palette_values, *bank_values[:3 if self._is_large() else 2])

    def _type_code(self) -> int:
        index = self.unit_type_editor.currentIndex()
        text = self.unit_type_editor.currentText().strip()
        if index >= 0 and text == self.unit_type_editor.itemText(index):
            return int(self.unit_type_editor.itemData(index))
        labels = {
            self.unit_type_editor.itemText(item): int(self.unit_type_editor.itemData(item))
            for item in range(self.unit_type_editor.count())
        }
        return labels.get(text, int(self.unit_type_editor.currentData() or 0))

    def _is_large(self) -> bool:
        return bool(self._type_code() & 0x80)

    def _type_changed(self, _index: int = -1) -> None:
        large = self._is_large()
        if large and self.bank_editors[2].value() == 0:
            self.bank_editors[2].setValue(
                min(self.bank_editors[1].value() + 1, self.bank_editors[2].count() - 1)
            )
        self.bank_editors[2].setEnabled(large)
        self.bank_descriptions[2].setEnabled(large)
        self.swap_body_library.setEnabled(large)
        rebuilt_for_small = False
        if not large:
            self.swap_body_library.setChecked(False)
            try:
                decode_unit_body_script(self.body_script, 64)
            except ValueError:
                # A large-unit script may address $40-$7F from its second
                # body bank.  A small unit has no way to render those tiles,
                # so start from the legacy one-bank template instead of
                # leaving the dialog in an invalid, non-previewable state.
                self._apply_body_grid(8, 8)
                rebuilt_for_small = True
        self.refresh_preview()
        if rebuilt_for_small:
            self.status.setText(
                "已切换为小型机；原拼图引用了图库2，已自动重建为8×8单图库脚本。"
                "确定后才写入ROM。"
            )

    def apply_script_text(self) -> None:
        try:
            body = parse_hex_script(self.body_script_view.toPlainText(), "主体拼图脚本")
            fragment = parse_hex_script(
                self.fragment_script_view.toPlainText(), "碎片拼图脚本"
            )
            decode_unit_body_script(body, len(self.values()[7:]) * 64)
            decode_unit_fragment_script(fragment)
            self.body_script = body
            self.fragment_script = fragment
            self.refresh_preview()
            self.status.setText(self.status.text() + " 脚本已验证，尚未写入ROM。")
        except ValueError as error:
            QMessageBox.warning(self, "拼图脚本无效", str(error))

    def _replace_script(self, kind: str, script: bytes) -> None:
        if kind == "body":
            self.body_script = script
            self.body_script_view.setPlainText(script.hex(" ").upper())
        else:
            self.fragment_script = script
            self.fragment_script_view.setPlainText(script.hex(" ").upper())
        self.refresh_preview()

    def _move_body(self, dx: int, dy: int) -> None:
        self._replace_script("body", move_body_script(self.body_script, dx, dy))

    def _apply_body_grid(self, width: int, height: int) -> None:
        """Apply one legacy continuous-tile body layout to the visible bank."""

        first_tile = self._body_display_offset()
        count = min(width * height, 64)
        start_x = -width + 1 if self._type_code() & 0x40 else 0
        start_y = -height + 1
        script = bytes((
            0xF3, start_y & 0xFF, start_x & 0xFF,
            0xFD, 0x20, width,
            0xF9, count, first_tile,
            0xFF,
        ))
        self._replace_script("body", script)

    def _body_display_offset(self) -> int:
        return 64 if len(self._library_banks("body")) > 1 and self.swap_body_library.isChecked() else 0

    def _swap_body_library_toggled(self, checked: bool) -> None:
        self._selected_body_tile = (64 if checked else 0) + self._selected_body_tile % 64
        self.body_selection.setText(
            f"当前选择的图块编号：{self._selected_body_tile:02X}"
        )
        self.refresh_preview()

    def _move_fragment(self, dx: int, dy: int) -> None:
        self._replace_script(
            "fragment", move_fragment_script(self.fragment_script, dx, dy)
        )

    def _flip_fragment(self, mask: int) -> None:
        try:
            self._replace_script(
                "fragment", flip_fragment_script(self.fragment_script, mask)
            )
        except ValueError as error:
            QMessageBox.warning(self, "无法翻转碎片", str(error))

    def _draft_project(self):
        return _DraftChrProject(self.project, self._draft_tiles)

    def _library_banks(self, kind: str) -> tuple[int, ...]:
        values = self.values()
        if kind == "body":
            return tuple(values[7:])
        first = values[6] & 0xFE
        return first, first + 1

    def _library_colors(self, kind: str) -> tuple[int, ...]:
        values = self.values()
        return tuple(values[:3] if kind == "body" else values[3:6])

    def _selected_local_tile(self, kind: str) -> int:
        return self._selected_body_tile if kind == "body" else self._selected_fragment_tile

    def _library_local_indices(self, kind: str) -> tuple[int, ...]:
        if kind == "body":
            first = self._body_display_offset()
            return tuple(range(first, first + 64))
        return tuple(range(128))

    def _absolute_tile(self, kind: str, local_tile: int | None = None) -> int:
        local_tile = self._selected_local_tile(kind) if local_tile is None else local_tile
        banks = self._library_banks(kind)
        bank_slot, tile = divmod(local_tile, 64)
        if not 0 <= bank_slot < len(banks):
            raise ValueError("所选图块不在当前图库中。")
        return banks[bank_slot] * 64 + tile

    def _select_library_tile(self, kind: str, x: int, y: int) -> None:
        bank_slot = y // 64
        local_y = y % 64
        local_tile = bank_slot * 64 + (local_y // 8) * 8 + x // 8
        if local_tile >= len(self._library_banks(kind)) * 64:
            return
        if kind == "body":
            self._selected_body_tile = local_tile
            self.body_selection.setText(f"当前选择的图块编号：{local_tile:02X}")
        else:
            self._selected_fragment_tile = local_tile
            self.fragment_selection.setText(f"已选碎片图块 ${local_tile:02X}")
        self.refresh_preview()

    def _remember_original_tile(self, absolute_tile: int) -> None:
        if absolute_tile not in self._original_draft_tiles:
            self._original_draft_tiles[absolute_tile] = self.project.chr_tile_pixels(absolute_tile)

    def _set_draft_tile(self, absolute_tile: int, pixels) -> None:
        pixels = tuple(pixels)
        if len(pixels) != 64 or any(value not in range(4) for value in pixels):
            raise ValueError("NES 图块必须是 8×8、每像素 0—3。")
        self._remember_original_tile(absolute_tile)
        self._draft_tiles[absolute_tile] = pixels
        self.refresh_preview()

    def _copy_tile(self, kind: str) -> None:
        pixels = tuple(self._draft_project().chr_tile_pixels(self._absolute_tile(kind)))
        UnitAppearanceDialog._tile_clipboard = pixels
        QApplication.clipboard().setText("DCCHR1:" + "".join(str(value) for value in pixels))
        self.status.setText(f"已复制{('主体' if kind == 'body' else '碎片')}图块。")

    def _paste_tile(self, kind: str) -> None:
        pixels = UnitAppearanceDialog._tile_clipboard
        text = QApplication.clipboard().text().strip()
        if text.startswith("DCCHR1:") and len(text) == 71:
            payload = text[7:]
            if all(character in "0123" for character in payload):
                pixels = tuple(int(character) for character in payload)
        if pixels is None:
            QMessageBox.information(self, "没有图块", "请先复制一个图块。")
            return
        self._set_draft_tile(self._absolute_tile(kind), pixels)

    def _copy_library(self, kind: str) -> None:
        indices = self._library_local_indices(kind)
        tiles = tuple(
            tuple(self._draft_project().chr_tile_pixels(self._absolute_tile(kind, index)))
            for index in indices
        )
        UnitAppearanceDialog._library_clipboard = tiles
        self.status.setText(f"已复制{len(tiles)}个图库图块。")

    def _paste_library(self, kind: str) -> None:
        tiles = UnitAppearanceDialog._library_clipboard
        indices = self._library_local_indices(kind)
        expected = len(indices)
        if tiles is None or len(tiles) != expected:
            QMessageBox.information(self, "图库不匹配", f"需要先复制同为 {expected} 图块的图库。")
            return
        for index, pixels in zip(indices, tiles):
            absolute = self._absolute_tile(kind, index)
            self._remember_original_tile(absolute)
            self._draft_tiles[absolute] = tuple(pixels)
        self.refresh_preview()

    def _clear_library(self, kind: str) -> None:
        if QMessageBox.question(
            self, "清空图库", "清空当前图库的全部图块？确定前仍可用“取消”撤销。"
        ) != QMessageBox.StandardButton.Yes:
            return
        for index in self._library_local_indices(kind):
            absolute = self._absolute_tile(kind, index)
            self._remember_original_tile(absolute)
            self._draft_tiles[absolute] = (0,) * 64
        self.refresh_preview()

    def _delete_tile(self, kind: str) -> None:
        self._set_draft_tile(self._absolute_tile(kind), (0,) * 64)

    def _edit_tile(self, kind: str, local_tile: int | None = None) -> None:
        local_tile = self._selected_local_tile(kind) if local_tile is None else local_tile
        absolute = self._absolute_tile(kind, local_tile)
        pixels = tuple(self._draft_project().chr_tile_pixels(absolute))
        editor = ChrTileEditorDialog(
            pixels,
            f"编辑{('主体' if kind == 'body' else '碎片')}图块 ${local_tile:02X}",
            self,
        )
        if editor.exec() == QDialog.DialogCode.Accepted and editor.pixels() != pixels:
            self._set_draft_tile(absolute, editor.pixels())

    def _import_library(self, kind: str) -> None:
        path, _filter = QFileDialog.getOpenFileName(
            self, "导入旧版 BMP 图块或图库", "", "BMP 图片 (*.bmp);;图片 (*.bmp *.png)"
        )
        if not path:
            return
        image = QImage(path)
        if image.isNull():
            QMessageBox.warning(self, "无法导入", "图片无法读取。")
            return
        if (image.width(), image.height()) == (8, 8):
            self._set_draft_tile(
                self._absolute_tile(kind), image_to_palette_pixels(image, WORK_PALETTE)
            )
            self.status.setText(
                f"已导入 8×8 {('主体' if kind == 'body' else '碎片')}图块；"
                "确定后才写入 ROM。"
            )
            return
        if kind == "body":
            self._import_body_image(image)
            return
        indices = self._library_local_indices(kind)
        valid_full_sizes = {(64, len(indices) // 64 * 64)}
        if kind == "body" and len(self._library_banks("body")) > 1:
            valid_full_sizes.add((64, 128))
        compressed_from: tuple[int, int] | None = None
        if (image.width(), image.height()) not in valid_full_sizes:
            compressed_from = image.width(), image.height()
            target_height = 64 if kind == "body" else 128
            image = compress_image_for_chr(image, 64, target_height)
        import_indices = (
            tuple(range(128))
            if kind == "body" and image.height() == 128
            else indices
        )
        for source_index, index in enumerate(import_indices):
            tile_x = (source_index % 8) * 8
            tile_y = (source_index // 64) * 64 + ((source_index % 64) // 8) * 8
            pixels = image_to_palette_pixels(image.copy(tile_x, tile_y, 8, 8), WORK_PALETTE)
            absolute = self._absolute_tile(kind, index)
            self._remember_original_tile(absolute)
            self._draft_tiles[absolute] = pixels
        self.refresh_preview()
        compression = (
            f"；已从 {compressed_from[0]}×{compressed_from[1]} 等比压缩并居中到 "
            f"{image.width()}×{image.height()}"
            if compressed_from else ""
        )
        self.status.setText(
            f"已导入 {len(import_indices)} 个图块{compression}；确定后才写入 ROM。"
        )

    def _export_bitmap_bytes(self, kind: str, *, selected_only: bool = False) -> bytes:
        """Encode a selected tile or the visible legacy library as 24-bit BMP."""

        draft_project = self._draft_project()
        if selected_only:
            width = height = 8
            tiles = (tuple(draft_project.chr_tile_pixels(self._absolute_tile(kind))),)
        else:
            indices = self._library_local_indices(kind)
            width = 64
            height = len(indices) // 8 * 8
            tiles = tuple(
                tuple(draft_project.chr_tile_pixels(self._absolute_tile(kind, index)))
                for index in indices
            )
        pixels = []
        for y in range(height):
            tile_row, pixel_y = divmod(y, 8)
            for x in range(width):
                tile_column, pixel_x = divmod(x, 8)
                tile = tiles[tile_row * (width // 8) + tile_column]
                pixels.append(LEGACY_MATERIAL_PALETTE_RGB[tile[pixel_y * 8 + pixel_x]])
        return encode_legacy_bmp24(width, height, pixels)

    def _export_library(self, kind: str, *, selected_only: bool = False) -> None:
        subject = "body" if kind == "body" else "fragment"
        suffix = f"tile_{self._selected_local_tile(kind):02X}" if selected_only else "library"
        default_name = f"unit_{self.unit_id:02X}_{subject}_{suffix}.bmp"
        path, _filter = QFileDialog.getSaveFileName(
            self,
            "导出旧版 BMP 图块" if selected_only else "导出旧版 BMP 图库",
            default_name,
            "BMP 图片 (*.bmp)",
        )
        if not path:
            return
        output_path = Path(path)
        if output_path.suffix.lower() != ".bmp":
            output_path = output_path.with_suffix(".bmp")
        try:
            output_path.write_bytes(self._export_bitmap_bytes(kind, selected_only=selected_only))
        except OSError as error:
            QMessageBox.warning(self, "无法导出", f"无法写入 BMP：{error}")
            return
        dimensions = "8×8" if selected_only else (
            "64×64" if kind == "body" else "64×128"
        )
        self.status.setText(f"已导出 {dimensions} BMP：{output_path}")

    def _import_body_image(self, image: QImage) -> None:
        width, height = choose_body_layout(image.width(), image.height())
        compressed = compress_image_for_chr(image, width * 8, height * 8)
        indices = self._library_local_indices("body")
        first = indices[0]
        tile_count = width * height
        for local_index in indices:
            absolute = self._absolute_tile("body", local_index)
            self._remember_original_tile(absolute)
            relative = local_index - first
            if relative < tile_count:
                tile_x = relative % width * 8
                tile_y = relative // width * 8
                pixels = image_to_palette_pixels(
                    compressed.copy(tile_x, tile_y, 8, 8), WORK_PALETTE
                )
            else:
                pixels = (0,) * 64
            self._draft_tiles[absolute] = pixels
        self._apply_body_grid(width, height)
        self.status.setText(
            f"已将 {image.width()}×{image.height()} 图片等比压缩为 "
            f"{width}×{height} 图块，并生成对应主体拼图脚本；确定后才写入 ROM。"
        )

    def _show_library_menu(self, kind: str, point: QPoint) -> None:
        menu = QMenu(self)
        actions = (
            ("导入图片\tCtrl+D", lambda: self._import_library(kind)),
            ("复制图块\tCtrl+C", lambda: self._copy_tile(kind)),
            ("粘贴图块\tCtrl+V", lambda: self._paste_tile(kind)),
            ("删除图块\tCtrl+S", lambda: self._delete_tile(kind)),
            ("复制图库", lambda: self._copy_library(kind)),
            ("粘贴图库", lambda: self._paste_library(kind)),
            ("清空图库\tCtrl+G", lambda: self._clear_library(kind)),
        )
        for index, (caption, callback) in enumerate(actions):
            if index in (1, 4):
                menu.addSeparator()
            action = menu.addAction(caption)
            action.triggered.connect(callback)
        menu.popup(point)

    def _composition_hits(self, x: int, y: int):
        values = self.values()
        body_origin_x = 15 if self._type_code() & 0x40 else 0
        body = decode_unit_body_script(self.body_script, len(values[7:]) * 64)
        body_hits = [index for index, item in enumerate(body)
                     if (item.x + body_origin_x) * 8 <= x < (item.x + body_origin_x + 1) * 8
                     and (item.y + 15) * 8 <= y < (item.y + 16) * 8]
        fragment_origin_x = 0x78 if self._type_code() & 0x40 else 0
        fragments = decode_unit_fragment_script(self.fragment_script)
        fragment_hits = [index for index, item in enumerate(fragments)
                         if item.x + fragment_origin_x <= x < item.x + fragment_origin_x + 8
                         and item.y <= y < item.y + 8]
        return body, body_hits, fragments, fragment_hits

    def _composition_pressed(self, x: int, y: int, button: int) -> None:
        self._last_composition_point = (x, y)
        body, body_hits, _fragments, _fragment_hits = self._composition_hits(x, y)
        if body_hits:
            index = body_hits[-1]
            if button == Qt.MouseButton.LeftButton.value:
                self._edit_tile("body", body[index].tile_index)
            elif button == Qt.MouseButton.RightButton.value:
                self._delete_body_at(body, index)

    def _delete_body_at(self, placements, index: int) -> None:
        placements = list(placements)
        del placements[index]
        self._replace_script("body", encode_body_placements(placements))

    def _delete_fragment_at(self, placements, index: int) -> None:
        placements = list(placements)
        del placements[index]
        self._replace_script("fragment", encode_fragment_placements(placements))

    def refresh_preview(self) -> None:
        values = self.values()
        draft_project = self._draft_project()
        for swatch, value in zip(self.color_swatches, values[:6]):
            swatch.set_value(value)
        body_banks = tuple(values[7:])
        fragment_bank = values[6] & 0xFE
        for description, bank in zip(self.bank_descriptions, values[6:]):
            description.setText(chr_bank_description(self.project, bank))
            description.setToolTip(chr_bank_description(self.project, bank))
        display_offset = self._body_display_offset()
        display_bank = body_banks[min(display_offset // 64, len(body_banks) - 1)]
        body_library = render_chr_banks(
            draft_project, body_banks, values[:3], columns=1,
            display_palette=WORK_PALETTE,
        )
        body_library_display = legacy_body_library_image(
            body_library,
            self._selected_body_tile,
            show_numbers=self.show_tile_numbers.isChecked(),
        )
        body_library_pixmap = QPixmap.fromImage(body_library_display)
        self.body_library_preview.set_source_pixmap(
            body_library_pixmap, 64, 128
        )
        preview_appearance = replace(
            self.appearance,
            configuration=bytes((self._type_code(), *values)),
            body_script=self.body_script,
            fragment_script=self.fragment_script,
        )
        body_picture = render_unit_battle_preview(
            draft_project,
            preview_appearance,
            show_fragments=False,
            display_palette=WORK_PALETTE,
        )
        composition_display = legacy_composition_image(
            body_picture,
            preview_appearance,
            show_numbers=self.show_tile_numbers.isChecked(),
            include_fragments=False,
        )
        body_composition_pixmap = QPixmap.fromImage(composition_display)
        self.body_composition_preview.set_source_pixmap(body_composition_pixmap, 128, 128)
        fragment_picture = render_chr_banks(
            draft_project, (fragment_bank, fragment_bank + 1), values[3:6], columns=1,
            display_palette=WORK_PALETTE,
        )
        fragment_display = (
            numbered_library_image(fragment_picture, self._selected_fragment_tile)
            if self.show_fragment_numbers.isChecked()
            else selected_library_image(fragment_picture, self._selected_fragment_tile)
        )
        fragment_pixmap = QPixmap.fromImage(fragment_display).scaled(
            166, 333, Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.FastTransformation,
        )
        self.fragment_library_preview.set_source_pixmap(
            fragment_pixmap, fragment_picture.width(), fragment_picture.height()
        )
        self.body_library_preview.setToolTip(
            "当前主体图库：" + " / ".join(
                chr_bank_description(self.project, bank) for bank in body_banks
            )
            + "；单击选择，右键编辑/导入/导出/复制/粘贴/删除"
        )
        self.body_composition_preview.setToolTip(
            f"主体脚本 {len(self.body_script)} 字节的机体预览；"
            "不叠加碎片层；“显示图块编号”只标注主体；"
            "左键编辑命中的主体图块，右键直接删除该主体拼图项"
        )
        self.fragment_library_preview.setToolTip(
            f"碎片图库：${fragment_bank:02X} / ${fragment_bank + 1:02X}"
        )
        fragment_placements = decode_unit_fragment_script(self.fragment_script)
        self.fragment_placements_view.setPlainText("\n".join(
            f"{index:03d}  X:{item.x:4d}  Y:{item.y:4d}  图块:${item.tile_index:02X}  "
            + ("水平" if item.flip_horizontal else "")
            + ("垂直" if item.flip_vertical else "")
            + ("不翻转" if not item.flip_horizontal and not item.flip_vertical else "")
            for index, item in enumerate(fragment_placements)
        ) or "（无碎片图块）")
        self.status.setText(
            f"当前记录 0x{self.appearance.file_offset:06X}；"
            + ("大型机：两个主体图库。" if len(values) == 9 else "小型机：一个主体图库。")
            + " 效果图仅显示主体机体；"
            + f"当前主体图库 {chr_bank_description(self.project, display_bank)}；"
            + f"碎片图库 {chr_bank_description(self.project, fragment_bank)} / "
            + f"{chr_bank_description(self.project, fragment_bank + 1)}；"
            + f"图库草稿 {len(self._draft_tiles)} 个图块。"
        )
        for widget in self.findChildren(QWidget):
            widget.setToolTip("")

    def accept(self) -> None:
        try:
            body = parse_hex_script(self.body_script_view.toPlainText(), "主体拼图脚本")
            fragment = parse_hex_script(
                self.fragment_script_view.toPlainText(), "碎片拼图脚本"
            )
            decode_unit_body_script(body, len(self.values()[7:]) * 64)
            decode_unit_fragment_script(fragment)
            current = read_unit_appearance(self.project, self.unit_id)
            if current != self.appearance:
                raise ValueError("当前外观记录已被其他操作更改，请取消后重新打开。")
            for tile_index, original in self._original_draft_tiles.items():
                if self.project.chr_tile_pixels(tile_index) != original:
                    raise ValueError("当前图库已被其他操作更改，请取消后重新打开。")
            active_tiles = {
                bank * 64 + tile
                for bank in (*self._library_banks("body"), *self._library_banks("fragment"))
                for tile in range(64)
            }
            if any(tile_index not in active_tiles for tile_index in self._draft_tiles):
                raise ValueError("编辑图库后又更改了图库地址；请恢复原地址或取消后重新操作。")
            desired_configuration = bytes((
                self._type_code(),
                *self.palette_values,
                *(editor.value() for editor in self.bank_editors),
            ))
            new_size = 10 if self._is_large() else 9
            old_size = 10 if self.appearance.configuration[0] & 0x80 else 9
            configuration_changed = (
                desired_configuration[:new_size]
                != self.appearance.configuration[:new_size]
                or new_size != old_size
            )
            with self.project.transaction(f"机体 ${self.unit_id:02X} · 类型、图库与拼图"):
                if configuration_changed:
                    self.project.set_unit_appearance_configuration(
                        self.unit_id, desired_configuration
                    )
                for tile_index, pixels in self._draft_tiles.items():
                    tile_offset = self.project.chr_codec.tile_offset(tile_index)
                    self.project.working[tile_offset:tile_offset + 16] = (
                        self.project.chr_codec.encode_tile(pixels)
                    )
                if body != self.appearance.body_script or fragment != self.appearance.fragment_script:
                    self.project.set_unit_appearance_scripts(
                        self.unit_id,
                        body_script=body,
                        fragment_script=fragment,
                    )
            self.changed = (
                configuration_changed
                or body != self.appearance.body_script
                or fragment != self.appearance.fragment_script
                or any(
                    self._original_draft_tiles[index] != pixels
                    for index, pixels in self._draft_tiles.items()
                )
            )
        except (ValueError, IndexError) as error:
            QMessageBox.warning(self, "无法保存机体拼图", str(error))
            return
        super().accept()
