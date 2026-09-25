from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QGridLayout,
    QGroupBox,
    QLabel,
    QLineEdit,
    QMenu,
    QPushButton,
    QSpinBox,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from fc_editor.codecs.legacy_text import decode_legacy_text

from fc_editor.codecs.chapter_event import (
    ACTION_FIELDS,
    INSTRUCTION_LENGTHS,
    OPCODE_HELP,
    OPCODE_LABELS,
    ChapterEventCodec,
)


REFERENCE_EVENT_MUSIC_LABELS = (
    "大卫音乐", "盖塔音乐", "加代音乐", "古莲音乐", "吉尔变身音乐",
    "安东音乐", "未知音乐2", "地球我方音乐", "地球敌方音乐", "存档音乐",
    "敌方增援音乐2", "游戏结束音乐", "宇宙我方音乐", "敌方增援音乐1",
    "升级音乐", "吉尔音乐", "瓦尔音乐", "宇宙敌方音乐", "未知音乐1",
    "通关音乐",
)


class ByteChoiceCombo(QComboBox):
    """A byte-valued, named selector with the same value API as QSpinBox."""

    def value(self) -> int:
        value = self.currentData()
        return 0 if value is None else int(value)

    def setValue(self, value: int) -> None:
        index = self.findData(value & 0xFF)
        if index >= 0:
            self.setCurrentIndex(index)


def _parameter_kind(label: str) -> str:
    """Classify only operands whose non-numeric meaning is verified."""

    if "人物" in label and "数量" not in label:
        return "character"
    if "头像" in label:
        return "portrait"
    if "机体ID" in label:
        return "unit"
    if "道具ID" in label:
        return "item"
    if "音乐命令" in label:
        return "music"
    if "动画ID" in label:
        return "animation"
    if "精神效果ID" in label:
        return "spirit"
    if "文本组" in label:
        return "text_group"
    if "文本编号" in label:
        return "text_record"
    if "事件开关" in label or "开关与状态" in label:
        return "switch"
    if "限制代码" in label:
        return "restriction"
    if "窗口样式/位置" in label:
        return "window_style"
    if "队伍槽" in label:
        return "roster_slot"
    if "队伍/成长参数" in label:
        return "roster"
    if "运算方式" in label or "置数/增加/减少" in label:
        return "operation"
    if "设置/取消" in label:
        return "set_clear"
    if "攻击/击落" in label:
        return "attack_result"
    if any(token in label for token in ("标志", "状态", "位掩码")):
        return "flags"
    return "number"


def _bit_description(value: int, noun: str) -> str:
    if value == 0:
        return f"未设置{noun}"
    bits = "、".join(str(index + 1) for index in range(8) if value & (1 << index))
    return f"第 {bits} 位为 1"


def _choice_text(project, kind: str, value: int) -> str:
    prefix = f"${value:02X} · "
    if kind == "character":
        if project is not None:
            return prefix + project.character_display_name(value)
        return prefix + ("无人物/特殊上下文" if value == 0 else f"人物 {value}")
    if kind == "portrait":
        if project is not None:
            return prefix + project.character_display_name(value)
        return prefix + ("无头像" if value == 0 else f"头像 {value}")
    if kind == "unit":
        if project is not None and 0 < value < project.unit_count:
            return prefix + project.unit_display_name(value)
        return prefix + ("无机体/特殊值" if value == 0 else "未分配机体值")
    if kind == "item":
        if project is not None:
            try:
                names = project.get_item_name_records()
                if 1 <= value <= len(names):
                    return prefix + decode_legacy_text(names[value - 1])
            except (AttributeError, IndexError, ValueError):
                pass
        return prefix + ("无道具" if value == 0 else f"道具 {value}")
    if kind == "music":
        index = value - 0x81
        if 0 <= index < len(REFERENCE_EVENT_MUSIC_LABELS):
            return prefix + REFERENCE_EVENT_MUSIC_LABELS[index]
        return prefix + "未命名/特殊音乐命令"
    if kind == "animation":
        return prefix + f"战场动画 {value}"
    if kind == "spirit":
        return prefix + f"精神效果 {value}"
    if kind == "text_group":
        return prefix + f"剧情文字组 ${value + 0x30:02X}"
    if kind == "text_record":
        return prefix + f"组内第 {value} 条文字"
    if kind == "switch":
        scope = "全局" if value & 0x80 else "本关"
        return prefix + f"{scope}开关 {value & 0x0F}"
    if kind == "restriction":
        return prefix + _bit_description(value, "移动限制")
    if kind == "window_style":
        known = {0x00: "默认文字窗", 0x0B: "扩展文字窗（带附加参数）", 0x0C: "扩展文字窗（带附加参数）"}
        return prefix + known.get(value, "参考版窗口样式/位置值")
    if kind == "roster_slot":
        return prefix + ("自动选择我方槽位" if value == 0 else f"我方队伍槽 {value}")
    if kind == "roster":
        return prefix + _bit_description(value, "队伍/成长状态")
    if kind == "operation":
        known = {0x00: "置数", 0x01: "增加", 0x02: "减少"}
        return prefix + known.get(value, "组合运算/偏移值")
    if kind == "set_clear":
        return prefix + {0x00: "取消", 0x01: "设置"}.get(value, "参考版组合状态")
    if kind == "attack_result":
        return prefix + {0x00: "攻击", 0x01: "击落"}.get(value, "参考版攻击结果")
    if kind == "flags":
        return prefix + _bit_description(value, "状态")
    return prefix + str(value)


def _make_parameter_editor(project, label: str, value: int, parent=None):
    kind = _parameter_kind(label)
    if kind == "number":
        editor = QSpinBox(parent)
        editor.setRange(0, 255)
        editor.setDisplayIntegerBase(10)
        editor.setValue(value)
        editor.setToolTip(f"ROM 原始值：${value:02X}")
        return editor
    editor = ByteChoiceCombo(parent)
    editor.setMaxVisibleItems(24)
    editor.setMinimumContentsLength(24)
    for candidate in range(256):
        editor.addItem(_choice_text(project, kind, candidate), candidate)
    editor.setValue(value)
    return editor


def parameter_labels(opcode: int, parameter_count: int) -> tuple[str, ...]:
    """Return verified labels where available and lossless labels otherwise."""

    labels = ACTION_FIELDS.get(opcode, ())
    if len(labels) <= parameter_count:
        return labels + tuple(
            f"附加参数 {index + 1}（原码）"
            for index in range(parameter_count - len(labels))
        )
    return tuple(f"参数 {index + 1}（原码）" for index in range(parameter_count))


class EventParameterDialog(QDialog):
    """Edit one existing instruction without mixing in the insert palette.

    The reference modifier uses two different surfaces: its three-page command
    palette chooses a new instruction, while right-click ``编辑`` opens only the
    selected instruction's parameters.  Keeping that distinction is especially
    useful for beginners because editing a value cannot accidentally replace the
    command itself.
    """

    def __init__(
        self,
        raw: bytes,
        parent=None,
        *,
        title: str = "事件参数修改",
        context: str = "",
        project=None,
    ) -> None:
        super().__init__(parent)
        if not raw:
            raise ValueError("事件指令不能为空。")
        self._original = bytes(raw)
        self._opcode = raw[0] & 0x7F
        self._project = project or getattr(parent, "project", None)
        self._loading = False
        self.setWindowTitle(title)
        self.setMinimumWidth(520)

        layout = QVBoxLayout(self)
        if context:
            context_label = QLabel(context)
            context_label.setObjectName("hintText")
            context_label.setWordWrap(True)
            layout.addWidget(context_label)

        heading = QLabel(
            f"${self._opcode:02X} · "
            f"{OPCODE_LABELS.get(self._opcode, '未知指令')}"
        )
        heading.setObjectName("eventParameterCommandName")
        heading.setStyleSheet("font-weight: 650;")
        layout.addWidget(heading)

        help_label = QLabel(
            OPCODE_HELP.get(
                self._opcode,
                "参考修改器尚未给出可靠含义；这里只按原始字节编辑，不猜测用途。",
            )
        )
        help_label.setObjectName("hintText")
        help_label.setWordWrap(True)
        layout.addWidget(help_label)

        parameter_group = QGroupBox(OPCODE_LABELS.get(self._opcode, "参数修改"))
        form = QFormLayout(parameter_group)
        self.terminal = QCheckBox("指令结束")
        self.terminal.setToolTip("与旧修改器相同：勾选后，该指令执行完即结束当前事件组。")
        form.addRow("事件结束", self.terminal)
        self.parameter_labels: list[QLabel] = []
        self.parameters: list[QSpinBox | ByteChoiceCombo] = []
        labels = parameter_labels(self._opcode, len(raw) - 1)
        for index, label_text in enumerate(labels):
            label = QLabel(label_text)
            editor = _make_parameter_editor(
                self._project, label_text, raw[index + 1], self
            )
            editor.setObjectName(f"eventParameter{index + 1}")
            if isinstance(editor, QSpinBox):
                editor.valueChanged.connect(self._validate)
            else:
                editor.currentIndexChanged.connect(self._validate)
            form.addRow(label, editor)
            self.parameter_labels.append(label)
            self.parameters.append(editor)
        layout.addWidget(parameter_group)

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

        self.terminal.setChecked(bool(raw[0] & 0x80))
        self.terminal.toggled.connect(self._validate)
        self._validate()

    def _validate(self, *_args) -> None:
        if self._loading:
            return
        raw = self.raw()
        changed = raw != self._original
        self.status.setText(
            f"{'有尚未确认的改动' if changed else '与当前工程一致'} · "
            f"{raw.hex(' ').upper()}"
        )
        self.status.setStyleSheet("color: #b45309;" if changed else "color: #18794e;")

    def raw(self) -> bytes:
        opcode = self._opcode | (0x80 if self.terminal.isChecked() else 0)
        return bytes((opcode, *(editor.value() for editor in self.parameters)))


class EventCodeDialog(QDialog):
    """Reference-shaped small hexadecimal editor used by the instruction dialog."""

    def __init__(self, raw: bytes, expected_length: int | None, parent=None) -> None:
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
            if self.expected_length is not None and len(raw) != self.expected_length:
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
    """Legacy three-page *insert* palette.

    The legacy modifier does not embed the currently selected instruction below
    this palette.  Choosing a command opens that command's parameter window;
    only the separate right-click ``编辑`` action opens the existing command.
    """

    TRIGGER_GROUPS = (
        ("触发条件1", (
            ("00回合判定", (0x00,)), ("01开关判定", (0x01,)),
            ("02人物移动限制代码判断", (0x02,)), ("03某人在队伍中判断", (0x03,)),
            ("04某人是否在战场中判断", (0x04,)), ("05某人是否进入母舰中判断", (0x05,)),
            ("06敌方人数判断", (0x06,)), ("07我方人数判断", (0x07,)),
        )),
        ("触发条件2", (
            ("08道具数量判断", (0x08,)), ("09某人剩余HP判断", (0x09,)),
            ("0A剩余金钱判断", (0x0A,)), ("0B待机数量判断", (0x0B,)),
            ("0C某人进入坐标判断", (0x0C,)), ("0D当前人物行动限制判断", (0x0D,)),
            ("0E与某人距离判断（行动）", (0x0E,)), ("0F进入某坐标判断（行动）", (0x0F,)),
            ("10进入某范围判断（行动）", (0x10,)), ("11周围有无敌方判断（行动）", (0x11,)),
            ("12剩余HP判断（行动）", (0x12,)),
        )),
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
        ("执行事件5", (
            ("6B离开战场（行动）", (0x6B,)),
            ("6C刷新移动坐标（行动）", (0x6C,)),
            ("6D获得金钱和经验（行动）", (0x6D,)),
            ("6E我方离队", (0x6E,)),
            ("6F加入我方队伍", (0x6F,)),
        )),
        ("执行事件6", (
            ("70设置胜利文字", (0x70,)),
            ("71过关（进入下一关）", (0x71,)),
            ("72失败（游戏结束）", (0x72,)),
            ("73通关（进入通关界面）", (0x73,)),
            ("DF事件结束", (0xDF,)),
        )),
        ("执行事件7", (("74机体被击破", (0x74,)),)),
    )

    def __init__(
        self,
        raw: bytes,
        parent=None,
        *,
        title: str = "事件指令编辑",
        context: str = "",
        allow_variable_length: bool = False,
        project=None,
    ) -> None:
        super().__init__(parent)
        if not raw:
            raise ValueError("事件指令不能为空。")
        self._slot_length = len(raw)
        self._allow_variable_length = allow_variable_length
        self._preset = bytes(raw)
        self._selected_raw: bytes | None = None
        self._project = project or getattr(parent, "project", None)
        self.opcode_buttons: dict[int, QPushButton] = {}
        self._button_opcodes: dict[QPushButton, tuple[int, ...]] = {}
        self.setWindowTitle(title)
        self.resize(700, 560)
        self.setMinimumSize(650, 480)

        layout = QVBoxLayout(self)
        if context:
            context_label = QLabel(context)
            context_label.setObjectName("hintText")
            context_label.setWordWrap(True)
            layout.addWidget(context_label)

        self.tabs = QTabWidget()
        self.tabs.setObjectName("legacyEventInstructionTabs")
        self.tabs.addTab(self._command_page(self.TRIGGER_GROUPS), "1")
        self.tabs.addTab(self._command_page(self.ACTION_GROUPS), "2")
        self.tabs.addTab(self._command_page(self.ADVANCED_GROUPS), "3")
        layout.addWidget(self.tabs, 1)

        hint = QLabel("选择要插入的事件指令；随后只显示该指令的参数窗口。")
        hint.setObjectName("hintText")
        layout.addWidget(hint)
        self.buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Cancel)
        self.buttons.button(QDialogButtonBox.StandardButton.Cancel).setText("取消")
        self.buttons.rejected.connect(self.reject)
        layout.addWidget(self.buttons)

    def _command_page(self, groups) -> QWidget:
        page = QWidget()
        page_layout = QGridLayout(page)
        for group_index, (title, entries) in enumerate(groups):
            group = QGroupBox(title)
            grid = QGridLayout(group)
            for index, (label, opcodes) in enumerate(entries):
                button = QPushButton(label)
                button.setCheckable(True)
                button.setMinimumHeight(23)
                compatible_opcodes = tuple(
                    opcode for opcode in opcodes
                    if opcode == 0xDF or INSTRUCTION_LENGTHS[opcode] > 0 or opcode == 0x43
                )
                compatible = bool(compatible_opcodes)
                button.setEnabled(compatible)
                if compatible:
                    button.clicked.connect(
                        lambda _checked=False, values=compatible_opcodes, source=button:
                        self._choose_opcode_group(values, source)
                    )
                else:
                    button.setToolTip("该指令尚未完成可靠解码。")
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
        candidate = self._default_raw(opcode)
        if opcode == 0xDF:
            self._selected_raw = candidate
            self.accept()
            return
        dialog = EventParameterDialog(
            candidate,
            self,
            title="事件结束" if opcode == 0xDF else OPCODE_LABELS.get(opcode, "事件参数修改"),
            context=f"插入指令 ${opcode:02X}",
            project=self._project,
        )
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        self._selected_raw = dialog.raw()
        self.accept()

    def _default_raw(self, opcode: int) -> bytes:
        if opcode == 0xDF:
            return b"\xDF"
        target_length = 2 if opcode == 0x43 else INSTRUCTION_LENGTHS[opcode]
        if target_length <= 0:
            raise ValueError(f"指令 ${opcode:02X} 的长度尚未确认。")
        if (self._preset[0] & 0x7F) == opcode and len(self._preset) == target_length:
            return self._preset
        return bytes((opcode,)) + bytes(target_length - 1)

    def _select_opcode_tab(self, opcode: int) -> None:
        if 0x00 <= opcode <= 0x26 or opcode == 0x36:
            self.tabs.setCurrentIndex(0)
        elif opcode >= 0x6B:
            self.tabs.setCurrentIndex(2)
        else:
            self.tabs.setCurrentIndex(1)

    def raw(self) -> bytes:
        if self._selected_raw is None:
            raise ValueError("尚未选择要插入的事件指令。")
        return self._selected_raw
