from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QComboBox,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QPushButton,
    QSplitter,
    QTableWidget,
    QTableWidgetItem,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from fc_editor.dc_text import dc_map_label

from .pages import ProjectPage, page_title, readonly_item


class PersuasionPage(ProjectPage):
    """Editor for the four verified persuasion match records."""

    def __init__(self) -> None:
        super().__init__()
        self.current_slot: int | None = None

        layout = QVBoxLayout(self)
        title, subtitle = page_title(
            "劝降条件",
            "修改哪一关、由谁劝说谁；成功后执行的脚本保持原地址不变。",
        )
        layout.addWidget(title)
        layout.addWidget(subtitle)
        scope_note = QLabel("全局劝降规则表：每条规则独立指定所在关卡、劝说者与目标。切换其他页的关卡不会改变这里的选择。")
        scope_note.setWordWrap(True)
        scope_note.setObjectName("hintText")
        layout.addWidget(scope_note)

        splitter = QSplitter()
        self.table = QTableWidget(0, 6)
        self.table.setHorizontalHeaderLabels(
            ("槽位", "章节", "劝说者", "目标", "脚本地址", "原始字节")
        )
        self.table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QTableWidget.SelectionMode.SingleSelection)
        self.table.setAlternatingRowColors(True)
        self.table.setColumnHidden(4, True)
        self.table.setColumnHidden(5, True)
        header = self.table.horizontalHeader()
        for column in (0, 4, 5):
            header.setSectionResizeMode(column, QHeaderView.ResizeMode.ResizeToContents)
        for column in (1, 2, 3):
            header.setSectionResizeMode(column, QHeaderView.ResizeMode.Stretch)
        self.table.itemSelectionChanged.connect(self._selection_changed)
        splitter.addWidget(self.table)

        editor = QWidget()
        editor_layout = QVBoxLayout(editor)
        group = QGroupBox("规则编辑")
        form = QFormLayout(group)
        self.slot_value = QLabel("—")
        self.script_value = QLabel("—")
        self.chapter = QComboBox()
        for scenario_id in range(0x20):
            self.chapter.addItem(
                f"${scenario_id:02X} · {dc_map_label(scenario_id)}", scenario_id
            )
        self.persuader = QComboBox()
        self.target = QComboBox()
        self.raw_value = QLabel("—")
        self.raw_value.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextSelectableByMouse
        )
        form.addRow("规则槽位", self.slot_value)
        form.addRow("所在章节", self.chapter)
        form.addRow("劝说者", self.persuader)
        form.addRow("被劝说目标", self.target)
        self.pending_state = QLabel("请选择劝降条件")
        self.pending_state.setObjectName("pendingBanner")
        form.addRow("编辑状态", self.pending_state)
        editor_layout.addWidget(group)
        self.advanced_toggle = QToolButton()
        self.advanced_toggle.setText("显示脚本地址与原始字节（高级）")
        self.advanced_toggle.setCheckable(True)
        self.advanced_toggle.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        self.advanced_toggle.setArrowType(Qt.ArrowType.RightArrow)
        self.advanced_panel = QGroupBox("规则原始信息（只读）")
        advanced_form = QFormLayout(self.advanced_panel)
        advanced_form.addRow("成功脚本", self.script_value)
        advanced_form.addRow("原始3字节", self.raw_value)
        self.advanced_panel.hide()
        self.advanced_toggle.toggled.connect(self._toggle_advanced)

        buttons = QHBoxLayout()
        self.apply_button = QPushButton("应用劝降条件")
        self.apply_button.setObjectName("primaryButton")
        self.reset_button = QPushButton("还原此条")
        self.apply_button.clicked.connect(self._apply)
        self.reset_button.clicked.connect(self._reset)
        buttons.addWidget(self.apply_button)
        buttons.addWidget(self.reset_button)
        editor_layout.addLayout(buttons)
        editor_layout.addWidget(self.advanced_toggle)
        editor_layout.addWidget(self.advanced_panel)

        note = QLabel(
            "已确认原ROM有4条可用规则。其余28个表槽位只是占位，"
            "没有独立安全脚本，修改器不会把它们伪装成可用事件。"
        )
        note.setObjectName("hintText")
        note.setWordWrap(True)
        editor_layout.addWidget(note)
        editor_layout.addStretch()
        splitter.addWidget(editor)
        splitter.setStretchFactor(0, 3)
        splitter.setStretchFactor(1, 2)
        layout.addWidget(splitter, 1)

        self.chapter.currentIndexChanged.connect(self._update_raw_preview)
        self.persuader.currentIndexChanged.connect(self._update_raw_preview)
        self.target.currentIndexChanged.connect(self._update_raw_preview)
        self._set_enabled(False)

    def _toggle_advanced(self, checked: bool) -> None:
        self.advanced_panel.setVisible(checked)
        self.table.setColumnHidden(4, not checked)
        self.table.setColumnHidden(5, not checked)
        self.advanced_toggle.setArrowType(
            Qt.ArrowType.DownArrow if checked else Qt.ArrowType.RightArrow
        )

    def _set_enabled(self, enabled: bool) -> None:
        for widget in (
            self.chapter,
            self.persuader,
            self.target,
            self.reset_button,
        ):
            widget.setEnabled(enabled)
        if not enabled:
            self.apply_button.setEnabled(False)

    @staticmethod
    def _select_data(combo: QComboBox, value: int) -> None:
        index = combo.findData(value)
        combo.setCurrentIndex(index if index >= 0 else 0)

    def _character_label(self, character_id: int) -> str:
        assert self.project is not None
        return (
            f"${character_id:02X} · "
            f"{self.project.character_display_name(character_id)}"
        )

    def refresh(self) -> None:
        previous = self.current_slot
        self.current_slot = None
        self.table.blockSignals(True)
        self.table.setRowCount(0)
        for combo in (self.persuader, self.target):
            combo.blockSignals(True)
            combo.clear()
        if self.project is None or not self.project.supports_persuasion_rules:
            for combo in (self.persuader, self.target):
                combo.blockSignals(False)
            self.table.blockSignals(False)
            self._set_enabled(False)
            return

        for character_id in range(1, self.project.profile.character_name_count):
            label = self._character_label(character_id)
            self.persuader.addItem(label, character_id)
            self.target.addItem(label, character_id)
        for combo in (self.persuader, self.target):
            combo.blockSignals(False)

        count = self.project.persuasion_rule_codec.spec.editable_count
        self.table.setRowCount(count)
        selected_row = 0
        for row in range(count):
            rule = self.project.get_persuasion_rule(row)
            values = (
                f"${rule.slot:02X}",
                f"${rule.scenario_id:02X} · {dc_map_label(rule.scenario_id)}",
                self._character_label(rule.persuader_id),
                self._character_label(rule.target_id),
                f"${rule.script_address:04X}",
                rule.raw.hex(" ").upper(),
            )
            for column, value in enumerate(values):
                item = readonly_item(value)
                if column == 0:
                    item.setData(Qt.ItemDataRole.UserRole, row)
                self.table.setItem(row, column, item)
            if row == previous:
                selected_row = row
        self.table.blockSignals(False)
        if count:
            self.table.selectRow(selected_row)
            self._selection_changed()

    def _selection_changed(self) -> None:
        if self.project is None:
            return
        row = self.table.currentRow()
        if row < 0:
            self.current_slot = None
            self._set_enabled(False)
            return
        item = self.table.item(row, 0)
        if item is None:
            return
        next_slot = int(item.data(Qt.ItemDataRole.UserRole))
        if (
            self.current_slot is not None
            and next_slot != self.current_slot
            and self.has_pending_draft
        ):
            target_slot = next_slot
            old_slot = self.current_slot
            self.table.blockSignals(True)
            self.table.selectRow(old_slot)
            self.table.blockSignals(False)
            if not self.commit_pending_changes():
                self.show_error(ValueError("当前劝降条件无法应用，请修正后再切换。"))
                return
            self.table.selectRow(target_slot)
            return
        self.current_slot = next_slot
        rule = self.project.get_persuasion_rule(self.current_slot)
        for combo in (self.chapter, self.persuader, self.target):
            combo.blockSignals(True)
        self._select_data(self.chapter, rule.scenario_id)
        self._select_data(self.persuader, rule.persuader_id)
        self._select_data(self.target, rule.target_id)
        for combo in (self.chapter, self.persuader, self.target):
            combo.blockSignals(False)
        self.slot_value.setText(f"${rule.slot:02X}")
        self.script_value.setText(f"${rule.script_address:04X}")
        self._set_enabled(True)
        self._update_raw_preview()

    def _update_raw_preview(self) -> None:
        values = (
            self.chapter.currentData(),
            self.persuader.currentData(),
            self.target.currentData(),
        )
        if any(value is None for value in values):
            self.raw_value.setText("—")
            self.pending_state.setText("请选择劝降条件")
            self.apply_button.setEnabled(False)
            return
        self.raw_value.setText(" ".join(f"{int(value):02X}" for value in values))
        changed = False
        if self.project is not None and self.current_slot is not None:
            rule = self.project.get_persuasion_rule(self.current_slot)
            changed = tuple(int(value) for value in values) != (
                rule.scenario_id,
                rule.persuader_id,
                rule.target_id,
            )
        self.apply_button.setEnabled(changed)
        self.pending_state.setText(
            "● 当前条件尚未应用" if changed else "✓ 与当前工程一致"
        )

    def _apply(self) -> None:
        if self.project is None or self.current_slot is None:
            return
        try:
            self.project.set_persuasion_rule(
                self.current_slot,
                int(self.chapter.currentData()),
                int(self.persuader.currentData()),
                int(self.target.currentData()),
            )
            self.project_changed.emit(f"已更新劝降规则 ${self.current_slot:02X}")
        except Exception as error:
            self.show_error(error)

    def _reset(self) -> None:
        if self.project is None or self.current_slot is None:
            return
        try:
            self.project.reset_persuasion_rule(self.current_slot)
            self.project_changed.emit(f"已还原劝降规则 ${self.current_slot:02X}")
        except Exception as error:
            self.show_error(error)
