from __future__ import annotations

import hashlib
import re
from pathlib import Path
from typing import Any

from PySide6.QtCore import QSize, Qt
from PySide6.QtGui import QColor, QIcon, QPainter, QPixmap
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QFileDialog,
    QFormLayout,
    QFrame,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QListWidget,
    QPlainTextEdit,
    QPushButton,
    QScrollArea,
    QSpinBox,
    QTableWidget,
    QTableWidgetItem,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from fc_editor.dc_text import default_dc_text_table
from fc_editor.text_table import TextTable
from fc_editor.codecs.dc_font import decode_glyph
from .font_edit import FontEditingMixin


READ_ONLY_NOTICE = "当前数据结构尚未完成单变量差分验证；为保护ROM，本窗口仅提供预览。"
GLYPH_PAGE_LEADS = (0xB8, 0xB9, 0xBA, 0xBB, 0xC8, 0xC9, 0xCA, 0xCB, 0xD8, 0xD9, 0xDA, 0xDB)


def _dialog_buttons(dialog: QDialog, *, writable: bool = True) -> QHBoxLayout:
    row = QHBoxLayout()
    row.addStretch()
    dialog.accept_button = QPushButton("确定")  # type: ignore[attr-defined]
    dialog.cancel_button = QPushButton("取消")  # type: ignore[attr-defined]
    dialog.accept_button.setEnabled(writable)  # type: ignore[attr-defined]
    dialog.accept_button.clicked.connect(dialog.accept)  # type: ignore[attr-defined]
    dialog.cancel_button.clicked.connect(dialog.reject)  # type: ignore[attr-defined]
    row.addWidget(dialog.accept_button)  # type: ignore[attr-defined]
    row.addWidget(dialog.cancel_button)  # type: ignore[attr-defined]
    return row


def _readonly_spin(value: int, maximum: int = 0xFFFF) -> QSpinBox:
    spin = QSpinBox()
    spin.setRange(0, maximum)
    spin.setValue(value)
    spin.setReadOnly(True)
    spin.setButtonSymbols(QSpinBox.ButtonSymbols.UpDownArrows)
    return spin


def _glyph_file_offset(token: bytes) -> int | None:
    """Return the verified legacy 12x12 glyph file offset for a two-byte token."""
    if len(token) != 2:
        return None
    lead, index = token
    if 0xB8 <= lead <= 0xBB:
        base = 0x6C010
        page = lead - 0xB8
    elif 0xC8 <= lead <= 0xCB:
        base = 0x70010
        page = lead - 0xC8
    elif 0xD8 <= lead <= 0xDB:
        base = 0x74010
        page = lead - 0xD8
    else:
        return None
    row, column = divmod(index, 0x10)
    glyph_column = column if column < 0x0E else 0
    return base + page * 0x1000 + row * 0x100 + glyph_column * 18


def _glyph_pixmap(raw: bytes, *, character: str = "", scale: int = 2) -> QPixmap:
    """Render the packed 12x12 ROM glyph; ``character`` is display metadata only."""
    side = 12 * scale
    pixmap = QPixmap(side, side)
    pixmap.fill(QColor("#080808"))
    painter = QPainter(pixmap)
    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(QColor("#f5f5f5"))
    for y, row in enumerate(decode_glyph(raw)):
        for x, pixel in enumerate(row):
            if pixel:
                painter.drawRect(x * scale, y * scale, scale, scale)
    painter.end()
    return pixmap


class FontLibraryDialog(FontEditingMixin, QDialog):
    """Legacy 16x16 font browser backed by the verified DC token map.

    Fixed glyph slots are editable on verified DC layouts. Font pointer
    relocation and automatic character-code insertion are not supported.
    """

    def __init__(self, parent: QWidget | None = None, project: Any | None = None) -> None:
        super().__init__(parent)
        self.project = project
        self.text_table = default_dc_text_table()
        self.current_token = bytes((0xC8, 0x00))
        self.setWindowTitle("字库编辑")
        self.resize(1000, 780)
        self.setMinimumSize(850, 620)
        self.setSizeGripEnabled(True)
        self.setModal(True)

        root = QVBoxLayout(self)
        content = QHBoxLayout()
        root.addLayout(content, 1)

        preview_group = QGroupBox("字库预览")
        preview_layout = QVBoxLayout(preview_group)
        self.glyph_table = QTableWidget(16, 16)
        self.glyph_table.setObjectName("glyphTable")
        self.glyph_table.setHorizontalHeaderLabels([f"{value:02X}" for value in range(16)])
        self.glyph_table.setVerticalHeaderLabels([f"{value:02X}" for value in range(16)])
        self.glyph_table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.glyph_table.verticalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.glyph_table.horizontalHeader().setMinimumSectionSize(25)
        self.glyph_table.verticalHeader().setMinimumSectionSize(25)
        self.glyph_table.horizontalHeader().setDefaultSectionSize(40)
        self.glyph_table.verticalHeader().setDefaultSectionSize(40)
        self.glyph_table.setIconSize(QSize(24, 24))
        self.glyph_table.setSelectionMode(QTableWidget.SelectionMode.SingleSelection)
        self.glyph_table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectItems)
        self.glyph_table.currentCellChanged.connect(
            lambda row, column, _previous_row, _previous_column: self._select_cell(row, column)
        )
        preview_layout.addWidget(self.glyph_table)
        content.addWidget(preview_group, 1)

        edit_group = QGroupBox("文字库修改")
        edit_group.setFixedWidth(270)
        edit_layout = QVBoxLayout(edit_group)
        edit_layout.addWidget(QLabel("字段选择:"))
        self.page_selector = QComboBox()
        for lead in GLYPH_PAGE_LEADS:
            self.page_selector.addItem(f"{lead:02X}", lead)
        self.page_selector.setCurrentIndex(GLYPH_PAGE_LEADS.index(0xC8))
        self.page_selector.currentIndexChanged.connect(self.refresh_page)
        edit_layout.addWidget(self.page_selector)
        edit_layout.addSpacing(22)
        edit_layout.addWidget(QLabel("字形修改:"))

        glyph_row = QHBoxLayout()
        self.original_glyph = QLabel()
        self.replacement_glyph = QLabel()
        for label in (self.original_glyph, self.replacement_glyph):
            label.setFixedSize(64, 64)
            label.setAlignment(Qt.AlignmentFlag.AlignCenter)
            label.setStyleSheet(
                "background:#080808; color:white; border:1px solid #6fa9cd; font-size:24px;"
            )
            glyph_row.addWidget(label)
        edit_layout.addLayout(glyph_row)
        self.replacement_text = QLineEdit()
        self.replacement_text.setMaxLength(1)
        self.replacement_text.setPlaceholderText("替换字符")
        self.replacement_text.textChanged.connect(self._update_replacement_preview)
        edit_layout.addWidget(self.replacement_text)

        self.write_button = QPushButton("写入文字")
        self.choose_font_button = QPushButton("选择字体")
        self.replace_all_button = QPushButton("替换全部字体")
        self.clear_page_button = QPushButton("清空本页")
        for button in (
            self.write_button,
            self.choose_font_button,
            self.replace_all_button,
            self.clear_page_button,
        ):
            button.setEnabled(False)
            button.setToolTip(READ_ONLY_NOTICE)
            edit_layout.addWidget(button)

        edit_layout.addStretch()
        form = QFormLayout()
        self.code_value = QLineEdit()
        self.address_value = QLineEdit()
        self.character_value = QLineEdit()
        for editor in (self.code_value, self.address_value, self.character_value):
            editor.setReadOnly(True)
        form.addRow("文字:", self.character_value)
        form.addRow("文字代码:", self.code_value)
        form.addRow("文字地址:", self.address_value)
        edit_layout.addLayout(form)
        self.status = QLabel("只读：字模写入尚未完成差分验证。")
        self.status.setWordWrap(True)
        self.status.setMaximumHeight(34)
        self.status.setStyleSheet("color:#9a5b00; font-size:9px;")
        edit_layout.addWidget(self.status)
        edit_scroll = QScrollArea()
        edit_scroll.setWidgetResizable(True)
        edit_scroll.setWidget(edit_group)
        edit_scroll.setMinimumWidth(294)
        edit_scroll.setMaximumWidth(310)
        content.addWidget(edit_scroll)

        only_ok = QHBoxLayout()
        only_ok.addStretch()
        self.accept_button = QPushButton("确定")
        self.accept_button.clicked.connect(self.accept)
        only_ok.addWidget(self.accept_button)
        root.addLayout(only_ok)
        self.initialize_font_editing(edit_layout, only_ok)
        self.refresh_page()

    def _token_at(self, row: int, column: int) -> bytes:
        lead = int(self.page_selector.currentData())
        return bytes((lead, row * 16 + column))

    def _raw_glyph(self, token: bytes) -> bytes | None:
        if self.project is None:
            return None
        canonical = bytes((token[0], token[1] & 0xF0)) if token[1] % 16 >= 14 else token
        if canonical in getattr(self, "_glyph_drafts", {}):
            return self._glyph_drafts[canonical]
        offset = _glyph_file_offset(token)
        working = getattr(self.project, "working", None)
        if offset is None or working is None or offset + 18 > len(working):
            return None
        return bytes(working[offset : offset + 18])

    def refresh_page(self, _index: int | None = None) -> None:
        blocked = self.glyph_table.blockSignals(True)
        for row in range(16):
            for column in range(16):
                token = self._token_at(row, column)
                character = self.text_table.byte_to_text.get(token, "")
                item = QTableWidgetItem()
                item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                raw = self._raw_glyph(token)
                if raw is not None:
                    item.setIcon(QIcon(_glyph_pixmap(raw, character=character)))
                else:
                    item.setText(character[:1])
                item.setToolTip(f"{token.hex().upper()} · {character or '未映射'}")
                item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEditable)
                self.glyph_table.setItem(row, column, item)
        self.glyph_table.setCurrentCell(0, 0)
        self.glyph_table.blockSignals(blocked)
        self._select_cell(0, 0)

    def _select_cell(self, row: int, column: int) -> None:
        if not 0 <= row < 16 or not 0 <= column < 16:
            return
        if hasattr(self, "glyph_canvas") and self.write_button.isEnabled():
            self.stage_current_glyph()
        self.current_token = self._token_at(row, column)
        character = self.text_table.byte_to_text.get(self.current_token, "")
        offset = _glyph_file_offset(self.current_token)
        self.character_value.setText(character)
        self.code_value.setText(self.current_token.hex().upper())
        self.address_value.setText(f"{offset:06X}" if offset is not None else "未定位")
        raw = self._raw_glyph(self.current_token)
        if raw is not None:
            self.original_glyph.setPixmap(
                _glyph_pixmap(raw, character=character, scale=4).scaled(
                    56, 56, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.FastTransformation
                )
            )
        else:
            self.original_glyph.setText(character[:1])
        self._font_loading = True
        self.replacement_text.setText(character[:1])
        self._font_loading = False
        self._load_font_canvas(raw)
        blocked = self.glyph_table.blockSignals(True)
        self.glyph_table.setCurrentCell(row, column)
        self.glyph_table.blockSignals(blocked)

    def _update_replacement_preview(self, text: str) -> None:
        self.replacement_glyph.setText(text[:1])
        self.preview_font_character(text)


from .animation_editor import MapAnimationEditorDialog


class MapAnimationDialog(MapAnimationEditorDialog):
    pass


class TextConverterDialog(QDialog):
    """Bidirectional, lossless helper using the same table as story text."""

    def __init__(
        self,
        parent: QWidget | None = None,
        project: Any | None = None,
        text_table: TextTable | None = None,
    ) -> None:
        super().__init__(parent)
        self.project = project
        self.text_table = text_table or default_dc_text_table()
        self.setWindowTitle("文字转换")
        self.setFixedSize(700, 700)
        self.setSizeGripEnabled(False)
        self.setModal(True)
        root = QVBoxLayout(self)
        root.addWidget(QLabel("文字:"))
        self.text_edit = QPlainTextEdit()
        self.text_edit.setPlaceholderText("输入中文、控制码名称或 <FF> 形式的原始Token")
        root.addWidget(self.text_edit, 1)

        buttons = QHBoxLayout()
        buttons.addStretch()
        self.encode_button = QPushButton("文字转代码")
        self.decode_button = QPushButton("代码转文字")
        self.encode_button.clicked.connect(self.encode_text)
        self.decode_button.clicked.connect(self.decode_code)
        buttons.addWidget(self.encode_button)
        buttons.addWidget(self.decode_button)
        buttons.addStretch()
        root.addLayout(buttons)

        root.addWidget(QLabel("代码:"))
        self.code_edit = QPlainTextEdit()
        self.code_edit.setPlaceholderText("示例：C9 0D C9 10 F2 FF")
        root.addWidget(self.code_edit, 1)
        self.status = QLabel("使用新DC内置Token字库；本工具不修改ROM。")
        self.status.setWordWrap(True)
        self.status.setMaximumHeight(30)
        self.status.setStyleSheet("font-size:9px;")
        root.addWidget(self.status)

    def _set_error(self, error: Exception) -> None:
        self.status.setText(f"转换失败：{error}")
        self.status.setStyleSheet("color:#b42318; font-size:9px;")

    def _set_success(self, message: str) -> None:
        self.status.setText(message)
        self.status.setStyleSheet("color:#2e7d4f; font-size:9px;")

    @staticmethod
    def parse_code(code: str) -> bytes:
        normalized = code.strip()
        normalized = re.sub(r"(?i)0x", "", normalized)
        normalized = normalized.replace("$", "")
        normalized = re.sub(r"[<>{}\[\](),，;；:_\-]", " ", normalized)
        compact = "".join(normalized.split())
        if not compact:
            return b""
        if not re.fullmatch(r"[0-9A-Fa-f]+", compact) or len(compact) % 2:
            raise ValueError("代码必须由完整的十六进制字节组成。")
        return bytes.fromhex(compact)

    def encode_text(self) -> None:
        try:
            raw = self.text_table.encode(self.text_edit.toPlainText())
        except ValueError as error:
            self._set_error(error)
            return
        self.code_edit.setPlainText(raw.hex(" ").upper())
        self._set_success(f"文字转代码完成：{len(raw)} 字节。")

    def decode_code(self) -> None:
        try:
            raw = self.parse_code(self.code_edit.toPlainText())
        except ValueError as error:
            self._set_error(error)
            return
        self.text_edit.setPlainText(self.text_table.decode(raw))
        self._set_success(f"代码转文字完成：{len(raw)} 字节。")


class _BattleSide(QWidget):
    def __init__(self, title: str, project: Any | None) -> None:
        super().__init__()
        self.setFixedHeight(390)
        self.project = project
        group = QGroupBox(title)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.addWidget(group)
        grid = QGridLayout(group)

        self.character = QComboBox()
        self.unit = QComboBox()
        self.weapon = QComboBox()
        self.level = QComboBox()
        self.level.addItems([str(value) for value in range(1, 100)])
        self.strength = self._spin(0, 999)
        self.defense = self._spin(0, 999)
        self.speed = self._spin(0, 999)
        self.hp = self._spin(0, 65535)
        self.weapon_hit = self._spin(0, 999)
        self.weapon_range = self._spin(0, 16)
        self.skill = self._spin(0, 255)
        self.power_air = self._spin(0, 999)
        self.power_land = self._spin(0, 999)
        self.power_sea = self._spin(0, 999)
        self.multiplier_numerator = self._spin(1, 99)
        self.multiplier_denominator = self._spin(1, 99)

        controls = (
            ("人物:", self.character, "强度:", self.strength, "伤害倍数:", self._multiplier_widget()),
            ("机体:", self.unit, "防御:", self.defense, "武器命中:", self.weapon_hit),
            ("武器:", self.weapon, "速度:", self.speed, "武器射程:", self.weapon_range),
            ("等级:", self.level, "HP:", self.hp, "机体特技:", self.skill),
            ("", QWidget(), "", QWidget(), "火力·空:", self.power_air),
            ("", QWidget(), "", QWidget(), "火力·陆:", self.power_land),
            ("", QWidget(), "", QWidget(), "火力·海:", self.power_sea),
        )
        for row, values in enumerate(controls):
            for pair in range(3):
                label, widget = values[pair * 2], values[pair * 2 + 1]
                if label:
                    grid.addWidget(QLabel(label), row, pair * 2)
                    grid.addWidget(widget, row, pair * 2 + 1)

        self._populate_records()
        self.unit.currentIndexChanged.connect(self._load_unit)
        self.weapon.currentIndexChanged.connect(self._load_weapon)
        self._load_unit()
        self._load_weapon()

    @staticmethod
    def _spin(minimum: int, maximum: int) -> QSpinBox:
        spin = QSpinBox()
        spin.setRange(minimum, maximum)
        return spin

    def _multiplier_widget(self) -> QWidget:
        widget = QWidget()
        row = QHBoxLayout(widget)
        row.setContentsMargins(0, 0, 0, 0)
        row.addWidget(self.multiplier_numerator)
        row.addWidget(QLabel("/"))
        row.addWidget(self.multiplier_denominator)
        return widget

    def _populate_records(self) -> None:
        if self.project is None:
            self.character.addItem("001：—", 1)
            self.unit.addItem("001：盖塔", 1)
            self.weapon.addItem("无", 0)
            return
        character_count = getattr(getattr(self.project, "profile", None), "character_name_count", 1)
        for record_id in range(1, character_count):
            self.character.addItem(
                f"{record_id:03d}：{self.project.character_display_name(record_id)}", record_id
            )
        for record_id in range(1, self.project.unit_count):
            self.unit.addItem(f"{record_id:03d}：{self.project.unit_display_name(record_id)}", record_id)
        self.weapon.addItem("无", 0)
        for record_id in range(1, self.project.weapon_count):
            self.weapon.addItem(f"{record_id:03d}：{self.project.weapon_display_name(record_id)}", record_id)

    def _load_unit(self, _index: int | None = None) -> None:
        if self.project is None or self.unit.currentData() is None:
            return
        record = self.project.unit_codec.decode_record(
            int(self.unit.currentData()), bytes(self.project.working)
        )
        self.strength.setValue(record.get("strength"))
        self.defense.setValue(record.get("defense"))
        self.speed.setValue(record.get("speed"))
        self.hp.setValue(record.get("hp"))

    def _load_weapon(self, _index: int | None = None) -> None:
        weapon_id = int(self.weapon.currentData() or 0)
        if self.project is None or weapon_id == 0:
            for spin in (
                self.weapon_hit,
                self.weapon_range,
                self.power_air,
                self.power_land,
                self.power_sea,
            ):
                spin.setValue(0)
            return
        record = self.project.weapon_codec.decode_record(weapon_id, bytes(self.project.working))
        self.weapon_hit.setValue(record.get("hit"))
        self.weapon_range.setValue(record.get("max_range"))
        self.power_air.setValue(record.get("power_air"))
        self.power_land.setValue(record.get("power_land"))
        self.power_sea.setValue(record.get("power_sea"))


class AttributeCalculatorDialog(QDialog):
    """Non-mutating comparison calculator with an explicit estimation formula."""

    def __init__(self, parent: QWidget | None = None, project: Any | None = None) -> None:
        super().__init__(parent)
        self.project = project
        self.setWindowTitle("战斗属性计算器")
        self.setFixedSize(1257, 998)
        self.setSizeGripEnabled(False)
        root = QVBoxLayout(self)
        sides = QHBoxLayout()
        self.enemy = _BattleSide("敌方", project)
        self.ally = _BattleSide("我方", project)
        sides.addWidget(self.enemy)
        sides.addWidget(self.ally)
        root.addLayout(sides)

        result_group = QGroupBox("属性计算")
        result_layout = QVBoxLayout(result_group)
        self.results = QTableWidget(0, 5)
        self.results.setHorizontalHeaderLabels(("攻击方", "目标", "命中率", "估算伤害", "命中后HP"))
        self.results.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.results.horizontalHeader().hide()
        self.results.verticalHeader().hide()
        self.results.setShowGrid(False)
        self.results.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        result_layout.addWidget(self.results, 1)
        root.addWidget(result_group, 1)
        self.calculate_button = QPushButton("开始计算")
        self.calculate_button.setToolTip(
            "安全估算（非已验证游戏公式）：命中率=clamp(武器命中+攻方速度-守方速度,0,100)；"
            "伤害=max(1,floor((攻方强度+对陆火力)×倍率)-守方防御)。"
        )
        self.calculate_button.clicked.connect(self.calculate)
        root.addWidget(self.calculate_button, 0, Qt.AlignmentFlag.AlignHCenter)

    @staticmethod
    def calculate_attack(attacker: _BattleSide, defender: _BattleSide) -> tuple[int, int, int]:
        hit = max(0, min(100, attacker.weapon_hit.value() + attacker.speed.value() - defender.speed.value()))
        scaled = (
            (attacker.strength.value() + attacker.power_land.value())
            * attacker.multiplier_numerator.value()
            // attacker.multiplier_denominator.value()
        )
        damage = max(1, scaled - defender.defense.value())
        remaining_hp = max(0, defender.hp.value() - damage)
        return hit, damage, remaining_hp

    def calculate(self) -> None:
        rows = (
            ("敌方", "我方", *self.calculate_attack(self.enemy, self.ally)),
            ("我方", "敌方", *self.calculate_attack(self.ally, self.enemy)),
        )
        self.results.setRowCount(len(rows))
        self.results.horizontalHeader().show()
        self.results.setShowGrid(True)
        for row, values in enumerate(rows):
            display = (values[0], values[1], f"{values[2]}%", str(values[3]), str(values[4]))
            for column, value in enumerate(display):
                item = QTableWidgetItem(value)
                item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                self.results.setItem(row, column, item)


class SaveEditorDialog(QDialog):
    """Legacy save-editor shell with an honest, isolated file lifecycle."""

    MAX_SAVE_SIZE = 4 * 1024 * 1024
    ALLY_HEADERS = ("序号", "人物", "机体", "等级", "机动", "强度", "防御", "速度", "HP", "EXP", "双击速度")
    ENEMY_HEADERS = ("序号", "人物", "机体", "等级", "机动", "强度", "防御", "速度", "HP", "金钱", "双击速度")

    def __init__(self, parent: QWidget | None = None, project: Any | None = None) -> None:
        super().__init__(parent)
        self.project = project
        self.save_path: Path | None = None
        self.save_bytes: bytes | None = None
        self.setWindowTitle("存档编辑器")
        self.setFixedSize(1175, 834)
        self.setSizeGripEnabled(False)
        root = QVBoxLayout(self)

        controls = QHBoxLayout()
        controls.addWidget(QLabel("存档:"))
        self.slot_selector = QComboBox()
        self.slot_selector.addItems(("1：没有数据", "2：没有数据", "3：没有数据"))
        controls.addWidget(self.slot_selector)
        controls.addSpacing(50)
        controls.addWidget(QLabel("关卡:"))
        self.chapter_selector = QComboBox()
        self.chapter_selector.addItems([f"{value:02d}" for value in range(1, 33)])
        controls.addWidget(self.chapter_selector)
        self.open_button = QPushButton("打开存档文件")
        self.read_button = QPushButton("读取存档")
        self.write_button = QPushButton("写入存档")
        self.save_button = QPushButton("保存存档文件")
        self.open_button.clicked.connect(self.open_file)
        self.read_button.clicked.connect(self.read_save)
        self.read_button.setEnabled(False)
        for button in (self.write_button, self.save_button):
            button.setEnabled(False)
            button.setToolTip("存档编解码器尚未验证，禁止写入。")
        controls.addWidget(self.open_button)
        controls.addWidget(self.read_button)
        controls.addWidget(self.write_button)
        controls.addWidget(self.save_button)
        controls.addStretch()
        root.addLayout(controls)

        self.ally_table = self._save_table(self.ALLY_HEADERS)
        self.enemy_table = self._save_table(self.ENEMY_HEADERS)
        root.addWidget(self.ally_table, 1)
        root.addWidget(self.enemy_table, 1)
        self.status = QLabel("尚未打开存档。存档编解码器尚未验证，写入和保存功能保持禁用。")
        self.status.setWordWrap(True)
        self.status.setMaximumHeight(22)
        self.status.setStyleSheet("color:#9a5b00; font-size:9px;")
        root.addWidget(self.status)

    @staticmethod
    def _save_table(headers: tuple[str, ...]) -> QTableWidget:
        table = QTableWidget(12, len(headers))
        table.setHorizontalHeaderLabels(headers)
        table.verticalHeader().hide()
        table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        return table

    def open_file(self) -> None:
        filename, _filter = QFileDialog.getOpenFileName(
            self, "打开存档文件", str(Path.cwd()), "存档文件 (*.sav *.srm *.dat);;所有文件 (*)"
        )
        if filename:
            self.load_path(Path(filename))

    def load_path(self, path: str | Path) -> None:
        candidate = Path(path).expanduser().resolve()
        size = candidate.stat().st_size
        if size > self.MAX_SAVE_SIZE:
            raise ValueError("存档文件超过4 MiB安全读取上限。")
        self.save_path = candidate
        self.save_bytes = None
        self.read_button.setEnabled(True)
        self.status.setText(f"已打开 {candidate.name}（{size} 字节），请点击“读取存档”。")

    def read_save(self) -> None:
        if self.save_path is None:
            return
        data = self.save_path.read_bytes()
        if len(data) > self.MAX_SAVE_SIZE:
            raise ValueError("存档文件超过4 MiB安全读取上限。")
        self.save_bytes = data
        digest = hashlib.sha256(data).hexdigest().upper()
        self.status.setText(
            f"已读取 {self.save_path.name}：{len(data)} 字节，SHA-256 {digest[:16]}…。"
            "尚无经过验证的存档编解码器，因此不会填充猜测数据，写入和保存保持禁用。"
        )
        self.status.setStyleSheet("color:#9a5b00; font-size:9px;")


class OtherSettingsDialog(QDialog):
    """Reference-shaped editor for verified global formulas and initial roster."""

    def __init__(self, parent: QWidget | None = None, project: Any | None = None) -> None:
        super().__init__(parent)
        self.project = project
        self.setWindowTitle("其他")
        self.setFixedSize(1166, 870)
        self.setSizeGripEnabled(False)
        self.setModal(True)
        root = QVBoxLayout(self)
        self.double_hit_values = self._number_group(
            root, "双击公式", (70, 90, 20), 3, fixed_height=105, field_width=72
        )
        self.damage_values = self._number_group(
            root, "伤害计算公式", (13, 10, 10, 1, 1), 5,
            fixed_height=110, field_width=72
        )

        lower = QHBoxLayout()
        left = QVBoxLayout()
        self.hit_values = self._number_group(
            left, "命中计算公式", (70,), 1, fixed_height=110, field_width=72
        )
        self.item_values = self._number_group(
            left,
            "道具相关修改 · 超合金Z防御增加",
            (1, 1, 1, 5, 3, 1, 3, 3, 25, 25, 50),
            3,
            field_width=150,
            stretch=1,
        )
        lower.addLayout(left, 1)
        lower.addWidget(self._initial_units_group(), 1)
        root.addLayout(lower, 1)
        self.status = QLabel(READ_ONLY_NOTICE + " 数值及初始机体均按原界面展示，不会写入ROM。")
        self.status.setWordWrap(True)
        self.status.setMaximumHeight(22)
        self.status.setStyleSheet("color:#9a5b00; font-size:9px;")
        root.addWidget(self.status)
        root.addLayout(_dialog_buttons(self, writable=True))
        self._load_project_values()

    @property
    def _is_writable(self) -> bool:
        return bool(
            self.project is not None
            and getattr(self.project, "supports_legacy_global_data", False)
        )

    def _load_project_values(self) -> None:
        groups = (
            self.double_hit_values,
            self.damage_values,
            self.hit_values,
            self.item_values,
        )
        if not self._is_writable:
            for editors in groups:
                for editor in editors:
                    editor.setReadOnly(True)
            self.status.setText(
                READ_ONLY_NOTICE + " 当前ROM配置没有已验证的全局参数地址。"
            )
            return

        value_groups = (
            self.project.get_double_hit_values(),
            self.project.get_damage_formula_values(),
            (self.project.get_hit_threshold(),),
            self.project.get_item_effect_values(),
        )
        for editors, values in zip(groups, value_groups):
            for editor, value in zip(editors, values):
                editor.setRange(0, 0xFF)
                editor.setValue(value)
                editor.setReadOnly(False)
        for index in (2, 4):
            self.damage_values[index].setMinimum(1)
        field_hints = (
            (
                self.double_hit_values,
                ("我方双击判定常量", "敌方双击判定常量", "双击速度差常量"),
            ),
            (
                self.damage_values,
                (
                    "强度系数",
                    "武器火力系数",
                    "攻击合计除数（不可为0）",
                    "防御系数",
                    "防御除数（不可为0）",
                ),
            ),
            (self.hit_values, ("命中判定阈值",)),
            (
                self.item_values,
                (
                    "超合金Z：防御增加",
                    "磁性涂层：速度增加",
                    "传感器：强度增加",
                    "超合金C：HP增加",
                    "超合金W：防御增加",
                    "推进器：机动增加",
                    "传感器2：强度增加",
                    "M合金：速度增加",
                    "电子护盾：HP增加",
                    "正义：SP消耗",
                    "治疗：SP消耗",
                ),
            ),
        )
        for editors, hints in field_hints:
            for editor, hint in zip(editors, hints):
                editor.setToolTip(hint)

        roster = self.project.get_initial_roster()
        for row, (character_id, unit_id) in enumerate(roster):
            for combo, record_id in (
                (self.initial_units[row * 2], character_id),
                (self.initial_units[row * 2 + 1], unit_id),
            ):
                index = combo.findData(record_id)
                if index < 0:
                    raise ValueError(
                        f"初始人物/机体ID ${record_id:02X} 不在当前配置范围内。"
                    )
                combo.setCurrentIndex(index)
                combo.setEnabled(True)
                combo.setToolTip("写入初始出击人物/机体ID")
        self.status.setText(
            "已读取ROM中的公式立即数、11项道具效果和6组初始人物/机体；"
            "按“确定”作为一个事务写入，按“取消”不修改ROM。"
        )
        self.status.setStyleSheet("color:#2e7d4f; font-size:9px;")

    @staticmethod
    def _number_group(
        parent_layout: QVBoxLayout,
        title: str,
        values: tuple[int, ...],
        columns: int,
        *,
        fixed_height: int | None = None,
        field_width: int = 90,
        stretch: int = 0,
    ) -> list[QSpinBox]:
        group = QGroupBox(title)
        if fixed_height is not None:
            group.setFixedHeight(fixed_height)
        grid = QGridLayout(group)
        spins: list[QSpinBox] = []
        for index, value in enumerate(values):
            spin = _readonly_spin(value, 9999)
            spin.setFixedWidth(field_width)
            spin.setToolTip(READ_ONLY_NOTICE)
            grid.addWidget(
                spin,
                index // columns,
                index % columns,
                Qt.AlignmentFlag.AlignCenter,
            )
            spins.append(spin)
        parent_layout.addWidget(group, stretch)
        return spins

    def _initial_units_group(self) -> QGroupBox:
        group = QGroupBox("初始机体")
        grid = QGridLayout(group)
        defaults = (4, 9, 5, 13, 6, 15, 7, 17, 8, 19, 9, 23)
        self.initial_units: list[QComboBox] = []
        for index, unit_id in enumerate(defaults):
            combo = QComboBox()
            if self.project is None:
                kind = "人物" if index % 2 == 0 else "机体"
                combo.addItem(f"{unit_id:03d}：未载入{kind}", unit_id)
            elif index % 2 == 0:
                character_count = self.project.profile.character_name_count
                for record_id in range(character_count):
                    combo.addItem(
                        f"{record_id:03d}：{self.project.character_display_name(record_id)}",
                        record_id,
                    )
                found = combo.findData(unit_id)
                if found >= 0:
                    combo.setCurrentIndex(found)
            else:
                for record_id in range(self.project.unit_count):
                    combo.addItem(
                        f"{record_id:03d}：{self.project.unit_display_name(record_id)}", record_id
                    )
                found = combo.findData(unit_id)
                if found >= 0:
                    combo.setCurrentIndex(found)
            combo.setEnabled(False)
            combo.setToolTip(READ_ONLY_NOTICE)
            grid.addWidget(combo, index // 2, index % 2)
            self.initial_units.append(combo)
        return group

    def accept(self) -> None:
        if not self._is_writable:
            super().accept()
            return
        try:
            roster = tuple(
                (
                    int(self.initial_units[row * 2].currentData()),
                    int(self.initial_units[row * 2 + 1].currentData()),
                )
                for row in range(6)
            )
            with self.project.transaction("其他全局参数"):
                self.project.set_double_hit_values(
                    tuple(editor.value() for editor in self.double_hit_values)
                )
                self.project.set_damage_formula_values(
                    tuple(editor.value() for editor in self.damage_values)
                )
                self.project.set_hit_threshold(self.hit_values[0].value())
                self.project.set_item_effect_values(
                    tuple(editor.value() for editor in self.item_values)
                )
                self.project.set_initial_roster(roster)
        except Exception as error:
            QMessageBox.critical(self, "无法应用全局参数", str(error))
            return
        super().accept()


__all__ = [
    "AttributeCalculatorDialog",
    "FontLibraryDialog",
    "MapAnimationDialog",
    "OtherSettingsDialog",
    "SaveEditorDialog",
    "TextConverterDialog",
]
