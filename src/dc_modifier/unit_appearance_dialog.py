from __future__ import annotations

from dataclasses import replace

from PySide6.QtCore import Qt
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import (
    QDialog, QDialogButtonBox, QGridLayout, QGroupBox, QLabel, QMessageBox,
    QPlainTextEdit, QSpinBox, QTabWidget, QVBoxLayout, QWidget,
)

from .database_graphics import (
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


class UnitAppearanceDialog(QDialog):
    """A local draft; writing on OK remains part of the database transaction."""

    def __init__(self, project, unit_id: int, parent=None) -> None:
        super().__init__(parent)
        self.project = project
        self.unit_id = unit_id
        self.appearance = read_unit_appearance(project, unit_id)
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
        script_layout.addWidget(QLabel("主体拼图脚本（只读）"), 0, 0)
        script_layout.addWidget(QLabel("碎片拼图脚本（只读）"), 0, 1)
        self.body_script_view = QPlainTextEdit()
        self.fragment_script_view = QPlainTextEdit()
        for editor in (self.body_script_view, self.fragment_script_view):
            editor.setReadOnly(True)
            editor.setLineWrapMode(QPlainTextEdit.LineWrapMode.WidgetWidth)
        self.body_script_view.setPlainText(self.appearance.body_script.hex(" ").upper())
        self.fragment_script_view.setPlainText(self.appearance.fragment_script.hex(" ").upper())
        script_layout.addWidget(self.body_script_view, 1, 0)
        script_layout.addWidget(self.fragment_script_view, 1, 1)
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
            f"主体脚本 {len(self.appearance.body_script)} 字节＋"
            f"碎片脚本 {len(self.appearance.fragment_script)} 字节的战斗合成结果"
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
            current = read_unit_appearance(self.project, self.unit_id)
            if current != self.appearance:
                raise ValueError("当前外观记录已被其他操作更改，请取消后重新打开。")
            offset, before, after = appearance_patch(self.project, self.unit_id, self.values())
            with self.project.transaction(f"机体 ${self.unit_id:02X} · 配色与图库"):
                self.project.working[offset:offset + len(after)] = after
            self.changed = before != after
        except (ValueError, IndexError) as error:
            QMessageBox.warning(self, "无法保存配色与图库", str(error))
            return
        super().accept()
