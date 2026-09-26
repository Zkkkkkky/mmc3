from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QComboBox, QHBoxLayout, QLabel, QLineEdit, QListWidget,
    QListWidgetItem, QMessageBox, QPlainTextEdit, QPushButton,
    QSplitter, QVBoxLayout, QWidget,
    QTableWidget, QTableWidgetItem, QHeaderView,
    QSpinBox, QFormLayout, QTabWidget, QDialog, QDialogButtonBox,
    QGridLayout, QGroupBox,
)

from fc_editor.codecs.chapter_event import ACTION_FIELDS
from fc_editor.codecs.legacy_scenario import LegacyScenarioCodec
from fc_editor.codecs.legacy_text import LegacyTextCodec, decode_legacy_text
from fc_editor.codecs.legacy_text_growth import LegacyGrowthCodec
from fc_editor.codecs.legacy_text_shop import LegacyShopCodec

from .pages import ProjectPage
from .event_preview import reference_event_preview


class LegacyTextPage(ProjectPage):
    """Shared real-ROM text editor for battle dialogue, system and item text.

    Battle dialogue, system text and item descriptions repack their verified
    fixed pools while preserving aliases and control tokens.
    """

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
        self.splitter = splitter
        left = QWidget()
        left_layout = QVBoxLayout(left)
        self.group_combo = QComboBox()
        self.group_combo.setObjectName("legacyDialogueGroup")
        self.search_edit = QLineEdit()
        self.search_edit.setPlaceholderText("查找文字或编号")
        self.record_list = QListWidget()
        self.record_list.setObjectName("legacyDialogueRecords")
        self.record_list.setAlternatingRowColors(True)
        left_layout.addWidget(QLabel("对话段 / 文字记录"))
        left_layout.addWidget(self.group_combo)
        left_layout.addWidget(self.search_edit)
        left_layout.addWidget(self.record_list, 1)
        right = QWidget()
        right_layout = QVBoxLayout(right)
        self.variant_list = QListWidget()
        self.variant_list.setObjectName("legacyDialogueVariants")
        self.text_edit = QPlainTextEdit()
        self.text_edit.setObjectName("legacyDialogueEditor")
        self.content_edit = QPlainTextEdit()
        self.content_edit.setObjectName("legacyDialogueContent")
        self.content_edit.setReadOnly(True)
        self.content_edit.setToolTip(
            "按参考版“按内容”视图汇总当前对话段；随机分支之间以 ++ 分隔。"
        )
        self.view_tabs = QTabWidget()
        self.view_tabs.setObjectName("legacyDialogueViews")
        self.view_tabs.addTab(self.variant_list, "按列表")
        self.view_tabs.addTab(self.content_edit, "按内容")
        self.status_label = QLabel()
        self.status_label.setWordWrap(True)
        self.editor_title = QLabel("文字编辑")
        right_layout.addWidget(self.editor_title)
        right_layout.addWidget(self.text_edit, 2)
        right_layout.addWidget(self.view_tabs, 1)
        splitter.addWidget(left)
        splitter.addWidget(right)
        splitter.setSizes([300, 650])
        layout.addWidget(splitter, 1)
        buttons = QHBoxLayout()
        self.apply_button = QPushButton("暂存文字修改")
        self.reset_button = QPushButton("还原当前文字")
        self.system_note = QLabel(
            '注："{"加3字节16进制代码等于直接写入3字节16进制\n'
            '    "["为直接写入2字节16进制， "|"为直接写入1字节16进制'
        )
        self.system_note.setObjectName("legacySystemTextNote")
        self.system_note.setStyleSheet("color: #b00020;")
        self.system_note.setVisible(group_keys == ("system",))
        self.add_button = QPushButton("添加")
        self.add_button.setVisible(group_keys == ("system",))
        self.add_button.setToolTip(
            "现有 221 项可在共享池内变长；新增编号会扩大指针表，仍保持关闭。"
            "点击查看容量说明。"
        )
        self.add_button.clicked.connect(self._show_add_boundary)
        buttons.addWidget(self.system_note, 1)
        buttons.addWidget(self.add_button)
        buttons.addStretch()
        buttons.addWidget(self.apply_button)
        buttons.addWidget(self.reset_button)
        layout.addLayout(buttons)
        layout.addWidget(self.status_label)
        self.group_combo.currentIndexChanged.connect(self._populate_records)
        self.record_list.currentRowChanged.connect(self._populate_variants)
        self.variant_list.currentRowChanged.connect(self._select_variant)
        self.text_edit.textChanged.connect(self._text_changed)
        self.search_edit.textChanged.connect(self._filter)
        self.apply_button.clicked.connect(self.apply_changes)
        self.reset_button.clicked.connect(self.reset_current)

    def _show_add_boundary(self) -> None:
        QMessageBox.information(
            self,
            "系统文字容量",
            "当前 221 项系统文字会在固定共享池内自动重排，因此单条可以变长，"
            "但总占用不能超过池容量。\n\n"
            "“添加”会改变指针表项数和后续布局，仍未开放；请编辑已有编号。",
        )

    def set_embedded_single_record_mode(self) -> None:
        """Reduce the generic text page to the editor used by M10's item panel."""

        self.splitter.widget(0).hide()
        self.editor_title.hide()
        self.view_tabs.hide()
        self.system_note.hide()
        self.add_button.hide()
        self.apply_button.hide()
        self.reset_button.hide()
        self.text_edit.setMinimumHeight(86)
        self.text_edit.setMaximumHeight(124)

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
        self.content_edit.clear()
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
        self._update_content_view()
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
        key, index, variant = self._selected
        variant_item = self.variant_list.item(variant)
        if variant_item is not None:
            variant_item.setText(
                f"{variant:03d}: {text.replace(chr(10), ' ↵ ').replace('⟦结束⟧', '')}"
            )
        if variant == 0:
            record_item = self.record_list.item(index)
            if record_item is not None:
                record_item.setText(
                    f"{index:03d}: {text.replace(chr(10), ' ↵ ').replace('⟦结束⟧', '')}"
                )
        self._update_content_view()
        self._update_status()

    def _update_content_view(self) -> None:
        key = self.group_combo.currentData()
        index = self.record_list.currentRow()
        if self.codec is None or key is None or index < 0:
            self.content_edit.clear()
            return
        texts = (
            self._drafts.get(
                (key, index, variant),
                self.codec.record(key, index, variant).text,
            ).replace("⟦结束⟧", "")
            for variant in range(self.codec.variant_count(key, index))
        )
        self.content_edit.setPlainText("++".join(texts))

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
        if self.codec is None:
            return frozenset()
        result: set[tuple[str, int]] = set()
        for identity in self._drafts:
            key, _index, _variant = identity
            if key.startswith("battle_"):
                result.add(("battle_text_bank", self.codec.group_by_key[key].bank))
            else:
                result.add(("legacy_text_pool", key))
        return frozenset(result)

    @property
    def pending_draft_key(self):
        return next(iter(self.pending_draft_keys), None)

    def set_transaction_conflict_checker(self, checker) -> None:
        self._transaction_conflict_checker = checker

    def _patches(self):
        if self.project is None:
            return ()
        codec = LegacyTextCodec(self.project.working, capacity_data=self.project.original)
        for identity, text in self._drafts.items():
            if self.codec is not None and codec.record(*identity).raw != self.codec.record(*identity).raw:
                raise ValueError("当前文字已在其他页面修改，请先还原本页草稿再重新编辑。")
        if self._drafts and all(key.startswith("battle_") for key, _index, _variant in self._drafts):
            return codec.battle_repack_patches(self._drafts)
        simple_keys = {
            key for key, _index, _variant in self._drafts
            if not key.startswith("battle_")
        }
        if self._drafts and len(simple_keys) == 1:
            return codec.simple_group_repack_patches(
                next(iter(simple_keys)), self._drafts
            )
        by_offset = {}
        for identity, text in self._drafts.items():
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
            key, _index, _variant = self._selected
            if key.startswith("battle_"):
                group = self.codec.group_by_key[key]
                usage = self.codec.battle_usage(group.bank, self._drafts)
                self.status_label.setText(
                    f"当前记录 {len(record.raw)} 字节；Bank ${group.bank:02X} "
                    f"安全文字段 {usage.used}/{usage.capacity} 字节，剩余 {usage.free} 字节。"
                    "缩短一条后，释放空间可供同 Bank 其他对话增长；暂存时会整体重排指针。"
                    f"共用此正文的条目：{len(record.shared_by)}。"
                )
            else:
                usage = self.codec.simple_group_usage(key, self._drafts)
                self.status_label.setText(
                    f"当前记录 {len(record.raw)} 字节；共享池 "
                    f"{usage.used}/{usage.capacity} 字节，剩余 {usage.free} 字节。"
                    "保留控制码和结束码后可变长，暂存时自动重排全部指针。"
                    f"共用此正文的条目：{len(record.shared_by)}。"
                )

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


REFERENCE_EVENT_MUSIC_LABELS = (
    "大卫音乐", "盖塔音乐", "加代音乐", "古莲音乐", "吉尔变身音乐",
    "安东音乐", "未知音乐2", "地球我方音乐", "地球敌方音乐", "存档音乐",
    "敌方增援音乐2", "游戏结束音乐", "宇宙我方音乐", "敌方增援音乐1",
    "升级音乐", "吉尔音乐", "瓦尔音乐", "宇宙敌方音乐", "未知音乐1",
    "通关音乐",
)


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
                address_rows = {
                    instruction.address: index
                    for index, instruction in enumerate(self._instructions)
                }
                for index, instruction in enumerate(self._instructions):
                    self.record_list.addItem(
                        self._instruction_summary(index, instruction, address_rows)
                    )
            except (ValueError, IndexError) as error:
                self.status_label.setText(str(error))
        self._loading = False
        self.setEnabled(self.codec is not None)
        self.record_list.setCurrentRow(0 if self.record_list.count() else -1)
        self._select()

    def _story_summary(self, instruction) -> str:
        if self.project is None or len(instruction.raw) < 3:
            return ""
        selector = instruction.raw[-2] + 0x30
        text_id = instruction.raw[-1]
        try:
            text = decode_legacy_text(
                self.project.get_story_text(selector, text_id).raw
            )
        except (KeyError, ValueError, IndexError):
            return f"文本组 ${selector:02X}，编号 ${text_id:02X}"
        return text.replace("\n", " ").replace("⟦结束⟧", "").strip()

    def _named_parameter(self, label: str, value: int) -> str:
        if self.project is None:
            return f"${value:02X}"
        if "人物" in label:
            return f"${value:02X} {self.project.character_display_name(value)}"
        if "机体" in label and value:
            return f"${value:02X} {self.project.unit_display_name(value)}"
        return f"${value:02X}"

    def _character_name(self, value: int) -> str:
        if self.project is None:
            return f"人物 ${value:02X}"
        return self.project.character_display_name(value)

    def _instruction_summary(self, index, instruction, address_rows) -> str:
        return reference_event_preview(
            instruction,
            index=index,
            project=self.project,
            address_rows=address_rows,
            story_summary=self._story_summary,
        )

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
        structural = []
        for item in self._instructions:
            if item.file_offset not in self._drafts:
                continue
            try:
                raw = bytes.fromhex(self._drafts[item.file_offset])
            except ValueError as error:
                raise ValueError("事件字节必须是完整的十六进制数，例如 59 88。") from error
            if len(raw) == len(item.raw):
                result.append(codec.replacement_patch(item, raw))
            else:
                structural.append((item, raw))
        if structural:
            if len(structural) != 1 or result:
                raise ValueError("变长事件一次只能暂存一条；请应用后再编辑下一条。")
            item, raw = structural[0]
            return codec.replacement_patches(item, raw)
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


class _GrowthHexEdit(QPlainTextEdit):
    """Multiline legacy edit with the former single-line compatibility API."""

    def text(self) -> str:
        return self.toPlainText()

    def setText(self, text: str) -> None:  # noqa: N802 - Qt compatibility
        self.setPlainText(text)


class GrowthHexDialog(QDialog):
    """Reference-shaped editor for the first 60 growth nibbles."""

    VALUE_COUNT = 60

    def __init__(
        self,
        values: tuple[int, ...],
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        if len(values) < self.VALUE_COUNT:
            raise ValueError("成长方式至少需要60级数据。")
        self.setWindowTitle("成长属性")
        self.setFixedSize(376, 160)
        self._tail = tuple(values[self.VALUE_COUNT :])
        layout = QVBoxLayout(self)
        self.hex_edit = _GrowthHexEdit()
        self.hex_edit.setPlainText(
            "".join(f"{value:X}" for value in values[: self.VALUE_COUNT])
        )
        self.hex_edit.setFixedHeight(72)
        self.hex_edit.setObjectName("legacyGrowthHex")
        layout.addWidget(self.hex_edit)
        self.length_label = QLabel()
        self.length_label.setObjectName("legacyGrowthHexLength")
        self.length_label.setStyleSheet("color: red;")
        layout.addWidget(self.length_label)
        self.buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok
            | QDialogButtonBox.StandardButton.Cancel
        )
        self.buttons.button(QDialogButtonBox.StandardButton.Ok).setText("确定")
        self.buttons.button(QDialogButtonBox.StandardButton.Cancel).setText("取消")
        self.buttons.accepted.connect(self.accept)
        self.buttons.rejected.connect(self.reject)
        layout.addWidget(self.buttons)
        self.hex_edit.textChanged.connect(self._validate)
        self._validate()

    def _validate(self) -> None:
        text = self.hex_edit.toPlainText().strip()
        valid = len(text) == self.VALUE_COUNT and all(
            character in "0123456789abcdefABCDEF" for character in text
        )
        self.length_label.setText(
            f"长度： {len(text)}"
        )
        self.buttons.button(QDialogButtonBox.StandardButton.Ok).setEnabled(valid)

    def values(self) -> tuple[int, ...]:
        text = self.hex_edit.toPlainText().strip()
        if len(text) != self.VALUE_COUNT or any(
            character not in "0123456789abcdefABCDEF" for character in text
        ):
            raise ValueError("成长属性必须是60位十六进制字符串。")
        return tuple(int(character, 16) for character in text) + self._tail


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
        self.hex_button = QPushButton("成长修改(16进制快捷修改)")
        layout.addWidget(QLabel("成长方式 · 每级数值 0—15"))
        layout.addWidget(self.growth_combo)
        layout.addWidget(self.growth_table, 1)
        layout.addWidget(self.status_label)
        layout.addWidget(self.hex_button)
        layout.addWidget(self.apply_button)
        layout.addWidget(self.reset_button)
        self.growth_combo.currentIndexChanged.connect(self._load)
        self.growth_table.itemChanged.connect(self._changed)
        self.apply_button.clicked.connect(self.apply_changes)
        self.reset_button.clicked.connect(self.reset_current)
        self.hex_button.clicked.connect(self._open_hex_editor)

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

    def _open_hex_editor(self) -> None:
        if self.codec is None:
            return
        growth_id = self.growth_combo.currentIndex() + 201
        source = self._drafts.get(
            growth_id,
            tuple(map(str, self.codec.record(growth_id).values)),
        )
        try:
            values = tuple(int(value) for value in source)
        except ValueError as error:
            QMessageBox.warning(self, "无法打开成长属性", str(error))
            return
        dialog = GrowthHexDialog(values, self)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        edited = dialog.values()
        self._drafts[growth_id] = tuple(map(str, edited))
        self._load()

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
        self.shop_combo.hide()
        self.shop_list = QListWidget()
        self.shop_list.setObjectName("legacyShopList")
        self.shop_list.addItems([f"{value:02X}" for value in range(0xF0, 0xFF)])
        self.shop_list.setMaximumWidth(130)
        self.shop_list.setAlternatingRowColors(True)
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
        settings_group = QGroupBox("商店设置")
        settings_layout = QVBoxLayout(settings_group)
        settings_layout.addWidget(self.fields)
        upper = QHBoxLayout()
        upper.addWidget(self.shop_list)
        upper.addWidget(settings_group, 1)
        layout.addLayout(upper)

        self.dialogue_group = QGroupBox("店员对话")
        dialogue_layout = QGridLayout(self.dialogue_group)
        self.dialogue_edits = []
        for index, label in enumerate(LegacyShopCodec.LABELS):
            edit = QPlainTextEdit()
            edit.setObjectName(f"legacyShopDialogue{index}")
            edit.setMinimumHeight(72)
            edit.textChanged.connect(lambda index=index: self._text_changed(index))
            self.dialogue_edits.append(edit)
            column = index // 3
            slot = index % 3
            dialogue_layout.addWidget(QLabel(f"{label}对话："), slot * 2, column)
            dialogue_layout.addWidget(edit, slot * 2 + 1, column)
        dialogue_note = QLabel("注：店员对话为 7 个顺序对话段，由对话起始编号连续取用。")
        dialogue_note.setWordWrap(True)
        dialogue_layout.addWidget(dialogue_note, 2, 2, 3, 1)
        self.dialogue_tabs = self.dialogue_group
        layout.addWidget(self.dialogue_group, 1)
        self.status_label = QLabel()
        self.status_label.setWordWrap(True)
        layout.addWidget(self.status_label)
        self.apply_button = QPushButton("暂存商店与对话")
        self.discard_button = QPushButton("放弃本页草稿")
        layout.addWidget(self.apply_button)
        layout.addWidget(self.discard_button)
        self.shop_combo.currentIndexChanged.connect(self._load)
        self.shop_combo.currentIndexChanged.connect(self._sync_shop_list)
        self.shop_list.currentRowChanged.connect(self._shop_row_changed)
        self.clerk_combo.currentIndexChanged.connect(self._metadata_changed)
        self.dialogue_spin.valueChanged.connect(self._dialogue_changed)
        self.apply_button.clicked.connect(self.apply_changes)
        self.discard_button.clicked.connect(self.discard_pending_changes)
        self.shop_list.setCurrentRow(0)

    def _shop_row_changed(self, row: int) -> None:
        if row >= 0 and self.shop_combo.currentIndex() != row:
            self.shop_combo.setCurrentIndex(row)

    def _sync_shop_list(self, index: int) -> None:
        if index >= 0 and self.shop_list.currentRow() != index:
            self.shop_list.setCurrentRow(index)

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
        return frozenset([
            *(("rom_offset", self.codec.record(key).file_offset) for key in self._drafts),
            *(("legacy_text_pool", "system") for _key in self._text_drafts),
        ])

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
        system_drafts = {}
        for text_id, text in self._text_drafts.items():
            if text_codec.record("system", text_id).raw != self.text_codec.record("system", text_id).raw:
                raise ValueError("对话已在其他页面变化，请还原草稿后重新编辑。")
            system_drafts[("system", text_id, 0)] = text
        for patch in text_codec.simple_group_repack_patches(
            "system", system_drafts
        ) if system_drafts else ():
            if patch[0] in patches and patch != patches[patch[0]]:
                raise ValueError("系统文字池与商店记录发生意外重叠。")
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
