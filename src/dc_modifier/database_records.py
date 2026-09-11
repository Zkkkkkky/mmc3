from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QComboBox,
    QFormLayout,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QScrollArea,
    QSpinBox,
    QSplitter,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from .pages import CharacterPage, WeaponPage
from .character_editor import CharacterDetailsWidget
from .animation_editor import WeaponAnimationWidget
from fc_editor.codecs.character_attributes import (
    CharacterAttributesCodec, WEAPON_SKILLS, apply_verified_patches,
    weapon_extra_patches, weapon_extra_values,
)
from fc_editor.models import WEAPON_FIELDS


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
        self._loading_details = False
        super().__init__()
        detail = _prepare_readable_page(self)
        self.capability_status = QLabel(
            "可编辑：名称引用、双方音乐、精神/成长、五项修正、精神与消耗、头像引用/颜色、击落不消失。\n"
            "战斗台词与变形台词尚未接通。"
        )
        self.capability_status.setObjectName("hintText")
        self.capability_status.setWordWrap(True)
        detail.insertWidget(1, self.capability_status)
        for label in self.findChildren(QLabel):
            if label.text().startswith("当前人物属性表、头像索引"):
                label.hide()
        self.original_name.setWordWrap(True)
        identities = [item for item in self.findChildren(QGroupBox) if item.title() in ("名称", "人物战斗音乐")]
        if len(identities) == 2:
            identity_row = QWidget()
            row = QHBoxLayout(identity_row)
            row.setContentsMargins(0, 0, 0, 0)
            position = detail.indexOf(identities[0])
            for group in identities:
                detail.removeWidget(group)
                row.addWidget(group, 1)
            detail.insertWidget(position, identity_row)
        self.character_details = CharacterDetailsWidget()
        self.character_details.changed.connect(self._update_pending_state)
        detail.insertWidget(detail.count() - 2, self.character_details)

    def record_text(self, record_id: int) -> str:
        assert self.project is not None
        return f"{record_id:03d}  {self.project.character_display_name(record_id)}"

    def preferred_record_id(self) -> int | None:
        if self.project is None:
            return None
        codec = CharacterAttributesCodec(self.project)
        return next(
            (
                character_id
                for character_id in self.record_ids()
                if any(codec.record_bytes(character_id))
            ),
            None,
        )

    def refresh(self) -> None:
        super().refresh()
        readable_references(self.name_reference)

    def load_record(self, record_id: int | None) -> None:
        self._loading_details = True
        try:
            super().load_record(record_id)
            self.character_details.set_record(self.project, record_id)
        finally:
            self._loading_details = False
        self._update_pending_state()

    def _update_pending_state(self) -> None:
        if self._loading_details:
            return
        super()._update_pending_state()
        details = getattr(self, "character_details", None)
        if details is not None and details.has_pending_changes():
            self.apply_button.setEnabled(True)
            self.pending_state.setText("● 有尚未暂存的人物属性、精神或头像改动")

    def apply_record(self) -> None:
        if self.project is None or self.current_id is None:
            return
        try:
            patches = self.character_details.pending_patches()
            with self.project.transaction(f"人物 ${self.current_id:02X} · 完整表单"):
                apply_verified_patches(self.project, patches, "人物属性、精神与头像")
                self.project.set_character_name_reference(self.current_id, int(self.name_reference.currentData()))
                if self.ally_music.isEnabled():
                    self.project.set_battle_music_binding(self.current_id, int(self.ally_music.currentData()), int(self.enemy_music.currentData()))
            self.load_record(self.current_id)
            self.project_changed.emit(f"已更新人物 ${self.current_id:02X}")
        except Exception as error:
            self.show_error(error)

    def reset_record(self) -> None:
        if self.project is None or self.current_id is None:
            return
        try:
            with self.project.transaction(f"人物 ${self.current_id:02X} · 还原"):
                self.character_details.reset_to_original()
                self.project.reset_character_name(self.current_id)
                if self.project.supports_battle_music:
                    self.project.reset_battle_music_binding(self.current_id)
            self.load_record(self.current_id)
            self.project_changed.emit(f"已还原人物 ${self.current_id:02X}；全局精神消耗保留当前值")
        except Exception as error:
            self.show_error(error)

    def duplicate_record(self) -> None:
        if self.project is None or self.current_id is None or not self.commit_pending_changes():
            return
        options = [f"${item:02X} · {self.project.character_display_name(item)}"
                   for item in range(1, self.project.profile.character_name_count) if item != self.current_id]
        selected, accepted = QInputDialog.getItem(self, "复制人物", "复制名称、音乐、属性、精神与头像到：", options, 0, False)
        if not accepted:
            return
        target = int(selected[1:3], 16)
        try:
            codec = CharacterAttributesCodec(self.project)
            patches = codec.patches(target, codec.read(self.current_id)) + codec.portrait_patches(target, codec.read_portrait(self.current_id))
            sources = self.project.character_name_source_ids(self.current_id)
            with self.project.transaction(f"复制人物 ${self.current_id:02X} 到 ${target:02X}"):
                apply_verified_patches(self.project, patches, "复制人物属性与头像")
                if sources:
                    self.project.set_character_name_reference(target, sources[0])
                if self.project.supports_battle_music:
                    binding = self.project.get_battle_music_binding(self.current_id)
                    self.project.set_battle_music_binding(target, binding.attacker_command, binding.defender_command)
            self.project_changed.emit(f"已复制人物到 ${target:02X}")
        except Exception as error:
            self.show_error(error)


class ReadableWeaponPage(WeaponPage):
    unit_requested = Signal(int)

    def __init__(self) -> None:
        self._loading_details = False
        self._extras_enabled = False
        super().__init__()
        detail = _prepare_readable_page(self)
        self.capability_status = QLabel(
            "可编辑：名称引用、射程、命中、距离补正、武器特技、对空/陆/海攻击力及双方动画的已验证参数。"
        )
        self.capability_status.setObjectName("hintText")
        self.capability_status.setWordWrap(True)
        detail.insertWidget(1, self.capability_status)
        self.rom_summary = QLabel("请选择武器以读取完整原始记录。")
        self.rom_summary.setObjectName("hintText")
        self.rom_summary.setWordWrap(True)
        self.rom_summary.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        detail.insertWidget(2, self.rom_summary)
        attributes = next(group for group in self.findChildren(QGroupBox) if group.title() == "战斗参数")
        grid = attributes.layout()
        if isinstance(grid, QGridLayout):
            retained = tuple(self.fields.values()) + tuple(self.original_values.values())
            while grid.count():
                widget = grid.takeAt(0).widget()
                if widget is not None and widget not in retained:
                    widget.hide()
                    widget.deleteLater()
            for index, field in enumerate(WEAPON_FIELDS):
                row, col = index // 3, index % 3 * 3
                self.fields[field.key].setMaximumWidth(75)
                grid.addWidget(QLabel(field.label), row, col)
                grid.addWidget(self.fields[field.key], row, col + 1)
                self.original_values[field.key].setToolTip("基准 ROM 原值")
                grid.addWidget(self.original_values[field.key], row, col + 2)
        extras = QGroupBox("武器特技与距离补正")
        form = QFormLayout(extras)
        self.weapon_skill = QComboBox()
        for index, name in enumerate(WEAPON_SKILLS):
            self.weapon_skill.addItem(f"{index:02d}：{name}", index)
        self.weapon_skill.currentIndexChanged.connect(self._update_pending_state)
        self.distance_correction = QSpinBox()
        self.distance_correction.setRange(0, 3)
        self.distance_correction.valueChanged.connect(self._update_pending_state)
        form.addRow("武器特技", self.weapon_skill)
        form.addRow("距离补正表", self.distance_correction)
        self.extra_status = QLabel()
        self.extra_status.setWordWrap(True)
        form.addRow(self.extra_status)
        detail.insertWidget(detail.count() - 2, extras)
        self.weapon_animation = WeaponAnimationWidget()
        self.weapon_animation.changed.connect(self._update_pending_state)
        detail.insertWidget(detail.count() - 2, self.weapon_animation)
        for button in self.findChildren(QPushButton):
            if button.text() == "复制到其他ID…":
                button.setText("复制属性与名称到其他ID…")
            elif button.text() == "还原此武器":
                button.setText("还原武器属性与名称")
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
        self.weapon_animation.addTab(group, "使用此武器的机体")

    def record_text(self, record_id: int) -> str:
        assert self.project is not None
        return f"{record_id:03d}  {self.project.weapon_display_name(record_id)}"

    def refresh(self) -> None:
        super().refresh()
        readable_references(self.name_reference)

    def load_record(self, record_id: int | None) -> None:
        self._loading_details = True
        try:
            super().load_record(record_id)
            self._extras_enabled = False
            if self.project is not None and record_id is not None:
                skill, distance = weapon_extra_values(self.project, record_id)
                weapon_extra_patches(self.project, record_id, skill, distance)
                self.weapon_skill.setCurrentIndex(skill)
                self.distance_correction.setValue(distance)
                self._extras_enabled = True
                self.extra_status.setText("距离补正引用“其他修改1”的第 0—3 号命中表；特技名称与旧修改器一致。")
                raw = self.project.weapon_record_bytes(record_id)
                name_raw = self.project.weapon_name_record_bytes(record_id)
                self.rom_summary.setText(
                    f"ROM属性 0x{self.project.weapon_codec.record_offset(record_id):06X}："
                    f"{raw.hex(' ').upper()}；名称Token：{name_raw.hex(' ').upper()}。"
                    "这里显示的是实际读取值，00 代表ROM原值为零。"
                )
            else:
                self.rom_summary.setText("请选择武器以读取完整原始记录。")
            self.weapon_skill.setEnabled(self._extras_enabled)
            self.distance_correction.setEnabled(self._extras_enabled)
            self.weapon_animation.set_record(self.project, record_id)
        except ValueError as error:
            self.extra_status.setText(str(error))
            self.rom_summary.setText(f"原始记录读取失败：{error}")
            self.weapon_animation.setEnabled(False)
        finally:
            self._loading_details = False
        self.refresh_usage()
        self._update_pending_state()

    def _update_pending_state(self) -> None:
        if self._loading_details:
            return
        super()._update_pending_state()
        animation = getattr(self, "weapon_animation", None)
        if animation is None or self.project is None or self.current_id is None:
            return
        extra_pending = self._extras_enabled and weapon_extra_values(self.project, self.current_id) != (self.weapon_skill.currentData(), self.distance_correction.value())
        if extra_pending or (animation.isEnabled() and animation.has_pending_changes()):
            self.apply_button.setEnabled(True)
            self.pending_state.setText("● 有尚未暂存的武器特技、距离补正或动画改动")

    def apply_record(self) -> None:
        if self.project is None or self.current_id is None:
            return
        try:
            if self.weapon_animation.isEnabled():
                self.weapon_animation.pending_patches()  # Validate every draft before mutating.
            with self.project.transaction(f"武器 ${self.current_id:02X} · 完整表单"):
                for field in WEAPON_FIELDS:
                    self.project.set_weapon_value(self.current_id, field.key, self.fields[field.key].value())
                if self._extras_enabled:
                    apply_verified_patches(self.project, weapon_extra_patches(self.project, self.current_id,
                                           int(self.weapon_skill.currentData()), self.distance_correction.value()), "武器特技与距离补正")
                if self.project.supports_weapon_names:
                    self.project.set_weapon_name_reference(self.current_id, int(self.name_reference.currentData()))
                if self.weapon_animation.isEnabled():
                    self.weapon_animation.apply_pending()
            self.load_record(self.current_id)
            self.project_changed.emit(f"已更新武器 ${self.current_id:02X}")
        except Exception as error:
            self.show_error(error)

    def duplicate_record(self) -> None:
        if self.project is None or self.current_id is None or not self.commit_pending_changes():
            return
        options = [f"${index:02X} · {self.project.weapon_display_name(index)}"
                   for index in range(1, self.project.weapon_count) if index != self.current_id]
        selected, accepted = QInputDialog.getItem(self, "复制武器属性与名称", "复制到（目标的共用属性记录同步改变）：", options, 0, False)
        if not accepted:
            return
        target = int(selected[1:3], 16)
        try:
            skill, distance = weapon_extra_values(self.project, self.current_id)
            weapon_extra_patches(self.project, target, skill, distance)
            sources = self.project.weapon_name_source_ids(self.current_id)
            with self.project.transaction(f"复制武器 ${self.current_id:02X} 到 ${target:02X}"):
                for field in WEAPON_FIELDS:
                    self.project.set_weapon_value(target, field.key, self.project.get_weapon_value(self.current_id, field.key))
                apply_verified_patches(self.project, weapon_extra_patches(self.project, target, skill, distance), "复制武器特技与距离补正")
                if sources:
                    self.project.set_weapon_name_reference(target, sources[0])
            self.project_changed.emit(f"已复制武器属性与名称到 ${target:02X}")
        except Exception as error:
            self.show_error(error)

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
