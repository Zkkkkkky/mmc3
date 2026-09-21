from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QApplication,
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
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from fc_editor.codecs.chapter_event import ACTION_FIELDS, ACTION_LABELS
from fc_editor.dc_text import dc_map_label

from .pages import ProjectPage, page_title, readonly_item


EVENT_GROUPS = (
    ("可编辑事件动作", {0x4A, 0x4B, 0x4C, 0x4D, 0x4E, 0x67, 0x68, 0x69, 0x6A, 0x6B, 0x75, 0x76, 0x77}),
    ("触发条件与行动判定", set(range(0x00, 0x1F))),
    ("对白、文字与镜头", set(range(0x40, 0x49))),
    ("增援", {0x4A, 0x4B, 0x4C, 0x75, 0x76, 0x77}),
    ("说得、加入与转化", {0x4D, 0x4E, 0x67, 0x68, 0x69}),
    ("开关、跳转与流程", set(range(0x51, 0x59))),
    ("音乐与等待", set(range(0x59, 0x5F))),
    ("行动控制", set(range(0x60, 0x6D))),
    ("奖励、离队与胜负", {0x4F, 0x50, 0x6D, 0x6E, 0x6F, 0x70, 0x71, 0x72, 0x73}),
    ("自爆、撤退与移除", {0x6A, 0x6B}),
    ("全部指令（专家）", None),
)


TEMPLATES_BY_LENGTH = {
    7: (
        ("客军增援", 0x4A),
        ("敌军增援", 0x4B),
        ("客军增援（扩展别名）", 0x75),
        ("敌军增援（扩展别名）", 0x76),
    ),
    5: (("我方出击/加入", 0x4C), ("我方出击/加入（扩展别名）", 0x77)),
    4: (("替换人物与机体", 0x4D),),
    3: (("更换机体", 0x4E),),
    2: (("正式加入我方（说得/加入）", 0x69),),
    1: (
        ("转为临时友军", 0x67),
        ("转为敌军", 0x68),
        ("当前单位自爆", 0x6A),
        ("移除当前单位", 0x6B),
    ),
}


class EventPage(ProjectPage):
    def __init__(self) -> None:
        super().__init__()
        self.current_address: int | None = None
        self._instructions = ()
        self._filter_state: tuple[int, int, int, str] | None = None
        self._changing_filters = False
        self._template_draft_changed = False
        self._raw_draft_changed = False
        self._raw_draft_invalid = False

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
            self.scenario_filter.addItem(
                f"${scenario_id:02X} · {dc_map_label(scenario_id)}", scenario_id
            )
        self.phase_filter = QComboBox()
        self.phase_filter.addItem("全部阶段", None)
        self.kind_filter = QComboBox()
        for label, opcodes in EVENT_GROUPS:
            self.kind_filter.addItem(label, opcodes)
        self.search = QLineEdit()
        self.search.setPlaceholderText("搜索地址、事件名、参数或章节…")
        self.search.setClearButtonEnabled(True)
        self.result_count = QLabel("0 条")
        self.result_count.setObjectName("countBadge")
        filters.addWidget(QLabel("章节"))
        filters.addWidget(self.scenario_filter)
        filters.addWidget(QLabel("阶段"))
        filters.addWidget(self.phase_filter)
        filters.addWidget(QLabel("类型"))
        filters.addWidget(self.kind_filter)
        filters.addWidget(self.search, 1)
        filters.addWidget(self.result_count)
        layout.addLayout(filters)

        splitter = QSplitter()
        self.table = QTableWidget(0, 5)
        self.table.setHorizontalHeaderLabels(("地址", "章节/阶段", "动作", "参数", "原始字节"))
        self.table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QTableWidget.SelectionMode.SingleSelection)
        self.table.setAlternatingRowColors(True)
        self.table.setColumnHidden(0, True)
        self.table.setColumnHidden(4, True)
        header = self.table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.Interactive)
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(2, QHeaderView.ResizeMode.Interactive)
        header.setSectionResizeMode(3, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(4, QHeaderView.ResizeMode.Interactive)
        self.table.setColumnWidth(0, 76)
        self.table.setColumnWidth(2, 170)
        self.table.setColumnWidth(4, 190)
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
        self.pending_state = QLabel("请选择事件动作")
        self.pending_state.setObjectName("pendingBanner")
        form.addRow("编辑状态", self.pending_state)
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
            value.valueChanged.connect(
                lambda _value, parameter_index=index: self._update_parameter_annotation(
                    parameter_index
                )
            )
            label.hide()
            value.hide()
            form.addRow(label, value)
            self.parameter_labels.append(label)
            self.parameters.append(value)
        self.raw = QLineEdit()
        self.raw.setPlaceholderText("例如：4B 10 08 3D A8 20 03")
        editor_layout.addWidget(details)

        buttons = QHBoxLayout()
        self.apply_template_button = QPushButton("应用模板参数")
        self.apply_raw_button = QPushButton("应用等长原始字节")
        self.reset_button = QPushButton("还原此指令")
        buttons.addWidget(self.apply_template_button)
        buttons.addWidget(self.reset_button)
        editor_layout.addLayout(buttons)
        hint = QLabel(
            "使用方法：先从左侧选择原有槽位，再选相同长度的模板。"
            "“正式加入我方”作用于当前事件上下文选中的单位；增援的六个参数依次为坐标、人物、机体、等级和AI标志。"
        )
        hint.setObjectName("hintText")
        hint.setWordWrap(True)
        editor_layout.addWidget(hint)
        self.advanced_toggle = QToolButton()
        self.advanced_toggle.setText("显示原始字节与地址（高级）")
        self.advanced_toggle.setCheckable(True)
        self.advanced_toggle.setArrowType(Qt.ArrowType.RightArrow)
        self.advanced_toggle.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        self.advanced_panel = QGroupBox("等长原始指令")
        advanced_layout = QVBoxLayout(self.advanced_panel)
        advanced_layout.addWidget(self.raw)
        advanced_buttons = QHBoxLayout()
        self.copy_button = QPushButton("复制当前指令")
        self.paste_button = QPushButton("粘贴为等长草稿")
        self.copy_button.clicked.connect(self.copy_instruction)
        self.paste_button.clicked.connect(self.paste_instruction)
        advanced_buttons.addWidget(self.copy_button)
        advanced_buttons.addWidget(self.paste_button)
        advanced_layout.addLayout(advanced_buttons)
        advanced_layout.addWidget(self.apply_raw_button)
        self.advanced_panel.hide()
        self.advanced_toggle.toggled.connect(self._toggle_advanced)
        editor_layout.addWidget(self.advanced_toggle)
        editor_layout.addWidget(self.advanced_panel)
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

        self.scenario_filter.currentIndexChanged.connect(self._filters_changed)
        self.phase_filter.currentIndexChanged.connect(self._filters_changed)
        self.kind_filter.currentIndexChanged.connect(self._filters_changed)
        self.search.textChanged.connect(self._filters_changed)
        self.table.itemSelectionChanged.connect(self._selection_changed)
        self.template.currentIndexChanged.connect(self._template_changed)
        self.terminal.toggled.connect(self._update_pending_state)
        self.raw.textChanged.connect(self._update_pending_state)
        self.apply_template_button.clicked.connect(self._apply_template)
        self.apply_raw_button.clicked.connect(self._apply_raw)
        self.reset_button.clicked.connect(self._reset_instruction)
        self._filter_state = self._current_filter_state()

    def _toggle_advanced(self, checked: bool) -> None:
        self.advanced_panel.setVisible(checked)
        self.table.setColumnHidden(0, not checked)
        self.table.setColumnHidden(4, not checked)
        self.advanced_toggle.setArrowType(
            Qt.ArrowType.DownArrow if checked else Qt.ArrowType.RightArrow
        )

    def _template_replacement(self, instruction) -> bytes:
        opcode = self.template.currentData()
        raw_opcode = instruction.opcode if opcode is None else int(opcode)
        if self.terminal.isChecked():
            raw_opcode |= 0x80
        count = (
            len(instruction.parameters)
            if opcode is None
            else len(ACTION_FIELDS.get(opcode, ()))
        )
        return bytes((raw_opcode, *(spin.value() for spin in self.parameters[:count])))

    def copy_instruction(self) -> None:
        instruction = self._selected_instruction()
        if instruction is None:
            return
        if self.pending_draft_error:
            self.show_error(ValueError(self.pending_draft_error))
            return
        raw = (
            self._parse_hex(self.raw.text())
            if self._raw_draft_changed
            else self._template_replacement(instruction)
        )
        QApplication.clipboard().setText(raw.hex(" ").upper())

    def paste_instruction(self) -> None:
        instruction = self._selected_instruction()
        if instruction is None or self.project is None:
            return
        try:
            if self.has_pending_draft:
                raise ValueError("当前指令有未应用改动，请先应用或还原，再粘贴。")
            raw = self._parse_hex(QApplication.clipboard().text())
            if len(raw) != len(instruction.raw):
                raise ValueError(f"目标指令为 {len(instruction.raw)} 字节，不能粘贴 {len(raw)} 字节。")
            codec = self.project.chapter_event_codec
            assert codec is not None
            if codec.instruction_length(raw[0], raw, 0) != len(raw):
                raise ValueError("粘贴内容必须恰好是一条等长指令，不能包含后续指令。")
            self.raw.setText(raw.hex(" ").upper())
            self.advanced_toggle.setChecked(True)
        except Exception as error:
            self.show_error(error)

    @staticmethod
    def _context_text(instruction) -> str:
        if not instruction.contexts:
            return "共享/分支块"
        return " / ".join(
            f"${context.scenario_id:02X}·"
            f"{dc_map_label(context.scenario_id)}·{context.label}"
            for context in instruction.contexts
        )

    def _parameter_annotation(self, label: str, value: int) -> str:
        if self.project is None:
            return ""
        if "机体ID" in label:
            if not 1 <= value < self.project.unit_count:
                return "无机体/特殊值" if value == 0 else "超出机体表"
            return self.project.unit_display_name(value)
        if "人物ID" in label:
            return self.project.character_display_name(value)
        return ""

    def _parameter_text(self, instruction) -> str:
        labels = instruction.field_labels
        if labels:
            parts = []
            for label, value in zip(labels, instruction.parameters):
                annotation = self._parameter_annotation(label, value)
                suffix = f"（{annotation}）" if annotation else ""
                parts.append(f"{label}=${value:02X}{suffix}")
            return "，".join(parts)
        return " ".join(f"{value:02X}" for value in instruction.parameters) or "—"

    def _update_parameter_annotation(self, index: int) -> None:
        if index >= len(self.parameter_labels):
            return
        label = self.parameter_labels[index].text()
        spin = self.parameters[index]
        annotation = self._parameter_annotation(label, spin.value())
        spin.setSuffix(f" · {annotation}" if annotation else "")
        self._update_pending_state()

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

    def _current_filter_state(self) -> tuple[int, int, int, str]:
        return (
            self.scenario_filter.currentIndex(),
            self.phase_filter.currentIndex(),
            self.kind_filter.currentIndex(),
            self.search.text(),
        )

    def _set_filter_state(self, state: tuple[int, int, int, str]) -> None:
        controls = (
            self.scenario_filter,
            self.phase_filter,
            self.kind_filter,
            self.search,
        )
        previous_blocks = tuple(control.blockSignals(True) for control in controls)
        try:
            scenario, phase, kind, search = state
            self.scenario_filter.setCurrentIndex(scenario)
            self.phase_filter.setCurrentIndex(phase)
            self.kind_filter.setCurrentIndex(kind)
            self.search.setText(search)
        finally:
            for control, blocked in zip(controls, previous_blocks):
                control.blockSignals(blocked)

    def _restore_filter_state(self) -> None:
        if self._filter_state is not None:
            self._set_filter_state(self._filter_state)

    def _filters_changed(self) -> None:
        if self._changing_filters:
            return
        self._changing_filters = True
        try:
            if self.has_pending_draft:
                requested_state = self._current_filter_state()
                # Restore the old filter before committing.  Applying an event
                # emits a synchronous page refresh; if the requested filter
                # already hid the old row, that refresh could otherwise bind
                # the still-open editor controls to a different instruction.
                self._restore_filter_state()
                error = self.pending_draft_error
                if error is not None or not self.commit_pending_changes():
                    self.show_error(
                        ValueError(
                            error
                            or self.pending_draft_error
                            or "当前事件仍有无法应用的改动，请修正后再筛选。"
                        )
                    )
                    return
                self._set_filter_state(requested_state)
            self._populate_table()
        finally:
            self._changing_filters = False

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
        self.result_count.setText(f"{len(visible)} 条")
        self.table.setUpdatesEnabled(False)
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
        self.table.setUpdatesEnabled(True)
        if selected_row < 0 and visible:
            selected_row = 0
        if selected_row >= 0:
            self.table.selectRow(selected_row)
            self._selection_changed()
        else:
            self.current_address = None
            self._show_instruction(None)
        self._filter_state = self._current_filter_state()

    def _selected_instruction(self):
        rows = self.table.selectionModel().selectedRows()
        if not rows or self.project is None or self.project.chapter_event_codec is None:
            return None
        address = self.table.item(rows[0].row(), 0).data(Qt.ItemDataRole.UserRole)
        return self.project.chapter_event_codec.instruction_at(address, bytes(self.project.working))

    def _selection_changed(self) -> None:
        instruction = self._selected_instruction()
        if (
            instruction is not None
            and self.current_address is not None
            and instruction.address != self.current_address
            and self.has_pending_draft
        ):
            target_address = instruction.address
            old_address = self.current_address
            self.table.blockSignals(True)
            self._select_address(old_address)
            self.table.blockSignals(False)
            if not self.commit_pending_changes():
                self.show_error(
                    ValueError(
                        self.pending_draft_error
                        or "当前事件仍有无法应用的改动，请修正后再切换。"
                    )
                )
                return
            self._select_address(target_address)
            return
        self.current_address = instruction.address if instruction is not None else None
        self._show_instruction(instruction)

    def _select_address(self, address: int) -> bool:
        for row in range(self.table.rowCount()):
            item = self.table.item(row, 0)
            if item is not None and item.data(Qt.ItemDataRole.UserRole) == address:
                self.table.selectRow(row)
                return True
        return False

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
            self.pending_state.setText("请选择事件动作")
        else:
            self.address_value.setText(
                f"${instruction.address:04X} / 文件 0x{instruction.file_offset:X} / {len(instruction.raw)} 字节"
            )
            self.context_value.setText(self._context_text(instruction))
            templates = TEMPLATES_BY_LENGTH.get(len(instruction.raw), ())
            if not templates:
                self.template.addItem("保持当前操作码 · 编辑参数字节", None)
            for label, opcode in templates:
                self.template.addItem(label, opcode)
            current_index = self.template.findData(instruction.opcode)
            if current_index >= 0:
                self.template.setCurrentIndex(current_index)
            elif templates:
                # A same-length template does not imply that the current
                # opcode is one of the verified actions.  Keep an explicit
                # lossless choice selected so simply opening the dialog never
                # manufactures a pending replacement for an unknown opcode.
                self.template.insertItem(0, "保持当前原始指令", None)
                self.template.setCurrentIndex(0)
            self.terminal.setChecked(instruction.is_terminal)
            self.raw.setText(instruction.raw.hex(" ").upper())
        self.template.blockSignals(False)
        self._update_parameter_controls(instruction)
        self._update_pending_state()

    def _update_parameter_controls(self, instruction) -> None:
        opcode = self.template.currentData()
        if opcode is None and instruction is not None:
            opcode = instruction.opcode
        labels = ACTION_FIELDS.get(opcode, ())
        values = instruction.parameters if instruction is not None else ()
        if not labels and opcode is not None and instruction is not None:
            labels = tuple(f"原始参数 {index + 1}（语义未验证）" for index in range(len(values)))
        for index, (label_widget, spin) in enumerate(
            zip(self.parameter_labels, self.parameters)
        ):
            visible = index < len(labels)
            label_widget.setVisible(visible)
            spin.setVisible(visible)
            if visible:
                label_widget.setText(labels[index])
                spin.setValue(values[index] if index < len(values) else 0)
                self._update_parameter_annotation(index)
            else:
                spin.setSuffix("")
        self.apply_template_button.setEnabled(instruction is not None and bool(labels) or (
            instruction is not None and opcode in {0x67, 0x68, 0x6A, 0x6B}
        ))

    def _template_changed(self) -> None:
        instruction = self._selected_instruction()
        self._update_parameter_controls(instruction)
        self._update_pending_state()

    def _update_pending_state(self) -> None:
        instruction = self._selected_instruction()
        if instruction is None:
            self._template_draft_changed = False
            self._raw_draft_changed = False
            self._raw_draft_invalid = False
            self.pending_state.setText("请选择事件动作")
            self.apply_template_button.setEnabled(False)
            self.apply_raw_button.setEnabled(False)
            return
        template_raw = self._template_replacement(instruction)
        try:
            raw_editor = self._parse_hex(self.raw.text())
            raw_valid = len(raw_editor) == len(instruction.raw)
        except ValueError:
            raw_editor = b""
            raw_valid = False
        template_valid = len(template_raw) == len(instruction.raw)
        template_changed = template_valid and template_raw != instruction.raw
        raw_changed = raw_valid and raw_editor != instruction.raw
        raw_invalid = not raw_valid
        raw_dirty = raw_changed or raw_invalid
        pending = template_changed or raw_dirty
        self._template_draft_changed = template_changed
        self._raw_draft_changed = raw_dirty
        self._raw_draft_invalid = raw_invalid
        self.apply_template_button.setEnabled(template_changed)
        self.apply_raw_button.setEnabled(raw_changed)
        if not raw_valid:
            self.pending_state.setText(
                f"● 原始字节必须保持 {len(instruction.raw)} 字节；当前输入不可应用"
            )
            self.pending_state.setStyleSheet("color: #b42318; font-weight: 650;")
        else:
            self.pending_state.setText(
                "● 当前参数尚未应用" if pending else "✓ 与当前工程一致"
            )
            self.pending_state.setStyleSheet(
                "color: #b45309; font-weight: 650;"
                if pending
                else "color: #2e7d4f;"
            )

    @property
    def has_pending_draft(self) -> bool:
        return self.pending_state.text().startswith("●")

    @property
    def pending_draft_error(self) -> str | None:
        if not self.has_pending_draft:
            return None
        if self._raw_draft_invalid:
            return self.pending_state.text().lstrip("● ")
        if self._template_draft_changed and self._raw_draft_changed:
            return "模板参数和原始字节同时有改动，请先明确应用其中一种。"
        instruction = self._selected_instruction()
        if instruction is not None and self.project is not None:
            raw = (
                self._parse_hex(self.raw.text())
                if self._raw_draft_changed
                else self._template_replacement(instruction)
            )
            codec = self.project.chapter_event_codec
            assert codec is not None
            try:
                length = codec.instruction_length(raw[0], raw, 0)
                if length != len(instruction.raw):
                    return f"新指令需要 {length} 字节，必须保持原槽 {len(instruction.raw)} 字节。"
            except (ValueError, IndexError) as error:
                return str(error)
        return None

    def commit_pending_changes(self) -> bool:
        if not self.has_pending_draft:
            return True
        if self.pending_draft_error is not None:
            return False
        assert self.project is not None
        before = bytes(self.project.working)
        button = (
            self.apply_template_button
            if self.apply_template_button.isEnabled()
            else self.apply_raw_button
        )
        button.click()
        if bytes(self.project.working) != before and self.has_pending_draft:
            self.refresh()
        return not self.has_pending_draft

    def _apply_template(self) -> None:
        instruction = self._selected_instruction()
        if instruction is None or self.project is None:
            return
        replacement = self._template_replacement(instruction)
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
