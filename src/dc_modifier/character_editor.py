from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QImage, QPixmap
from PySide6.QtWidgets import (
    QCheckBox, QFileDialog, QFormLayout, QGridLayout, QGroupBox, QHBoxLayout,
    QComboBox, QHeaderView, QLabel, QMessageBox, QPushButton, QSpinBox,
    QTableWidget, QTableWidgetItem, QTabWidget, QVBoxLayout, QWidget,
)

from fc_editor.codecs.character_attributes import (
    CharacterAttributes, CharacterAttributesCodec, PortraitRecord, SPIRIT_NAMES,
    apply_verified_patches,
)
from fc_editor.codecs.character_dialogue import (
    CharacterDialogueRecord, DialogueBinding, DialogueRule,
    TransformDialogueBinding, VALID_SEGMENTS,
)
from .database_graphics import palette_color


class CharacterDialogueWidget(QGroupBox):
    changed = Signal()

    DIRECT_LABELS = (
        "攻击命中", "攻击受阻", "防御成功", "防御未受伤",
        "防御轻伤", "防御中伤", "防御重伤", "被击落",
    )
    RULE_LABELS = ("一次攻击", "二次攻击", "三次攻击")

    def __init__(self) -> None:
        super().__init__("战斗台词绑定")
        self.project = None
        self.character_id = None
        self.codec = None
        self._baseline = None
        self._loading = False
        outer = QVBoxLayout(self)
        self.status = QLabel(
            "文字段与对话编号指向“战斗对话”页正文；特殊攻击保留现有规则条数。"
        )
        self.status.setObjectName("hintText")
        self.status.setWordWrap(True)
        outer.addWidget(self.status)
        tabs = QTabWidget()
        outer.addWidget(tabs)

        direct_page = QWidget()
        grid = QGridLayout(direct_page)
        self.direct_controls: list[tuple[QComboBox, QSpinBox]] = []
        for index, label in enumerate(self.DIRECT_LABELS):
            segment = QComboBox()
            for value in VALID_SEGMENTS:
                segment.addItem(f"文字段 ${value:02X}", value)
            dialogue = QSpinBox()
            dialogue.setRange(0, 0xFF)
            dialogue.setPrefix("$")
            dialogue.setDisplayIntegerBase(16)
            segment.currentIndexChanged.connect(self._changed)
            dialogue.valueChanged.connect(self._changed)
            row, column = index % 4, (index // 4) * 3
            grid.addWidget(QLabel(label), row, column)
            grid.addWidget(segment, row, column + 1)
            grid.addWidget(dialogue, row, column + 2)
            self.direct_controls.append((segment, dialogue))
        tabs.addTab(direct_page, "直接台词（2攻/6防）")

        self.rule_tables: list[QTableWidget] = []
        for label in self.RULE_LABELS:
            table = QTableWidget(0, 4)
            table.setHorizontalHeaderLabels(
                ("人物/机体条件", "武器/机体条件", "文字段", "对话编号")
            )
            table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
            table.verticalHeader().setVisible(False)
            table.cellChanged.connect(self._changed)
            self.rule_tables.append(table)
            tabs.addTab(table, label)

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

    @staticmethod
    def _hex_item(value: int) -> QTableWidgetItem:
        item = QTableWidgetItem(f"{value:02X}")
        item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
        return item

    @staticmethod
    def _parse_hex(item: QTableWidgetItem | None, label: str) -> int:
        if item is None:
            raise ValueError(f"{label}不能为空。")
        text = item.text().strip().removeprefix("$")
        try:
            value = int(text, 16)
        except ValueError as error:
            raise ValueError(f"{label}必须是 00—FF 的十六进制数。") from error
        if not 0 <= value <= 0xFF:
            raise ValueError(f"{label}必须是 00—FF 的十六进制数。")
        return value

    def _changed(self, *_args) -> None:
        if not self._loading:
            self.changed.emit()

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
        row = self.transform_table.rowCount()
        self.transform_table.insertRow(row)
        for column, value in enumerate((0x00, 0xFF, 0x00)):
            self.transform_table.setItem(row, column, self._hex_item(value))
        self.transform_table.setCurrentCell(row, 0)
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
                        table.setItem(row, column, self._hex_item(value))
            transforms = codec.character_transform_bindings(
                character_id, project.working
            )
            self.transform_table.setRowCount(len(transforms))
            for row, binding in enumerate(transforms):
                for column, value in enumerate((
                    binding.unit_start, binding.unit_end, binding.dialogue,
                )):
                    self.transform_table.setItem(row, column, self._hex_item(value))
            aliases = codec.shared_ids(character_id, project.working)
            self.status.setText(
                "现有规则可逐字节编辑；为保持已验证记录边界，暂不增删规则。"
                f" 共用此台词记录：{'、'.join(f'{item:03d}' for item in aliases)}。"
            )
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
        patch = self.codec.patch(
            self.project.working, self.character_id, self.record()
        )
        transform_patch = self.codec.transform_patch(
            self.project.working, self.character_id, self.transform_records()
        )
        return tuple(
            item for item in (patch, transform_patch) if item is not None
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
        patch = self.codec.patch(
            self.project.working,
            self.character_id,
            self.codec.read(self.character_id, self.project.original),
        )
        if patch is not None:
            apply_verified_patches(self.project, (patch,), "还原人物战斗台词绑定")
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
        self.status = QLabel()
        self.status.setWordWrap(True)
        outer.addWidget(self.status)
        self.raw_details = QLabel()
        self.raw_details.setObjectName("hintText")
        self.raw_details.setWordWrap(True)
        self.raw_details.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        outer.addWidget(self.raw_details)
        tabs = QTabWidget()
        outer.addWidget(tabs)
        attributes_page = QWidget()
        attributes_row = QHBoxLayout(attributes_page)
        attributes_row.setContentsMargins(4, 4, 4, 4)
        tabs.addTab(attributes_page, "人物属性与精神")

        attributes = QGroupBox("人物属性")
        grid = QGridLayout(attributes)
        self.fields = {}
        specs = (("spirit", "精神值", 255), ("growth", "精神成长", 250),
                 ("strength", "强度补正", 255), ("movement", "机动补正", 127),
                 ("defense", "防御补正", 255), ("hp", "HP补正", 255),
                 ("speed", "速度补正", 255))
        for index, (key, label, maximum) in enumerate(specs):
            spin = QSpinBox()
            spin.setRange(0, maximum)
            spin.setMaximumWidth(70)
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
        self.attribute_sharing = QLabel()
        self.attribute_sharing.setWordWrap(True)
        grid.addWidget(self.attribute_sharing, 5, 0, 1, 4)
        attributes_row.addWidget(attributes, 1)

        spirits = QGroupBox("精神列表与消耗")
        grid = QGridLayout(spirits)
        self.spirits = []
        self.costs = []
        for index, name in enumerate(SPIRIT_NAMES):
            check = QCheckBox(name)
            check.setObjectName(f"character_spirit_{index}")
            cost = QSpinBox()
            cost.setRange(0, 255)
            cost.setMaximumWidth(62)
            cost.setObjectName(f"spirit_cost_{index}")
            check.toggled.connect(self._changed)
            cost.valueChanged.connect(self._changed)
            row, col = index % 8, index // 8 * 2
            grid.addWidget(check, row, col)
            grid.addWidget(cost, row, col + 1)
            self.spirits.append(check)
            self.costs.append(cost)
        hint = QLabel("消耗值全人物共用；游戏精神菜单最多显示 6 项，按列表顺序取前 6 项。")
        hint.setWordWrap(True)
        grid.addWidget(hint, 8, 0, 1, 6)
        attributes_row.addWidget(spirits, 2)

        portrait = QGroupBox("头像设置")
        form = QFormLayout(portrait)
        portrait_controls = QWidget()
        portrait_grid = QGridLayout(portrait_controls)
        portrait_grid.setContentsMargins(0, 0, 0, 0)
        self.portrait_fields = {}
        for index, (key, label, minimum, maximum) in enumerate((
            ("front_bank", "正面图库", 0, 255), ("front_slot", "正面位置", 1, 4),
            ("back_bank", "背景图库寄存器", 0, 255), ("back_slot", "背景位置（2KB内）", 1, 8),
            ("color0", "头像颜色1", 0, 63), ("color1", "头像颜色2", 0, 63),
            ("color2", "头像颜色3", 0, 63),
        )):
            spin = QSpinBox()
            spin.setRange(minimum, maximum)
            spin.setMaximumWidth(100)
            spin.setObjectName(f"portrait_{key}")
            spin.valueChanged.connect(self._changed)
            self.portrait_fields[key] = spin
            portrait_grid.addWidget(QLabel(label), index // 2, index % 2 * 2)
            portrait_grid.addWidget(spin, index // 2, index % 2 * 2 + 1)
        form.addRow(portrait_controls)
        self.shared_portrait = QCheckBox("同时修改共用头像记录")
        self.shared_portrait.toggled.connect(self._changed)
        form.addRow(self.shared_portrait)
        self.portrait_sharing = QLabel()
        self.portrait_sharing.setWordWrap(True)
        form.addRow(self.portrait_sharing)
        preview = QWidget()
        row = QHBoxLayout(preview)
        row.setContentsMargins(0, 0, 0, 0)
        self.front_preview = QLabel()
        self.back_preview = QLabel()
        self.composite_preview = QLabel()
        row.addWidget(QLabel("正面"))
        row.addWidget(self.front_preview)
        row.addWidget(QLabel("背景"))
        row.addWidget(self.back_preview)
        row.addWidget(QLabel("合成"))
        row.addWidget(self.composite_preview)
        row.addStretch()
        form.addRow(preview)
        uploads = QWidget()
        row = QHBoxLayout(uploads)
        row.setContentsMargins(0, 0, 0, 0)
        for kind, text in (("front", "上传正面…"), ("back", "上传背景…")):
            button = QPushButton(text)
            button.clicked.connect(lambda _checked=False, kind=kind: self._upload_image(kind))
            row.addWidget(button)
        row.addStretch()
        form.addRow(uploads)
        hint = QLabel("头像由真实 CHR 图块预览。背景使用 2KB 图库窗口，寄存器低位由硬件忽略；位置 5—8 使用后半个 1KB。")
        hint.setWordWrap(True)
        form.addRow(hint)
        tabs.addTab(portrait, "头像设置与上传")

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
                (portrait.back_bank & 0xFE) * 64 + portrait.back_slot * 16,
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
            for key, spin in self.portrait_fields.items():
                value = portrait.colors[int(key[-1])] if key.startswith("color") else getattr(portrait, key)
                spin.setValue(value + (1 if key.endswith("slot") else 0))
            self.shared_attributes.setChecked(False)
            self.shared_portrait.setChecked(False)
            for label, is_portrait in ((self.attribute_sharing, False), (self.portrait_sharing, True)):
                ids = codec.shared_ids(character_id, portrait=is_portrait)
                names = "、".join(f"{item:03d}" for item in ids[:16])
                label.setText(f"共用此记录：{names}{'…' if len(ids) > 16 else ''}（{len(ids)} 个）。独立修改需要原数据池有空间。")
                label.setToolTip("、".join(f"{item:03d} {project.character_display_name(item)}" for item in ids if item < project.profile.character_name_count))
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
        return PortraitRecord(tuple(values[f"color{index}"] for index in range(3)),
                              values["front_bank"], values["back_bank"], values["front_slot"] - 1, values["back_slot"] - 1)

    def pending_patches(self):
        if self.codec is None or self.character_id is None:
            return ()
        patches = (self.codec.patches(self.character_id, self.attribute_record(), shared=self.shared_attributes.isChecked())
                   + self.codec.portrait_patches(self.character_id, self.portrait_record(), shared=self.shared_portrait.isChecked())
                   + (self.codec.cost_patch(tuple(cost.value() for cost in self.costs)),))
        portrait = self.portrait_record()
        targets = {"front": portrait.front_bank * 64 + portrait.front_slot * 16,
                   "back": (portrait.back_bank & 0xFE) * 64 + portrait.back_slot * 16}
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
        front = self._render_preview(self.front_preview, record.front_bank * 64 + record.front_slot * 16, record.colors, transparent=True)
        back = self._render_preview(self.back_preview, (record.back_bank & 0xFE) * 64 + record.back_slot * 16, (0, 0x10, 0x20))
        if front is not None and back is not None:
            for y in range(32):
                for x in range(32):
                    if front.pixelColor(x, y).alpha():
                        back.setPixelColor(x, y, front.pixelColor(x, y))
            self.composite_preview.setPixmap(QPixmap.fromImage(back.scaled(96, 96)))

    def _render_preview(self, label: QLabel, first_tile: int, palette: tuple[int, ...], *, transparent: bool = False) -> QImage | None:
        if first_tile + 16 > self.project.chr_tile_count:
            label.clear()
            label.setText("图库越界")
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
        label.setPixmap(QPixmap.fromImage(image.scaled(96, 96)))
        return image

    def import_portrait_image(self, kind: str, image: QImage) -> None:
        if self.codec is None or kind not in ("front", "back"):
            raise ValueError("请先选择人物及正面或背景头像。")
        if image.isNull() or image.width() != 32 or image.height() != 32:
            raise ValueError("头像图片必须为 32×32 像素。")
        record = self.portrait_record()
        first_tile = record.front_bank * 64 + record.front_slot * 16 if kind == "front" else (record.back_bank & 0xFE) * 64 + record.back_slot * 16
        self.project.chr_codec.range_bytes(first_tile, 16, bytes(self.project.working))
        colors = (palette_color(0x0F), *(palette_color(value) for value in (record.colors if kind == "front" else (0, 0x10, 0x20))))
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
