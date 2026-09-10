from __future__ import annotations

from collections.abc import Callable
from difflib import SequenceMatcher
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QComboBox,
    QFileDialog,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QPlainTextEdit,
    QPushButton,
    QSplitter,
    QTabWidget,
    QTableWidget,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from fc_editor.text_table import TextTable
from fc_editor.dc_text import concise_dc_text, default_dc_text_table

from .pages import ProjectPage, page_title, readonly_item
from .workspace import default_export_path, writable_output_path


class StoryPage(ProjectPage):
    def __init__(self) -> None:
        super().__init__()
        self.current_selector: int | None = None
        self.current_index: int | None = None
        self.text_table: TextTable | None = default_dc_text_table()
        self._raw_dirty = False
        self._decoded_dirty = False
        self._syncing_raw = False
        self._syncing_decoded = False
        self._raw_source_text = ""
        self._decoded_source_raw = b""
        self._decoded_source_text = ""
        self._transaction_conflict_checker: (
            Callable[[StoryPage], str | None] | None
        ) = None
        outer = QVBoxLayout(self)
        title, subtitle = page_title(
            "剧情文本",
            "内置新DC完整码表；Unicode与原始Token可双向编辑，控制参数以“原始字节”明确标注并可逆保留。",
        )
        outer.addWidget(title)
        outer.addWidget(subtitle)
        splitter = QSplitter()

        left = QWidget()
        left_layout = QVBoxLayout(left)
        left_layout.setContentsMargins(0, 0, 0, 0)
        self.selector = QComboBox()
        self.selector.currentIndexChanged.connect(self._selector_changed)
        self.search = QLineEdit()
        self.search.setPlaceholderText("搜索文本索引…")
        self.search.setClearButtonEnabled(True)
        self.search.textChanged.connect(self._filter_indices)
        search_row = QHBoxLayout()
        self.previous_button = QToolButton()
        self.previous_button.setText("◀")
        self.previous_button.setToolTip("上一条可见文本")
        self.previous_button.clicked.connect(lambda: self._select_relative(-1))
        self.next_button = QToolButton()
        self.next_button.setText("▶")
        self.next_button.setToolTip("下一条可见文本")
        self.next_button.clicked.connect(lambda: self._select_relative(1))
        self.result_count = QLabel("0 条")
        self.result_count.setObjectName("countBadge")
        search_row.addWidget(self.search, 1)
        search_row.addWidget(self.previous_button)
        search_row.addWidget(self.next_button)
        search_row.addWidget(self.result_count)
        self.indices = QListWidget()
        self.indices.setAlternatingRowColors(True)
        self.indices.setUniformItemSizes(True)
        self.indices.currentItemChanged.connect(self._index_changed)
        left_layout.addWidget(QLabel("文本组"))
        left_layout.addWidget(self.selector)
        left_layout.addWidget(self.indices)
        left_layout.addLayout(search_row)
        splitter.addWidget(left)

        right = QWidget()
        right_layout = QVBoxLayout(right)
        self.heading = QLabel("请选择文本")
        self.heading.setObjectName("sectionTitle")
        self.meta = QLabel("—")
        self.meta.setObjectName("hintText")
        self.meta.setWordWrap(True)
        right_layout.addWidget(self.heading)
        right_layout.addWidget(self.meta)
        table_row = QHBoxLayout()
        self.table_status = QLabel(
            f"内置新DC码表 · {len(self.text_table.byte_to_text)} 条有效映射"
        )
        self.table_status.setObjectName("hintText")
        load_table_button = QPushButton("载入外部 .tbl…")
        load_table_button.clicked.connect(self.load_text_table)
        export_template_button = QPushButton("导出字库模板…")
        export_template_button.clicked.connect(self.export_text_table_template)
        table_row.addWidget(self.table_status, 1)
        table_row.addWidget(load_table_button)
        table_row.addWidget(export_template_button)
        right_layout.addLayout(table_row)
        editor_tabs = QTabWidget()
        self.raw = QPlainTextEdit()
        self.raw.setPlaceholderText("十六进制Token数据")
        self.raw.setMaximumBlockCount(4096)
        self.raw.textChanged.connect(self._raw_changed)
        self.decoded = QPlainTextEdit()
        self.decoded.setPlaceholderText(
            "内置码表会显示Unicode文字；未证实语义的控制参数显示为 ⟦原始字节 $XX⟧。"
        )
        self.decoded.textChanged.connect(self._decoded_changed)
        editor_tabs.addTab(self.decoded, "Unicode文字")
        editor_tabs.addTab(self.raw, "原始Token")
        right_layout.addWidget(editor_tabs, 1)
        self.length_label = QLabel("—")
        self.length_label.setObjectName("hintText")
        right_layout.addWidget(self.length_label)
        buttons = QHBoxLayout()
        parse_button = QPushButton("刷新Token解析")
        parse_button.clicked.connect(self._render_tokens)
        encode_button = QPushButton("文字编码到Token")
        encode_button.clicked.connect(self.encode_decoded_text)
        self.apply_button = QPushButton("应用当前文本")
        self.apply_button.setObjectName("primaryButton")
        self.apply_button.clicked.connect(self.apply_text)
        reset_button = QPushButton("还原此文本")
        reset_button.clicked.connect(self.reset_text)
        buttons.addWidget(parse_button)
        buttons.addWidget(encode_button)
        buttons.addWidget(self.apply_button)
        buttons.addWidget(reset_button)
        buttons.addStretch()
        right_layout.addLayout(buttons)
        self.tokens = QTableWidget(0, 3)
        self.tokens.setHorizontalHeaderLabels(("记录内偏移", "字节", "解释"))
        self.tokens.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        self.tokens.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        self.tokens.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
        self.tokens.setAlternatingRowColors(True)
        right_layout.addWidget(QLabel("Token解析"))
        right_layout.addWidget(self.tokens, 1)
        splitter.addWidget(right)
        splitter.setSizes([270, 850])
        outer.addWidget(splitter, 1)

    def refresh(self) -> None:
        previous_selector = self.current_selector
        self.selector.blockSignals(True)
        self.selector.clear()
        if self.project is not None:
            for group in self.project.story_text_groups:
                self.selector.addItem(
                    f"${group.selector:02X} · {group.label} · {group.count}项",
                    group.selector,
                )
        self.selector.blockSignals(False)
        if self.selector.count():
            index = self.selector.findData(previous_selector)
            self.selector.setCurrentIndex(max(0, index))
            self._selector_changed()
        else:
            self.indices.clear()
            self._set_raw_editor(b"", dirty=False)
            self.tokens.setRowCount(0)

    def _selector_changed(self) -> None:
        if self.project is None or self.selector.currentIndex() < 0:
            return
        next_selector = int(self.selector.currentData())
        if (
            self.current_selector is not None
            and next_selector != self.current_selector
            and self.has_pending_draft
        ):
            target_selector = next_selector
            old_selector = self.current_selector
            self.selector.blockSignals(True)
            self.selector.setCurrentIndex(self.selector.findData(old_selector))
            self.selector.blockSignals(False)
            if not self.commit_pending_changes():
                self.show_error(
                    ValueError(
                        self.pending_draft_error
                        or "当前文本仍有无法应用的改动，请修正后再切换文本组。"
                    )
                )
                return
            self.selector.setCurrentIndex(self.selector.findData(target_selector))
            return
        previous_index = self.current_index
        self.current_selector = next_selector
        group = self.project.story_text_codec.group_by_selector[self.current_selector]
        self.indices.blockSignals(True)
        self.indices.clear()
        pointers = self.project.story_text_codec.pointers(self.current_selector)
        for index, pointer in enumerate(pointers):
            record = self.project.get_story_text(self.current_selector, index)
            suffix = f"{record.capacity} B" if record.capacity else "空/别名哨兵"
            preview = concise_dc_text(record.raw) if record.capacity else ""
            preview_text = f" · {preview}" if preview else ""
            item = QListWidgetItem(
                f"${index:02X}  指针 ${pointer:04X}  ·  {suffix}{preview_text}"
            )
            item.setData(Qt.ItemDataRole.UserRole, index)
            self.indices.addItem(item)
        self.indices.blockSignals(False)
        self._filter_indices(self.search.text())
        if self.indices.count():
            row = min(previous_index or 0, self.indices.count() - 1)
            self.indices.setCurrentRow(row)
            self._index_changed(self.indices.currentItem(), None)

    def _filter_indices(self, text: str) -> None:
        query = text.strip().lower()
        visible_count = 0
        for row in range(self.indices.count()):
            item = self.indices.item(row)
            index = int(item.data(Qt.ItemDataRole.UserRole))
            visible = not (
                bool(query)
                and query not in item.text().lower()
                and query not in (str(index), f"{index:02x}")
            )
            item.setHidden(not visible)
            visible_count += int(visible)
        self.result_count.setText(f"{visible_count} 条")
        self.previous_button.setEnabled(visible_count > 1)
        self.next_button.setEnabled(visible_count > 1)

    def _select_relative(self, direction: int) -> None:
        if not self.indices.count():
            return
        start = self.indices.currentRow()
        for step in range(1, self.indices.count() + 1):
            row = (start + direction * step) % self.indices.count()
            if not self.indices.item(row).isHidden():
                self.indices.setCurrentRow(row)
                self.indices.scrollToItem(self.indices.item(row))
                return

    def _index_changed(
        self,
        item: QListWidgetItem | None,
        previous: QListWidgetItem | None,
    ) -> None:
        if self.project is None or self.current_selector is None or item is None:
            return
        next_index = int(item.data(Qt.ItemDataRole.UserRole))
        if (
            previous is not None
            and self.current_index is not None
            and next_index != self.current_index
            and self.has_pending_draft
        ):
            target_index = next_index
            old_index = self.current_index
            self.indices.blockSignals(True)
            for row in range(self.indices.count()):
                if int(self.indices.item(row).data(Qt.ItemDataRole.UserRole)) == old_index:
                    self.indices.setCurrentRow(row)
                    break
            self.indices.blockSignals(False)
            if not self.commit_pending_changes():
                self.show_error(
                    ValueError(
                        self.pending_draft_error
                        or "当前文本仍有无法应用的改动，请修正后再切换。"
                    )
                )
                return
            for row in range(self.indices.count()):
                if int(self.indices.item(row).data(Qt.ItemDataRole.UserRole)) == target_index:
                    self.indices.setCurrentRow(row)
                    return
            return
        self.current_index = next_index
        record = self.project.get_story_text(self.current_selector, self.current_index)
        aliases = "、".join(f"${index:02X}" for index in record.indices)
        self.heading.setText(f"剧情文本 ${self.current_selector:02X}:${self.current_index:02X}")
        plan = self.project.expansion_plan
        pair = plan.story_pair_for(self.current_selector) if plan is not None else None
        binding = (
            f" · 已自动绑定 Bank ${pair[0]:02X}/${pair[1]:02X}"
            if pair is not None
            else (" · 首次修改时自动绑定 16 KiB" if plan is not None else "")
        )
        self.meta.setText(
            f"CPU指针 ${record.pointer:04X} · 当前记录 {len(record.raw)} 字节 · "
            f"共享索引：{aliases}{binding}"
        )
        self.raw.setReadOnly(not bool(record.capacity))
        self._set_raw_editor(record.raw, dirty=False)
        self._render_tokens()

    @property
    def has_pending_draft(self) -> bool:
        if self.project is None or self.current_selector is None or self.current_index is None:
            return False
        if not (self._raw_dirty or self._decoded_dirty):
            return False
        try:
            staged = self._pending_replacement()
        except ValueError:
            return True
        return staged != self.project.get_story_text(
            self.current_selector, self.current_index
        ).raw

    @property
    def transaction_sync_group(self) -> str:
        return "story_text"

    @property
    def pending_draft_key(self) -> tuple[str, int, int] | None:
        if (
            not self.has_pending_draft
            or self.current_selector is None
            or self.current_index is None
        ):
            return None
        return (
            self.transaction_sync_group,
            self.current_selector,
            self.current_index,
        )

    def set_transaction_conflict_checker(
        self,
        checker: Callable[[StoryPage], str | None] | None,
    ) -> None:
        self._transaction_conflict_checker = checker

    def _transaction_conflict_error(self) -> str | None:
        if not self.has_pending_draft or self._transaction_conflict_checker is None:
            return None
        return self._transaction_conflict_checker(self)

    @property
    def pending_draft_error(self) -> str | None:
        if not self.has_pending_draft:
            return None
        assert self.project is not None
        assert self.current_selector is not None
        assert self.current_index is not None
        try:
            staged = self._pending_replacement()
            self._validate_replacement(staged)
        except (TypeError, ValueError) as error:
            return str(error)
        return self._transaction_conflict_error()

    def commit_pending_changes(self) -> bool:
        if not self.has_pending_draft:
            return True
        if self.pending_draft_error is not None:
            return False
        assert self.project is not None
        before = bytes(self.project.working)
        self.apply_text()
        if bytes(self.project.working) != before and self.has_pending_draft:
            self.refresh()
        return not self.has_pending_draft

    @staticmethod
    def _parse_hex(text: str) -> bytes:
        compact = "".join(character for character in text if character not in " \t\r\n,-_")
        if not compact:
            return b""
        if len(compact) % 2:
            raise ValueError("Token必须使用完整的两位十六进制字节。")
        try:
            return bytes.fromhex(compact)
        except ValueError as error:
            raise ValueError("Token中含有无效的十六进制字符。") from error

    def _pending_replacement(self) -> bytes:
        if self._raw_dirty and self._decoded_dirty:
            raise ValueError(
                "Unicode文字和原始Token同时存在未提交改动。"
                "请先明确保留其中一份；可用“文字编码到Token”"
                "以Unicode内容覆盖Token草稿。"
            )
        if self._decoded_dirty:
            if self.text_table is None:
                raise ValueError("请先载入 .tbl 字库映射。")
            return self._encode_decoded_preserving_tokens(
                self.decoded.toPlainText()
            )
        return self._parse_hex(self.raw.toPlainText())

    def _encode_decoded_preserving_tokens(self, text: str) -> bytes:
        """Encode edited text without rewriting untouched source tokens.

        The DC table contains several byte aliases that render as the same
        Unicode character.  A whole-record ``TextTable.encode`` therefore
        canonicalizes unrelated glyphs.  Match the edited Unicode text back
        to the exact raw stream that produced the editor view and reuse every
        complete token contained in an unchanged span.  Only changed or
        partially touched spans go through the ordinary encoder.
        """

        if self.text_table is None:
            raise ValueError("请先载入 .tbl 字库映射。")
        if text == self._decoded_source_text:
            return self._decoded_source_raw
        if self.project is None:
            return self.text_table.encode(text)

        token_spans: list[tuple[int, int, bytes]] = []
        text_cursor = 0
        for token in self.project.story_text_codec.tokenize(
            self._decoded_source_raw
        ):
            token_text = self.text_table.byte_to_text.get(
                token.raw,
                f"<{token.raw.hex().upper()}>",
            )
            token_end = text_cursor + len(token_text)
            token_spans.append((text_cursor, token_end, token.raw))
            text_cursor = token_end

        if text_cursor != len(self._decoded_source_text):
            # The table was mutated without asking the page to render it again.
            # Falling back is safer than splicing against stale boundaries.
            return self.text_table.encode(text)

        preserved: list[tuple[int, int, bytes]] = []
        matcher = SequenceMatcher(
            None,
            self._decoded_source_text,
            text,
            autojunk=False,
        )
        for tag, source_start, source_end, edited_start, _edited_end in matcher.get_opcodes():
            if tag != "equal":
                continue
            for token_start, token_end, raw in token_spans:
                if source_start <= token_start and token_end <= source_end:
                    preserved.append(
                        (
                            edited_start + token_start - source_start,
                            edited_start + token_end - source_start,
                            raw,
                        )
                    )

        result = bytearray()
        edited_cursor = 0
        for token_start, token_end, raw in preserved:
            if token_start < edited_cursor:
                continue
            result.extend(self.text_table.encode(text[edited_cursor:token_start]))
            result.extend(raw)
            edited_cursor = token_end
        result.extend(self.text_table.encode(text[edited_cursor:]))
        return bytes(result)

    def _set_raw_editor(self, raw: bytes, *, dirty: bool) -> None:
        self._syncing_raw = True
        previous = self.raw.blockSignals(True)
        try:
            raw_text = raw.hex(" ").upper()
            if not dirty:
                self._raw_source_text = raw_text
                self._decoded_dirty = False
            self.raw.setPlainText(raw_text)
            self._raw_dirty = dirty
            self._raw_changed()
        finally:
            self.raw.blockSignals(previous)
            self._syncing_raw = False

    def _validate_replacement(self, replacement: bytes) -> None:
        assert self.project is not None
        assert self.current_selector is not None
        assert self.current_index is not None
        current = self.project.get_story_text(
            self.current_selector, self.current_index
        ).raw
        if self.project.expansion_plan is None and len(replacement) != len(current):
            raise ValueError("当前 ROM 尚未自动规划剧情空间，文本必须保持原长度。")
        if self.project.expansion_plan is not None:
            self.project.story_text_replacement_usage(
                self.current_selector, self.current_index, replacement
            )

    def _decoded_changed(self) -> None:
        if self._syncing_decoded:
            return
        self._decoded_dirty = (
            self.decoded.toPlainText() != self._decoded_source_text
        )
        if self.project is None or self.current_selector is None or self.current_index is None:
            self.length_label.setText("—")
            return
        if self._raw_dirty and self._decoded_dirty:
            self.length_label.setText(
                "Unicode文字和原始Token同时有改动；请先明确保留其中一份。"
            )
            self.length_label.setStyleSheet("color: #b42318; font-weight: 650;")
            self.apply_button.setEnabled(False)
            return
        if not self._decoded_dirty:
            self._raw_changed()
            return
        try:
            encoded = self._pending_replacement()
            current = self.project.get_story_text(
                self.current_selector, self.current_index
            ).raw
            changed = encoded != current
            if not changed:
                self._decoded_dirty = False
            self._validate_replacement(encoded)
            if self.project.expansion_plan is not None:
                used, capacity = self.project.story_text_replacement_usage(
                    self.current_selector, self.current_index, encoded
                )
                status = f"文本组预计 {used} / {capacity} 字节 · 可自动重排"
            else:
                status = "长度正确"
            staged = " · 有尚未应用的改动" if changed else " · 与当前工程一致"
            self.length_label.setText(
                f"Unicode编码后 {len(encoded)} 字节 · {status}{staged}"
            )
            self.length_label.setStyleSheet(
                "color: #b45309; font-weight: 650;"
                if changed
                else "color: #2e7d4f;"
            )
            self.apply_button.setEnabled(changed)
        except (TypeError, ValueError) as error:
            self.length_label.setText(str(error))
            self.length_label.setStyleSheet("color: #b42318;")
            self.apply_button.setEnabled(False)

    def _raw_changed(self) -> None:
        if not self._syncing_raw:
            try:
                staged_raw = self._parse_hex(self.raw.toPlainText())
            except ValueError:
                # Invalid input is still a real draft and must block navigation.
                self._raw_dirty = True
            else:
                if (
                    self.project is not None
                    and self.current_selector is not None
                    and self.current_index is not None
                ):
                    current_raw = self.project.get_story_text(
                        self.current_selector, self.current_index
                    ).raw
                    self._raw_dirty = staged_raw != current_raw
                else:
                    self._raw_dirty = (
                        self.raw.toPlainText() != self._raw_source_text
                    )
        if self.project is None or self.current_selector is None or self.current_index is None:
            self.length_label.setText("—")
            return
        if self._raw_dirty and self._decoded_dirty:
            self.length_label.setText(
                "Unicode文字和原始Token同时有改动；请先明确保留其中一份。"
            )
            self.length_label.setStyleSheet("color: #b42318; font-weight: 650;")
            self.apply_button.setEnabled(False)
            return
        if self._decoded_dirty:
            self._decoded_changed()
            return
        try:
            parsed = self._parse_hex(self.raw.toPlainText())
            length = len(parsed)
            current = self.project.get_story_text(
                self.current_selector, self.current_index
            ).raw
            changed = parsed != current
            if self.project.expansion_plan is not None:
                used, capacity = self.project.story_text_replacement_usage(
                    self.current_selector, self.current_index, parsed
                )
                valid = True
                status = f"文本组预计 {used} / {capacity} 字节 · 可自动重排"
            else:
                capacity = len(current)
                valid = length == capacity
                status = "长度正确" if valid else "当前ROM必须保持等长"
            staged = " · 有尚未应用的改动" if changed else " · 与当前工程一致"
            self.length_label.setText(
                f"输入 {length} 字节 · {status}{staged}"
            )
            self.length_label.setStyleSheet(
                "color: #b45309; font-weight: 650;"
                if changed
                else "color: #2e7d4f;"
            )
            self.apply_button.setEnabled(valid and changed)
        except ValueError as error:
            self.length_label.setText(str(error))
            self.length_label.setStyleSheet("color: #b42318;")
            self.apply_button.setEnabled(False)
        self._render_decoded()

    def _render_decoded(self) -> None:
        try:
            raw = self._parse_hex(self.raw.toPlainText())
        except ValueError:
            return
        self._syncing_decoded = True
        previous = self.decoded.blockSignals(True)
        try:
            if self.text_table is None:
                decoded_text = (
                    "".join(
                        f"<{token.raw.hex().upper()}>"
                        for token in self.project.story_text_codec.tokenize(raw)
                    )
                    if self.project is not None
                    else ""
                )
            else:
                decoded_text = self.text_table.decode(raw)
            self.decoded.setPlainText(decoded_text)
            self._decoded_source_raw = raw
            self._decoded_source_text = decoded_text
            self._decoded_dirty = False
        finally:
            self.decoded.blockSignals(previous)
            self._syncing_decoded = False

    def encode_decoded_text(self) -> None:
        if self.text_table is None:
            self.show_error(ValueError("请先载入 .tbl 字库映射。"))
            return
        try:
            encoded = self._encode_decoded_preserving_tokens(
                self.decoded.toPlainText()
            )
            dirty = True
            if (
                self.project is not None
                and self.current_selector is not None
                and self.current_index is not None
            ):
                dirty = encoded != self.project.get_story_text(
                    self.current_selector, self.current_index
                ).raw
            self._decoded_dirty = False
            self._set_raw_editor(encoded, dirty=dirty)
            self._render_tokens()
        except Exception as error:
            self.show_error(error)

    def load_text_table(self) -> None:
        filename, _ = QFileDialog.getOpenFileName(
            self, "载入剧情字库表", str(Path.cwd()), "字库表 (*.tbl *.txt);;所有文件 (*)"
        )
        if not filename:
            return
        try:
            table = TextTable.parse(Path(filename).read_text(encoding="utf-8-sig"))
            if self._decoded_dirty and not self.commit_pending_changes():
                raise ValueError(
                    self.pending_draft_error
                    or "Unicode文本草稿无法在重载码表前提交，请修正后重试。"
                )
            self.text_table = table
            self.table_status.setText(
                f"已载入 {Path(filename).name} · {len(self.text_table.byte_to_text)} 条映射"
            )
            self._render_decoded()
        except Exception as error:
            self.show_error(error)

    def export_text_table_template(self) -> None:
        if self.project is None:
            return
        tokens: set[bytes] = set()
        for group in self.project.story_text_groups:
            for pointer, indices in self.project.story_text_codec.ids_by_pointer(group.selector).items():
                if not group.data_start <= pointer < group.data_end:
                    continue
                record = self.project.get_story_text(group.selector, indices[0])
                tokens.update(token.raw for token in self.project.story_text_codec.tokenize(record.raw))
        filename, _ = QFileDialog.getSaveFileName(
            self,
            "导出字库模板",
            str(default_export_path("newdc_story_template.tbl")),
            "字库表 (*.tbl)",
        )
        if not filename:
            return
        try:
            destination = Path(filename)
            if destination.suffix.lower() != ".tbl":
                destination = destination.with_suffix(".tbl")
            destination = writable_output_path(destination)
            destination.write_text(TextTable.template(tokens), encoding="utf-8")
        except Exception as error:
            self.show_error(error)

    def _render_tokens(self) -> None:
        self.tokens.setRowCount(0)
        try:
            raw = self._parse_hex(self.raw.toPlainText())
        except ValueError:
            return
        if self.project is None:
            return
        tokens = self.project.story_text_codec.tokenize(raw)
        self.tokens.setRowCount(len(tokens))
        for row, token in enumerate(tokens):
            explanation = token.category
            if self.text_table is not None:
                value = self.text_table.byte_to_text.get(token.raw)
                if value:
                    display = "换行" if value == "\n" else value
                    explanation = f"{explanation}：{display}"
            for column, value in enumerate(
                (f"+0x{token.record_offset:04X}", token.code, explanation)
            ):
                self.tokens.setItem(row, column, readonly_item(value))

    def apply_text(self) -> None:
        if self.project is None or self.current_selector is None or self.current_index is None:
            return
        try:
            replacement = self._pending_replacement()
            self._validate_replacement(replacement)
            conflict = self._transaction_conflict_error()
            if conflict is not None:
                raise ValueError(conflict)
            self.project.set_story_text_raw(
                self.current_selector,
                self.current_index,
                replacement,
            )
            self._set_raw_editor(replacement, dirty=False)
            self._render_tokens()
            self.project_changed.emit(
                f"已更新剧情文本 ${self.current_selector:02X}:${self.current_index:02X}"
            )
        except Exception as error:
            self.show_error(error)

    def reset_text(self) -> None:
        if self.project is None or self.current_selector is None or self.current_index is None:
            return
        try:
            self.project.reset_story_text(self.current_selector, self.current_index)
            self.project_changed.emit(
                f"已还原剧情文本 ${self.current_selector:02X}:${self.current_index:02X}"
            )
        except Exception as error:
            self.show_error(error)
