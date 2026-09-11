from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QComboBox,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QScrollArea,
    QSplitter,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from .pages import CharacterPage, WeaponPage


def readable_references(combo: QComboBox) -> None:
    """Keep source IDs as item data; put pointer diagnostics in tooltips."""
    for index in range(combo.count()):
        text = combo.itemText(index)
        if " · 来源 " in text:
            combo.setItemData(index, text, Qt.ItemDataRole.ToolTipRole)
            name = text.split(" · 来源 ", 1)[0]
            combo.setItemText(index, f"{name}  [${int(combo.itemData(index)):02X}]")
    combo.setMinimumContentsLength(12)
    combo.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)


def collapsible_details(title: str, content: QWidget) -> QWidget:
    host = QWidget()
    layout = QVBoxLayout(host)
    layout.setContentsMargins(0, 0, 0, 0)
    toggle = QToolButton()
    toggle.setText(title)
    toggle.setCheckable(True)
    toggle.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
    toggle.setArrowType(Qt.ArrowType.RightArrow)
    toggle.toggled.connect(content.setVisible)
    toggle.toggled.connect(lambda expanded: toggle.setArrowType(
        Qt.ArrowType.DownArrow if expanded else Qt.ArrowType.RightArrow
    ))
    layout.addWidget(toggle)
    layout.addWidget(content)
    content.hide()
    return host


def _prepare_readable_page(page) -> QVBoxLayout:
    splitter = page.findChild(QSplitter)
    assert splitter is not None
    detail = splitter.widget(1)
    detail_layout = detail.layout()
    assert isinstance(detail_layout, QVBoxLayout)
    detail.setMinimumWidth(0)
    page.record_meta.setWordWrap(True)
    advanced = QWidget()
    advanced_layout = QVBoxLayout(advanced)
    advanced_layout.setContentsMargins(0, 0, 0, 0)
    advanced_layout.addWidget(page.record_meta)
    for field in (page.name_tokens, getattr(page, "raw_record", None)):
        if field is None:
            continue
        parent_layout = field.parentWidget().layout()
        if isinstance(parent_layout, QFormLayout):
            label = parent_layout.labelForField(field)
            parent_layout.removeWidget(field)
            if label is not None:
                parent_layout.removeWidget(label)
                advanced_layout.addWidget(label)
        advanced_layout.addWidget(field)
    detail_layout.insertWidget(2, collapsible_details("技术详情：指针、共享记录与原始字节", advanced))
    page.records.setMinimumWidth(180)
    page.records.setMaximumWidth(400)
    splitter.setSizes([280, 770])
    splitter.setChildrenCollapsible(False)
    scroll = QScrollArea()
    scroll.setWidgetResizable(True)
    scroll.setFrameShape(QScrollArea.Shape.NoFrame)
    # Reparenting the detail widget removes its old splitter slot.
    scroll.setWidget(detail)
    splitter.addWidget(scroll)
    splitter.setStretchFactor(0, 0)
    splitter.setStretchFactor(1, 1)
    return detail_layout


class ReadableCharacterPage(CharacterPage):
    def __init__(self) -> None:
        super().__init__()
        detail = _prepare_readable_page(self)
        self.capability_status = QLabel(
            "可编辑：已有名称引用、我方/敌方战斗音乐。\n"
            "尚未接通：正反头像、精神/修正值、战斗台词、击破不消失。"
        )
        self.capability_status.setObjectName("hintText")
        self.capability_status.setWordWrap(True)
        detail.insertWidget(1, self.capability_status)

    def record_text(self, record_id: int) -> str:
        assert self.project is not None
        return f"{record_id:03d}  {self.project.character_display_name(record_id)}"

    def refresh(self) -> None:
        super().refresh()
        readable_references(self.name_reference)


class ReadableWeaponPage(WeaponPage):
    unit_requested = Signal(int)

    def __init__(self) -> None:
        super().__init__()
        detail = _prepare_readable_page(self)
        self.capability_status = QLabel(
            "可编辑：已有名称引用、射程、命中、对空/陆/海攻击力。\n"
            "动画、特技与效果模式尚未接通；其原始字节保留。"
        )
        self.capability_status.setObjectName("hintText")
        self.capability_status.setWordWrap(True)
        detail.insertWidget(1, self.capability_status)
        group = QGroupBox("使用此武器的机体")
        layout = QVBoxLayout(group)
        self.usage_status = QLabel("请选择武器。")
        self.usage_status.setWordWrap(True)
        layout.addWidget(self.usage_status)
        self.usage_list = QListWidget()
        self.usage_list.setObjectName("weaponUnitUsageList")
        self.usage_list.setAlternatingRowColors(True)
        self.usage_list.setMinimumHeight(100)
        self.usage_list.setMaximumHeight(190)
        self.usage_list.itemDoubleClicked.connect(self._open_usage)
        layout.addWidget(self.usage_list)
        row = QHBoxLayout()
        jump = QPushButton("转到所选机体")
        jump.clicked.connect(lambda: self._open_usage(self.usage_list.currentItem()))
        row.addWidget(jump)
        row.addWidget(QLabel("双击机体也可跳转；按实际装备槽统计。"))
        row.addStretch()
        layout.addLayout(row)
        detail.insertWidget(detail.count() - 2, group)

    def record_text(self, record_id: int) -> str:
        assert self.project is not None
        return f"{record_id:03d}  {self.project.weapon_display_name(record_id)}"

    def refresh(self) -> None:
        super().refresh()
        readable_references(self.name_reference)

    def load_record(self, record_id: int | None) -> None:
        super().load_record(record_id)
        self.refresh_usage()

    def refresh_usage(self) -> None:
        if self.project is None or self.current_id is None:
            self._set_usage_entries([])
            self.usage_status.setText("请选择武器。")
            return
        if not self.project.supports_unit_weapons:
            self._set_usage_entries([])
            self.usage_status.setText("当前 ROM 的机体武器关联表尚未验证。")
            return
        entries: list[tuple[int, str]] = []
        for unit_id in range(1, self.project.unit_count):
            slots = tuple(index + 1 for index, weapon_id in enumerate(
                self.project.get_unit_weapons(unit_id)
            ) if weapon_id == self.current_id)
            if not slots:
                continue
            text = (
                f"{unit_id:03d}  {self.project.unit_display_name(unit_id)}"
                f"  · 武器槽 {'、'.join(map(str, slots))}"
            )
            entries.append((unit_id, text))
        self._set_usage_entries(entries)
        count = len(entries)
        self.usage_status.setText(
            f"当前工程有 {count} 个机体装备此武器。"
            if count else "当前没有机体装备此武器；这不代表该记录或动画空间可以删除。"
        )

    def _set_usage_entries(self, entries: list[tuple[int, str]]) -> None:
        """Retain items during parameter/name edits and double-click signals."""
        role = Qt.ItemDataRole.UserRole
        selected = self.usage_list.currentItem()
        selected_id = int(selected.data(role)) if selected is not None else None
        old_ids = tuple(int(self.usage_list.item(row).data(role))
                        for row in range(self.usage_list.count()))
        new_ids = tuple(unit_id for unit_id, _text in entries)
        blocked = self.usage_list.blockSignals(True)
        updates = self.usage_list.updatesEnabled()
        self.usage_list.setUpdatesEnabled(False)
        try:
            if old_ids == new_ids:
                for row, (_unit_id, text) in enumerate(entries):
                    self.usage_list.item(row).setText(text)
            else:
                self.usage_list.clear()
                for unit_id, text in entries:
                    item = QListWidgetItem(text)
                    item.setData(role, unit_id)
                    self.usage_list.addItem(item)
            if entries:
                row = new_ids.index(selected_id) if selected_id in new_ids else 0
                self.usage_list.setCurrentRow(row)
        finally:
            self.usage_list.blockSignals(blocked)
            self.usage_list.setUpdatesEnabled(updates)

    def _open_usage(self, item: QListWidgetItem | None) -> None:
        if item is None:
            return
        # Committing emits project_changed synchronously. The dialog refreshes
        # this page and rebuilds usage_list, destroying its QListWidgetItems.
        # Only the stable ID may be retained across that refresh.
        unit_id = int(item.data(Qt.ItemDataRole.UserRole))
        if self.commit_pending_changes():
            self.unit_requested.emit(unit_id)
