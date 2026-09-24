from __future__ import annotations

from PySide6.QtCore import QSize, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QIcon, QImage, QPainter, QPen, QPixmap
from PySide6.QtWidgets import (
    QCheckBox, QComboBox, QDialog, QDialogButtonBox, QFormLayout, QGroupBox,
    QHBoxLayout, QHeaderView, QLabel, QLineEdit, QListView, QListWidget,
    QListWidgetItem, QMenu, QPlainTextEdit, QPushButton, QSpinBox, QTableWidget,
    QTableWidgetItem, QTabWidget, QVBoxLayout, QWidget,
)

from fc_editor.codecs.animation import (
    AnimationCodec, AnimationRecord, SpriteComposition, apply_animation_patches,
    decode_script, decode_sprite_composition, decode_sprite_timeline,
)
from .workspace import ROOT


def animation_names(filename: str, count: int, first: int = 0) -> tuple[str, ...]:
    path = ROOT / "src" / "resources" / "default_config" / filename
    lines: list[str] = []
    if path.is_file():
        for encoding in ("utf-8-sig", "gb18030"):
            try:
                lines = [line.strip() for line in path.read_text(encoding=encoding).splitlines() if line.strip()]
                break
            except UnicodeError:
                continue
    return tuple(lines[i-first] if 0 <= i-first < len(lines) else "未命名" for i in range(count))


class AnimationPointerDialog(QDialog):
    """Reference-shaped prompt for locating an existing animation pointer."""

    def __init__(
        self,
        parent: QWidget | None = None,
        *,
        pointer: int = 0x8000,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("请输入：")
        self.setModal(True)
        self.setFixedSize(380, 170)
        root = QVBoxLayout(self)
        root.addWidget(QLabel("请输入动画指针"))
        self.pointer_edit = QLineEdit(pointer.to_bytes(2, "little").hex().upper())
        self.pointer_edit.setInputMask("HHHH;_")
        self.pointer_edit.selectAll()
        root.addWidget(self.pointer_edit)
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.button(QDialogButtonBox.StandardButton.Ok).setText("确认输入(&O)")
        buttons.button(QDialogButtonBox.StandardButton.Cancel).setText("取消(&C)")
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        root.addWidget(buttons)

    def value(self) -> str:
        return self.pointer_edit.text().upper()

    def pointer(self) -> int:
        raw = bytes.fromhex(self.value())
        if len(raw) != 2:
            raise ValueError("动画指针必须是两个十六进制字节。")
        return int.from_bytes(raw, "little")


class AnimationInstructionDialog(QDialog):
    """Beginner-facing editor for one verified, fixed-length instruction."""

    def __init__(
        self,
        parent: QWidget | None = None,
        *,
        instruction,
        values: tuple[int, ...],
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("编辑武器动画指令")
        self.setModal(True)
        self.setMinimumWidth(500)
        root = QVBoxLayout(self)
        summary = QLabel(
            f"{instruction.text}\n"
            f"ROM 地址：${instruction.offset:06X}　原始字节：{instruction.raw.hex(' ').upper()}"
        )
        summary.setWordWrap(True)
        root.addWidget(summary)
        form = QFormLayout()
        self.parameter_editors: list[QSpinBox] = []
        for value, (local, low, high) in zip(values, instruction.editable):
            editor = QSpinBox()
            editor.setRange(low, high)
            editor.setDisplayIntegerBase(16)
            editor.setPrefix("$ ")
            editor.setValue(value)
            editor.setToolTip(
                f"允许范围 ${low:02X}—${high:02X}；只替换当前指令的第 {local + 1} 字节。"
            )
            form.addRow(f"参数 +{local}", editor)
            self.parameter_editors.append(editor)
        root.addLayout(form)
        hint = QLabel(
            "这里只修改当前指令中已验证的参数字节，不改变脚本长度、指令边界或动画指针。"
        )
        hint.setWordWrap(True)
        root.addWidget(hint)
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.button(QDialogButtonBox.StandardButton.Ok).setText("应用到草稿")
        buttons.button(QDialogButtonBox.StandardButton.Cancel).setText("取消")
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        root.addWidget(buttons)

    def parameter_values(self) -> tuple[int, ...]:
        return tuple(editor.value() for editor in self.parameter_editors)


_WEAPON_COMMAND_PRESETS = (
    ("等待（帧）", bytes.fromhex("01"), "一字节等待时间，01—DF 帧。"),
    ("F4 定义声音", bytes.fromhex("F4 00"), "参数为音乐或音效编号。"),
    ("F0 定义颜色", bytes.fromhex("F0 11 03 0F 16 20"), "区域、数量和颜色值；默认是物理区域三色。"),
    ("F2 定义光束图库", bytes.fromhex("F2 22 01 00"), "区域、数量和图库编号。"),
    ("F3 定义光束规律", bytes.fromhex("F3 00 00"), "资源编号和规律编号。"),
    ("E0 切换 00 区域图库", bytes.fromhex("E0 00"), "参数为图库编号。"),
    ("E1 切换 01 区域图库", bytes.fromhex("E1 00"), "参数为图库编号。"),
    ("FD 移动屏幕", bytes.fromhex("FD 00 00"), "X、Y 为有符号位移字节。"),
    ("FE 跳转重复", bytes.fromhex("FE 02 00 80"), "重复次数和 CPU 小端目标地址。"),
    ("F9 创建物体", bytes.fromhex("F9 00 00 00 00 00 00 00 00"), "物体、坐标、规律、组图和 X/Y 规律。"),
    ("42 定义物体运行规律 1", bytes.fromhex("42 69 00 00 00"), "标志、组图、X 规律、Y 规律。"),
    ("C2 定义物体运行规律 2", bytes.fromhex("C2 69 00 00 00"), "标志、组图、X 规律、Y 规律。"),
    ("FF 动画结束", bytes.fromhex("FF"), "每段动画必须保留一个结束指令。"),
)


def _weapon_command_preset_index(raw: bytes) -> int:
    if len(raw) == 1 and raw[0] < 0xE0 and raw[0] not in (0x42, 0xC2):
        return 0
    for index, (_label, preset, _hint) in enumerate(_WEAPON_COMMAND_PRESETS[1:], 1):
        if raw and raw[0] == preset[0]:
            return index
    return 0


class WeaponAnimationCommandDialog(QDialog):
    """Choose and fully edit one reference-compatible weapon command."""

    def __init__(self, parent=None, *, raw: bytes | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("武器指令")
        self.setModal(True)
        self.setMinimumWidth(620)
        root = QVBoxLayout(self)
        form = QFormLayout()
        self.command_type = QComboBox()
        for label, _preset, hint in _WEAPON_COMMAND_PRESETS:
            self.command_type.addItem(label)
            self.command_type.setItemData(self.command_type.count() - 1, hint, Qt.ItemDataRole.ToolTipRole)
        form.addRow("指令类型", self.command_type)
        self.raw_edit = QLineEdit()
        self.raw_edit.setPlaceholderText("例如：F9 0F C8 B0 20 09 F9 11 15")
        form.addRow("完整字节", self.raw_edit)
        root.addLayout(form)
        self.help_label = QLabel()
        self.help_label.setWordWrap(True)
        root.addWidget(self.help_label)
        self.preview_label = QLabel()
        self.preview_label.setWordWrap(True)
        root.addWidget(self.preview_label)
        self.buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        self.buttons.button(QDialogButtonBox.StandardButton.Ok).setText("应用指令")
        self.buttons.button(QDialogButtonBox.StandardButton.Cancel).setText("取消")
        self.buttons.accepted.connect(self.accept)
        self.buttons.rejected.connect(self.reject)
        root.addWidget(self.buttons)
        self.command_type.currentIndexChanged.connect(self._select_preset)
        self.raw_edit.textChanged.connect(self._validate)
        initial = raw if raw is not None else _WEAPON_COMMAND_PRESETS[0][1]
        self.command_type.setCurrentIndex(_weapon_command_preset_index(initial))
        self.raw_edit.setText(initial.hex(" ").upper())
        self._validate()

    def _select_preset(self, index: int) -> None:
        _label, preset, _hint = _WEAPON_COMMAND_PRESETS[index]
        self.raw_edit.setText(preset.hex(" ").upper())

    def _validate(self) -> bool:
        self.help_label.setText(_WEAPON_COMMAND_PRESETS[self.command_type.currentIndex()][2])
        try:
            raw = bytes.fromhex(self.raw_edit.text())
            if not raw:
                raise ValueError("请输入指令字节。")
            probe = raw if raw == b"\xFF" else raw + b"\xFF"
            rows, complete = decode_script(probe, 0)
            if not complete or not rows or rows[0].raw != raw:
                raise ValueError("字节必须恰好组成一条受支持的完整指令。")
            self.preview_label.setText(f"预览：{rows[0].text}")
            self.preview_label.setStyleSheet("color: #176b2c;")
            self.buttons.button(QDialogButtonBox.StandardButton.Ok).setEnabled(True)
            return True
        except ValueError as error:
            self.preview_label.setText(f"不能应用：{error}")
            self.preview_label.setStyleSheet("color: #a32626;")
            self.buttons.button(QDialogButtonBox.StandardButton.Ok).setEnabled(False)
            return False

    def command(self) -> bytes:
        return bytes.fromhex(self.raw_edit.text())


class SpritePuzzlePreviewDialog(QDialog):
    """Render the verified physical-puzzle stream against real CHR tiles."""

    _PALETTES = (
        ("#151922", "#86A8D9", "#D7E5F4", "#FFFFFF"),
        ("#151922", "#72B58A", "#B8E3A8", "#F0FFD8"),
        ("#151922", "#C99163", "#F3C77D", "#FFF0C2"),
        ("#151922", "#B57DB6", "#E0B4D8", "#FFE7FA"),
    )

    def __init__(
        self,
        record: AnimationRecord,
        project,
        codec: AnimationCodec,
        parent: QWidget | None = None,
        *,
        initial_library: int = 8,
    ) -> None:
        super().__init__(parent)
        self.project = project
        self.codec = codec
        self.initial_record = record
        self.current_record = record
        self.timeline_frames: tuple[int, ...] = (record.index,)
        self.timeline_loop_start: int | None = None
        self.timeline_terminated = True
        self.frame_index = 0
        self.setWindowTitle("物理拼图")
        self.resize(1180, 760)
        root = QVBoxLayout(self)

        settings = QGroupBox("参考设置")
        form = QFormLayout(settings)
        self.library_combo = QComboBox()
        bank_count = self.project.chr_tile_count // 64
        for bank in range(max(0, bank_count - 3)):
            self.library_combo.addItem(
                f"[{bank:02X}]{bank:03d}：{0x80010 + bank * 0x400:05X}",
                bank,
            )
        selected = self.library_combo.findData(initial_library)
        self.library_combo.setCurrentIndex(max(0, selected))
        form.addRow("图库地址：", self.library_combo)
        offsets = QHBoxLayout()
        self.zero_start = QSpinBox()
        self.high_start = QSpinBox()
        for spin in (self.zero_start, self.high_start):
            spin.setRange(0, 0xFF)
            spin.setDisplayIntegerBase(16)
            spin.setPrefix("$")
        self.high_start.setValue(0x80)
        offsets.addWidget(QLabel("00 开始"))
        offsets.addWidget(self.zero_start)
        offsets.addWidget(QLabel("80 开始"))
        offsets.addWidget(self.high_start)
        self.show_numbers = QCheckBox("显示图块编号")
        self.show_numbers.setChecked(True)
        offsets.addWidget(self.show_numbers)
        offsets.addStretch()
        form.addRow("映射：", offsets)
        flips = QHBoxLayout()
        self.flip_horizontal = QCheckBox("图片水平翻转")
        self.flip_vertical = QCheckBox("图片垂直翻转")
        flips.addWidget(self.flip_horizontal)
        flips.addWidget(self.flip_vertical)
        flips.addStretch()
        form.addRow("效果图片：", flips)
        root.addWidget(settings)

        content = QHBoxLayout()
        source = QGroupBox("组图规律与解释")
        source_layout = QVBoxLayout(source)
        self.code_view = QPlainTextEdit(record.raw.hex(" ").upper())
        self.code_view.setReadOnly(True)
        self.code_view.setMaximumHeight(92)
        source_layout.addWidget(self.code_view)
        self.placement_table = QTableWidget(0, 5)
        self.placement_table.setHorizontalHeaderLabels(
            ("指令", "图块", "X", "Y", "属性")
        )
        self.placement_table.verticalHeader().hide()
        self.placement_table.horizontalHeader().setSectionResizeMode(
            QHeaderView.ResizeMode.Stretch
        )
        self.placement_table.setEditTriggers(
            QTableWidget.EditTrigger.NoEditTriggers
        )
        source_layout.addWidget(self.placement_table, 1)
        content.addWidget(source, 3)

        library = QGroupBox("图库")
        library_layout = QVBoxLayout(library)
        self.library_list = QListWidget()
        self.library_list.setViewMode(QListView.ViewMode.IconMode)
        self.library_list.setResizeMode(QListView.ResizeMode.Adjust)
        self.library_list.setMovement(QListView.Movement.Static)
        self.library_list.setIconSize(QSize(32, 32))
        self.library_list.setGridSize(QSize(48, 50))
        self.library_list.setSelectionMode(QListWidget.SelectionMode.NoSelection)
        library_layout.addWidget(self.library_list)
        content.addWidget(library, 3)

        preview = QGroupBox("效果图片")
        preview_layout = QVBoxLayout(preview)
        self.preview_label = QLabel()
        self.preview_label.setMinimumSize(390, 390)
        self.preview_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.preview_label.setStyleSheet("background:#151922; border:1px solid #66717a;")
        preview_layout.addWidget(self.preview_label, 1)
        self.preview_status = QLabel()
        self.preview_status.setWordWrap(True)
        preview_layout.addWidget(self.preview_status)
        content.addWidget(preview, 4)
        root.addLayout(content, 1)

        playback = QGroupBox("运行规律播放（只影响预览）")
        playback_layout = QHBoxLayout(playback)
        self.timeline_combo = QComboBox()
        self.timeline_combo.addItem(
            f"单帧：组图 ${record.index:02X}", None
        )
        movement_names = animation_names(
            "地图动画运行规律名称.ini", codec.count("movement"), 1
        )
        roles = codec.movement_roles()
        for index in sorted(
            value for value, role in roles.items() if role == {"frames"}
        ):
            self.timeline_combo.addItem(
                f"[{index:02X}]{index:03d}：{movement_names[index]}", index
            )
        playback_layout.addWidget(self.timeline_combo, 1)
        self.previous_button = QPushButton("上一帧")
        self.play_button = QPushButton("播放")
        self.next_button = QPushButton("下一帧")
        playback_layout.addWidget(self.previous_button)
        playback_layout.addWidget(self.play_button)
        playback_layout.addWidget(self.next_button)
        self.frame_status = QLabel()
        playback_layout.addWidget(self.frame_status, 1)
        root.addWidget(playback)

        self.timer = QTimer(self)
        self.timer.setInterval(1000 // 12)
        self.timer.timeout.connect(self._advance_frame)
        self.library_combo.currentIndexChanged.connect(self._refresh_all)
        self.zero_start.valueChanged.connect(self._refresh_all)
        self.high_start.valueChanged.connect(self._refresh_all)
        self.show_numbers.toggled.connect(self._render_preview)
        self.flip_horizontal.toggled.connect(self._render_preview)
        self.flip_vertical.toggled.connect(self._render_preview)
        self.timeline_combo.currentIndexChanged.connect(self._timeline_changed)
        self.previous_button.clicked.connect(lambda: self._step_frame(-1))
        self.next_button.clicked.connect(lambda: self._step_frame(1))
        self.play_button.clicked.connect(self._toggle_playback)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.button(QDialogButtonBox.StandardButton.Ok).setText("确定")
        buttons.button(QDialogButtonBox.StandardButton.Cancel).setText("取消")
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        root.addWidget(buttons)
        self._timeline_changed()
        self._populate_library()

    def _mapped_tile(self, logical: int) -> int:
        if logical < 0x80:
            return (self.zero_start.value() + logical) & 0xFF
        return (self.high_start.value() + (logical & 0x7F)) & 0xFF

    def _tile_image(self, logical: int, palette: int = 0) -> QImage:
        mapped = self._mapped_tile(logical)
        bank = int(self.library_combo.currentData() or 0)
        pixels = self.project.chr_tile_pixels(bank * 64 + mapped)
        image = QImage(8, 8, QImage.Format.Format_RGB32)
        colors = tuple(QColor(value) for value in self._PALETTES[palette & 3])
        for y in range(8):
            for x in range(8):
                image.setPixelColor(x, y, colors[pixels[y * 8 + x]])
        return image

    def _populate_library(self) -> None:
        self.library_list.setUpdatesEnabled(False)
        try:
            self.library_list.clear()
            for logical in range(256):
                icon = QPixmap.fromImage(self._tile_image(logical)).scaled(
                    32,
                    32,
                    Qt.AspectRatioMode.KeepAspectRatio,
                    Qt.TransformationMode.FastTransformation,
                )
                item = QListWidgetItem(QIcon(icon), f"{logical:02X}")
                item.setToolTip(
                    f"逻辑图块 ${logical:02X} → 图库内 ${self._mapped_tile(logical):02X}"
                )
                self.library_list.addItem(item)
        finally:
            self.library_list.setUpdatesEnabled(True)

    def _composition(self) -> SpriteComposition:
        return decode_sprite_composition(
            self.current_record.raw, self.current_record.offset
        )

    def _fill_placement_table(self, composition: SpriteComposition) -> None:
        self.placement_table.setRowCount(len(composition.placements))
        for row, placement in enumerate(composition.placements):
            tile = (
                f"${placement.tile_index:02X}"
                if placement.tile_index is not None
                else f"运行时 ${placement.tile_token:02X}"
            )
            flags = []
            if placement.horizontal_flip:
                flags.append("H")
            if placement.vertical_flip:
                flags.append("V")
            flags.append(f"P{placement.palette}")
            for column, value in enumerate(
                (
                    f"${placement.command_offset:06X}",
                    tile,
                    str(placement.x),
                    str(placement.y),
                    "/".join(flags),
                )
            ):
                self.placement_table.setItem(row, column, QTableWidgetItem(value))

    def _render_preview(self, _checked: bool | None = None) -> None:
        composition = self._composition()
        self._fill_placement_table(composition)
        if not composition.placements:
            self.preview_label.setPixmap(QPixmap())
            self.preview_label.setText(composition.error or "该组图没有可显示的图块。")
            self.preview_status.setText(composition.error)
            return
        min_x = min(item.x for item in composition.placements)
        max_x = max(item.x for item in composition.placements)
        min_y = min(item.y for item in composition.placements)
        max_y = max(item.y for item in composition.placements)
        width = max(24, max_x - min_x + 24)
        height = max(24, max_y - min_y + 24)
        image = QImage(width, height, QImage.Format.Format_RGB32)
        image.fill(QColor("#151922"))
        unresolved = 0
        for placement in composition.placements:
            x = placement.x
            y = placement.y
            horizontal = placement.horizontal_flip
            vertical = placement.vertical_flip
            if self.flip_horizontal.isChecked():
                x = min_x + max_x - x
                horizontal = not horizontal
            if self.flip_vertical.isChecked():
                y = min_y + max_y - y
                vertical = not vertical
            target_x = x - min_x + 8
            target_y = y - min_y + 8
            if placement.tile_index is None:
                unresolved += 1
                painter = QPainter(image)
                painter.setPen(QPen(QColor("#FF4FD8"), 1))
                painter.drawRect(target_x, target_y, 7, 7)
                painter.drawLine(target_x, target_y, target_x + 7, target_y + 7)
                painter.drawLine(target_x + 7, target_y, target_x, target_y + 7)
                painter.end()
                continue
            tile = self._tile_image(placement.tile_index, placement.palette)
            for py in range(8):
                source_y = 7 - py if vertical else py
                for px in range(8):
                    source_x = 7 - px if horizontal else px
                    color = tile.pixelColor(source_x, source_y)
                    if color != QColor(self._PALETTES[placement.palette][0]):
                        image.setPixelColor(target_x + px, target_y + py, color)
            if self.show_numbers.isChecked():
                painter = QPainter(image)
                painter.fillRect(target_x, target_y, 8, 4, QColor(0, 0, 0, 190))
                painter.setPen(QColor("white"))
                font = painter.font()
                font.setPixelSize(4)
                painter.setFont(font)
                painter.drawText(target_x, target_y, 8, 4, Qt.AlignmentFlag.AlignCenter,
                                 f"{placement.tile_index:02X}")
                painter.end()
        pixmap = QPixmap.fromImage(image).scaled(
            self.preview_label.size(),
            Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.FastTransformation,
        )
        self.preview_label.setText("")
        self.preview_label.setPixmap(pixmap)
        state = "完整" if composition.complete else f"不完整：{composition.error}"
        runtime = f"；{unresolved} 块依赖运行时图块表" if unresolved else ""
        self.preview_status.setText(
            f"组图 ${self.current_record.index:02X} · {len(composition.placements)} 块 · "
            f"锚点 X={composition.anchor_x} / Y={composition.anchor_y} · {state}{runtime}。"
        )

    def _refresh_all(self, _value: int | None = None) -> None:
        self._populate_library()
        self._render_preview()

    def _timeline_changed(self, _index: int | None = None) -> None:
        self.timer.stop()
        self.play_button.setText("播放")
        movement = self.timeline_combo.currentData()
        if movement is None:
            self.timeline_frames = (self.initial_record.index,)
            self.timeline_loop_start = None
            self.timeline_terminated = True
            error = ""
        else:
            record = self.codec.record("movement", int(movement))
            timeline = decode_sprite_timeline(
                record.raw, self.codec.count("sprite")
            )
            self.timeline_frames = timeline.frames or (self.initial_record.index,)
            self.timeline_loop_start = timeline.loop_start
            self.timeline_terminated = timeline.terminated
            error = timeline.error
        self.frame_index = 0
        self._show_frame()
        if error:
            self.frame_status.setToolTip(error)

    def _show_frame(self) -> None:
        sprite = self.timeline_frames[self.frame_index]
        self.current_record = (
            self.initial_record
            if sprite == self.initial_record.index
            else self.codec.record("sprite", sprite)
        )
        self.code_view.setPlainText(self.current_record.raw.hex(" ").upper())
        loop = (
            f" · 循环起点 {self.timeline_loop_start + 1}"
            if self.timeline_loop_start is not None
            else ""
        )
        self.frame_status.setText(
            f"帧 {self.frame_index + 1}/{len(self.timeline_frames)} · 组图 ${sprite:02X}{loop}"
        )
        self._render_preview()

    def _step_frame(self, delta: int) -> None:
        if not self.timeline_frames:
            return
        self.frame_index = (self.frame_index + delta) % len(self.timeline_frames)
        self._show_frame()

    def _advance_frame(self) -> None:
        if not self.timeline_frames:
            return
        if self.frame_index + 1 < len(self.timeline_frames):
            self.frame_index += 1
        elif self.timeline_loop_start is not None:
            self.frame_index = self.timeline_loop_start
        elif self.timeline_terminated:
            self.timer.stop()
            self.play_button.setText("播放")
            return
        else:
            self.frame_index = 0
        self._show_frame()

    def _toggle_playback(self) -> None:
        if self.timer.isActive():
            self.timer.stop()
            self.play_button.setText("播放")
        else:
            self.timer.start()
            self.play_button.setText("暂停")

    def accept(self) -> None:
        self.timer.stop()
        super().accept()

    def reject(self) -> None:
        self.timer.stop()
        super().reject()


class AnimationScriptWidget(QWidget):
    """A draft script editor; the caller owns its enclosing transaction."""
    changed = Signal()
    pointer_requested = Signal(int)
    _command_clipboard: tuple[bytes, ...] = ()

    def __init__(self, parent: QWidget | None = None, *, legacy_pointer_dialog: bool = False) -> None:
        super().__init__(parent)
        self.legacy_pointer_dialog = legacy_pointer_dialog
        self.codec: AnimationCodec | None = None
        self.record: AnimationRecord | None = None
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        self.status = QLabel("请选择动画。")
        self.status.setWordWrap(True)
        root.addWidget(self.status)
        self.instruction_table = QTableWidget(0, 2)
        self.instruction_table.setHorizontalHeaderLabels(("动画指令", "原始字节"))
        self.instruction_table.verticalHeader().hide()
        self.instruction_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self.instruction_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        self.instruction_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.instruction_table.setAlternatingRowColors(True)
        self.instruction_table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.instruction_table.currentCellChanged.connect(self._select_instruction)
        if not legacy_pointer_dialog:
            self.instruction_table.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
            self.instruction_table.customContextMenuRequested.connect(self._show_instruction_context_menu)
        self.instruction_table.cellDoubleClicked.connect(
            lambda row, _column: self.edit_instruction(row)
        )
        self.instruction_table.setToolTip(
            "参考版地图动画不使用武器动画右键菜单：左侧“添加”复制整套动画；"
            "此处选择指令后编辑已验证参数，“代码编辑”按指针定位。"
            if legacy_pointer_dialog
            else "双击或右键可全面编辑单武器动画；支持插入、替换、剪切、复制、粘贴、删除和清空。"
        )
        self.instruction_table.setMinimumHeight(200)
        root.addWidget(self.instruction_table, 1)
        self.structure_bar = QWidget()
        structure_layout = QHBoxLayout(self.structure_bar)
        structure_layout.setContentsMargins(0, 0, 0, 0)
        for text, slot in (
            ("插入指令", self.insert_instruction),
            ("编辑指令", self.edit_instruction),
            ("删除指令", self.delete_instruction),
            ("清空动画", self.clear_instructions),
        ):
            button = QPushButton(text)
            button.clicked.connect(slot)
            structure_layout.addWidget(button)
        structure_layout.addStretch()
        self.structure_bar.setVisible(not legacy_pointer_dialog)
        root.addWidget(self.structure_bar)
        self.parameters = QWidget()
        self.parameter_layout = QHBoxLayout(self.parameters)
        self.parameter_layout.setContentsMargins(0, 0, 0, 0)
        root.addWidget(self.parameters)
        self.code_button = QPushButton("代码编辑")
        self.code_button.clicked.connect(self._toggle_code)
        root.addWidget(self.code_button, 0, Qt.AlignmentFlag.AlignLeft)
        self.code_edit = QPlainTextEdit()
        self.code_edit.setPlaceholderText("完整动画十六进制代码（必须以 FF 结束）")
        self.code_edit.setMaximumHeight(130)
        self.code_edit.textChanged.connect(self._code_changed)
        self.code_edit.hide()
        root.addWidget(self.code_edit)
        hint = QLabel(
            "地图动画按参考版流程制作：先在左侧选择最接近的完整动画，点“添加”复制到预留槽，"
            "再逐条调整已验证参数；“代码编辑”输入已有动画指针用于定位，不改写指针。"
            if legacy_pointer_dialog
            else "武器动画可按指令新增、替换、删除和组合；写入范围不会越过下一条动画。"
            "共享同一指针的武器会同步变化。高级用户也可展开完整代码。"
        )
        hint.setWordWrap(True)
        root.addWidget(hint)

    def set_record(self, data: bytes | bytearray, kind: str, index: int) -> None:
        self.codec = AnimationCodec(data)
        self.record = self.codec.record(kind, index)
        record = self.record
        self._set_code(record.raw)
        self._refresh_instruction_table()
        aliases = ", ".join(f"${i:02X}" for i in record.aliases[:12])
        if len(record.aliases) > 12:
            aliases += f"…共 {len(record.aliases)} 项"
        capacity = self.codec.script_capacity(record) if record.offset else 0
        self.status.setText(f"当前 ROM · ${record.offset:06X} · 已用 {len(record.raw)}/{capacity} 字节"
                            + (f" · 共享：{aliases}" if aliases else " · 独立记录")
                            + ("" if record.complete else " · 包含未验证内容"))
        self.code_button.setEnabled(record.complete)
        self.code_edit.setReadOnly(not self.code_button.isEnabled())
        self.instruction_table.setCurrentCell(0, 0)
        self._select_instruction(0, 0, -1, -1)

    def _draft_instructions(self):
        if self.record is None:
            return (), False
        try:
            raw = bytes.fromhex(self.code_edit.toPlainText())
        except ValueError:
            return (), False
        return decode_script(raw, self.record.offset)

    def _refresh_instruction_table(self) -> None:
        rows, complete = self._draft_instructions()
        visible_rows = max(20, len(rows) + (0 if len(rows) >= 20 else 1))
        blocked = self.instruction_table.blockSignals(True)
        self.instruction_table.setRowCount(visible_rows)
        for row in range(visible_rows):
            if row < len(rows):
                instruction = rows[row]
                item = QTableWidgetItem(f"{row:03d}：{instruction.text}")
                item.setToolTip(f"文件地址 ${instruction.offset:06X}")
                raw_item = QTableWidgetItem(instruction.raw.hex(" ").upper())
            else:
                item = QTableWidgetItem(f"{row:03d}：空代码")
                item.setToolTip("右键或点击“插入指令”，会在动画结束前新增一条指令。")
                raw_item = QTableWidgetItem("")
                item.setForeground(QColor("#777777"))
            self.instruction_table.setItem(row, 0, item)
            self.instruction_table.setItem(row, 1, raw_item)
        self.instruction_table.blockSignals(blocked)
        self.instruction_table.resizeRowsToContents()
        if not complete and self.record is not None:
            self.status.setText("当前草稿不是完整动画；请修正代码或撤销本次编辑。")

    def _set_code(self, data: bytes) -> None:
        blocked = self.code_edit.blockSignals(True)
        self.code_edit.setPlainText(data.hex(" ").upper())
        self.code_edit.blockSignals(blocked)

    def _toggle_code(self) -> None:
        if self.legacy_pointer_dialog:
            pointer = 0x8000
            if self.codec is not None and self.record is not None:
                pointer = self.codec.pointers[self.record.kind][self.record.index]
            dialog = AnimationPointerDialog(self, pointer=pointer)
            if dialog.exec() == QDialog.DialogCode.Accepted:
                try:
                    selected = dialog.pointer()
                except ValueError as error:
                    self.status.setText(str(error))
                else:
                    self.pointer_requested.emit(selected)
            return
        self._toggle_raw_code()

    def _toggle_raw_code(self) -> None:
        self.code_edit.setVisible(not self.code_edit.isVisible())
        if self.code_edit.isVisible():
            self.code_edit.setFocus()

    def _show_instruction_context_menu(self, position) -> None:
        row = self.instruction_table.rowAt(position.y())
        if row >= 0:
            self.instruction_table.setCurrentCell(row, 0)
        else:
            row = self.instruction_table.currentRow()
        menu = QMenu(self.instruction_table)
        rows, complete = self._draft_instructions()
        actual = 0 <= row < len(rows)
        is_end = actual and rows[row].raw == b"\xFF"
        insert_action = menu.addAction("插入")
        insert_action.setEnabled(complete and not self.legacy_pointer_dialog)
        insert_action.triggered.connect(lambda: self.insert_instruction(row))
        edit_action = menu.addAction("编辑")
        edit_action.setEnabled(actual and not is_end and not self.legacy_pointer_dialog)
        edit_action.triggered.connect(lambda: self.edit_instruction(row))
        cut_action = menu.addAction("剪切")
        cut_action.setEnabled(actual and not is_end and not self.legacy_pointer_dialog)
        cut_action.triggered.connect(lambda: self.cut_instruction(row))
        copy_action = menu.addAction("复制")
        copy_action.setEnabled(actual and not is_end)
        copy_action.triggered.connect(lambda: self.copy_instruction(row))
        copy_all_action = menu.addAction("复制全部")
        copy_all_action.setEnabled(bool(rows))
        copy_all_action.triggered.connect(self.copy_all_instructions)
        paste_action = menu.addAction("粘贴")
        paste_action.setEnabled(bool(self._command_clipboard) and not self.legacy_pointer_dialog)
        paste_action.triggered.connect(lambda: self.paste_instructions(row, False))
        paste_all_action = menu.addAction("粘贴全部")
        paste_all_action.setEnabled(bool(self._command_clipboard) and not self.legacy_pointer_dialog)
        paste_all_action.triggered.connect(lambda: self.paste_instructions(row, True))
        delete_action = menu.addAction("删除")
        delete_action.setEnabled(actual and not is_end and not self.legacy_pointer_dialog)
        delete_action.triggered.connect(lambda: self.delete_instruction(row))
        clear_action = menu.addAction("清空")
        clear_action.setEnabled(complete and not self.legacy_pointer_dialog)
        clear_action.triggered.connect(self.clear_instructions)
        menu.addSeparator()
        action = menu.addAction(
            "隐藏完整代码编辑区" if self.code_edit.isVisible() else "显示完整代码编辑区"
        )
        action.triggered.connect(self._toggle_raw_code)
        menu.popup(self.instruction_table.viewport().mapToGlobal(position))

    def edit_instruction(self, row: int | None = None) -> None:
        if self.record is None or self.legacy_pointer_dialog:
            return
        if row is None or isinstance(row, bool):
            row = self.instruction_table.currentRow()
        rows, complete = self._draft_instructions()
        if not complete or not 0 <= row < len(rows) or rows[row].raw == b"\xFF":
            return
        dialog = WeaponAnimationCommandDialog(self, raw=rows[row].raw)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            commands = [instruction.raw for instruction in rows]
            commands[row] = dialog.command()
            self._replace_commands(commands, row)
        dialog.deleteLater()

    def insert_instruction(self, row: int | None = None) -> None:
        if self.record is None or self.legacy_pointer_dialog:
            return
        rows, complete = self._draft_instructions()
        if not complete:
            return
        commands = [instruction.raw for instruction in rows]
        end = max(0, len(commands) - 1)
        target = self.instruction_table.currentRow() if row is None or isinstance(row, bool) else row
        target = min(max(0, target), end)
        dialog = WeaponAnimationCommandDialog(self)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            command = dialog.command()
            if command == b"\xFF":
                self.status.setText("结束指令由编辑器自动保留；请选择其他指令插入。")
            else:
                commands.insert(target, command)
                self._replace_commands(commands, target)
        dialog.deleteLater()

    def _apply_instruction_values(self, row: int, values: tuple[int, ...]) -> None:
        """Keep the compact parameter controls in sync with structural edits."""

        rows, complete = self._draft_instructions()
        if not complete or not 0 <= row < len(rows):
            raise ValueError("当前动画草稿不是完整指令序列。")
        instruction = rows[row]
        if len(values) != len(instruction.editable):
            raise ValueError("动画指令参数数量不匹配。")
        command = bytearray(instruction.raw)
        for value, (local, low, high) in zip(values, instruction.editable):
            if not low <= value <= high:
                raise ValueError(f"动画参数必须在 ${low:02X}—${high:02X} 范围内。")
            command[local] = value
        commands = [current.raw for current in rows]
        commands[row] = bytes(command)
        if not self._replace_commands(commands, row):
            raise ValueError(self.status.text())

    def _replace_commands(self, commands: list[bytes] | tuple[bytes, ...], selected: int = 0) -> bool:
        if self.record is None or self.codec is None:
            return False
        normalized = [bytes(command) for command in commands if command != b"\xFF"] + [b"\xFF"]
        replacement = b"".join(normalized)
        try:
            self.codec.script_sequence_patch(self.record, replacement)
        except ValueError as error:
            self.status.setText(f"未修改：{error}")
            return False
        self._set_code(replacement)
        self._code_changed()
        self.instruction_table.setCurrentCell(min(selected, len(normalized) - 1), 0)
        return True

    def copy_instruction(self, row: int | None = None) -> None:
        rows, complete = self._draft_instructions()
        if row is None:
            row = self.instruction_table.currentRow()
        if complete and 0 <= row < len(rows) and rows[row].raw != b"\xFF":
            type(self)._command_clipboard = (rows[row].raw,)
            self.status.setText("已复制 1 条武器动画指令。")

    def copy_all_instructions(self) -> None:
        rows, complete = self._draft_instructions()
        if complete:
            type(self)._command_clipboard = tuple(
                instruction.raw for instruction in rows if instruction.raw != b"\xFF"
            )
            self.status.setText(f"已复制 {len(self._command_clipboard)} 条武器动画指令。")

    def cut_instruction(self, row: int | None = None) -> None:
        if row is None:
            row = self.instruction_table.currentRow()
        self.copy_instruction(row)
        self.delete_instruction(row)

    def paste_instructions(self, row: int | None = None, replace_all: bool = False) -> None:
        if not self._command_clipboard:
            return
        rows, complete = self._draft_instructions()
        if not complete:
            return
        if replace_all:
            self._replace_commands(list(self._command_clipboard), 0)
            return
        commands = [instruction.raw for instruction in rows]
        end = max(0, len(commands) - 1)
        target = self.instruction_table.currentRow() if row is None else row
        target = min(max(0, target), end)
        commands[target:target] = self._command_clipboard
        self._replace_commands(commands, target)

    def delete_instruction(self, row: int | None = None) -> None:
        rows, complete = self._draft_instructions()
        if row is None or isinstance(row, bool):
            row = self.instruction_table.currentRow()
        if not complete or not 0 <= row < len(rows) or rows[row].raw == b"\xFF":
            return
        commands = [instruction.raw for instruction in rows]
        del commands[row]
        self._replace_commands(commands, max(0, row - 1))

    def clear_instructions(self, *_args) -> None:
        if self.record is not None and not self.legacy_pointer_dialog:
            self._replace_commands([b"\xFF"], 0)

    def _code_changed(self) -> None:
        if self.record is not None:
            self._refresh_instruction_table()
        self.changed.emit()

    def has_pending_changes(self) -> bool:
        if self.record is None:
            return False
        try:
            return bytes.fromhex(self.code_edit.toPlainText()) != self.record.raw
        except ValueError:
            return True

    def pending_patch(self):
        if self.record is None or self.codec is None:
            return None
        try:
            replacement = bytes.fromhex(self.code_edit.toPlainText())
        except ValueError as error:
            raise ValueError("动画代码须为完整的两位十六进制字节。") from error
        if self.legacy_pointer_dialog:
            return self.codec.script_patch(self.record, replacement)
        return self.codec.script_sequence_patch(self.record, replacement)

    def _select_instruction(self, row: int, *_args) -> None:
        while self.parameter_layout.count():
            item = self.parameter_layout.takeAt(0)
            if item.widget() is not None:
                item.widget().deleteLater()
        rows, complete = self._draft_instructions()
        if self.record is None or not complete or not 0 <= row < len(rows):
            return
        instruction = rows[row]
        if not instruction.editable:
            self.parameter_layout.addWidget(QLabel("此条指令的控制字节及引用保持原值。"))
        for local, low, high in instruction.editable:
            byte_index = instruction.offset - self.record.offset + local
            self.parameter_layout.addWidget(QLabel(f"参数 +{local}"))
            spin = QSpinBox()
            spin.setRange(low, high)
            spin.setDisplayIntegerBase(16)
            spin.setPrefix("$")
            try:
                draft = bytes.fromhex(self.code_edit.toPlainText())
                value = draft[byte_index]
            except (ValueError, IndexError):
                value = instruction.raw[local]
            spin.setValue(value)
            spin.setToolTip(f"十六进制；原值 {instruction.raw[local]}（十进制）")
            spin.valueChanged.connect(lambda value, index=byte_index: self._edit_byte(index, value))
            self.parameter_layout.addWidget(spin)
        self.parameter_layout.addStretch()

    def _edit_byte(self, index: int, value: int) -> None:
        if self.record is None:
            return
        try:
            replacement = bytearray(bytes.fromhex(self.code_edit.toPlainText()))
            if not 0 <= index < len(replacement):
                raise ValueError("当前参数位置已不在动画草稿内。")
            replacement[index] = value
            if self.codec is not None and not self.legacy_pointer_dialog:
                self.codec.script_sequence_patch(self.record, bytes(replacement))
            self._set_code(replacement)
            self._code_changed()
        except ValueError as error:
            self.status.setText(str(error))


class WeaponAnimationWidget(QTabWidget):
    changed = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.project = None
        self.weapon_id: int | None = None
        self.editors = (AnimationScriptWidget(), AnimationScriptWidget())
        for title, editor in zip(("我方武器动画", "敌方武器动画"), self.editors):
            self.addTab(editor, title)
            editor.changed.connect(self.changed)
        self.setMinimumHeight(350)

    def set_record(self, project, weapon_id: int | None) -> None:
        self.project, self.weapon_id = project, weapon_id
        if project is None or weapon_id is None:
            self.setEnabled(False)
            return
        self.setEnabled(True)
        for kind, editor in zip(("ally", "enemy"), self.editors):
            editor.set_record(project.working, kind, weapon_id)

    def has_pending_changes(self) -> bool:
        return any(editor.has_pending_changes() for editor in self.editors)

    def pending_patches(self):
        return tuple(editor.pending_patch() for editor in self.editors if editor.has_pending_changes())

    def apply_pending(self) -> None:
        if self.project is not None:
            apply_animation_patches(self.project, self.pending_patches(), "武器双方动画参数")
            self.set_record(self.project, self.weapon_id)

    def discard_pending(self) -> None:
        self.set_record(self.project, self.weapon_id)


class MapAnimationEditorDialog(QDialog):
    def __init__(self, parent: QWidget | None = None, project=None) -> None:
        super().__init__(parent)
        self.project = project
        self.setWindowTitle("地图动画")
        self.resize(900, 680)
        self.setMinimumSize(820, 600)
        self._selected = -1
        self._movement_index = -1
        self._background_index = -1
        self._sprite_index = -1
        self._loading = False
        self.base = bytes(project.working) if project is not None else b""
        self.draft = bytearray(self.base)
        root = QVBoxLayout(self)
        self.read_only_status = QLabel()
        self.read_only_status.setWordWrap(True)
        self.tabs = QTabWidget()
        root.addWidget(self.tabs, 1)
        root.addWidget(self.read_only_status)
        buttons = QHBoxLayout()
        buttons.addStretch()
        self.accept_button = QPushButton("确定")
        self.accept_button.clicked.connect(self.accept)
        self.cancel_button = QPushButton("取消")
        self.cancel_button.clicked.connect(self.reject)
        buttons.addWidget(self.accept_button)
        buttons.addWidget(self.cancel_button)
        root.addLayout(buttons)
        try:
            self.codec = AnimationCodec(self.draft)
        except ValueError as error:
            self.read_only_status.setText(str(error))
            self.accept_button.setEnabled(False)
            return
        map_defaults = animation_names("地图动画名称.ini", self.codec.count("map"), 1)
        self.default_names: dict[str, tuple[str, ...]] = {"map": map_defaults}
        self.name_overrides = dict(
            getattr(project, "animation_label_overrides", {})
        )
        self.names = list(map_defaults)
        for index in range(len(self.names)):
            self.names[index] = self.name_overrides.get(("map", index), self.names[index])
        self.tabs.addTab(self._animation_tab(), "地图动画")
        self.tabs.addTab(self._rules_tab(), "规律")
        self.tabs.addTab(self._calls_tab(), "动画调用")
        self.read_only_status.setText("已载入当前 ROM 的动画、背景规律、运行规律、组图及调用。修改先留在窗口草稿，确定后一次写入；取消放弃。")
        self.animation_list.setCurrentRow(1)

    def _animation_tab(self) -> QWidget:
        page = QWidget()
        layout = QHBoxLayout(page)
        group = QGroupBox("动画选择")
        left = QVBoxLayout(group)
        self.animation_list = QListWidget()
        self.animation_list.addItems(f"[{i:02X}]{i:03d}：{name}" for i, name in enumerate(self.names))
        self.animation_list.currentRowChanged.connect(self._select_animation)
        left.addWidget(self.animation_list, 1)
        self.add_button = QPushButton("添加")
        self.add_button.setToolTip(
            "复制当前动画到下一个预留槽；内部循环指针会同步重定位。"
        )
        self.add_button.clicked.connect(self._add_animation)
        left.addWidget(self.add_button)
        left.addWidget(QLabel("动画名称（配置标签）"))
        self.animation_name = QLineEdit()
        self.animation_name.setMaxLength(80)
        self.animation_name.textEdited.connect(self._change_animation_name)
        left.addWidget(self.animation_name)
        group.setMaximumWidth(320)
        layout.addWidget(group, 1)
        self.script_editor = AnimationScriptWidget(legacy_pointer_dialog=True)
        self.script_editor.pointer_requested.connect(self._jump_to_animation_pointer)
        self.instruction_table = self.script_editor.instruction_table
        self.code_button = self.script_editor.code_button
        layout.addWidget(self.script_editor, 3)
        return page

    def _jump_to_animation_pointer(self, pointer: int) -> None:
        matches = [
            index
            for index, value in enumerate(self.codec.pointers["map"])
            if value == pointer
        ]
        if not matches:
            self.script_editor.status.setText(
                f"指针 ${pointer:04X} 不属于当前地图动画表；未修改 ROM。"
            )
            return
        target = matches[0]
        self.animation_list.setCurrentRow(target)
        if self.animation_list.currentRow() != target:
            return
        self.script_editor.code_edit.show()
        aliases = "、".join(f"${index:02X}" for index in matches)
        self.script_editor.status.setText(
            f"已定位指针 ${pointer:04X}（动画 {aliases}）；"
            "等长代码区已展开，只允许修改已验证参数。"
        )
        self.script_editor.code_edit.setFocus()

    def _flush_script(self) -> bool:
        try:
            if self.script_editor.has_pending_changes():
                offset, before, after = self.script_editor.pending_patch()
                if self.draft[offset:offset + len(before)] != before:
                    raise ValueError("当前草稿已变化，请重新选择动画。")
                self.draft[offset:offset + len(after)] = after
            return True
        except ValueError as error:
            self.read_only_status.setText(f"动画草稿未保存：{error}")
            return False

    def _select_animation(self, row: int) -> None:
        if row < 0:
            return
        if self._selected >= 0 and not self._flush_script():
            blocked = self.animation_list.blockSignals(True)
            self.animation_list.setCurrentRow(self._selected)
            self.animation_list.blockSignals(blocked)
            return
        self._selected = row
        self.animation_name.setText(self.names[row])
        self.script_editor.set_record(self.draft, "map", row)

    def _change_animation_name(self, text: str) -> None:
        row = self.animation_list.currentRow()
        if row < 0:
            return
        self.names[row] = text
        if text == self.default_names["map"][row]:
            self.name_overrides.pop(("map", row), None)
        else:
            self.name_overrides[("map", row)] = text
        self.animation_list.item(row).setText(f"[{row:02X}]{row:03d}：{text}")
        if hasattr(self, "call_combos"):
            for combo in self.call_combos.values():
                combo.setItemText(row, f"[{row:02X}]{row:03d}：{text}")

    def _add_animation(self) -> None:
        source_index = self.animation_list.currentRow()
        if source_index < 0 or not self._flush_script():
            return
        try:
            codec = AnimationCodec(self.draft)
            new_index, patches = codec.clone_map_animation_patches(source_index)
            for offset, before, after in patches:
                if bytes(self.draft[offset:offset + len(before)]) != before:
                    raise ValueError("动画草稿已变化，请重新打开窗口。")
                self.draft[offset:offset + len(after)] = after
            base_name = self.names[source_index]
            new_name = f"{base_name} 副本"
            if len(new_name) > 80:
                new_name = f"动画 {new_index:03d} 副本"
            self.names[new_index] = new_name
            self.name_overrides[("map", new_index)] = new_name
            self.animation_list.item(new_index).setText(
                f"[{new_index:02X}]{new_index:03d}：{new_name}"
            )
            if hasattr(self, "call_combos"):
                for combo in self.call_combos.values():
                    combo.setItemText(
                        new_index,
                        f"[{new_index:02X}]{new_index:03d}：{new_name}",
                    )
            self.animation_list.setCurrentRow(new_index)
            self.read_only_status.setText(
                f"已把动画 ${source_index:02X} 复制到预留槽 ${new_index:02X}；"
                "点击确定后写入工程。"
            )
        except ValueError as error:
            self.read_only_status.setText(f"未添加动画：{error}")

    def _rules_tab(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        self.rule_category_tabs = QTabWidget()
        self.rule_category_tabs.setObjectName("legacyAnimationRuleTabs")
        layout.addWidget(self.rule_category_tabs, 1)
        self.rule_lists: dict[str, QListWidget] = {}
        self.rule_codes: dict[str, QPlainTextEdit] = {}
        self.rule_statuses: dict[str, QLabel] = {}
        self.rule_names: dict[str, list[str]] = {}
        self.rule_name_edits: dict[str, QLineEdit] = {}
        self.rule_add_buttons: dict[str, QPushButton] = {}
        self._movement_roles = self.codec.movement_roles()
        for kind, title, filename, first in (
            ("background", "背景规律", "背景规律名称.ini", 0),
            ("movement", "运行规律", "地图动画运行规律名称.ini", 1),
            ("sprite", "组图规律", "地图动画图片名称.ini", 0),
        ):
            group = QGroupBox(title)
            box = QVBoxLayout(group)
            listing = QListWidget()
            defaults = animation_names(filename, self.codec.count(kind), first)
            self.default_names[kind] = defaults
            names = [
                self.name_overrides.get((kind, index), default)
                for index, default in enumerate(defaults)
            ]
            self.rule_names[kind] = names
            listing.addItems(f"[{i:02X}]{i:03d}：{name}" for i, name in enumerate(names))
            self.rule_lists[kind] = listing
            listing.currentRowChanged.connect(lambda row, key=kind: self._select_rule(key, row))
            box.addWidget(listing, 3)
            if kind in ("movement", "sprite"):
                add_button = QPushButton("添加")
                self.rule_add_buttons[kind] = add_button
                if kind == "sprite":
                    add_button.setToolTip(
                        "复制当前完整组图到 $EB—$F6 可调用预留槽；使用尾部 88 字节安全池。"
                    )
                    add_button.clicked.connect(
                        lambda _checked=False: self._add_sprite_rule()
                    )
                else:
                    add_button.setToolTip(
                        "复制当前规律到 $7D—$9C，并同时改绑当前地图动画中唯一一处同角色引用。"
                    )
                    add_button.clicked.connect(
                        lambda _checked=False: self._add_movement_rule()
                    )
                box.addWidget(add_button)
            name_edit = QLineEdit()
            name_edit.setMaxLength(80)
            name_edit.textEdited.connect(
                lambda text, key=kind: self._change_rule_name(key, text)
            )
            self.rule_name_edits[kind] = name_edit
            box.addWidget(QLabel("规律名称"))
            box.addWidget(name_edit)
            status = QLabel()
            status.setWordWrap(True)
            self.rule_statuses[kind] = status
            box.addWidget(status)
            code = QPlainTextEdit()
            code.setReadOnly(True)
            self.rule_codes[kind] = code
            box.addWidget(code, 2)
            if kind == "sprite":
                code.setReadOnly(False)
                apply = QPushButton("应用首图块")
                apply.setToolTip(
                    "仅首图块字节已有参考版保存/全新进程重开黄金；X/Y 与后续拼图指令保持只读。"
                )
                apply.clicked.connect(self._apply_sprite_code)
                box.addWidget(apply)
                preview_library = QComboBox()
                bank_count = self.project.chr_tile_count // 64
                for bank in range(max(0, bank_count - 3)):
                    preview_library.addItem(
                        f"[{bank:02X}]{bank:03d}：{0x80010 + bank * 0x400:05X}",
                        bank,
                    )
                preview_library.setCurrentIndex(
                    max(0, preview_library.findData(8))
                )
                preview_library.setToolTip(
                    "只选择物理拼图使用的 4 KiB CHR 预览窗口，不写入 ROM。"
                )
                self.sprite_preview_library = preview_library
                preview_row = QFormLayout()
                preview_row.addRow("预览图库", preview_library)
                box.addLayout(preview_row)
                self.animation_puzzle_button = QPushButton("动画拼图")
                self.animation_puzzle_button.clicked.connect(self._open_sprite_puzzle)
                box.addWidget(self.animation_puzzle_button)
                form = QFormLayout()
                self.sprite_y, self.sprite_x = QSpinBox(), QSpinBox()
                for spin in (self.sprite_y, self.sprite_x):
                    spin.setRange(-128, 127)
                    spin.setReadOnly(True)
                    spin.setButtonSymbols(QSpinBox.ButtonSymbols.NoButtons)
                    spin.setToolTip(
                        "参考版现场采集证明：界面值会变化，但确定/保存不写 ROM，故保持只读。"
                    )
                form.addRow("起始 X", self.sprite_x)
                form.addRow("起始 Y", self.sprite_y)
                box.addLayout(form)
                box.addWidget(QLabel("X/Y 仅展示；可编辑代码仅限黄金验证的首图块字节。"))
            elif kind == "movement":
                apply = QPushButton("应用等长代码")
                apply.clicked.connect(self._apply_movement_code)
                box.addWidget(apply)
                notice = QLabel("根据实际调用区分组图帧和坐标位移。可改帧、位移、音效和循环次数；跳转、长度与控制码保持原值。")
                notice.setWordWrap(True)
                box.addWidget(notice)
            else:
                apply = QPushButton("应用等长代码")
                apply.clicked.connect(self._apply_background_code)
                box.addWidget(apply)
                notice = QLabel(
                    "仅完整到达唯一结束码的背景记录可改已验证绘制参数；控制码、资源引用、变长/运行时参数、FE 布局头和 FF 结束码保持原值。"
                )
                notice.setWordWrap(True)
                box.addWidget(notice)
            # The reference editor shows one rule family at a time.  Keeping
            # all three full editors side by side makes every field narrow and
            # is especially unusable at Windows display scaling above 100%.
            host = QWidget()
            host_layout = QHBoxLayout(host)
            host_layout.setContentsMargins(6, 6, 6, 6)
            host_layout.addStretch(1)
            group.setMaximumWidth(520)
            host_layout.addWidget(group, 0)
            host_layout.addStretch(1)
            self.rule_category_tabs.addTab(host, title)
        for kind, listing in self.rule_lists.items():
            listing.setCurrentRow(1 if kind == "movement" else 0)
        return page

    def _change_rule_name(self, kind: str, text: str) -> None:
        row = self.rule_lists[kind].currentRow()
        if row < 0:
            return
        self.rule_names[kind][row] = text
        if text == self.default_names[kind][row]:
            self.name_overrides.pop((kind, row), None)
        else:
            self.name_overrides[(kind, row)] = text
        self.rule_lists[kind].item(row).setText(
            f"[{row:02X}]{row:03d}：{text}"
        )

    def _add_sprite_rule(self) -> None:
        source_index = self.rule_lists["sprite"].currentRow()
        if source_index < 0:
            return
        try:
            codec = AnimationCodec(self.draft)
            new_index, patches = codec.clone_sprite_rule_patches(source_index)
            for offset, before, after in patches:
                if bytes(self.draft[offset:offset + len(before)]) != before:
                    raise ValueError("组图草稿已变化，请重新打开窗口。")
                self.draft[offset:offset + len(after)] = after
            base_name = self.rule_names["sprite"][source_index]
            new_name = f"{base_name} 副本"
            if len(new_name) > 80:
                new_name = f"组图 {new_index:03d} 副本"
            self.rule_names["sprite"][new_index] = new_name
            self.name_overrides[("sprite", new_index)] = new_name
            self.rule_lists["sprite"].item(new_index).setText(
                f"[{new_index:02X}]{new_index:03d}：{new_name}"
            )
            self.rule_lists["sprite"].setCurrentRow(new_index)
            self.read_only_status.setText(
                f"已把组图 ${source_index:02X} 复制到预留槽 ${new_index:02X}；"
                "点击确定后写入工程。"
            )
        except ValueError as error:
            self.read_only_status.setText(f"未添加组图：{error}")

    def _add_movement_rule(self) -> None:
        source_index = self.rule_lists["movement"].currentRow()
        map_index = self.animation_list.currentRow()
        if source_index < 0 or map_index < 0 or not self._flush_script():
            return
        try:
            codec = AnimationCodec(self.draft)
            new_index, role, patches = codec.clone_movement_rule_patches(
                source_index,
                map_index,
            )
            for offset, before, after in patches:
                if bytes(self.draft[offset:offset + len(before)]) != before:
                    raise ValueError("运行规律草稿已变化，请重新打开窗口。")
                self.draft[offset:offset + len(after)] = after
            self._movement_roles = AnimationCodec(self.draft).movement_roles()
            base_name = self.rule_names["movement"][source_index]
            new_name = f"{base_name} 副本"
            if len(new_name) > 80:
                new_name = f"运行规律 {new_index:03d} 副本"
            self.rule_names["movement"][new_index] = new_name
            self.name_overrides[("movement", new_index)] = new_name
            self.rule_lists["movement"].item(new_index).setText(
                f"[{new_index:02X}]{new_index:03d}：{new_name}"
            )
            # Refresh the visible map record so returning to the first tab does
            # not retain the pre-bind operand in its local editor snapshot.
            self.script_editor.set_record(self.draft, "map", map_index)
            self.rule_lists["movement"].setCurrentRow(new_index)
            role_text = "组图帧序列" if role == "frames" else "坐标位移"
            self.read_only_status.setText(
                f"已把{role_text} ${source_index:02X} 复制到 ${new_index:02X}，"
                f"并改绑地图动画 ${map_index:02X} 的唯一引用；点击确定后写入工程。"
            )
        except ValueError as error:
            self.read_only_status.setText(f"未添加运行规律：{error}")

    def _select_rule(self, kind: str, row: int) -> None:
        if row < 0:
            return
        if (
            kind == "background"
            and self._background_index >= 0
            and not self._apply_background_code(self._background_index)
        ):
            listing = self.rule_lists[kind]
            blocked = listing.blockSignals(True)
            listing.setCurrentRow(self._background_index)
            listing.blockSignals(blocked)
            return
        if kind == "movement" and self._movement_index >= 0 and not self._apply_movement_code(self._movement_index):
            listing = self.rule_lists[kind]
            blocked = listing.blockSignals(True)
            listing.setCurrentRow(self._movement_index)
            listing.blockSignals(blocked)
            return
        if kind == "sprite" and self._sprite_index >= 0 and not self._apply_sprite_code(self._sprite_index):
            listing = self.rule_lists[kind]
            blocked = listing.blockSignals(True)
            listing.setCurrentRow(self._sprite_index)
            listing.blockSignals(blocked)
            return
        record = AnimationCodec(self.draft).record(kind, row)
        self.rule_name_edits[kind].setText(self.rule_names[kind][row])
        self.rule_codes[kind].setPlainText(record.raw.hex(" ").upper())
        self.rule_statuses[kind].setText(f"当前 ROM · ${record.offset:06X} · {len(record.raw)} 字节"
                                         + (f" · 与 {len(record.aliases)} 项共享" if record.aliases else ""))
        if kind == "background":
            self._background_index = row
            editable, explanation = AnimationCodec(self.draft).background_edit_status(row)
            self.rule_codes[kind].setReadOnly(not editable)
            self.rule_statuses[kind].setText(
                self.rule_statuses[kind].text()
                + f" · {explanation}"
            )
        if kind == "movement":
            self._movement_index = row
            roles = self._movement_roles.get(row, set())
            self.rule_codes[kind].setReadOnly(len(roles) != 1)
            self.rule_statuses[kind].setText(self.rule_statuses[kind].text() + " · " +
                                            ({"frames": "组图帧序列", "axis": "坐标位移"}.get(next(iter(roles)), "")
                                             if len(roles) == 1 else "运行方式未唯一确认，只读"))
        if kind == "sprite":
            self._sprite_index = row
            self.rule_codes[kind].setPlainText(record.raw[2:].hex(" ").upper())
            self.rule_statuses[kind].setText(
                self.rule_statuses[kind].text()
                + " · X/Y 参考版不持久化，只读；首图块已有动态黄金"
            )
            self._loading = True
            self.sprite_x.setValue(int.from_bytes(record.raw[:1], signed=True))
            self.sprite_y.setValue(int.from_bytes(record.raw[1:2], signed=True))
            self._loading = False

    def _open_sprite_puzzle(self) -> None:
        row = self.rule_lists["sprite"].currentRow()
        if row < 0:
            return
        codec = AnimationCodec(self.draft)
        record = codec.record("sprite", row)
        SpritePuzzlePreviewDialog(
            record,
            self.project,
            codec,
            self,
            initial_library=int(self.sprite_preview_library.currentData() or 0),
        ).exec()

    def _apply_movement_code(self, row: int | None = None) -> bool:
        try:
            codec = AnimationCodec(self.draft)
            if row is None or isinstance(row, bool):
                row = self.rule_lists["movement"].currentRow()
            record = codec.record("movement", row)
            changed = bytes.fromhex(self.rule_codes["movement"].toPlainText())
            if changed == record.raw:
                return True
            offset, _before, after = codec.rule_patch(record, changed)
            self.draft[offset:offset + len(after)] = after
            self.read_only_status.setText("运行规律已应用到窗口草稿，点击确定后写入工程。")
            return True
        except ValueError as error:
            self.read_only_status.setText(f"运行规律未应用：{error}")
            return False

    def _apply_background_code(self, row: int | None = None) -> bool:
        try:
            codec = AnimationCodec(self.draft)
            if row is None or isinstance(row, bool):
                row = self.rule_lists["background"].currentRow()
            record = codec.record("background", row)
            changed = bytes.fromhex(self.rule_codes["background"].toPlainText())
            if changed == record.raw:
                return True
            offset, _before, after = codec.rule_patch(record, changed)
            self.draft[offset:offset + len(after)] = after
            self.read_only_status.setText(
                "背景规律已验证绘制参数已应用到窗口草稿，点击确定后写入工程。"
            )
            return True
        except ValueError as error:
            self.read_only_status.setText(f"背景规律未应用：{error}")
            return False

    def _apply_sprite_code(self, row: int | None = None) -> bool:
        try:
            codec = AnimationCodec(self.draft)
            if row is None or isinstance(row, bool):
                row = self.rule_lists["sprite"].currentRow()
            record = codec.record("sprite", row)
            changed = record.raw[:2] + bytes.fromhex(
                self.rule_codes["sprite"].toPlainText()
            )
            if changed == record.raw:
                return True
            offset, _before, after = codec.rule_patch(record, changed)
            self.draft[offset:offset + len(after)] = after
            self.read_only_status.setText(
                "组图首图块已应用到窗口草稿，点击确定后写入工程。"
            )
            return True
        except ValueError as error:
            self.read_only_status.setText(f"组图规律未应用：{error}")
            return False
            return False

    def _calls_tab(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        hint = QLabel("从当前事件脚本识别 38 02 动画调用；显示真实文件地址。未证明精神名称关联的调用不猜测名称。")
        hint.setWordWrap(True)
        layout.addWidget(hint)
        self.call_table = QTableWidget(0, 4)
        self.call_table.setHorizontalHeaderLabels(("调用位置", "当前动画", "状态/原因", "动画指令"))
        self.call_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        self.call_table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
        self.call_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.call_table.setAlternatingRowColors(True)
        self.call_combos: dict[int, QComboBox] = {}
        calls = self.codec.calls()
        self.call_table.setRowCount(len(calls))
        for row, (offset, index) in enumerate(calls):
            self.call_table.setItem(row, 0, QTableWidgetItem(f"${offset:06X}"))
            combo = QComboBox()
            for i, name in enumerate(self.names):
                combo.addItem(f"[{i:02X}]{i:03d}：{name}", i)
            combo.setCurrentIndex(index)
            editable, explanation = self.codec.call_status(offset)
            if not editable:
                combo.setEnabled(False)
                combo.setToolTip(explanation)
            else:
                combo.setToolTip(explanation)
            combo.currentIndexChanged.connect(lambda selected, address=offset: self._change_call(address, selected))
            self.call_table.setCellWidget(row, 1, combo)
            self.call_combos[offset] = combo
            status_item = QTableWidgetItem(explanation)
            status_item.setToolTip(explanation)
            self.call_table.setItem(row, 2, status_item)
            jump = QPushButton("查看动画")
            jump.clicked.connect(lambda checked=False, box=combo: self._show_call_animation(box.currentIndex()))
            self.call_table.setCellWidget(row, 3, jump)
        layout.addWidget(self.call_table, 1)
        return page

    def _change_call(self, offset: int, index: int) -> None:
        try:
            # The two address/ID-documented sites are verified against the
            # original ROM value.  After a first draft change, checking that
            # documentation against the draft would incorrectly lock the
            # selector and prevent a second edit or a return to the original.
            if not self.codec.call_is_editable(offset):
                raise ValueError("此处只识别到调用字节，事件上下文尚未验证，暂不改写。")
            codec = AnimationCodec(self.draft)
            if self.draft[offset:offset + 2] != b"\x38\x02":
                raise ValueError("动画调用指令已变化，不能继续编辑。")
            if not 0 <= index < codec.count("map"):
                raise ValueError("动画编号超出指针表。")
            if not codec.record("map", index).complete:
                raise ValueError("目标动画包含未验证指令，不能作为新的调用目标。")
            self.draft[offset + 2] = index
        except ValueError as error:
            self.read_only_status.setText(str(error))
            combo = self.call_combos[offset]
            blocked = combo.blockSignals(True)
            combo.setCurrentIndex(self.draft[offset + 2])
            combo.blockSignals(blocked)

    def _show_call_animation(self, index: int) -> None:
        self.animation_list.setCurrentRow(index)
        self.tabs.setCurrentIndex(0)

    def accept(self) -> None:
        if (self.project is None or not hasattr(self, "script_editor") or not self._flush_script()
                or not self._apply_movement_code() or not self._apply_background_code()
                or not self._apply_sprite_code()):
            return
        try:
            # Small changed runs retain optimistic conflict checks without
            # treating unrelated database edits as an animation conflict.
            patches = []
            cursor = 0
            while cursor < len(self.base):
                if self.base[cursor] == self.draft[cursor]:
                    cursor += 1
                    continue
                start = cursor
                while cursor < len(self.base) and self.base[cursor] != self.draft[cursor]:
                    cursor += 1
                patches.append((start, self.base[start:cursor], bytes(self.draft[start:cursor])))
            with self.project.transaction("地图动画、规律、调用与名称"):
                apply_animation_patches(
                    self.project,
                    tuple(patches),
                    "地图动画、规律与调用",
                )
                self.project.replace_animation_label_overrides(self.name_overrides)
        except ValueError as error:
            self.read_only_status.setText(f"未写入：{error}")
            return
        super().accept()
