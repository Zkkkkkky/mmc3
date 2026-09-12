from __future__ import annotations

from dataclasses import replace

from PySide6.QtCore import Qt
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import (
    QDialog, QDialogButtonBox, QGridLayout, QGroupBox, QHBoxLayout, QLabel,
    QMessageBox, QPlainTextEdit, QPushButton, QSpinBox, QTabWidget, QVBoxLayout,
    QWidget,
)

from .database_graphics import (
    decode_unit_body_script,
    decode_unit_fragment_script,
    palette_color,
    read_unit_appearance,
    render_chr_banks,
    render_tile_grid,
    render_unit_battle_preview,
)
from .map_page import NesColorButton


def appearance_patch(project, unit_id: int, values: tuple[int, ...]):
    """Patch only the six palette bytes and the existing CHR references.

    The small record's following byte belongs to its neighbour; never write
    the normalised tenth byte from the expansion extractor into that slot.
    """
    appearance = read_unit_appearance(project, unit_id)
    count = 9 if appearance.configuration[0] & 0x80 else 8
    if len(values) != count:
        raise ValueError("配色/图库字段数与当前机体类型不符。")
    if any(type(value) is not int or not 0 <= value <= 0x3F for value in values[:6]):
        raise ValueError("配色索引必须在 $00—$3F 之间。")
    bank_count = project.chr_tile_count // 64
    if any(type(value) is not int or not 0 <= value < bank_count for value in values[6:]):
        raise ValueError("图库编号超出活动 CHR。")
    offset = appearance.file_offset + 1
    before = bytes(project.working[offset:offset + count])
    return offset, before, bytes(values)


class HexByteSpinBox(QSpinBox):
    def textFromValue(self, value: int) -> str:
        return f"{value:02X}"


def parse_hex_script(text: str, label: str) -> bytes:
    compact = text.replace(",", " ").replace("\n", " ").strip()
    try:
        values = bytes(int(part.removeprefix("$").removeprefix("0x"), 16)
                       for part in compact.split())
    except ValueError as error:
        raise ValueError(f"{label}只能包含以空格分隔的两位十六进制字节。") from error
    if not values:
        raise ValueError(f"{label}不能为空。")
    return values


def move_body_script(script: bytes, dx: int, dy: int) -> bytes:
    """Adjust or prepend one verified F3 move without rewriting tile commands."""

    if not -128 <= dx <= 127 or not -128 <= dy <= 127:
        raise ValueError("主体移动量超出单字节范围。")
    if script.startswith(b"\xF3") and len(script) >= 4:
        current_y = ((script[1] + 128) % 256) - 128
        current_x = ((script[2] + 128) % 256) - 128
        new_x, new_y = current_x + dx, current_y + dy
        if not -128 <= new_x <= 127 or not -128 <= new_y <= 127:
            raise ValueError("主体移动后坐标超出单字节范围。")
        return bytes((0xF3, new_y & 0xFF, new_x & 0xFF)) + script[3:]
    prefix = bytes((0xF3, dy & 0xFF, dx & 0xFF))
    return prefix + script


def move_fragment_script(script: bytes, dx: int, dy: int) -> bytes:
    if len(script) < 4:
        raise ValueError("碎片拼图脚本不完整。")
    x = ((script[0] + 128) % 256) - 128 + dx
    y = ((script[1] + 128) % 256) - 128 + dy
    if not -128 <= x <= 127 or not -128 <= y <= 127:
        raise ValueError("碎片移动后坐标超出单字节范围。")
    return bytes((x & 0xFF, y & 0xFF)) + script[2:]


def flip_fragment_script(script: bytes, mask: int) -> bytes:
    """Toggle the renderer flags on every draw command, preserving parameters."""

    result = bytearray(script)
    cursor = 3
    parameter_counts = {
        0x02: 0, 0x03: 0, 0x06: 1, 0x07: 1, 0x0A: 1, 0x0B: 1,
        0x0E: 2, 0x0F: 2, 0x22: 1, 0x23: 1, 0x26: 2, 0x27: 2,
        0x2A: 2, 0x2B: 2, 0x2E: 3, 0x2F: 3,
    }
    while cursor < len(result):
        command = result[cursor]
        if command == 0xFF:
            return bytes(result)
        count = parameter_counts.get(command & 0x3F)
        if count is None or cursor + count >= len(result):
            raise ValueError(f"碎片拼图包含未验证指令 ${command:02X}。")
        result[cursor] ^= mask
        cursor += count + 1
    raise ValueError("碎片拼图缺少 FF 结束码。")


class UnitAppearanceDialog(QDialog):
    """A local draft; writing on OK remains part of the database transaction."""

    def __init__(self, project, unit_id: int, parent=None) -> None:
        super().__init__(parent)
        self.project = project
        self.unit_id = unit_id
        self.appearance = read_unit_appearance(project, unit_id)
        self.body_script = self.appearance.body_script
        self.fragment_script = self.appearance.fragment_script
        self.setWindowTitle(f"机体拼图与配色 · {project.unit_display_name(unit_id)}")
        self.resize(1040, 780)
        self.changed = False
        root = QVBoxLayout(self)
        hint = QLabel(
            "修改当前外观记录的配色与图库。共用这条外观记录的机体会一起变化；"
            "碎片与物理武器仍共用图库。拼图页左侧显示主体原始图库，"
            "右侧按真实主体脚本合成完整机体。"
        )
        hint.setWordWrap(True)
        root.addWidget(hint)
        self.editors: list[QSpinBox] = []
        self.color_swatches: list[NesColorButton] = []
        self.color_buttons = self.color_swatches
        grid = QGridLayout()
        root.addLayout(grid)
        for group_index, title in enumerate((
            "机体颜色（记录 +1～+3 / $0476～$0478）",
            "碎片颜色（记录 +4～+6 / $0479～$047B）",
        )):
            group = QGroupBox(title)
            row = QGridLayout(group)
            for color in range(3):
                value = self.appearance.configuration[1 + group_index * 3 + color]
                swatch = NesColorButton(value)
                swatch.setMinimumWidth(82)
                self.color_swatches.append(swatch)
                editor = HexByteSpinBox()
                editor.setRange(0, 63)
                editor.setDisplayIntegerBase(16)
                editor.setPrefix("$")
                editor.setValue(value)
                editor.setMinimumWidth(72)
                editor.setToolTip(
                    f"外观记录 +{1 + group_index * 3 + color}；"
                    f"运行时 ${0x0476 + group_index * 3 + color:04X}"
                )
                row.addWidget(swatch, 0, color * 2)
                row.addWidget(editor, 0, color * 2 + 1)
                self.editors.append(editor)
                swatch.value_changed.connect(editor.setValue)
                editor.valueChanged.connect(swatch.set_value)
            grid.addWidget(group, 0, group_index)
        bank_form = QGridLayout()
        root.addLayout(bank_form)
        count = 10 if self.appearance.configuration[0] & 0x80 else 9
        labels = ("碎片图库（2 KiB 偶数页对）", "机体图库1", "机体图库2（大型机）")
        for index in range(7, count):
            editor = HexByteSpinBox()
            editor.setRange(0, min(255, project.chr_tile_count // 64 - 1))
            editor.setDisplayIntegerBase(16)
            editor.setPrefix("$")
            editor.setValue(self.appearance.configuration[index])
            bank_form.addWidget(QLabel(labels[index - 7]), index - 7, 0)
            bank_form.addWidget(editor, index - 7, 1)
            self.editors.append(editor)
        preview_tabs = QTabWidget()
        root.addWidget(preview_tabs, 1)

        body_tab = QWidget()
        body_grid = QGridLayout(body_tab)
        body_grid.addWidget(QLabel("主体图库（8×8 原始图块）"), 0, 0)
        body_grid.addWidget(QLabel("战斗效果（主体＋碎片，128×128）"), 0, 1)
        self.body_library_preview = QLabel()
        self.body_composition_preview = QLabel()
        for preview in (self.body_library_preview, self.body_composition_preview):
            preview.setAlignment(Qt.AlignmentFlag.AlignCenter)
            preview.setStyleSheet("background:black; border:1px solid #333;")
        self.body_library_preview.setMinimumSize(260, 420)
        self.body_composition_preview.setMinimumSize(520, 420)
        body_grid.addWidget(self.body_library_preview, 1, 0)
        body_grid.addWidget(self.body_composition_preview, 1, 1)
        body_grid.setColumnStretch(0, 2)
        body_grid.setColumnStretch(1, 3)
        preview_tabs.addTab(body_tab, "战斗合成")

        fragment_tab = QWidget()
        fragment_layout = QVBoxLayout(fragment_tab)
        fragment_hint = QLabel(
            "这里仅显示碎片图库的全部原始图块，并使用碎片三色。"
            "它不是机体主体的一部分，也不应与主体三色逐项相同。"
        )
        fragment_hint.setWordWrap(True)
        fragment_layout.addWidget(fragment_hint)
        self.fragment_library_preview = QLabel()
        self.fragment_library_preview.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.fragment_library_preview.setStyleSheet("background:black; border:1px solid #333;")
        self.fragment_library_preview.setMinimumHeight(360)
        fragment_layout.addWidget(self.fragment_library_preview, 1)
        preview_tabs.addTab(fragment_tab, "碎片原始图库")

        script_tab = QWidget()
        script_layout = QGridLayout(script_tab)
        script_layout.addWidget(QLabel("主体拼图脚本"), 0, 0)
        script_layout.addWidget(QLabel("碎片拼图脚本"), 0, 1)
        self.body_script_view = QPlainTextEdit()
        self.fragment_script_view = QPlainTextEdit()
        for editor in (self.body_script_view, self.fragment_script_view):
            editor.setLineWrapMode(QPlainTextEdit.LineWrapMode.WidgetWidth)
        self.body_script_view.setPlainText(self.appearance.body_script.hex(" ").upper())
        self.fragment_script_view.setPlainText(self.appearance.fragment_script.hex(" ").upper())
        script_layout.addWidget(self.body_script_view, 1, 0)
        script_layout.addWidget(self.fragment_script_view, 1, 1)
        body_actions = QHBoxLayout()
        fragment_actions = QHBoxLayout()
        refresh_scripts = QPushButton("验证脚本并刷新效果")
        refresh_scripts.clicked.connect(self.apply_script_text)
        body_actions.addWidget(refresh_scripts)
        body_actions.addStretch()
        clear_body = QPushButton("清除主体")
        clear_body.clicked.connect(lambda: self._replace_script("body", b"\xFF"))
        body_actions.addWidget(clear_body)
        for caption, dx, dy in (("←", -1, 0), ("→", 1, 0), ("↑", 0, -1), ("↓", 0, 1)):
            button = QPushButton(caption)
            button.setToolTip("主体按 8×8 图块移动")
            button.clicked.connect(
                lambda _checked=False, x=dx, y=dy: self._move_body(x, y)
            )
            body_actions.addWidget(button)
        clear_fragment = QPushButton("清除碎片")
        clear_fragment.clicked.connect(
            lambda: self._replace_script("fragment", bytes.fromhex("00 F0 00 00 FF"))
        )
        fragment_actions.addWidget(clear_fragment)
        for caption, dx, dy in (("←", -1, 0), ("→", 1, 0), ("↑", 0, -1), ("↓", 0, 1)):
            button = QPushButton(caption)
            button.setToolTip("碎片按 1 像素移动")
            button.clicked.connect(
                lambda _checked=False, x=dx, y=dy: self._move_fragment(x, y)
            )
            fragment_actions.addWidget(button)
        horizontal = QPushButton("水平翻转")
        vertical = QPushButton("垂直翻转")
        horizontal.clicked.connect(lambda: self._flip_fragment(0x40))
        vertical.clicked.connect(lambda: self._flip_fragment(0x80))
        fragment_actions.addWidget(horizontal)
        fragment_actions.addWidget(vertical)
        fragment_actions.addStretch()
        script_layout.addLayout(body_actions, 2, 0)
        script_layout.addLayout(fragment_actions, 2, 1)
        preview_tabs.addTab(script_tab, "拼图脚本原码")
        self.preview_tabs = preview_tabs
        self.previews = (
            self.body_library_preview,
            self.body_composition_preview,
            self.fragment_library_preview,
        )
        self.status = QLabel()
        self.status.setWordWrap(True)
        root.addWidget(self.status)
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.button(QDialogButtonBox.StandardButton.Ok).setText("确定")
        buttons.button(QDialogButtonBox.StandardButton.Cancel).setText("取消")
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        root.addWidget(buttons)
        for editor in self.editors:
            editor.valueChanged.connect(self.refresh_preview)
        self.refresh_preview()

    def values(self) -> tuple[int, ...]:
        return tuple(editor.value() for editor in self.editors)

    def apply_script_text(self) -> None:
        try:
            body = parse_hex_script(self.body_script_view.toPlainText(), "主体拼图脚本")
            fragment = parse_hex_script(
                self.fragment_script_view.toPlainText(), "碎片拼图脚本"
            )
            decode_unit_body_script(body, len(self.values()[7:]) * 64)
            decode_unit_fragment_script(fragment)
            self.body_script = body
            self.fragment_script = fragment
            self.refresh_preview()
            self.status.setText(self.status.text() + " 脚本已验证，尚未写入ROM。")
        except ValueError as error:
            QMessageBox.warning(self, "拼图脚本无效", str(error))

    def _replace_script(self, kind: str, script: bytes) -> None:
        if kind == "body":
            self.body_script = script
            self.body_script_view.setPlainText(script.hex(" ").upper())
        else:
            self.fragment_script = script
            self.fragment_script_view.setPlainText(script.hex(" ").upper())
        self.refresh_preview()

    def _move_body(self, dx: int, dy: int) -> None:
        self._replace_script("body", move_body_script(self.body_script, dx, dy))

    def _move_fragment(self, dx: int, dy: int) -> None:
        self._replace_script(
            "fragment", move_fragment_script(self.fragment_script, dx, dy)
        )

    def _flip_fragment(self, mask: int) -> None:
        try:
            self._replace_script(
                "fragment", flip_fragment_script(self.fragment_script, mask)
            )
        except ValueError as error:
            QMessageBox.warning(self, "无法翻转碎片", str(error))

    def refresh_preview(self) -> None:
        values = self.values()
        for swatch, value in zip(self.color_swatches, values[:6]):
            swatch.set_value(value)
        body_banks = tuple(values[7:])
        fragment_bank = values[6] & 0xFE
        body_library = render_chr_banks(
            self.project, body_banks, values[:3], columns=1
        )
        self.body_library_preview.setPixmap(QPixmap.fromImage(
            render_tile_grid(body_library)
        ).scaled(
            208, 416 if len(body_banks) > 1 else 208,
            Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.FastTransformation,
        ))
        preview_appearance = replace(
            self.appearance,
            configuration=bytes((self.appearance.configuration[0], *values)),
            body_script=self.body_script,
            fragment_script=self.fragment_script,
        )
        body_picture = render_unit_battle_preview(self.project, preview_appearance)
        self.body_composition_preview.setPixmap(QPixmap.fromImage(
            render_tile_grid(body_picture)
        ).scaled(
            416, 416, Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.FastTransformation,
        ))
        fragment_picture = render_chr_banks(
            self.project, (fragment_bank, fragment_bank + 1), values[3:6], columns=1
        )
        self.fragment_library_preview.setPixmap(QPixmap.fromImage(
            render_tile_grid(fragment_picture)
        ).scaled(
            208, 416, Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.FastTransformation,
        ))
        self.body_library_preview.setToolTip(
            "主体图库：" + " / ".join(f"${bank:02X}" for bank in body_banks)
        )
        self.body_composition_preview.setToolTip(
            f"主体脚本 {len(self.body_script)} 字节＋"
            f"碎片脚本 {len(self.fragment_script)} 字节的战斗合成结果"
        )
        self.fragment_library_preview.setToolTip(
            f"碎片图库：${fragment_bank:02X} / ${fragment_bank + 1:02X}"
        )
        self.status.setText(
            f"当前记录 0x{self.appearance.file_offset:06X}；"
            + ("大型机：两个主体图库。" if len(values) == 9 else "小型机：一个主体图库。")
            + f" 主体与碎片已按两段实际脚本叠加；"
            + f"碎片图库 ${fragment_bank:02X}/${fragment_bank + 1:02X}。"
        )

    def accept(self) -> None:
        try:
            body = parse_hex_script(self.body_script_view.toPlainText(), "主体拼图脚本")
            fragment = parse_hex_script(
                self.fragment_script_view.toPlainText(), "碎片拼图脚本"
            )
            decode_unit_body_script(body, len(self.values()[7:]) * 64)
            decode_unit_fragment_script(fragment)
            current = read_unit_appearance(self.project, self.unit_id)
            if current != self.appearance:
                raise ValueError("当前外观记录已被其他操作更改，请取消后重新打开。")
            offset, before, after = appearance_patch(self.project, self.unit_id, self.values())
            with self.project.transaction(f"机体 ${self.unit_id:02X} · 配色与图库"):
                self.project.working[offset:offset + len(after)] = after
                if body != self.appearance.body_script or fragment != self.appearance.fragment_script:
                    self.project.set_unit_appearance_scripts(
                        self.unit_id,
                        body_script=body,
                        fragment_script=fragment,
                    )
            self.changed = (
                before != after
                or body != self.appearance.body_script
                or fragment != self.appearance.fragment_script
            )
        except (ValueError, IndexError) as error:
            QMessageBox.warning(self, "无法保存配色与图库", str(error))
            return
        super().accept()
