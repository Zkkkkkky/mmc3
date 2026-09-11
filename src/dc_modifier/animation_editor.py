from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QComboBox, QDialog, QFormLayout, QGroupBox, QHBoxLayout, QHeaderView,
    QLabel, QLineEdit, QListWidget, QPlainTextEdit, QPushButton, QSpinBox,
    QTableWidget, QTableWidgetItem, QTabWidget, QVBoxLayout, QWidget,
)

from fc_editor.codecs.animation import (
    AnimationCodec, AnimationRecord, apply_animation_patches,
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


class AnimationScriptWidget(QWidget):
    """A draft script editor; the caller owns its enclosing transaction."""
    changed = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
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
        self.instruction_table.setMinimumHeight(200)
        root.addWidget(self.instruction_table, 1)
        self.parameters = QWidget()
        self.parameter_layout = QHBoxLayout(self.parameters)
        self.parameter_layout.setContentsMargins(0, 0, 0, 0)
        root.addWidget(self.parameters)
        self.code_button = QPushButton("代码编辑")
        self.code_button.clicked.connect(self._toggle_code)
        root.addWidget(self.code_button, 0, Qt.AlignmentFlag.AlignLeft)
        self.code_edit = QPlainTextEdit()
        self.code_edit.setPlaceholderText("等长十六进制代码")
        self.code_edit.setMaximumHeight(130)
        self.code_edit.textChanged.connect(self._code_changed)
        self.code_edit.hide()
        root.addWidget(self.code_edit)
        hint = QLabel("选择一条指令可调整参数。代码编辑仅接受已有指令的颜色、等待、图库、坐标、音乐和循环次数；共享指针的动画同步变化。")
        hint.setWordWrap(True)
        root.addWidget(hint)

    def set_record(self, data: bytes | bytearray, kind: str, index: int) -> None:
        self.codec = AnimationCodec(data)
        self.record = self.codec.record(kind, index)
        record = self.record
        self._set_code(record.raw)
        self.instruction_table.setRowCount(len(record.instructions))
        for row, instruction in enumerate(record.instructions):
            item = QTableWidgetItem(f"{row:03d}：{instruction.text}")
            item.setToolTip(f"文件地址 ${instruction.offset:06X}")
            self.instruction_table.setItem(row, 0, item)
            self.instruction_table.setItem(row, 1, QTableWidgetItem(instruction.raw.hex(" ").upper()))
        self.instruction_table.resizeRowsToContents()
        aliases = ", ".join(f"${i:02X}" for i in record.aliases[:12])
        if len(record.aliases) > 12:
            aliases += f"…共 {len(record.aliases)} 项"
        self.status.setText(f"当前 ROM · ${record.offset:06X} · {len(record.raw)} 字节"
                            + (f" · 共享：{aliases}" if aliases else " · 独立记录")
                            + ("" if record.complete else " · 包含未验证内容"))
        self.code_button.setEnabled(any(i.editable for i in record.instructions))
        self.code_edit.setReadOnly(not self.code_button.isEnabled())
        self.instruction_table.setCurrentCell(0, 0)
        self._select_instruction(0, 0, -1, -1)

    def _set_code(self, data: bytes) -> None:
        blocked = self.code_edit.blockSignals(True)
        self.code_edit.setPlainText(data.hex(" ").upper())
        self.code_edit.blockSignals(blocked)

    def _toggle_code(self) -> None:
        self.code_edit.setVisible(not self.code_edit.isVisible())
        if self.code_edit.isVisible():
            self.code_edit.setFocus()

    def _code_changed(self) -> None:
        if self.record is not None:
            from fc_editor.codecs.animation import decode_script
            try:
                raw = bytes.fromhex(self.code_edit.toPlainText())
                rows, _complete = decode_script(raw, self.record.offset)
                if len(rows) == self.instruction_table.rowCount():
                    for row, instruction in enumerate(rows):
                        self.instruction_table.item(row, 0).setText(f"{row:03d}：{instruction.text}")
                        self.instruction_table.item(row, 1).setText(instruction.raw.hex(" ").upper())
                    self.instruction_table.resizeRowsToContents()
            except ValueError:
                pass
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
        return self.codec.script_patch(self.record, replacement)

    def _select_instruction(self, row: int, *_args) -> None:
        while self.parameter_layout.count():
            item = self.parameter_layout.takeAt(0)
            if item.widget() is not None:
                item.widget().deleteLater()
        if self.record is None or not 0 <= row < len(self.record.instructions):
            return
        instruction = self.record.instructions[row]
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
            if len(replacement) != len(self.record.raw):
                raise ValueError("请先修正代码长度。")
            replacement[index] = value
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
        self.setMinimumHeight(360)

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
        self.resize(1160, 800)
        self.setMinimumSize(850, 620)
        self._selected = -1
        self._movement_index = -1
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
        self.names = animation_names("地图动画名称.ini", self.codec.count("map"), 1)
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
        self.add_button.setEnabled(False)
        self.add_button.setToolTip("当前实现编辑既有记录；新增指针和搬移空间尚未开放。")
        left.addWidget(self.add_button)
        left.addWidget(QLabel("动画名称（配置标签）"))
        self.animation_name = QLineEdit()
        self.animation_name.setReadOnly(True)
        left.addWidget(self.animation_name)
        group.setMaximumWidth(320)
        layout.addWidget(group, 1)
        self.script_editor = AnimationScriptWidget()
        self.instruction_table = self.script_editor.instruction_table
        self.code_button = self.script_editor.code_button
        layout.addWidget(self.script_editor, 3)
        return page

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

    def _rules_tab(self) -> QWidget:
        page = QWidget()
        layout = QHBoxLayout(page)
        self.rule_lists: dict[str, QListWidget] = {}
        self.rule_codes: dict[str, QPlainTextEdit] = {}
        self.rule_statuses: dict[str, QLabel] = {}
        self._movement_roles = self.codec.movement_roles()
        for kind, title, filename, first in (
            ("background", "背景规律", "背景规律名称.ini", 0),
            ("movement", "运行规律", "地图动画运行规律名称.ini", 1),
            ("sprite", "组图规律", "地图动画图片名称.ini", 0),
        ):
            group = QGroupBox(title)
            box = QVBoxLayout(group)
            listing = QListWidget()
            names = animation_names(filename, self.codec.count(kind), first)
            listing.addItems(f"[{i:02X}]{i:03d}：{name}" for i, name in enumerate(names))
            self.rule_lists[kind] = listing
            listing.currentRowChanged.connect(lambda row, key=kind: self._select_rule(key, row))
            box.addWidget(listing, 3)
            status = QLabel()
            status.setWordWrap(True)
            self.rule_statuses[kind] = status
            box.addWidget(status)
            code = QPlainTextEdit()
            code.setReadOnly(True)
            self.rule_codes[kind] = code
            box.addWidget(code, 2)
            if kind == "sprite":
                form = QFormLayout()
                self.sprite_y, self.sprite_x = QSpinBox(), QSpinBox()
                for spin in (self.sprite_y, self.sprite_x):
                    spin.setRange(-128, 127)
                    spin.valueChanged.connect(self._change_sprite_anchor)
                form.addRow("起始 X", self.sprite_x)
                form.addRow("起始 Y", self.sprite_y)
                box.addLayout(form)
                box.addWidget(QLabel("可调整组图起始坐标；拼图指令保持原值。"))
            elif kind == "movement":
                apply = QPushButton("应用等长代码")
                apply.clicked.connect(self._apply_movement_code)
                box.addWidget(apply)
                notice = QLabel("根据实际调用区分组图帧和坐标位移。可改帧、位移、音效和循环次数；跳转、长度与控制码保持原值。")
                notice.setWordWrap(True)
                box.addWidget(notice)
            else:
                notice = QLabel("显示真实指针范围内的代码；此类规律的代码改写尚未开放。")
                notice.setWordWrap(True)
                box.addWidget(notice)
            layout.addWidget(group, 1)
        for kind, listing in self.rule_lists.items():
            listing.setCurrentRow(1 if kind == "movement" else 0)
        return page

    def _select_rule(self, kind: str, row: int) -> None:
        if row < 0:
            return
        if kind == "movement" and self._movement_index >= 0 and not self._apply_movement_code(self._movement_index):
            listing = self.rule_lists[kind]
            blocked = listing.blockSignals(True)
            listing.setCurrentRow(self._movement_index)
            listing.blockSignals(blocked)
            return
        record = AnimationCodec(self.draft).record(kind, row)
        self.rule_codes[kind].setPlainText(record.raw.hex(" ").upper())
        self.rule_statuses[kind].setText(f"当前 ROM · ${record.offset:06X} · {len(record.raw)} 字节"
                                         + (f" · 与 {len(record.aliases)} 项共享" if record.aliases else ""))
        if kind == "movement":
            self._movement_index = row
            roles = self._movement_roles.get(row, set())
            self.rule_codes[kind].setReadOnly(len(roles) != 1)
            self.rule_statuses[kind].setText(self.rule_statuses[kind].text() + " · " +
                                            ({"frames": "组图帧序列", "axis": "坐标位移"}.get(next(iter(roles)), "")
                                             if len(roles) == 1 else "运行方式未唯一确认，只读"))
        if kind == "sprite":
            self._loading = True
            self.sprite_y.setValue(int.from_bytes(record.raw[:1], signed=True))
            self.sprite_x.setValue(int.from_bytes(record.raw[1:2], signed=True))
            self._loading = False

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

    def _change_sprite_anchor(self) -> None:
        if self._loading:
            return
        row = self.rule_lists["sprite"].currentRow()
        if row < 0:
            return
        codec = AnimationCodec(self.draft)
        record = codec.record("sprite", row)
        changed = bytes((self.sprite_y.value() & 255, self.sprite_x.value() & 255)) + record.raw[2:]
        offset, _before, after = codec.rule_patch(record, changed)
        self.draft[offset:offset + len(after)] = after
        self.rule_codes["sprite"].setPlainText(after.hex(" ").upper())

    def _calls_tab(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        hint = QLabel("从当前事件脚本识别 38 02 动画调用；显示真实文件地址。未证明精神名称关联的调用不猜测名称。")
        hint.setWordWrap(True)
        layout.addWidget(hint)
        self.call_table = QTableWidget(0, 3)
        self.call_table.setHorizontalHeaderLabels(("调用位置", "当前动画", "动画指令"))
        self.call_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
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
            if not self.codec.call_is_editable(offset):
                combo.setEnabled(False)
                combo.setToolTip("此处已识别到调用字节，但事件上下文未验证；保留只读。")
            combo.currentIndexChanged.connect(lambda selected, address=offset: self._change_call(address, selected))
            self.call_table.setCellWidget(row, 1, combo)
            self.call_combos[offset] = combo
            jump = QPushButton("查看动画")
            jump.clicked.connect(lambda checked=False, box=combo: self._show_call_animation(box.currentIndex()))
            self.call_table.setCellWidget(row, 2, jump)
        layout.addWidget(self.call_table, 1)
        return page

    def _change_call(self, offset: int, index: int) -> None:
        try:
            codec = AnimationCodec(self.draft)
            address, _before, after = codec.call_patch(offset, index)
            self.draft[address:address + 1] = after
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
                or not self._apply_movement_code()):
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
            apply_animation_patches(self.project, tuple(patches), "地图动画、规律与调用")
        except ValueError as error:
            self.read_only_status.setText(f"未写入：{error}")
            return
        super().accept()
