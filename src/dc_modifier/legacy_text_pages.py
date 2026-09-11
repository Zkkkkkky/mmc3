from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QComboBox, QHBoxLayout, QLabel, QLineEdit, QListWidget,
    QListWidgetItem, QMessageBox, QPlainTextEdit, QPushButton,
    QSplitter, QVBoxLayout, QWidget,
    QTableWidget, QTableWidgetItem, QHeaderView,
    QSpinBox, QFormLayout, QTabWidget,
)

from fc_editor.codecs.legacy_scenario import LegacyScenarioCodec
from fc_editor.codecs.legacy_text import LegacyTextCodec, decode_legacy_text
from fc_editor.codecs.legacy_text_growth import LegacyGrowthCodec
from fc_editor.codecs.legacy_text_shop import LegacyShopCodec

from .pages import ProjectPage


class LegacyTextPage(ProjectPage):
    """Shared real-ROM text editor for battle dialogue, system and item text."""

    def __init__(self, group_keys: tuple[str, ...] = ("battle_00", "battle_01", "battle_04", "battle_05")) -> None:
        super().__init__()
        self.group_keys = group_keys
        self.codec: LegacyTextCodec | None = None
        self._drafts: dict[tuple[str, int, int], str] = {}
        self._selected: tuple[str, int, int] | None = None
        self._loading = False
        self._transaction_conflict_checker = None
        layout = QVBoxLayout(self)
        splitter = QSplitter()
        left = QWidget()
        left_layout = QVBoxLayout(left)
        self.group_combo = QComboBox()
        self.search_edit = QLineEdit()
        self.search_edit.setPlaceholderText("查找文字或编号")
        self.record_list = QListWidget()
        self.record_list.setAlternatingRowColors(True)
        left_layout.addWidget(QLabel("对话段 / 文字记录"))
        left_layout.addWidget(self.group_combo)
        left_layout.addWidget(self.search_edit)
        left_layout.addWidget(self.record_list, 1)
        right = QWidget()
        right_layout = QVBoxLayout(right)
        self.variant_list = QListWidget()
        self.variant_list.setMaximumHeight(180)
        self.text_edit = QPlainTextEdit()
        self.status_label = QLabel()
        self.status_label.setWordWrap(True)
        right_layout.addWidget(QLabel("文字编辑 · 随机对话的各条正文"))
        right_layout.addWidget(self.variant_list)
        right_layout.addWidget(self.text_edit, 1)
        right_layout.addWidget(self.status_label)
        splitter.addWidget(left)
        splitter.addWidget(right)
        splitter.setSizes([300, 650])
        layout.addWidget(splitter, 1)
        buttons = QHBoxLayout()
        self.apply_button = QPushButton("暂存文字修改")
        self.reset_button = QPushButton("还原当前文字")
        buttons.addStretch()
        buttons.addWidget(self.apply_button)
        buttons.addWidget(self.reset_button)
        layout.addLayout(buttons)
        self.group_combo.currentIndexChanged.connect(self._populate_records)
        self.record_list.currentRowChanged.connect(self._populate_variants)
        self.variant_list.currentRowChanged.connect(self._select_variant)
        self.text_edit.textChanged.connect(self._text_changed)
        self.search_edit.textChanged.connect(self._filter)
        self.apply_button.clicked.connect(self.apply_changes)
        self.reset_button.clicked.connect(self.reset_current)

    def refresh(self) -> None:
        if self.has_pending_draft:
            return
        self._loading = True
        old_group = self.group_combo.currentData()
        old_index = self.record_list.currentRow()
        self._selected = None
        self.codec = None
        self.group_combo.clear()
        self.record_list.clear()
        self.variant_list.clear()
        self.text_edit.clear()
        if self.project is not None:
            try:
                self.codec = LegacyTextCodec(self.project.working)
                for key in self.group_keys:
                    self.group_combo.addItem(self.codec.group_by_key[key].label, key)
                index = self.group_combo.findData(old_group)
                self.group_combo.setCurrentIndex(max(0, index))
            except (ValueError, IndexError) as error:
                self.status_label.setText(str(error))
        self.setEnabled(self.codec is not None)
        self._loading = False
        self._populate_records()
        if 0 <= old_index < self.record_list.count():
            self.record_list.setCurrentRow(old_index)

    def _populate_records(self, *_args) -> None:
        if self._loading:
            return
        self._loading = True
        self.record_list.clear()
        key = self.group_combo.currentData()
        if self.codec is not None and key is not None:
            for index in range(self.codec.group_by_key[key].count):
                text = self._drafts.get((key, index, 0), self.codec.record(key, index).text)
                self.record_list.addItem(f"{index:03d}: {text.replace(chr(10), ' ↵ ').replace('⟦结束⟧', '')}")
        self._loading = False
        self.record_list.setCurrentRow(0 if self.record_list.count() else -1)
        self._populate_variants()
        self._filter()

    def _populate_variants(self, *_args) -> None:
        if self._loading:
            return
        self._loading = True
        self.variant_list.clear()
        key = self.group_combo.currentData()
        index = self.record_list.currentRow()
        if self.codec is not None and key is not None and index >= 0:
            for variant in range(self.codec.variant_count(key, index)):
                text = self._drafts.get((key, index, variant), self.codec.record(key, index, variant).text)
                self.variant_list.addItem(f"{variant:03d}: {text.replace(chr(10), ' ↵ ').replace('⟦结束⟧', '')}")
        self._loading = False
        self.variant_list.setCurrentRow(0 if self.variant_list.count() else -1)
        self._select_variant()

    def _select_variant(self, *_args) -> None:
        if self._loading:
            return
        key = self.group_combo.currentData()
        index = self.record_list.currentRow()
        variant = self.variant_list.currentRow()
        self._selected = (key, index, variant) if self.codec is not None and key is not None and min(index, variant) >= 0 else None
        self._loading = True
        self.text_edit.setPlainText(self._drafts.get(self._selected, self.codec.record(*self._selected).text) if self._selected is not None else "")
        self._loading = False
        self._update_status()

    def _text_changed(self) -> None:
        if self._loading or self._selected is None or self.codec is None:
            return
        text = self.text_edit.toPlainText()
        if text == self.codec.record(*self._selected).text:
            self._drafts.pop(self._selected, None)
        else:
            self._drafts[self._selected] = text
        self._update_status()

    def _filter(self, *_args) -> None:
        query = self.search_edit.text().casefold()
        for index in range(self.record_list.count()):
            item = self.record_list.item(index)
            item.setHidden(query not in item.text().casefold())

    @property
    def has_pending_draft(self) -> bool:
        return bool(self._drafts)

    transaction_sync_group = "rom_text"

    @property
    def pending_draft_keys(self) -> frozenset[tuple[str, int]]:
        return frozenset(("rom_offset", self.codec.record(*key).file_offset) for key in self._drafts) if self.codec else frozenset()

    @property
    def pending_draft_key(self):
        return next(iter(self.pending_draft_keys), None)

    def set_transaction_conflict_checker(self, checker) -> None:
        self._transaction_conflict_checker = checker

    def _patches(self):
        if self.project is None:
            return ()
        codec = LegacyTextCodec(self.project.working, capacity_data=self.project.original)
        by_offset = {}
        for identity, text in self._drafts.items():
            if self.codec is not None and codec.record(*identity).raw != self.codec.record(*identity).raw:
                raise ValueError("当前文字已在其他页面修改，请先还原本页草稿再重新编辑。")
            patch = codec.replacement_patch(*identity, text)
            if patch[0] in by_offset and by_offset[patch[0]] != patch:
                raise ValueError("共用同一文字的两个编号存在不同草稿，请保留一份修改。")
            by_offset[patch[0]] = patch
        return tuple(by_offset.values())

    @property
    def pending_draft_error(self) -> str | None:
        if not self.has_pending_draft:
            return None
        if self._transaction_conflict_checker is not None:
            conflict = self._transaction_conflict_checker(self)
            if conflict:
                return conflict
        try:
            self._patches()
        except (ValueError, IndexError) as error:
            return str(error)
        return None

    def _update_status(self) -> None:
        error = self.pending_draft_error
        self.apply_button.setEnabled(self.has_pending_draft and error is None)
        self.reset_button.setEnabled(self._selected is not None)
        if error:
            self.status_label.setText(error)
        elif self.codec is not None and self._selected is not None:
            record = self.codec.record(*self._selected)
            self.status_label.setText(f"原记录 {len(record.raw)} 字节；保留控制码和结束码，可在原容量内修改正文。共用此正文的条目：{len(record.shared_by)}。")

    def apply_changes(self) -> bool:
        if self.project is None:
            return False
        try:
            if self.pending_draft_error:
                raise ValueError(self.pending_draft_error)
            patches = self._patches()
            if patches:
                self.project._apply_legacy_global_patches(patches, "文字修改")
        except (ValueError, IndexError) as error:
            QMessageBox.warning(self, "文字未暂存", str(error))
            return False
        self._drafts.clear()
        self.refresh()
        if patches:
            self.project_changed.emit("文字修改")
        return True

    def commit_pending_changes(self) -> bool:
        return self.apply_changes() if self.has_pending_draft else True

    def discard_pending_changes(self) -> None:
        self._drafts.clear()
        self.refresh()

    def reset_current(self) -> None:
        if self._selected is not None and self.project is not None:
            self.text_edit.setPlainText(LegacyTextCodec(self.project.original).record(*self._selected).text)


class LegacyScenarioEventsPage(ProjectPage):
    def __init__(self, phase: int = 0) -> None:
        super().__init__()
        self.phase = phase
        self.scenario_id = 0
        self.codec = None
        self._instructions = ()
        self._drafts: dict[int, str] = {}
        self._loading = False
        self._transaction_conflict_checker = None
        layout = QVBoxLayout(self)
        self.record_list = QListWidget()
        self.record_list.setAlternatingRowColors(True)
        self.raw_edit = QLineEdit()
        self.raw_edit.setPlaceholderText("事件字节（十六进制）")
        self.status_label = QLabel()
        self.status_label.setWordWrap(True)
        self.apply_button = QPushButton("暂存事件参数")
        layout.addWidget(self.record_list, 1)
        layout.addWidget(self.raw_edit)
        layout.addWidget(self.status_label)
        layout.addWidget(self.apply_button)
        self.record_list.currentRowChanged.connect(self._select)
        self.raw_edit.textChanged.connect(self._changed)
        self.apply_button.clicked.connect(self.apply_changes)

    def set_scenario(self, scenario_id: int) -> None:
        if self.has_pending_draft and not self.commit_pending_changes():
            return
        self.scenario_id = scenario_id
        self.refresh()

    def refresh(self) -> None:
        if self.has_pending_draft:
            return
        self._loading = True
        self.record_list.clear()
        self.codec = None
        self._instructions = ()
        if self.project is not None:
            try:
                self.codec = LegacyScenarioCodec(self.project.working)
                self._instructions = self.codec.instructions(self.scenario_id, self.phase)
                for index, instruction in enumerate(self._instructions):
                    extra = instruction.raw[1:].hex(" ").upper()
                    if instruction.opcode in (0x40, 0x41, 0x42, 0x44):
                        selector = instruction.raw[-2] + 0x30
                        text_id = instruction.raw[-1]
                        try:
                            extra = decode_legacy_text(self.project.get_story_text(selector, text_id).raw).replace("\n", " ").replace("⟦结束⟧", "")
                        except (KeyError, ValueError, IndexError):
                            pass
                    self.record_list.addItem(f"{index:03d}: {instruction.label}：{extra}")
            except (ValueError, IndexError) as error:
                self.status_label.setText(str(error))
        self._loading = False
        self.setEnabled(self.codec is not None)
        self.record_list.setCurrentRow(0 if self.record_list.count() else -1)
        self._select()

    def _select(self, *_args) -> None:
        if self._loading:
            return
        row = self.record_list.currentRow()
        self._loading = True
        if 0 <= row < len(self._instructions):
            instruction = self._instructions[row]
            self.raw_edit.setText(self._drafts.get(instruction.file_offset, instruction.raw.hex(" ").upper()))
            self.status_label.setText(f"{LegacyScenarioCodec.PHASE_LABELS[self.phase]} · Bank ${instruction.bank:02X} · ${instruction.address:04X} · 原指令 {len(instruction.raw)} 字节")
        else:
            self.raw_edit.clear()
        self._loading = False
        self.apply_button.setEnabled(self.has_pending_draft)

    def _changed(self, *_args) -> None:
        if self._loading:
            return
        row = self.record_list.currentRow()
        if not 0 <= row < len(self._instructions):
            return
        instruction = self._instructions[row]
        try:
            raw = bytes.fromhex(self.raw_edit.text())
        except ValueError:
            raw = b""
        if raw == instruction.raw:
            self._drafts.pop(instruction.file_offset, None)
        else:
            self._drafts[instruction.file_offset] = self.raw_edit.text()
        error = self.pending_draft_error
        if error:
            self.status_label.setText(error)
        self.apply_button.setEnabled(self.has_pending_draft and error is None)

    @property
    def has_pending_draft(self) -> bool:
        return bool(self._drafts)

    transaction_sync_group = "chapter_event"

    @property
    def pending_draft_keys(self) -> frozenset[tuple[str, int]]:
        return frozenset(("rom_offset", offset) for offset in self._drafts)

    @property
    def pending_draft_key(self):
        return next(iter(self.pending_draft_keys), None)

    def set_transaction_conflict_checker(self, checker) -> None:
        self._transaction_conflict_checker = checker

    def _patches(self):
        codec = LegacyScenarioCodec(self.project.working) if self.project is not None and self.has_pending_draft else self.codec
        result = []
        for item in self._instructions:
            if item.file_offset not in self._drafts:
                continue
            try:
                raw = bytes.fromhex(self._drafts[item.file_offset])
            except ValueError as error:
                raise ValueError("事件字节必须是完整的十六进制数，例如 59 88。") from error
            result.append(codec.replacement_patch(item, raw))
        return tuple(result)

    @property
    def pending_draft_error(self) -> str | None:
        if self.has_pending_draft and self._transaction_conflict_checker is not None:
            conflict = self._transaction_conflict_checker(self)
            if conflict:
                return conflict
        try:
            self._patches()
        except (ValueError, IndexError) as error:
            return str(error)
        return None

    def apply_changes(self) -> bool:
        if self.project is None:
            return False
        try:
            if self.pending_draft_error:
                raise ValueError(self.pending_draft_error)
            patches = self._patches()
            self.project._apply_legacy_global_patches(patches, "章节事件参数")
        except (ValueError, IndexError) as error:
            QMessageBox.warning(self, "事件未暂存", str(error))
            return False
        self._drafts.clear()
        self.refresh()
        if patches:
            self.project_changed.emit("章节事件参数")
        return True

    def commit_pending_changes(self) -> bool:
        return self.apply_changes() if self.has_pending_draft else True

    def discard_pending_changes(self) -> None:
        self._drafts.clear()
        self.refresh()


class LegacyGrowthPage(ProjectPage):
    transaction_sync_group = "growth_table"

    def __init__(self) -> None:
        super().__init__()
        self.codec = None
        self._drafts = {}
        self._loading = False
        self._transaction_conflict_checker = None
        layout = QVBoxLayout(self)
        self.growth_combo = QComboBox()
        self.growth_combo.addItems([str(value) for value in range(201, 254)])
        self.growth_table = QTableWidget(99, 2)
        self.growth_table.setHorizontalHeaderLabels(("等级", "成长数值"))
        self.growth_table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.growth_table.verticalHeader().hide()
        self.growth_table.setAlternatingRowColors(True)
        self.status_label = QLabel()
        self.status_label.setWordWrap(True)
        self.apply_button = QPushButton("暂存成长方式")
        self.reset_button = QPushButton("还原当前成长")
        layout.addWidget(QLabel("成长方式 · 每级数值 0—15"))
        layout.addWidget(self.growth_combo)
        layout.addWidget(self.growth_table, 1)
        layout.addWidget(self.status_label)
        layout.addWidget(self.apply_button)
        layout.addWidget(self.reset_button)
        self.growth_combo.currentIndexChanged.connect(self._load)
        self.growth_table.itemChanged.connect(self._changed)
        self.apply_button.clicked.connect(self.apply_changes)
        self.reset_button.clicked.connect(self.reset_current)

    def refresh(self) -> None:
        if self.has_pending_draft:
            return
        try:
            self.codec = LegacyGrowthCodec(self.project.working) if self.project else None
        except ValueError as error:
            self.codec = None
            self.status_label.setText(str(error))
        self.setEnabled(self.codec is not None)
        self._load()

    def _load(self, *_args) -> None:
        if self.codec is None:
            return
        growth_id = self.growth_combo.currentIndex() + 201
        record = self.codec.record(growth_id)
        values = self._drafts.get(growth_id, tuple(map(str, record.values)))
        self._loading = True
        for index, value in enumerate(values):
            label = QTableWidgetItem(str(index + 1))
            label.setFlags(label.flags() & ~Qt.ItemFlag.ItemIsEditable)
            self.growth_table.setItem(index, 0, label)
            self.growth_table.setItem(index, 1, QTableWidgetItem(value))
        self._loading = False
        self.status_label.setText(f"成长编号 {growth_id}；共用此记录的编号：" + "、".join(map(str, record.shared_ids)))
        self.apply_button.setEnabled(self.has_pending_draft and self.pending_draft_error is None)

    def _changed(self, *_args) -> None:
        if self._loading or self.codec is None:
            return
        growth_id = self.growth_combo.currentIndex() + 201
        values = tuple(self.growth_table.item(i, 1).text() for i in range(99))
        if values == tuple(map(str, self.codec.record(growth_id).values)):
            self._drafts.pop(growth_id, None)
        else:
            self._drafts[growth_id] = values
        error = self.pending_draft_error
        if error:
            self.status_label.setText(error)
        self.apply_button.setEnabled(self.has_pending_draft and error is None)

    @property
    def has_pending_draft(self) -> bool:
        return bool(self._drafts)

    @property
    def pending_draft_keys(self):
        return frozenset(("rom_offset", self.codec.record(key).file_offset) for key in self._drafts) if self.codec else frozenset()

    @property
    def pending_draft_key(self):
        return next(iter(self.pending_draft_keys), None)

    def set_transaction_conflict_checker(self, checker) -> None:
        self._transaction_conflict_checker = checker

    def _patches(self):
        codec = LegacyGrowthCodec(self.project.working)
        patches = {}
        for growth_id, values in self._drafts.items():
            if codec.record(growth_id).raw != self.codec.record(growth_id).raw:
                raise ValueError("成长方式已在其他页面修改，请先还原草稿。")
            patch = codec.replacement_patch(growth_id, tuple(int(value) for value in values))
            if patch[0] in patches and patch != patches[patch[0]]:
                raise ValueError("共用成长记录存在不同草稿，请只保留一份修改。")
            patches[patch[0]] = patch
        return tuple(patches.values())

    @property
    def pending_draft_error(self) -> str | None:
        if not self.has_pending_draft:
            return None
        if self._transaction_conflict_checker:
            conflict = self._transaction_conflict_checker(self)
            if conflict:
                return conflict
        try:
            self._patches()
        except ValueError as error:
            return str(error)
        return None

    def apply_changes(self) -> bool:
        if self.project is None:
            return False
        try:
            if self.pending_draft_error:
                raise ValueError(self.pending_draft_error)
            patches = self._patches()
            self.project._apply_legacy_global_patches(patches, "成长方式")
        except ValueError as error:
            QMessageBox.warning(self, "成长方式未暂存", str(error))
            return False
        self._drafts.clear()
        self.refresh()
        if patches:
            self.project_changed.emit("成长方式")
        return True

    def commit_pending_changes(self) -> bool:
        return self.apply_changes() if self.has_pending_draft else True

    def discard_pending_changes(self) -> None:
        self._drafts.clear()
        self.refresh()

    def reset_current(self) -> None:
        if self.project is None:
            return
        growth_id = self.growth_combo.currentIndex() + 201
        values = LegacyGrowthCodec(self.project.original).record(growth_id).values
        self._loading = True
        for index, value in enumerate(values):
            self.growth_table.item(index, 1).setText(str(value))
        self._loading = False
        self._changed()


class LegacyShopPage(ProjectPage):
    transaction_sync_group = "rom_text"

    def __init__(self) -> None:
        super().__init__()
        self.codec = None
        self.text_codec = None
        self._drafts = {}
        self._text_drafts = {}
        self._loading = False
        self._transaction_conflict_checker = None
        layout = QVBoxLayout(self)
        self.shop_combo = QComboBox()
        self.shop_combo.addItems([f"商店 {value:02X}" for value in range(0xF0, 0xFF)])
        layout.addWidget(self.shop_combo)
        self.fields = QWidget()
        form = QFormLayout(self.fields)
        self.item_combos = [QComboBox() for _ in range(4)]
        for index, combo in enumerate(self.item_combos):
            form.addRow(f"道具 {index + 1}", combo)
            combo.currentIndexChanged.connect(self._metadata_changed)
        self.clerk_combo = QComboBox()
        self.dialogue_spin = QSpinBox()
        self.dialogue_spin.setRange(0, 214)
        form.addRow("店员", self.clerk_combo)
        form.addRow("对话起始编号", self.dialogue_spin)
        layout.addWidget(self.fields)
        self.dialogue_tabs = QTabWidget()
        self.dialogue_edits = []
        for index, label in enumerate(LegacyShopCodec.LABELS):
            edit = QPlainTextEdit()
            edit.textChanged.connect(lambda index=index: self._text_changed(index))
            self.dialogue_edits.append(edit)
            self.dialogue_tabs.addTab(edit, label)
        layout.addWidget(self.dialogue_tabs, 1)
        self.status_label = QLabel()
        self.status_label.setWordWrap(True)
        layout.addWidget(self.status_label)
        self.apply_button = QPushButton("暂存商店与对话")
        layout.addWidget(self.apply_button)
        self.discard_button = QPushButton("放弃本页草稿")
        layout.addWidget(self.discard_button)
        self.shop_combo.currentIndexChanged.connect(self._load)
        self.clerk_combo.currentIndexChanged.connect(self._metadata_changed)
        self.dialogue_spin.valueChanged.connect(self._dialogue_changed)
        self.apply_button.clicked.connect(self.apply_changes)
        self.discard_button.clicked.connect(self.discard_pending_changes)

    def refresh(self) -> None:
        if self.has_pending_draft:
            return
        self.codec = self.text_codec = None
        if self.project is not None:
            try:
                self.codec = LegacyShopCodec(self.project.working)
                self.text_codec = LegacyTextCodec(self.project.working)
            except ValueError as error:
                self.codec = self.text_codec = None
                self.status_label.setText(str(error))
        self.setEnabled(self.codec is not None and self.text_codec is not None)
        self._loading = True
        for edit in self.dialogue_edits:
            edit.clear()
        for combo in self.item_combos:
            combo.clear()
            if self.project is not None and self.codec is not None:
                for index, raw in enumerate(self.project.get_item_name_records(), 1):
                    combo.addItem(f"{index:02d}: {decode_legacy_text(raw)}", index)
        self.clerk_combo.clear()
        if self.project is not None and self.codec is not None:
            for index in range(0xC8):
                self.clerk_combo.addItem(f"[{index:02X}] {self.project.character_display_name(index)}", index)
        self._loading = False
        self._load()

    def _load(self, *_args) -> None:
        if self._loading or self.codec is None:
            return
        self._loading = True
        shop_id = 0xF0 + self.shop_combo.currentIndex()
        try:
            record = self.codec.record(shop_id)
            clerk, dialogue, items = self._drafts.get(shop_id, (record.clerk_id, record.dialogue_id, record.items))
            self.fields.setEnabled(True)
            self.dialogue_tabs.setEnabled(True)
            self.clerk_combo.setCurrentIndex(clerk)
            self.dialogue_spin.setValue(dialogue)
            for index, combo in enumerate(self.item_combos):
                combo.setEnabled(index < len(items))
                combo.setCurrentIndex(items[index] - 1 if index < len(items) else -1)
            self.status_label.setText(f"商店 {shop_id:02X} · {len(items)} 件商品；七段对话与系统文字共用，按原容量保存。")
        except ValueError as error:
            self.fields.setEnabled(False)
            self.dialogue_tabs.setEnabled(False)
            self.status_label.setText(str(error))
            for edit in self.dialogue_edits:
                edit.clear()
        self._loading = False
        if self.fields.isEnabled():
            self._load_dialogues()
        self.apply_button.setEnabled(self.has_pending_draft and self.pending_draft_error is None)

    def _load_dialogues(self) -> None:
        if self.text_codec is None:
            return
        self._loading = True
        for index, edit in enumerate(self.dialogue_edits):
            text_id = self.dialogue_spin.value() + index
            record = self.text_codec.record("system", text_id)
            edit.setPlainText(self._text_drafts.get(text_id, record.text))
        self._loading = False

    def _metadata_changed(self, *_args) -> None:
        if self._loading or self.codec is None or not self.fields.isEnabled():
            return
        shop_id = 0xF0 + self.shop_combo.currentIndex()
        record = self.codec.record(shop_id)
        values = (self.clerk_combo.currentIndex(), self.dialogue_spin.value(), tuple(combo.currentData() for combo in self.item_combos[:len(record.items)]))
        if values == (record.clerk_id, record.dialogue_id, record.items):
            self._drafts.pop(shop_id, None)
        else:
            self._drafts[shop_id] = values
        self.apply_button.setEnabled(self.has_pending_draft and self.pending_draft_error is None)

    def _dialogue_changed(self, *_args) -> None:
        if not self._loading:
            self._metadata_changed()
            self._load_dialogues()

    def _text_changed(self, index: int) -> None:
        if self._loading or self.text_codec is None:
            return
        text_id = self.dialogue_spin.value() + index
        text = self.dialogue_edits[index].toPlainText()
        if text == self.text_codec.record("system", text_id).text:
            self._text_drafts.pop(text_id, None)
        else:
            self._text_drafts[text_id] = text
        error = self.pending_draft_error
        if error:
            self.status_label.setText(error)
        self.apply_button.setEnabled(self.has_pending_draft and error is None)

    @property
    def has_pending_draft(self) -> bool:
        return bool(self._drafts or self._text_drafts)

    @property
    def pending_draft_keys(self):
        return frozenset([*( ("rom_offset", self.codec.record(key).file_offset) for key in self._drafts), *( ("rom_offset", self.text_codec.record("system", key).file_offset) for key in self._text_drafts)])

    @property
    def pending_draft_key(self):
        return next(iter(self.pending_draft_keys), None)

    def set_transaction_conflict_checker(self, checker) -> None:
        self._transaction_conflict_checker = checker

    def _patches(self):
        if self.project is None:
            return ()
        codec = LegacyShopCodec(self.project.working)
        text_codec = LegacyTextCodec(self.project.working, capacity_data=self.project.original)
        patches = {}
        for shop_id, values in self._drafts.items():
            if codec.record(shop_id).raw != self.codec.record(shop_id).raw:
                raise ValueError("商店已在其他页面变化，请还原草稿后重新编辑。")
            patch = codec.replacement_patch(shop_id, *values)
            patches[patch[0]] = patch
        for text_id, text in self._text_drafts.items():
            if text_codec.record("system", text_id).raw != self.text_codec.record("system", text_id).raw:
                raise ValueError("对话已在其他页面变化，请还原草稿后重新编辑。")
            patch = text_codec.replacement_patch("system", text_id, 0, text)
            if patch[0] in patches and patch != patches[patch[0]]:
                raise ValueError("共用文字存在不同草稿，请只保留一份修改。")
            patches[patch[0]] = patch
        return tuple(patches.values())

    @property
    def pending_draft_error(self) -> str | None:
        if not self.has_pending_draft:
            return None
        if self._transaction_conflict_checker:
            conflict = self._transaction_conflict_checker(self)
            if conflict:
                return conflict
        try:
            self._patches()
        except (ValueError, TypeError) as error:
            return str(error)
        return None

    def apply_changes(self) -> bool:
        if self.project is None:
            return False
        try:
            if self.pending_draft_error:
                raise ValueError(self.pending_draft_error)
            patches = self._patches()
            self.project._apply_legacy_global_patches(patches, "商店与对话")
        except ValueError as error:
            QMessageBox.warning(self, "商店未暂存", str(error))
            return False
        self._drafts.clear()
        self._text_drafts.clear()
        self.refresh()
        if patches:
            self.project_changed.emit("商店与对话")
        return True

    def commit_pending_changes(self) -> bool:
        return self.apply_changes() if self.has_pending_draft else True

    def discard_pending_changes(self) -> None:
        self._drafts.clear()
        self._text_drafts.clear()
        self.refresh()
