from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import (
    QDialog, QDialogButtonBox, QGridLayout, QGroupBox, QLabel, QMessageBox,
    QSpinBox, QVBoxLayout,
)

from .database_graphics import (
    palette_color,
    read_unit_appearance,
    render_chr_banks,
    render_unit_body_composition,
)


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
        self.setWindowTitle(f"配色与图库 · {project.unit_display_name(unit_id)}")
        self.resize(760, 610)
        self.changed = False
        root = QVBoxLayout(self)
        hint = QLabel(
            "修改当前外观记录的配色与图库。共用这条外观记录的机体会一起变化；"
            "碎片与物理武器仍共用图库。左侧按真实主体脚本合成机体，"
            "右侧显示碎片图库全部图块。"
        )
        hint.setWordWrap(True)
        root.addWidget(hint)
        self.editors: list[QSpinBox] = []
        self.color_swatches: list[QLabel] = []
        grid = QGridLayout()
        root.addLayout(grid)
        for group_index, title in enumerate((
            "机体颜色（记录 +1～+3 / $0476～$0478）",
            "碎片颜色（记录 +4～+6 / $0479～$047B）",
        )):
            group = QGroupBox(title)
            row = QGridLayout(group)
            for color in range(3):
                swatch = QLabel()
                swatch.setFixedSize(24, 24)
                self.color_swatches.append(swatch)
                editor = HexByteSpinBox()
                editor.setRange(0, 63)
                editor.setDisplayIntegerBase(16)
                editor.setPrefix("$")
                editor.setValue(self.appearance.configuration[1 + group_index * 3 + color])
                editor.setMinimumWidth(72)
                editor.setToolTip(
                    f"外观记录 +{1 + group_index * 3 + color}；"
                    f"运行时 ${0x0476 + group_index * 3 + color:04X}"
                )
                row.addWidget(swatch, 0, color * 2)
                row.addWidget(editor, 0, color * 2 + 1)
                self.editors.append(editor)
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
        self.previews = (QLabel(), QLabel())
        for index, preview in enumerate(self.previews):
            preview.setAlignment(Qt.AlignmentFlag.AlignCenter)
            preview.setStyleSheet("background:black;")
            preview.setMinimumHeight(270)
            grid.addWidget(preview, 1, index)
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
            color = palette_color(value)
            swatch.setStyleSheet(
                f"background:{color.name()}; border:1px solid #666;"
            )
            swatch.setToolTip(
                f"NES 色号 ${value:02X} · RGB {color.name().upper()}（FCEUX.pal）"
            )
        body_banks = tuple(values[7:])
        fragment_bank = values[6] & 0xFE
        body_picture = render_unit_body_composition(
            self.project, self.appearance.body_script, body_banks, values[:3]
        )
        self.previews[0].setPixmap(QPixmap.fromImage(body_picture).scaled(
            256, 256, Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.FastTransformation,
        ))
        fragment_picture = render_chr_banks(
            self.project, (fragment_bank, fragment_bank + 1), values[3:6]
        )
        self.previews[1].setPixmap(QPixmap.fromImage(fragment_picture).scaled(
            256, 128, Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.FastTransformation,
        ))
        self.status.setText(
            f"当前记录 0x{self.appearance.file_offset:06X}；"
            + ("大型机：两个主体图库。" if len(values) == 9 else "小型机：一个主体图库。")
            + f" 主体按 {len(self.appearance.body_script)} 字节脚本合成；"
            + f"碎片实际使用 ${fragment_bank:02X}/${fragment_bank + 1:02X}。"
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
