from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QSpinBox,
    QSplitter,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from fc_editor.codecs.chapter_event import ACTION_FIELDS, ACTION_LABELS

from .pages import ProjectPage, page_title, readonly_item


EVENT_GROUPS = (
    ("可编辑事件动作", {0x4A, 0x4B, 0x4C, 0x4D, 0x4E, 0x67, 0x68, 0x69, 0x6A, 0x6B, 0x75, 0x76, 0x77}),
    ("增援", {0x4A, 0x4B, 0x4C, 0x75, 0x76, 0x77}),
    ("说得、加入与转化", {0x4D, 0x4E, 0x67, 0x68, 0x69}),
    ("撤退与移除", {0x6A, 0x6B}),
    ("全部指令（专家）", None),
)


TEMPLATES_BY_LENGTH = {
    7: (("客军增援", 0x4A), ("敌军增援", 0x4B)),
    5: (("我方出击/加入", 0x4C),),
    4: (("替换人物与机体", 0x4D),),
    3: (("更换机体", 0x4E),),
    2: (("正式加入我方（说得/加入）", 0x69),),
    1: (
        ("转为临时友军", 0x67),
        ("转为敌军", 0x68),
        ("撤退并保留镜头目标", 0x6A),
        ("移除当前单位", 0x6B),
    ),
}


class EventPage(ProjectPage):
    def __init__(self) -> None:
        super().__init__()
        self.current_address: int | None = None
        self._instructions = ()

        layout = QVBoxLayout(self)
        title, subtitle = page_title(
            "战场事件",
            "按章节筛选并修改增援、我方加入、说得转化和撤退。所有编辑保持原指令长度，不移动脚本指针。",
        )
        layout.addWidget(title)
        layout.addWidget(subtitle)

        filters = QHBoxLayout()
        self.scenario_filter = QComboBox()
        self.scenario_filter.addItem("全部章节", None)
        for scenario_id in range(0x20):
            self.scenario_filter.addItem(f"章节 ${scenario_id:02X}", scenario_id)
        self.phase_filter = QComboBox()
        self.phase_filter.addItem("全部阶段", None)
        self.kind_filter = QComboBox()
        for label, opcodes in EVENT_GROUPS:
            self.kind_filter.addItem(label, opcodes)
        self.search = QLineEdit()
        self.search.setPlaceholderText("搜索地址、事件名、参数或章节…")
        self.search.setClearButtonEnabled(True)
        filters.addWidget(QLabel("章节"))
        filters.addWidget(self.scenario_filter)
        filters.addWidget(QLabel("阶段"))
        filters.addWidget(self.phase_filter)
        filters.addWidget(QLabel("类型"))
        filters.addWidget(self.kind_filter)
        filters.addWidget(self.search, 1)
        layout.addLayout(filters)

        splitter = QSplitter()
        self.table = QTableWidget(0, 5)
        self.table.setHorizontalHeaderLabels(("地址", "章节/阶段", "动作", "参数", "原始字节"))
        self.table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QTableWidget.SelectionMode.SingleSelection)
        self.table.setAlternatingRowColors(True)
        header = self.table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(3, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(4, QHeaderView.ResizeMode.ResizeToContents)
        splitter.addWidget(self.table)

        editor = QWidget()
        editor_layout = QVBoxLayout(editor)
        details = QGroupBox("事件动作编辑器")
        form = QFormLayout(details)
        self.address_value = QLabel("—")
        self.address_value.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self.context_value = QLabel("—")
        self.context_value.setWordWrap(True)
        self.template = QComboBox()
        self.terminal = QCheckBox("结束本事件组（操作码高位）")
        form.addRow("脚本地址", self.address_value)
        form.addRow("章节归属", self.context_value)
        form.addRow("兼容模板", self.template)
        form.addRow("执行控制", self.terminal)
        self.parameter_labels: list[QLabel] = []
        self.parameters: list[QSpinBox] = []
        for index in range(7):
            label = QLabel(f"参数 {index + 1}")
            value = QSpinBox()
            value.setRange(0, 255)
            value.setDisplayIntegerBase(16)
            value.setPrefix("$")
            label.hide()
            value.hide()
            form.addRow(label, value)
            self.parameter_labels.append(label)
            self.parameters.append(value)
        self.raw = QLineEdit()
        self.raw.setPlaceholderText("例如：4B 10 08 3D A8 20 03")
        form.addRow("等长原始字节", self.raw)
        editor_layout.addWidget(details)

        buttons = QHBoxLayout()
        self.apply_template_button = QPushButton("应用模板参数")
        self.apply_raw_button = QPushButton("应用等长原始字节")
        self.reset_button = QPushButton("还原此指令")
        buttons.addWidget(self.apply_template_button)
        buttons.addWidget(self.apply_raw_button)
        buttons.addWidget(self.reset_button)
        editor_layout.addLayout(buttons)
        hint = QLabel(
            "使用方法：先从左侧选择原有槽位，再选相同长度的模板。"
            "“正式加入我方”作用于当前事件上下文选中的单位；增援的六个参数依次为坐标、机体、人物、等级和AI标志。"
        )
        hint.setObjectName("hintText")
        hint.setWordWrap(True)
        editor_layout.addWidget(hint)
        safety = QLabel(
            "安全边界：原脚本区已接近 8 KiB 上限，本页不插入或删除字节。专家模式可修改其余触发器和动作，但新操作码也必须与原槽等长。"
        )
        safety.setWordWrap(True)
        safety.setStyleSheet("color: #9a5b00;")
        editor_layout.addWidget(safety)
        editor_layout.addStretch()
        splitter.addWidget(editor)
        splitter.setStretchFactor(0, 3)
        splitter.setStretchFactor(1, 2)
        layout.addWidget(splitter, 1)

        self.scenario_filter.currentIndexChanged.connect(self._populate_table)
        self.phase_filter.currentIndexChanged.connect(self._populate_table)
        self.kind_filter.currentIndexChanged.connect(self._populate_table)
        self.search.textChanged.connect(self._populate_table)
        self.table.itemSelectionChanged.connect(self._selection_changed)
        self.template.currentIndexChanged.connect(self._template_changed)
        self.apply_template_button.clicked.connect(self._apply_template)
        self.apply_raw_button.clicked.connect(self._apply_raw)
        self.reset_button.clicked.connect(self._reset_instruction)

    @staticmethod
    def _context_text(instruction) -> str:
        if not instruction.contexts:
            return "共享/分支块"
        return " / ".join(
            f"${context.scenario_id:02X}·{context.label}"
            for context in instruction.contexts
        )

    @staticmethod
    def _parameter_text(instruction) -> str:
        labels = instruction.field_labels
        if labels:
            return "，".join(
                f"{label}=${value:02X}"
                for label, value in zip(labels, instruction.parameters)
            )
        return " ".join(f"{value:02X}" for value in instruction.parameters) or "—"

    def refresh(self) -> None:
        self.phase_filter.blockSignals(True)
        previous_phase = self.phase_filter.currentData()
        self.phase_filter.clear()
        self.phase_filter.addItem("全部阶段", None)
        if self.project is not None and self.project.chapter_event_codec is not None:
            for phase, label in enumerate(self.project.chapter_event_codec.spec.phase_labels):
                self.phase_filter.addItem(label, phase)
            index = self.phase_filter.findData(previous_phase)
            self.phase_filter.setCurrentIndex(max(0, index))
            self._instructions = self.project.chapter_event_instructions()
        else:
            self._instructions = ()
        self.phase_filter.blockSignals(False)
        self._populate_table()

    def _visible_instructions(self):
        scenario_id = self.scenario_filter.currentData()
        phase = self.phase_filter.currentData()
        opcodes = self.kind_filter.currentData()
        query = self.search.text().strip().lower()
        for instruction in self._instructions:
            if opcodes is not None and instruction.opcode not in opcodes:
                continue
            if scenario_id is not None and not any(
                context.scenario_id == scenario_id for context in instruction.contexts
            ):
                continue
            if phase is not None and not any(
                context.phase == phase for context in instruction.contexts
            ):
                continue
            haystack = " ".join(
                (
                    f"{instruction.address:04x}",
                    self._context_text(instruction).lower(),
                    instruction.action_label.lower(),
                    self._parameter_text(instruction).lower(),
                    instruction.raw.hex(" "),
                )
            )
            if query and query not in haystack:
                continue
            yield instruction

    def _populate_table(self) -> None:
        previous = self.current_address
        visible = tuple(self._visible_instructions())
        self.table.blockSignals(True)
        self.table.setRowCount(len(visible))
        selected_row = -1
        for row, instruction in enumerate(visible):
            address = readonly_item(f"${instruction.address:04X}")
            address.setData(Qt.ItemDataRole.UserRole, instruction.address)
            self.table.setItem(row, 0, address)
            self.table.setItem(row, 1, readonly_item(self._context_text(instruction)))
            self.table.setItem(row, 2, readonly_item(instruction.action_label))
            self.table.setItem(row, 3, readonly_item(self._parameter_text(instruction)))
            self.table.setItem(row, 4, readonly_item(instruction.raw.hex(" ").upper()))
            if instruction.address == previous:
                selected_row = row
        self.table.blockSignals(False)
        if selected_row < 0 and visible:
            selected_row = 0
        if selected_row >= 0:
            self.table.selectRow(selected_row)
            self._selection_changed()
        else:
            self.current_address = None
            self._show_instruction(None)

    def _selected_instruction(self):
        rows = self.table.selectionModel().selectedRows()
        if not rows or self.project is None or self.project.chapter_event_codec is None:
            return None
        address = self.table.item(rows[0].row(), 0).data(Qt.ItemDataRole.UserRole)
        return self.project.chapter_event_codec.instruction_at(address, bytes(self.project.working))

    def _selection_changed(self) -> None:
        instruction = self._selected_instruction()
        self.current_address = instruction.address if instruction is not None else None
        self._show_instruction(instruction)

    def _show_instruction(self, instruction) -> None:
        enabled = instruction is not None
        self.apply_template_button.setEnabled(enabled)
        self.apply_raw_button.setEnabled(enabled)
        self.reset_button.setEnabled(enabled)
        self.template.blockSignals(True)
        self.template.clear()
        if instruction is None:
            self.address_value.setText("—")
            self.context_value.setText("—")
            self.raw.clear()
            self.terminal.setChecked(False)
            self.template.addItem("无可用指令", None)
        else:
            self.address_value.setText(
                f"${instruction.address:04X} / 文件 0x{instruction.file_offset:X} / {len(instruction.raw)} 字节"
            )
            self.context_value.setText(self._context_text(instruction))
            templates = TEMPLATES_BY_LENGTH.get(len(instruction.raw), ())
            if not templates:
                self.template.addItem("仅可使用原始字节编辑", None)
            for label, opcode in templates:
                self.template.addItem(label, opcode)
            current_index = self.template.findData(instruction.opcode)
            if current_index >= 0:
                self.template.setCurrentIndex(current_index)
            self.terminal.setChecked(instruction.is_terminal)
            self.raw.setText(instruction.raw.hex(" ").upper())
        self.template.blockSignals(False)
        self._update_parameter_controls(instruction)

    def _update_parameter_controls(self, instruction) -> None:
        opcode = self.template.currentData()
        if opcode is None and instruction is not None:
            opcode = instruction.opcode
        labels = ACTION_FIELDS.get(opcode, ())
        values = instruction.parameters if instruction is not None else ()
        for index, (label_widget, spin) in enumerate(
            zip(self.parameter_labels, self.parameters)
        ):
            visible = index < len(labels)
            label_widget.setVisible(visible)
            spin.setVisible(visible)
            if visible:
                label_widget.setText(labels[index])
                spin.setValue(values[index] if index < len(values) else 0)
        self.apply_template_button.setEnabled(instruction is not None and bool(labels) or (
            instruction is not None and opcode in {0x67, 0x68, 0x6A, 0x6B}
        ))

    def _template_changed(self) -> None:
        instruction = self._selected_instruction()
        self._update_parameter_controls(instruction)

    def _apply_template(self) -> None:
        instruction = self._selected_instruction()
        opcode = self.template.currentData()
        if instruction is None or opcode is None or self.project is None:
            return
        labels = ACTION_FIELDS.get(opcode, ())
        raw_opcode = opcode | (0x80 if self.terminal.isChecked() else 0)
        replacement = bytes((raw_opcode, *(spin.value() for spin in self.parameters[: len(labels)])))
        try:
            self.project.set_chapter_event_instruction(instruction.address, replacement)
        except Exception as error:
            self.show_error(error)
            return
        self.project_changed.emit(f"已更新章节事件 ${instruction.address:04X}")

    @staticmethod
    def _parse_hex(text: str) -> bytes:
        compact = text.replace(",", " ").replace("0x", "").replace("$", "")
        tokens = compact.split()
        if not tokens:
            raise ValueError("请输入十六进制字节。")
        try:
            values = bytes(int(token, 16) for token in tokens)
        except ValueError as error:
            raise ValueError("原始字节必须是 00—FF 的十六进制数。") from error
        return values

    def _apply_raw(self) -> None:
        instruction = self._selected_instruction()
        if instruction is None or self.project is None:
            return
        try:
            replacement = self._parse_hex(self.raw.text())
            self.project.set_chapter_event_instruction(instruction.address, replacement)
        except Exception as error:
            self.show_error(error)
            return
        self.project_changed.emit(f"已更新章节事件 ${instruction.address:04X}")

    def _reset_instruction(self) -> None:
        instruction = self._selected_instruction()
        if instruction is None or self.project is None:
            return
        try:
            self.project.reset_chapter_event_instruction(instruction.address)
        except Exception as error:
            self.show_error(error)
            return
        self.project_changed.emit(f"已还原章节事件 ${instruction.address:04X}")
