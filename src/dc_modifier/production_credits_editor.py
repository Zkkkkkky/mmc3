from __future__ import annotations

from typing import Any

from PySide6.QtCore import Qt
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from fc_editor.codecs.production_credits import ProductionCreditsCodec


class ProductionCreditsDialog(QDialog):
    """Edit the fixed opening-credit text used by map animations $13/$14."""

    def __init__(
        self,
        parent: QWidget | None = None,
        project: Any | None = None,
        *,
        staged_texts: tuple[str, str] | None = None,
        defer_apply: bool = False,
    ) -> None:
        super().__init__(parent)
        self.project = project
        self.staged_texts = staged_texts
        self.defer_apply = defer_apply
        self.edited_texts: tuple[str, str] | None = None
        self.setObjectName("productionCreditsDialog")
        self.setWindowTitle("制作信息与出演名单")
        self.resize(900, 650)
        self.setMinimumSize(760, 540)
        self.setModal(True)
        self.setStyleSheet(
            "QDialog#productionCreditsDialog { background:#eef2f4; }"
            "QGroupBox { background:#f9fbfc; border:1px solid #a9bbc4; "
            "border-radius:7px; margin-top:12px; padding-top:12px; }"
            "QGroupBox::title { color:#17566d; font-weight:600; "
            "subcontrol-origin:margin; left:12px; padding:0 5px; }"
            "QPlainTextEdit { border:1px solid #a9bbc4; border-radius:5px; "
            "padding:7px; background:#ffffff; }"
            "QPlainTextEdit[preview='true'] { background:#10191d; color:#f4f6f2; "
            "border-color:#6f8c98; }"
            "QLabel#creditsNotice { color:#526b77; background:#e5eef2; "
            "border-radius:5px; padding:8px; }"
            "QLabel[invalid='true'] { color:#a43d32; }"
            "QPushButton#creditsPrimaryButton { background:#3f8798; color:white; "
            "border:1px solid #347383; border-radius:5px; padding:5px 16px; }"
        )

        root = QVBoxLayout(self)
        notice = QLabel(
            "这里编辑地图动画 $13“制作信息介绍与序幕”和 $14“序幕下移滚屏”绘制的字幕内容。"
            "左侧编辑、右侧即时预览；换行写入原 F1 分行码，普通空格写入原 AF 对齐码。"
            "字节、行数和单行宽度均不得超过原滚屏版面。"
        )
        notice.setObjectName("creditsNotice")
        notice.setWordWrap(True)
        root.addWidget(notice)

        self.production_edit, self.production_preview, self.production_counter = (
            self._text_group(
                root,
                "制作信息",
                "作者、技术支持及交流群等文字",
                stretch=1,
            )
        )
        self.cast_edit, self.cast_preview, self.cast_counter = self._text_group(
            root,
            "出演名单",
            "机体系列出演文字；“勒”位于本区域",
            stretch=2,
        )

        button_row = QHBoxLayout()
        self.restore_button = QPushButton("恢复打开 ROM 时的内容")
        self.restore_button.clicked.connect(self.restore_original)
        button_row.addWidget(self.restore_button)
        button_row.addStretch()
        self.buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok
            | QDialogButtonBox.StandardButton.Cancel
        )
        self.buttons.button(QDialogButtonBox.StandardButton.Ok).setText("确定")
        self.buttons.button(QDialogButtonBox.StandardButton.Ok).setObjectName(
            "creditsPrimaryButton"
        )
        self.buttons.button(QDialogButtonBox.StandardButton.Cancel).setText("取消")
        self.buttons.accepted.connect(self.apply_and_accept)
        self.buttons.rejected.connect(self.reject)
        button_row.addWidget(self.buttons)
        root.addLayout(button_row)

        self.production_edit.textChanged.connect(self._refresh_feedback)
        self.cast_edit.textChanged.connect(self._refresh_feedback)
        self._load_current()

    @staticmethod
    def _text_group(
        root: QVBoxLayout,
        title: str,
        description: str,
        *,
        stretch: int,
    ) -> tuple[QPlainTextEdit, QPlainTextEdit, QLabel]:
        group = QGroupBox(title)
        layout = QVBoxLayout(group)
        heading = QHBoxLayout()
        hint = QLabel(description)
        hint.setStyleSheet("color:#526b77;")
        counter = QLabel()
        counter.setAlignment(Qt.AlignmentFlag.AlignRight)
        heading.addWidget(hint, 1)
        heading.addWidget(counter)
        layout.addLayout(heading)
        columns = QHBoxLayout()
        editor = QPlainTextEdit()
        editor.setPlaceholderText("输入显示文字；Enter 表示游戏内分行。")
        editor.setTabChangesFocus(True)
        preview = QPlainTextEdit()
        preview.setProperty("preview", True)
        preview.setReadOnly(True)
        preview.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        preview_font = QFont("Microsoft YaHei UI", 13)
        preview_font.setStyleHint(QFont.StyleHint.Monospace)
        preview.setFont(preview_font)
        columns.addWidget(editor, 1)
        columns.addWidget(preview, 1)
        layout.addLayout(columns, 1)
        root.addWidget(group, stretch)
        return editor, preview, counter

    def _load_current(self) -> None:
        if self.project is None or not self.project.supports_production_credits:
            raise ValueError("当前 ROM 没有已验证的制作信息文字块。")
        production, cast = self.project.get_production_credits()
        self._set_texts(*(self.staged_texts or (production.text, cast.text)))

    def _set_texts(self, production: str, cast: str) -> None:
        for editor, text in (
            (self.production_edit, production),
            (self.cast_edit, cast),
        ):
            editor.blockSignals(True)
            editor.setPlainText(text)
            editor.blockSignals(False)
        self._refresh_feedback()

    def restore_original(self) -> None:
        production, cast = self.project.get_production_credits(original=True)
        self._set_texts(production.text, cast.text)

    def _encoded_lengths(self) -> tuple[int, int]:
        combined = (
            self.production_edit.toPlainText() + self.cast_edit.toPlainText()
        ).replace(" ", "").replace("\n", "").replace("\r", "")
        table, _allocated = self.project.prospective_font_text_table(
            combined, channel="story"
        )
        return (
            len(ProductionCreditsCodec.encode_text(self.production_edit.toPlainText(), table)),
            len(ProductionCreditsCodec.encode_text(self.cast_edit.toPlainText(), table)),
        )

    def _validated_input(self) -> tuple[tuple[str, str], tuple[int, int]]:
        texts = (
            self.production_edit.toPlainText(),
            self.cast_edit.toPlainText(),
        )
        combined = (texts[0] + texts[1]).replace(" ", "").replace("\n", "").replace("\r", "")
        table, _allocated = self.project.prospective_font_text_table(
            combined, channel="story"
        )
        ProductionCreditsCodec(self.project.working).replacement_patches(
            self.project.working,
            texts[0],
            texts[1],
            text_table=table,
        )
        return texts, (
            len(ProductionCreditsCodec.encode_text(texts[0], table)),
            len(ProductionCreditsCodec.encode_text(texts[1], table)),
        )

    def _refresh_feedback(self) -> None:
        self.production_preview.setPlainText(self.production_edit.toPlainText())
        self.cast_preview.setPlainText(self.cast_edit.toPlainText())
        records = self.project.get_production_credits()
        try:
            _texts, lengths = self._validated_input()
            for counter, editor, length, record in zip(
                (self.production_counter, self.cast_counter),
                (self.production_edit, self.cast_edit),
                lengths,
                records,
            ):
                lines = editor.toPlainText().replace("\r", "").split("\n")
                widest = max(map(len, lines), default=0)
                counter.setText(
                    f"{length}/{record.capacity} 字节｜"
                    f"{len(lines)}/{record.max_lines} 行｜"
                    f"最长 {widest}/{record.max_columns} 格"
                )
                counter.setProperty("invalid", False)
                counter.style().unpolish(counter)
                counter.style().polish(counter)
            self.buttons.button(QDialogButtonBox.StandardButton.Ok).setEnabled(True)
        except ValueError as error:
            for counter in (self.production_counter, self.cast_counter):
                counter.setText(str(error))
                counter.setProperty("invalid", True)
                counter.style().unpolish(counter)
                counter.style().polish(counter)
            self.buttons.button(QDialogButtonBox.StandardButton.Ok).setEnabled(False)

    def apply_and_accept(self) -> None:
        try:
            texts, _lengths = self._validated_input()
            if self.defer_apply:
                self.edited_texts = texts
            else:
                self.project.set_production_credits(*texts)
        except (ValueError, IndexError) as error:
            QMessageBox.warning(self, "制作信息未写入", str(error))
            return
        self.accept()
