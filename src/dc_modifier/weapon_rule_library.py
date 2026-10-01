from __future__ import annotations

from dataclasses import dataclass

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtGui import QColor, QMouseEvent, QPainter, QPen
from PySide6.QtWidgets import (
    QApplication,
    QAbstractSpinBox,
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QSpinBox,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from fc_editor.codecs.animation import AnimationRecord

from .animation_editor import SpritePuzzlePreviewDialog, animation_names


@dataclass(frozen=True)
class WeaponRuleTable:
    key: str
    title: str
    filename: str
    pointer_table: int
    count: int
    file_base: int
    cpu_base: int
    hidden_prefix: int
    first_pointer: int
    directory_offset: int


WEAPON_RULE_TABLES = (
    WeaponRuleTable(
        "weapon_beam", "光束组图规律", "光束规律名称.ini",
        0x11117, 0xFF, 0x10010, 0x8000, 3, 0x9307, 0x10018,
    ),
    WeaponRuleTable(
        "weapon_movement_1", "物理运行规律1", "运行规律名称.ini",
        0x120B9, 0xFC, 0x10010, 0x8000, 0, 0xA2A3, 0x1001A,
    ),
    WeaponRuleTable(
        "weapon_movement_2", "物理运行规律2", "运行规律名称2.ini",
        0x12A8A, 0xFA, 0x10010, 0x8000, 0, 0xAC70, 0x1001C,
    ),
    WeaponRuleTable(
        "weapon_picture", "物理图片规律", "物理图片名称.ini",
        0x10030, 0xFF, 0x10010, 0x8000, 2, 0x8220, 0x10014,
    ),
)

WEAPON_RULE_SHARED_END = 0x13010
WEAPON_RULE_TABLE_BY_KEY = {table.key: table for table in WEAPON_RULE_TABLES}
WEAPON_RULE_STORAGE_ORDER = tuple(
    WEAPON_RULE_TABLE_BY_KEY[key]
    for key in (
        "weapon_picture",
        "weapon_beam",
        "weapon_movement_1",
        "weapon_movement_2",
    )
)


def _signed(value: int) -> int:
    return value - 0x100 if value & 0x80 else value


@dataclass(frozen=True)
class BeamRuleParts:
    initial: tuple[int, int] | None
    body: bytes
    next_offset: tuple[int, int] | None


def split_beam_rule(raw: bytes) -> BeamRuleParts:
    """Split the controls hidden by the reference beam-rule page.

    The old page shows an optional leading ``FE Y X`` in the “设置初始坐标”
    group and an optional terminal ``F3 DY DX`` in “设置下一张图片坐标”.
    Only the drawing body plus ``FF`` remains in its code box.
    """

    if not raw or raw[-1] != 0xFF:
        raise ValueError("光束规律缺少 $FF 结束码。")
    cursor = 0
    initial: tuple[int, int] | None = None
    if len(raw) >= 4 and raw[0] == 0xFE:
        initial = (raw[2], raw[1])
        cursor = 3
    end = len(raw) - 1
    next_offset: tuple[int, int] | None = None
    if end - cursor >= 3 and raw[end - 3] == 0xF3:
        next_offset = (_signed(raw[end - 1]), _signed(raw[end - 2]))
        end -= 3
    body = raw[cursor:end] + b"\xFF"
    if not body:
        body = b"\xFF"
    return BeamRuleParts(initial, body, next_offset)


def join_beam_rule(parts: BeamRuleParts) -> bytes:
    if not parts.body or parts.body[-1] != 0xFF:
        raise ValueError("光束规律正文必须以 $FF 结束。")
    result = bytearray()
    if parts.initial is not None:
        x, y = parts.initial
        if not 0 <= x <= 0xFF or not 0 <= y <= 0xFF:
            raise ValueError("光束初始坐标必须在 0—255 之间。")
        result.extend((0xFE, y, x))
    result.extend(parts.body[:-1])
    if parts.next_offset is not None:
        dx, dy = parts.next_offset
        if not -128 <= dx <= 127 or not -128 <= dy <= 127:
            raise ValueError("下一张图片坐标差必须在 -128—127 之间。")
        result.extend((0xF3, dy & 0xFF, dx & 0xFF))
    result.append(0xFF)
    return bytes(result)


def decode_axis_preview(raw: bytes, *, limit: int = 960) -> tuple[int, ...]:
    """Expand the legacy axis-rule subset used by the movement simulator.

    Literal bytes are coordinate samples and ``83 count relative`` is the
    verified counted-loop form.  Other control families stop the offline
    preview instead of guessing their runtime state.
    """

    pc = 0
    values: list[int] = []
    counters: dict[int, int] = {}
    budget = max(1024, limit * 16)
    while 0 <= pc < len(raw) and len(values) < limit and budget:
        budget -= 1
        opcode = raw[pc]
        if opcode < 0x80 or opcode > 0x86:
            values.append(_signed(opcode))
            pc += 1
            continue
        if opcode == 0x83:
            if pc + 2 >= len(raw):
                break
            count = raw[pc + 1]
            if count >= 0xFC:
                break
            remaining = counters.setdefault(pc, count)
            remaining -= 1
            if remaining > 0:
                counters[pc] = remaining
                pc = pc + 3 + _signed(raw[pc + 2])
            else:
                counters.pop(pc, None)
                pc += 3
            continue
        # $85 is a two-byte side effect and does not itself emit a coordinate.
        if opcode == 0x85 and pc + 1 < len(raw):
            pc += 2
            continue
        # $84 has two operands.  The remaining control instructions depend on
        # runtime state or terminate the axis stream, so fail closed here.
        if opcode == 0x84 and pc + 2 < len(raw):
            pc += 3
            continue
        break
    return tuple(values)


def increment_weapon_rule_tiles(raw: bytes, amount: int) -> bytes:
    """Apply the legacy ``图块编号增加`` operation to one movement rule."""

    sizes = {
        0xF7: 2,
        0xF8: 1,
        0xF9: 2,
        0xFA: 2,
        0xFB: 3,
        0xFC: 3,
        0xFD: 2,
        0xFE: 2,
        0xFF: 1,
    }
    result = bytearray(raw)
    cursor = 0
    changed = False
    while cursor < len(result):
        opcode = result[cursor]
        size = sizes.get(opcode, 1)
        if cursor + size > len(result):
            raise ValueError("运行规律末尾存在截断指令，不能增加图块编号。")
        if opcode < 0xF7:
            value = opcode + amount
            if not 0 <= value <= 0xF6:
                raise ValueError("增加后的图块编号超出 $00—$F6。")
            result[cursor] = value
            changed = True
        cursor += size
        if opcode == 0xFF:
            break
    if not changed:
        raise ValueError("当前运行规律没有可增加的图块编号。")
    return bytes(result)


class _MovementCanvas(QWidget):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setMinimumSize(480, 440)
        self.setMouseTracking(True)
        self.object_width = 8
        self.object_height = 8
        self.x = 0
        self.y = 0
        self.follow_mouse = False
        self.object_created = False

    def set_object(
        self, width: int, height: int, x: int, y: int, *, created: bool | None = None
    ) -> None:
        self.object_width = width
        self.object_height = height
        self.x = x
        self.y = y
        if created is not None:
            self.object_created = created
        self.update()

    def paintEvent(self, _event) -> None:  # type: ignore[override]
        painter = QPainter(self)
        painter.fillRect(self.rect(), QColor("black"))
        painter.setPen(QPen(QColor("#ff2038"), 2))
        painter.drawLine(0, self.height() // 2, self.width(), self.height() // 2)
        painter.drawLine(self.width() // 2, 0, self.width() // 2, self.height())
        if self.object_created:
            painter.setPen(QPen(QColor("#00ffff"), 1))
            # Direct text entry in the reference spinner is not constrained
            # by its 0--100 arrow range.  Keep the stored value intact, but
            # protect Qt's native int drawing API from Python integers outside
            # a signed 32-bit coordinate.
            clamp = lambda value: min(0x7FFFFFFF, max(-0x80000000, int(value)))
            painter.drawRect(
                clamp(self.width() // 2 + self.x),
                clamp(self.height() // 2 + self.y),
                clamp(max(1, self.object_width)),
                clamp(max(1, self.object_height)),
            )

    def mousePressEvent(self, event: QMouseEvent) -> None:  # type: ignore[override]
        if event.button() == Qt.MouseButton.LeftButton:
            self.parent()._canvas_clicked(  # type: ignore[attr-defined]
                int(event.position().x()) - self.width() // 2,
                int(event.position().y()) - self.height() // 2,
            )
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event: QMouseEvent) -> None:  # type: ignore[override]
        if self.follow_mouse:
            self.x = int(event.position().x()) - self.width() // 2
            self.y = int(event.position().y()) - self.height() // 2
            self.update()
            self.parent()._canvas_mouse_position(self.x, self.y)  # type: ignore[attr-defined]
        super().mouseMoveEvent(event)


class _LegacyFreeSpinBox(QAbstractSpinBox):
    """Reference spinner: free decimal text plus a 0--100 cyclic stepper.

    The legacy Easy Language control is a native edit paired with an up/down
    control.  Desktop evidence shows that the edit preserves signed values
    outside 0--100 (and even outside signed 32-bit), while the arrows retain
    their independent native 0--100 wrapping range.  QSpinBox cannot express
    both behaviours at once, so this small adapter keeps the edit free-form
    and implements only the verified arrow semantics.
    """

    valueChanged = Signal(object)

    def __init__(self, value: int = 0, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._last_value = int(value)
        self.lineEdit().setText(str(self._last_value))
        self.lineEdit().editingFinished.connect(self._commit_text)

    def minimum(self) -> int:
        return 0

    def maximum(self) -> int:
        return 100

    def value(self) -> int:
        text = self.lineEdit().text().strip()
        try:
            return int(text, 10)
        except ValueError:
            return self._last_value

    def setValue(self, value: int) -> None:
        value = int(value)
        changed = value != self.value() or self.lineEdit().text() != str(value)
        self._last_value = value
        self.lineEdit().setText(str(value))
        if changed:
            self.valueChanged.emit(value)

    def stepBy(self, steps: int) -> None:  # type: ignore[override]
        if not steps:
            return
        current = self.value()
        direction = 1 if steps > 0 else -1
        if not 0 <= current <= 100:
            current = 0 if direction > 0 else 100
            remaining = abs(steps) - 1
        else:
            remaining = abs(steps)
        if remaining:
            current = (current + direction * remaining) % 101
        self.setValue(current)

    def stepEnabled(self):  # type: ignore[override]
        flags = QAbstractSpinBox.StepEnabledFlag
        return flags.StepUpEnabled | flags.StepDownEnabled

    def _commit_text(self) -> None:
        text = self.lineEdit().text().strip()
        try:
            value = int(text, 10)
        except ValueError:
            self.lineEdit().setText(str(self._last_value))
            return
        if value != self._last_value:
            self._last_value = value
            self.valueChanged.emit(value)


class WeaponMovementSimulatorDialog(QDialog):
    """Reference-shaped, non-writing weapon movement-rule simulator."""

    def __init__(
        self,
        x_code: bytes = b"",
        y_code: bytes = b"",
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("运行规律模拟")
        self.resize(940, 570)
        self.frame = 0
        self.x_values: tuple[int, ...] = ()
        self.y_values: tuple[int, ...] = ()
        self.awaiting_object = False
        self.recording = False
        self.record_move_count = 0
        self.last_mouse_position: tuple[int, int] | None = None
        root = QHBoxLayout(self)
        root.setSpacing(10)
        self.canvas = _MovementCanvas(self)
        root.addWidget(self.canvas, 5)
        controls = QVBoxLayout()
        controls.setSpacing(7)
        parameters = QGridLayout()
        parameters.setHorizontalSpacing(6)
        parameters.setVerticalSpacing(6)
        self.width_spin = _LegacyFreeSpinBox(8)
        self.height_spin = _LegacyFreeSpinBox(8)
        for spin in (self.width_spin, self.height_spin):
            spin.setValue(8)
            spin.setMinimumWidth(62)
        parameters.addWidget(QLabel("物体高度"), 0, 0)
        parameters.addWidget(self.height_spin, 0, 1)
        parameters.addWidget(QLabel("物体宽度"), 0, 2)
        parameters.addWidget(self.width_spin, 0, 3)
        self.mouse_check = QCheckBox("鼠标模拟运动")
        parameters.addWidget(self.mouse_check, 0, 4)
        self.x_spin = _LegacyFreeSpinBox(0)
        self.y_spin = _LegacyFreeSpinBox(0)
        self.sample_spin = _LegacyFreeSpinBox(1)
        for spin in (self.x_spin, self.y_spin, self.sample_spin):
            spin.setMinimumWidth(62)
        parameters.addWidget(QLabel("X 轴"), 1, 0)
        parameters.addWidget(self.x_spin, 1, 1)
        parameters.addWidget(QLabel("Y 轴"), 1, 2)
        parameters.addWidget(self.y_spin, 1, 3)
        parameters.addWidget(QLabel("每隔几次移动记录坐标"), 2, 0, 1, 3)
        parameters.addWidget(self.sample_spin, 2, 3)
        parameters.setColumnStretch(4, 1)
        controls.addLayout(parameters)
        buttons = QHBoxLayout()
        self.move_button = QPushButton("移动")
        self.start_button = QPushButton("开始")
        self.stop_button = QPushButton("结束")
        self.preview_button = QPushButton("播放代码（增强）")
        buttons.addWidget(self.move_button)
        buttons.addWidget(self.start_button)
        buttons.addWidget(self.stop_button)
        buttons.addWidget(self.preview_button)
        buttons.addStretch()
        controls.addLayout(buttons)
        controls.addWidget(QLabel("X运行规律"))
        self.x_code = QPlainTextEdit(x_code.hex(" ").upper())
        controls.addWidget(self.x_code, 1)
        controls.addWidget(QLabel("Y运行规律"))
        self.y_code = QPlainTextEdit(y_code.hex(" ").upper())
        controls.addWidget(self.y_code, 1)
        self.status = QLabel("模拟只读取窗口内容，不写入 ROM。")
        self.status.setWordWrap(True)
        controls.addWidget(self.status)
        close = QPushButton("关闭")
        close.clicked.connect(self.reject)
        controls.addWidget(close)
        root.addLayout(controls, 4)
        self.timer = QTimer(self)
        self.timer.setInterval(16)
        self.timer.timeout.connect(self._advance)
        self.move_button.clicked.connect(self._move)
        self.start_button.clicked.connect(self._start)
        self.stop_button.clicked.connect(self._stop)
        self.preview_button.clicked.connect(self._preview)
        self.mouse_check.toggled.connect(self._mouse_toggled)
        for spin in (self.width_spin, self.height_spin, self.x_spin, self.y_spin):
            spin.valueChanged.connect(self._move)
        self._move()

    @staticmethod
    def _parse_code(editor: QPlainTextEdit) -> bytes:
        text = editor.toPlainText().replace(",", " ").strip()
        if not text:
            return b""
        tokens = text.split()
        if any(len(token) > 2 for token in tokens):
            raise ValueError("运行规律必须使用两位十六进制字节。")
        try:
            return bytes(int(token, 16) for token in tokens)
        except ValueError as error:
            raise ValueError("运行规律包含无效十六进制字节。") from error

    def _canvas_mouse_position(self, x: int, y: int) -> None:
        self.x_spin.blockSignals(True)
        self.y_spin.blockSignals(True)
        self.x_spin.setValue(x)
        self.y_spin.setValue(y)
        self.x_spin.blockSignals(False)
        self.y_spin.blockSignals(False)
        if self.recording:
            previous = self.last_mouse_position
            self.last_mouse_position = (x, y)
            if previous is not None:
                self._record_delta(x - previous[0], y - previous[1])

    def _canvas_clicked(self, x: int, y: int) -> None:
        if not self.awaiting_object:
            return
        self.awaiting_object = False
        self.canvas.set_object(
            self.width_spin.value(), self.height_spin.value(), x, y,
            created=True,
        )
        self.last_mouse_position = (x, y)
        self.status.setText("物体已创建；再次点击“开始”进入记录。")

    def _mouse_toggled(self, checked: bool) -> None:
        self.canvas.follow_mouse = checked
        if checked:
            self.last_mouse_position = (self.canvas.x, self.canvas.y)

    def _move(self, _value: int | None = None) -> None:
        if self.sender() is self.move_button:
            if not self.recording:
                self._show_information("请先点击开始")
                return
            dx = self.x_spin.value()
            dy = self.y_spin.value()
            self.canvas.set_object(
                self.width_spin.value(), self.height_spin.value(),
                self.canvas.x + dx, self.canvas.y + dy, created=True,
            )
            self.last_mouse_position = (self.canvas.x, self.canvas.y)
            self._record_delta(dx, dy)
            return
        self.canvas.set_object(
            self.width_spin.value(),
            self.height_spin.value(),
            self.canvas.x,
            self.canvas.y,
        )

    def _start(self) -> None:
        if not self.canvas.object_created:
            self.awaiting_object = True
            self._show_information("请使用鼠标左键点击屏幕创建物体")
            self.status.setText("请在黑色画布内左键创建物体。")
            return
        self.recording = True
        self.record_move_count = 0
        self.last_mouse_position = (self.canvas.x, self.canvas.y)
        self.status.setText("正在记录运动规律；完成后点击“结束”。")

    def _show_information(self, text: str) -> None:
        QMessageBox.information(self, "信息：", text)

    @staticmethod
    def _axis_byte(value: int) -> str:
        return f"{value & 0xFF:02X}"

    def _append_axis_byte(self, editor: QPlainTextEdit, value: int) -> None:
        current = editor.toPlainText().strip()
        token = self._axis_byte(value)
        editor.setPlainText(f"{current} {token}".strip())

    def _record_delta(self, dx: int, dy: int) -> None:
        self.record_move_count += 1
        # In the reference editor a zero (or negative) interval records every
        # move; it does not raise or reject the value.
        interval = max(1, self.sample_spin.value())
        if self.record_move_count % interval:
            return
        self._append_axis_byte(self.x_code, dx)
        self._append_axis_byte(self.y_code, dy)

    def _preview(self) -> None:
        try:
            self.x_values = decode_axis_preview(self._parse_code(self.x_code))
            self.y_values = decode_axis_preview(self._parse_code(self.y_code))
        except ValueError as error:
            self.status.setText(str(error))
            return
        if not self.x_values and not self.y_values:
            self.status.setText("没有可离线解释的坐标样本。")
            return
        self.frame = 0
        self.recording = False
        self.canvas.object_created = True
        self.timer.start()
        self.status.setText("正在按规律播放；运行时依赖控制码会安全停止。")

    def _advance(self) -> None:
        if self.frame >= max(len(self.x_values), len(self.y_values)):
            self._stop()
            return
        if self.x_values:
            self.x_spin.setValue(self.x_values[min(self.frame, len(self.x_values) - 1)])
        if self.y_values:
            self.y_spin.setValue(self.y_values[min(self.frame, len(self.y_values) - 1)])
        self.frame += 1

    def _stop(self) -> None:
        was_recording = self.recording
        self.recording = False
        self.awaiting_object = False
        self.canvas.follow_mouse = False
        self.mouse_check.blockSignals(True)
        self.mouse_check.setChecked(False)
        self.mouse_check.blockSignals(False)
        self.timer.stop()
        if was_recording:
            self.status.setText("记录已结束。")
        else:
            self.status.setText(f"已停止，共播放 {self.frame} 帧。")

    def reject(self) -> None:
        self.timer.stop()
        super().reject()


class WeaponRuleCatalog:
    """Read the four reference weapon-rule pointer libraries safely."""

    def __init__(self, data: bytes | bytearray) -> None:
        self.data = bytes(data)
        for table in WEAPON_RULE_TABLES:
            table_pointer = self.table_pointer(table)
            expected_first = table_pointer + (table.count + 1) * 2
            if self._pointer(table, 1) != expected_first:
                raise ValueError(f"{table.title}指针表与已验证格式不同；已停止解析。")

    def table_pointer(self, table: WeaponRuleTable) -> int:
        return int.from_bytes(
            self.data[table.directory_offset:table.directory_offset + 2],
            "little",
        )

    def table_offset(self, table: WeaponRuleTable) -> int:
        return table.file_base + self.table_pointer(table) - table.cpu_base

    def _pointer(self, table: WeaponRuleTable, rule_id: int) -> int:
        offset = self.table_offset(table) + rule_id * 2
        return int.from_bytes(self.data[offset:offset + 2], "little")

    def pointer(self, table: WeaponRuleTable, rule_id: int) -> int:
        if not 1 <= rule_id <= table.count:
            raise IndexError(rule_id)
        return self._pointer(table, rule_id)

    def record(
        self,
        table: WeaponRuleTable,
        rule_id: int,
        *,
        include_hidden: bool = False,
    ) -> tuple[int, bytes, tuple[int, ...]]:
        if not 1 <= rule_id <= table.count:
            raise IndexError(rule_id)
        pointer = self._pointer(table, rule_id)
        aliases = tuple(
            index
            for index in range(1, table.count + 1)
            if index != rule_id and self._pointer(table, index) == pointer
        )
        larger = {
            self._pointer(table, index)
            for index in range(1, table.count + 1)
            if self._pointer(table, index) > pointer
        }
        start = table.file_base + pointer - table.cpu_base
        if larger:
            end = table.file_base + min(larger) - table.cpu_base
        else:
            bank_end = WEAPON_RULE_SHARED_END
            terminator = self.data.find(b"\xFF", start, bank_end)
            end = terminator + 1 if terminator >= start else bank_end
        if not 0 <= start < end <= len(self.data):
            raise ValueError(f"{table.title} ${rule_id:02X} 指针越界。")
        raw = self.data[start:end]
        return start, raw if include_hidden else raw[table.hidden_prefix:], aliases

    def used_end(self) -> int:
        final = WEAPON_RULE_TABLE_BY_KEY["weapon_movement_2"]
        start, raw, _aliases = self.record(
            final, final.count, include_hidden=True
        )
        return start + len(raw)


def replace_weapon_rule_record(
    data: bytes | bytearray,
    table_key: str,
    rule_id: int,
    replacement: bytes,
    *,
    include_hidden: bool = False,
) -> bytes:
    """Repack one legacy weapon-rule record in the shared four-library pool.

    The reference editor stores the four libraries as a directory-linked
    chain.  Growing an earlier record shifts every later table and record,
    updates the three movable directory entries, and keeps the fixed Bank end.
    This routine mirrors that behavior without changing the ROM file size.
    """

    table = WEAPON_RULE_TABLE_BY_KEY.get(table_key)
    if table is None:
        raise ValueError(f"未知武器规律库：{table_key}")
    catalog = WeaponRuleCatalog(data)
    start, old_full, aliases = catalog.record(
        table, rule_id, include_hidden=True
    )
    new_full = bytes(replacement)
    if not include_hidden:
        new_full = old_full[:table.hidden_prefix] + new_full
    if not new_full:
        raise ValueError("规律代码不能为空。")
    used_end = catalog.used_end()
    if not aliases:
        old_end = start + len(old_full)
        delta = len(new_full) - len(old_full)
        new_used_end = used_end + delta
        if new_used_end > WEAPON_RULE_SHARED_END:
            remaining = WEAPON_RULE_SHARED_END - used_end
            raise ValueError(
                f"武器规律共享池容量不足：本次需净增 {delta} B，"
                f"当前仅剩 {remaining} B。"
            )
        if new_used_end <= start:
            raise ValueError("规律重排后的共享池边界无效。")
        output = bytearray(data)
        tail = bytes(catalog.data[old_end:used_end])
        packed = new_full + tail
        output[start:start + len(packed)] = packed
        if delta < 0:
            output[new_used_end:used_end] = b"\x00" * (-delta)

        selected_pointer = catalog.pointer(table, rule_id)
        selected_order = WEAPON_RULE_STORAGE_ORDER.index(table)
        for order, family in enumerate(WEAPON_RULE_STORAGE_ORDER):
            old_table_pointer = catalog.table_pointer(family)
            new_table_pointer = old_table_pointer + (
                delta if order > selected_order else 0
            )
            if order > selected_order:
                output[
                    family.directory_offset:family.directory_offset + 2
                ] = new_table_pointer.to_bytes(2, "little")
            new_table_offset = family.file_base + new_table_pointer - family.cpu_base
            for index in range(1, family.count + 1):
                pointer = catalog.pointer(family, index)
                if order > selected_order or (
                    order == selected_order and pointer > selected_pointer
                ):
                    pointer += delta
                pointer_offset = new_table_offset + index * 2
                output[pointer_offset:pointer_offset + 2] = pointer.to_bytes(2, "little")
        return bytes(output)

    selected_order = WEAPON_RULE_STORAGE_ORDER.index(table)
    table_start = catalog.table_offset(table)
    data_start = table_start + (table.count + 1) * 2
    if selected_order + 1 < len(WEAPON_RULE_STORAGE_ORDER):
        table_end = catalog.table_offset(
            WEAPON_RULE_STORAGE_ORDER[selected_order + 1]
        )
    else:
        table_end = used_end

    # The reference editor treats aliases as storage compression, not linked
    # logical records.  Rebuild this family by logical ID and de-duplicate
    # equal bodies, which gives an edited alias its own record while its peers
    # keep sharing the original bytes.
    records = [
        catalog.record(table, index, include_hidden=True)[1]
        for index in range(1, table.count + 1)
    ]
    records[rule_id - 1] = new_full
    packed_records = bytearray()
    relative_by_body: dict[bytes, int] = {}
    rebuilt_pointers: list[int] = []
    for raw in records:
        relative = relative_by_body.get(raw)
        if relative is None:
            relative = len(packed_records)
            relative_by_body[raw] = relative
            packed_records.extend(raw)
        rebuilt_pointers.append(
            catalog.table_pointer(table) + (table.count + 1) * 2 + relative
        )

    old_data_size = table_end - data_start
    delta = len(packed_records) - old_data_size
    new_used_end = used_end + delta
    if new_used_end > WEAPON_RULE_SHARED_END:
        remaining = WEAPON_RULE_SHARED_END - used_end
        raise ValueError(
            f"武器规律共享池容量不足：本次需净增 {delta} B，"
            f"当前仅剩 {remaining} B。"
        )
    if new_used_end <= data_start:
        raise ValueError("规律重排后的共享池边界无效。")
    output = bytearray(data)
    tail = bytes(catalog.data[table_end:used_end])
    packed = bytes(packed_records) + tail
    output[data_start:data_start + len(packed)] = packed
    if delta < 0:
        output[new_used_end:used_end] = b"\x00" * (-delta)

    for order, family in enumerate(WEAPON_RULE_STORAGE_ORDER):
        old_table_pointer = catalog.table_pointer(family)
        new_table_pointer = old_table_pointer + (delta if order > selected_order else 0)
        if order > selected_order:
            output[
                family.directory_offset:family.directory_offset + 2
            ] = new_table_pointer.to_bytes(2, "little")
        new_table_offset = family.file_base + new_table_pointer - family.cpu_base
        for index in range(1, family.count + 1):
            if order == selected_order:
                pointer = rebuilt_pointers[index - 1]
            else:
                pointer = catalog.pointer(family, index)
            if order > selected_order:
                pointer += delta
            pointer_offset = new_table_offset + index * 2
            output[pointer_offset:pointer_offset + 2] = pointer.to_bytes(2, "little")
    return bytes(output)


class WeaponRuleLibraryDialog(QDialog):
    """Reference-shaped, dedicated four-page weapon-rule browser."""

    def __init__(self, project, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.project = project
        self.base = bytes(project.working)
        self.catalog = WeaponRuleCatalog(project.working)
        self.overrides = dict(getattr(project, "animation_label_overrides", {}))
        self.rule_overrides: dict[tuple[str, int], bytes] = {}
        self.code_errors: dict[tuple[str, int], str] = {}
        self._loading_code = False
        self.defaults: dict[str, tuple[str, ...]] = {}
        self.setWindowTitle("规律")
        self.resize(840, 610)
        root = QVBoxLayout(self)
        notice = QLabel(
            "这里是武器专用的四套规律库，不与地图动画规律混用。"
            "代码与坐标按旧版四库共享池重排；增长会同步移动后续指针表，"
            "不会覆盖相邻记录。"
        )
        notice.setWordWrap(True)
        root.addWidget(notice)
        self.memory_status = QLabel()
        root.addWidget(self.memory_status)
        self.tabs = QTabWidget()
        self.lists: dict[str, QListWidget] = {}
        self.names: dict[str, QLineEdit] = {}
        self.codes: dict[str, QPlainTextEdit] = {}
        self.statuses: dict[str, QLabel] = {}
        self.searches: dict[str, QLineEdit] = {}
        self.complete_checks: dict[str, QCheckBox] = {}
        self.preview_library: dict[str, QComboBox] = {}
        self.puzzle_buttons: dict[str, QPushButton] = {}
        self.simulator_buttons: dict[str, QPushButton] = {}
        self.coordinate_controls: dict[str, tuple[QSpinBox, QSpinBox]] = {}
        self.beam_coordinate_controls: dict[
            str,
            tuple[QCheckBox, QSpinBox, QSpinBox, QCheckBox, QSpinBox, QSpinBox],
        ] = {}
        self.tile_increment_controls: dict[str, QSpinBox] = {}
        root.addWidget(self.tabs, 1)
        overrides = getattr(project, "animation_label_overrides", {})
        for table in WEAPON_RULE_TABLES:
            page = QWidget()
            layout = QHBoxLayout(page)
            listing = QListWidget()
            defaults = animation_names(table.filename, table.count)
            self.defaults[table.key] = defaults
            listing.addItems(
                f"[{rule_id:02X}]{rule_id:03d}："
                f"{overrides.get((table.key, rule_id), defaults[rule_id - 1])}"
                for rule_id in range(1, table.count + 1)
            )
            listing.setMinimumWidth(330)
            selection = QVBoxLayout()
            search_row = QHBoxLayout()
            search = QLineEdit()
            search.setPlaceholderText("按编号或名称查找，例如 20、光束")
            find_next = QPushButton("查找下一个")
            find_next.clicked.connect(
                lambda _checked=False, item=table: self._find_next(item)
            )
            search.returnPressed.connect(lambda item=table: self._find_next(item))
            search_row.addWidget(search, 1)
            search_row.addWidget(find_next)
            selection.addLayout(search_row)
            selection.addWidget(listing, 1)
            layout.addLayout(selection, 2)
            details = QVBoxLayout()
            status = QLabel()
            status.setWordWrap(True)
            status.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
            details.addWidget(status)
            details.addWidget(QLabel("规律名称（当前配置）"))
            name = QLineEdit()
            name.setMaxLength(80)
            details.addWidget(name)
            code_title = QHBoxLayout()
            code_title.addWidget(QLabel("代码（十六进制，可编辑）"))
            complete = QCheckBox("显示完整记录（含前置字节）")
            complete.setToolTip(
                "参考窗口会隐藏部分固定前置字节；勾选后可查看磁盘中的完整记录，仍不会修改 ROM。"
            )
            complete.toggled.connect(
                lambda checked=False, item=table: self._toggle_complete(item, checked)
            )
            code_title.addStretch()
            code_title.addWidget(complete)
            details.addLayout(code_title)
            code = QPlainTextEdit()
            details.addWidget(code, 1)
            if table.key == "weapon_beam":
                coordinate_row = QHBoxLayout()
                initial_check = QCheckBox("设置初始坐标")
                initial_x = QSpinBox()
                initial_y = QSpinBox()
                for spin in (initial_x, initial_y):
                    spin.setRange(0, 0xFF)
                coordinate_row.addWidget(initial_check)
                coordinate_row.addWidget(QLabel("X"))
                coordinate_row.addWidget(initial_x)
                coordinate_row.addWidget(QLabel("Y"))
                coordinate_row.addWidget(initial_y)
                next_check = QCheckBox("设置下一张图片坐标")
                next_x = QSpinBox()
                next_y = QSpinBox()
                for spin in (next_x, next_y):
                    spin.setRange(-128, 127)
                coordinate_row.addSpacing(12)
                coordinate_row.addWidget(next_check)
                coordinate_row.addWidget(QLabel("X"))
                coordinate_row.addWidget(next_x)
                coordinate_row.addWidget(QLabel("Y"))
                coordinate_row.addWidget(next_y)
                coordinate_row.addStretch()
                details.addLayout(coordinate_row)
                controls = (
                    initial_check, initial_x, initial_y,
                    next_check, next_x, next_y,
                )
                self.beam_coordinate_controls[table.key] = controls
                for control in controls:
                    if isinstance(control, QCheckBox):
                        control.toggled.connect(
                            lambda _checked=False, item=table:
                            self._coordinate_changed(item)
                        )
                    else:
                        control.valueChanged.connect(
                            lambda _value=0, item=table:
                            self._coordinate_changed(item)
                        )
            elif table.key == "weapon_picture":
                coordinate_row = QHBoxLayout()
                coordinate_row.addWidget(QLabel("锚点坐标"))
                x_spin = QSpinBox()
                y_spin = QSpinBox()
                for spin in (x_spin, y_spin):
                    spin.setRange(0, 0xFF)
                coordinate_row.addWidget(QLabel("X"))
                coordinate_row.addWidget(x_spin)
                coordinate_row.addWidget(QLabel("Y"))
                coordinate_row.addWidget(y_spin)
                coordinate_row.addStretch()
                details.addLayout(coordinate_row)
                self.coordinate_controls[table.key] = (x_spin, y_spin)
                x_spin.valueChanged.connect(
                    lambda _value=0, item=table: self._coordinate_changed(item)
                )
                y_spin.valueChanged.connect(
                    lambda _value=0, item=table: self._coordinate_changed(item)
                )
            elif table.key.startswith("weapon_movement_"):
                increment_row = QHBoxLayout()
                increment_row.addWidget(QLabel("图块编号增加"))
                increment_spin = QSpinBox()
                increment_spin.setRange(1, 0xFF)
                increment_spin.setDisplayIntegerBase(16)
                increment_spin.setPrefix("$")
                increment_spin.setValue(1)
                apply_increment = QPushButton("应用增加值")
                apply_increment.clicked.connect(
                    lambda _checked=False, item=table: self._increment_tiles(item)
                )
                increment_row.addWidget(increment_spin)
                increment_row.addWidget(apply_increment)
                increment_row.addStretch()
                details.addLayout(increment_row)
                self.tile_increment_controls[table.key] = increment_spin
            code_actions = QHBoxLayout()
            copy_code = QPushButton("复制代码")
            copy_code.clicked.connect(
                lambda _checked=False, item=table: self._copy_current(item)
            )
            export_current = QPushButton("导出当前…")
            export_current.clicked.connect(
                lambda _checked=False, item=table: self._export_current(item)
            )
            export_all = QPushButton("导出本页全部…")
            export_all.clicked.connect(
                lambda _checked=False, item=table: self._export_all(item)
            )
            code_actions.addWidget(copy_code)
            code_actions.addWidget(export_current)
            code_actions.addWidget(export_all)
            code_actions.addStretch()
            details.addLayout(code_actions)
            legacy_actions = QHBoxLayout()
            simulator = QPushButton("运动规律模拟器")
            simulator.clicked.connect(
                lambda _checked=False, item=table: self._open_simulator(item)
            )
            legacy_actions.addWidget(simulator)
            self.simulator_buttons[table.key] = simulator
            if table.key in {"weapon_beam", "weapon_picture"}:
                legacy_actions.addWidget(QLabel("预览图库"))
                library_combo = QComboBox()
                bank_count = max(1, project.chr_tile_count // 64 - 3)
                for bank in range(bank_count):
                    library_combo.addItem(
                        f"[{bank:02X}]{bank:03d}：{0x80010 + bank * 0x400:05X}",
                        bank,
                    )
                puzzle = QPushButton(
                    "光束规律拼图"
                    if table.key == "weapon_beam"
                    else "物理图片拼图"
                )
                puzzle.clicked.connect(
                    lambda _checked=False, item=table: self._open_puzzle(item)
                )
                legacy_actions.addWidget(library_combo, 1)
                legacy_actions.addWidget(puzzle)
                self.preview_library[table.key] = library_combo
                self.puzzle_buttons[table.key] = puzzle
            else:
                legacy_actions.addStretch()
            details.addLayout(legacy_actions)
            boundary = QLabel(
                "名称保存到工程；代码和坐标随窗口“确定”一次写入 ROM。"
                "取消不会修改 ROM；超出共享池容量会拒绝保存。"
            )
            boundary.setWordWrap(True)
            details.addWidget(boundary)
            layout.addLayout(details, 3)
            self.tabs.addTab(page, table.title)
            self.lists[table.key] = listing
            self.names[table.key] = name
            self.codes[table.key] = code
            self.statuses[table.key] = status
            self.searches[table.key] = search
            self.complete_checks[table.key] = complete
            code.textChanged.connect(
                lambda item=table: self._code_changed(item)
            )
            listing.currentRowChanged.connect(
                lambda row, item=table: self._select(item, row)
            )
            name.textEdited.connect(
                lambda text, item=table: self._rename(item, text)
            )
            listing.setCurrentRow(0)
        self._update_memory_status(self.base)
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok
            | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.button(QDialogButtonBox.StandardButton.Ok).setText("确定")
        buttons.button(QDialogButtonBox.StandardButton.Cancel).setText("取消")
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        root.addWidget(buttons)

    def _current_record(
        self, table: WeaponRuleTable, *, include_hidden: bool = False
    ) -> tuple[int, int, bytes, tuple[int, ...]]:
        row = self.lists[table.key].currentRow()
        if row < 0:
            raise ValueError("尚未选择规律。")
        rule_id = row + 1
        offset, _raw, aliases = self.catalog.record(
            table, rule_id, include_hidden=True
        )
        full = self._full_record(table, rule_id)
        if include_hidden:
            raw = full
        elif table.key == "weapon_beam":
            raw = split_beam_rule(full).body
        else:
            raw = full[table.hidden_prefix:]
        return rule_id, offset, raw, aliases

    @staticmethod
    def _parse_hex_code(text: str) -> bytes:
        normalized = text.replace(",", " ").strip()
        if not normalized:
            raise ValueError("规律代码不能为空。")
        tokens = normalized.split()
        if any(len(token) != 2 for token in tokens):
            raise ValueError("规律代码必须使用空格分隔的两位十六进制字节。")
        try:
            return bytes(int(token, 16) for token in tokens)
        except ValueError as error:
            raise ValueError("规律代码包含无效十六进制字节。") from error

    def _full_record(self, table: WeaponRuleTable, rule_id: int) -> bytes:
        override = self.rule_overrides.get((table.key, rule_id))
        if override is not None:
            return override
        return self.catalog.record(table, rule_id, include_hidden=True)[1]

    def _preview_bytes(self) -> bytes:
        draft = self.base
        order = {table.key: index for index, table in enumerate(WEAPON_RULE_STORAGE_ORDER)}
        for (key, rule_id), raw in sorted(
            self.rule_overrides.items(), key=lambda item: (order[item[0][0]], item[0][1])
        ):
            draft = replace_weapon_rule_record(
                draft, key, rule_id, raw, include_hidden=True
            )
        return draft

    def _update_memory_status(self, data: bytes) -> None:
        catalog = WeaponRuleCatalog(data)
        start = catalog.table_offset(WEAPON_RULE_STORAGE_ORDER[0])
        used = catalog.used_end() - start
        capacity = WEAPON_RULE_SHARED_END - start
        self.memory_status.setText(
            f"四库共享容量：已用 {used}/{capacity} B · 剩余 {capacity - used} B · "
            "物理图片 → 光束组图 → 运行规律1 → 运行规律2"
        )

    def _code_changed(self, table: WeaponRuleTable) -> None:
        if self._loading_code or self.complete_checks[table.key].isChecked():
            return
        row = self.lists[table.key].currentRow()
        if row < 0:
            return
        rule_id = row + 1
        try:
            visible = self._parse_hex_code(self.codes[table.key].toPlainText())
            original = self._full_record(table, rule_id)
            if table.key == "weapon_beam":
                parts = split_beam_rule(original)
                full = join_beam_rule(
                    BeamRuleParts(parts.initial, visible, parts.next_offset)
                )
            else:
                full = original[:table.hidden_prefix] + visible
            if table.key == "weapon_picture" and len(full) < 3:
                raise ValueError("物理图片规律必须保留 X/Y 前置字节和规律内容。")
            self.rule_overrides[(table.key, rule_id)] = full
            self.code_errors.pop((table.key, rule_id), None)
            self._update_memory_status(self._preview_bytes())
        except ValueError as error:
            self.code_errors[(table.key, rule_id)] = str(error)
            self.statuses[table.key].setText(f"未暂存：{error}")

    def _coordinate_changed(self, table: WeaponRuleTable) -> None:
        if self._loading_code:
            return
        row = self.lists[table.key].currentRow()
        if row < 0:
            return
        rule_id = row + 1
        if table.key == "weapon_beam":
            controls = self.beam_coordinate_controls.get(table.key)
            if controls is None:
                return
            initial_check, initial_x, initial_y, next_check, next_x, next_y = controls
            initial_x.setEnabled(initial_check.isChecked())
            initial_y.setEnabled(initial_check.isChecked())
            next_x.setEnabled(next_check.isChecked())
            next_y.setEnabled(next_check.isChecked())
            parts = split_beam_rule(self._full_record(table, rule_id))
            full = join_beam_rule(
                BeamRuleParts(
                    (initial_x.value(), initial_y.value())
                    if initial_check.isChecked() else None,
                    parts.body,
                    (next_x.value(), next_y.value())
                    if next_check.isChecked() else None,
                )
            )
        else:
            controls = self.coordinate_controls.get(table.key)
            if controls is None:
                return
            full = bytearray(self._full_record(table, rule_id))
            x_spin, y_spin = controls
            if len(full) < 2:
                return
            full[0] = x_spin.value()
            full[1] = y_spin.value()
        self.rule_overrides[(table.key, rule_id)] = bytes(full)
        self._update_memory_status(self._preview_bytes())

    def _increment_tiles(self, table: WeaponRuleTable) -> None:
        row = self.lists[table.key].currentRow()
        spin = self.tile_increment_controls.get(table.key)
        if row < 0 or spin is None:
            return
        rule_id = row + 1
        try:
            full = increment_weapon_rule_tiles(
                self._full_record(table, rule_id), spin.value()
            )
            self.rule_overrides[(table.key, rule_id)] = full
            self.code_errors.pop((table.key, rule_id), None)
            self._loading_code = True
            self.codes[table.key].setPlainText(full.hex(" ").upper())
            self._loading_code = False
            self._update_memory_status(self._preview_bytes())
            self._refresh_selected(table)
        except ValueError as error:
            self.statuses[table.key].setText(f"未应用：{error}")

    def _toggle_complete(self, table: WeaponRuleTable, checked: bool) -> None:
        self.codes[table.key].setReadOnly(checked)
        self._refresh_selected(table)

    def _open_simulator(self, table: WeaponRuleTable) -> None:
        # The reference simulator is an independent scratch tool.  All four
        # entry points open with blank X/Y streams; they do not duplicate the
        # selected rule into both axes or write back on close.
        dialog = WeaponMovementSimulatorDialog(parent=self)
        dialog.exec()

    def _open_puzzle(self, table: WeaponRuleTable) -> None:
        try:
            rule_id, offset, full, aliases = self._current_record(
                table, include_hidden=True
            )
        except ValueError as error:
            QMessageBox.information(self, "无法打开拼图", str(error))
            return
        if table.key == "weapon_beam":
            parts = split_beam_rule(full)
            anchor_x, anchor_y = parts.initial or (0, 0)
            raw = bytes((anchor_x, anchor_y)) + parts.body
            title = "光束拼图"
        elif table.key == "weapon_picture":
            raw = full
            title = "物理拼图"
        else:
            return
        record = AnimationRecord(
            kind="sprite",
            index=rule_id,
            offset=offset,
            raw=raw,
            aliases=aliases,
            instructions=(),
            complete=True,
        )

        class _StaticCodec:
            @staticmethod
            def count(kind: str) -> int:
                return 0 if kind == "movement" else 0x100

            @staticmethod
            def movement_roles() -> dict[int, set[str]]:
                return {}

        dialog = SpritePuzzlePreviewDialog(
            record,
            self.project,
            _StaticCodec(),  # type: ignore[arg-type]
            self,
            initial_library=int(self.preview_library[table.key].currentData() or 0),
            editable=True,
            puzzle_kind=("beam" if table.key == "weapon_beam" else "physical"),
        )
        dialog.setWindowTitle(title)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        try:
            edited = dialog.edited_raw()
            if table.key == "weapon_beam":
                if len(edited) < 3:
                    raise ValueError("光束拼图必须包含 X、Y 与规律内容。")
                edited_parts = split_beam_rule(
                    bytes((0xFE, edited[1], edited[0])) + edited[2:]
                )
                original_parts = split_beam_rule(full)
                updated = join_beam_rule(
                    BeamRuleParts(
                        edited_parts.initial
                        if original_parts.initial is not None else None,
                        edited_parts.body,
                        original_parts.next_offset
                        if original_parts.next_offset is not None
                        else edited_parts.next_offset,
                    )
                )
            else:
                updated = edited
            self.rule_overrides[(table.key, rule_id)] = updated
            self.code_errors.pop((table.key, rule_id), None)
            self._update_memory_status(self._preview_bytes())
            self._refresh_selected(table)
        except ValueError as error:
            self.statuses[table.key].setText(f"拼图未应用：{error}")

    def _select(self, table: WeaponRuleTable, row: int) -> None:
        if row < 0:
            return
        rule_id = row + 1
        include_hidden = self.complete_checks[table.key].isChecked()
        self.names[table.key].setText(
            self.lists[table.key].item(row).text().split("：", 1)[-1]
        )
        try:
            offset, _original, aliases = self.catalog.record(
                table, rule_id, include_hidden=True
            )
            full = self._full_record(table, rule_id)
            if include_hidden:
                raw = full
            elif table.key == "weapon_beam":
                raw = split_beam_rule(full).body
            else:
                raw = full[table.hidden_prefix:]
        except ValueError as error:
            pointer = self.catalog.pointer(table, rule_id)
            self.codes[table.key].clear()
            self.statuses[table.key].setText(
                f"规律 ${rule_id:02X} · 指针 ${pointer:04X} · "
                f"保留/控制项，不能按普通规律解析：{error}"
            )
            return
        self._loading_code = True
        self.codes[table.key].setPlainText(raw.hex(" ").upper())
        beam_controls = self.beam_coordinate_controls.get(table.key)
        if beam_controls is not None:
            initial_check, initial_x, initial_y, next_check, next_x, next_y = (
                beam_controls
            )
            parts = split_beam_rule(full)
            initial_check.setChecked(parts.initial is not None)
            initial_x.setValue(parts.initial[0] if parts.initial else 0)
            initial_y.setValue(parts.initial[1] if parts.initial else 0)
            next_check.setChecked(parts.next_offset is not None)
            next_x.setValue(parts.next_offset[0] if parts.next_offset else 0)
            next_y.setValue(parts.next_offset[1] if parts.next_offset else 0)
            initial_x.setEnabled(parts.initial is not None)
            initial_y.setEnabled(parts.initial is not None)
            next_x.setEnabled(parts.next_offset is not None)
            next_y.setEnabled(parts.next_offset is not None)
        controls = self.coordinate_controls.get(table.key)
        if controls is not None:
            x_spin, y_spin = controls
            if table.key == "weapon_picture" and len(full) >= 2:
                x_value, y_value = full[0], full[1]
            else:
                x_value = y_value = 0
            x_spin.setValue(x_value)
            y_spin.setValue(y_value)
        self._loading_code = False
        shared = "、".join(f"${value:02X}" for value in aliases[:16])
        self.statuses[table.key].setText(
            f"规律 ${rule_id:02X} · 文件地址 0x{offset:06X} · {len(raw)} 字节"
            + (
                "（完整记录，含坐标控制字节）"
                if include_hidden and table.key == "weapon_beam"
                else f"（完整记录，含 {table.hidden_prefix} 个前置字节）"
                if include_hidden and table.hidden_prefix
                else ""
            )
            + (
                f" · 存储同源：{shared}（编辑当前项时自动拆分）"
                if shared else " · 独立记录"
            )
        )

    def _refresh_selected(self, table: WeaponRuleTable) -> None:
        self._select(table, self.lists[table.key].currentRow())

    def _find_next(self, table: WeaponRuleTable) -> None:
        query = self.searches[table.key].text().strip().casefold()
        if not query:
            return
        listing = self.lists[table.key]
        start = listing.currentRow() + 1
        for step in range(listing.count()):
            row = (start + step) % listing.count()
            text = listing.item(row).text().casefold()
            rule_id = row + 1
            identifiers = {
                str(rule_id), f"{rule_id:02x}", f"${rule_id:02x}",
                f"[{rule_id:02x}]",
            }
            if query in text or query in identifiers:
                listing.setCurrentRow(row)
                listing.scrollToItem(listing.item(row))
                return
        QMessageBox.information(self, "没有找到", f"本页没有匹配“{query}”的规律。")

    def _current_text(self, table: WeaponRuleTable) -> str:
        row = self.lists[table.key].currentRow()
        if row < 0:
            return ""
        rule_id = row + 1
        name = self.lists[table.key].item(row).text().split("：", 1)[-1]
        preview_catalog = WeaponRuleCatalog(self._preview_bytes())
        try:
            offset, raw, aliases = preview_catalog.record(
                table,
                rule_id,
                include_hidden=self.complete_checks[table.key].isChecked(),
            )
        except ValueError as error:
            pointer = preview_catalog.pointer(table, rule_id)
            return (
                f"{table.title} ${rule_id:02X}\n"
                f"名称：{name}\n"
                f"指针：${pointer:04X}\n"
                f"状态：保留/控制项，不能按普通规律解析（{error}）\n"
            )
        alias_text = "、".join(f"${value:02X}" for value in aliases) or "无"
        return (
            f"{table.title} ${rule_id:02X}\n"
            f"名称：{name}\n"
            f"文件地址：0x{offset:06X}\n"
            f"存储同源规律：{alias_text}（编辑当前项时自动拆分）\n"
            f"代码：{raw.hex(' ').upper()}\n"
        )

    def _all_text(self, table: WeaponRuleTable) -> str:
        complete = self.complete_checks[table.key].isChecked()
        preview_catalog = WeaponRuleCatalog(self._preview_bytes())
        rows = [f"# {table.title}", f"# 记录数：{table.count}", ""]
        for rule_id in range(1, table.count + 1):
            name = self.lists[table.key].item(rule_id - 1).text().split("：", 1)[-1]
            try:
                offset, raw, aliases = preview_catalog.record(
                    table, rule_id, include_hidden=complete
                )
            except ValueError as error:
                pointer = preview_catalog.pointer(table, rule_id)
                rows.append(
                    f"${rule_id:02X}\t指针:${pointer:04X}\t{name}\t"
                    f"保留/控制项\t{error}"
                )
                continue
            shared = ",".join(f"${value:02X}" for value in aliases) or "-"
            rows.append(
                f"${rule_id:02X}\t0x{offset:06X}\t{name}\t共享:{shared}\t"
                f"{raw.hex(' ').upper()}"
            )
        return "\n".join(rows) + "\n"

    def _copy_current(self, table: WeaponRuleTable) -> None:
        text = self._current_text(table)
        if text:
            QApplication.clipboard().setText(text)
            self.statuses[table.key].setText(
                self.statuses[table.key].text() + " · 已复制"
            )

    def _save_text(self, title: str, suggested: str, text: str) -> None:
        path, _selected_filter = QFileDialog.getSaveFileName(
            self, title, suggested, "文本文件 (*.txt);;所有文件 (*)"
        )
        if not path:
            return
        try:
            from pathlib import Path

            Path(path).write_text(text, encoding="utf-8-sig")
        except OSError as error:
            QMessageBox.warning(self, "导出失败", str(error))

    def _export_current(self, table: WeaponRuleTable) -> None:
        row = self.lists[table.key].currentRow()
        if row < 0:
            return
        self._save_text(
            "导出当前规律",
            f"{table.title}-${row + 1:02X}.txt",
            self._current_text(table),
        )

    def _export_all(self, table: WeaponRuleTable) -> None:
        self._save_text(
            "导出本页全部规律",
            f"{table.title}-全部.txt",
            self._all_text(table),
        )

    def _rename(self, table: WeaponRuleTable, text: str) -> None:
        row = self.lists[table.key].currentRow()
        if row < 0:
            return
        rule_id = row + 1
        default = self.defaults[table.key][row]
        if text == default:
            self.overrides.pop((table.key, rule_id), None)
        else:
            self.overrides[(table.key, rule_id)] = text
        self.lists[table.key].item(row).setText(
            f"[{rule_id:02X}]{rule_id:03d}：{text}"
        )

    def accept(self) -> None:
        try:
            if self.code_errors:
                first_error = next(iter(self.code_errors.values()))
                raise ValueError(first_error)
            if bytes(self.project.working) != self.base:
                raise ValueError("ROM 草稿已在其他窗口变化；请重新打开规律窗口后再保存。")
            draft = self._preview_bytes()
            with self.project.transaction("武器四库规律、坐标与名称"):
                self.project.working[:] = draft
                self.project.replace_animation_label_overrides(self.overrides)
        except ValueError as error:
            QMessageBox.warning(self, "无法保存武器规律", str(error))
            return
        super().accept()
