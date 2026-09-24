from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMenu,
    QMessageBox,
    QPushButton,
    QSpinBox,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from fc_editor.codecs.chapter_event import (
    ACTION_FIELDS,
    INSTRUCTION_LENGTHS,
    OPCODE_HELP,
    OPCODE_LABELS,
    ChapterEventCodec,
)


def parameter_labels(opcode: int, parameter_count: int) -> tuple[str, ...]:
    """Return verified labels where available and lossless labels otherwise."""

    labels = ACTION_FIELDS.get(opcode, ())
    if len(labels) == parameter_count:
        return labels
    return tuple(f"参数 {index + 1}（原码）" for index in range(parameter_count))


class EventCodeDialog(QDialog):
    """Reference-shaped small hexadecimal editor used by the instruction dialog."""

    def __init__(self, raw: bytes, expected_length: int, parent=None) -> None:
        super().__init__(parent)
        self.expected_length = expected_length
        self.setWindowTitle("事件代码编辑")
        self.setMinimumWidth(520)
        layout = QVBoxLayout(self)
        layout.addWidget(QLabel("十六进制代码："))
        self.code_edit = QLineEdit(raw.hex(" ").upper())
        self.code_edit.setObjectName("eventInstructionHexCode")
        self.status = QLabel()
        self.status.setWordWrap(True)
        layout.addWidget(self.code_edit)
        layout.addWidget(self.status)
        self.buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok
            | QDialogButtonBox.StandardButton.Cancel
        )
        self.buttons.button(QDialogButtonBox.StandardButton.Ok).setText("确定")
        self.buttons.button(QDialogButtonBox.StandardButton.Cancel).setText("取消")
        self.buttons.accepted.connect(self.accept)
        self.buttons.rejected.connect(self.reject)
        layout.addWidget(self.buttons)
        self.code_edit.textChanged.connect(self._validate)
        self._validate()

    @staticmethod
    def parse_hex(text: str) -> bytes:
        compact = text.replace(",", " ").replace("0x", "").replace("$", "")
        tokens = compact.split()
        if not tokens:
            raise ValueError("请输入十六进制字节。")
        try:
            return bytes(int(token, 16) for token in tokens)
        except ValueError as error:
            raise ValueError("代码必须由 00—FF 的十六进制字节组成。") from error

    def _validate(self) -> None:
        try:
            raw = self.parse_hex(self.code_edit.text())
            if len(raw) != self.expected_length:
                raise ValueError(
                    f"当前槽位固定为 {self.expected_length} 字节，输入为 {len(raw)} 字节。"
                )
            length = ChapterEventCodec.instruction_length(raw[0], raw, 0)
            if length != len(raw):
                raise ValueError(
                    f"操作码 ${raw[0] & 0x7F:02X} 需要 {length} 字节，"
                    f"不能放入 {self.expected_length} 字节槽位。"
                )
        except (IndexError, ValueError) as error:
            self.status.setText(str(error))
            self.status.setStyleSheet("color: #b42318;")
            self.buttons.button(QDialogButtonBox.StandardButton.Ok).setEnabled(False)
            return
        self.status.setText(f"结构有效 · {len(raw)} 字节")
        self.status.setStyleSheet("color: #18794e;")
        self.buttons.button(QDialogButtonBox.StandardButton.Ok).setEnabled(True)

    def raw(self) -> bytes:
        return self.parse_hex(self.code_edit.text())


class EventInstructionDialog(QDialog):
    """Beginner-facing, fixed-slot editor matching the legacy three-page flow."""

    TRIGGER_GROUPS = (
        ("触发条件1", tuple((f"{code:02X}{OPCODE_LABELS[code]}", (code,)) for code in range(0x00, 0x08))),
        ("触发条件2", tuple((f"{code:02X}{OPCODE_LABELS[code]}", (code,)) for code in range(0x08, 0x13))),
        (
            "触发条件3",
            (
                ("13击落/被击落判断", (0x13,)),
                ("14向最近的敌人移动（行动）", (0x14,)),
                ("15向某人移动（行动）", (0x15,)),
                ("16/36强制移动某人（行动）", (0x16, 0x36)),
                ("18向某坐标移动（行动）", (0x18,)),
                ("19强制移向某坐标（行动）", (0x19,)),
                ("1A能否攻击判断（行动）", (0x1A,)),
                ("1B只攻击某人判断（行动）", (0x1B,)),
            ),
        ),
        (
            "触发条件4",
            (
                ("1C不攻击某人判断（行动）", (0x1C,)),
                ("1D地图炮攻击判断（行动）", (0x1D,)),
                ("1E控制某人行动（无光标）", (0x1E,)),
                ("1F提升五围（仅限我方，行动）", (0x1F,)),
                ("20剩余HP判断", (0x20,)),
                ("21地址量位判断", (0x21,)),
                ("22属性某位判断（行动）", (0x22,)),
                ("23属性值少于判断（行动）", (0x23,)),
                ("24范围内机体数量判断", (0x24,)),
                ("25周围机体数量判断（行动）", (0x25,)),
                ("26选项判断", (0x26,)),
            ),
        ),
    )
    ACTION_GROUPS = (
        (
            "执行事件1",
            (
                ("30动画播放（行动）", (0x30,)),
                ("31/32/33HP增减（行动）", (0x31, 0x32, 0x33)),
                ("34血量百分比恢复（行动）", (0x34,)),
                ("35置位与取消", (0x35,)),
                ("38传送到某人物周围（行动）", (0x38,)),
                ("39精神恢复（行动）", (0x39,)),
                ("3B敌方精神（行动）", (0x3B,)),
                ("3C选项事件", (0x3C,)),
                ("3A/3D范围内机体增加减少HP", (0x3A, 0x3D)),
                ("3E/3F周围机体增加减少HP（行动）", (0x3E, 0x3F)),
            ),
        ),
        (
            "执行事件2",
            (
                ("40/41/42对话窗口", (0x40, 0x41, 0x42)),
                ("43/44文字窗口", (0x43, 0x44)),
                ("45结束对话（关闭窗口）", (0x45,)),
                ("46/47/48设置光标位置", (0x46, 0x47, 0x48)),
                ("49攻击光标滑动", (0x49,)),
                ("4A/4B/4C战场机体增援", (0x4A, 0x4B, 0x4C)),
                ("4D更换人物和机体", (0x4D,)),
                ("4E更换机体", (0x4E,)),
                ("4F增加或减少道具", (0x4F,)),
            ),
        ),
        (
            "执行事件3",
            (
                ("50增加或减少金钱", (0x50,)),
                ("51/52开关操作", (0x51, 0x52)),
                ("53/54置移动限制代码", (0x53, 0x54)),
                ("55跳转到", (0x55,)),
                ("56跳转重复", (0x56,)),
                ("57/58判断跳转", (0x57, 0x58)),
                ("59/5A/5B播放音乐", (0x59, 0x5A, 0x5B)),
                ("5C属性置数单字节", (0x5C,)),
                ("5D属性置数双字节", (0x5D,)),
                ("5E等待（帧）", (0x5E,)),
            ),
        ),
        (
            "执行事件4",
            (
                ("60/61置移动限制代码（行动）", (0x60, 0x61)),
                ("62执行移动或攻击（行动）", (0x62,)),
                ("63执行待机（行动）", (0x63,)),
                ("64控制某人行动（有光标）", (0x64,)),
                ("65传送到某坐标（行动）", (0x65,)),
                ("66临时更换机体（行动）", (0x66,)),
                ("67/68更换阵营（行动）", (0x67, 0x68)),
                ("69更换为我方队员（行动）", (0x69,)),
                ("6A自爆（行动）", (0x6A,)),
            ),
        ),
    )
    ADVANCED_GROUPS = (
        (
            "其他指令",
            tuple(
                (f"{code:02X}{OPCODE_LABELS.get(code, '扩展指令')}", (code,))
                for code in (
                    0x17,
                    *range(0x27, 0x30),
                    0x37,
                    0x5F,
                    *range(0x6B, 0x7B),
                )
            ),
        ),
    )

    def __init__(
        self,
        raw: bytes,
        parent=None,
        *,
        title: str = "事件指令编辑",
        context: str = "",
    ) -> None:
        super().__init__(parent)
        if not raw:
            raise ValueError("事件指令不能为空。")
        self._slot_length = len(raw)
        self._raw = bytes(raw)
        self._current_opcode = raw[0] & 0x7F
        self._loading = False
        self.opcode_buttons: dict[int, QPushButton] = {}
        self._button_opcodes: dict[QPushButton, tuple[int, ...]] = {}
        self.setWindowTitle(title)
        self.resize(640, 700)
        self.setMinimumSize(600, 620)

        layout = QVBoxLayout(self)
        if context:
            context_label = QLabel(context)
            context_label.setObjectName("hintText")
            context_label.setWordWrap(True)
            layout.addWidget(context_label)

        self.tabs = QTabWidget()
        self.tabs.setObjectName("legacyEventInstructionTabs")
        self.tabs.addTab(self._command_page(self.TRIGGER_GROUPS), "1")
        self.tabs.addTab(self._command_page(self.ADVANCED_GROUPS), "2")
        self.tabs.addTab(self._command_page(self.ACTION_GROUPS), "3")
        layout.addWidget(self.tabs, 1)

        editor = QGroupBox("当前指令参数")
        form = QFormLayout(editor)
        self.command_name = QLabel()
        self.command_name.setWordWrap(True)
        self.meaning_help = QLabel()
        self.meaning_help.setWordWrap(True)
        self.meaning_help.setObjectName("hintText")
        self.terminal = QCheckBox("结束本事件组（操作码高位）")
        form.addRow("指令", self.command_name)
        form.addRow("作用", self.meaning_help)
        form.addRow("执行控制", self.terminal)
        self.parameter_labels: list[QLabel] = []
        self.parameters: list[QSpinBox] = []
        for index in range(7):
            label = QLabel()
            spin = QSpinBox()
            spin.setRange(0, 255)
            spin.setDisplayIntegerBase(16)
            spin.setPrefix("$")
            spin.valueChanged.connect(self._parameters_changed)
            label.hide()
            spin.hide()
            form.addRow(label, spin)
            self.parameter_labels.append(label)
            self.parameters.append(spin)
        layout.addWidget(editor)

        tools = QHBoxLayout()
        self.code_button = QPushButton("代码编辑…")
        self.copy_button = QPushButton("复制")
        self.paste_button = QPushButton("粘贴")
        self.restore_button = QPushButton("还原")
        tools.addWidget(self.code_button)
        tools.addWidget(self.copy_button)
        tools.addWidget(self.paste_button)
        tools.addWidget(self.restore_button)
        tools.addStretch(1)
        layout.addLayout(tools)
        self.status = QLabel()
        self.status.setWordWrap(True)
        layout.addWidget(self.status)
        self.buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok
            | QDialogButtonBox.StandardButton.Cancel
        )
        self.buttons.button(QDialogButtonBox.StandardButton.Ok).setText("确定")
        self.buttons.button(QDialogButtonBox.StandardButton.Cancel).setText("取消")
        self.buttons.accepted.connect(self.accept)
        self.buttons.rejected.connect(self.reject)
        layout.addWidget(self.buttons)

        self.terminal.toggled.connect(self._parameters_changed)
        self.code_button.clicked.connect(self._open_code_editor)
        self.copy_button.clicked.connect(self._copy)
        self.paste_button.clicked.connect(self._paste)
        self.restore_button.clicked.connect(lambda: self._load_raw(self._raw))
        self._load_raw(raw)

    def _command_page(self, groups) -> QWidget:
        page = QWidget()
        page_layout = QGridLayout(page)
        for group_index, (title, entries) in enumerate(groups):
            group = QGroupBox(title)
            grid = QGridLayout(group)
            for index, (label, opcodes) in enumerate(entries):
                button = QPushButton(label)
                button.setCheckable(True)
                compatible_opcodes = tuple(
                    opcode
                    for opcode in opcodes
                    if INSTRUCTION_LENGTHS[opcode] == self._slot_length
                    and INSTRUCTION_LENGTHS[opcode] > 0
                )
                compatible = bool(compatible_opcodes)
                button.setEnabled(compatible)
                if compatible:
                    button.clicked.connect(
                        lambda _checked=False, values=compatible_opcodes, source=button:
                        self._choose_opcode_group(values, source)
                    )
                else:
                    lengths = "/".join(
                        str(INSTRUCTION_LENGTHS[opcode] or "可变")
                        for opcode in opcodes
                    )
                    button.setToolTip(
                        f"此组指令需要 {lengths} 字节；当前槽位为 {self._slot_length} 字节。"
                    )
                grid.addWidget(button, index, 0)
                self._button_opcodes[button] = tuple(opcodes)
                for opcode in opcodes:
                    self.opcode_buttons[opcode] = button
            page_layout.addWidget(group, group_index // 2, group_index % 2)
        page_layout.setRowStretch((len(groups) - 1) // 2 + 1, 1)
        return page

    def _choose_opcode_group(
        self, opcodes: tuple[int, ...], button: QPushButton
    ) -> None:
        if len(opcodes) == 1:
            self._choose_opcode(opcodes[0])
            return
        menu = QMenu(self)
        for opcode in opcodes:
            action = menu.addAction(
                f"${opcode:02X} · {OPCODE_LABELS.get(opcode, '扩展指令')}"
            )
            action.triggered.connect(
                lambda _checked=False, value=opcode: self._choose_opcode(value)
            )
        menu.exec(button.mapToGlobal(button.rect().bottomLeft()))

    def _choose_opcode(self, opcode: int) -> None:
        parameters = bytes(
            spin.value() for spin in self.parameters[: self._slot_length - 1]
        )
        needed = self._slot_length - 1
        candidate = bytes((opcode,)) + parameters[:needed].ljust(needed, b"\x00")
        self._load_raw(candidate)

    def _load_raw(self, raw: bytes) -> None:
        self._loading = True
        try:
            opcode = raw[0] & 0x7F
            self._current_opcode = opcode
            self.terminal.setChecked(bool(raw[0] & 0x80))
            self.command_name.setText(
                f"${opcode:02X} · {OPCODE_LABELS.get(opcode, '未知指令')} · "
                f"固定 {self._slot_length} 字节"
            )
            self.meaning_help.setText(
                OPCODE_HELP.get(
                    opcode,
                    "该操作码的作用尚未完成可靠命名；编辑器会保留原始字节，"
                    "不会用猜测含义覆盖 ROM。",
                )
            )
            labels = parameter_labels(opcode, self._slot_length - 1)
            for index, (label, spin) in enumerate(
                zip(self.parameter_labels, self.parameters)
            ):
                visible = index < len(labels)
                label.setVisible(visible)
                spin.setVisible(visible)
                if visible:
                    label.setText(labels[index])
                    spin.setValue(raw[index + 1])
            for button, values in self._button_opcodes.items():
                button.setChecked(opcode in values)
            self._select_opcode_tab(opcode)
        finally:
            self._loading = False
        self._validate()

    def _select_opcode_tab(self, opcode: int) -> None:
        if 0x00 <= opcode <= 0x26 or opcode == 0x36:
            self.tabs.setCurrentIndex(0)
        elif opcode in (0x17, 0x37) or 0x27 <= opcode <= 0x2F or opcode >= 0x6B:
            self.tabs.setCurrentIndex(1)
        else:
            self.tabs.setCurrentIndex(2)

    def _parameters_changed(self, *_args) -> None:
        if not self._loading:
            self._validate()

    def current_raw(self) -> bytes:
        opcode = self._current_opcode | (0x80 if self.terminal.isChecked() else 0)
        return bytes((opcode, *(spin.value() for spin in self.parameters[: self._slot_length - 1])))

    def _validate(self) -> None:
        try:
            raw = self.current_raw()
            length = ChapterEventCodec.instruction_length(raw[0], raw, 0)
            if length != self._slot_length:
                raise ValueError(
                    f"所选指令需要 {length} 字节，当前槽位为 {self._slot_length} 字节。"
                )
        except (IndexError, ValueError) as error:
            self.status.setText(str(error))
            self.status.setStyleSheet("color: #b42318;")
            self.buttons.button(QDialogButtonBox.StandardButton.Ok).setEnabled(False)
            return
        changed = raw != self._raw
        self.status.setText(
            f"{'有尚未确认的改动' if changed else '与当前工程一致'} · "
            f"{raw.hex(' ').upper()}"
        )
        self.status.setStyleSheet("color: #b45309;" if changed else "color: #18794e;")
        self.buttons.button(QDialogButtonBox.StandardButton.Ok).setEnabled(True)

    def _open_code_editor(self) -> None:
        dialog = EventCodeDialog(self.current_raw(), self._slot_length, self)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            self._load_raw(dialog.raw())

    def _copy(self) -> None:
        QApplication.clipboard().setText(self.current_raw().hex(" ").upper())

    def _paste(self) -> None:
        try:
            raw = EventCodeDialog.parse_hex(QApplication.clipboard().text())
            if len(raw) != self._slot_length:
                raise ValueError(
                    f"当前槽位固定为 {self._slot_length} 字节，不能粘贴 {len(raw)} 字节。"
                )
            length = ChapterEventCodec.instruction_length(raw[0], raw, 0)
            if length != len(raw):
                raise ValueError(f"粘贴内容不是一条完整的 {len(raw)} 字节指令。")
        except (IndexError, ValueError) as error:
            QMessageBox.warning(self, "无法粘贴事件指令", str(error))
            return
        self._load_raw(raw)

    def raw(self) -> bytes:
        return self.current_raw()
