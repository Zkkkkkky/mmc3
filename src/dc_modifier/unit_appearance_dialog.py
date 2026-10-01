from __future__ import annotations

from dataclasses import dataclass, replace
from pathlib import Path

from PySide6.QtCore import QPoint, QRect, QSize, Qt, Signal
from PySide6.QtGui import QColor, QImage, QMouseEvent, QPainter, QPen, QPixmap
from PySide6.QtWidgets import (
    QApplication, QButtonGroup, QCheckBox, QComboBox, QDialog, QDialogButtonBox, QFileDialog, QGridLayout,
    QGroupBox, QHBoxLayout, QInputDialog, QLabel, QListWidget, QMenu, QMessageBox, QPlainTextEdit,
    QPushButton, QSizePolicy, QSpinBox, QTabWidget, QVBoxLayout, QWidget,
)
from fc_editor.legacy_bitmap import LEGACY_MATERIAL_PALETTE_RGB, encode_legacy_bmp24
from .database_graphics import (
    CompositionTile,
    FragmentTile,
    decode_unit_body_script,
    decode_unit_fragment_script,
    palette_color,
    read_unit_appearance,
    render_chr_banks,
    render_tile_grid,
    render_unit_battle_preview,
)


WORK_PALETTE = tuple(QColor(*rgb) for rgb in LEGACY_MATERIAL_PALETTE_RGB)


@dataclass(frozen=True)
class FragmentSliceResult:
    tiles: tuple[tuple[int, ...], ...]
    placements: tuple[FragmentTile, ...]
    exact: bool
    search_nodes: int


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


def clear_unit_appearance_image(
    project,
    unit_id: int,
    kind: str,
    *,
    sync_shared_previews: bool = True,
) -> int:
    """Clear only the current composition's referenced tiles and its script."""

    appearance = read_unit_appearance(project, unit_id)
    if kind == "body":
        banks = tuple(appearance.secondary_banks)
        placements = decode_unit_body_script(
            appearance.body_script, len(banks) * 64
        )
        body_script = b"\xFF"
        fragment_script = None
        subject = "机体"
    elif kind == "fragment":
        first = appearance.primary_bank & 0xFE
        banks = (first, first + 1)
        placements = decode_unit_fragment_script(appearance.fragment_script)
        body_script = None
        fragment_script = bytes.fromhex("00 F0 00 00 FF")
        subject = "碎片"
    else:
        raise ValueError(f"未知拼图类型：{kind}")

    local_tiles = sorted({placement.tile_index for placement in placements})
    absolute_tiles = [
        banks[local_tile // 64] * 64 + local_tile % 64
        for local_tile in local_tiles
    ]

    zero = project.chr_codec.encode_tile((0,) * 64)
    with project.transaction(f"机体 ${unit_id:02X} · 清除{subject}拼图"):
        for tile_index in absolute_tiles:
            tile_offset = project.chr_codec.tile_offset(tile_index)
            project.working[tile_offset:tile_offset + 16] = zero
        project.set_unit_appearance_scripts(
            unit_id,
            body_script=body_script,
            fragment_script=fragment_script,
            sync_shared_previews=sync_shared_previews,
        )
    return len(absolute_tiles)


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


class FragmentPlacementDialog(QDialog):
    """Beginner-facing editor for one item in the fragment composition."""

    def __init__(self, placement, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("编辑碎片图块位置")
        root = QVBoxLayout(self)
        hint = QLabel("修改当前碎片的位置、图块和翻转状态；确定后先保留在拼图草稿中。")
        hint.setWordWrap(True)
        root.addWidget(hint)
        form = QGridLayout()
        self.x_editor = QSpinBox()
        self.y_editor = QSpinBox()
        self.tile_editor = HexByteSpinBox()
        for editor, value in (
            (self.x_editor, placement.x),
            (self.y_editor, placement.y),
        ):
            editor.setRange(-128, 255)
            editor.setValue(value)
        self.tile_editor.setRange(0, 127)
        self.tile_editor.setValue(placement.tile_index)
        form.addWidget(QLabel("X 坐标"), 0, 0)
        form.addWidget(self.x_editor, 0, 1)
        form.addWidget(QLabel("Y 坐标"), 1, 0)
        form.addWidget(self.y_editor, 1, 1)
        form.addWidget(QLabel("图块编号"), 2, 0)
        form.addWidget(self.tile_editor, 2, 1)
        self.horizontal = QCheckBox("水平翻转图块")
        self.vertical = QCheckBox("垂直翻转图块")
        self.horizontal.setChecked(placement.flip_horizontal)
        self.vertical.setChecked(placement.flip_vertical)
        root.addLayout(form)
        flip_group = QGroupBox("翻转状态")
        flip_row = QHBoxLayout(flip_group)
        flip_row.addWidget(self.horizontal)
        flip_row.addWidget(self.vertical)
        flip_row.addStretch(1)
        root.addWidget(flip_group)
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.button(QDialogButtonBox.StandardButton.Ok).setText("确定")
        buttons.button(QDialogButtonBox.StandardButton.Cancel).setText("取消")
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        root.addWidget(buttons)

    def updated(self, placement):
        return replace(
            placement,
            x=self.x_editor.value(),
            y=self.y_editor.value(),
            tile_index=self.tile_editor.value(),
            flip_horizontal=self.horizontal.isChecked(),
            flip_vertical=self.vertical.isChecked(),
        )


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


def encode_compact_fragment_placements(placements) -> bytes:
    """Use the shortest verified command family for sequential fragment tiles."""

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
        sequential = following.tile_index == placement.tile_index + 1
        if sequential and dx == 8 and dy == 0:
            result.append(flags | 0x02)
        elif sequential and dy == 0:
            result.extend((flags | 0x06, dx & 0xFF))
        elif sequential and dy == 8:
            result.extend((flags | 0x0A, dx & 0xFF))
        elif sequential:
            result.extend((flags | 0x0E, dx & 0xFF, dy & 0xFF))
        elif dx == 8 and dy == 0:
            result.extend((flags | 0x22, following.tile_index))
        elif dy == 0:
            result.extend((flags | 0x26, following.tile_index, dx & 0xFF))
        elif dy == 8:
            result.extend((flags | 0x2A, following.tile_index, dx & 0xFF))
        else:
            result.extend((
                flags | 0x2E,
                following.tile_index,
                dx & 0xFF,
                dy & 0xFF,
            ))
    result.append(0xFF)
    return bytes(result)


def image_to_chr_pixels(image: QImage, colors: tuple[int, ...]) -> tuple[int, ...]:
    """Quantise an image to the active NES background plus three colours."""

    palette = (palette_color(0x0F), *(palette_color(value) for value in colors))
    return image_to_palette_pixels(image, palette)


def image_to_palette_pixels(image: QImage, palette) -> tuple[int, ...]:
    # ``pixelColor`` creates a QColor Python wrapper for every pixel.  A
    # 128×128 import used to spend several hundred milliseconds here before
    # the fragment optimiser even started.  RGBA8888 has a stable byte order,
    # so quantise its buffer directly and memoise repeated source colours.
    converted = image.convertToFormat(QImage.Format.Format_RGBA8888)
    raw = bytes(converted.constBits())
    stride = converted.bytesPerLine()
    palette_rgb = tuple((color.red(), color.green(), color.blue()) for color in palette)
    colour_cache: dict[tuple[int, int, int, int], int] = {}
    result: list[int] = []
    for y in range(converted.height()):
        row = y * stride
        for x in range(converted.width()):
            start = row + x * 4
            rgba = tuple(raw[start:start + 4])
            index = colour_cache.get(rgba)
            if index is None:
                red, green, blue, alpha = rgba
                index = 0 if alpha < 128 else min(
                    range(4),
                    key=lambda candidate: (
                        (red - palette_rgb[candidate][0]) ** 2
                        + (green - palette_rgb[candidate][1]) ** 2
                        + (blue - palette_rgb[candidate][2]) ** 2
                    ),
                )
                colour_cache[rgba] = index
            result.append(index)
    return tuple(result)


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


def encode_sparse_body_placements(placements) -> bytes:
    """Encode sparse body rows with compact consecutive-tile runs."""

    ordered = sorted(placements, key=lambda item: (item.y, item.x, item.tile_index))
    if not ordered:
        return b"\xFF"
    result = bytearray()
    cursor_x = cursor_y = 0
    index = 0
    while index < len(ordered):
        first = ordered[index]
        run = 1
        while index + run < len(ordered):
            following = ordered[index + run]
            if (
                following.y != first.y
                or following.x != first.x + run
                or following.tile_index != first.tile_index + run
            ):
                break
            run += 1
        dx = first.x - cursor_x
        dy = first.y - cursor_y
        if dx or dy:
            if not -128 <= dx <= 127 or not -128 <= dy <= 127:
                raise ValueError("主体稀疏拼图位移超出单字节范围。")
            result.extend((0xF3, dy & 0xFF, dx & 0xFF))
        result.extend((0xF9, run, first.tile_index))
        cursor_x = first.x + run
        cursor_y = first.y
        index += run
    result.append(0xFF)
    return bytes(result)


def pad_body_image_to_tile_grid(
    image: QImage,
    *,
    enemy: bool = False,
    maximum_size: int = 128,
) -> QImage:
    """Pad a body image to whole CHR cells without scaling its pixels.

    Battle bodies are grounded at the bottom of the composition canvas.  An
    allied body is anchored on the left, while an enemy body is anchored on
    the right.  Padding must therefore be added above and on the side opposite
    that anchor; adding it below would visibly move the unit in battle.
    """

    width = image.width()
    height = image.height()
    if image.isNull() or width < 1 or height < 1:
        raise ValueError("机体图片尺寸无效。")
    if width > maximum_size or height > maximum_size:
        raise ValueError(
            f"机体图片不得超过 {maximum_size}×{maximum_size}；不会缩放或裁剪。"
        )
    padded_width = (width + 7) // 8 * 8
    padded_height = (height + 7) // 8 * 8
    if padded_width == width and padded_height == height:
        return image.copy()
    padded = QImage(
        padded_width, padded_height, QImage.Format.Format_ARGB32
    )
    padded.fill(WORK_PALETTE[0])
    painter = QPainter(padded)
    painter.drawImage(
        padded_width - width if enemy else 0,
        padded_height - height,
        image,
    )
    painter.end()
    return padded


def body_import_alignment_candidates(
    image: QImage,
    *,
    enemy: bool = False,
    maximum_shift: int = 3,
) -> tuple[tuple[QImage, int, int], ...]:
    """Build lossless 128x128 body canvases around the side anchor.

    Moving artwork by a few pixels changes its phase against the NES 8x8 CHR
    grid and can reduce the number of distinct tiles.  Candidates that would
    clip even one non-background pixel are discarded.  The unshifted canvas is
    always first so later tie-breaking preserves the original position.
    """

    if image.isNull() or not 1 <= image.width() <= 128 or not 1 <= image.height() <= 128:
        raise ValueError("机体图片不得超过 128×128；不会缩放或裁剪。")
    source_pixels = image_to_palette_pixels(image, WORK_PALETTE)
    occupied = [
        (index % image.width(), index // image.width())
        for index, value in enumerate(source_pixels)
        if value
    ]
    base_x = 128 - image.width() if enemy else 0
    base_y = 128 - image.height()
    shifts = [(0, 0)]
    shifts.extend(
        (shift_x, shift_y)
        for shift_y in range(-maximum_shift, maximum_shift + 1)
        for shift_x in range(-maximum_shift, maximum_shift + 1)
        if (shift_x, shift_y) != (0, 0)
    )
    candidates: list[tuple[QImage, int, int]] = []
    for shift_x, shift_y in shifts:
        origin_x = base_x + shift_x
        origin_y = base_y + shift_y
        if occupied and any(
            not 0 <= origin_x + x < 128 or not 0 <= origin_y + y < 128
            for x, y in occupied
        ):
            continue
        canvas = QImage(128, 128, QImage.Format.Format_ARGB32)
        canvas.fill(WORK_PALETTE[0])
        painter = QPainter(canvas)
        painter.drawImage(origin_x, origin_y, image)
        painter.end()
        candidates.append((canvas, shift_x, shift_y))
    return tuple(candidates)


def sparse_body_tiles(
    image: QImage,
    *,
    first_tile: int = 0,
    enemy: bool = False,
) -> tuple[tuple[tuple[int, ...], ...], tuple[CompositionTile, ...]]:
    """Return the minimum body-tile dictionary for the fixed 8x8 grid.

    Body composition commands can only place whole, unflipped 8x8 background
    tiles.  Consequently every occupied grid cell needs one placement, while
    equal cell bitmaps may safely share one CHR index.  Dropping empty cells and
    interning equal non-empty cells therefore gives the provably smallest CHR
    tile set representable by the verified body-script language.
    """

    if (
        image.isNull()
        or image.width() % 8
        or image.height() % 8
        or not 8 <= image.width() <= 128
        or not 8 <= image.height() <= 128
    ):
        raise ValueError("主体最少分块需要 8 像素整数倍且不超过 128×128 的图片。")
    grid_width = image.width() // 8
    grid_height = image.height() // 8
    pixels = image_to_palette_pixels(image, WORK_PALETTE)
    tiles: list[tuple[int, ...]] = []
    tile_indices: dict[tuple[int, ...], int] = {}
    placements: list[CompositionTile] = []
    for tile_y in range(grid_height):
        for tile_x in range(grid_width):
            tile = tuple(
                pixels[(tile_y * 8 + y) * image.width() + tile_x * 8 + x]
                for y in range(8)
                for x in range(8)
            )
            if not any(tile):
                continue
            tile_index = tile_indices.get(tile)
            if tile_index is None:
                tile_index = first_tile + len(tiles)
                tile_indices[tile] = tile_index
                tiles.append(tile)
            placements.append(CompositionTile(
                tile_index,
                tile_x - (grid_width - 1 if enemy else 0),
                tile_y - (grid_height - 1),
            ))
    return tuple(tiles), tuple(placements)


def optimize_fragment_slices(
    image: QImage,
    *,
    first_tile: int = 0,
    enemy: bool = False,
    maximum_tiles: int = 128,
    node_limit: int = 2_000_000,
) -> FragmentSliceResult:
    """Cover all non-background pixels with as few 8x8 fragments as possible.

    For the left-most still-uncovered pixel an optimal square can always be
    shifted right until its left edge reaches that pixel.  The search therefore
    only branches over the at-most eight possible Y origins.  Pairwise
    incompatible-pixel packings provide a safe lower bound; reaching the end
    without the node guard proves the returned count minimal.
    """

    if image.isNull() or (image.width(), image.height()) != (128, 128):
        raise ValueError("碎片自动分块需要 128×128 图片。")
    source = image_to_palette_pixels(image, WORK_PALETTE)
    points = tuple(
        (x, y)
        for x in range(128)
        for y in range(128)
        if source[y * 128 + x]
    )
    if not points:
        return FragmentSliceResult((), (), True, 0)
    if any(y == 0 for _x, y in points):
        raise ValueError("碎片图片第 1 行含像素，超出游戏可表示的精灵 Y 坐标。")
    if len(points) > maximum_tiles * 64:
        raise ValueError(
            f"非背景像素至少需要超过 {maximum_tiles} 个碎片图块，当前图库无法容纳。"
        )

    point_index = {point: index for index, point in enumerate(points)}
    full_state = (1 << len(points)) - 1
    option_cache: dict[int, tuple[tuple[int, tuple[int, int]], ...]] = {}
    share_cache: dict[int, int] = {}

    def options(index: int) -> tuple[tuple[int, tuple[int, int]], ...]:
        cached = option_cache.get(index)
        if cached is not None:
            return cached
        x, y = points[index]
        unique: dict[int, tuple[int, int]] = {}
        for top in range(max(1, y - 7), min(y, 120) + 1):
            mask = 0
            for px in range(x, min(128, x + 8)):
                for py in range(top, top + 8):
                    point = point_index.get((px, py))
                    if point is not None:
                        mask |= 1 << point
            unique[mask] = (x, top)
        cached = tuple(unique.items())
        if not cached:
            raise ValueError(f"碎片像素 ({x},{y}) 无法放入游戏的 8×8 精灵坐标。")
        option_cache[index] = cached
        return cached

    def share_mask(index: int) -> int:
        cached = share_cache.get(index)
        if cached is not None:
            return cached
        x, y = points[index]
        mask = 0
        for px in range(max(0, x - 7), min(127, x + 7) + 1):
            for py in range(max(1, y - 7), min(127, y + 7) + 1):
                point = point_index.get((px, py))
                if point is not None:
                    mask |= 1 << point
        share_cache[index] = mask
        return mask

    def greedy(state: int) -> list[tuple[int, int]]:
        result: list[tuple[int, int]] = []
        while state:
            index = (state & -state).bit_length() - 1
            mask, anchor = max(
                options(index), key=lambda item: (state & item[0]).bit_count()
            )
            state &= ~mask
            result.append(anchor)
        return result

    orders = (
        tuple(range(len(points))),
        tuple(sorted(range(len(points)), key=lambda index: (points[index][1], points[index][0]))),
    )

    def lower_bound(state: int) -> int:
        bounds = []
        for order in orders:
            remaining = state
            count = 0
            for index in order:
                if remaining & (1 << index):
                    count += 1
                    remaining &= ~share_mask(index)
                    if not remaining:
                        break
            bounds.append(count)
        return max(bounds)

    best = greedy(full_state)
    if len(best) > maximum_tiles and lower_bound(full_state) > maximum_tiles:
        raise ValueError(f"碎片自动分块至少需要超过 {maximum_tiles} 个图块。")
    seen_depth: dict[int, int] = {}
    search_nodes = 0
    completed = True

    def search(state: int, path: list[tuple[int, int]]) -> None:
        nonlocal best, search_nodes, completed
        search_nodes += 1
        if search_nodes > node_limit:
            completed = False
            return
        if not state:
            if len(path) < len(best):
                best = path.copy()
            return
        if len(path) + lower_bound(state) >= len(best):
            return
        previous_depth = seen_depth.get(state)
        if previous_depth is not None and previous_depth <= len(path):
            return
        seen_depth[state] = len(path)
        index = (state & -state).bit_length() - 1
        candidates = []
        covered_masks: set[int] = set()
        for mask, anchor in options(index):
            covered = state & mask
            if covered in covered_masks:
                continue
            covered_masks.add(covered)
            candidates.append((covered.bit_count(), mask, anchor))
        candidates.sort(reverse=True)
        for _count, mask, anchor in candidates:
            search(state & ~mask, [*path, anchor])
            if not completed:
                return

    search(full_state, [])
    if len(best) > maximum_tiles:
        raise ValueError(
            f"碎片自动分块需要 {len(best)} 个图块，超过剩余容量 {maximum_tiles}。"
        )

    work = list(source)
    tiles: list[tuple[int, ...]] = []
    placements: list[FragmentTile] = []
    for tile_number, (left, top) in enumerate(best):
        tile = tuple(
            work[(top + y) * 128 + left + x]
            for y in range(8)
            for x in range(8)
        )
        if not any(tile):
            raise ValueError("碎片优化器生成了空图块，已停止导入。")
        tiles.append(tile)
        placements.append(FragmentTile(
            first_tile + tile_number,
            left - (0x78 if enemy else 0),
            top,
        ))
        for y in range(8):
            start = (top + y) * 128 + left
            work[start:start + 8] = (0,) * 8
    return FragmentSliceResult(
        tuple(tiles), tuple(placements), completed, search_nodes
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


def legacy_fragment_library_image(
    image: QImage, selected_tile: int, *, show_numbers: bool
) -> QImage:
    """Render fragment tiles in the reference tool's linear 16×8 order.

    ``render_chr_banks(..., columns=2)`` produces two independent 8×8 banks
    side by side (00—07 followed by 40—47 on the first row).  The legacy
    fragment window instead walks the combined 128-tile address range in
    ordinary row-major order: 00—0F, 10—1F, ... 70—7F.
    """

    scale = 3
    tile_size = 8 * scale
    linear = QImage(128, 64, QImage.Format.Format_RGB32)
    linear.fill(WORK_PALETTE[0])
    linear_painter = QPainter(linear)
    for tile in range(128):
        bank, local = divmod(tile, 64)
        source_x = (bank * 8 + local % 8) * 8
        source_y = local // 8 * 8
        target_x = tile % 16 * 8
        target_y = tile // 16 * 8
        linear_painter.drawImage(
            target_x, target_y, image.copy(source_x, source_y, 8, 8)
        )
    linear_painter.end()
    result = linear.scaled(
        128 * scale,
        64 * scale,
        Qt.AspectRatioMode.IgnoreAspectRatio,
        Qt.TransformationMode.FastTransformation,
    )
    painter = QPainter(result)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing, False)
    if show_numbers:
        font = painter.font()
        font.setPixelSize(8)
        font.setBold(True)
        painter.setFont(font)
        for tile in range(128):
            x = tile % 16 * tile_size
            y = tile // 16 * tile_size
            painter.fillRect(x, y, 16, 10, QColor(0, 0, 0, 72))
            painter.setPen(QColor("#ffffff"))
            painter.drawText(x + 1, y + 8, f"{tile:02X}")
    _draw_scaled_grid(painter, result.width(), result.height(), tile_size)
    selected_x = selected_tile % 16 * tile_size
    selected_y = selected_tile // 16 * tile_size
    # Keep the red selection legible even when the fragment palette itself
    # contains red or magenta pixels.
    painter.setPen(QPen(QColor("#101820"), 4))
    painter.drawRect(selected_x, selected_y, tile_size - 1, tile_size - 1)
    painter.setPen(QPen(QColor("#ff3048"), 2))
    painter.drawRect(selected_x, selected_y, tile_size - 1, tile_size - 1)
    painter.end()
    return result


def numbered_composition_image(
    image: QImage,
    appearance,
    target_size: int = 384,
    *,
    include_body: bool = True,
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

    if include_body:
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
    include_body: bool = True,
    include_fragments: bool = True,
    target_size: int = 384,
) -> QImage:
    """Render the old modifier's square grid and red battle-origin guides."""

    if show_numbers:
        result = numbered_composition_image(
            image,
            appearance,
            target_size,
            include_body=include_body,
            include_fragments=include_fragments,
        )
    else:
        result = _scaled_tile_grid(image, target_size)
    painter = QPainter(result)
    painter.setPen(QPen(QColor("#ff2038"), 2))
    guide_y = round(24 * target_size / image.height())
    # The legacy editor treats the red marks as the battle-screen crop, not a
    # generic origin crosshair. Friendly units use the right-side boundary at
    # x=104; opposing small units mirror it to x=24. For an opposing large
    # unit the right boundary is exactly the preview's outer edge, so there is
    # no internal vertical line.
    type_code = appearance.configuration[0] & 0xC0
    if type_code != 0xC0:
        guide_logical_x = 24 if type_code == 0x40 else 104
        guide_x = round(guide_logical_x * target_size / image.width())
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


def move_body_script(
    script: bytes,
    dx: int,
    dy: int,
    *,
    enemy: bool | None = None,
) -> bytes:
    """Move a body composition within the legacy 16x16 battle canvas.

    The reference editor silently keeps the old script when a move would put
    any tile outside the side-specific canvas.  This is observable on the
    golden friendly sample: its bottom and left edges already touch the
    limits, so Down and Left are no-ops while Up and Right are accepted.
    """

    if not -128 <= dx <= 127 or not -128 <= dy <= 127:
        raise ValueError("主体移动量超出单字节范围。")
    placements = decode_unit_body_script(script, 0x80)
    if placements:
        if enemy is None:
            enemy = max(item.x for item in placements) <= 0
        minimum_x, maximum_x = (-15, 0) if enemy else (0, 15)
        if (
            min(item.x for item in placements) + dx < minimum_x
            or max(item.x for item in placements) + dx > maximum_x
            or min(item.y for item in placements) + dy < -15
            or max(item.y for item in placements) + dy > 0
        ):
            return script
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


def apply_legacy_body_template(
    script: bytes,
    width: int,
    height: int,
    *,
    first_tile: int = 0,
    enemy: bool = False,
) -> bytes:
    """Return the exact body-template result observed in the old editor."""

    if (width, height) not in ((8, 8), (7, 9), (9, 7), (10, 6)):
        raise ValueError("未知的旧版主体拼图模板。")
    if (width, height) == (7, 9):
        return script
    count = min(width * height, 64)
    start_x = -width + 1 if enemy else 0
    start_y = -height + 1
    return bytes((
        0xF3, start_y & 0xFF, start_x & 0xFF,
        0xFD, 0x20, width,
        0xF9, count, first_tile,
        0xFF,
    ))


def flip_fragment_script(script: bytes, mask: int) -> bytes:
    """Mirror fragments exactly like the reference editor and re-encode.

    Horizontal mirroring maps an 8-pixel sprite's left edge with ``120-x``.
    The legacy vertical command uses its battle/OAM coordinate system and the
    golden transform is ``122-y``.  Re-encoding with the compact command
    family is significant: the horizontal golden result grows from 49 to 52
    bytes, so merely toggling command flag bits is not equivalent.
    """

    if mask not in (0x40, 0x80):
        raise ValueError("碎片翻转只支持水平或垂直方向。")
    placements = decode_unit_fragment_script(script)
    if not placements:
        return script
    if mask == 0x40:
        mirrored = tuple(
            replace(
                item,
                x=120 - item.x,
                flip_horizontal=not item.flip_horizontal,
            )
            for item in placements
        )
    else:
        mirrored = tuple(
            replace(
                item,
                y=122 - item.y,
                flip_vertical=not item.flip_vertical,
            )
            for item in placements
        )
    return encode_compact_fragment_placements(mirrored)


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
        # Track explicit clear actions separately from ordinary code edits so
        # their intent remains visible while this child-window draft is open.
        self._clear_script_requests: set[str] = set()
        self._draft_tiles: dict[int, tuple[int, ...]] = {}
        self._original_draft_tiles: dict[int, tuple[int, ...]] = {}
        self._transient_body_preview: QImage | None = None
        self._transient_fragment_preview: QImage | None = None
        self._selected_body_tile = 0
        self._selected_fragment_tile = 0
        self.setWindowTitle("机体拼图")
        self.setObjectName("unitAppearanceDialog")
        self.setFixedSize(740, 700)
        self.setWindowFlag(Qt.WindowType.WindowMaximizeButtonHint, False)
        self.changed = False
        root = QVBoxLayout(self)
        root.setContentsMargins(8, 7, 8, 7)
        root.setSpacing(6)
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
        reference_code_row.setSpacing(8)
        reference_group = QGroupBox("参考设置")
        reference_group.setObjectName("puzzleReferencePanel")
        self.body_reference_group = reference_group
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
            editor.setFixedSize(158, 22)
        reference_group.setFixedWidth(250)
        reference_code_row.addWidget(reference_group, 2)

        body_code_group = QGroupBox("代码编辑")
        body_code_group.setObjectName("puzzleCodePanel")
        self.body_code_group = body_code_group
        body_code_layout = QVBoxLayout(body_code_group)
        body_code_layout.setContentsMargins(9, 10, 9, 7)
        body_code_layout.setSpacing(5)
        self.body_script_view = QPlainTextEdit()
        self.body_script_view.setLineWrapMode(QPlainTextEdit.LineWrapMode.WidgetWidth)
        self.body_script_view.setPlainText(self.appearance.body_script.hex(" ").upper())
        self.body_script_view.setMaximumHeight(66)
        body_script_font = self.body_script_view.font()
        body_script_font.setPointSize(8)
        self.body_script_view.setFont(body_script_font)
        body_code_layout.addWidget(self.body_script_view)
        body_code_actions = QHBoxLayout()
        body_code_actions.setSpacing(5)
        clear_body_quick = QPushButton("清除")
        clear_body_quick.setObjectName("puzzleClearButton")
        clear_body_quick.setFixedSize(48, 22)
        clear_body_quick.clicked.connect(
            lambda: self._clear_image("body", confirm=False)
        )
        body_code_actions.addWidget(clear_body_quick)
        self.body_template_buttons: list[QPushButton] = []
        for width, height in ((8, 8), (7, 9), (9, 7), (10, 6)):
            button = QPushButton(f"{width}×{height}")
            button.setObjectName("puzzleTemplateButton")
            button.setFixedSize(48, 22)
            button.setToolTip("按旧版模板用当前图库的连续图块重建主体拼图")
            button.clicked.connect(
                lambda _checked=False, w=width, h=height: self._apply_body_grid(w, h)
            )
            body_code_actions.addWidget(button)
            self.body_template_buttons.append(button)
        validate_body = QPushButton("查看效果")
        validate_body.setObjectName("puzzlePreviewButton")
        validate_body.setFixedSize(68, 22)
        validate_body.clicked.connect(self.apply_script_text)
        body_code_actions.addWidget(validate_body)
        self.body_clear_button = clear_body_quick
        self.body_validate_button = validate_body
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
        library_group.setObjectName("puzzleLibraryPanel")
        legacy_frame_style = (
            "QGroupBox { border:1px solid #8FBAC6; border-radius:6px; margin-top:8px; "
            "background:#F8FBFC; }"
            "QGroupBox::title { subcontrol-origin:margin; left:8px; padding:0 5px; "
            "background:#DCECEF; color:#19556A; font-weight:650; }"
        )
        library_group.setStyleSheet(legacy_frame_style)
        library_group.setFixedSize(210, 510)
        library_layout = QVBoxLayout(library_group)
        library_layout.setContentsMargins(4, 5, 4, 7)
        library_layout.setSpacing(4)
        library_layout.setAlignment(Qt.AlignmentFlag.AlignTop)
        body_header = QWidget()
        body_header.setFixedHeight(28)
        body_header_layout = QVBoxLayout(body_header)
        body_header_layout.setContentsMargins(0, 0, 0, 0)
        body_header_layout.setSpacing(4)
        self.body_selection = QLabel("当前选择的图块编号：00")
        self.body_selection.setStyleSheet(
            "color:#A12626; font-weight:650; background:#FFF4F2; "
            "border:1px solid #E8C1BB; border-radius:3px; padding-left:5px;"
        )
        self.body_selection.setFixedHeight(22)
        body_header_layout.addWidget(self.body_selection)
        # Keep the upload options available to the database-page shortcuts,
        # but do not expose an extra row that the reference puzzle window
        # does not have.  Import/export remain in the library context menu.
        body_advanced_options = QWidget(body_header)
        body_import_options = QHBoxLayout(body_advanced_options)
        body_import_options.setContentsMargins(0, 0, 0, 0)
        body_import_options.setSpacing(4)
        body_import_options.addWidget(QLabel("导图偏移"))
        self.body_import_offset = QSpinBox()
        self.body_import_offset.setRange(0, 63)
        self.body_import_offset.setFixedWidth(48)
        self.body_import_offset.setToolTip(
            "导入的第一个图块写到当前主体图库的此编号。"
        )
        body_import_options.addWidget(self.body_import_offset)
        self.body_compress_upload = QCheckBox("压缩/复用")
        self.body_compress_upload.setChecked(True)
        self.body_compress_upload.setToolTip(
            "勾选时接受不超过128×128的原图，不缩放、不裁剪；不足8像素整数倍时"
            "我方贴左下、敌方贴右下补背景到完整图块；"
            "导入前自动比较横纵各最多3像素的无损微调位置，只在图块更少时采用；"
            "去除空白图块，并优先复用当前图库中完全相同的图块；"
            "差异图块写入安全空位，再生成完整稀疏拼图；"
            "取消时同样补齐网格，但图片不得超过64×64，仍按最少图块导入。"
        )
        body_import_options.addWidget(self.body_compress_upload)
        body_advanced_options.hide()
        body_header_layout.addStretch()
        library_layout.addWidget(body_header)
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
        # Keep the two independent options on separate rows.  Placing both in
        # the 192 px legacy library column clipped their captions at 100% and
        # became visibly crowded at 125%.
        body_tools = QVBoxLayout()
        body_tools.setSpacing(2)
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
        body_import_actions = QWidget(library_group)
        self.body_import_button = QPushButton("上传机体…")
        self.body_import_button.setToolTip(
            "按导图偏移和压缩上传选项导入图片，并生成主体拼图代码。"
        )
        self.body_import_button.clicked.connect(lambda: self._import_library("body"))
        self.body_export_button = QPushButton("导出BMP…")
        self.body_export_button.setToolTip("导出当前显示的 64×64 主体图库")
        self.body_export_button.clicked.connect(lambda: self._export_library("body"))
        clear_body_library = QPushButton("清除机体")
        clear_body_library.clicked.connect(lambda: self._clear_image("body"))
        for button in (
            self.body_import_button, self.body_export_button, clear_body_library
        ):
            button.setParent(body_import_actions)
        body_import_actions.hide()
        self.body_library_group = library_group
        body_grid.addWidget(library_group, 0, 0)

        composition_group = QGroupBox("效果图（提示：左键编辑图块，右键删除图块）")
        composition_group.setObjectName("puzzleCompositionPanel")
        composition_group.setStyleSheet(legacy_frame_style)
        composition_group.setFixedSize(496, 510)
        composition_grid = QGridLayout(composition_group)
        composition_grid.setContentsMargins(4, 5, 4, 7)
        composition_grid.setHorizontalSpacing(8)
        composition_grid.setVerticalSpacing(4)
        composition_grid.setAlignment(Qt.AlignmentFlag.AlignTop)
        composition_grid.setRowMinimumHeight(0, 28)
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
            button.setObjectName("puzzleDirectionButton")
            button.setToolTip("按一个 8×8 图块移动主体拼图")
            button.clicked.connect(
                lambda _checked=False, x=dx, y=dy: self._move_body(x, y)
            )
            if key in ("left", "right"):
                button.setFixedSize(24, 148)
                button.setStyleSheet("padding:0;")
            else:
                button.setFixedSize(134, 24)
            composition_grid.addWidget(
                button, row_index, column_index, Qt.AlignmentFlag.AlignCenter
            )
            self.body_move_buttons[key] = button
        self.body_composition_group = composition_group
        body_grid.addWidget(composition_group, 0, 1)
        body_grid.setColumnStretch(0, 0)
        body_grid.setColumnStretch(1, 1)
        preview_tabs.addTab(body_tab, "战斗合成")

        fragment_tab = QWidget()
        fragment_layout = QVBoxLayout(fragment_tab)
        fragment_layout.setContentsMargins(0, 0, 0, 0)
        fragment_layout.setSpacing(4)

        fragment_top = QHBoxLayout()
        fragment_top.setSpacing(8)
        fragment_reference = QGroupBox("参考设置")
        fragment_reference.setObjectName("puzzleReferencePanel")
        # Match the reference editor's two vertical columns: captions above
        # their controls, with type/fragment on the left and body banks on the
        # right.  This is both easier to scan and gives long addresses room.
        fragment_reference.setFixedWidth(432)
        self.fragment_reference_group = fragment_reference
        fragment_reference_layout = QGridLayout(fragment_reference)
        fragment_reference_layout.setContentsMargins(9, 10, 9, 7)
        fragment_reference_layout.setHorizontalSpacing(12)
        fragment_reference_layout.setVerticalSpacing(2)
        self.fragment_unit_type_editor = QComboBox()
        for index in range(self.unit_type_editor.count()):
            self.fragment_unit_type_editor.addItem(
                self.unit_type_editor.itemText(index), self.unit_type_editor.itemData(index)
            )
        self.fragment_unit_type_editor.setCurrentIndex(self.unit_type_editor.currentIndex())
        self.fragment_unit_type_editor.setFixedSize(164, 24)
        self.fragment_reference_labels = {
            "type": QLabel("机体类型"),
            "fragment": QLabel("碎片地址"),
            "body1": QLabel("图库地址1"),
            "body2": QLabel("图库地址2"),
        }
        for label in self.fragment_reference_labels.values():
            label.setObjectName("puzzleFieldLabel")
        fragment_reference_layout.addWidget(self.fragment_reference_labels["type"], 0, 0)
        fragment_reference_layout.addWidget(self.fragment_reference_labels["body1"], 0, 1)
        fragment_reference_layout.addWidget(self.fragment_unit_type_editor, 1, 0)
        self.fragment_bank_proxies: list[ChrBankComboBox] = []
        for source in self.bank_editors:
            proxy = ChrBankComboBox(project, bank_max)
            proxy.setValue(source.value())
            proxy.setFixedSize(164, 24)
            self.fragment_bank_proxies.append(proxy)
        fragment_reference_layout.addWidget(self.fragment_bank_proxies[1], 1, 1)
        fragment_reference_layout.addWidget(self.fragment_reference_labels["fragment"], 2, 0)
        fragment_reference_layout.addWidget(self.fragment_reference_labels["body2"], 2, 1)
        fragment_reference_layout.addWidget(self.fragment_bank_proxies[0], 3, 0)
        fragment_reference_layout.addWidget(self.fragment_bank_proxies[2], 3, 1)
        fragment_reference_layout.setColumnStretch(0, 1)
        fragment_reference_layout.setColumnStretch(1, 1)
        self.fragment_unit_type_editor.currentIndexChanged.connect(
            lambda index: self.unit_type_editor.setCurrentIndex(index)
        )
        self.unit_type_editor.currentIndexChanged.connect(
            lambda index: self.fragment_unit_type_editor.setCurrentIndex(index)
        )
        for source, proxy in zip(self.bank_editors, self.fragment_bank_proxies):
            proxy.valueChanged.connect(source.setValue)
            source.valueChanged.connect(proxy.setValue)
        fragment_top.addWidget(fragment_reference)

        fragment_code_group = QGroupBox("代码编辑")
        fragment_code_group.setObjectName("puzzleCodePanel")
        self.fragment_code_group = fragment_code_group
        fragment_code_layout = QVBoxLayout(fragment_code_group)
        fragment_code_layout.setContentsMargins(9, 10, 9, 7)
        fragment_code_layout.setSpacing(5)
        self.fragment_script_view = QPlainTextEdit()
        self.fragment_script_view.setLineWrapMode(QPlainTextEdit.LineWrapMode.WidgetWidth)
        self.fragment_script_view.setPlainText(self.appearance.fragment_script.hex(" ").upper())
        self.fragment_script_view.setMaximumHeight(66)
        fragment_script_font = self.fragment_script_view.font()
        fragment_script_font.setPointSize(8)
        self.fragment_script_view.setFont(fragment_script_font)
        fragment_code_layout.addWidget(self.fragment_script_view)
        fragment_code_actions = QHBoxLayout()
        fragment_code_actions.setSpacing(5)
        clear_fragment = QPushButton("清除")
        clear_fragment.setObjectName("puzzleClearButton")
        clear_fragment.clicked.connect(
            lambda: self._clear_image("fragment", confirm=False)
        )
        validate_fragment = QPushButton("查看效果")
        validate_fragment.setObjectName("puzzlePreviewButton")
        validate_fragment.clicked.connect(self.apply_script_text)
        horizontal_quick = QPushButton("水平镜像翻转")
        vertical_quick = QPushButton("垂直镜像翻转")
        horizontal_quick.setObjectName("puzzleTemplateButton")
        vertical_quick.setObjectName("puzzleTemplateButton")
        horizontal_quick.clicked.connect(lambda: self._flip_fragment(0x40))
        vertical_quick.clicked.connect(lambda: self._flip_fragment(0x80))
        for button, width in (
            (clear_fragment, 72),
            (validate_fragment, 84),
            (horizontal_quick, 110),
            (vertical_quick, 110),
        ):
            button.setFixedWidth(width)
            button.setFixedHeight(24)
        fragment_code_actions.addStretch(1)
        for button in (clear_fragment, validate_fragment, horizontal_quick, vertical_quick):
            fragment_code_actions.addWidget(button)
        fragment_code_actions.addStretch(1)
        self.fragment_clear_button = clear_fragment
        self.fragment_validate_button = validate_fragment
        self.fragment_horizontal_flip_button = horizontal_quick
        self.fragment_vertical_flip_button = vertical_quick
        fragment_code_layout.addLayout(fragment_code_actions)
        fragment_top.addWidget(fragment_code_group, 1)
        fragment_layout.addLayout(fragment_top)

        fragment_content = QHBoxLayout()
        fragment_content.setSpacing(4)
        fragment_library_group = QGroupBox("图库（提示：左键选择图块）")
        fragment_library_group.setStyleSheet(legacy_frame_style)
        fragment_library_group.setFixedSize(400, 523)
        fragment_library_layout = QVBoxLayout(fragment_library_group)
        fragment_library_layout.setContentsMargins(4, 5, 4, 7)
        fragment_library_layout.setSpacing(4)
        self.fragment_library_preview = InteractivePreviewLabel()
        self.fragment_library_preview.setAlignment(
            Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignTop
        )
        self.fragment_library_preview.setStyleSheet("background:black; border:1px solid #333;")
        self.fragment_library_preview.setFixedSize(384, 192)
        fragment_library_layout.addWidget(
            self.fragment_library_preview, 0, Qt.AlignmentFlag.AlignHCenter
        )
        self.show_fragment_numbers = QCheckBox("显示图块编号")
        self.show_fragment_numbers.toggled.connect(self.refresh_preview)
        fragment_library_layout.addWidget(self.show_fragment_numbers)
        self.fragment_placements_view = QListWidget()
        self.fragment_placements_view.setAlternatingRowColors(True)
        self.fragment_placements_view.setUniformItemSizes(True)
        self.fragment_placements_view.setToolTip(
            "单击一项即可选中对应碎片，并在上方图库中用红框定位其图块。"
        )
        self.fragment_placements_view.setFixedHeight(230)
        fragment_library_layout.addWidget(self.fragment_placements_view)
        self.fragment_add_tile_button = QPushButton("添加图块")
        self.fragment_add_tile_button.setObjectName("puzzleTemplateButton")
        self.fragment_add_tile_button.setFixedHeight(24)
        self.fragment_add_tile_button.setToolTip(
            "逐个向碎片拼图追加图块；可使用当前选中图块，或输入十六进制图块号。"
        )
        self.fragment_add_tile_button.clicked.connect(self._add_fragment_tile)
        fragment_library_layout.addWidget(self.fragment_add_tile_button)
        hidden_fragment_tools = QWidget(fragment_library_group)
        self.fragment_selection = QLabel("已选碎片图块 $00")
        self.fragment_import_offset = QSpinBox()
        self.fragment_import_offset.setRange(0, 127)
        self.fragment_compress_upload = QCheckBox("压缩/复用")
        self.fragment_compress_upload.setChecked(True)
        self.fragment_compress_upload.setToolTip(
            "勾选时以最少8×8图块覆盖非背景像素，优先复用当前图库中完全"
            "相同的图块，差异图块写入安全空位并生成碎片拼图脚本。"
        )
        self.fragment_import_button = QPushButton("导入BMP…")
        self.fragment_import_button.clicked.connect(lambda: self._import_library("fragment"))
        self.fragment_export_button = QPushButton("导出BMP…")
        self.fragment_export_button.clicked.connect(lambda: self._export_library("fragment"))
        for widget in (
            self.fragment_selection, self.fragment_import_offset,
            self.fragment_compress_upload, self.fragment_import_button,
            self.fragment_export_button,
        ):
            widget.setParent(hidden_fragment_tools)
        hidden_fragment_tools.hide()
        fragment_content.addWidget(fragment_library_group)

        fragment_composition_group = QGroupBox(
            "效果图片（提示：左键编辑调整图块位置，右键翻转图块）"
        )
        fragment_composition_group.setStyleSheet(legacy_frame_style)
        fragment_composition_group.setFixedSize(451, 523)
        fragment_composition_grid = QGridLayout(fragment_composition_group)
        fragment_composition_grid.setContentsMargins(4, 5, 4, 7)
        fragment_composition_grid.setHorizontalSpacing(4)
        fragment_composition_grid.setVerticalSpacing(4)
        self.fragment_composition_preview = InteractivePreviewLabel()
        self.fragment_composition_preview.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.fragment_composition_preview.setStyleSheet("background:black; border:1px solid #333;")
        self.fragment_composition_preview.setFixedSize(384, 384)
        fragment_composition_grid.addWidget(self.fragment_composition_preview, 1, 1)
        self.fragment_move_buttons: dict[str, QPushButton] = {}
        for key, caption, dx, dy, row_index, column_index in (
            ("up", "向上移动", 0, -1, 0, 1),
            ("left", "向\n左\n移\n动", -1, 0, 1, 0),
            ("right", "向\n右\n移\n动", 1, 0, 1, 2),
            ("down", "向下移动", 0, 1, 2, 1),
        ):
            button = QPushButton(caption)
            button.clicked.connect(
                lambda _checked=False, x=dx, y=dy: self._move_fragment(x, y)
            )
            if key in ("left", "right"):
                button.setFixedSize(24, 168)
                button.setStyleSheet("padding:0;")
            else:
                button.setFixedSize(134, 24)
            fragment_composition_grid.addWidget(
                button, row_index, column_index, Qt.AlignmentFlag.AlignCenter
            )
            self.fragment_move_buttons[key] = button
        fragment_content.addWidget(fragment_composition_group)
        fragment_layout.addLayout(fragment_content)
        preview_tabs.addTab(fragment_tab, "碎片原始图库")

        script_tab = QWidget()
        script_layout = QGridLayout(script_tab)
        script_layout.addWidget(QLabel("主体与碎片脚本已移到各自参考版页面。"), 0, 0)
        body_script_note = QLabel("使用顶部“主体代码编辑”及其模板按钮。")
        body_script_note.setAlignment(Qt.AlignmentFlag.AlignCenter)
        script_layout.addWidget(body_script_note, 1, 0)
        preview_tabs.addTab(script_tab, "拼图脚本原码")
        self.preview_tabs = preview_tabs
        self.previews = (
            self.body_library_preview,
            self.body_composition_preview,
            self.fragment_library_preview,
            self.fragment_composition_preview,
        )
        self.status = QLabel()
        self.status.setWordWrap(True)
        self.status.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        self.status.hide()
        self.setStyleSheet(
            self.styleSheet()
            + """
            QDialog#unitAppearanceDialog { background:#F2F6F8; }
            QGroupBox#puzzleReferencePanel {
                background:#F7FAFC; border:1px solid #AFC7D0; border-radius:6px;
            }
            QGroupBox#puzzleReferencePanel::title {
                background:#DCECEF; color:#19556A; font-weight:650;
                padding:0 5px;
            }
            QGroupBox#puzzleCodePanel {
                background:#F8FAFC; border:1px solid #ADC5D0; border-radius:6px;
            }
            QGroupBox#puzzleCodePanel::title {
                background:#E2EDF2; color:#294F62; font-weight:650;
                padding:0 5px;
            }
            QLabel#puzzleFieldLabel {
                color:#315C6C; font-weight:600;
            }
            QPushButton#puzzleTemplateButton, QPushButton#puzzleDirectionButton {
                color:#214F65; background:#EDF6FA; border:1px solid #8EB6C7;
            }
            QPushButton#puzzleTemplateButton:hover, QPushButton#puzzleDirectionButton:hover {
                background:#DDEFF6; border-color:#4D91AA;
            }
            QPushButton#puzzlePreviewButton {
                color:#FFFFFF; background:#3E899D; border:1px solid #33788B;
                font-weight:650;
            }
            QPushButton#puzzlePreviewButton:hover { background:#34798C; }
            QPushButton#puzzleClearButton {
                color:#A23A31; background:#FFF3F0; border:1px solid #DCA69F;
            }
            QPushButton#puzzleClearButton:hover { background:#FBE4DF; }
            """
        )
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.button(QDialogButtonBox.StandardButton.Ok).setText("确定")
        buttons.button(QDialogButtonBox.StandardButton.Cancel).setText("取消")
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        bottom_actions = QHBoxLayout()
        self.body_auto_align_check = QCheckBox("导入自动微调")
        self.body_auto_align_check.setChecked(True)
        self.body_auto_align_check.setToolTip(
            "开启：按右侧像素上限搜索机体位置，只有唯一图块数严格减少时才移动；"
            "关闭：始终保持原位置。"
        )
        bottom_actions.addWidget(self.body_auto_align_check)
        self.body_auto_align_pixels = QSpinBox()
        self.body_auto_align_pixels.setRange(1, 7)
        self.body_auto_align_pixels.setValue(3)
        self.body_auto_align_pixels.setFixedWidth(44)
        self.body_auto_align_pixels.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.body_auto_align_pixels.setToolTip(
            "自动微调的单轴最大像素数；8×8图块相位只需检查1—7像素。"
        )
        self.body_auto_align_pixels.setEnabled(
            self.body_auto_align_check.isChecked()
        )
        self.body_auto_align_check.toggled.connect(
            self.body_auto_align_pixels.setEnabled
        )
        bottom_actions.addWidget(self.body_auto_align_pixels)
        bottom_actions.addWidget(QLabel("px"))
        self.sync_shared_previews_check = QCheckBox("同步同组贴图")
        self.sync_shared_previews_check.setChecked(True)
        self.sync_shared_previews_check.setToolTip(
            "开启：主体或碎片拼图持续同步到原版同指针组；"
            "关闭：只修改当前机体，仍可复用图库中完全相同的8×8图块。"
        )
        bottom_actions.addWidget(self.sync_shared_previews_check)
        bottom_actions.addStretch(1)
        bottom_actions.addWidget(buttons)
        root.addLayout(bottom_actions)
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
        self.fragment_composition_preview.image_pressed.connect(
            self._fragment_composition_pressed
        )
        self.fragment_placements_view.currentRowChanged.connect(
            self._fragment_placement_selected
        )
        preview_tabs.currentChanged.connect(self._page_changed)
        self._last_composition_point = (0, 0)
        self._type_changed(refresh=False)
        self._page_changed(preview_tabs.currentIndex())
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

    def _type_changed(self, _index: int = -1, *, refresh: bool = True) -> None:
        large = self._is_large()
        if large and self.bank_editors[2].value() == 0:
            self.bank_editors[2].setValue(
                min(self.bank_editors[1].value() + 1, self.bank_editors[2].count() - 1)
            )
        self.bank_editors[2].setEnabled(large)
        if hasattr(self, "fragment_bank_proxies"):
            self.fragment_bank_proxies[2].setEnabled(large)
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
        if refresh:
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

    def _replace_script(
        self, kind: str, script: bytes, *, clear_request: bool = False
    ) -> None:
        if clear_request:
            self._clear_script_requests.add(kind)
        else:
            self._clear_script_requests.discard(kind)
        if kind == "body":
            self._transient_body_preview = None
            self.body_script = script
            self.body_script_view.setPlainText(script.hex(" ").upper())
        else:
            self._transient_fragment_preview = None
            self.fragment_script = script
            self.fragment_script_view.setPlainText(script.hex(" ").upper())
        self.refresh_preview()

    def _move_body(self, dx: int, dy: int) -> None:
        self._replace_script(
            "body",
            move_body_script(
                self.body_script,
                dx,
                dy,
                enemy=bool(self._type_code() & 0x40),
            ),
        )

    def _apply_body_grid(
        self, width: int, height: int, *, import_offset: int = 0
    ) -> None:
        """Apply one legacy continuous-tile body layout to the visible bank."""

        first_tile = self._body_display_offset() + import_offset
        script = apply_legacy_body_template(
            self.body_script,
            width,
            height,
            first_tile=first_tile,
            enemy=bool(self._type_code() & 0x40),
        )
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
            # Context-menu operations belong to the page that contains the
            # actually selected tile.  A right click on the lower half of a
            # large-unit library selects $40-$7F even when the optional
            # "调换图库拼图" checkbox is not checked.
            first = self._selected_body_tile // 64 * 64
            return tuple(range(first, first + 64))
        return tuple(range(128))

    def _body_import_indices(self) -> tuple[int, ...]:
        """Return body slots available from the currently displayed page onward.

        A large unit owns two consecutive 64-tile pages.  The checkbox chooses
        the import starting page; it must not incorrectly cap an import that
        starts on page 1 to that page alone.
        """

        first = self._body_display_offset()
        return tuple(range(first, len(self._library_banks("body")) * 64))

    def _absolute_tile(self, kind: str, local_tile: int | None = None) -> int:
        local_tile = self._selected_local_tile(kind) if local_tile is None else local_tile
        banks = self._library_banks(kind)
        bank_slot, tile = divmod(local_tile, 64)
        if not 0 <= bank_slot < len(banks):
            raise ValueError("所选图块不在当前图库中。")
        return banks[bank_slot] * 64 + tile

    def _select_library_tile(self, kind: str, x: int, y: int) -> None:
        if kind == "fragment":
            local_tile = (y // 8) * 16 + x // 8
        else:
            bank_slot = y // 64
            local_y = y % 64
            local_tile = bank_slot * 64 + (local_y // 8) * 8 + x // 8
        if local_tile >= len(self._library_banks(kind)) * 64:
            return
        if kind == "body":
            self._selected_body_tile = local_tile
            self.body_import_offset.setValue(
                local_tile - self._library_local_indices("body")[0]
            )
            self.body_selection.setText(f"当前选择的图块编号：{local_tile:02X}")
        else:
            self._selected_fragment_tile = local_tile
            self.fragment_import_offset.setValue(local_tile)
            self.fragment_selection.setText(f"已选碎片图块 ${local_tile:02X}")
        self.refresh_preview()

    def _use_selected_import_offset(self, kind: str) -> None:
        """Make a library context-menu import start at the red selection."""

        if kind == "body":
            first = self._library_local_indices("body")[0]
            self.body_import_offset.setValue(self._selected_body_tile - first)
        else:
            self.fragment_import_offset.setValue(self._selected_fragment_tile)

    def _import_from_selected_tile(self, kind: str) -> None:
        self._use_selected_import_offset(kind)
        if kind == "fragment":
            # The per-tile import flow is driven by hexadecimal library numbers.
            # Keep those numbers visible while the user confirms or adjusts each
            # destination, matching the red selection in the library preview.
            self.show_fragment_numbers.blockSignals(True)
            self.show_fragment_numbers.setChecked(True)
            self.show_fragment_numbers.blockSignals(False)
            self._refresh_fragment_library_preview()
        self._import_library(kind)

    def _ask_legacy_fragment_import_position(self) -> bool | None:
        """Reproduce the reference editor's compact Yes/No position prompt."""

        prompt = QMessageBox(self)
        prompt.setIcon(QMessageBox.Icon.Question)
        prompt.setWindowTitle("自定义导入位置")
        prompt.setText("是否自定义导入的位置？")
        yes_button = prompt.addButton("是(Y)", QMessageBox.ButtonRole.YesRole)
        no_button = prompt.addButton("否(N)", QMessageBox.ButtonRole.NoRole)
        prompt.setDefaultButton(yes_button)
        prompt.exec()
        clicked = prompt.clickedButton()
        if clicked is yes_button:
            return True
        if clicked is no_button:
            return False
        return None

    def _prompt_legacy_fragment_tile_index(
        self, default_index: int
    ) -> tuple[str, bool]:
        """Prompt for one tile while showing the next sequential destination."""

        # A compressed fragment can require many consecutive choices.  Reusing
        # one native dialog avoids recreating and polishing a top-level window
        # for every tile (which is particularly visible on the first import).
        prompt = getattr(self, "_fragment_tile_prompt", None)
        if prompt is None:
            prompt = QInputDialog(self)
            prompt.setWindowTitle("请输入：")
            prompt.setLabelText("请输入图库的十六进制编号")
            prompt.setOkButtonText("确认输入(O)")
            prompt.setCancelButtonText("取消(C)")
            self._fragment_tile_prompt = prompt
        prompt.setTextValue(f"{default_index:02X}")
        accepted = prompt.exec() == QDialog.DialogCode.Accepted
        return prompt.textValue(), accepted

    def _add_fragment_tile(self) -> None:
        """Append one fragment using the reference editor's tile choice flow."""

        selected = self._selected_fragment_tile
        custom = QMessageBox.question(
            self,
            "自定义导入位置",
            "是否自定义导入的图块编号？\n"
            f"选择“否”将使用当前选中的图块 ${selected:02X}。",
            QMessageBox.StandardButton.Yes
            | QMessageBox.StandardButton.No
            | QMessageBox.StandardButton.Cancel,
            QMessageBox.StandardButton.No,
        )
        if custom == QMessageBox.StandardButton.Yes:
            text, accepted = QInputDialog.getText(
                self,
                "请输入",
                "请输入图库的十六进制编号（00—7F）",
                text=f"{selected:02X}",
            )
            if not accepted:
                return
            try:
                value = text.strip().lower().removeprefix("$").removeprefix("0x")
                tile_index = int(value, 16)
            except ValueError:
                QMessageBox.warning(self, "无法添加图块", "图块编号必须是 00—7F 的十六进制数。")
                return
            if not 0 <= tile_index <= 0x7F:
                QMessageBox.warning(self, "无法添加图块", "图块编号必须在 $00—$7F 之间。")
                return
        elif custom == QMessageBox.StandardButton.No:
            tile_index = selected
        else:
            return

        placements = list(decode_unit_fragment_script(self.fragment_script))
        if placements:
            previous = placements[-1]
            x, y = previous.x + 8, previous.y
            if x > 120:
                x, y = 0, min(previous.y + 8, 120)
        else:
            x, y = 0, 113
        placements.append(FragmentTile(tile_index, x, y))
        self._selected_fragment_tile = tile_index
        self.fragment_import_offset.setValue(tile_index)
        self.fragment_selection.setText(f"已选碎片图块 ${tile_index:02X}")
        self._replace_script(
            "fragment", encode_compact_fragment_placements(tuple(placements))
        )
        self.status.setText(
            f"已添加碎片图块 ${tile_index:02X}；可继续添加，或在效果图中左键调整位置。"
        )

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
        self._stage_clear_library(kind)
        self.refresh_preview()
        self.status.setText(
            f"已清空当前{('主体' if kind == 'body' else '碎片')}图库；"
            "拼图脚本保持不变，确定后才写入 ROM。"
        )

    def _stage_clear_library(self, kind: str) -> None:
        for index in self._library_local_indices(kind):
            absolute = self._absolute_tile(kind, index)
            self._remember_original_tile(absolute)
            self._draft_tiles[absolute] = (0,) * 64

    def _clear_image(self, kind: str, *, confirm: bool = True) -> bool:
        """Clear the current composition without erasing unrelated tiles."""

        subject = "机体" if kind == "body" else "碎片"
        if confirm and QMessageBox.question(
            self,
            f"清除{subject}",
            f"清除当前{subject}拼图引用的图块并置空脚本？"
            "确定前仍可用“取消”撤销。",
        ) != QMessageBox.StandardButton.Yes:
            return False
        self._clear_referenced_image(kind)
        return True

    def _clear_referenced_image(self, kind: str) -> int:
        """Clear unique tiles referenced by this script, preserving the rest."""

        if kind == "body":
            placements = decode_unit_body_script(
                self.body_script, len(self._library_banks("body")) * 64
            )
            script = b"\xFF"
        else:
            placements = decode_unit_fragment_script(self.fragment_script)
            script = bytes.fromhex("00 F0 00 00 FF")
        local_indices = sorted({placement.tile_index for placement in placements})
        cleared = 0
        for local_index in local_indices:
            absolute = self._absolute_tile(kind, local_index)
            self._remember_original_tile(absolute)
            self._draft_tiles[absolute] = (0,) * 64
            cleared += 1
        self._replace_script(kind, script, clear_request=True)
        subject = "机体" if kind == "body" else "碎片"
        self.status.setText(
            f"已清除当前{subject}拼图实际引用的 {cleared} 个图块并置空脚本；"
            "同图库中未引用的图块保持不变，"
            "确定后才写入 ROM，取消仍可完整撤销。"
        )
        return cleared

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

    def _import_library(self, kind: str, *, strict_legacy: bool = False) -> None:
        path, _filter = QFileDialog.getOpenFileName(
            self, "导入旧版 BMP 图块或图库", "", "BMP 图片 (*.bmp);;图片 (*.bmp *.png)"
        )
        if not path:
            return
        image = QImage(path)
        if image.isNull():
            QMessageBox.warning(self, "无法导入", "图片无法读取。")
            return
        if strict_legacy:
            if kind == "fragment" and (image.width(), image.height()) != (128, 128):
                QMessageBox.warning(
                    self,
                    "无法导入",
                    "碎片主页面上传只接受原始 128×128 图片；不会缩放或重新居中。",
                )
                return
            if kind == "body" and (
                image.width() < 1
                or image.height() < 1
                or image.width() > 128
                or image.height() > 128
            ):
                QMessageBox.warning(
                    self,
                    "无法导入",
                    "机体图片不得超过 128×128；不会缩放或裁剪。",
                )
                return
            compress = (
                self.body_compress_upload.isChecked()
                if kind == "body"
                else self.fragment_compress_upload.isChecked()
            )
            if not compress:
                if kind == "body":
                    self._transient_body_preview = image.copy()
                else:
                    self._transient_fragment_preview = image.copy()
                self.refresh_preview()
                self.status.setText(
                    f"已按旧修改器普通上传仅预览{('机体' if kind == 'body' else '碎片')}原图；"
                    "不会写入图库或拼图脚本。"
                )
                return
        if not strict_legacy and (image.width(), image.height()) == (8, 8):
            self._set_draft_tile(
                self._absolute_tile(kind), image_to_palette_pixels(image, WORK_PALETTE)
            )
            self.status.setText(
                f"已导入 8×8 {('主体' if kind == 'body' else '碎片')}图块；"
                "确定后才写入 ROM。"
            )
            return
        if kind == "body":
            try:
                self._import_body_image(image)
            except ValueError as error:
                QMessageBox.warning(self, "无法导入", str(error))
            return
        try:
            self._import_fragment_image(image, choose_tiles=True)
        except ValueError as error:
            QMessageBox.warning(self, "无法导入", str(error))

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

    def _plan_shared_library_tiles(
        self,
        kind: str,
        tiles: tuple[tuple[int, ...], ...],
        placements,
        *,
        first_source_tile: int,
        allocation_indices: tuple[int, ...],
    ):
        """Reuse exact library tiles and place differences in blank slots.

        Existing non-blank tiles are never overwritten by this optimisation;
        they may only be referenced.  New patterns use all-zero slots from the
        caller's allowed allocation range.  Returning ``None`` lets the legacy
        sequential importer remain available when a safe shared plan cannot
        fit in the current library.
        """

        all_indices = (
            tuple(range(len(self._library_banks("body")) * 64))
            if kind == "body"
            else tuple(range(128))
        )
        draft = self._draft_project()
        current = {
            local_index: tuple(
                draft.chr_tile_pixels(self._absolute_tile(kind, local_index))
            )
            for local_index in all_indices
        }
        pattern_to_index: dict[tuple[int, ...], int] = {}
        allocation_set = set(allocation_indices)
        for local_index in all_indices:
            if local_index not in allocation_set:
                continue
            pattern = current[local_index]
            if any(pattern):
                pattern_to_index.setdefault(pattern, local_index)
        blank_slots = [
            local_index
            for local_index in allocation_indices
            if not any(current[local_index])
        ]
        blank_cursor = 0
        source_to_target: dict[int, int] = {}
        staged: dict[int, tuple[int, ...]] = {}
        reused = 0
        for relative, tile in enumerate(tiles):
            target = pattern_to_index.get(tile)
            if target is not None:
                reused += 1
            else:
                if blank_cursor >= len(blank_slots):
                    return None
                target = blank_slots[blank_cursor]
                blank_cursor += 1
                staged[target] = tile
                pattern_to_index[tile] = target
            source_to_target[first_source_tile + relative] = target
        remapped = tuple(
            replace(item, tile_index=source_to_target[item.tile_index])
            for item in placements
        )
        return staged, remapped, reused

    def _import_body_image(self, image: QImage) -> None:
        enemy = bool(self._type_code() & 0x40)
        source_size = (image.width(), image.height())
        maximum_size = 128 if self.body_compress_upload.isChecked() else 64
        import_image = pad_body_image_to_tile_grid(
            image,
            enemy=enemy,
            maximum_size=maximum_size,
        )
        padded_size = (import_image.width(), import_image.height())
        if padded_size == source_size:
            size_note = f"原图 {source_size[0]}×{source_size[1]}（无需补边）"
        else:
            anchor = "右下" if enemy else "左下"
            size_note = (
                f"原图 {source_size[0]}×{source_size[1]}，按{anchor}锚点补背景为 "
                f"{padded_size[0]}×{padded_size[1]}"
            )
        if self.body_compress_upload.isChecked():
            self._transient_body_preview = None
            import_offset = self.body_import_offset.value()
            indices = self._body_import_indices()
            available = len(indices) - import_offset
            first_source_tile = indices[0] + import_offset
            best = None
            minimum_tile_count = None
            maximum_shift = (
                self.body_auto_align_pixels.value()
                if self.body_auto_align_check.isChecked()
                else 0
            )
            for candidate, shift_x, shift_y in body_import_alignment_candidates(
                image,
                enemy=enemy,
                maximum_shift=maximum_shift,
            ):
                candidate_tiles, candidate_placements = sparse_body_tiles(
                    candidate,
                    first_tile=first_source_tile,
                    enemy=enemy,
                )
                minimum_tile_count = (
                    len(candidate_tiles)
                    if minimum_tile_count is None
                    else min(minimum_tile_count, len(candidate_tiles))
                )
                if len(candidate_tiles) > available:
                    continue
                candidate_plan = self._plan_shared_library_tiles(
                    "body",
                    candidate_tiles,
                    candidate_placements,
                    first_source_tile=first_source_tile,
                    allocation_indices=indices[import_offset:],
                )
                if candidate_plan is None:
                    candidate_staged = {
                        indices[import_offset + relative]: tile
                        for relative, tile in enumerate(candidate_tiles)
                    }
                    candidate_remapped = candidate_placements
                    candidate_reused = 0
                    candidate_allocation_note = "安全空位不足，按原导图偏移顺序写入"
                else:
                    candidate_staged, candidate_remapped, candidate_reused = candidate_plan
                    candidate_allocation_note = (
                        f"复用现有相同图块 {candidate_reused} 个，只新增 "
                        f"{len(candidate_staged)} 个差异图块"
                    )
                candidate_script = encode_sparse_body_placements(candidate_remapped)
                key = (
                    len(candidate_tiles),
                    0 if (shift_x, shift_y) == (0, 0) else 1,
                    len(candidate_staged),
                    len(candidate_script),
                    abs(shift_x) + abs(shift_y),
                    abs(shift_y),
                    abs(shift_x),
                    shift_y,
                    shift_x,
                )
                if best is None or key < best[0]:
                    best = (
                        key,
                        candidate_tiles,
                        candidate_staged,
                        candidate_script,
                        candidate_allocation_note,
                        shift_x,
                        shift_y,
                    )
            if best is None:
                raise ValueError(
                    f"主体最少分块需要 {minimum_tile_count or 0} 个图块，"
                    f"偏移 ${import_offset:02X} 后"
                    f"只剩 {available} 个图块。"
                )
            (
                _key,
                tiles,
                staged,
                body_script,
                allocation_note,
                shift_x,
                shift_y,
            ) = best
            if not self.body_auto_align_check.isChecked():
                alignment_note = "已关闭自动微调，保持原位置"
            elif shift_x or shift_y:
                horizontal = (
                    f"向右 {shift_x} 像素" if shift_x > 0
                    else f"向左 {-shift_x} 像素" if shift_x < 0
                    else "横向不动"
                )
                vertical = (
                    f"向下 {shift_y} 像素" if shift_y > 0
                    else f"向上 {-shift_y} 像素" if shift_y < 0
                    else "纵向不动"
                )
                alignment_note = f"导入前自动微调：{horizontal}、{vertical}"
            else:
                alignment_note = (
                    f"原位置已是 {maximum_shift} 像素范围内的最少图块方案"
                )
            for local_index, tile in staged.items():
                absolute = self._absolute_tile("body", local_index)
                self._remember_original_tile(absolute)
                self._draft_tiles[absolute] = tile
            self._replace_script("body", body_script)
            self.status.setText(
                f"主体自动分块完成：{size_note}；使用 {len(tiles)} 个图库图块（数量最少）；"
                f"{alignment_note}；{allocation_note}，"
                f"从偏移 ${import_offset:02X} 的安全范围分配并生成完整拼图脚本；"
                "未使用图块保持原值；确定后才写入 ROM。"
            )
            return
        indices = self._body_import_indices()
        import_offset = self.body_import_offset.value()
        available = len(indices) - import_offset
        tiles, placements = sparse_body_tiles(
            import_image,
            first_tile=indices[0] + import_offset,
            enemy=enemy,
        )
        if len(tiles) > available:
            raise ValueError(
                f"主体最少分块需要 {len(tiles)} 个图块，偏移 ${import_offset:02X} 后"
                f"只剩 {available} 个图块。"
            )
        for relative, tile in enumerate(tiles):
            local_index = indices[import_offset + relative]
            absolute = self._absolute_tile("body", local_index)
            self._remember_original_tile(absolute)
            self._draft_tiles[absolute] = tile
        self._replace_script("body", encode_sparse_body_placements(placements))
        self.status.setText(
            f"已导入机体图片：{size_note}；使用 {len(tiles)} 个"
            f"图库图块（相同图块已复用，数量最少），从偏移 ${import_offset:02X} "
            "写入并生成主体拼图脚本，后续未使用图块保持原值；"
            "确定后才写入 ROM。"
        )

    def _import_fragment_image(
        self, image: QImage, *, choose_tiles: bool = False
    ) -> None:
        offset = self.fragment_import_offset.value()
        indices = self._library_local_indices("fragment")
        if not self.fragment_compress_upload.isChecked():
            if (image.width(), image.height()) != (64, 128):
                raise ValueError("未勾选“压缩上传”时，碎片图片必须为 64×128。")
            for source_index, local_index in enumerate(indices[offset:]):
                tile_x = (source_index % 8) * 8
                tile_y = (source_index // 8) * 8
                pixels = image_to_palette_pixels(
                    image.copy(tile_x, tile_y, 8, 8), WORK_PALETTE
                )
                absolute = self._absolute_tile("fragment", local_index)
                self._remember_original_tile(absolute)
                self._draft_tiles[absolute] = pixels
            self.refresh_preview()
            self.status.setText(
                f"已从偏移 ${offset:02X} 顺序导入 {len(indices) - offset} 个图库图块；"
                "未重建碎片脚本，确定后才写入 ROM。"
            )
            return

        if (image.width(), image.height()) != (128, 128):
            raise ValueError(
                "旧修改器的碎片自动分块只接受原始 128×128 图片；"
                "不会缩放或重新居中。"
            )
        self._transient_fragment_preview = None
        available = len(indices) - offset
        custom = False
        if choose_tiles:
            custom_choice = self._ask_legacy_fragment_import_position()
            if custom_choice is None:
                return
            custom = custom_choice
        self.status.setText("正在分析碎片并计算最少图块，请稍候…")
        QApplication.processEvents()
        result = optimize_fragment_slices(
            image,
            first_tile=offset,
            enemy=bool(self._type_code() & 0x40),
            maximum_tiles=available,
        )
        if not result.exact:
            raise ValueError(
                "碎片组合过于复杂，当前搜索上限内无法证明图块数量已经最少；"
                "未写入任何草稿，请减少零散像素后重试。"
            )

        tile_indices = [indices[offset + relative] for relative in range(len(result.tiles))]
        staged_incrementally = False
        if choose_tiles and custom:
            draft_before = dict(self._draft_tiles)
            originals_before = dict(self._original_draft_tiles)
            selected_before = self._selected_fragment_tile
            selected: list[int] = []
            next_default = tile_indices[0]
            try:
                for number, tile in enumerate(result.tiles, start=1):
                    if next_default > 0x7F:
                        raise ValueError(
                            "后续默认图块编号已超过 $7F；请从更靠前的图块开始导入。"
                        )
                    text, accepted = self._prompt_legacy_fragment_tile_index(
                        next_default
                    )
                    if not accepted:
                        self._draft_tiles = draft_before
                        self._original_draft_tiles = originals_before
                        self._selected_fragment_tile = selected_before
                        self.fragment_selection.setText(
                            f"已选碎片图块 ${selected_before:02X}"
                        )
                        self._refresh_fragment_library_preview()
                        return
                    value = text.strip().lower().removeprefix("$").removeprefix("0x")
                    try:
                        tile_index = int(value, 16)
                    except ValueError as error:
                        raise ValueError(
                            f"第 {number} 个图块编号必须是 00—7F 的十六进制数。"
                        ) from error
                    if not 0 <= tile_index <= 0x7F:
                        raise ValueError(
                            f"第 {number} 个图块编号必须在 $00—$7F 之间。"
                        )
                    selected.append(tile_index)
                    absolute = self._absolute_tile("fragment", tile_index)
                    self._remember_original_tile(absolute)
                    self._draft_tiles[absolute] = tile
                    self._selected_fragment_tile = tile_index
                    self.fragment_selection.setText(
                        f"已选碎片图块 ${tile_index:02X}"
                    )
                    self._refresh_fragment_library_preview()
                    QApplication.processEvents()
                    next_default = tile_index + 1
            except Exception:
                self._draft_tiles = draft_before
                self._original_draft_tiles = originals_before
                self._selected_fragment_tile = selected_before
                self.fragment_selection.setText(
                    f"已选碎片图块 ${selected_before:02X}"
                )
                self._refresh_fragment_library_preview()
                raise
            tile_indices = selected
            staged_incrementally = True

        reused = 0
        if not staged_incrementally:
            shared_plan = self._plan_shared_library_tiles(
                "fragment",
                result.tiles,
                result.placements,
                first_source_tile=offset,
                allocation_indices=indices[offset:],
            )
            if shared_plan is not None:
                staged, remapped, reused = shared_plan
                tile_indices = [item.tile_index for item in remapped]
                placements = remapped
            else:
                staged = dict(zip(tile_indices, result.tiles))
                placements = tuple(
                    replace(item, tile_index=tile_indices[index])
                    for index, item in enumerate(result.placements)
                )
            for local_index, tile in staged.items():
                absolute = self._absolute_tile("fragment", local_index)
                self._remember_original_tile(absolute)
                self._draft_tiles[absolute] = tile
        else:
            placements = tuple(
                replace(item, tile_index=tile_indices[index])
                for index, item in enumerate(result.placements)
            )
        self._replace_script(
            "fragment", encode_compact_fragment_placements(placements)
        )
        placement_text = (
            "已逐项指定图库编号"
            if choose_tiles and tile_indices != list(
                range(offset, offset + len(result.tiles))
            )
            else (
                f"复用现有相同图块 {reused} 个、只新增 {len(staged)} 个差异图块"
                if reused
                else f"从偏移 ${offset:02X} 连续写入"
            )
        )
        self.status.setText(
            f"碎片自动分块完成：{len(result.tiles)} 个图块（已证明最少，"
            f"搜索 {result.search_nodes} 个状态），{placement_text}并生成碎片脚本"
            "；后续未使用图块保持原值，原图未缩放、未重新居中，确定后才写入 ROM。"
        )

    def _page_changed(self, index: int) -> None:
        fragment_page = index == 1
        self.body_reference_group.setVisible(not fragment_page)
        self.body_code_group.setVisible(not fragment_page)
        self.setWindowTitle("碎片拼图" if fragment_page else "机体拼图")
        self.setFixedSize(887 if fragment_page else 740, 708 if fragment_page else 700)

    def _show_library_menu(self, kind: str, point: QPoint) -> None:
        menu = QMenu(self)
        actions = (
            ("从所选图块导入图片\tCtrl+D", lambda: self._import_from_selected_tile(kind)),
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

    def _fragment_composition_pressed(self, x: int, y: int, button: int) -> None:
        self._last_composition_point = (x, y)
        _body, _body_hits, fragments, fragment_hits = self._composition_hits(x, y)
        if not fragment_hits:
            return
        index = fragment_hits[-1]
        self.fragment_placements_view.setCurrentRow(index)
        if button == Qt.MouseButton.LeftButton.value:
            self._edit_fragment_at(fragments, index)
        elif button == Qt.MouseButton.RightButton.value:
            self._flip_fragment_at(fragments, index)

    def _edit_fragment_at(self, placements, index: int) -> None:
        placements = list(placements)
        editor = FragmentPlacementDialog(placements[index], self)
        if editor.exec() == QDialog.DialogCode.Accepted:
            placements[index] = editor.updated(placements[index])
            self._replace_script("fragment", encode_fragment_placements(placements))

    def _flip_fragment_at(self, placements, index: int) -> None:
        placements = list(placements)
        placement = placements[index]
        placements[index] = replace(
            placement, flip_horizontal=not placement.flip_horizontal
        )
        self._replace_script("fragment", encode_fragment_placements(placements))

    def _delete_body_at(self, placements, index: int) -> None:
        placements = list(placements)
        del placements[index]
        self._replace_script("body", encode_body_placements(placements))

    def _delete_fragment_at(self, placements, index: int) -> None:
        placements = list(placements)
        del placements[index]
        self._replace_script("fragment", encode_fragment_placements(placements))

    def _fragment_placement_selected(self, row: int) -> None:
        """Link a selected composition row to the fragment-library red frame."""

        placements = decode_unit_fragment_script(self.fragment_script)
        if not 0 <= row < len(placements):
            return
        tile_index = placements[row].tile_index
        self._selected_fragment_tile = tile_index
        self.fragment_import_offset.setValue(tile_index)
        self.fragment_selection.setText(f"已选碎片图块 ${tile_index:02X}")
        self._refresh_fragment_library_preview()

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
            draft_project,
            (fragment_bank, fragment_bank + 1),
            values[3:6],
            columns=2,
            display_palette=WORK_PALETTE,
        )
        fragment_display = legacy_fragment_library_image(
            fragment_picture,
            self._selected_fragment_tile,
            show_numbers=self.show_fragment_numbers.isChecked(),
        )
        self.fragment_library_preview.set_source_pixmap(
            QPixmap.fromImage(fragment_display), 128, 64
        )
        fragment_composition = render_unit_battle_preview(
            draft_project,
            preview_appearance,
            show_body=True,
            show_fragments=True,
            body_display_palette=WORK_PALETTE,
            fragment_display_palette=(
                WORK_PALETTE[0],
                *(palette_color(value) for value in values[3:6]),
            ),
        )
        fragment_composition_display = legacy_composition_image(
            fragment_composition,
            preview_appearance,
            # The legacy checkbox labels the library only.  The effect canvas
            # keeps a clean body/work-colour + fragment/record-colour preview.
            show_numbers=False,
            include_body=True,
            include_fragments=True,
        )
        self.fragment_composition_preview.set_source_pixmap(
            QPixmap.fromImage(fragment_composition_display), 128, 128
        )
        if self._transient_body_preview is not None:
            self.body_composition_preview.set_source_pixmap(
                QPixmap.fromImage(self._transient_body_preview), 128, 128
            )
        if self._transient_fragment_preview is not None:
            self.fragment_composition_preview.set_source_pixmap(
                QPixmap.fromImage(self._transient_fragment_preview), 128, 128
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
            f"碎片图库：${fragment_bank:02X} / ${fragment_bank + 1:02X}；"
            "固定使用旧修改器素材工作色"
        )
        self.fragment_composition_preview.setToolTip(
            f"机体素材工作色＋上色碎片预览；碎片脚本 {len(self.fragment_script)} 字节；"
            "碎片使用当前碎片三色，以便和主体区分；不叠加图块编号；"
            "左键编辑命中图块，"
            "右键切换命中碎片的水平翻转"
        )
        fragment_placements = decode_unit_fragment_script(self.fragment_script)
        selected_row = self.fragment_placements_view.currentRow()
        placement_lines = [
            f"{index:03d}: X:{item.x:03d}  Y:{item.y:03d}  图块:{item.tile_index:02X}  翻转标志:"
            + ("水平" if item.flip_horizontal else "")
            + ("垂直" if item.flip_vertical else "")
            + ("不翻转" if not item.flip_horizontal and not item.flip_vertical else "")
            for index, item in enumerate(fragment_placements)
        ]
        self.fragment_placements_view.blockSignals(True)
        self.fragment_placements_view.clear()
        self.fragment_placements_view.addItems(placement_lines or ["（无碎片图块）"])
        if placement_lines and 0 <= selected_row < len(placement_lines):
            self.fragment_placements_view.setCurrentRow(selected_row)
        self.fragment_placements_view.blockSignals(False)
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

    def _refresh_fragment_library_preview(self) -> None:
        """Repaint only the fragment library during step-by-step imports."""

        values = self.values()
        fragment_bank = values[6] & 0xFE
        fragment_picture = render_chr_banks(
            self._draft_project(),
            (fragment_bank, fragment_bank + 1),
            values[3:6],
            columns=2,
            display_palette=WORK_PALETTE,
        )
        fragment_display = legacy_fragment_library_image(
            fragment_picture,
            self._selected_fragment_tile,
            show_numbers=self.show_fragment_numbers.isChecked(),
        )
        self.fragment_library_preview.set_source_pixmap(
            QPixmap.fromImage(fragment_display), 128, 64
        )

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
            type_code = self._type_code()
            captain_flag = (
                self.appearance.configuration[0] & 0x20
                if type_code & 0x80
                else 0
            )
            desired_configuration = bytes((
                type_code | captain_flag,
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
                script_changes = {
                    kind
                    for kind, changed in (
                        ("body", body != self.appearance.body_script),
                        ("fragment", fragment != self.appearance.fragment_script),
                    )
                    if changed
                }
                if script_changes:
                    self.project.set_unit_appearance_scripts(
                        self.unit_id,
                        body_script=body if "body" in script_changes else None,
                        fragment_script=(
                            fragment if "fragment" in script_changes else None
                        ),
                        sync_shared_previews=(
                            self.sync_shared_previews_check.isChecked()
                        ),
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
