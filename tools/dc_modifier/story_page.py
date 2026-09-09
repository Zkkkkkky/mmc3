from __future__ import annotations

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
    QVBoxLayout,
    QWidget,
)

from fc_editor.text_table import TextTable

from .pages import ProjectPage, page_title, readonly_item


class StoryPage(ProjectPage):
    def __init__(self) -> None:
        super().__init__()
        self.current_selector: int | None = None
        self.current_index: int | None = None
        self.text_table: TextTable | None = None
        outer = QVBoxLayout(self)
        title, subtitle = page_title(
            "剧情文本",
            "当前以无损Token模式编辑：已识别中文字形对、控制码和结束码，未知内容不会被自动改写。",
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
        self.indices = QListWidget()
        self.indices.setAlternatingRowColors(True)
        self.indices.currentItemChanged.connect(self._index_changed)
        left_layout.addWidget(QLabel("文本组"))
        left_layout.addWidget(self.selector)
        left_layout.addWidget(self.search)
        left_layout.addWidget(self.indices)
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
        self.table_status = QLabel("未载入 .tbl 字库；Unicode页以原始Token显示。")
        self.table_status.setObjectName("hintText")
        load_table_button = QPushButton("载入 .tbl…")
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
            "载入 .tbl 后显示Unicode文字；未映射Token保持为 <C901> 形式。"
        )
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
        apply_button = QPushButton("应用文本")
        apply_button.setObjectName("primaryButton")
        apply_button.clicked.connect(self.apply_text)
        reset_button = QPushButton("还原此文本")
        reset_button.clicked.connect(self.reset_text)
        buttons.addWidget(parse_button)
        buttons.addWidget(encode_button)
        buttons.addWidget(apply_button)
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
            self.raw.clear()
            self.tokens.setRowCount(0)

    def _selector_changed(self) -> None:
        if self.project is None or self.selector.currentIndex() < 0:
            return
        previous_index = self.current_index
        self.current_selector = int(self.selector.currentData())
        group = self.project.story_text_codec.group_by_selector[self.current_selector]
        self.indices.blockSignals(True)
        self.indices.clear()
        pointers = self.project.story_text_codec.pointers(self.current_selector)
        for index, pointer in enumerate(pointers):
            record = self.project.get_story_text(self.current_selector, index)
            suffix = f"{record.capacity} B" if record.capacity else "空/别名哨兵"
            item = QListWidgetItem(f"${index:02X}  指针 ${pointer:04X}  ·  {suffix}")
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
        for row in range(self.indices.count()):
            item = self.indices.item(row)
            index = int(item.data(Qt.ItemDataRole.UserRole))
            item.setHidden(bool(query) and query not in item.text().lower() and query not in (str(index), f"{index:02x}"))

    def _index_changed(
        self,
        item: QListWidgetItem | None,
        _previous: QListWidgetItem | None,
    ) -> None:
        if self.project is None or self.current_selector is None or item is None:
            return
        self.current_index = int(item.data(Qt.ItemDataRole.UserRole))
        record = self.project.get_story_text(self.current_selector, self.current_index)
        aliases = "、".join(f"${index:02X}" for index in record.indices)
        self.heading.setText(f"剧情文本 ${self.current_selector:02X}:${self.current_index:02X}")
        self.meta.setText(
            f"CPU指针 ${record.pointer:04X} · 容量 {record.capacity} 字节 · 共享索引：{aliases}"
        )
        self.raw.blockSignals(True)
        self.raw.setPlainText(record.raw.hex(" ").upper())
        self.raw.blockSignals(False)
        self.raw.setReadOnly(not bool(record.capacity))
        self._raw_changed()
        self._render_tokens()
        self._render_decoded()

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

    def _raw_changed(self) -> None:
        if self.project is None or self.current_selector is None or self.current_index is None:
            self.length_label.setText("—")
            return
        capacity = self.project.get_story_text(self.current_selector, self.current_index).capacity
        try:
            length = len(self._parse_hex(self.raw.toPlainText()))
            status = "长度正确" if length == capacity else "必须保持等长"
            self.length_label.setText(f"输入 {length} / 容量 {capacity} 字节 · {status}")
        except ValueError as error:
            self.length_label.setText(str(error))
        self._render_decoded()

    def _render_decoded(self) -> None:
        try:
            raw = self._parse_hex(self.raw.toPlainText())
        except ValueError:
            return
        self.decoded.blockSignals(True)
        if self.text_table is None:
            self.decoded.setPlainText(
                "".join(f"<{token.raw.hex().upper()}>" for token in self.project.story_text_codec.tokenize(raw))
                if self.project is not None
                else ""
            )
        else:
            self.decoded.setPlainText(self.text_table.decode(raw))
        self.decoded.blockSignals(False)

    def encode_decoded_text(self) -> None:
        if self.text_table is None:
            self.show_error(ValueError("请先载入 .tbl 字库映射。"))
            return
        try:
            encoded = self.text_table.encode(self.decoded.toPlainText())
            self.raw.blockSignals(True)
            self.raw.setPlainText(encoded.hex(" ").upper())
            self.raw.blockSignals(False)
            self._raw_changed()
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
            self.text_table = TextTable.parse(Path(filename).read_text(encoding="utf-8-sig"))
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
            str(self.project.path.with_name("newdc_story_template.tbl")),
            "字库表 (*.tbl)",
        )
        if not filename:
            return
        try:
            destination = Path(filename)
            if destination.suffix.lower() != ".tbl":
                destination = destination.with_suffix(".tbl")
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
            for column, value in enumerate(
                (f"+0x{token.record_offset:04X}", token.code, token.category)
            ):
                self.tokens.setItem(row, column, readonly_item(value))

    def apply_text(self) -> None:
        if self.project is None or self.current_selector is None or self.current_index is None:
            return
        try:
            replacement = self._parse_hex(self.raw.toPlainText())
            self.project.set_story_text_raw(
                self.current_selector,
                self.current_index,
                replacement,
            )
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
