"""Transactional fixed-slot font editing for the legacy grid browser."""
from __future__ import annotations

from PySide6.QtCore import QRect, Qt, Signal
from PySide6.QtGui import QColor, QFont, QFontMetrics, QImage, QPainter
from PySide6.QtWidgets import (
    QFileDialog,
    QFontDialog,
    QInputDialog,
    QMenu,
    QMessageBox,
    QPushButton,
    QWidget,
)

from fc_editor.codecs.dc_font import (
    FULL_FONT_PAYLOAD_SIZE,
    GLYPH_PAGE_LEADS,
    PAGE_PAYLOAD_SIZE,
    SUPPORTED_PROFILES,
    decode_full_font_file,
    decode_glyph,
    encode_full_font_file,
    encode_glyph,
    font_tokens,
    glyph_file_offset,
    page_tokens,
    safe_unmapped_tokens,
)
from fc_editor.dc_text import dc_text_table_with_overrides


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
        self._font_mapping_expected = dict(
            getattr(self.project, "font_character_overrides", {})
            if self.project is not None
            else {}
        )
        self._font_mapping_drafts = dict(self._font_mapping_expected)
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
        self.write_button.setToolTip(
            "先在 12×12 点阵中左键绘制、右键擦除；点阵变化后即可写入当前字模草稿，"
            "最后按“确定”一次提交。"
            if self._font_writable
            else "当前 ROM 的字模写入布局未经验证，仅可预览。"
        )
        self.choose_font_button.clicked.connect(self.choose_font)
        # Keep the legacy caption; the verified implementation currently
        # applies it to the selected font page without relocating glyphs.
        self.replace_all_button.setText("替换全部字体")
        self.replace_all_button.clicked.connect(self.replace_font_page)
        self.clear_page_button.clicked.connect(self.clear_font_page)
        for button in (self.choose_font_button, self.replace_all_button, self.clear_page_button):
            button.setEnabled(self._font_writable)
            button.setToolTip("仅修改固定字模，不新增字符编码；所有修改在确定后一次提交，关闭窗口可放弃。")

        # The legacy dialog exposes only the bottom OK button. Keep the
        # verified per-page interchange extension off the visible layout and
        # offer it from the glyph grid's context menu instead.
        self.import_page_button = QPushButton("导入本页点阵", self)
        self.export_page_button = QPushButton("导出本页点阵", self)
        self.import_page_button.clicked.connect(self.import_font_page)
        self.export_page_button.clicked.connect(self.export_font_page)
        self.import_page_button.setEnabled(self._font_writable)
        self.export_page_button.setEnabled(self._font_writable)
        self.import_page_button.hide()
        self.export_page_button.hide()
        self.allocate_character_button = QPushButton("自动分配新字符", self)
        self.import_full_font_button = QPushButton("导入全字库", self)
        self.export_full_font_button = QPushButton("导出全字库", self)
        self.allocate_character_button.clicked.connect(self.allocate_new_character)
        self.import_full_font_button.clicked.connect(self.import_full_font)
        self.export_full_font_button.clicked.connect(self.export_full_font)
        for button in (
            self.allocate_character_button,
            self.import_full_font_button,
            self.export_full_font_button,
        ):
            button.setEnabled(self._font_writable)
            button.hide()
        self.glyph_table.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.glyph_table.customContextMenuRequested.connect(self._show_font_page_menu)
        self.status.setMaximumHeight(16777215)
        self.status.setStyleSheet("color:#735100;")

    def _show_font_page_menu(self, position) -> None:
        menu = QMenu(self.glyph_table)
        import_action = menu.addAction("导入本页点阵…")
        export_action = menu.addAction("导出本页点阵…")
        menu.addSeparator()
        allocate_action = menu.addAction("自动分配新字符…")
        import_full_action = menu.addAction("导入全字库…")
        export_full_action = menu.addAction("导出全字库…")
        import_action.setEnabled(self.import_page_button.isEnabled())
        export_action.setEnabled(self.export_page_button.isEnabled())
        allocate_action.setEnabled(self.allocate_character_button.isEnabled())
        import_full_action.setEnabled(self.import_full_font_button.isEnabled())
        export_full_action.setEnabled(self.export_full_font_button.isEnabled())
        import_action.triggered.connect(self.import_font_page)
        export_action.triggered.connect(self.export_font_page)
        allocate_action.triggered.connect(self.allocate_new_character)
        import_full_action.triggered.connect(self.import_full_font)
        export_full_action.triggered.connect(self.export_full_font)
        menu.exec(self.glyph_table.viewport().mapToGlobal(position))

    def _set_mapping_drafts(self, mappings: dict[bytes, str]) -> None:
        self.text_table = dc_text_table_with_overrides(mappings)
        self._font_mapping_drafts = dict(mappings)

    def allocate_new_character(self) -> None:
        """Assign the next conservative unused ROM token to one new glyph."""

        if not self._font_writable or self.project is None:
            return
        initial = self.replacement_text.text()
        character, accepted = QInputDialog.getText(
            self,
            "自动分配新字符",
            "输入一枚尚未编码的 Unicode 字符：",
            text=initial,
        )
        if not accepted:
            return
        try:
            if len(character) != 1:
                raise ValueError("必须恰好输入一枚 Unicode 字符。")
            existing = self.text_table.text_to_byte.get(character)
            if existing is not None:
                raise ValueError(
                    f"字符“{character}”已有代码 {existing.hex().upper()}，无需重复分配。"
                )
            candidates = safe_unmapped_tokens(
                bytes(self.project.working),
                set(self.text_table.byte_to_text),
            )
            if not candidates:
                raise ValueError("没有同时满足未映射、全 ROM 未引用和统一填充的安全字模槽。")
            token = candidates[0]
            glyph = self._render_character(character)
            mappings = dict(self._font_mapping_drafts)
            mappings[token] = character
            self._set_mapping_drafts(mappings)
            self.page_selector.setCurrentIndex(
                self.page_selector.findData(token[0])
            )
            self._stage_glyphs({token: glyph})
            row, column = divmod(token[1], 16)
            self._select_cell(row, column)
            self.status.setText(
                f"已为“{character}”暂存代码 {token.hex().upper()}；确定后写入字模和工程码表。"
            )
        except ValueError as error:
            QMessageBox.warning(self, "无法分配字符", str(error))

    def _load_font_canvas(self, raw: bytes | None) -> None:
        if not hasattr(self, "glyph_canvas"):
            return
        self.glyph_canvas.load(raw or b"\xff" * 18)
        writable = self._font_writable and self.current_token[1] % 16 < 14
        self.glyph_canvas.setEnabled(writable)
        self.write_button.setEnabled(False)
        self.replacement_text.setEnabled(writable)
        self.status.setText(
            f"已暂存 {len(self._glyph_drafts)} 个字模。点阵左画右擦；确定提交，关闭窗口放弃。"
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
            self, action, f"{action}会影响本页所有引用这些字模的名称和对话。\n确定后才写入工程，提交前可关闭窗口放弃。",
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

    def import_full_font(self) -> None:
        from pathlib import Path

        if not self._font_writable:
            return
        path, _ = QFileDialog.getOpenFileName(
            self,
            "导入全字库",
            "",
            "新DC全字库 (*.dcfontset);;所有文件 (*)",
        )
        if not path:
            return
        try:
            glyphs, mappings = decode_full_font_file(Path(path).read_bytes())
            dc_text_table_with_overrides(mappings)
            if not self._confirm_font_page(
                f"导入全部 {len(glyphs)} 个字模和 {len(mappings)} 条自定义编码"
            ):
                return
            if self.write_button.isEnabled():
                self.stage_current_glyph()
            self._set_mapping_drafts(mappings)
            self._stage_glyphs(glyphs)
            self.status.setText(
                f"已暂存全字库：{FULL_FONT_PAYLOAD_SIZE} 字节点阵，"
                f"{len(mappings)} 条自定义编码；确定后提交。"
            )
        except (OSError, ValueError) as error:
            QMessageBox.warning(self, "导入失败", str(error))

    def export_full_font(self) -> None:
        from .workspace import default_export_path, writable_output_path

        if not self._font_writable:
            return
        path, _ = QFileDialog.getSaveFileName(
            self,
            "导出全字库",
            str(default_export_path("新DC全字库.dcfontset")),
            "新DC全字库 (*.dcfontset)",
        )
        if not path:
            return
        try:
            if self.write_button.isEnabled():
                self.stage_current_glyph()
            glyphs = {token: self._raw_glyph(token) for token in font_tokens()}
            if any(raw is None for raw in glyphs.values()):
                raise ValueError("当前 ROM 的全字库地址不完整。")
            destination = writable_output_path(path)
            if destination.suffix.lower() != ".dcfontset":
                destination = destination.with_suffix(".dcfontset")
            destination.write_bytes(
                encode_full_font_file(
                    {token: bytes(raw) for token, raw in glyphs.items() if raw is not None},
                    self._font_mapping_drafts,
                )
            )
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
            if (
                self.project is not None
                and self.project.font_character_overrides
                != self._font_mapping_expected
            ):
                raise ValueError("工程码表已被其他编辑修改，请取消后重开，避免覆盖新数据。")
            if self.project is not None and (
                self._glyph_drafts
                or self._font_mapping_drafts != self._font_mapping_expected
            ):
                with self.project.transaction(
                    f"更新字库：{len(self._glyph_drafts)} 个字模，"
                    f"{len(self._font_mapping_drafts)} 条自定义编码"
                ):
                    if self._glyph_drafts:
                        self.project.set_font_glyphs(self._glyph_drafts)
                    self.project.replace_font_character_overrides(
                        self._font_mapping_drafts
                    )
        except ValueError as error:
            QMessageBox.warning(self, "未提交字库", str(error))
            return
        super().accept()

    def reject(self) -> None:
        self._glyph_drafts.clear()
        self._font_mapping_drafts = dict(self._font_mapping_expected)
        self.write_button.setEnabled(False)
        # Reload the selected canvas as well, so reusing this dialog instance
        # cannot resurrect pixels that the user explicitly discarded.
        self._load_font_canvas(self._raw_glyph(self.current_token))
        super().reject()
