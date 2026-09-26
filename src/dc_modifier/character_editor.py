from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QImage, QPixmap
from PySide6.QtWidgets import (
    QCheckBox, QFileDialog, QFormLayout, QGridLayout, QGroupBox, QHBoxLayout,
    QComboBox, QDialog, QDialogButtonBox, QHeaderView, QLabel, QLineEdit,
    QListWidget, QMenu, QMessageBox, QPushButton, QSpinBox, QSizePolicy, QTableWidget,
    QTableWidgetItem, QTabWidget, QVBoxLayout, QWidget,
)

from fc_editor.codecs.character_attributes import (
    CharacterAttributes, CharacterAttributesCodec, PortraitRecord, SPIRIT_NAMES,
    apply_verified_patches,
)
from fc_editor.codecs.character_dialogue import (
    CharacterDialogueRecord, DialogueBinding, DialogueRule,
    TransformDialogueBinding, VALID_SEGMENTS,
)
from fc_editor.codecs.legacy_text import LegacyTextCodec
from .database_graphics import palette_color
from .map_page import NesColorButton
from .portrait_export import PORTRAIT_BACKGROUND_PALETTE_NES


def legacy_portrait_selectors(record: PortraitRecord) -> tuple[int, int, int, int]:
    """Return the four selectors with the reference editor's 1-based slots."""

    return (
        record.front_bank,
        record.front_slot + 1,
        record.back_bank,
        record.back_slot + 1,
    )


class LegacyValueCombo(QComboBox):
    """Reference-style selector with the QSpinBox API used by old tests."""

    valueChanged = Signal(int)

    def __init__(self, minimum: int, maximum: int, formatter, parent=None) -> None:
        super().__init__(parent)
        for value in range(minimum, maximum + 1):
            self.addItem(formatter(value), value)
        self.currentIndexChanged.connect(
            lambda _index: self.valueChanged.emit(self.value())
        )

    def value(self) -> int:
        return int(self.currentData())

    def setValue(self, value: int) -> None:
        index = self.findData(int(value))
        if index >= 0:
            self.setCurrentIndex(index)


class NesColorField(NesColorButton):
    """NES swatch with a QSpinBox-compatible value API."""

    valueChanged = Signal(int)

    def __init__(self, value: int = 0, parent=None) -> None:
        super().__init__(value, parent)
        self.value_changed.connect(self.valueChanged.emit)
        self.setMinimumSize(72, 30)

    def value(self) -> int:
        return self._value

    def setValue(self, value: int) -> None:
        self.set_value(value)


class SpiritCostDialog(QDialog):
    def __init__(self, name: str, value: int, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("精神修改")
        self.setFixedSize(472, 155)
        root = QGridLayout(self)
        name_field = QLineEdit(name)
        name_field.setReadOnly(True)
        name_field.setToolTip("精神名称来自参考配置；本窗口只修改ROM中的全局消耗值。")
        self.cost = QSpinBox()
        self.cost.setRange(0, 255)
        self.cost.setValue(value)
        root.addWidget(QLabel("精神名称："), 0, 0)
        root.addWidget(name_field, 0, 1)
        root.addWidget(QLabel("精神消耗："), 1, 0)
        root.addWidget(self.cost, 1, 1)
        ok = QPushButton("确定")
        cancel = QPushButton("取消")
        ok.setFixedSize(110, 32)
        cancel.setFixedSize(110, 32)
        ok.clicked.connect(self.accept)
        cancel.clicked.connect(self.reject)
        root.addWidget(ok, 0, 2)
        root.addWidget(cancel, 1, 2)
        root.setColumnStretch(1, 1)


class SpiritCheckBox(QCheckBox):
    editRequested = Signal()

    def mouseDoubleClickEvent(self, event) -> None:
        self.editRequested.emit()
        event.accept()


def dialogue_preview(
    project, segment: int, dialogue: int, codec: LegacyTextCodec | None = None
) -> str:
    """Return a compact real-text preview without creating any widgets."""

    try:
        key = {
            0x00: "battle_00",
            0x01: "battle_01",
            0x04: "battle_04",
            0x05: "battle_05",
            0x07: "system",
        }[segment]
        text = (codec or LegacyTextCodec(project.working)).record(
            key, dialogue
        ).text
        return text.replace("\n", " ").replace("⟦结束⟧", "").strip() or "空文本"
    except (AttributeError, IndexError, KeyError, ValueError):
        return "未定义/不可读"


class DialogueBindingDialog(QDialog):
    """Reference-shaped picker for one battle-dialogue binding."""

    SEGMENT_LABELS = {
        0x00: "00 · 进攻战斗对话",
        0x01: "01 · 进攻特殊对话",
        0x04: "04 · 防御战斗对话",
        0x05: "05 · 防御特殊对话",
        0x07: "07 · 系统文字",
    }

    def __init__(
        self, project, segment: int, dialogue: int, parent=None,
        *, text_codec: LegacyTextCodec | None = None,
        title: str = "防御对话",
    ) -> None:
        super().__init__(parent)
        self.project = project
        self.text_codec = text_codec or LegacyTextCodec(project.working)
        self.setWindowTitle(title)
        self.setFixedSize(578, 160)
        root = QVBoxLayout(self)
        group = QGroupBox("文字段")
        row = QHBoxLayout(group)
        self.segment = QComboBox()
        for value in VALID_SEGMENTS:
            self.segment.addItem(f"{value:02X}", value)
        self.segment.setFixedWidth(92)
        self.dialogue = QComboBox()
        self.dialogue.setMinimumWidth(390)
        self.segment.currentIndexChanged.connect(self._load_dialogues)
        row.addWidget(self.segment)
        row.addWidget(self.dialogue, 1)
        root.addWidget(group)
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok
            | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.button(QDialogButtonBox.StandardButton.Ok).setText("确定")
        buttons.button(QDialogButtonBox.StandardButton.Cancel).setText("取消")
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        root.addWidget(buttons)
        self.segment.setCurrentIndex(self.segment.findData(segment))
        self._load_dialogues()
        index = self.dialogue.findData(dialogue)
        self.dialogue.setCurrentIndex(max(0, index))

    def _preview(self, segment: int, dialogue: int) -> str:
        return dialogue_preview(
            self.project, segment, dialogue, self.text_codec
        )

    def _load_dialogues(self, *_args) -> None:
        previous = self.dialogue.currentData()
        segment = int(self.segment.currentData())
        count = 0x10 if segment == 0x01 else 0x40 if segment == 0x05 else 0xDD if segment == 0x07 else 0x100
        self.dialogue.clear()
        for value in range(count):
            self.dialogue.addItem(
                f"[{value:02X}]{value:03d}： {self._preview(segment, value)}", value
            )
        if previous is not None:
            index = self.dialogue.findData(previous)
            if index >= 0:
                self.dialogue.setCurrentIndex(index)

    def binding(self) -> DialogueBinding:
        return DialogueBinding(
            int(self.segment.currentData()), int(self.dialogue.currentData())
        )


class RuleConditionDialog(QDialog):
    """Named selectors for the two polymorphic legacy condition bytes."""

    def __init__(self, project, actor: int, weapon: int, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("特殊攻击条件")
        form = QFormLayout(self)
        self.actor = QComboBox()
        self.weapon = QComboBox()
        for value in range(0x100):
            try:
                character_name = project.character_display_name(value)
            except (IndexError, ValueError):
                character_name = "—"
            try:
                unit_name = project.unit_display_name(value)
            except (IndexError, ValueError):
                unit_name = "—"
            try:
                weapon_name = project.weapon_display_name(value)
            except (IndexError, ValueError):
                weapon_name = "—"
            self.actor.addItem(
                f"${value:02X} · 人物 {character_name} / 机体 {unit_name}", value
            )
            self.weapon.addItem(
                f"${value:02X} · 武器 {weapon_name} / 机体 {unit_name}", value
            )
        self.actor.setCurrentIndex(self.actor.findData(actor))
        self.weapon.setCurrentIndex(self.weapon.findData(weapon))
        form.addRow("人物/机体条件", self.actor)
        form.addRow("武器/机体条件", self.weapon)
        hint = QLabel(
            "旧格式会按规则类型把同一字节解释为人物或机体、武器或机体；"
            "因此同时显示两种名称，保存仍保持原始编号。"
        )
        hint.setWordWrap(True)
        form.addRow(hint)
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok
            | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        form.addRow(buttons)

    def values(self) -> tuple[int, int]:
        return int(self.actor.currentData()), int(self.weapon.currentData())


class DialogueRuleDialog(QDialog):
    """Reference-shaped editor for one special battle-dialogue rule."""

    MODE_LABELS = ("我方武器限制", "敌方人物限制", "敌方机体限制")

    def __init__(
        self, project, group: int, rule: DialogueRule, parent=None,
        *, text_codec: LegacyTextCodec | None = None,
    ) -> None:
        super().__init__(parent)
        self.project = project
        self.text_codec = text_codec or LegacyTextCodec(project.working)
        self.setWindowTitle("攻击对话")
        self.setFixedSize(560, 494)
        root = QVBoxLayout(self)
        self.raw_list = QListWidget()
        self.raw_list.addItem(
            "01："
            f"{rule.actor_or_unit:02X} {rule.weapon_or_unit:02X} "
            f"{rule.segment:02X} {rule.dialogue:02X} "
        )
        self.raw_list.setCurrentRow(0)
        root.addWidget(self.raw_list, 1)

        limits = QGroupBox("特殊对话限制（起始至终止）")
        limit_layout = QGridLayout(limits)
        self.mode = QComboBox()
        for index, label in enumerate(self.MODE_LABELS):
            self.mode.addItem(label, index)
        self.start = QComboBox()
        self.end = QComboBox()
        limit_layout.addWidget(self.mode, 0, 0, 1, 2)
        limit_layout.addWidget(self.start, 1, 0)
        limit_layout.addWidget(self.end, 1, 1)
        root.addWidget(limits)

        text_group = QGroupBox("文字段")
        text_layout = QHBoxLayout(text_group)
        self.segment = QComboBox()
        for value in VALID_SEGMENTS:
            self.segment.addItem(f"{value:02X}", value)
        self.segment.setFixedWidth(92)
        self.dialogue = QComboBox()
        text_layout.addWidget(self.segment)
        text_layout.addWidget(self.dialogue, 1)
        root.addWidget(text_group)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok
            | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.button(QDialogButtonBox.StandardButton.Ok).setText("确定")
        buttons.button(QDialogButtonBox.StandardButton.Cancel).setText("取消")
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        root.addWidget(buttons)

        self.mode.currentIndexChanged.connect(self._load_limits)
        self.segment.currentIndexChanged.connect(self._load_dialogues)
        self.mode.setCurrentIndex(max(0, min(2, group)))
        self._load_limits()
        self.start.setCurrentIndex(self.start.findData(rule.actor_or_unit))
        self.end.setCurrentIndex(self.end.findData(rule.weapon_or_unit))
        self.segment.setCurrentIndex(self.segment.findData(rule.segment))
        self._load_dialogues()
        self.dialogue.setCurrentIndex(self.dialogue.findData(rule.dialogue))

    def _load_limits(self, *_args) -> None:
        old_start, old_end = self.start.currentData(), self.end.currentData()
        self.start.clear()
        self.end.clear()
        mode = int(self.mode.currentData())
        for value in range(0x100):
            try:
                if mode == 0:
                    name = self.project.weapon_display_name(value)
                elif mode == 1:
                    name = self.project.character_display_name(value)
                else:
                    name = self.project.unit_display_name(value)
            except (IndexError, KeyError, ValueError):
                name = ""
            label = f"[{value:02X}]{value:03d}：{name}"
            self.start.addItem(label, value)
            self.end.addItem(label, value)
        for combo, previous in ((self.start, old_start), (self.end, old_end)):
            if previous is not None and combo.findData(previous) >= 0:
                combo.setCurrentIndex(combo.findData(previous))

    def _load_dialogues(self, *_args) -> None:
        previous = self.dialogue.currentData()
        segment = int(self.segment.currentData())
        count = 0x10 if segment == 0x01 else 0x40 if segment == 0x05 else 0xDD if segment == 0x07 else 0x100
        self.dialogue.clear()
        for value in range(count):
            self.dialogue.addItem(
                f"[{value:02X}]{value:03d}： "
                f"{dialogue_preview(self.project, segment, value, self.text_codec)}",
                value,
            )
        if previous is not None and self.dialogue.findData(previous) >= 0:
            self.dialogue.setCurrentIndex(self.dialogue.findData(previous))

    def result_value(self) -> tuple[int, DialogueRule]:
        return int(self.mode.currentData()), DialogueRule(
            int(self.start.currentData()), int(self.end.currentData()),
            int(self.segment.currentData()), int(self.dialogue.currentData()),
        )


class DialogueRuleGroupDialog(QDialog):
    """Reference attack-dialogue window with list and editor in one dialog."""

    MODE_LABELS = DialogueRuleDialog.MODE_LABELS

    def __init__(
        self, project, group: int, rules: list[DialogueRule], parent=None,
        *, text_codec: LegacyTextCodec | None = None,
    ) -> None:
        super().__init__(parent)
        self.project = project
        self.text_codec = text_codec or LegacyTextCodec(project.working)
        self._rules = list(rules) or [DialogueRule(0x00, 0x00, 0x00, 0x00)]
        self._current_row = -1
        self._loading = False
        self.setWindowTitle("攻击对话")
        self.setFixedSize(560, 494)

        root = QVBoxLayout(self)
        root.setContentsMargins(6, 6, 6, 6)
        root.setSpacing(5)
        self.raw_list = QListWidget()
        self.raw_list.setContextMenuPolicy(
            Qt.ContextMenuPolicy.CustomContextMenu
        )
        self.raw_list.setFixedHeight(216)
        self.raw_list.setToolTip("选择一条规则后在下方修改；右键可新增或删除规则。")
        root.addWidget(self.raw_list, 1)

        limits = QGroupBox("特殊对话限制（起始至终止）")
        limit_layout = QGridLayout(limits)
        self.mode = QComboBox()
        for index, label in enumerate(self.MODE_LABELS):
            self.mode.addItem(label, index)
        self.start = QComboBox()
        self.end = QComboBox()
        limit_layout.addWidget(self.mode, 0, 0, 1, 2)
        limit_layout.addWidget(self.start, 1, 0)
        limit_layout.addWidget(self.end, 1, 1)
        root.addWidget(limits)

        text_group = QGroupBox("文字段")
        text_layout = QHBoxLayout(text_group)
        self.segment = QComboBox()
        for value in VALID_SEGMENTS:
            self.segment.addItem(f"{value:02X}", value)
        self.segment.setFixedWidth(92)
        self.dialogue = QComboBox()
        text_layout.addWidget(self.segment)
        text_layout.addWidget(self.dialogue, 1)
        root.addWidget(text_group)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok
            | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.button(QDialogButtonBox.StandardButton.Ok).setText("确定")
        buttons.button(QDialogButtonBox.StandardButton.Cancel).setText("取消")
        buttons.accepted.connect(self._accept)
        buttons.rejected.connect(self.reject)
        root.addWidget(buttons)

        self.mode.currentIndexChanged.connect(self._mode_changed)
        self.start.currentIndexChanged.connect(self._field_changed)
        self.end.currentIndexChanged.connect(self._field_changed)
        self.segment.currentIndexChanged.connect(self._segment_changed)
        self.dialogue.currentIndexChanged.connect(self._field_changed)
        self.raw_list.currentRowChanged.connect(self._select_row)
        self.raw_list.customContextMenuRequested.connect(self._show_rule_menu)

        self._loading = True
        self.mode.setCurrentIndex(max(0, min(2, group)))
        self._load_limits()
        self._loading = False
        self._refresh_raw_list()
        self.raw_list.setCurrentRow(0)

    @staticmethod
    def _raw_text(index: int, rule: DialogueRule) -> str:
        return (
            f"{index + 1:02d}: {rule.actor_or_unit:02X} "
            f"{rule.weapon_or_unit:02X} {rule.segment:02X} {rule.dialogue:02X}"
        )

    def _refresh_raw_list(self) -> None:
        current = self.raw_list.currentRow()
        self.raw_list.blockSignals(True)
        self.raw_list.clear()
        for index, rule in enumerate(self._rules):
            self.raw_list.addItem(self._raw_text(index, rule))
        self.raw_list.blockSignals(False)
        if self._rules:
            self.raw_list.setCurrentRow(min(max(0, current), len(self._rules) - 1))

    def _load_limits(self) -> None:
        old_start, old_end = self.start.currentData(), self.end.currentData()
        self.start.blockSignals(True)
        self.end.blockSignals(True)
        self.start.clear()
        self.end.clear()
        mode = int(self.mode.currentData())
        for value in range(0x100):
            try:
                if mode == 0:
                    name = self.project.weapon_display_name(value)
                elif mode == 1:
                    name = self.project.character_display_name(value)
                else:
                    name = self.project.unit_display_name(value)
            except (IndexError, KeyError, ValueError):
                name = ""
            label = f"[{value:02X}]{value:03d}：{name}"
            self.start.addItem(label, value)
            self.end.addItem(label, value)
        for combo, previous in ((self.start, old_start), (self.end, old_end)):
            index = combo.findData(previous)
            combo.setCurrentIndex(index if index >= 0 else 0)
        self.start.blockSignals(False)
        self.end.blockSignals(False)

    def _load_dialogues(self, selected: int | None = None) -> None:
        previous = self.dialogue.currentData() if selected is None else selected
        self.dialogue.blockSignals(True)
        self.dialogue.clear()
        segment = int(self.segment.currentData())
        count = (
            0x10 if segment == 0x01 else 0x40 if segment == 0x05
            else 0xDD if segment == 0x07 else 0x100
        )
        for value in range(count):
            self.dialogue.addItem(
                f"[{value:02X}]{value:03d}： "
                f"{dialogue_preview(self.project, segment, value, self.text_codec)}",
                value,
            )
        index = self.dialogue.findData(previous)
        self.dialogue.setCurrentIndex(index if index >= 0 else 0)
        self.dialogue.blockSignals(False)

    def _select_row(self, row: int) -> None:
        if self._loading or row < 0 or row >= len(self._rules):
            return
        self._store_current()
        self._current_row = row
        rule = self._rules[row]
        self._loading = True
        self.start.setCurrentIndex(self.start.findData(rule.actor_or_unit))
        self.end.setCurrentIndex(self.end.findData(rule.weapon_or_unit))
        self.segment.setCurrentIndex(self.segment.findData(rule.segment))
        self._load_dialogues(rule.dialogue)
        self._loading = False

    def _store_current(self) -> None:
        if self._current_row < 0 or self._loading:
            return
        values = (
            self.start.currentData(), self.end.currentData(),
            self.segment.currentData(), self.dialogue.currentData(),
        )
        if any(value is None for value in values):
            return
        self._rules[self._current_row] = DialogueRule(
            *(int(value) for value in values)
        )
        item = self.raw_list.item(self._current_row)
        if item is not None:
            item.setText(self._raw_text(
                self._current_row, self._rules[self._current_row]
            ))

    def _field_changed(self, *_args) -> None:
        if not self._loading:
            self._store_current()

    def _segment_changed(self, *_args) -> None:
        if self._loading:
            return
        self._load_dialogues()
        self._store_current()

    def _mode_changed(self, *_args) -> None:
        if self._loading:
            return
        self._loading = True
        self._load_limits()
        if self._current_row >= 0:
            rule = self._rules[self._current_row]
            self.start.setCurrentIndex(self.start.findData(rule.actor_or_unit))
            self.end.setCurrentIndex(self.end.findData(rule.weapon_or_unit))
        self._loading = False

    def _show_rule_menu(self, position) -> None:
        menu = QMenu(self)
        add = menu.addAction("新增规则")
        remove = menu.addAction("删除规则")
        remove.setEnabled(len(self._rules) > 1 and self.raw_list.currentRow() >= 0)
        chosen = menu.exec(self.raw_list.mapToGlobal(position))
        if chosen is add:
            self._store_current()
            self._rules.append(DialogueRule(0x00, 0x00, 0x00, 0x00))
            self._refresh_raw_list()
            self.raw_list.setCurrentRow(len(self._rules) - 1)
        elif chosen is remove:
            row = self.raw_list.currentRow()
            if row >= 0 and len(self._rules) > 1:
                del self._rules[row]
                self._current_row = -1
                self._refresh_raw_list()
                self.raw_list.setCurrentRow(min(row, len(self._rules) - 1))

    def _accept(self) -> None:
        self._store_current()
        self.accept()

    def result_values(self) -> tuple[int, tuple[DialogueRule, ...]]:
        self._store_current()
        return int(self.mode.currentData()), tuple(self._rules)


class TransformDialogueDialog(QDialog):
    """Reference-shaped transform/launch dialogue binding editor."""

    def __init__(
        self, project, binding: TransformDialogueBinding, parent=None,
        *, text_codec: LegacyTextCodec | None = None,
    ) -> None:
        super().__init__(parent)
        self.project = project
        self.character_id = binding.character_id
        self.text_codec = text_codec or LegacyTextCodec(project.working)
        self.setWindowTitle("防御对话")
        self.setFixedSize(560, 230)
        root = QVBoxLayout(self)
        limits = QGroupBox("机体限定（起点至终点）")
        limit_layout = QHBoxLayout(limits)
        self.start = QComboBox()
        self.end = QComboBox()
        for value in range(0x100):
            try:
                name = project.unit_display_name(value)
            except (IndexError, ValueError):
                name = ""
            label = f"[{value:02X}]{value:03d}：{name}"
            self.start.addItem(label, value)
            self.end.addItem(label, value)
        self.start.setCurrentIndex(self.start.findData(binding.unit_start))
        self.end.setCurrentIndex(self.end.findData(binding.unit_end))
        limit_layout.addWidget(self.start)
        limit_layout.addWidget(self.end)
        root.addWidget(limits)

        text_group = QGroupBox("文字段")
        text_layout = QHBoxLayout(text_group)
        segment = QComboBox()
        segment.addItem("05", 0x05)
        segment.setEnabled(False)
        segment.setFixedWidth(92)
        self.dialogue = QComboBox()
        for value in range(0x40):
            self.dialogue.addItem(
                f"[{value:02X}]{value:03d}： "
                f"{dialogue_preview(project, 0x05, value, self.text_codec)}",
                value,
            )
        self.dialogue.setCurrentIndex(self.dialogue.findData(binding.dialogue))
        text_layout.addWidget(segment)
        text_layout.addWidget(self.dialogue, 1)
        root.addWidget(text_group)
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok
            | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.button(QDialogButtonBox.StandardButton.Ok).setText("确定")
        buttons.button(QDialogButtonBox.StandardButton.Cancel).setText("取消")
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        root.addWidget(buttons)

    def binding(self) -> TransformDialogueBinding:
        return TransformDialogueBinding(
            self.character_id, int(self.start.currentData()),
            int(self.end.currentData()), int(self.dialogue.currentData()),
        )


class CharacterDialogueWidget(QGroupBox):
    changed = Signal()

    DIRECT_LABELS = (
        "无力反击", "攻击受阻", "防御成功", "未受损伤",
        "轻微损伤", "中度损伤", "重度损伤", "被击落",
    )
    RULE_LABELS = ("一次攻击", "二次攻击", "三次攻击")
    REFERENCE_ATTACK_LABELS = (
        "一次攻击", "二次攻击", "可以反击", "无力反击", "攻击受阻"
    )

    def __init__(self) -> None:
        super().__init__()
        self.setFlat(True)
        self.project = None
        self.character_id = None
        self.codec = None
        self._baseline = None
        self._text_codec = None
        self._loading = False
        outer = QGridLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setHorizontalSpacing(5)
        outer.setVerticalSpacing(4)
        self.status = QLabel(
            "文字段与对话编号指向“战斗对话”页正文；特殊攻击保留现有规则条数。"
        )
        self.status.setObjectName("hintText")
        self.status.setWordWrap(True)
        self.status.setToolTip(self.status.text())
        self.status.hide()
        tabs = QTabWidget()
        self.tabs = tabs
        tabs.hide()

        attack_group = QGroupBox("攻击对话")
        self.attack_group = attack_group
        attack_grid = QGridLayout(attack_group)
        attack_grid.setContentsMargins(7, 9, 7, 7)
        attack_grid.setHorizontalSpacing(5)
        attack_grid.setVerticalSpacing(3)

        defense_group = QGroupBox("防御对话")
        self.defense_group = defense_group
        defense_grid = QGridLayout(defense_group)
        defense_grid.setContentsMargins(7, 9, 7, 7)
        defense_grid.setHorizontalSpacing(5)
        defense_grid.setVerticalSpacing(3)

        direct_page = QWidget()
        grid = QGridLayout(direct_page)
        grid.setContentsMargins(4, 4, 4, 4)
        grid.setHorizontalSpacing(4)
        grid.setVerticalSpacing(2)
        self.direct_controls: list[tuple[QComboBox, QSpinBox]] = []
        self.direct_buttons: list[QPushButton] = []
        for index, label in enumerate(self.DIRECT_LABELS):
            segment = QComboBox(direct_page)
            segment.setMinimumWidth(0)
            segment.setSizePolicy(
                QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Fixed
            )
            for value in VALID_SEGMENTS:
                segment.addItem(f"文字段 ${value:02X}", value)
            dialogue = QSpinBox(direct_page)
            dialogue.setRange(0, 0xFF)
            dialogue.setPrefix("$")
            dialogue.setDisplayIntegerBase(16)
            segment.currentIndexChanged.connect(self._changed)
            dialogue.valueChanged.connect(self._changed)
            segment.hide()
            dialogue.hide()
            choose = QPushButton()
            choose.setMinimumWidth(0)
            choose.setSizePolicy(
                QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Fixed
            )
            choose.setObjectName(f"character_dialogue_{index}")
            choose.setToolTip("点击选择文字组，并按实际正文预览选择台词。")
            choose.clicked.connect(
                lambda _checked=False, row=index: self._choose_direct_dialogue(row)
            )
            if index < 2:
                row = index + 3
                attack_grid.addWidget(
                    QLabel(self.REFERENCE_ATTACK_LABELS[row]), row, 0
                )
                attack_grid.addWidget(choose, row, 1)
            else:
                row = index - 2
                defense_grid.addWidget(QLabel(label), row, 0)
                defense_grid.addWidget(choose, row, 1)
            self.direct_controls.append((segment, dialogue))
            self.direct_buttons.append(choose)
        tabs.addTab(direct_page, "直接台词（2攻/6防）")

        self.rule_tables: list[QTableWidget] = []
        self.rule_buttons: list[QPushButton] = []
        for group_index, label in enumerate(self.RULE_LABELS):
            page = QWidget()
            page_layout = QVBoxLayout(page)
            page_layout.setContentsMargins(4, 4, 4, 4)
            table = QTableWidget(0, 4)
            table.setHorizontalHeaderLabels(
                ("人物/机体条件", "武器/机体条件", "文字段", "对话编号")
            )
            table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
            table.verticalHeader().setVisible(False)
            table.cellChanged.connect(self._changed)
            table.cellDoubleClicked.connect(
                lambda _row, _column, group=group_index: self._edit_rule(group)
            )
            self.rule_tables.append(table)
            rule_button = QPushButton()
            rule_button.setMinimumWidth(0)
            rule_button.setSizePolicy(
                QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Fixed
            )
            rule_button.setObjectName(f"character_dialogue_rule_{group_index}")
            rule_button.setToolTip("点击编辑这一类攻击台词的全部条件规则。")
            rule_button.clicked.connect(
                lambda _checked=False, group=group_index: self._manage_rule_group(group)
            )
            attack_grid.addWidget(
                QLabel(self.REFERENCE_ATTACK_LABELS[group_index]), group_index, 0
            )
            attack_grid.addWidget(rule_button, group_index, 1)
            self.rule_buttons.append(rule_button)
            page_layout.addWidget(table)
            rule_actions = QHBoxLayout()
            add_rule = QPushButton("新增规则")
            edit_condition = QPushButton("编辑条件…")
            edit_rule = QPushButton("选择台词…")
            remove_rule = QPushButton("删除选中规则")
            add_rule.clicked.connect(
                lambda _checked=False, group=group_index: self._add_rule(group)
            )
            edit_condition.clicked.connect(
                lambda _checked=False, group=group_index: self._choose_rule_condition(group)
            )
            edit_rule.clicked.connect(
                lambda _checked=False, group=group_index: self._choose_rule_dialogue(group)
            )
            remove_rule.clicked.connect(
                lambda _checked=False, group=group_index: self._remove_rule(group)
            )
            rule_actions.addWidget(add_rule)
            rule_actions.addWidget(edit_condition)
            rule_actions.addWidget(edit_rule)
            rule_actions.addWidget(remove_rule)
            rule_actions.addStretch()
            page_layout.addLayout(rule_actions)
            tabs.addTab(page, label)

        transform_page = QWidget()
        transform_layout = QVBoxLayout(transform_page)
        transform_layout.setContentsMargins(4, 4, 4, 4)
        self.transform_table = QTableWidget(0, 3)
        self.transform_table.setHorizontalHeaderLabels(
            ("起始机体", "终止机体", "05 段对话编号")
        )
        self.transform_table.horizontalHeader().setSectionResizeMode(
            QHeaderView.ResizeMode.Stretch
        )
        self.transform_table.verticalHeader().setVisible(False)
        self.transform_table.cellChanged.connect(self._changed)
        self.transform_table.cellDoubleClicked.connect(
            lambda _row, _column: self._edit_transform()
        )
        transform_layout.addWidget(self.transform_table)
        buttons = QHBoxLayout()
        add = QPushButton("添加变形台词绑定")
        remove = QPushButton("清空选中绑定")
        add.clicked.connect(self._add_transform)
        remove.clicked.connect(self._remove_transform)
        buttons.addWidget(add)
        buttons.addWidget(remove)
        buttons.addStretch()
        transform_layout.addLayout(buttons)
        hint = QLabel(
            "正文使用“战斗对话”页的 05 · 防御特殊对话；这里编辑人物、机体范围和正文编号。"
        )
        hint.setObjectName("hintText")
        hint.setWordWrap(True)
        transform_layout.addWidget(hint)
        tabs.addTab(transform_page, "变形起飞")

        transform_group = QGroupBox("变形起飞对话")
        self.transform_group = transform_group
        transform_row = QHBoxLayout(transform_group)
        transform_row.setContentsMargins(7, 9, 7, 7)
        transform_row.setSpacing(5)
        transform_row.addWidget(QLabel("变形对话："))
        self.transform_button = QPushButton()
        self.transform_button.setMinimumWidth(0)
        self.transform_button.setSizePolicy(
            QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Fixed
        )
        self.transform_button.clicked.connect(self._manage_transform_bindings)
        transform_row.addWidget(self.transform_button, 1)
        self.transform_clear_button = QPushButton("清空")
        self.transform_clear_button.clicked.connect(self._remove_transform)
        transform_row.addWidget(self.transform_clear_button)

        outer.addWidget(attack_group, 0, 0)
        outer.addWidget(defense_group, 1, 0)
        outer.addWidget(transform_group, 2, 0)
        outer.setRowStretch(3, 1)

    @staticmethod
    def _hex_item(value: int, detail: str = "") -> QTableWidgetItem:
        item = QTableWidgetItem(
            f"{value:02X}" + (f" · {detail}" if detail else "")
        )
        item.setToolTip(detail)
        return item

    @staticmethod
    def _parse_hex(item: QTableWidgetItem | None, label: str) -> int:
        if item is None:
            raise ValueError(f"{label}不能为空。")
        text = item.text().strip().split("·", 1)[0].strip().removeprefix("$")
        try:
            value = int(text, 16)
        except ValueError as error:
            raise ValueError(f"{label}必须是 00—FF 的十六进制数。") from error
        if not 0 <= value <= 0xFF:
            raise ValueError(f"{label}必须是 00—FF 的十六进制数。")
        return value

    def _changed(self, *_args) -> None:
        if not self._loading:
            self._refresh_direct_buttons()
            self._refresh_rule_buttons()
            self._refresh_transform_button()
            self.changed.emit()

    def _binding_text(self, binding: DialogueBinding) -> str:
        segment = DialogueBindingDialog.SEGMENT_LABELS.get(
            binding.segment, f"文字段 ${binding.segment:02X}"
        )
        preview = dialogue_preview(
            self.project, binding.segment, binding.dialogue, self._text_codec
        )
        return f"{segment} · ${binding.dialogue:02X} · {preview}"

    def _refresh_direct_buttons(self) -> None:
        for button, (segment, dialogue) in zip(
            self.direct_buttons, self.direct_controls
        ):
            if segment.currentData() is None:
                button.setText("未绑定")
                continue
            binding = DialogueBinding(
                int(segment.currentData()), dialogue.value()
            )
            button.setText(dialogue_preview(
                self.project, binding.segment, binding.dialogue, self._text_codec
            ))
            button.setToolTip(self._binding_text(binding))

    def _refresh_rule_buttons(self) -> None:
        for group, (button, table) in enumerate(zip(
            self.rule_buttons, self.rule_tables
        )):
            if table.rowCount() == 0:
                button.setText("无")
                button.setToolTip("点击新增此类攻击台词规则。")
                continue
            previews = []
            for row in range(table.rowCount()):
                segment = self._parse_hex(table.item(row, 2), "文字段")
                dialogue = self._parse_hex(table.item(row, 3), "对话编号")
                previews.append(dialogue_preview(
                    self.project, segment, dialogue, self._text_codec
                ))
            button.setText(
                previews[0]
                + (f"（共 {len(previews)} 条）" if len(previews) > 1 else "")
            )
            button.setToolTip(
                f"{self.RULE_LABELS[group]}规则：\n" + "\n".join(previews)
            )

    def _refresh_transform_button(self) -> None:
        rows = self.transform_table.rowCount()
        if rows == 0:
            self.transform_button.setText("无")
            self.transform_button.setToolTip("点击添加变形起飞台词绑定。")
            self.transform_clear_button.setEnabled(False)
            return
        previews = []
        for row in range(rows):
            dialogue = self._parse_hex(
                self.transform_table.item(row, 2), "变形台词"
            )
            previews.append(dialogue_preview(
                self.project, 0x05, dialogue, self._text_codec
            ))
        self.transform_button.setText(
            previews[0] + (f"（共 {rows} 条）" if rows > 1 else "")
        )
        self.transform_button.setToolTip("\n".join(previews))
        self.transform_clear_button.setEnabled(True)

    def _manage_rule_group(self, group: int) -> None:
        table = self.rule_tables[group]
        rules = []
        for row in range(table.rowCount()):
            values = tuple(
                self._parse_hex(table.item(row, column), "特殊对话规则")
                for column in range(4)
            )
            rules.append(DialogueRule(*values))
        dialog = DialogueRuleGroupDialog(
            self.project, group, rules, self, text_codec=self._text_codec
        )
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        target_group, updated = dialog.result_values()
        self._loading = True
        table.setRowCount(0)
        target = self.rule_tables[target_group]
        if target_group != group:
            start_row = target.rowCount()
        else:
            start_row = 0
        for offset, rule in enumerate(updated):
            row = start_row + offset
            target.insertRow(row)
            for column, value in enumerate((
                rule.actor_or_unit, rule.weapon_or_unit,
                rule.segment, rule.dialogue,
            )):
                detail = self._rule_detail(column, value)
                if column == 3:
                    detail = dialogue_preview(
                        self.project, rule.segment, rule.dialogue,
                        self._text_codec,
                    )
                target.setItem(row, column, self._hex_item(value, detail))
        self._loading = False
        self._changed()

    def _manage_transform_bindings(self) -> None:
        rows = self.transform_table.rowCount()
        if rows == 0:
            self._add_transform()
            return
        if rows == 1:
            self.transform_table.setCurrentCell(0, 0)
            self._edit_transform()
            return
        dialog = QDialog(self)
        dialog.setWindowTitle("防御对话")
        dialog.resize(540, 280)
        root = QVBoxLayout(dialog)
        items = QListWidget()
        root.addWidget(items)

        def refresh() -> None:
            current = max(0, items.currentRow())
            items.clear()
            for row in range(self.transform_table.rowCount()):
                start = self.transform_table.item(row, 0).text()
                end = self.transform_table.item(row, 1).text()
                text = self.transform_table.item(row, 2).text().split("·", 1)[-1].strip()
                items.addItem(f"{row + 1:02d}  {start} → {end}：{text}")
            if items.count():
                items.setCurrentRow(min(current, items.count() - 1))

        actions = QHBoxLayout()
        add = QPushButton("添加")
        edit = QPushButton("编辑")
        remove = QPushButton("删除")
        done = QPushButton("关闭")
        for button in (add, edit, remove):
            actions.addWidget(button)
        actions.addStretch()
        actions.addWidget(done)
        root.addLayout(actions)

        def edit_selected() -> None:
            if items.currentRow() < 0:
                return
            self.transform_table.setCurrentCell(items.currentRow(), 0)
            self._edit_transform()
            refresh()

        def remove_selected() -> None:
            if items.currentRow() < 0:
                return
            self.transform_table.setCurrentCell(items.currentRow(), 0)
            self._remove_transform()
            refresh()

        add.clicked.connect(lambda: (self._add_transform(), refresh()))
        edit.clicked.connect(edit_selected)
        remove.clicked.connect(remove_selected)
        items.itemDoubleClicked.connect(lambda _item: edit_selected())
        done.clicked.connect(dialog.accept)
        refresh()
        dialog.exec()

    def _choose_direct_dialogue(self, index: int) -> None:
        segment, dialogue = self.direct_controls[index]
        picker = DialogueBindingDialog(
            self.project, int(segment.currentData()), dialogue.value(), self,
            text_codec=self._text_codec,
            title="攻击对话" if index < 2 else "防御对话",
        )
        if picker.exec() != QDialog.DialogCode.Accepted:
            return
        binding = picker.binding()
        segment.setCurrentIndex(segment.findData(binding.segment))
        dialogue.setValue(binding.dialogue)

    def _add_rule(self, group: int) -> None:
        picker = DialogueRuleDialog(
            self.project, group, DialogueRule(0x00, 0x00, 0x00, 0x00), self,
            text_codec=self._text_codec,
        )
        if picker.exec() != QDialog.DialogCode.Accepted:
            return
        target_group, rule = picker.result_value()
        table = self.rule_tables[target_group]
        row = table.rowCount()
        table.insertRow(row)
        for column, value in enumerate((
            rule.actor_or_unit, rule.weapon_or_unit,
            rule.segment, rule.dialogue,
        )):
            detail = self._rule_detail(column, value)
            if column == 3:
                detail = dialogue_preview(
                    self.project, rule.segment, rule.dialogue,
                    self._text_codec,
                )
            table.setItem(row, column, self._hex_item(value, detail))
        table.setCurrentCell(row, 0)
        self._changed()

    def _rule_detail(self, column: int, value: int) -> str:
        if self.project is None:
            return ""
        try:
            if column == 0:
                character = self.project.character_display_name(value)
                unit = self.project.unit_display_name(value)
                return f"人物 {character} / 机体 {unit}"
            if column == 1:
                weapon = self.project.weapon_display_name(value)
                unit = self.project.unit_display_name(value)
                return f"武器 {weapon} / 机体 {unit}"
            if column == 2:
                return DialogueBindingDialog.SEGMENT_LABELS.get(value, "未知文字组")
        except (IndexError, KeyError, ValueError):
            return "该编号没有可用名称"
        return ""

    def _remove_rule(self, group: int) -> None:
        table = self.rule_tables[group]
        row = table.currentRow()
        if row < 0 and table.rowCount():
            row = table.rowCount() - 1
        if row >= 0:
            table.removeRow(row)
            self._changed()

    def _choose_rule_condition(self, group: int) -> None:
        self._edit_rule(group)

    def _edit_rule(self, group: int) -> None:
        table = self.rule_tables[group]
        row = table.currentRow()
        if row < 0:
            return
        values = tuple(
            self._parse_hex(table.item(row, column), "特殊对话规则")
            for column in range(4)
        )
        picker = DialogueRuleDialog(
            self.project, group, DialogueRule(*values), self,
            text_codec=self._text_codec,
        )
        if picker.exec() != QDialog.DialogCode.Accepted:
            return
        target_group, rule = picker.result_value()
        if target_group != group:
            table.removeRow(row)
            table = self.rule_tables[target_group]
            row = table.rowCount()
            table.insertRow(row)
        for column, value in enumerate((
            rule.actor_or_unit, rule.weapon_or_unit,
            rule.segment, rule.dialogue,
        )):
            detail = self._rule_detail(column, value)
            if column == 3:
                detail = dialogue_preview(
                    self.project, rule.segment, rule.dialogue, self._text_codec
                )
            table.setItem(row, column, self._hex_item(value, detail))
        table.setCurrentCell(row, 0)
        self._changed()

    def _choose_rule_dialogue(self, group: int) -> None:
        self._edit_rule(group)

    def _dialogue_state(self):
        direct = tuple(
            (int(segment.currentData()), dialogue.value())
            for segment, dialogue in self.direct_controls
        )
        rules = tuple(
            tuple(
                table.item(row, column).text().strip()
                if table.item(row, column) is not None
                else ""
                for column in range(4)
            )
            for table in self.rule_tables
            for row in range(table.rowCount())
        )
        shape = tuple(table.rowCount() for table in self.rule_tables)
        return direct, shape, rules

    def _transform_state(self):
        return tuple(
            tuple(
                self.transform_table.item(row, column).text().strip()
                if self.transform_table.item(row, column) is not None
                else ""
                for column in range(3)
            )
            for row in range(self.transform_table.rowCount())
        )

    def _state(self):
        return self._dialogue_state(), self._transform_state()

    def _add_transform(self) -> None:
        if self._loading or self.character_id is None:
            return
        picker = TransformDialogueDialog(
            self.project,
            TransformDialogueBinding(self.character_id, 0x00, 0xFF, 0x00),
            self,
            text_codec=self._text_codec,
        )
        if picker.exec() != QDialog.DialogCode.Accepted:
            return
        binding = picker.binding()
        row = self.transform_table.rowCount()
        self.transform_table.insertRow(row)
        values = (binding.unit_start, binding.unit_end, binding.dialogue)
        details = (
            self.project.unit_display_name(binding.unit_start),
            self.project.unit_display_name(binding.unit_end),
            dialogue_preview(
                self.project, 0x05, binding.dialogue, self._text_codec
            ),
        )
        for column, (value, detail) in enumerate(zip(values, details)):
            self.transform_table.setItem(
                row, column, self._hex_item(value, detail)
            )
        self.transform_table.setCurrentCell(row, 0)
        self._changed()

    def _edit_transform(self) -> None:
        if self.character_id is None:
            return
        row = self.transform_table.currentRow()
        if row < 0:
            return
        values = tuple(
            self._parse_hex(self.transform_table.item(row, column), "变形台词")
            for column in range(3)
        )
        picker = TransformDialogueDialog(
            self.project,
            TransformDialogueBinding(self.character_id, *values),
            self,
            text_codec=self._text_codec,
        )
        if picker.exec() != QDialog.DialogCode.Accepted:
            return
        binding = picker.binding()
        values = (binding.unit_start, binding.unit_end, binding.dialogue)
        details = (
            self.project.unit_display_name(binding.unit_start),
            self.project.unit_display_name(binding.unit_end),
            dialogue_preview(
                self.project, 0x05, binding.dialogue, self._text_codec
            ),
        )
        for column, (value, detail) in enumerate(zip(values, details)):
            self.transform_table.setItem(
                row, column, self._hex_item(value, detail)
            )
        self._changed()

    def _remove_transform(self) -> None:
        row = self.transform_table.currentRow()
        if row < 0 and self.transform_table.rowCount():
            row = self.transform_table.rowCount() - 1
        if row >= 0:
            self.transform_table.removeRow(row)
            self._changed()

    def set_record(self, project, character_id: int | None) -> None:
        self.project, self.character_id = project, character_id
        self.codec = None
        self._text_codec = None
        self._baseline = None
        if (
            project is None
            or character_id is None
            or project.character_dialogue_codec is None
        ):
            self.setEnabled(False)
            return
        self._loading = True
        try:
            codec = project.character_dialogue_codec
            self._text_codec = LegacyTextCodec(project.working)
            record = codec.read(character_id, project.working)
            for (segment, dialogue), binding in zip(self.direct_controls, record.direct):
                segment.setCurrentIndex(segment.findData(binding.segment))
                dialogue.setValue(binding.dialogue)
            for table, rules in zip(self.rule_tables, record.rules):
                table.setRowCount(len(rules))
                for row, rule in enumerate(rules):
                    for column, value in enumerate((
                        rule.actor_or_unit, rule.weapon_or_unit,
                        rule.segment, rule.dialogue,
                    )):
                        detail = self._rule_detail(column, value)
                        if column == 3:
                            detail = dialogue_preview(
                                project, rule.segment, rule.dialogue,
                                self._text_codec,
                            )
                        table.setItem(row, column, self._hex_item(value, detail))
            transforms = codec.character_transform_bindings(
                character_id, project.working
            )
            self.transform_table.setRowCount(len(transforms))
            for row, binding in enumerate(transforms):
                values = (binding.unit_start, binding.unit_end, binding.dialogue)
                details = (
                    project.unit_display_name(binding.unit_start),
                    project.unit_display_name(binding.unit_end),
                    dialogue_preview(
                        project, 0x05, binding.dialogue, self._text_codec
                    ),
                )
                for column, (value, detail) in enumerate(zip(values, details)):
                    self.transform_table.setItem(
                        row, column, self._hex_item(value, detail)
                    )
            aliases = codec.shared_ids(character_id, project.working)
            self.status.setText(
                "直接台词可按正文预览选择；特殊规则可新增、删除或修改，"
                "保存时会在已验证共享池容量内安全重排。"
                f" 共用此台词记录：{'、'.join(f'{item:03d}' for item in aliases)}。"
            )
            self._refresh_direct_buttons()
            self._refresh_rule_buttons()
            self._refresh_transform_button()
            self.codec = codec
            self._baseline = self._state()
            self.setEnabled(True)
        except (ValueError, IndexError) as error:
            self.status.setText(str(error))
            self.setEnabled(False)
        finally:
            self._loading = False

    def record(self) -> CharacterDialogueRecord:
        direct = tuple(
            DialogueBinding(int(segment.currentData()), dialogue.value())
            for segment, dialogue in self.direct_controls
        )
        groups: list[tuple[DialogueRule, ...]] = []
        for table in self.rule_tables:
            rules = []
            for row in range(table.rowCount()):
                values = tuple(
                    self._parse_hex(
                        table.item(row, column),
                        table.horizontalHeaderItem(column).text(),
                    )
                    for column in range(4)
                )
                rules.append(DialogueRule(*values))
            groups.append(tuple(rules))
        return CharacterDialogueRecord(direct, tuple(groups))

    def transform_records(self) -> tuple[TransformDialogueBinding, ...]:
        if self.character_id is None:
            return ()
        result = []
        for row in range(self.transform_table.rowCount()):
            values = tuple(
                self._parse_hex(
                    self.transform_table.item(row, column),
                    self.transform_table.horizontalHeaderItem(column).text(),
                )
                for column in range(3)
            )
            result.append(
                TransformDialogueBinding(self.character_id, *values)
            )
        return tuple(result)

    def has_pending_changes(self) -> bool:
        return (
            self.codec is not None
            and self._baseline is not None
            and self._state() != self._baseline
        )

    def pending_patches(self):
        if self.codec is None or self.character_id is None:
            return ()
        record = self.record()
        before = self.codec.raw_record(self.character_id, self.project.working)
        if len(record.encode()) == len(before):
            dialogue_patches = tuple(filter(None, (
                self.codec.patch(self.project.working, self.character_id, record),
            )))
        else:
            dialogue_patches = self.codec.repack_patches(
                self.project.working, self.character_id, record
            )
        transform_patch = self.codec.transform_patch(
            self.project.working, self.character_id, self.transform_records()
        )
        return dialogue_patches + tuple(
            item for item in (transform_patch,) if item is not None
        )

    def shared_change_impacts(self):
        if (
            self.codec is None
            or self._baseline is None
            or self._dialogue_state() == self._baseline[0]
        ):
            return ()
        aliases = self.codec.shared_ids(self.character_id, self.project.working)
        return (("人物战斗台词记录", aliases),) if len(aliases) > 1 else ()

    def reset_change_impacts(self):
        if self.codec is None or self.character_id is None:
            return ()
        if self.codec.read(
            self.character_id, self.project.working
        ) == self.codec.read(self.character_id, self.project.original):
            return ()
        aliases = self.codec.shared_ids(self.character_id, self.project.working)
        return (("人物战斗台词记录", aliases),) if len(aliases) > 1 else ()

    def reset_to_original(self) -> None:
        if self.codec is None or self.character_id is None:
            return
        original_record = self.codec.read(self.character_id, self.project.original)
        if len(original_record.encode()) == len(
            self.codec.raw_record(self.character_id, self.project.working)
        ):
            patch = self.codec.patch(
                self.project.working, self.character_id, original_record
            )
            dialogue_patches = tuple(filter(None, (patch,)))
        else:
            dialogue_patches = self.codec.repack_patches(
                self.project.working, self.character_id, original_record
            )
        if dialogue_patches:
            apply_verified_patches(
                self.project, dialogue_patches, "还原人物战斗台词绑定"
            )
        transform_patch = self.codec.transform_patch(
            self.project.working,
            self.character_id,
            self.codec.character_transform_bindings(
                self.character_id, self.project.original
            ),
        )
        if transform_patch is not None:
            apply_verified_patches(
                self.project, (transform_patch,), "还原人物变形台词绑定"
            )


class CharacterDetailsWidget(QWidget):
    changed = Signal()
    portrait_export_requested = Signal()

    def __init__(self) -> None:
        super().__init__()
        self.project = None
        self.character_id = None
        self.codec = None
        self._loading = False
        self._baseline = None
        self._image_drafts: dict[str, tuple[int, bytes]] = {}
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(4)
        self.info_panel = QWidget()
        info_layout = QVBoxLayout(self.info_panel)
        info_layout.setContentsMargins(0, 0, 0, 0)
        info_layout.setSpacing(3)
        self.status = QLabel()
        self.status.setWordWrap(True)
        info_layout.addWidget(self.status)
        self.raw_details = QLabel()
        self.raw_details.setObjectName("hintText")
        self.raw_details.setWordWrap(True)
        self.raw_details.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        info_layout.addWidget(self.raw_details)
        attributes_page = QWidget()
        self.attributes_page = attributes_page
        attributes_row = QHBoxLayout(attributes_page)
        attributes_row.setContentsMargins(0, 0, 0, 0)
        attributes_row.setSpacing(5)

        attributes = QGroupBox("人物属性")
        self.attributes_group = attributes
        grid = QGridLayout(attributes)
        grid.setContentsMargins(5, 7, 5, 5)
        grid.setHorizontalSpacing(5)
        grid.setVerticalSpacing(3)
        self.fields = {}
        specs = (("spirit", "精神值", 255), ("growth", "精神成长", 250),
                 ("strength", "强度补正", 255), ("movement", "机动补正", 127),
                 ("defense", "防御补正", 255), ("hp", "HP补正", 255),
                 ("speed", "速度补正", 255))
        for index, (key, label, maximum) in enumerate(specs):
            spin = QSpinBox()
            spin.setRange(0, maximum)
            spin.setMaximumWidth(62)
            spin.setObjectName(f"character_{key}")
            spin.valueChanged.connect(self._changed)
            self.fields[key] = spin
            grid.addWidget(QLabel(label), index // 2, index % 2 * 2)
            grid.addWidget(spin, index // 2, index % 2 * 2 + 1)
        self.fields["growth"].setToolTip("0—200：每级固定增长；201—250：使用第 0—49 号成长曲线。")
        self.survive = QCheckBox("击落不消失")
        self.survive.toggled.connect(self._changed)
        grid.addWidget(self.survive, 3, 2, 1, 2)
        self.shared_attributes = QCheckBox("同时修改共用属性记录")
        self.shared_attributes.toggled.connect(self._changed)
        grid.addWidget(self.shared_attributes, 4, 0, 1, 4)
        self.shared_attributes.hide()
        self.attribute_sharing = QLabel()
        self.attribute_sharing.setWordWrap(True)
        self.attribute_sharing.hide()
        attributes_row.addWidget(attributes, 1)

        spirits = QGroupBox("精神列表与消耗")
        self.spirits_group = spirits
        grid = QGridLayout(spirits)
        grid.setContentsMargins(5, 7, 5, 5)
        grid.setHorizontalSpacing(4)
        grid.setVerticalSpacing(2)
        self.spirits = []
        self.costs = []
        for index, name in enumerate(SPIRIT_NAMES):
            check = SpiritCheckBox(name)
            check.setObjectName(f"character_spirit_{index}")
            cost = QSpinBox()
            cost.setRange(0, 255)
            cost.setMinimumWidth(46)
            cost.setMaximumWidth(54)
            cost.setObjectName(f"spirit_cost_{index}")
            check.toggled.connect(self._changed)
            cost.valueChanged.connect(self._changed)
            cost.valueChanged.connect(
                lambda _value, spirit=index: self._refresh_spirit_label(spirit)
            )
            check.editRequested.connect(
                lambda spirit=index: self._edit_spirit_cost(spirit)
            )
            check.setToolTip("勾选人物拥有的精神；双击修改全局消耗。")
            cost.hide()
            row, col = index % 8, index // 8
            grid.addWidget(check, row, col)
            self.spirits.append(check)
            self.costs.append(cost)
        hint = QLabel("消耗值全人物共用；游戏精神菜单最多显示 6 项，按列表顺序取前 6 项。")
        hint.setWordWrap(True)
        hint.hide()
        spirits.setToolTip(hint.text())
        attributes_row.addWidget(spirits, 2)

        portrait = QGroupBox("头像设置")
        self.portrait_group = portrait
        portrait_layout = QGridLayout(portrait)
        portrait_layout.setContentsMargins(6, 8, 6, 6)
        portrait_layout.setHorizontalSpacing(4)
        portrait_layout.setVerticalSpacing(3)
        self.portrait_preview = QLabel()
        self.portrait_preview.setFixedSize(64, 64)
        portrait_layout.addWidget(self.portrait_preview, 0, 0, 2, 1)
        visibility = QVBoxLayout()
        visibility.setSpacing(2)
        self.show_front = QCheckBox("显示正面")
        self.show_back = QCheckBox("显示背景")
        self.show_front.setChecked(True)
        self.show_back.setChecked(True)
        self.show_front.toggled.connect(self._render_previews)
        self.show_back.toggled.connect(self._render_previews)
        visibility.addWidget(self.show_front)
        visibility.addWidget(self.show_back)
        visibility.addStretch()
        portrait_layout.addLayout(visibility, 0, 1, 2, 1)

        upload_actions = QVBoxLayout()
        upload_actions.setSpacing(2)
        for kind, text in (("front", "正面上传"), ("back", "背景上传")):
            button = QPushButton(text)
            button.clicked.connect(
                lambda _checked=False, kind=kind: self._upload_image(kind)
            )
            upload_actions.addWidget(button)
        portrait_layout.addLayout(upload_actions, 0, 2, 2, 1)

        self.portrait_fields = {}
        for key, _label, minimum, maximum in (
            ("front_bank", "正面图库", 0, 255), ("front_slot", "", 1, 4),
            ("back_bank", "背景图库", 0, 255), ("back_slot", "", 1, 4),
            ("color0", "头像颜色1", 0, 63), ("color1", "头像颜色2", 0, 63),
            ("color2", "头像颜色3", 0, 63),
        ):
            if key.startswith("color"):
                spin = NesColorField()
            elif key.endswith("bank"):
                spin = LegacyValueCombo(
                    minimum, maximum, lambda value: f"图库: {value:03d}"
                )
            else:
                spin = LegacyValueCombo(
                    minimum, maximum, lambda value: f"头像{value}"
                )
            if key.endswith("bank"):
                spin.setMaximumWidth(100)
            elif key.endswith("slot"):
                spin.setMaximumWidth(78)
            else:
                spin.setMaximumWidth(84)
            spin.setObjectName(f"portrait_{key}")
            spin.valueChanged.connect(self._changed)
            self.portrait_fields[key] = spin

        selector_specs = (
            ("正面图库：", "front_bank", "front_slot"),
            ("背景图库：", "back_bank", "back_slot"),
        )
        for column, (label, bank_key, slot_key) in enumerate(selector_specs, 3):
            portrait_layout.addWidget(QLabel(label), 0, column)
            selector = QWidget()
            selector_row = QHBoxLayout(selector)
            selector_row.setContentsMargins(0, 0, 0, 0)
            selector_row.setSpacing(3)
            selector_row.addWidget(self.portrait_fields[bank_key])
            selector_row.addWidget(self.portrait_fields[slot_key])
            portrait_layout.addWidget(selector, 1, column)

        for column, (label, key) in enumerate((
            ("头像颜色1：", "color0"),
            ("头像颜色2：", "color1"),
            ("头像颜色3：", "color2"),
        ), 5):
            portrait_layout.addWidget(QLabel(label), 0, column)
            portrait_layout.addWidget(self.portrait_fields[key], 1, column)

        utility_actions = QVBoxLayout()
        utility_actions.setSpacing(2)
        self.shared_portrait = QCheckBox("同时修改共用头像记录")
        self.shared_portrait.toggled.connect(self._changed)
        self.shared_portrait.hide()
        self.portrait_sharing = QLabel()
        self.portrait_sharing.setWordWrap(True)
        self.portrait_sharing.setMaximumWidth(210)
        self.portrait_sharing.hide()
        self.portrait_export_button = QPushButton("导出当前头像…")
        self.portrait_export_button.setObjectName("portrait_export_button")
        self.portrait_export_button.setToolTip(
            "导出当前人物的[背面].bmp、[正面].bmp和[效果].bmp"
        )
        self.portrait_export_button.clicked.connect(
            self.portrait_export_requested.emit
        )
        utility_actions.addWidget(self.portrait_export_button)
        self.portrait_advanced_button = QPushButton("高级…")
        self.portrait_advanced_button.setCheckable(True)
        self.portrait_advanced_button.setToolTip(
            "仅在多个人物共用同一属性或头像记录、且需要一起修改时使用。"
        )
        self.portrait_advanced_button.toggled.connect(
            self.shared_portrait.setVisible
        )
        self.portrait_advanced_button.toggled.connect(
            self.shared_attributes.setVisible
        )
        utility_actions.addWidget(self.portrait_advanced_button)
        portrait_layout.addLayout(utility_actions, 0, 8, 2, 1)
        portrait_layout.setColumnStretch(8, 1)
        portrait.setToolTip(
            "选择正面、背景和三种颜色；上传图片后点数据库窗口的“确定”保存。"
        )

        outer.addWidget(portrait)
        outer.addWidget(attributes_page)

    def _refresh_spirit_label(self, index: int) -> None:
        self.spirits[index].setText(
            f"{SPIRIT_NAMES[index]}：{self.costs[index].value()}"
        )

    def _edit_spirit_cost(self, index: int) -> None:
        dialog = SpiritCostDialog(
            SPIRIT_NAMES[index], self.costs[index].value(), self
        )
        if dialog.exec() == QDialog.DialogCode.Accepted:
            self.costs[index].setValue(dialog.cost.value())

    def _state(self):
        return (tuple(spin.value() for spin in self.fields.values()), self.survive.isChecked(),
                tuple(check.isChecked() for check in self.spirits), tuple(cost.value() for cost in self.costs),
                tuple(spin.value() for spin in self.portrait_fields.values()))

    def _changed(self, *_args) -> None:
        if self._loading:
            return
        self._render_previews()
        self.changed.emit()

    def has_pending_changes(self) -> bool:
        return self.codec is not None and self._baseline is not None and (self._state() != self._baseline or bool(self._image_drafts))

    def shared_change_impacts(self) -> tuple[tuple[str, tuple[int, ...]], ...]:
        """Describe drafts that intentionally affect more than one character ID."""

        if self.codec is None or self.character_id is None:
            return ()
        impacts: list[tuple[str, tuple[int, ...]]] = []
        if (
            self.shared_attributes.isChecked()
            and self.attribute_record() != self.codec.read(self.character_id)
        ):
            ids = self.codec.shared_ids(self.character_id)
            if len(ids) > 1:
                impacts.append(("人物属性记录", ids))
        if (
            self.shared_portrait.isChecked()
            and self.portrait_record() != self.codec.read_portrait(self.character_id)
        ):
            ids = self.codec.shared_ids(self.character_id, portrait=True)
            if len(ids) > 1:
                impacts.append(("头像记录", ids))
        for kind, (first_tile, _payload) in self._image_drafts.items():
            ids = self._portrait_tile_users(first_tile)
            if len(ids) > 1:
                impacts.append(
                    ("正面头像 CHR 图块" if kind == "front" else "背景头像 CHR 图块", ids)
                )
        return tuple(impacts)

    def _portrait_tile_users(self, first_tile: int) -> tuple[int, ...]:
        if self.codec is None:
            return ()
        affected: set[int] = set()
        for character_id in range(1, self.codec.COUNT):
            portrait = self.codec.read_portrait(character_id)
            starts = (
                portrait.front_bank * 64 + portrait.front_slot * 16,
                portrait.back_bank * 64 + portrait.back_slot * 16,
            )
            if first_tile in starts:
                affected.add(character_id)
        if self.character_id is not None:
            affected.add(self.character_id)
        return tuple(sorted(affected))

    @staticmethod
    def _format_ids(ids: tuple[int, ...]) -> str:
        shown = "、".join(f"{value:03d}" for value in ids[:24])
        return shown + (f"…共 {len(ids)} 个" if len(ids) > 24 else "")

    def set_record(self, project, character_id: int | None) -> None:
        self.project, self.character_id = project, character_id
        self.codec = None
        self._baseline = None
        self._image_drafts.clear()
        if project is None or character_id is None:
            self.raw_details.clear()
            self.setEnabled(False)
            return
        self._loading = True
        try:
            codec = CharacterAttributesCodec(project)
            record = codec.read(character_id)
            portrait = codec.read_portrait(character_id)
            attribute_raw = codec.record_bytes(character_id)
            portrait_raw = codec.record_bytes(character_id, portrait=True)
            self.raw_details.setText(
                f"属性记录 0x{codec.record_offset(character_id):06X}（{len(attribute_raw)}字节）："
                f"{attribute_raw.hex(' ').upper()}；头像记录 "
                f"0x{codec.record_offset(character_id, portrait=True):06X}："
                f"{portrait_raw.hex(' ').upper()}。00 是ROM中的真实零值。"
            )
            values = dict(zip(("movement", "strength", "defense", "speed", "hp"), record.corrections))
            values.update(spirit=record.spirit, growth=record.growth)
            values["movement"] &= 127
            for key, spin in self.fields.items():
                spin.setValue(values[key])
            self.survive.setChecked(bool(record.corrections[0] & 128))
            for index, check in enumerate(self.spirits):
                check.setChecked(bool(record.spirit_mask & (1 << (23 - index))))
            for cost, value in zip(self.costs, codec.costs()):
                cost.setValue(value)
            selector_values = dict(zip(
                ("front_bank", "front_slot", "back_bank", "back_slot"),
                legacy_portrait_selectors(portrait),
            ))
            for key, spin in self.portrait_fields.items():
                value = (
                    portrait.colors[int(key[-1])]
                    if key.startswith("color")
                    else selector_values[key]
                )
                spin.setValue(value)
            self.shared_attributes.setChecked(False)
            self.shared_portrait.setChecked(False)
            for label, is_portrait in ((self.attribute_sharing, False), (self.portrait_sharing, True)):
                ids = codec.shared_ids(character_id, portrait=is_portrait)
                names = "、".join(f"{item:03d}" for item in ids[:16])
                label.setText(f"共用此记录：{names}{'…' if len(ids) > 16 else ''}（{len(ids)} 个）。独立修改需要原数据池有空间。")
                label.setToolTip("、".join(f"{item:03d} {project.character_display_name(item)}" for item in ids if item < project.profile.character_name_count))
                toggle = self.shared_portrait if is_portrait else self.shared_attributes
                toggle.setToolTip(label.text() + "\n" + label.toolTip())
            self.codec = codec
            self._baseline = self._state()
            self.status.setText("修改将随数据库窗口“确定”保存；“取消”会还原本次窗口内的改动。")
            self.setEnabled(True)
            self._render_previews()
        except (ValueError, IndexError) as error:
            self.status.setText(str(error))
            self.raw_details.setText(f"原始记录读取失败：{error}")
            self.setEnabled(False)
        finally:
            self._loading = False

    def attribute_record(self) -> CharacterAttributes:
        original = self.codec.read(self.character_id)
        values = self.fields
        movement = values["movement"].value() | (128 if self.survive.isChecked() else 0)
        return CharacterAttributes(values["spirit"].value(), values["growth"].value(),
                                   sum(1 << (23 - index) for index, check in enumerate(self.spirits) if check.isChecked()),
                                   (movement, values["strength"].value(), values["defense"].value(),
                                    values["speed"].value(), values["hp"].value()), original.reserved_flags)

    def portrait_record(self) -> PortraitRecord:
        values = {key: spin.value() for key, spin in self.portrait_fields.items()}
        return PortraitRecord(
            tuple(values[f"color{index}"] for index in range(3)),
            values["front_bank"],
            values["back_bank"],
            values["front_slot"] - 1,
            values["back_slot"] - 1,
        )

    def pending_patches(self):
        if self.codec is None or self.character_id is None:
            return ()
        patches = (self.codec.patches(self.character_id, self.attribute_record(), shared=self.shared_attributes.isChecked())
                   + self.codec.portrait_patches(self.character_id, self.portrait_record(), shared=self.shared_portrait.isChecked())
                   + (self.codec.cost_patch(tuple(cost.value() for cost in self.costs)),))
        portrait = self.portrait_record()
        targets = {"front": portrait.front_bank * 64 + portrait.front_slot * 16,
                   "back": portrait.back_bank * 64 + portrait.back_slot * 16}
        for kind, (first_tile, payload) in self._image_drafts.items():
            if targets[kind] != first_tile:
                raise ValueError("上传后更改了头像图库位置，请在新位置重新上传图片。")
            offset = self.project.chr_codec.tile_offset(first_tile)
            patches += ((offset, bytes(self.project.working[offset:offset + len(payload)]), payload),)
        replacements = {}
        for offset, _before, after in patches:
            for index, value in enumerate(after):
                if offset + index in replacements and replacements[offset + index] != value:
                    raise ValueError("正面和背景上传指向重叠的 CHR 图块，且内容不同；请为它们选择不同图库位置。")
                replacements[offset + index] = value
        return patches

    def apply_pending(self) -> None:
        if self.has_pending_changes():
            apply_verified_patches(self.project, self.pending_patches(), "人物属性、精神与头像")

    def reset_to_original(self) -> None:
        if self.codec is None or self.character_id is None:
            return
        patches = (self.codec.patches(self.character_id, self.codec.read(self.character_id, original=True),
                                      shared=self.shared_attributes.isChecked())
                   + self.codec.portrait_patches(self.character_id, self.codec.read_portrait(self.character_id, original=True),
                                                shared=self.shared_portrait.isChecked()))
        apply_verified_patches(self.project, patches, "还原人物属性与头像")

    def _render_previews(self) -> None:
        if self.project is None or self.codec is None:
            return
        record = self.portrait_record()
        front = self._portrait_image(
            record.front_bank * 64 + record.front_slot * 16,
            record.colors,
            transparent=True,
        )
        back = self._portrait_image(
            record.back_bank * 64 + record.back_slot * 16,
            PORTRAIT_BACKGROUND_PALETTE_NES[1:],
        )
        if front is None or back is None:
            self.portrait_preview.clear()
            self.portrait_preview.setText("图库越界")
            return
        composite = QImage(32, 32, QImage.Format.Format_ARGB32)
        composite.fill(palette_color(0x0F))
        if self.show_back.isChecked():
            composite = back.copy()
        if self.show_front.isChecked():
            for y in range(32):
                for x in range(32):
                    if front.pixelColor(x, y).alpha():
                        composite.setPixelColor(x, y, front.pixelColor(x, y))
        self.portrait_preview.setPixmap(QPixmap.fromImage(composite.scaled(64, 64)))

    def _portrait_image(self, first_tile: int, palette: tuple[int, ...], *, transparent: bool = False) -> QImage | None:
        if first_tile + 16 > self.project.chr_tile_count:
            return None
        image = QImage(32, 32, QImage.Format.Format_ARGB32)
        colors = (palette_color(0x0F), *(palette_color(value) for value in palette))
        if transparent:
            colors[0].setAlpha(0)
        for tile in range(16):
            pixels = self.project.chr_tile_pixels(first_tile + tile)
            for draft_start, payload in self._image_drafts.values():
                if draft_start <= first_tile + tile < draft_start + 16:
                    raw = payload[(first_tile + tile - draft_start) * 16:(first_tile + tile - draft_start + 1) * 16]
                    pixels = tuple(((raw[y] >> (7-x)) & 1) | (((raw[y+8] >> (7-x)) & 1) << 1) for y in range(8) for x in range(8))
            for y in range(8):
                for x in range(8):
                    image.setPixelColor(tile % 4 * 8 + x, tile // 4 * 8 + y, colors[pixels[y * 8 + x]])
        return image

    def import_portrait_image(self, kind: str, image: QImage) -> None:
        if self.codec is None or kind not in ("front", "back"):
            raise ValueError("请先选择人物及正面或背景头像。")
        if image.isNull() or image.width() != 32 or image.height() != 32:
            raise ValueError("头像图片必须为 32×32 像素。")
        record = self.portrait_record()
        first_tile = (
            record.front_bank * 64 + record.front_slot * 16
            if kind == "front"
            else record.back_bank * 64 + record.back_slot * 16
        )
        self.project.chr_codec.range_bytes(first_tile, 16, bytes(self.project.working))
        layer_colors = (
            record.colors
            if kind == "front"
            else PORTRAIT_BACKGROUND_PALETTE_NES[1:]
        )
        colors = (palette_color(0x0F), *(palette_color(value) for value in layer_colors))
        payload = bytearray()
        for tile in range(16):
            pixels = []
            for y in range(8):
                for x in range(8):
                    color = image.pixelColor(tile % 4 * 8 + x, tile // 4 * 8 + y)
                    if color.alpha() < 128:
                        pixels.append(0)
                    else:
                        pixels.append(min(range(4), key=lambda index: sum((a-b)**2 for a, b in zip(color.getRgb()[:3], colors[index].getRgb()[:3]))))
            payload.extend(self.project.chr_codec.encode_tile(pixels))
        self._image_drafts[kind] = first_tile, bytes(payload)
        affected = self._portrait_tile_users(first_tile)
        self.status.setText(
            "头像图片已暂存，按当前四色量化；将影响使用这些 CHR 图块的人物："
            f"{self._format_ids(affected)}。确定后写入，取消可放弃。"
        )
        self._changed()

    def _upload_image(self, kind: str) -> None:
        path, _filter = QFileDialog.getOpenFileName(self, "上传32×32头像", "", "图片 (*.png *.bmp)")
        if not path:
            return
        try:
            self.import_portrait_image(kind, QImage(path))
        except ValueError as error:
            QMessageBox.critical(self, "头像上传失败", str(error))
