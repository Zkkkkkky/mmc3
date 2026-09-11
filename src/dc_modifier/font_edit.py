"""Transactional fixed-slot font editing for the legacy grid browser."""
from __future__ import annotations

from PySide6.QtCore import QRect, Qt, Signal
from PySide6.QtGui import QColor, QFont, QFontMetrics, QImage, QPainter
from PySide6.QtWidgets import QFileDialog, QFontDialog, QHBoxLayout, QMessageBox, QPushButton, QWidget

from fc_editor.codecs.dc_font import (
    GLYPH_PAGE_LEADS, PAGE_PAYLOAD_SIZE, SUPPORTED_PROFILES, decode_glyph, encode_glyph,
    glyph_file_offset, page_tokens,
)


class GlyphCanvas(QWidget):
    changed = Signal()

    def __init__(self) -> None:
        super().__init__()
        self.setFixedSize(168, 168)
        self.pixels = [[0] * 12 for _ in range(12)]
        self._ink = 1
        self.setToolTip("左键画点，右键擦除；可按住拖动。写入文字后暂存，确定后提交。")

    def load(self, raw: bytes) -> None:
        self.pixels = [list(row) for row in decode_glyph(raw)]
        self.update()

    def raw(self) -> bytes:
        return encode_glyph(self.pixels)

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        for y in range(12):
            for x in range(12):
                painter.fillRect(x * 14, y * 14, 14, 14,
                                 QColor("#f5f5f5" if self.pixels[y][x] else "#080808"))
        painter.setPen(QColor("#63717a"))
        for index in range(13):
            painter.drawLine(index * 14, 0, index * 14, 168)
            painter.drawLine(0, index * 14, 168, index * 14)

    def _draw(self, event) -> None:
        x, y = int(event.position().x()) // 14, int(event.position().y()) // 14
        if self.isEnabled() and 0 <= x < 12 and 0 <= y < 12:
            if self.pixels[y][x] != self._ink:
                self.pixels[y][x] = self._ink
                self.update()
                self.changed.emit()

    def mousePressEvent(self, event) -> None:
        if event.button() not in (Qt.MouseButton.LeftButton, Qt.MouseButton.RightButton):
            return
        self._ink = 0 if event.button() == Qt.MouseButton.RightButton else 1
        self._draw(event)

    def mouseMoveEvent(self, event) -> None:
        if event.buttons() & (Qt.MouseButton.LeftButton | Qt.MouseButton.RightButton):
            self._draw(event)


class FontEditingMixin:
    def initialize_font_editing(self, edit_layout, button_row) -> None:
        self._glyph_drafts: dict[bytes, bytes] = {}
        self._glyph_expected: dict[bytes, bytes] = {}
        self._font_loading = False
        self._font = QFont("SimSun")
        self._font.setPixelSize(12)
        self._font.setStyleStrategy(QFont.StyleStrategy.NoAntialias)
        self._font_writable = getattr(getattr(self.project, "profile", None), "key", "") in SUPPORTED_PROFILES
        if self._font_writable:
            # Freeze the observed baseline when the dialog opens, not when a
            # draft is eventually staged. Otherwise a concurrent editor can
            # change this glyph while the user is painting, and that new
            # value would incorrectly become the overwrite's expected value.
            for lead in GLYPH_PAGE_LEADS:
                for token in page_tokens(lead):
                    offset = glyph_file_offset(token, writable=True)
                    raw = bytes(self.project.working[offset:offset + 18])
                    if len(raw) != 18:
                        self._font_writable = False
                        self._glyph_expected.clear()
                        break
                    self._glyph_expected[token] = raw
                if not self._font_writable:
                    break
        self.glyph_canvas = GlyphCanvas()
        edit_layout.insertWidget(5, self.glyph_canvas, 0, Qt.AlignmentFlag.AlignHCenter)
        self.glyph_canvas.changed.connect(self._font_pixels_changed)
        self.write_button.clicked.connect(self.stage_current_glyph)
        self.choose_font_button.clicked.connect(self.choose_font)
        self.replace_all_button.setText("用选定字体替换本页")
        self.replace_all_button.clicked.connect(self.replace_font_page)
        self.clear_page_button.clicked.connect(self.clear_font_page)
        for button in (self.choose_font_button, self.replace_all_button, self.clear_page_button):
            button.setEnabled(self._font_writable)
            button.setToolTip("仅修改固定字模，不新增字符编码；所有修改在确定后一次提交，取消可放弃。")
        self.import_page_button = QPushButton("导入本页点阵")
        self.export_page_button = QPushButton("导出本页点阵")
        self.import_page_button.clicked.connect(self.import_font_page)
        self.export_page_button.clicked.connect(self.export_font_page)
        self.import_page_button.setEnabled(self._font_writable)
        self.export_page_button.setEnabled(self._font_writable)
        row = QHBoxLayout()
        row.addWidget(self.import_page_button)
        row.addWidget(self.export_page_button)
        edit_layout.addLayout(row)
        self.cancel_button = QPushButton("取消")
        self.cancel_button.clicked.connect(self.reject)
        button_row.addWidget(self.cancel_button)
        self.status.setMaximumHeight(16777215)
        self.status.setStyleSheet("color:#735100;")

    def _load_font_canvas(self, raw: bytes | None) -> None:
        if not hasattr(self, "glyph_canvas"):
            return
        self.glyph_canvas.load(raw or b"\xff" * 18)
        writable = self._font_writable and self.current_token[1] % 16 < 14
        self.glyph_canvas.setEnabled(writable)
        self.write_button.setEnabled(False)
        self.replacement_text.setEnabled(writable)
        self.status.setText(
            f"已暂存 {len(self._glyph_drafts)} 个字模。点阵左画右擦；确定提交，取消放弃。"
            if writable else "E/F 列引用同一行 0 列，请在 0 列编辑。" if self._font_writable
            else "当前 ROM 的字模写入布局未经验证，仅预览。"
        )

    def _font_pixels_changed(self) -> None:
        self.write_button.setEnabled(self.glyph_canvas.isEnabled() and
                                     self.glyph_canvas.raw() != self._raw_glyph(self.current_token))

    def _render_character(self, text: str) -> bytes:
        if len(text) != 1 or not QFontMetrics(self._font).inFontUcs4(ord(text)):
            raise ValueError("所选字体不包含该字符；请换字体或直接编辑点阵。")
        image = QImage(12, 12, QImage.Format.Format_RGB32)
        image.fill(Qt.GlobalColor.black)
        painter = QPainter(image)
        painter.setRenderHint(QPainter.RenderHint.TextAntialiasing, False)
        painter.setFont(self._font)
        painter.setPen(Qt.GlobalColor.white)
        painter.drawText(QRect(0, 0, 12, 12), Qt.AlignmentFlag.AlignCenter, text)
        painter.end()
        return encode_glyph([[int(image.pixelColor(x, y).lightness() >= 128)
                              for x in range(12)] for y in range(12)])

    def preview_font_character(self, text: str) -> None:
        if self._font_loading or not text or not hasattr(self, "glyph_canvas"):
            return
        try:
            self.glyph_canvas.load(self._render_character(text))
            self._font_pixels_changed()
            self.status.setText("这是所选系统字体生成的 12×12 预览；请检查字形后点写入。仅换字形，不改变码表。")
        except ValueError as error:
            self.status.setText(str(error))

    def choose_font(self) -> None:
        accepted, selected = QFontDialog.getFont(self._font, self, "选择字模字体（固定 12 像素）")
        if accepted:
            self._font = selected
            self._font.setPixelSize(12)
            self._font.setStyleStrategy(QFont.StyleStrategy.NoAntialias)
            self.preview_font_character(self.replacement_text.text())

    def _stage_glyphs(self, glyphs: dict[bytes, bytes]) -> None:
        if not self._font_writable or self.project is None:
            return
        # Validate the whole batch before changing any draft, matching the
        # atomic write guarantee of RomProject.set_font_glyphs.
        for token, raw in glyphs.items():
            glyph_file_offset(token, writable=True)
            if len(raw) != 18:
                raise ValueError("字模必须恰好为 18 字节。")
        self.write_button.setEnabled(False)
        for token, raw in glyphs.items():
            if raw == self._glyph_expected[token]:
                self._glyph_drafts.pop(token, None)
            else:
                self._glyph_drafts[token] = bytes(raw)
        row, col = divmod(self.current_token[1], 16)
        self.refresh_page()
        self.glyph_table.setCurrentCell(row, col)
        self._select_cell(row, col)

    def stage_current_glyph(self) -> None:
        if self.glyph_canvas.isEnabled():
            self._stage_glyphs({self.current_token: self.glyph_canvas.raw()})

    def _confirm_font_page(self, action: str) -> bool:
        return QMessageBox.question(
            self, action, f"{action}会影响本页所有引用这些字模的名称和对话。\n确定后才写入工程，仍可取消整个窗口。",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        ) == QMessageBox.StandardButton.Yes

    def clear_font_page(self) -> None:
        if not self._font_writable:
            return
        if self._confirm_font_page("清空本页"):
            self._stage_glyphs({token: b"\xff" * 18 for token in page_tokens(self.page_selector.currentData())})

    def replace_font_page(self) -> None:
        if not self._font_writable:
            return
        try:
            glyphs = {token: self._render_character(character)
                      for token in page_tokens(self.page_selector.currentData())
                      if len(character := self.text_table.byte_to_text.get(token, "")) == 1}
            if self._confirm_font_page(f"替换本页 {len(glyphs)} 个已映射字模"):
                self._stage_glyphs(glyphs)
        except ValueError as error:
            QMessageBox.warning(self, "未替换任何字模", str(error))

    def import_font_page(self) -> None:
        from pathlib import Path
        if not self._font_writable:
            return
        path, _ = QFileDialog.getOpenFileName(self, "导入 4032 字节页点阵", "", "字模点阵 (*.dcfont);;所有文件 (*)")
        if not path:
            return
        try:
            raw = Path(path).read_bytes()
            if len(raw) != PAGE_PAYLOAD_SIZE:
                raise ValueError("页文件必须是 4032 字节（224 个 18 字节字模），不包含 E/F 别名或行保留字节。")
            if self._confirm_font_page("导入本页"):
                self._stage_glyphs({token: raw[i * 18:(i + 1) * 18]
                                   for i, token in enumerate(page_tokens(self.page_selector.currentData()))})
        except (OSError, ValueError) as error:
            QMessageBox.warning(self, "导入失败", str(error))

    def export_font_page(self) -> None:
        from .workspace import default_export_path, writable_output_path
        if not self._font_writable:
            return
        path, _ = QFileDialog.getSaveFileName(
            self, "导出本页点阵",
            str(default_export_path(f"{self.page_selector.currentData():02X}.dcfont")),
            "字模点阵 (*.dcfont)",
        )
        if path:
            try:
                # Export what is currently visible, including the glyph the
                # user has just painted without pressing the staging button.
                if self.write_button.isEnabled():
                    self.stage_current_glyph()
                destination = writable_output_path(path)
                if destination.suffix.lower() != ".dcfont":
                    destination = destination.with_suffix(".dcfont")
                destination.write_bytes(b"".join(self._raw_glyph(t) for t in page_tokens(self.page_selector.currentData())))
            except (OSError, ValueError) as error:
                QMessageBox.warning(self, "导出失败", str(error))

    def accept(self) -> None:
        if self.write_button.isEnabled():
            self.stage_current_glyph()
        try:
            for token in self._glyph_drafts:
                offset = glyph_file_offset(token, writable=True)
                if bytes(self.project.working[offset:offset + 18]) != self._glyph_expected[token]:
                    raise ValueError("字模已被其他编辑修改，请取消后重开，避免覆盖新数据。")
            if self._glyph_drafts:
                self.project.set_font_glyphs(self._glyph_drafts)
        except ValueError as error:
            QMessageBox.warning(self, "未提交字库", str(error))
            return
        super().accept()

    def reject(self) -> None:
        self._glyph_drafts.clear()
        self.write_button.setEnabled(False)
        # Reload the selected canvas as well, so reusing this dialog instance
        # cannot resurrect pixels that the user explicitly discarded.
        self._load_font_canvas(self._raw_glyph(self.current_token))
        super().reject()
