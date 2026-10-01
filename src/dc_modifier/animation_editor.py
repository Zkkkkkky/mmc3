from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass, replace

from PySide6.QtCore import QProcess, QSize, Qt, QTimer, Signal
from PySide6.QtGui import (
    QColor, QIcon, QImage, QMouseEvent, QPainter, QPen, QPixmap, QStandardItem,
    QStandardItemModel,
)
from PySide6.QtWidgets import (
    QCheckBox, QComboBox, QDialog, QDialogButtonBox, QFormLayout, QGridLayout,
    QGroupBox, QHBoxLayout, QHeaderView, QLabel, QLineEdit, QListView, QListWidget,
    QListWidgetItem, QMenu, QMessageBox, QPlainTextEdit, QProgressBar, QProgressDialog,
    QPushButton, QSpinBox, QRadioButton, QSlider, QTableWidget, QTableWidgetItem,
    QTabWidget, QVBoxLayout, QWidget,
)

from fc_editor.codecs.animation import (
    AnimationCodec, AnimationInstruction, AnimationRecord, BeamComposition,
    SpriteComposition,
    apply_animation_patches, decode_script, decode_sprite_composition,
    decode_legacy_beam_composition, decode_sprite_timeline,
    encode_legacy_beam_composition, encode_legacy_sprite_composition,
    legacy_script_lines,
)
from fc_editor.codecs.character_attributes import SPIRIT_NAMES
from .workspace import ROOT
from .beginner_ui import collapsible_details, task_hint
from .database_graphics import palette_color
from .map_animation_runtime_preview import (
    prepare_map_animation_runtime_preview,
    runtime_preview_frames,
)


SPIRIT_ANIMATION_CALLS = (
    0x3891D, 0x389B9, 0x3B88B, 0x38A95, 0x38A2A, 0x38959,
    0x3B8B3, 0x389CE, 0x38AD2, 0x3B6EB, 0x38A3D, 0x38C9D,
    0x38C27, 0x388BE, 0x3B723, 0x3B673, 0x3884B, 0x3B6D3,
    0x38906, 0x38CB2, 0x3B7B6, 0x3B7E6, 0x3B82B, 0x3B85B,
)
MAP_WEAPON_ANIMATION_CALLS = {
    0x3BB93: "范围修理",
    0x38FBE: "普通地图炮1",
    0x3BF33: "普通地图炮2",
    0x3BBC7: "普通地图炮3",
    0x3BE73: "距离衰减地图炮",
    0x3BD06: "抛射地图炮1",
    0x3BD16: "抛射地图炮2",
    0x3B659: "抛射地图炮3",
    0x3BCD3: "十字地图炮",
    0x3BD78: "直线地图炮1（第1段）",
    0x3BE4B: "直线地图炮1（第2段）",
    0x3BE5C: "直线地图炮1（第3段）",
    0x3BD67: "直线地图炮1（第4段）",
    0x3BF5B: "直线地图炮2（第1段）",
    0x3BF6C: "直线地图炮2（第2段）",
    0x3BF7D: "直线地图炮2（第3段）",
    0x3BC37: "直线地图炮2（第4段）",
    0x380DF: "开场介绍",
    0x38EEA: "通关介绍",
}


class HexByteSpinBox(QSpinBox):
    """Compact byte editor matching the reference modifier's 00-FF notation."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setDisplayIntegerBase(16)

    def textFromValue(self, value: int) -> str:
        return f"{value:02X}"


def animation_names(filename: str, count: int, first: int = 0) -> tuple[str, ...]:
    path = ROOT / "src" / "resources" / "default_config" / filename
    lines: list[str] = []
    if path.is_file():
        for encoding in ("utf-8-sig", "gb18030"):
            try:
                lines = [line.strip() for line in path.read_text(encoding=encoding).splitlines() if line.strip()]
                break
            except UnicodeError:
                continue
    return tuple(lines[i-first] if 0 <= i-first < len(lines) else "未命名" for i in range(count))


class AnimationPointerDialog(QDialog):
    """Reference-shaped prompt for locating an existing animation pointer."""

    def __init__(
        self,
        parent: QWidget | None = None,
        *,
        pointer: int = 0x8000,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("请输入：")
        self.setModal(True)
        self.setFixedSize(380, 170)
        root = QVBoxLayout(self)
        root.addWidget(QLabel("请输入动画指针"))
        self.pointer_edit = QLineEdit(pointer.to_bytes(2, "little").hex().upper())
        self.pointer_edit.setInputMask("HHHH;_")
        self.pointer_edit.selectAll()
        root.addWidget(self.pointer_edit)
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.button(QDialogButtonBox.StandardButton.Ok).setText("确认输入(&O)")
        buttons.button(QDialogButtonBox.StandardButton.Cancel).setText("取消(&C)")
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        root.addWidget(buttons)

    def value(self) -> str:
        return self.pointer_edit.text().upper()

    def pointer(self) -> int:
        raw = bytes.fromhex(self.value())
        if len(raw) != 2:
            raise ValueError("动画指针必须是两个十六进制字节。")
        return int.from_bytes(raw, "little")


class AnimationInstructionDialog(QDialog):
    """Beginner-facing editor for one verified, fixed-length instruction."""

    def __init__(
        self,
        parent: QWidget | None = None,
        *,
        instruction,
        values: tuple[int, ...],
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("编辑武器动画指令")
        self.setModal(True)
        self.setMinimumWidth(500)
        root = QVBoxLayout(self)
        self.task_hint = task_hint(
            "操作：选择动画或规律后修改；右键动画指令可插入、编辑、复制或删除；最后点击“确定”。"
        )
        root.addWidget(self.task_hint)
        summary = QLabel(
            f"{instruction.text}\n"
            f"ROM 地址：${instruction.offset:06X}　原始字节：{instruction.raw.hex(' ').upper()}"
        )
        summary.setWordWrap(True)
        root.addWidget(summary)
        form = QFormLayout()
        self.parameter_editors: list[QSpinBox] = []
        for value, (local, low, high) in zip(values, instruction.editable):
            editor = QSpinBox()
            editor.setRange(low, high)
            editor.setDisplayIntegerBase(16)
            editor.setPrefix("$ ")
            editor.setValue(value)
            editor.setToolTip(
                f"允许范围 ${low:02X}—${high:02X}；只替换当前指令的第 {local + 1} 字节。"
            )
            form.addRow(f"参数 +{local}", editor)
            self.parameter_editors.append(editor)
        root.addLayout(form)
        hint = QLabel(
            "这里只修改当前指令中已验证的参数字节，不改变脚本长度、指令边界或动画指针。"
        )
        hint.setWordWrap(True)
        root.addWidget(hint)
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.button(QDialogButtonBox.StandardButton.Ok).setText("应用到草稿")
        buttons.button(QDialogButtonBox.StandardButton.Cancel).setText("取消")
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        root.addWidget(buttons)

    def parameter_values(self) -> tuple[int, ...]:
        return tuple(editor.value() for editor in self.parameter_editors)


_WEAPON_COMMAND_PRESETS = (
    ("等待指定帧数", bytes.fromhex("01"), "让动画暂停 1—223 帧。"),
    ("播放音乐或音效", bytes.fromhex("F4 00"), "选择一个音乐或音效编号并播放。"),
    ("设置动画颜色", bytes.fromhex("F0 11 03 0F 16 20"), "设置物体使用的三个颜色值。"),
    ("切换光束图库", bytes.fromhex("F2 03 01 00"), "为光束动画选择图库。"),
    ("设置光束动画规律", bytes.fromhex("F3 22 01"), "选择旧修改器中的光束运行规律。"),
    ("设置屏幕属性", bytes.fromhex("F6 00"), "修改屏幕显示属性。"),
    ("切换区域 00 的图库", bytes.fromhex("E0 00"), "为显示区域 00 选择图库。"),
    ("切换区域 01 的图库", bytes.fromhex("E1 00"), "为显示区域 01 选择图库。"),
    ("移动屏幕", bytes.fromhex("FD 00 00"), "按横向和纵向位移量移动屏幕。"),
    ("循环播放前面的指令", bytes.fromhex("FE 02 00 80"), "按指定次数返回前面的循环起点。"),
    ("创建动画物体", bytes.fromhex("F9 00 00 00"), "设置物体编号及初始 X、Y 坐标。"),
    ("设置物体运行规律 1", bytes.fromhex("42 69 01 01 01"), "设置物体状态、组图和横纵移动规律。"),
    ("设置物体运行规律 2", bytes.fromhex("C2 69 01 01 01"), "设置第二类物体状态、组图和横纵移动规律。"),
    ("结束当前动画", bytes.fromhex("FF"), "结束当前动画；每段动画必须保留一个结束指令。"),
)

_OBJECT_RULE_OPCODES = (0x40, 0x42, 0xC0, 0xC2)

_LEGACY_WEAPON_INSERT_ROWS = (
    (1, "F4定义声音", "设置要播放的音乐或音效代码。"),
    (2, "F0定义颜色", "设置光束或物体使用的三个颜色。"),
    (3, "F2定义光束图库", "选择光束动画使用的图库。"),
    (4, "F3定义光束规律", "设置光束图库与运行规律。"),
    (6, "E0切换00区域的图库号", "设置 00 区域使用的图库号。"),
    (7, "E1切换01区域的图库号", "设置 01 区域使用的图库号。"),
    (8, "FD移动屏幕", "设置屏幕横向与纵向移动量。"),
    (9, "FE跳转重复", "设置重复次数和跳转目标。"),
    (10, "F9创建物体", "设置物体编号、坐标与三类规律。"),
    (11, "42/C2定义物体运行规律", "选择 42/C2 并设置取图、X 轴与 Y 轴运行规律。"),
    (0, "等待（帧）", "设置等待帧数。"),
    (13, "FF动画结束", "结束当前动画。"),
)


def _legacy_dialog_title(raw: bytes) -> str:
    opcode = raw[0]
    if opcode < 0xE0 and opcode not in _OBJECT_RULE_OPCODES:
        return "等待(帧)"
    return {
        0x40: "运行规律",
        0x42: "运行规律",
        0xC0: "运行规律",
        0xC2: "运行规律",
        0xE0: "切换精灵图库0",
        0xE1: "切换精灵图库1",
        0xF0: "定义颜色",
        0xF2: "定义光束规律图库",
        0xF3: "定义光束规律",
        0xF4: "定义声音",
        0xF6: "写入IO端口2001",
        0xF7: "设置背景位置",
        0xF9: "创建物体",
        0xFD: "移动屏幕",
        0xFE: "跳转重复",
        0xFF: "动画结束",
    }.get(opcode, "动画指令")


def _legacy_group_title(raw: bytes) -> str:
    return {
        0xF0: "颜色设置",
        0xF4: "声音设置",
        0xF3: "光束规律设置",
        0xF6: "状态设置",
        0xF7: "背景位置设置",
        0xE0: "图库设置",
        0xE1: "图库设置",
        0xFD: "屏幕移动设置",
        0xFE: "跳转重复设置",
        0xF9: "物体设置",
        0x40: "物体运行规律设置",
        0x42: "物体运行规律设置",
        0xC0: "物体运行规律设置",
        0xC2: "物体运行规律设置",
    }.get(raw[0], "帧数设置")


def _command_parameter_name(raw: bytes, local: int) -> str:
    opcode = raw[0]
    if opcode < 0xE0 and opcode not in _OBJECT_RULE_OPCODES:
        return "等待时间"
    if opcode == 0xF9 and len(raw) == 4:
        return {1: "物体编号", 2: "物体初始X坐标", 3: "物体初始Y坐标"}.get(
            local, f"数值 {local}"
        )
    names = {
        0xE0: {1: "图库编号"},
        0xE1: {1: "图库编号"},
        0xF0: {1: "作用区域", 3: "颜色 1", 4: "颜色 2", 5: "颜色 3"},
        0xF2: {3: "图库地址"},
        0xF3: {2: "光束运行规律"},
        0xF4: {1: "音乐代码"},
        0xF6: {1: "写入数值"},
        0xF7: {2: "背景X轴偏移"},
        0xFD: {1: "X轴移动量", 2: "Y轴移动量"},
        0xFE: {1: "重复次数"},
        **{
            op: {1: "状态代码", 2: "取图规律号", 3: "X轴运行规律号", 4: "Y轴运行规律号"}
            for op in _OBJECT_RULE_OPCODES
        },
    }
    return names.get(opcode, {}).get(local, f"数值 {local}")


def _parameter_uses_hex(raw: bytes, local: int) -> bool:
    """Use hex for ROM codes/IDs, decimal for human quantities and offsets."""

    opcode = raw[0]
    if opcode < 0xE0 and opcode not in _OBJECT_RULE_OPCODES:
        return False
    if opcode in (0xFD, 0xFE) or (opcode == 0xF7 and local == 2):
        return False
    if opcode in (0xF8, 0xF9) and local in (2, 3):
        return False
    return True


def _insert_parameter_ranges(raw: bytes) -> tuple[tuple[int, int, int], ...]:
    opcode = raw[0]
    if opcode < 0xE0 and opcode not in _OBJECT_RULE_OPCODES:
        return ((0, 1, 0xDF),)
    if opcode == 0xF9 and len(raw) == 4:
        return ((2, 0, 255), (3, 0, 255))
    if opcode in _OBJECT_RULE_OPCODES and len(raw) == 5:
        # Byte 1 is the reference editor's named 规律1/规律2 selector.
        return ((2, 0, 0xF8), (3, 0, 0x9C), (4, 0, 0x9C))
    locals_by_opcode = {
        0xE0: (), 0xE1: (), 0xF0: (3, 4, 5), 0xF2: (),
        0xF3: (), 0xF4: (1,), 0xF6: (1,), 0xFD: (1, 2),
        0xFE: (1,),
    }
    return tuple(
        (local, 0, 0x0F if opcode == 0xF9 and local == 1 else 255)
        for local in locals_by_opcode.get(opcode, ())
    )


def _weapon_command_preset_index(raw: bytes) -> int:
    if len(raw) == 1 and raw[0] < 0xE0 and raw[0] not in _OBJECT_RULE_OPCODES:
        return 0
    for index, (_label, preset, _hint) in enumerate(_WEAPON_COMMAND_PRESETS[1:], 1):
        if raw and (
            raw[0] == preset[0]
            or (
                raw[0] in _OBJECT_RULE_OPCODES
                and preset[0] in (0x42, 0xC2)
                and bool(raw[0] & 0x80) == bool(preset[0] & 0x80)
            )
        ):
            return index
    return 0


class WeaponAnimationCommandDialog(QDialog):
    """Edit one command through named fields rather than raw byte entry."""

    def __init__(
        self,
        parent=None,
        *,
        raw: bytes | None = None,
        allow_type_change: bool | None = None,
        operation: str = "edit",
        loop_targets: tuple[tuple[str, int], ...] = (),
    ) -> None:
        super().__init__(parent)
        if allow_type_change is None:
            allow_type_change = raw is None
        self.allow_type_change = allow_type_change
        self._original = bytes(raw) if raw is not None else None
        self._original_type = (
            _weapon_command_preset_index(self._original)
            if self._original is not None
            else None
        )
        self.operation = operation
        self.loop_targets = tuple(loop_targets)
        initial = raw if raw is not None else _WEAPON_COMMAND_PRESETS[0][1]
        self.setWindowTitle(_legacy_dialog_title(initial))
        self.setModal(True)
        self.resize(480, 280)
        self.setMinimumWidth(420)
        root = QVBoxLayout(self)
        root.setSpacing(8)
        self.command_type = QComboBox()
        for label, _preset, hint in _WEAPON_COMMAND_PRESETS:
            self.command_type.addItem(label)
            self.command_type.setItemData(self.command_type.count() - 1, hint, Qt.ItemDataRole.ToolTipRole)
        self._raw = bytearray(initial)
        self.command_type.setCurrentIndex(_weapon_command_preset_index(initial))
        self.command_type.setEnabled(self.allow_type_change)
        if self.allow_type_change:
            root.addWidget(QLabel("要执行的动作"))
            root.addWidget(self.command_type)
        else:
            self.command_type.hide()
            self.type_label = QLabel(
                _WEAPON_COMMAND_PRESETS[self.command_type.currentIndex()][0]
            )
            self.type_label.hide()
        self.raw_edit = QLineEdit()
        self.raw_edit.hide()
        self.parameter_group = QGroupBox(_legacy_group_title(initial))
        parameter_group_layout = QVBoxLayout(self.parameter_group)
        parameter_group_layout.setContentsMargins(10, 10, 10, 10)
        parameter_group_layout.setSpacing(6)
        self.color_type_widget = QWidget()
        color_type_layout = QHBoxLayout(self.color_type_widget)
        color_type_layout.setContentsMargins(0, 0, 0, 0)
        self.beam_color = QRadioButton("光束颜色")
        self.physical_color = QRadioButton("物理颜色")
        color_type_layout.addWidget(self.beam_color)
        color_type_layout.addWidget(self.physical_color)
        color_type_layout.addStretch()
        parameter_group_layout.addWidget(self.color_type_widget)
        self.rule_type_widget = QWidget()
        rule_type_layout = QHBoxLayout(self.rule_type_widget)
        rule_type_layout.setContentsMargins(0, 0, 0, 0)
        self.rule_42 = QRadioButton("42")
        self.rule_c2 = QRadioButton("C2")
        self.rule_variant = QComboBox()
        self.rule_variant.addItems(("规律1", "规律2"))
        rule_type_layout.addWidget(self.rule_42)
        rule_type_layout.addWidget(self.rule_c2)
        rule_type_layout.addWidget(self.rule_variant)
        rule_type_layout.addStretch()
        parameter_group_layout.addWidget(self.rule_type_widget)
        rule_names = animation_names("运行规律名称.ini", 0xFC)
        self.object_rule_combos: list[QComboBox] = []
        for local in (2, 3, 4):
            combo = QComboBox()
            combo.setObjectName(f"weaponObjectRuleCombo{local}")
            for value, name in enumerate(rule_names, start=1):
                combo.addItem(f"[{value:02X}]{value:03d}：{name}", value)
            combo.currentIndexChanged.connect(
                lambda index, byte_index=local: self._change_object_rule(
                    byte_index, index
                )
            )
            self.object_rule_combos.append(combo)
        self.beam_rule_combo = QComboBox()
        self.beam_rule_combo.setObjectName("weaponBeamRuleCombo")
        for value, name in enumerate(
            animation_names("光束规律名称.ini", 0xFF), start=1
        ):
            self.beam_rule_combo.addItem(
                f"[{value:02X}]{value:03d}：{name}", value
            )
        self.beam_rule_combo.currentIndexChanged.connect(
            self._change_beam_rule
        )
        self.beam_library_combo = QComboBox()
        self.beam_library_combo.setObjectName("weaponBeamLibraryCombo")
        for value in range(0x100):
            self.beam_library_combo.addItem(
                f"[{value:02X}]{value:03d}：{0x80010 + value * 0x400:05X}",
                value,
            )
        self.beam_library_combo.currentIndexChanged.connect(
            self._change_beam_library
        )
        self.object_combo = QComboBox()
        self.object_combo.setObjectName("weaponObjectCombo")
        for value in range(0xFF):
            self.object_combo.addItem(f"{value:02X}", value)
        self.object_combo.currentIndexChanged.connect(self._change_object)
        self.loop_target_combo = QComboBox()
        self.loop_target_combo.setObjectName("weaponLoopTargetCombo")
        for index in range(200):
            self.loop_target_combo.addItem(f"{index:03d}")
            if index < len(self.loop_targets):
                label, address = self.loop_targets[index]
                self.loop_target_combo.setItemData(index, address)
                self.loop_target_combo.setItemData(
                    index, label, Qt.ItemDataRole.ToolTipRole
                )
            else:
                item = self.loop_target_combo.model().item(index)
                if item is not None:
                    item.setEnabled(False)
        self.loop_target_combo.currentIndexChanged.connect(
            self._change_loop_target
        )
        self.color_fields_widget = QWidget()
        self.color_fields_layout = QGridLayout(self.color_fields_widget)
        self.color_fields_layout.setContentsMargins(0, 0, 0, 0)
        self.color_fields_layout.setSpacing(12)
        parameter_group_layout.addWidget(self.color_fields_widget)
        self.parameter_widget = QWidget()
        self.parameter_form = QFormLayout(self.parameter_widget)
        self.parameter_form.setContentsMargins(0, 0, 0, 0)
        self.parameter_form.setHorizontalSpacing(14)
        self.parameter_form.setVerticalSpacing(6)
        parameter_group_layout.addWidget(self.parameter_widget)
        root.addWidget(self.parameter_group)
        self.help_label = QLabel()
        self.help_label.setObjectName("infoPanel")
        self.help_label.setWordWrap(True)
        root.addWidget(self.help_label)
        self.help_label.hide()
        self.preview_label = QLabel()
        self.preview_label.setObjectName("pendingBanner")
        self.preview_label.setWordWrap(True)
        root.addWidget(self.preview_label)
        self.preview_label.hide()
        self.buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        self.buttons.button(QDialogButtonBox.StandardButton.Ok).setText(
            "插入指令" if operation == "insert" else "应用参数"
        )
        self.buttons.button(QDialogButtonBox.StandardButton.Cancel).setText("取消")
        self.buttons.accepted.connect(self._accept_command)
        self.buttons.rejected.connect(self.reject)
        root.addWidget(self.buttons)
        self.command_type.currentIndexChanged.connect(self._select_preset)
        self.parameter_editors: list[tuple[int, QSpinBox, bool]] = []
        self.color_swatches: dict[int, QLabel] = {}
        self.beam_color.toggled.connect(self._change_color_type)
        self.physical_color.toggled.connect(self._change_physical_color_type)
        self.rule_42.toggled.connect(self._change_rule_opcode_42)
        self.rule_c2.toggled.connect(self._change_rule_opcode_c2)
        self.rule_variant.currentIndexChanged.connect(self._change_rule_variant)
        self._rebuild_parameter_form()

    def _change_color_type(self, checked: bool) -> None:
        if not checked or not self._raw or self._raw[0] != 0xF0:
            return
        self._raw[1] = 0x10
        self._validate()

    def _change_physical_color_type(self, checked: bool) -> None:
        if not checked or not self._raw or self._raw[0] != 0xF0:
            return
        self._raw[1] = 0x11
        self._validate()

    def _change_rule_opcode_42(self, checked: bool) -> None:
        if checked and self._raw and self._raw[0] in _OBJECT_RULE_OPCODES:
            self._raw[0] = 0x42
            self._validate()

    def _change_rule_opcode_c2(self, checked: bool) -> None:
        if checked and self._raw and self._raw[0] in _OBJECT_RULE_OPCODES:
            self._raw[0] = 0xC2
            self._validate()

    def _change_rule_variant(self, index: int) -> None:
        if self._raw and self._raw[0] in _OBJECT_RULE_OPCODES and len(self._raw) >= 2:
            self._raw[1] = 0x69 if index == 0 else 0x6A
            self._validate()

    def _change_beam_rule(self, index: int) -> None:
        if self._raw and self._raw[0] == 0xF3 and len(self._raw) >= 3:
            # The reference editor fixes byte 1 to $22 and exposes only its
            # 01--FF named rule selector.
            self._raw[1] = 0x22
            self._raw[2] = index + 1
            self._validate()

    def _change_beam_library(self, index: int) -> None:
        if self._raw and self._raw[0] == 0xF2 and len(self._raw) >= 4:
            self._raw[3] = index
            self._validate()
        elif self._raw and self._raw[0] in (0xE0, 0xE1) and len(self._raw) >= 2:
            self._raw[1] = index
            self._validate()

    def _change_loop_target(self, index: int) -> None:
        if not self._raw or self._raw[0] != 0xFE or len(self._raw) < 4:
            return
        address = self.loop_target_combo.itemData(index)
        if address is None:
            return
        self._raw[2:4] = int(address).to_bytes(2, "little")
        self._validate()

    def _change_object(self, index: int) -> None:
        if self._raw and self._raw[0] == 0xF9 and len(self._raw) == 4:
            self._raw[1] = index
            self._validate()

    def _change_object_rule(self, local: int, index: int) -> None:
        if self._raw and self._raw[0] in _OBJECT_RULE_OPCODES and len(self._raw) == 5:
            self._raw[local] = index + 1
            self._validate()

    def _accept_command(self) -> None:
        if self._raw and self._raw[0] == 0xF2 and len(self._raw) >= 4:
            prompt = QMessageBox(
                QMessageBox.Icon.Question,
                "信息：",
                "是否是大型机体专用光束武器？",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                self,
            )
            yes_button = prompt.button(QMessageBox.StandardButton.Yes)
            no_button = prompt.button(QMessageBox.StandardButton.No)
            yes_button.setText("是(Y)")
            no_button.setText("否(N)")
            prompt.setDefaultButton(
                yes_button if self._raw[1] == 0x04 else no_button
            )
            answer = QMessageBox.StandardButton(prompt.exec())
            self._raw[1] = (
                0x04
                if answer == QMessageBox.StandardButton.Yes
                else 0x03
            )
            self._raw[2] = 0x01
            self._validate()
        self.accept()

    def _select_preset(self, index: int) -> None:
        if not self.allow_type_change:
            return
        _label, preset, _hint = _WEAPON_COMMAND_PRESETS[index]
        self._raw = bytearray(preset)
        self._rebuild_parameter_form()

    def _parameter_ranges(self) -> tuple[tuple[int, int, int], ...]:
        if self._raw and self._raw[0] in _OBJECT_RULE_OPCODES:
            return ()
        if self.operation == "insert" or self.allow_type_change:
            ranges = list(_insert_parameter_ranges(bytes(self._raw)))
            if self._raw and self._raw[0] == 0xF0:
                ranges = [
                    (local, low, 0x3F if local >= 3 else high)
                    for local, low, high in ranges
                ]
            return tuple(ranges)
        probe = bytes(self._raw) if self._raw == b"\xFF" else bytes(self._raw) + b"\xFF"
        rows, complete = decode_script(probe, 0)
        if complete and rows and self._raw and self._raw[0] in (*_OBJECT_RULE_OPCODES, 0xF9):
            return _insert_parameter_ranges(bytes(self._raw))
        return rows[0].editable if complete and rows else ()

    def _rebuild_parameter_form(self) -> None:
        while self.parameter_form.count():
            item = self.parameter_form.takeAt(0)
            if item.widget() is not None:
                item.widget().deleteLater()
        while self.color_fields_layout.count():
            item = self.color_fields_layout.takeAt(0)
            if item.widget() is not None:
                item.widget().deleteLater()
        self.parameter_editors.clear()
        self.color_swatches.clear()
        is_color = bool(self._raw and self._raw[0] == 0xF0)
        is_object_rule = bool(self._raw and self._raw[0] in _OBJECT_RULE_OPCODES)
        is_object_creation = bool(self._raw and self._raw[0] == 0xF9)
        is_beam_rule = bool(self._raw and self._raw[0] == 0xF3)
        is_library_address = bool(
            self._raw and self._raw[0] in (0xE0, 0xE1, 0xF2)
        )
        is_loop = bool(self._raw and self._raw[0] == 0xFE)
        self.color_type_widget.setVisible(is_color)
        self.rule_type_widget.setVisible(is_object_rule)
        self.color_fields_widget.setVisible(is_color)
        self.parameter_widget.setVisible(not is_color)
        self.beam_rule_combo.setVisible(is_beam_rule)
        self.beam_library_combo.setVisible(is_library_address)
        self.object_combo.setVisible(is_object_creation)
        self.loop_target_combo.setVisible(is_loop)
        for combo in self.object_rule_combos:
            combo.setVisible(is_object_rule)
        if is_color:
            blocked_beam = self.beam_color.blockSignals(True)
            blocked_physical = self.physical_color.blockSignals(True)
            self.physical_color.setChecked(self._raw[1] == 0x11)
            self.beam_color.setChecked(self._raw[1] != 0x11)
            self.beam_color.blockSignals(blocked_beam)
            self.physical_color.blockSignals(blocked_physical)
        if is_object_rule:
            blocked_42 = self.rule_42.blockSignals(True)
            blocked_c2 = self.rule_c2.blockSignals(True)
            blocked_variant = self.rule_variant.blockSignals(True)
            self.rule_42.setChecked(not bool(self._raw[0] & 0x80))
            self.rule_c2.setChecked(bool(self._raw[0] & 0x80))
            self.rule_variant.setCurrentIndex(0 if self._raw[1] == 0x69 else 1)
            self.rule_42.blockSignals(blocked_42)
            self.rule_c2.blockSignals(blocked_c2)
            self.rule_variant.blockSignals(blocked_variant)
            for local, combo in zip((2, 3, 4), self.object_rule_combos):
                blocked_rule = combo.blockSignals(True)
                combo.setCurrentIndex(max(0, min(self._raw[local] - 1, 0xFB)))
                combo.blockSignals(blocked_rule)
            self.parameter_form.addRow("物体取图规律", self.object_rule_combos[0])
            self.parameter_form.addRow("物体X轴运行规律", self.object_rule_combos[1])
            self.parameter_form.addRow("物体Y轴运行规律", self.object_rule_combos[2])
        if is_beam_rule:
            blocked_beam_rule = self.beam_rule_combo.blockSignals(True)
            value = self._raw[2] if len(self._raw) >= 3 else 1
            self.beam_rule_combo.setCurrentIndex(
                max(0, min(value - 1, self.beam_rule_combo.count() - 1))
            )
            self.beam_rule_combo.blockSignals(blocked_beam_rule)
            self.parameter_form.addRow("光束运行规律", self.beam_rule_combo)
        if is_library_address:
            blocked_beam_library = self.beam_library_combo.blockSignals(True)
            value = (
                self._raw[3]
                if self._raw[0] == 0xF2 and len(self._raw) >= 4
                else self._raw[1]
            )
            self.beam_library_combo.setCurrentIndex(value)
            self.beam_library_combo.blockSignals(blocked_beam_library)
            self.parameter_form.addRow("图库地址", self.beam_library_combo)
        if is_object_creation:
            blocked_object = self.object_combo.blockSignals(True)
            self.object_combo.setCurrentIndex(self._raw[1])
            self.object_combo.blockSignals(blocked_object)
            self.parameter_form.addRow("物体编号", self.object_combo)
        if is_loop:
            blocked_loop = self.loop_target_combo.blockSignals(True)
            target = int.from_bytes(self._raw[2:4], "little")
            target_index = next(
                (
                    index
                    for index, (_label, address) in enumerate(self.loop_targets)
                    if address == target
                ),
                0,
            )
            self.loop_target_combo.setCurrentIndex(target_index)
            self.loop_target_combo.blockSignals(blocked_loop)
            self.parameter_form.addRow("跳转地址", self.loop_target_combo)
        for local, low, high in self._parameter_ranges():
            editor = HexByteSpinBox() if _parameter_uses_hex(bytes(self._raw), local) else QSpinBox()
            signed = bool(
                (self._raw[0] == 0xFD and local in (1, 2))
                or (self._raw[0] == 0xF7 and local == 2)
            )
            if signed:
                editor.setRange(-128, 127)
                editor.setValue(int.from_bytes(self._raw[local:local + 1], signed=True))
                editor.setSuffix(" 格")
            else:
                editor.setRange(low, high)
                editor.setValue(
                    self._raw[local] & 0x0F
                    if self._raw[0] == 0xF9 and local == 1
                    else self._raw[local]
                )
                if self._raw[0] < 0xE0 and self._raw[0] not in _OBJECT_RULE_OPCODES:
                    editor.setSuffix(" 帧")
            editor.setToolTip(
                "这里显示的是游戏中的实际参数；"
                f"底层编码位置为第 {local + 1} 字节。"
            )
            editor.valueChanged.connect(
                lambda value, index=local, is_signed=signed: self._change_parameter(
                    index, value, is_signed
                )
            )
            field: QWidget = editor
            if self._raw[0] == 0xF0 and local >= 3:
                field = QWidget()
                field_layout = QVBoxLayout(field)
                field_layout.setContentsMargins(0, 0, 0, 0)
                field_layout.setSpacing(4)
                field_layout.addWidget(QLabel(f"颜色 {local - 2}"), 0, Qt.AlignmentFlag.AlignCenter)
                swatch = QLabel()
                swatch.setFixedSize(58, 38)
                self.color_swatches[local] = swatch
                field_layout.addWidget(swatch, 0, Qt.AlignmentFlag.AlignCenter)
                field_layout.addWidget(editor)
                self._refresh_color_swatch(local)
                color_index = local - 3
                self.color_fields_layout.addWidget(
                    field, color_index // 3, color_index % 3
                )
            else:
                self.parameter_form.addRow(
                    _command_parameter_name(bytes(self._raw), local), field
                )
            self.parameter_editors.append((local, editor, signed))
        if not self.parameter_editors and not (
            is_object_rule or is_beam_rule or is_library_address
            or is_object_creation or is_loop
        ):
            message = QLabel("这个动作没有需要设置的参数。")
            message.setObjectName("hintText")
            self.parameter_form.addRow(message)
        if is_color and len(self.parameter_editors) > 3:
            self.resize(480, 460)
        self._validate()

    def _change_parameter(self, local: int, value: int, signed: bool) -> None:
        self._raw[local] = value & 0xFF if signed else value
        self._refresh_color_swatch(local)
        self._validate()

    def _refresh_color_swatch(self, local: int) -> None:
        swatch = self.color_swatches.get(local)
        if swatch is None:
            return
        color = palette_color(self._raw[local])
        swatch.setStyleSheet(
            f"background: {color.name()}; border: 1px solid #8698a1; border-radius: 3px;"
        )
        swatch.setToolTip(f"NES 颜色 {self._raw[local]:02X}")

    def _validate(self) -> bool:
        self.help_label.setText(_WEAPON_COMMAND_PRESETS[self.command_type.currentIndex()][2])
        try:
            raw = bytes(self._raw)
            if not raw:
                raise ValueError("这个动作没有可用内容。")
            probe = raw if raw == b"\xFF" else raw + b"\xFF"
            rows, complete = decode_script(probe, 0)
            if not complete or not rows or rows[0].raw != raw:
                raise ValueError("当前参数无法组成完整的动画动作。")
            if not self.allow_type_change and self._original is not None:
                if len(raw) != len(self._original):
                    raise ValueError(
                        "右键“编辑”只能修改当前指令参数，不能改变指令长度；"
                        "请使用删除和插入更换指令。"
                    )
                if _weapon_command_preset_index(raw) != self._original_type:
                    raise ValueError(
                        "右键“编辑”不能更换指令类型；请使用删除和插入更换指令。"
                    )
            self.raw_edit.setText(raw.hex(" ").upper())
            self.preview_label.setText(f"实际效果：{rows[0].text}")
            self.preview_label.setStyleSheet("")
            self.buttons.button(QDialogButtonBox.StandardButton.Ok).setEnabled(True)
            return True
        except ValueError as error:
            self.preview_label.setText(f"不能应用：{error}")
            self.preview_label.setStyleSheet("color: #a32626;")
            self.buttons.button(QDialogButtonBox.StandardButton.Ok).setEnabled(False)
            return False

    def command(self) -> bytes:
        return bytes(self._raw)


class WeaponAnimationCommandPaletteDialog(QDialog):
    """Reference-style first step used only to choose a new command type."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("动画指令")
        self.setModal(True)
        self.setFixedSize(304, 540)
        root = QVBoxLayout(self)
        root.setContentsMargins(12, 12, 12, 12)
        root.setSpacing(4)
        self.command_list = QListWidget()
        self.command_list.setStyleSheet(
            "QListWidget { border: none; background: transparent; outline: 0; }"
            "QListWidget::item { background: #e8f5fb; border: 1px solid #80b8cf; "
            "border-radius: 3px; margin: 2px; color: #183946; }"
            "QListWidget::item:selected { background: #4f91a6; color: white; "
            "border-color: #397b90; }"
            "QListWidget::item:disabled { background: #f1f3f4; color: #8b969b; "
            "border-color: #c8d0d4; }"
        )
        self.command_list.setUniformItemSizes(True)
        for preset_index, label, description in _LEGACY_WEAPON_INSERT_ROWS:
            item = QListWidgetItem(label)
            item.setData(Qt.ItemDataRole.UserRole, preset_index)
            item.setToolTip(description)
            item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            item.setSizeHint(QSize(260, 34))
            self.command_list.addItem(item)
        self.command_list.setCurrentRow(0)
        self.command_list.itemClicked.connect(
            lambda item: self.accept() if item.flags() & Qt.ItemFlag.ItemIsEnabled else None
        )
        root.addWidget(self.command_list, 1)

    def preset(self) -> bytes:
        item = self.command_list.currentItem()
        if item is None or item.data(Qt.ItemDataRole.UserRole) is None:
            raise ValueError("尚未选择要插入的武器动画指令。")
        return _WEAPON_COMMAND_PRESETS[item.data(Qt.ItemDataRole.UserRole)][1]


class _SpritePuzzleCanvas(QLabel):
    pressed = Signal(float, float, object)

    def mousePressEvent(self, event: QMouseEvent) -> None:  # type: ignore[override]
        if self.pixmap() is not None and not self.pixmap().isNull():
            pixmap = self.pixmap()
            left = (self.width() - pixmap.width()) / 2
            top = (self.height() - pixmap.height()) / 2
            if (
                left <= event.position().x() < left + pixmap.width()
                and top <= event.position().y() < top + pixmap.height()
            ):
                self.pressed.emit(
                    (event.position().x() - left) / pixmap.width(),
                    (event.position().y() - top) / pixmap.height(),
                    event.button(),
                )
        super().mousePressEvent(event)


class SpritePuzzlePreviewDialog(QDialog):
    """Render the verified physical-puzzle stream against real CHR tiles."""

    _PALETTES = (
        ("#151922", "#86A8D9", "#D7E5F4", "#FFFFFF"),
        ("#151922", "#72B58A", "#B8E3A8", "#F0FFD8"),
        ("#151922", "#C99163", "#F3C77D", "#FFF0C2"),
        ("#151922", "#B57DB6", "#E0B4D8", "#FFE7FA"),
    )

    def __init__(
        self,
        record: AnimationRecord,
        project,
        codec: AnimationCodec,
        parent: QWidget | None = None,
        *,
        initial_library: int = 8,
        editable: bool = False,
        puzzle_kind: str = "physical",
    ) -> None:
        super().__init__(parent)
        self.project = project
        self.codec = codec
        self.editable = editable
        self.puzzle_kind = puzzle_kind
        self._loading_code = False
        self.initial_record = record
        self.current_record = record
        self.timeline_frames: tuple[int, ...] = (record.index,)
        self.timeline_loop_start: int | None = None
        self.timeline_terminated = True
        self.frame_index = 0
        self.setWindowTitle("光束拼图" if puzzle_kind == "beam" else "物理拼图")
        if editable:
            self.resize(800 if puzzle_kind == "beam" else 1030, 640 if puzzle_kind == "beam" else 703)
        else:
            self.resize(1180, 760)
        root = QVBoxLayout(self)

        settings = QGroupBox("参考设置")
        form = QFormLayout(settings)
        self.library_combo = QComboBox()
        bank_count = self.project.chr_tile_count // 64
        for bank in range(max(0, bank_count - 3)):
            self.library_combo.addItem(
                f"[{bank:02X}]{bank:03d}：{0x80010 + bank * 0x400:05X}",
                bank,
            )
        selected = self.library_combo.findData(initial_library)
        self.library_combo.setCurrentIndex(max(0, selected))
        form.addRow("图库地址：", self.library_combo)
        offsets = QHBoxLayout()
        self.zero_start = QSpinBox()
        self.high_start = QSpinBox()
        for spin in (self.zero_start, self.high_start):
            spin.setRange(0, 0xFF)
            spin.setDisplayIntegerBase(16)
            spin.setPrefix("$")
        if puzzle_kind == "beam":
            self.zero_start.setValue(0x40)
        self.high_start.setValue(0x80)
        if editable:
            self.low_start_radio = QRadioButton(
                "40 开始" if puzzle_kind == "beam" else "00 开始"
            )
            self.high_start_radio = QRadioButton("80 开始")
            self.low_start_radio.setChecked(True)
            self.zero_start.hide()
            self.high_start.hide()
            offsets.addWidget(self.low_start_radio)
            offsets.addWidget(self.high_start_radio)
        else:
            offsets.addWidget(QLabel("00 开始"))
            offsets.addWidget(self.zero_start)
            offsets.addWidget(QLabel("80 开始"))
            offsets.addWidget(self.high_start)
        self.show_numbers = QCheckBox("显示图块编号")
        self.show_numbers.setChecked(True)
        offsets.addWidget(self.show_numbers)
        offsets.addStretch()
        form.addRow("映射：", offsets)
        flips = QHBoxLayout()
        if editable:
            self.flip_horizontal = QPushButton("图片水平翻转")
            self.flip_vertical = QPushButton("图片垂直翻转")
        else:
            self.flip_horizontal = QCheckBox("图片水平翻转")
            self.flip_vertical = QCheckBox("图片垂直翻转")
        flips.addWidget(self.flip_horizontal)
        flips.addWidget(self.flip_vertical)
        flips.addStretch()
        if not (editable and puzzle_kind == "beam"):
            form.addRow("效果图片：", flips)
        else:
            self.flip_horizontal.hide()
            self.flip_vertical.hide()
        root.addWidget(settings)

        content = QHBoxLayout()
        source = QGroupBox("组图规律与解释")
        source_layout = QVBoxLayout(source)
        self.code_view = QPlainTextEdit(record.raw.hex(" ").upper())
        self.code_view.setReadOnly(not editable)
        self.code_view.setMaximumHeight(92)
        self.code_view.setToolTip(
            "按两位十六进制字节编辑当前拼图规律；确定后返回规律窗口草稿。"
            if editable
            else "当前组图规律的只读代码。"
        )
        source_layout.addWidget(self.code_view)
        self.code_error = QLabel()
        self.code_error.setObjectName("errorPanel")
        self.code_error.setWordWrap(True)
        self.code_error.setVisible(False)
        source_layout.addWidget(self.code_error)
        self.placement_table = QTableWidget(0, 5)
        self.placement_table.setHorizontalHeaderLabels(
            ("指令", "图块", "X", "Y", "属性")
        )
        self.placement_table.verticalHeader().hide()
        self.placement_table.horizontalHeader().setSectionResizeMode(
            QHeaderView.ResizeMode.Stretch
        )
        self.placement_table.setEditTriggers(
            QTableWidget.EditTrigger.NoEditTriggers
        )
        source_layout.addWidget(self.placement_table, 1)
        content.addWidget(source, 3)

        library = QGroupBox("图库")
        library_layout = QVBoxLayout(library)
        self.library_list = QListWidget()
        self.library_list.setViewMode(QListView.ViewMode.IconMode)
        self.library_list.setResizeMode(QListView.ResizeMode.Adjust)
        self.library_list.setMovement(QListView.Movement.Static)
        self.library_list.setIconSize(QSize(32, 32))
        self.library_list.setGridSize(QSize(48, 50))
        self.library_list.setSelectionMode(
            QListWidget.SelectionMode.SingleSelection
            if editable
            else QListWidget.SelectionMode.NoSelection
        )
        library_layout.addWidget(self.library_list)
        content.addWidget(library, 3)

        preview = QGroupBox("效果图片")
        preview_layout = QVBoxLayout(preview)
        self.preview_label = _SpritePuzzleCanvas()
        self.preview_label.setMinimumSize(390, 390)
        self.preview_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.preview_label.setStyleSheet("background:#151922; border:1px solid #66717a;")
        preview_layout.addWidget(self.preview_label, 1)
        self.preview_status = QLabel()
        self.preview_status.setWordWrap(True)
        preview_layout.addWidget(self.preview_status)
        if editable:
            edit_hint = QLabel(
                (
                    "图库左键选择图块；效果图左键替换命中的图块，右键删除。"
                    if puzzle_kind == "beam"
                    else "先在列表和图库中选择图块；效果图左键修改图块与位置，右键切换翻转。"
                )
            )
            edit_hint.setWordWrap(True)
            preview_layout.addWidget(edit_hint)
        content.addWidget(preview, 4)
        root.addLayout(content, 1)

        playback = QGroupBox("运行规律播放（只影响预览）")
        playback_layout = QHBoxLayout(playback)
        self.timeline_combo = QComboBox()
        self.timeline_combo.addItem(
            f"单帧：组图 ${record.index:02X}", None
        )
        movement_names = animation_names(
            "地图动画运行规律名称.ini", codec.count("movement"), 1
        )
        roles = codec.movement_roles()
        for index in sorted(
            value for value, role in roles.items() if role == {"frames"}
        ):
            self.timeline_combo.addItem(
                f"[{index:02X}]{index:03d}：{movement_names[index]}", index
            )
        playback_layout.addWidget(self.timeline_combo, 1)
        self.previous_button = QPushButton("上一帧")
        self.play_button = QPushButton("播放")
        self.next_button = QPushButton("下一帧")
        playback_layout.addWidget(self.previous_button)
        playback_layout.addWidget(self.play_button)
        playback_layout.addWidget(self.next_button)
        self.frame_status = QLabel()
        playback_layout.addWidget(self.frame_status, 1)
        root.addWidget(playback)
        playback.setVisible(not editable)

        self.timer = QTimer(self)
        self.timer.setInterval(1000 // 12)
        self.timer.timeout.connect(self._advance_frame)
        self.library_combo.currentIndexChanged.connect(self._refresh_all)
        self.zero_start.valueChanged.connect(self._refresh_all)
        self.high_start.valueChanged.connect(self._refresh_all)
        self.show_numbers.toggled.connect(self._render_preview)
        if self.editable:
            self.flip_horizontal.clicked.connect(
                lambda: self._flip_composition(horizontal=True)
            )
            self.flip_vertical.clicked.connect(
                lambda: self._flip_composition(horizontal=False)
            )
        else:
            self.flip_horizontal.toggled.connect(self._render_preview)
            self.flip_vertical.toggled.connect(self._render_preview)
        self.timeline_combo.currentIndexChanged.connect(self._timeline_changed)
        self.previous_button.clicked.connect(lambda: self._step_frame(-1))
        self.next_button.clicked.connect(lambda: self._step_frame(1))
        self.play_button.clicked.connect(self._toggle_playback)
        if self.editable:
            self.code_view.textChanged.connect(self._code_changed)
            self.preview_label.pressed.connect(self._preview_pressed)
            self.low_start_radio.toggled.connect(self._refresh_all)
            self.high_start_radio.toggled.connect(self._refresh_all)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.button(QDialogButtonBox.StandardButton.Ok).setText("确定")
        buttons.button(QDialogButtonBox.StandardButton.Cancel).setText("取消")
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        root.addWidget(buttons)
        self._timeline_changed()
        self._populate_library()

    @staticmethod
    def _parse_hex(text: str) -> bytes:
        normalized = text.replace(",", " ").strip()
        if not normalized:
            raise ValueError("拼图规律代码不能为空。")
        tokens = normalized.split()
        if any(len(token) != 2 for token in tokens):
            raise ValueError("拼图规律必须使用空格分隔的两位十六进制字节。")
        try:
            return bytes(int(token, 16) for token in tokens)
        except ValueError as error:
            raise ValueError("拼图规律包含无效十六进制字节。") from error

    @staticmethod
    def _beam_full(raw: bytes) -> bytes:
        if len(raw) < 2:
            return raw
        return bytes((0xFE, raw[1], raw[0])) + raw[2:]

    def _validate_raw(self, raw: bytes, offset: int) -> None:
        composition = (
            decode_legacy_beam_composition(self._beam_full(raw), offset)
            if self.puzzle_kind == "beam"
            else decode_sprite_composition(raw, offset)
        )
        if not composition.complete:
            raise ValueError(composition.error or "拼图规律没有正常结束。")
        expected_length = len(raw) + 1 if self.puzzle_kind == "beam" else len(raw)
        if composition.consumed != expected_length:
            raise ValueError("拼图规律结束码后仍有多余字节。")
        if self.puzzle_kind == "beam" and not composition.editable:
            raise ValueError(composition.error)

    def _code_changed(self) -> None:
        if self._loading_code or not self.editable:
            return
        try:
            raw = self._parse_hex(self.code_view.toPlainText())
            self._validate_raw(raw, self.initial_record.offset)
        except ValueError as error:
            self.code_error.setText(str(error))
            self.code_error.setVisible(True)
            return
        self.code_error.clear()
        self.code_error.setVisible(False)
        self.initial_record = replace(self.initial_record, raw=raw)
        self.current_record = self.initial_record
        self.timeline_frames = (self.initial_record.index,)
        self.timeline_combo.setCurrentIndex(0)
        self.frame_index = 0
        self._render_preview()

    def edited_raw(self) -> bytes:
        raw = self._parse_hex(self.code_view.toPlainText())
        self._validate_raw(raw, self.initial_record.offset)
        return raw

    def _apply_placements(self, placements) -> None:
        composition = self._composition()
        if self.puzzle_kind == "beam":
            if not isinstance(composition, BeamComposition) or not composition.editable:
                raise ValueError(composition.error or "该光束规律当前不能安全编辑。")
            full = encode_legacy_beam_composition(
                tuple(placements),
                anchor_x=composition.anchor_x,
                anchor_y=composition.anchor_y,
            )
            raw = bytes((full[2], full[1])) + full[3:]
        else:
            raw = encode_legacy_sprite_composition(tuple(placements))
        self._loading_code = True
        self.code_view.setPlainText(raw.hex(" ").upper())
        self._loading_code = False
        self.initial_record = replace(self.initial_record, raw=raw)
        self.current_record = self.initial_record
        self.timeline_frames = (self.initial_record.index,)
        self.frame_index = 0
        self.code_error.clear()
        self.code_error.setVisible(False)
        self._render_preview()

    def _flip_composition(self, *, horizontal: bool) -> None:
        composition = self._composition()
        if not composition.placements:
            return
        if horizontal:
            placements = [
                replace(
                    item,
                    x=-item.x,
                    attributes=item.attributes ^ 0x40,
                )
                for item in composition.placements
            ]
        else:
            placements = [
                replace(
                    item,
                    y=-item.y,
                    attributes=item.attributes ^ 0x80,
                )
                for item in composition.placements
            ]
        try:
            self._apply_placements(placements)
        except ValueError as error:
            QMessageBox.warning(self, "无法翻转图片", str(error))

    def _edit_placement(self, row: int) -> None:
        composition = self._composition()
        if not 0 <= row < len(composition.placements):
            return
        placement = composition.placements[row]
        dialog = QDialog(self)
        dialog.setWindowTitle("编辑图块")
        layout = QVBoxLayout(dialog)
        form = QFormLayout()
        tile = HexByteSpinBox()
        tile.setRange(0, 0xFF)
        tile.setValue(placement.tile_token)
        x_editor = QSpinBox()
        y_editor = QSpinBox()
        for editor, value in ((x_editor, placement.x), (y_editor, placement.y)):
            editor.setRange(-128, 127)
            editor.setValue(value)
        palette = QSpinBox()
        palette.setRange(0, 3)
        palette.setValue(placement.palette)
        horizontal = QCheckBox("水平翻转")
        vertical = QCheckBox("垂直翻转")
        horizontal.setChecked(placement.horizontal_flip)
        vertical.setChecked(placement.vertical_flip)
        form.addRow("图块编号", tile)
        form.addRow("X 坐标", x_editor)
        form.addRow("Y 坐标", y_editor)
        form.addRow("调色板", palette)
        flips = QHBoxLayout()
        flips.addWidget(horizontal)
        flips.addWidget(vertical)
        flips.addStretch()
        form.addRow("翻转", flips)
        layout.addLayout(form)
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok
            | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.button(QDialogButtonBox.StandardButton.Ok).setText("应用")
        buttons.button(QDialogButtonBox.StandardButton.Cancel).setText("取消")
        buttons.accepted.connect(dialog.accept)
        buttons.rejected.connect(dialog.reject)
        layout.addWidget(buttons)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        attributes = palette.value()
        if horizontal.isChecked():
            attributes |= 0x40
        if vertical.isChecked():
            attributes |= 0x80
        placements = list(composition.placements)
        placements[row] = replace(
            placement,
            x=x_editor.value(),
            y=y_editor.value(),
            tile_index=tile.value() if tile.value() < 0xF8 else None,
            tile_token=tile.value(),
            attributes=attributes,
        )
        try:
            self._apply_placements(placements)
        except ValueError as error:
            QMessageBox.warning(self, "无法编辑图块", str(error))

    def _preview_pressed(self, nx: float, ny: float, button) -> None:
        composition = self._composition()
        if isinstance(composition, BeamComposition) and not composition.editable:
            self.code_error.setText(composition.error)
            self.code_error.setVisible(True)
            return
        if not composition.placements or not hasattr(self, "_render_geometry"):
            return
        min_x, min_y, width, height = self._render_geometry
        image_x = nx * width
        image_y = ny * height
        if self.puzzle_kind == "beam":
            column = max(0, min(15, int(image_x // 8)))
            row_value = max(0, min(15, int(image_y // 8)))
            hit = next(
                (
                    index
                    for index, item in enumerate(composition.placements)
                    if (item.x & 0x0F) == column
                    and (item.y & 0x0F) == row_value
                ),
                None,
            )
            placements = list(composition.placements)
            use_high = self.high_start_radio.isChecked()
            for index, item in enumerate(placements):
                token = item.tile_token
                if use_high and 0x40 <= token < 0x80:
                    token += 0x40
                elif not use_high and 0x80 <= token < 0xC0:
                    token -= 0x40
                if token != item.tile_token:
                    placements[index] = replace(
                        item,
                        tile_index=token,
                        tile_token=token,
                    )
            if button == Qt.MouseButton.LeftButton:
                selected_item = self.library_list.currentItem()
                logical = (
                    int(selected_item.data(Qt.ItemDataRole.UserRole))
                    if selected_item is not None else 0
                )
                selected_tile = self._mapped_tile(logical)
                world_x = (composition.anchor_x & 0xF0) | column
                world_y = (composition.anchor_y & 0xF0) | row_value
                if hit is None:
                    template = placements[-1]
                    placements.append(
                        replace(
                            template,
                            command_offset=self.initial_record.offset,
                            x=world_x,
                            y=world_y,
                            tile_index=selected_tile,
                            tile_token=selected_tile,
                            attributes=0,
                        )
                    )
                    target_row = len(placements) - 1
                else:
                    target = placements[hit]
                    placements[hit] = replace(
                        target,
                        tile_index=selected_tile,
                        tile_token=selected_tile,
                    )
                    target_row = hit
                try:
                    self._apply_placements(placements)
                    self.placement_table.selectRow(target_row)
                except ValueError as error:
                    QMessageBox.warning(self, "无法修改图块", str(error))
                return
            if button == Qt.MouseButton.RightButton and hit is not None:
                del placements[hit]
                try:
                    self._apply_placements(placements)
                except ValueError as error:
                    QMessageBox.warning(self, "无法修改图块", str(error))
            return
        coordinate_x = image_x
        coordinate_y = image_y
        row = min(
            range(len(composition.placements)),
            key=lambda index: (
                (composition.placements[index].x - min_x + 0.5 - coordinate_x) ** 2
                + (composition.placements[index].y - min_y + 0.5 - coordinate_y) ** 2
            ),
        )
        placement = composition.placements[row]
        selected_row = self.placement_table.currentRow()
        if not 0 <= selected_row < len(composition.placements):
            selected_row = 0
        selected_tile_item = self.library_list.currentItem()
        selected_tile = (
            int(selected_tile_item.data(Qt.ItemDataRole.UserRole))
            if selected_tile_item is not None
            else 0
        )
        if button == Qt.MouseButton.LeftButton:
            placements = list(composition.placements)
            target_row = row if self.puzzle_kind == "beam" else selected_row
            target = placements[target_row]
            placements[target_row] = replace(
                target,
                x=max(-128, min(127, round(image_x))),
                y=max(-128, min(127, round(image_y))),
                tile_index=selected_tile if selected_tile < 0xF8 else None,
                tile_token=selected_tile,
            )
            try:
                self._apply_placements(placements)
                self.placement_table.selectRow(target_row)
            except ValueError as error:
                QMessageBox.warning(self, "无法修改图块", str(error))
            return
        if button != Qt.MouseButton.RightButton:
            return
        placements = list(composition.placements)
        placement = placements[selected_row]
        placements[selected_row] = replace(
            placement, attributes=placement.attributes ^ 0x40
        )
        try:
            self._apply_placements(placements)
        except ValueError as error:
            QMessageBox.warning(self, "无法修改图块", str(error))

    def _mapped_tile(self, logical: int) -> int:
        if self.editable:
            start = (
                self.high_start.value()
                if self.high_start_radio.isChecked()
                else self.zero_start.value()
            )
            return (start + logical) & 0xFF
        if logical < 0x80:
            return (self.zero_start.value() + logical) & 0xFF
        return (self.high_start.value() + (logical & 0x7F)) & 0xFF

    def _tile_image(self, logical: int, palette: int = 0) -> QImage:
        mapped = self._mapped_tile(logical)
        bank = int(self.library_combo.currentData() or 0)
        pixels = self.project.chr_tile_pixels(bank * 64 + mapped)
        image = QImage(8, 8, QImage.Format.Format_RGB32)
        colors = tuple(QColor(value) for value in self._PALETTES[palette & 3])
        for y in range(8):
            for x in range(8):
                image.setPixelColor(x, y, colors[pixels[y * 8 + x]])
        return image

    def _populate_library(self) -> None:
        self.library_list.setUpdatesEnabled(False)
        try:
            self.library_list.clear()
            for logical in range(128 if self.editable else 256):
                mapped = self._mapped_tile(logical)
                icon = QPixmap.fromImage(self._tile_image(logical)).scaled(
                    32,
                    32,
                    Qt.AspectRatioMode.KeepAspectRatio,
                    Qt.TransformationMode.FastTransformation,
                )
                item = QListWidgetItem(QIcon(icon), f"{mapped:02X}")
                item.setData(Qt.ItemDataRole.UserRole, logical)
                item.setToolTip(
                    f"逻辑图块 ${logical:02X} → 图库内 ${self._mapped_tile(logical):02X}"
                )
                self.library_list.addItem(item)
            if self.editable and self.library_list.count():
                self.library_list.setCurrentRow(0)
        finally:
            self.library_list.setUpdatesEnabled(True)

    def _composition(self) -> SpriteComposition | BeamComposition:
        if self.puzzle_kind == "beam":
            return decode_legacy_beam_composition(
                self._beam_full(self.current_record.raw),
                self.current_record.offset,
            )
        return decode_sprite_composition(self.current_record.raw, self.current_record.offset)

    def _fill_placement_table(
        self, composition: SpriteComposition | BeamComposition
    ) -> None:
        selected_row = self.placement_table.currentRow()
        self.placement_table.setRowCount(len(composition.placements))
        for row, placement in enumerate(composition.placements):
            tile = (
                f"${placement.tile_index:02X}"
                if self.puzzle_kind == "beam" and placement.tile_index is not None
                else f"${self._mapped_tile(placement.tile_index):02X}"
                if self.editable and placement.tile_index is not None
                else f"${placement.tile_index:02X}"
                if placement.tile_index is not None
                else f"运行时 ${placement.tile_token:02X}"
            )
            flags = []
            if placement.horizontal_flip:
                flags.append("H")
            if placement.vertical_flip:
                flags.append("V")
            flags.append(f"P{placement.palette}")
            for column, value in enumerate(
                (
                    f"${placement.command_offset:06X}",
                    tile,
                    str(placement.x),
                    str(placement.y),
                    "/".join(flags),
                )
            ):
                self.placement_table.setItem(row, column, QTableWidgetItem(value))
        if composition.placements:
            self.placement_table.selectRow(
                min(max(selected_row, 0), len(composition.placements) - 1)
            )

    def _render_preview(self, _checked: bool | None = None) -> None:
        composition = self._composition()
        self._fill_placement_table(composition)
        if not composition.placements:
            self.preview_label.setPixmap(QPixmap())
            self.preview_label.setText(composition.error or "该组图没有可显示的图块。")
            self.preview_status.setText(composition.error)
            return
        min_x = min(item.x for item in composition.placements)
        max_x = max(item.x for item in composition.placements)
        min_y = min(item.y for item in composition.placements)
        max_y = max(item.y for item in composition.placements)
        if self.editable and self.puzzle_kind == "beam":
            min_x = min_y = 0
            width = height = 128
        elif self.editable:
            min_x = min_y = 0
            width = height = 128
        else:
            width = max(24, max_x - min_x + 24)
            height = max(24, max_y - min_y + 24)
        self._render_geometry = (min_x, min_y, width, height)
        image = QImage(width, height, QImage.Format.Format_RGB32)
        image.fill(QColor("#151922"))
        if self.editable:
            painter = QPainter(image)
            painter.setPen(QPen(QColor("#78838d"), 1))
            for grid in range(0, 129, 8):
                painter.drawLine(grid, 0, grid, 127)
                painter.drawLine(0, grid, 127, grid)
            painter.end()
        unresolved = 0
        for placement in composition.placements:
            x = placement.x
            y = placement.y
            horizontal = placement.horizontal_flip
            vertical = placement.vertical_flip
            if self.flip_horizontal.isChecked():
                x = min_x + max_x - x
                horizontal = not horizontal
            if self.flip_vertical.isChecked():
                y = min_y + max_y - y
                vertical = not vertical
            if self.puzzle_kind == "beam" and self.editable:
                target_x = (x & 0x0F) * 8
                target_y = (y & 0x0F) * 8
            else:
                target_x = x - min_x + (0 if self.editable else 8)
                target_y = y - min_y + (0 if self.editable else 8)
            if placement.tile_index is None:
                unresolved += 1
                painter = QPainter(image)
                painter.setPen(QPen(QColor("#FF4FD8"), 1))
                painter.drawRect(target_x, target_y, 7, 7)
                painter.drawLine(target_x, target_y, target_x + 7, target_y + 7)
                painter.drawLine(target_x + 7, target_y, target_x, target_y + 7)
                painter.end()
                continue
            if self.puzzle_kind == "beam":
                bank = int(self.library_combo.currentData() or 0)
                pixels = self.project.chr_tile_pixels(
                    bank * 64 + placement.tile_index
                )
                tile = QImage(8, 8, QImage.Format.Format_RGB32)
                colors = tuple(QColor(value) for value in self._PALETTES[0])
                for py in range(8):
                    for px in range(8):
                        tile.setPixelColor(px, py, colors[pixels[py * 8 + px]])
            else:
                tile = self._tile_image(placement.tile_index, placement.palette)
            for py in range(8):
                source_y = 7 - py if vertical else py
                for px in range(8):
                    source_x = 7 - px if horizontal else px
                    color = tile.pixelColor(source_x, source_y)
                    if color != QColor(self._PALETTES[placement.palette][0]):
                        image.setPixelColor(target_x + px, target_y + py, color)
            if self.show_numbers.isChecked():
                painter = QPainter(image)
                painter.fillRect(target_x, target_y, 8, 4, QColor(0, 0, 0, 190))
                painter.setPen(QColor("white"))
                font = painter.font()
                font.setPixelSize(4)
                painter.setFont(font)
                painter.drawText(target_x, target_y, 8, 4, Qt.AlignmentFlag.AlignCenter,
                                 f"{placement.tile_index:02X}"
                                 if self.puzzle_kind == "beam"
                                 else f"{self._mapped_tile(placement.tile_index):02X}"
                                 if self.editable
                                 else f"{placement.tile_index:02X}")
                painter.end()
        pixmap = QPixmap.fromImage(image).scaled(
            self.preview_label.size(),
            Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.FastTransformation,
        )
        self.preview_label.setText("")
        self.preview_label.setPixmap(pixmap)
        state = "完整" if composition.complete else f"不完整：{composition.error}"
        if isinstance(composition, BeamComposition) and not composition.editable:
            state = f"只读：{composition.error}"
        runtime = f"；{unresolved} 块依赖运行时图块表" if unresolved else ""
        self.preview_status.setText(
            f"组图 ${self.current_record.index:02X} · {len(composition.placements)} 块 · "
            f"锚点 X={composition.anchor_x} / Y={composition.anchor_y} · {state}{runtime}。"
        )

    def _refresh_all(self, _value: int | None = None) -> None:
        self._populate_library()
        self._render_preview()

    def _timeline_changed(self, _index: int | None = None) -> None:
        self.timer.stop()
        self.play_button.setText("播放")
        movement = self.timeline_combo.currentData()
        if movement is None:
            self.timeline_frames = (self.initial_record.index,)
            self.timeline_loop_start = None
            self.timeline_terminated = True
            error = ""
        else:
            record = self.codec.record("movement", int(movement))
            timeline = decode_sprite_timeline(
                record.raw, self.codec.count("sprite")
            )
            self.timeline_frames = timeline.frames or (self.initial_record.index,)
            self.timeline_loop_start = timeline.loop_start
            self.timeline_terminated = timeline.terminated
            error = timeline.error
        self.frame_index = 0
        self._show_frame()
        if error:
            self.frame_status.setToolTip(error)

    def _show_frame(self) -> None:
        sprite = self.timeline_frames[self.frame_index]
        self.current_record = (
            self.initial_record
            if sprite == self.initial_record.index
            else self.codec.record("sprite", sprite)
        )
        self._loading_code = True
        self.code_view.setPlainText(self.current_record.raw.hex(" ").upper())
        self._loading_code = False
        loop = (
            f" · 循环起点 {self.timeline_loop_start + 1}"
            if self.timeline_loop_start is not None
            else ""
        )
        self.frame_status.setText(
            f"帧 {self.frame_index + 1}/{len(self.timeline_frames)} · 组图 ${sprite:02X}{loop}"
        )
        self._render_preview()

    def _step_frame(self, delta: int) -> None:
        if not self.timeline_frames:
            return
        self.frame_index = (self.frame_index + delta) % len(self.timeline_frames)
        self._show_frame()

    def _advance_frame(self) -> None:
        if not self.timeline_frames:
            return
        if self.frame_index + 1 < len(self.timeline_frames):
            self.frame_index += 1
        elif self.timeline_loop_start is not None:
            self.frame_index = self.timeline_loop_start
        elif self.timeline_terminated:
            self.timer.stop()
            self.play_button.setText("播放")
            return
        else:
            self.frame_index = 0
        self._show_frame()

    def _toggle_playback(self) -> None:
        if self.timer.isActive():
            self.timer.stop()
            self.play_button.setText("播放")
        else:
            self.timer.start()
            self.play_button.setText("暂停")

    def accept(self) -> None:
        self.timer.stop()
        if self.editable:
            try:
                raw = self.edited_raw()
            except ValueError as error:
                QMessageBox.warning(self, "无法应用拼图", str(error))
                return
            self.initial_record = replace(self.initial_record, raw=raw)
            self.current_record = self.initial_record
        super().accept()

    def reject(self) -> None:
        self.timer.stop()
        super().reject()


@dataclass(frozen=True)
class _MapPreviewObject:
    object_id: int
    x: int
    y: int
    frame_rule: int
    x_rule: int
    y_rule: int


@dataclass(frozen=True)
class _MapPreviewFrame:
    objects: tuple[_MapPreviewObject, ...]
    library: int
    colors: tuple[int, ...]
    screen_x: int
    screen_y: int
    action: str


class MapAnimationPreviewDialog(QDialog):
    """Play the current map-animation draft without writing a ROM."""

    def __init__(
        self,
        project,
        data: bytes | bytearray,
        animation_index: int,
        animation_name: str,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.project = project
        self.codec = AnimationCodec(data)
        self.animation_index = animation_index
        self.frames, notes = self._build_frames()
        self.frame_index = 0
        self.setWindowTitle(f"预览地图动画：{animation_name}")
        self.resize(690, 650)
        self.setMinimumSize(620, 590)
        root = QVBoxLayout(self)
        title = QLabel(f"[{animation_index:02X}]{animation_index:03d}：{animation_name}")
        title.setObjectName("sectionTitle")
        root.addWidget(title)
        self.preview_label = QLabel()
        self.preview_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.preview_label.setMinimumSize(512, 480)
        self.preview_label.setStyleSheet(
            "background:#111820; border:1px solid #91a8b2; border-radius:4px;"
        )
        root.addWidget(self.preview_label, 1)

        controls = QHBoxLayout()
        self.restart_button = QPushButton("从头播放")
        self.previous_button = QPushButton("上一帧")
        self.play_button = QPushButton("暂停")
        self.next_button = QPushButton("下一帧")
        for button in (
            self.restart_button, self.previous_button, self.play_button,
            self.next_button,
        ):
            controls.addWidget(button)
        controls.addWidget(QLabel("播放速度"))
        self.speed_combo = QComboBox()
        self.speed_combo.addItem("慢速（0.5 倍）", 0.5)
        self.speed_combo.addItem("正常（1 倍）", 1.0)
        self.speed_combo.addItem("快速（2 倍）", 2.0)
        self.speed_combo.setCurrentIndex(1)
        controls.addWidget(self.speed_combo)
        root.addLayout(controls)
        self.frame_slider = QSlider(Qt.Orientation.Horizontal)
        self.frame_slider.setRange(0, max(0, len(self.frames) - 1))
        root.addWidget(self.frame_slider)
        self.frame_status = QLabel()
        self.frame_status.setWordWrap(True)
        root.addWidget(self.frame_status)
        note_text = (
            "直接播放窗口内尚未保存的草稿。图库、组图、颜色、等待、屏幕位移、"
            "循环和结束均来自当前 ROM；依赖战斗现场数据的坐标规律与动态图块无法"
            "脱离游戏完全还原，会保持当前位置或显示占位框。"
        )
        if notes:
            note_text += "\n预览提示：" + "；".join(notes)
        note = QLabel(note_text)
        note.setObjectName("hintText")
        note.setWordWrap(True)
        root.addWidget(note)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        buttons.button(QDialogButtonBox.StandardButton.Close).setText("关闭")
        buttons.rejected.connect(self.reject)
        root.addWidget(buttons)

        self.timer = QTimer(self)
        self.timer.timeout.connect(self._advance)
        self.restart_button.clicked.connect(self._restart)
        self.previous_button.clicked.connect(lambda: self._step(-1))
        self.play_button.clicked.connect(self._toggle_playback)
        self.next_button.clicked.connect(lambda: self._step(1))
        self.speed_combo.currentIndexChanged.connect(self._set_speed)
        self.frame_slider.valueChanged.connect(self._show_frame)
        self._set_speed()
        self._show_frame(0)
        if self.frames:
            self.timer.start()
        else:
            self.play_button.setEnabled(False)

    @staticmethod
    def _signed(value: int) -> int:
        return value - 0x100 if value & 0x80 else value

    def _build_frames(self) -> tuple[tuple[_MapPreviewFrame, ...], tuple[str, ...]]:
        record = self.codec.record("map", self.animation_index)
        if not record.complete:
            return (), ("动画包含尚未识别的指令，无法安全播放。",)
        instructions = record.instructions
        base_pointer = self.codec.pointers["map"][self.animation_index]
        pointer_rows = {
            base_pointer + item.offset - record.offset: row
            for row, item in enumerate(instructions)
        }
        objects: dict[int, _MapPreviewObject] = {}
        library = 0
        colors: tuple[int, ...] = (0x0F, 0x21, 0x31)
        screen_x = screen_y = pc = 0
        loop_remaining: dict[int, int] = {}
        frames: list[_MapPreviewFrame] = []
        notes: set[str] = set()

        def snapshot(action: str) -> _MapPreviewFrame:
            return _MapPreviewFrame(
                tuple(objects[key] for key in sorted(objects)), library, colors,
                screen_x, screen_y, action,
            )

        for _budget in range(4096):
            if not 0 <= pc < len(instructions) or len(frames) >= 1800:
                notes.add("播放达到安全上限，已在当前位置停止。")
                break
            instruction = instructions[pc]
            raw = instruction.raw
            op = raw[0]
            if op < 0xE0 and op not in _OBJECT_RULE_OPCODES:
                frames.extend(snapshot(instruction.text) for _ in range(op or 256))
                pc += 1
                continue
            if op == 0xE0:
                library = raw[1]
            elif op == 0xF0 and len(raw) >= 4:
                colors = tuple(raw[3:])
            elif op in (0xF8, 0xF9):
                count = (
                    2
                    if op == 0xF9
                    else 2 - bool(raw[1] & 0x80) - bool(raw[1] & 0x40)
                )
                object_id = raw[1]
                x = self._signed(raw[2]) if count else 128
                y = self._signed(raw[3]) if count > 1 else 120
                if count < 2:
                    notes.add("部分物体坐标由事件现场传入，预览中放在画面中央。")
                objects[object_id] = _MapPreviewObject(
                    object_id, x, y, 0, 0, 0
                )
            elif op in _OBJECT_RULE_OPCODES and objects:
                key = next(reversed(objects))
                old = objects[key]
                objects[key] = _MapPreviewObject(
                    old.object_id, old.x, old.y, raw[2], raw[3], raw[4]
                )
            elif op == 0xF7:
                screen_x = self._signed(raw[2])
            elif op == 0xFD:
                screen_x += self._signed(raw[1])
                screen_y += self._signed(raw[2])
            elif op == 0xFE:
                remaining = loop_remaining.get(pc, raw[1]) - 1
                if remaining > 0:
                    loop_remaining[pc] = remaining
                    target = int.from_bytes(raw[2:4], "little")
                    if target not in pointer_rows:
                        notes.add("循环目标不在当前动画内，预览在循环处停止。")
                        break
                    pc = pointer_rows[target]
                    continue
                loop_remaining.pop(pc, None)
            elif op == 0xFF:
                if not frames:
                    frames.append(snapshot("动画结束"))
                break
            elif op in (0xF3, 0xF5, 0xF6, 0xFA, 0xFB, 0xFC):
                notes.add("动画含有依赖游戏现场状态的效果，仅显示已确认部分。")
            pc += 1
        if not frames:
            frames.append(snapshot("动画没有等待帧，显示最终状态"))
        return tuple(frames), tuple(sorted(notes))

    def _sprite_frame(self, rule: int, tick: int) -> int | None:
        try:
            timeline = decode_sprite_timeline(
                self.codec.record("movement", rule).raw,
                self.codec.count("sprite"),
                max_frames=360,
            )
            if not timeline.frames:
                return None
            if tick < len(timeline.frames):
                return timeline.frames[tick]
            if timeline.loop_start is not None:
                loop = timeline.frames[timeline.loop_start:]
                return loop[(tick - timeline.loop_start) % len(loop)] if loop else None
            return timeline.frames[-1]
        except (ValueError, IndexError):
            return None

    def _tile(
        self, bank: int, logical: int, colors: tuple[int, ...], palette: int
    ) -> QImage | None:
        absolute = bank * 64 + logical
        if not 0 <= absolute < self.project.chr_tile_count:
            return None
        values = colors[palette * 3:palette * 3 + 3] or colors[:3]
        values = tuple(values) + (0x0F,) * max(0, 3 - len(values))
        display = (palette_color(0x0F), *(palette_color(value) for value in values[:3]))
        image = QImage(8, 8, QImage.Format.Format_ARGB32)
        image.fill(Qt.GlobalColor.transparent)
        for pos, value in enumerate(self.project.chr_tile_pixels(absolute)):
            if value:
                image.setPixelColor(pos % 8, pos // 8, display[value])
        return image

    def _render(self, frame: _MapPreviewFrame, tick: int) -> QPixmap:
        image = QImage(256, 240, QImage.Format.Format_RGB32)
        background = frame.colors[0] if frame.colors else 0x0F
        image.fill(palette_color(background))
        painter = QPainter(image)
        grid_color = palette_color(frame.colors[1] if len(frame.colors) > 1 else 0x10)
        grid_color.setAlpha(110)
        painter.setPen(QPen(grid_color, 1))
        grid_x = frame.screen_x % 16
        grid_y = frame.screen_y % 16
        for x in range(grid_x - 16, 257, 16):
            painter.drawLine(x, 0, x, 239)
        for y in range(grid_y - 16, 241, 16):
            painter.drawLine(0, y, 255, y)
        painter.end()
        unresolved = 0
        for obj in frame.objects:
            sprite = self._sprite_frame(obj.frame_rule, tick)
            if sprite is None:
                unresolved += 1
                continue
            try:
                composition = decode_sprite_composition(
                    self.codec.record("sprite", sprite).raw
                )
            except (ValueError, IndexError):
                unresolved += 1
                continue
            for placement in composition.placements:
                x = obj.x + placement.x + frame.screen_x
                y = obj.y + placement.y + frame.screen_y
                if placement.tile_index is None:
                    unresolved += 1
                    painter = QPainter(image)
                    painter.setPen(QPen(QColor("#ff5fc8"), 1))
                    painter.drawRect(x, y, 7, 7)
                    painter.end()
                    continue
                tile = self._tile(
                    frame.library, placement.tile_index, frame.colors,
                    placement.palette,
                )
                if tile is None:
                    unresolved += 1
                    continue
                if placement.horizontal_flip or placement.vertical_flip:
                    tile = tile.mirrored(
                        placement.horizontal_flip, placement.vertical_flip
                    )
                painter = QPainter(image)
                painter.drawImage(x, y, tile)
                painter.end()
        self._unresolved = unresolved
        return QPixmap.fromImage(image).scaled(
            512, 480, Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.FastTransformation,
        )

    def _show_frame(self, index: int) -> None:
        if not self.frames:
            self.preview_label.setText("当前草稿无法生成安全预览。")
            self.frame_status.setText("没有可播放画面。")
            return
        self.frame_index = min(max(index, 0), len(self.frames) - 1)
        frame = self.frames[self.frame_index]
        self.preview_label.setPixmap(self._render(frame, self.frame_index))
        blocked = self.frame_slider.blockSignals(True)
        self.frame_slider.setValue(self.frame_index)
        self.frame_slider.blockSignals(blocked)
        extra = f" · {self._unresolved} 个动态图块未解析" if self._unresolved else ""
        self.frame_status.setText(
            f"第 {self.frame_index + 1} / {len(self.frames)} 帧 · {frame.action}"
            f" · 物体 {len(frame.objects)} 个 · 图库 {frame.library:02X}{extra}"
        )

    def _advance(self) -> None:
        if self.frames:
            self._show_frame((self.frame_index + 1) % len(self.frames))

    def _step(self, amount: int) -> None:
        self.timer.stop()
        self.play_button.setText("播放")
        if self.frames:
            self._show_frame((self.frame_index + amount) % len(self.frames))

    def _restart(self) -> None:
        self._show_frame(0)
        self.play_button.setText("暂停")
        self.timer.start()

    def _toggle_playback(self) -> None:
        if self.timer.isActive():
            self.timer.stop()
            self.play_button.setText("播放")
        else:
            self.timer.start()
            self.play_button.setText("暂停")

    def _set_speed(self, _index: int | None = None) -> None:
        speed = float(self.speed_combo.currentData() or 1.0)
        self.timer.setInterval(max(8, round(1000 / (60 * speed))))

    def reject(self) -> None:
        self.timer.stop()
        super().reject()


class RuntimeMapAnimationPlaybackDialog(QDialog):
    """Play frames captured from the real game running in Mesen."""

    def __init__(
        self,
        frame_paths: tuple,
        animation_index: int,
        animation_name: str,
        context: str,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.frame_paths = frame_paths
        self.frame_index = 0
        self.setWindowTitle(f"游戏内真实预览：{animation_name}")
        self.resize(690, 650)
        root = QVBoxLayout(self)
        title = QLabel(
            f"[{animation_index:02X}]{animation_index:03d}：{animation_name} · {context}"
        )
        title.setObjectName("sectionTitle")
        root.addWidget(title)
        self.preview_label = QLabel()
        self.preview_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.preview_label.setMinimumSize(512, 480)
        self.preview_label.setStyleSheet(
            "background:#111820; border:1px solid #91a8b2; border-radius:4px;"
        )
        root.addWidget(self.preview_label, 1)
        controls = QHBoxLayout()
        self.restart_button = QPushButton("从头播放")
        self.previous_button = QPushButton("上一帧")
        self.play_button = QPushButton("暂停")
        self.next_button = QPushButton("下一帧")
        for button in (
            self.restart_button, self.previous_button, self.play_button,
            self.next_button,
        ):
            controls.addWidget(button)
        controls.addWidget(QLabel("播放速度"))
        self.speed_combo = QComboBox()
        self.speed_combo.addItem("慢速（0.5 倍）", 0.5)
        self.speed_combo.addItem("正常（1 倍）", 1.0)
        self.speed_combo.addItem("快速（2 倍）", 2.0)
        self.speed_combo.setCurrentIndex(1)
        controls.addWidget(self.speed_combo)
        root.addLayout(controls)
        self.frame_slider = QSlider(Qt.Orientation.Horizontal)
        self.frame_slider.setRange(0, max(0, len(frame_paths) - 1))
        root.addWidget(self.frame_slider)
        self.status = QLabel()
        self.status.setWordWrap(True)
        root.addWidget(self.status)
        note = QLabel(
            "以上画面由 Mesen 运行隔离测试 ROM 后逐帧抓取，使用的是游戏自身的地图动画解释器、"
            "PPU、调色板、背景和运行时数据；预览文件不会覆盖当前 ROM。"
        )
        note.setObjectName("hintText")
        note.setWordWrap(True)
        root.addWidget(note)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        buttons.button(QDialogButtonBox.StandardButton.Close).setText("关闭")
        buttons.rejected.connect(self.reject)
        root.addWidget(buttons)
        self.timer = QTimer(self)
        self.timer.timeout.connect(self._advance)
        self.restart_button.clicked.connect(self._restart)
        self.previous_button.clicked.connect(lambda: self._step(-1))
        self.play_button.clicked.connect(self._toggle)
        self.next_button.clicked.connect(lambda: self._step(1))
        self.speed_combo.currentIndexChanged.connect(self._set_speed)
        self.frame_slider.valueChanged.connect(self._show_frame)
        self._set_speed()
        self._show_frame(0)
        self.timer.start()

    def _show_frame(self, index: int) -> None:
        if not self.frame_paths:
            return
        self.frame_index = min(max(index, 0), len(self.frame_paths) - 1)
        pixmap = QPixmap(str(self.frame_paths[self.frame_index])).scaled(
            512, 480, Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.FastTransformation,
        )
        self.preview_label.setPixmap(pixmap)
        blocked = self.frame_slider.blockSignals(True)
        self.frame_slider.setValue(self.frame_index)
        self.frame_slider.blockSignals(blocked)
        self.status.setText(
            f"真实游戏运行帧 {self.frame_index + 1} / {len(self.frame_paths)}"
        )

    def _advance(self) -> None:
        self._show_frame((self.frame_index + 1) % len(self.frame_paths))

    def _step(self, amount: int) -> None:
        self.timer.stop()
        self.play_button.setText("播放")
        self._show_frame((self.frame_index + amount) % len(self.frame_paths))

    def _restart(self) -> None:
        self._show_frame(0)
        self.play_button.setText("暂停")
        self.timer.start()

    def _toggle(self) -> None:
        if self.timer.isActive():
            self.timer.stop()
            self.play_button.setText("播放")
        else:
            self.timer.start()
            self.play_button.setText("暂停")

    def _set_speed(self, _index: int | None = None) -> None:
        speed = float(self.speed_combo.currentData() or 1.0)
        self.timer.setInterval(max(16, round(1000 / (30 * speed))))

    def reject(self) -> None:
        self.timer.stop()
        super().reject()


class AnimationScriptWidget(QWidget):
    """A draft script editor; the caller owns its enclosing transaction."""
    changed = Signal()
    pointer_requested = Signal(int)
    _command_clipboard: tuple[bytes, ...] = ()

    def __init__(
        self,
        parent: QWidget | None = None,
        *,
        legacy_pointer_dialog: bool = False,
        allow_structure_edit: bool | None = None,
        show_raw_column: bool = True,
        show_structure_buttons: bool = True,
        chr_bank_count: int | None = None,
    ) -> None:
        super().__init__(parent)
        self.legacy_pointer_dialog = legacy_pointer_dialog
        self.allow_structure_edit = (
            not legacy_pointer_dialog
            if allow_structure_edit is None
            else allow_structure_edit
        )
        self.show_raw_column = show_raw_column
        self.show_structure_buttons = show_structure_buttons
        self.chr_bank_count = chr_bank_count
        self.row_height = 18 if legacy_pointer_dialog else 16
        self.codec: AnimationCodec | None = None
        self.record: AnimationRecord | None = None
        self._structural_patch_override = None
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(4)
        self.status = QLabel("请选择动画。")
        self.status.setWordWrap(False)
        header = QHBoxLayout()
        header.setContentsMargins(0, 0, 0, 0)
        header.setSpacing(10)
        header.addWidget(self.status, 1)
        self.pool_status = QWidget()
        pool_layout = QHBoxLayout(self.pool_status)
        pool_layout.setContentsMargins(0, 0, 0, 0)
        self.pool_usage = QProgressBar()
        self.pool_usage.setTextVisible(True)
        self.pool_usage.setMinimumSize(330, 23)
        self.pool_usage.setMaximumWidth(420)
        pool_layout.addWidget(self.pool_usage, 1)
        self.pool_status.hide()
        header.addWidget(self.pool_status, 1)
        root.addLayout(header)
        self.instruction_table = QTableWidget(0, 2 if show_raw_column else 1)
        self.instruction_table.setHorizontalHeaderLabels(
            ("动画内容", "原始字节") if show_raw_column else ("动画内容",)
        )
        self.instruction_table.verticalHeader().hide()
        self.instruction_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        if show_raw_column:
            self.instruction_table.horizontalHeader().setSectionResizeMode(
                1, QHeaderView.ResizeMode.ResizeToContents
            )
        self.instruction_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.instruction_table.setAlternatingRowColors(True)
        self.instruction_table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        compact_font = self.instruction_table.font()
        compact_font.setPointSizeF(max(8.0, compact_font.pointSizeF() - 2.0))
        self.instruction_table.setFont(compact_font)
        self.instruction_table.setStyleSheet(
            "QTableWidget::item { padding: 0px 4px; }"
        )
        self.instruction_table.verticalHeader().setSectionResizeMode(
            QHeaderView.ResizeMode.Fixed
        )
        self.instruction_table.verticalHeader().setDefaultSectionSize(self.row_height)
        self.instruction_table.verticalHeader().setMinimumSectionSize(self.row_height)
        self.instruction_table.currentCellChanged.connect(self._select_instruction)
        if self.allow_structure_edit:
            self.instruction_table.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
            self.instruction_table.customContextMenuRequested.connect(self._show_instruction_context_menu)
        self.instruction_table.cellDoubleClicked.connect(
            lambda row, _column: self.edit_instruction(row)
        )
        self.instruction_table.setToolTip(
            "选择一行后可在下方直接修改参数；“编辑详情”打开完整参数窗，"
            "右键还可插入、复制、粘贴或删除。所有改动先保存在窗口草稿中。"
            if legacy_pointer_dialog
            else "双击或右键可全面编辑单武器动画；支持插入、替换、剪切、复制、粘贴、删除和清空。"
        )
        self.instruction_table.setMinimumHeight(200)
        root.addWidget(self.instruction_table, 1)
        self.structure_bar: QWidget | None = None
        if self.allow_structure_edit and self.show_structure_buttons:
            self.structure_bar = QWidget()
            structure_layout = QHBoxLayout(self.structure_bar)
            structure_layout.setContentsMargins(0, 0, 0, 0)
            actions = [
                ("插入指令", self.insert_instruction),
                ("编辑详情", self.edit_instruction),
                ("删除指令", self.delete_instruction),
            ]
            if not self.legacy_pointer_dialog:
                actions.append(("清空动画", self.clear_instructions))
            for text, slot in actions:
                button = QPushButton(text)
                button.clicked.connect(slot)
                structure_layout.addWidget(button)
            structure_layout.addStretch()
            if self.legacy_pointer_dialog:
                draft_hint = QLabel("选择一行后在下方改参数；窗口“确定”后才写入 ROM")
                draft_hint.setObjectName("hintText")
                structure_layout.addWidget(draft_hint)
            root.addWidget(self.structure_bar)
        self.parameters = QWidget()
        self.parameter_layout = (
            QGridLayout(self.parameters)
            if self.legacy_pointer_dialog
            else QHBoxLayout(self.parameters)
        )
        self.parameter_layout.setContentsMargins(0, 0, 0, 0)
        self.parameter_layout.setSpacing(6)
        root.addWidget(self.parameters)
        self.code_button = QPushButton("代码编辑")
        self.code_button.clicked.connect(self._toggle_code)
        self.code_edit = QPlainTextEdit()
        self.code_edit.setPlaceholderText("完整动画十六进制代码（必须以 FF 结束）")
        self.code_edit.setMaximumHeight(130)
        self.code_edit.textChanged.connect(self._code_changed)
        self.code_edit.hide()
        root.addWidget(self.code_edit)
        self.guidance = QLabel(
            "先在左侧选择接近的动画，也可点“添加”复制后再调整。"
            "双击编辑，右键可插入、复制、粘贴或删除；保存时自动整理空间和循环目标。"
            if legacy_pointer_dialog
            else "武器动画可按指令新增、替换、删除和组合；写入范围不会越过下一条动画。"
            "共享同一指针的武器会同步变化。高级用户也可展开完整代码。"
        )
        self.guidance.setWordWrap(True)
        footer = QHBoxLayout()
        footer.setContentsMargins(0, 0, 0, 0)
        footer.setSpacing(8)
        footer.addWidget(self.code_button, 0, Qt.AlignmentFlag.AlignTop)
        footer.addWidget(self.guidance, 1)
        if self.legacy_pointer_dialog:
            footer.addStretch(1)
        root.addLayout(footer)

    def _editable_ranges(
        self, instruction: AnimationInstruction
    ) -> tuple[tuple[int, int, int], ...]:
        """Expose the verified map-object references as semantic parameters.

        The generic decoder intentionally exposes only F9 coordinates.  In the
        map editor we also know the referenced table sizes, so the object slot,
        sprite rule and both movement-rule references can be changed safely.
        The two interpreter bytes between them remain fixed and are never
        offered as editable values.
        """

        raw = instruction.raw
        if not self.legacy_pointer_dialog or not raw:
            return instruction.editable
        sprite_high = max(0, (self.codec.count("sprite") - 1) if self.codec else 0xF8)
        movement_high = max(0, (self.codec.count("movement") - 1) if self.codec else 0x9C)
        if raw[0] in _OBJECT_RULE_OPCODES and len(raw) == 5:
            return (
                (1, 0, 255), (2, 0, sprite_high),
                (3, 0, movement_high), (4, 0, movement_high),
            )
        if raw[0] == 0xF9 and len(raw) == 4:
            return ((1, 0, 0xFE), (2, 0, 255), (3, 0, 255))
        if raw[0] in (0xE0, 0xE1) and self.chr_bank_count:
            return ((1, 0, max(0, min(255, self.chr_bank_count - 1))),)
        return instruction.editable

    def _semantic_options(
        self, raw: bytes, local: int, current: int
    ) -> tuple[tuple[str, int], ...]:
        if not self.legacy_pointer_dialog or not raw:
            return ()
        opcode = raw[0]
        if opcode in (0xE0, 0xE1) and local == 1 and self.chr_bank_count:
            return tuple(
                (f"[{value:02X}]{value:03d} · ROM ${0x80010 + value * 0x400:05X}", value)
                for value in range(self.chr_bank_count)
            )
        if opcode == 0xF4 and local == 1:
            names = animation_names("音乐.ini", 256)
            return tuple(
                (f"[{value:02X}]{value:03d} · {names[value]}", value)
                for value in range(256)
                if names[value] != "未命名" or value == current
            )
        if opcode == 0xF9 and local == 1:
            return tuple(
                (f"物体编号 {value:02X}", value)
                for value in range(0xFF)
            )
        sprite_local = (
            opcode in _OBJECT_RULE_OPCODES and local == 2
        )
        movement_local = (
            opcode in _OBJECT_RULE_OPCODES and local in (3, 4)
        )
        if sprite_local and self.codec is not None:
            names = animation_names(
                "地图动画图片名称.ini", self.codec.count("sprite")
            )
            return tuple(
                (f"[{value:02X}]{value:03d} · {names[value]}", value)
                for value in range(len(names))
            )
        if movement_local and self.codec is not None:
            names = animation_names(
                "地图动画运行规律名称.ini", self.codec.count("movement"), 1
            )
            return tuple(
                (f"[{value:02X}]{value:03d} · {names[value]}", value)
                for value in range(len(names))
            )
        return ()

    def set_record(self, data: bytes | bytearray, kind: str, index: int) -> None:
        self._structural_patch_override = None
        self.codec = AnimationCodec(data)
        self.record = self.codec.record(kind, index)
        record = self.record
        self._set_code(record.raw)
        self._refresh_instruction_table()
        aliases = ", ".join(f"${i:02X}" for i in record.aliases[:12])
        if len(record.aliases) > 12:
            aliases += f"…共 {len(record.aliases)} 项"
        usage = self.codec.script_pool_usage(record.kind) if record.offset else None
        legacy_actions = sum(
            len(legacy_script_lines(row))
            for row in record.instructions
            if row.raw != b"\xFF"
        )
        self.status.setText(f"当前动画共 {legacy_actions} 项动作"
                            + (f" · 共享：{aliases}" if aliases else " · 独立记录")
                            + ("" if record.complete else " · 包含未验证内容"))
        self.status.setToolTip(
            f"ROM 中实际为 {len(record.instructions)} 条底层指令；"
            "列表严格按旧修改器隐藏刷新指令并拆分创建物体说明。"
        )
        self.pool_status.setVisible(
            record.kind == "map" and usage is not None
            and not (self.legacy_pointer_dialog and not self.show_structure_buttons)
        )
        self._refresh_pool_usage()
        self.code_button.setEnabled(record.complete)
        self.code_edit.setReadOnly(not self.code_button.isEnabled())
        self.instruction_table.setCurrentCell(0, 0)
        self._select_instruction(0, 0, -1, -1)

    def _draft_instructions(self):
        if self.record is None:
            return (), False
        try:
            raw = bytes.fromhex(self.code_edit.toPlainText())
        except ValueError:
            return (), False
        return decode_script(raw, self.record.offset)

    def _weapon_loop_targets(self) -> tuple[tuple[str, int], ...]:
        """Return reference-style FE targets for the current draft.

        The legacy dialog shows a fixed 000--199 instruction-number list.  A
        selectable row resolves to the CPU address of that command in the
        current record; the codec later relocates that proven boundary when it
        repacks the shared animation pool.
        """

        if self.codec is None or self.record is None:
            return ()
        rows, complete = self._draft_instructions()
        if not complete:
            return ()
        pointer = self.codec.pointers[self.record.kind][self.record.index]
        return tuple(
            (
                f"{index:03d}：{(legacy_script_lines(row) or (row.text,))[0]}",
                pointer + row.offset - self.record.offset,
            )
            for index, row in enumerate(rows[:200])
        )

    def _refresh_instruction_table(self) -> None:
        rows, complete = self._draft_instructions()
        display_count = sum(len(legacy_script_lines(row)) for row in rows)
        placeholder_count = max(1, 23 - display_count)
        table_rows = len(rows) + placeholder_count
        blocked = self.instruction_table.blockSignals(True)
        self.instruction_table.setRowCount(table_rows)
        display_index = 0
        for row in range(table_rows):
            self.instruction_table.setRowHidden(row, False)
            self.instruction_table.setRowHeight(row, self.row_height)
            if row < len(rows):
                instruction = rows[row]
                lines = legacy_script_lines(instruction)
                if not lines:
                    self.instruction_table.setRowHidden(row, True)
                    item = QTableWidgetItem("")
                else:
                    item = QTableWidgetItem("\n".join(
                        f"{display_index + index:03d}：{text}"
                        for index, text in enumerate(lines)
                    ))
                    if len(lines) > 1:
                        self.instruction_table.setRowHeight(
                            row, self.row_height * len(lines)
                        )
                    display_index += len(lines)
                item.setToolTip(f"文件地址 ${instruction.offset:06X}")
                raw_item = QTableWidgetItem(instruction.raw.hex(" ").upper())
            else:
                item = QTableWidgetItem(f"{display_index:03d}：空代码")
                item.setToolTip("右键可在动画结束前新增一条指令。")
                raw_item = QTableWidgetItem("")
                item.setForeground(QColor("#777777"))
                display_index += 1
            self.instruction_table.setItem(row, 0, item)
            if self.show_raw_column:
                self.instruction_table.setItem(row, 1, raw_item)
        self.instruction_table.blockSignals(blocked)
        if not complete and self.record is not None:
            self.status.setText("当前草稿不是完整动画；请修正代码或撤销本次编辑。")

    def _set_code(self, data: bytes) -> None:
        blocked = self.code_edit.blockSignals(True)
        self.code_edit.setPlainText(data.hex(" ").upper())
        self.code_edit.blockSignals(blocked)

    def _toggle_code(self) -> None:
        if self.legacy_pointer_dialog:
            pointer = 0x8000
            if self.codec is not None and self.record is not None:
                pointer = self.codec.pointers[self.record.kind][self.record.index]
            dialog = AnimationPointerDialog(self, pointer=pointer)
            if dialog.exec() == QDialog.DialogCode.Accepted:
                try:
                    selected = dialog.pointer()
                except ValueError as error:
                    self.status.setText(str(error))
                else:
                    self.pointer_requested.emit(selected)
            return
        self._toggle_raw_code()

    def _toggle_raw_code(self) -> None:
        self.code_edit.setVisible(not self.code_edit.isVisible())
        if self.code_edit.isVisible():
            self.code_edit.setFocus()

    def _show_instruction_context_menu(self, position) -> None:
        row = self.instruction_table.rowAt(position.y())
        if row >= 0:
            self.instruction_table.setCurrentCell(row, 0)
        else:
            row = self.instruction_table.currentRow()
        menu = QMenu(self.instruction_table)
        rows, complete = self._draft_instructions()
        actual = 0 <= row < len(rows)
        is_end = actual and rows[row].raw == b"\xFF"
        insert_action = menu.addAction("插入")
        insert_action.setEnabled(complete and self.allow_structure_edit)
        insert_action.triggered.connect(lambda: self.insert_instruction(row))
        edit_action = menu.addAction("编辑")
        edit_action.setEnabled(actual and not is_end and self.allow_structure_edit)
        edit_action.triggered.connect(lambda: self.edit_instruction(row))
        cut_action = menu.addAction("剪切")
        cut_action.setEnabled(actual and not is_end and self.allow_structure_edit)
        cut_action.triggered.connect(lambda: self.cut_instruction(row))
        copy_action = menu.addAction("复制")
        copy_action.setEnabled(actual and not is_end)
        copy_action.triggered.connect(lambda: self.copy_instruction(row))
        copy_all_action = menu.addAction("复制全部")
        copy_all_action.setEnabled(bool(rows))
        copy_all_action.triggered.connect(self.copy_all_instructions)
        paste_action = menu.addAction("粘贴")
        paste_action.setEnabled(bool(self._command_clipboard) and self.allow_structure_edit)
        paste_action.triggered.connect(lambda: self.paste_instructions(row, False))
        paste_all_action = menu.addAction("粘贴全部")
        paste_all_action.setEnabled(bool(self._command_clipboard) and self.allow_structure_edit)
        paste_all_action.triggered.connect(lambda: self.paste_instructions(row, True))
        delete_action = menu.addAction("删除")
        delete_action.setEnabled(actual and not is_end and self.allow_structure_edit)
        delete_action.triggered.connect(lambda: self.delete_instruction(row))
        clear_action = menu.addAction("清空")
        clear_action.setEnabled(complete and self.allow_structure_edit)
        clear_action.triggered.connect(self.clear_instructions)
        menu.addSeparator()
        action = menu.addAction(
            "隐藏完整代码编辑区" if self.code_edit.isVisible() else "显示完整代码编辑区"
        )
        action.triggered.connect(self._toggle_raw_code)
        menu.popup(self.instruction_table.viewport().mapToGlobal(position))

    def edit_instruction(self, row: int | None = None) -> None:
        if self.record is None or not self.allow_structure_edit:
            return
        if row is None or isinstance(row, bool):
            row = self.instruction_table.currentRow()
        rows, complete = self._draft_instructions()
        if not complete or not 0 <= row < len(rows) or rows[row].raw == b"\xFF":
            return
        dialog = WeaponAnimationCommandDialog(
            self,
            raw=rows[row].raw,
            allow_type_change=False,
            loop_targets=self._weapon_loop_targets(),
        )
        if dialog.exec() == QDialog.DialogCode.Accepted:
            commands = [instruction.raw for instruction in rows]
            commands[row] = dialog.command()
            self._replace_commands(commands, row)
        dialog.deleteLater()

    def insert_instruction(self, row: int | None = None) -> None:
        if self.record is None or not self.allow_structure_edit:
            return
        rows, complete = self._draft_instructions()
        if not complete:
            return
        commands = [instruction.raw for instruction in rows]
        end = max(0, len(commands) - 1)
        target = self.instruction_table.currentRow() if row is None or isinstance(row, bool) else row
        target = min(max(0, target), end)
        palette = WeaponAnimationCommandPaletteDialog(self)
        if palette.exec() != QDialog.DialogCode.Accepted:
            palette.deleteLater()
            return
        preset = palette.preset()
        palette.deleteLater()
        if preset == b"\xFF":
            # The reference chooser treats FF as an immediate action: it
            # closes without a parameter dialog and makes the selected row the
            # new end of the animation.  Its save path also performs the old
            # editor's copy-on-write allocation so aliases keep the original.
            try:
                patch = self.codec.script_insert_end_patch(self.record, target)
            except ValueError as error:
                self.status.setText(f"未修改：{error}")
                return
            replacement = b"".join(commands[:target]) + b"\xFF"
            self._set_code(replacement)
            self._structural_patch_override = patch
            self._refresh_instruction_table()
            self._refresh_pool_usage()
            self.instruction_table.setCurrentCell(max(0, target - 1), 0)
            self.changed.emit()
            return
        loop_targets = self._weapon_loop_targets()
        if preset[:1] == b"\xFE" and loop_targets:
            preset = preset[:2] + loop_targets[0][1].to_bytes(2, "little")
        dialog = WeaponAnimationCommandDialog(
            self,
            raw=preset,
            allow_type_change=False,
            operation="insert",
            loop_targets=loop_targets,
        )
        if dialog.exec() == QDialog.DialogCode.Accepted:
            command = dialog.command()
            commands.insert(target, command)
            self._replace_commands(commands, target)
        dialog.deleteLater()

    def _apply_instruction_values(self, row: int, values: tuple[int, ...]) -> None:
        """Keep the compact parameter controls in sync with structural edits."""

        rows, complete = self._draft_instructions()
        if not complete or not 0 <= row < len(rows):
            raise ValueError("当前动画草稿不是完整指令序列。")
        instruction = rows[row]
        if len(values) != len(instruction.editable):
            raise ValueError("动画指令参数数量不匹配。")
        command = bytearray(instruction.raw)
        for value, (local, low, high) in zip(values, instruction.editable):
            if not low <= value <= high:
                raise ValueError(f"动画参数必须在 ${low:02X}—${high:02X} 范围内。")
            command[local] = value
        commands = [current.raw for current in rows]
        commands[row] = bytes(command)
        if not self._replace_commands(commands, row):
            raise ValueError(self.status.text())

    def _replace_commands(self, commands: list[bytes] | tuple[bytes, ...], selected: int = 0) -> bool:
        if self.record is None or self.codec is None:
            return False
        self._structural_patch_override = None
        normalized = [bytes(command) for command in commands if command != b"\xFF"] + [b"\xFF"]
        replacement = b"".join(normalized)
        try:
            self.codec.script_sequence_patch(self.record, replacement)
        except ValueError as error:
            self.status.setText(f"未修改：{error}")
            return False
        self._set_code(replacement)
        self._code_changed()
        self.instruction_table.setCurrentCell(min(selected, len(normalized) - 1), 0)
        return True

    def copy_instruction(self, row: int | None = None) -> None:
        rows, complete = self._draft_instructions()
        if row is None:
            row = self.instruction_table.currentRow()
        if complete and 0 <= row < len(rows) and rows[row].raw != b"\xFF":
            type(self)._command_clipboard = (rows[row].raw,)
            self.status.setText("已复制 1 条武器动画指令。")

    def copy_all_instructions(self) -> None:
        rows, complete = self._draft_instructions()
        if complete:
            type(self)._command_clipboard = tuple(
                instruction.raw for instruction in rows if instruction.raw != b"\xFF"
            )
            self.status.setText(f"已复制 {len(self._command_clipboard)} 条武器动画指令。")

    def cut_instruction(self, row: int | None = None) -> None:
        if row is None:
            row = self.instruction_table.currentRow()
        self.copy_instruction(row)
        self.delete_instruction(row)

    def paste_instructions(self, row: int | None = None, replace_all: bool = False) -> None:
        if not self._command_clipboard:
            return
        rows, complete = self._draft_instructions()
        if not complete:
            return
        if replace_all:
            self._replace_commands(list(self._command_clipboard), 0)
            return
        commands = [instruction.raw for instruction in rows]
        end = max(0, len(commands) - 1)
        target = self.instruction_table.currentRow() if row is None else row
        target = min(max(0, target), end)
        # The reference editor's ordinary “粘贴” replaces commands beginning
        # at the selected row; it is not an insertion operation.  The
        # dedicated “粘贴全部” path above replaces the complete animation.
        replace_end = min(end, target + len(self._command_clipboard))
        # Some physical commands (notably F1 after an F0 colour command) are
        # deliberately hidden by the old editor and belong to the preceding
        # visible row.  Replacing that visible row consumes its hidden suffix
        # as well; otherwise the new editor leaves an orphan refresh command.
        while (
            replace_end < end
            and not legacy_script_lines(rows[replace_end])
        ):
            replace_end += 1
        commands[target:replace_end] = self._command_clipboard
        self._replace_commands(commands, target)

    def delete_instruction(self, row: int | None = None) -> None:
        rows, complete = self._draft_instructions()
        if row is None or isinstance(row, bool):
            row = self.instruction_table.currentRow()
        if not complete or not 0 <= row < len(rows) or rows[row].raw == b"\xFF":
            return
        commands = [instruction.raw for instruction in rows]
        del commands[row]
        self._replace_commands(commands, max(0, row - 1))

    def clear_instructions(self, *_args) -> None:
        if self.record is not None and self.allow_structure_edit:
            self._replace_commands([b"\xFF"], 0)

    def _code_changed(self) -> None:
        self._structural_patch_override = None
        if self.record is not None:
            self._refresh_instruction_table()
            self._refresh_pool_usage()
        self.changed.emit()

    def _refresh_pool_usage(self) -> None:
        """Show projected map-pool usage for the current unsaved draft."""

        if self.codec is None or self.record is None or self.record.kind != "map":
            return
        try:
            usage = self.codec.script_pool_usage("map")
            replacement = bytes.fromhex(self.code_edit.toPlainText())
            rows, complete = decode_script(replacement, self.record.offset)
            if not complete or sum(len(row.raw) for row in rows) != len(replacement):
                raise ValueError
        except ValueError:
            self.pool_usage.setRange(0, 1)
            self.pool_usage.setValue(0)
            self.pool_usage.setFormat("当前草稿无法计算")
            self.pool_usage.setStyleSheet("QProgressBar::chunk { background: #c94f4f; }")
            return
        projected_used = usage.used - len(self.record.raw) + len(replacement)
        projected_free = usage.capacity - projected_used
        self.pool_usage.setRange(0, usage.capacity)
        self.pool_usage.setValue(min(max(projected_used, 0), usage.capacity))
        self.pool_usage.setFormat(
            f"内存：已用 {projected_used} / {usage.capacity} 字节｜剩余 {projected_free} 字节"
        )
        ratio = projected_used / usage.capacity if usage.capacity else 1.0
        color = "#c94f4f" if projected_free < 0 or ratio >= 0.95 else (
            "#d69a2d" if ratio >= 0.80 else "#4f8f9d"
        )
        self.pool_usage.setStyleSheet(f"QProgressBar::chunk {{ background: {color}; }}")

    def has_pending_changes(self) -> bool:
        if self.record is None:
            return False
        if self._structural_patch_override is not None:
            return True
        try:
            return bytes.fromhex(self.code_edit.toPlainText()) != self.record.raw
        except ValueError:
            return True

    def pending_patch(self):
        if self.record is None or self.codec is None:
            return None
        if self._structural_patch_override is not None:
            return self._structural_patch_override
        try:
            replacement = bytes.fromhex(self.code_edit.toPlainText())
        except ValueError as error:
            raise ValueError("动画代码须为完整的两位十六进制字节。") from error
        if self.allow_structure_edit:
            if self.record.kind in ("ally", "enemy"):
                return self.codec.legacy_weapon_sequence_patch(
                    self.record, replacement
                )
            return self.codec.script_sequence_patch(self.record, replacement)
        return self.codec.script_patch(self.record, replacement)

    def _select_instruction(self, row: int, *_args) -> None:
        while self.parameter_layout.count():
            item = self.parameter_layout.takeAt(0)
            if item.widget() is not None:
                item.widget().deleteLater()
        rows, complete = self._draft_instructions()
        if self.record is None or not complete or not 0 <= row < len(rows):
            return
        instruction = rows[row]
        editable = self._editable_ranges(instruction)
        if not editable:
            message = QLabel("这个动作没有可直接调整的参数。")
            if self.legacy_pointer_dialog:
                self.parameter_layout.addWidget(message, 0, 0, 1, 6)
            else:
                self.parameter_layout.addWidget(message)
        elif self.legacy_pointer_dialog:
            title = QLabel("当前指令参数")
            title.setObjectName("sectionLabel")
            title.setToolTip("下列控件修改后立即写入本窗口草稿；点击窗口“确定”才写入 ROM。")
            self.parameter_layout.addWidget(title, 0, 0)
        if (
            self.legacy_pointer_dialog and instruction.raw[:1] == b"\xF9"
            and len(instruction.raw) >= 7
        ):
            coordinate_count = 2 - bool(instruction.raw[1] & 0x80) - bool(instruction.raw[1] & 0x40)
            base = 2 + coordinate_count
            fixed = QLabel(
                f"调用方式 {instruction.raw[base]:02X} {instruction.raw[base + 1]:02X}（固定）"
            )
            fixed.setObjectName("hintText")
            fixed.setToolTip("这是地图动画解释器的固定调用码，保持只读以防脚本损坏。")
            self.parameter_layout.addWidget(fixed, 0, 1, 1, 5)
        for field_index, (local, low, high) in enumerate(editable):
            byte_index = instruction.offset - self.record.offset + local
            field_label = QLabel(_command_parameter_name(instruction.raw, local))
            try:
                draft = bytes.fromhex(self.code_edit.toPlainText())
                value = draft[byte_index]
            except (ValueError, IndexError):
                value = instruction.raw[local]
            options = self._semantic_options(instruction.raw, local, value)
            if options:
                combo = QComboBox()
                combo.setObjectName(f"animationParameter{local}")
                combo.setMinimumContentsLength(12)
                combo.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
                for label, option_value in options:
                    combo.addItem(label, option_value)
                selected = combo.findData(value)
                if selected < 0 and instruction.raw[0] == 0xF9 and local == 1:
                    selected = combo.findData((value & 0xF0) | (value & 0x0F))
                combo.setCurrentIndex(max(0, selected))
                combo.setToolTip(
                    "选择后立即更新本窗口草稿；只有点击窗口“确定”才会写入 ROM。"
                )
                combo.currentIndexChanged.connect(
                    lambda _index, box=combo, index=byte_index: self._edit_byte(
                        index, int(box.currentData())
                    )
                )
                if self.legacy_pointer_dialog:
                    grid_row, pair = 1 + field_index // 3, field_index % 3
                    self.parameter_layout.addWidget(field_label, grid_row, pair * 2)
                    self.parameter_layout.addWidget(combo, grid_row, pair * 2 + 1)
                    self.parameter_layout.setColumnStretch(pair * 2 + 1, 1)
                else:
                    self.parameter_layout.addWidget(field_label)
                    self.parameter_layout.addWidget(combo, 1)
                continue
            spin = HexByteSpinBox() if _parameter_uses_hex(instruction.raw, local) else QSpinBox()
            spin.setObjectName(f"animationParameter{local}")
            signed = bool(
                (instruction.raw[0] == 0xFD and local in (1, 2))
                or (instruction.raw[0] == 0xF7 and local == 2)
            )
            if signed:
                spin.setRange(-128, 127)
                spin.setValue(int.from_bytes(bytes((value,)), signed=True))
                spin.setSuffix(" 格")
            else:
                spin.setRange(low, high)
                spin.setValue(value)
                if instruction.raw[0] < 0xE0 and instruction.raw[0] not in _OBJECT_RULE_OPCODES:
                    spin.setSuffix(" 帧")
            shown_value = f"{spin.value():02X}" if _parameter_uses_hex(instruction.raw, local) else str(spin.value())
            spin.setToolTip(
                f"当前值 {shown_value}；修改后会立即更新草稿和内存占用。"
            )
            spin.valueChanged.connect(
                lambda value, index=byte_index, is_signed=signed: self._edit_byte(
                    index, value & 0xFF if is_signed else value
                )
            )
            if self.legacy_pointer_dialog:
                grid_row, pair = 1 + field_index // 3, field_index % 3
                self.parameter_layout.addWidget(field_label, grid_row, pair * 2)
                self.parameter_layout.addWidget(spin, grid_row, pair * 2 + 1)
                self.parameter_layout.setColumnStretch(pair * 2 + 1, 1)
            else:
                self.parameter_layout.addWidget(field_label)
                self.parameter_layout.addWidget(spin)
        if not self.legacy_pointer_dialog:
            self.parameter_layout.addStretch()

    def _edit_byte(self, index: int, value: int) -> None:
        if self.record is None:
            return
        try:
            replacement = bytearray(bytes.fromhex(self.code_edit.toPlainText()))
            if not 0 <= index < len(replacement):
                raise ValueError("当前参数位置已不在动画草稿内。")
            replacement[index] = value
            if self.codec is not None and self.allow_structure_edit:
                self.codec.script_sequence_patch(self.record, bytes(replacement))
            self._set_code(replacement)
            self._code_changed()
        except ValueError as error:
            self.status.setText(str(error))


class WeaponAnimationWidget(QTabWidget):
    changed = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.project = None
        self.weapon_id: int | None = None
        self.editors = (AnimationScriptWidget(), AnimationScriptWidget())
        for title, editor in zip(("我方武器动画", "敌方武器动画"), self.editors):
            self.addTab(editor, title)
            editor.changed.connect(self.changed)
        self.setMinimumHeight(350)

    def set_record(self, project, weapon_id: int | None) -> None:
        self.project, self.weapon_id = project, weapon_id
        if project is None or weapon_id is None:
            self.setEnabled(False)
            return
        self.setEnabled(True)
        for kind, editor in zip(("ally", "enemy"), self.editors):
            editor.set_record(project.working, kind, weapon_id)

    def has_pending_changes(self) -> bool:
        return any(editor.has_pending_changes() for editor in self.editors)

    def pending_patches(self):
        return tuple(editor.pending_patch() for editor in self.editors if editor.has_pending_changes())

    def apply_pending(self) -> None:
        if self.project is not None:
            apply_animation_patches(self.project, self.pending_patches(), "武器双方动画参数")
            self.set_record(self.project, self.weapon_id)

    def discard_pending(self) -> None:
        self.set_record(self.project, self.weapon_id)


class MapAnimationEditorDialog(QDialog):
    def sizeHint(self) -> QSize:  # noqa: N802
        """Keep first-show geometry compact instead of filling screen height."""

        return QSize(900, 650)

    def __init__(self, parent: QWidget | None = None, project=None) -> None:
        super().__init__(parent)
        self.project = project
        self.setWindowTitle("地图动画")
        self.resize(900, 650)
        self.setMinimumSize(800, 540)
        self._selected = -1
        self._movement_index = -1
        self._background_index = -1
        self._sprite_index = -1
        self._loading = False
        self._pending_credits: tuple[str, str] | None = None
        self._initial_geometry_pending = True
        self.base = bytes(project.working) if project is not None else b""
        self.draft = bytearray(self.base)
        root = QVBoxLayout(self)
        root.setContentsMargins(10, 10, 10, 8)
        root.setSpacing(7)
        self.read_only_status = QLabel()
        self.read_only_status.setWordWrap(False)
        self.read_only_status.setObjectName("infoPanel")
        self.read_only_status.setMaximumHeight(36)
        self.tabs = QTabWidget()
        root.addWidget(self.tabs, 1)
        root.addWidget(self.read_only_status)
        buttons = QHBoxLayout()
        buttons.addStretch()
        self.accept_button = QPushButton("确定")
        self.accept_button.clicked.connect(self.accept)
        self.cancel_button = QPushButton("取消")
        self.cancel_button.clicked.connect(self.reject)
        buttons.addWidget(self.accept_button)
        buttons.addWidget(self.cancel_button)
        root.addLayout(buttons)
        try:
            self.codec = AnimationCodec(self.draft)
        except ValueError as error:
            self.read_only_status.setText(str(error))
            self.accept_button.setEnabled(False)
            return
        map_defaults = list(
            animation_names("地图动画名称.ini", self.codec.count("map"), 1)
        )
        if map_defaults:
            map_defaults[0] = "开始界面标题组合动画"
        map_defaults = tuple(map_defaults)
        self.default_names: dict[str, tuple[str, ...]] = {"map": map_defaults}
        self.name_overrides = dict(
            getattr(project, "animation_label_overrides", {})
        )
        self.names = list(map_defaults)
        for index in range(len(self.names)):
            self.names[index] = self.name_overrides.get(("map", index), self.names[index])
        self.tabs.addTab(self._animation_tab(), "地图动画")
        self.tabs.addTab(self._rules_tab(), "规律")
        calls_placeholder = QLabel("首次切换到本页时读取动画调用…")
        calls_placeholder.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.tabs.addTab(calls_placeholder, "动画调用")
        self._calls_placeholder = calls_placeholder
        self.tabs.currentChanged.connect(self._ensure_editor_tab)
        self.read_only_status.setText(
            "已载入当前 ROM。修改保留在本窗口草稿；"
            "确定统一写入，取消放弃。"
        )
        self.read_only_status.setToolTip(
            "已载入当前 ROM 的动画、背景规律、运行规律、"
            "组图及调用。修改确定后一次写入。"
        )
        self.animation_list.setCurrentRow(1)

    def showEvent(self, event) -> None:  # noqa: N802
        super().showEvent(event)
        if self._initial_geometry_pending:
            self._initial_geometry_pending = False
            # Windows applies the layout's height-for-width result after the
            # constructor.  Resize on the next event-loop tick so the dialog
            # opens at the intended compact height instead of screen height.
            QTimer.singleShot(0, lambda: self.resize(900, 650))

    def _ensure_editor_tab(self, index: int) -> None:
        if index != 2 or hasattr(self, "_call_table"):
            return
        selected_index = self.tabs.currentIndex()
        page = self._calls_tab()
        previous = self.tabs.blockSignals(True)
        old = self.tabs.widget(index)
        self.tabs.removeTab(index)
        self.tabs.insertTab(index, page, "动画调用")
        self.tabs.setCurrentIndex(
            index if selected_index == index else selected_index
        )
        self.tabs.blockSignals(previous)
        old.deleteLater()

    @property
    def call_table(self) -> QTableWidget:
        if not hasattr(self, "_call_table"):
            self._ensure_editor_tab(2)
        return self._call_table

    @call_table.setter
    def call_table(self, value: QTableWidget) -> None:
        self._call_table = value

    @property
    def call_combos(self) -> dict[int, QComboBox]:
        if not hasattr(self, "_call_combos"):
            self._ensure_editor_tab(2)
        return self._call_combos

    @call_combos.setter
    def call_combos(self, value: dict[int, QComboBox]) -> None:
        self._call_combos = value

    def _animation_tab(self) -> QWidget:
        page = QWidget()
        layout = QHBoxLayout(page)
        layout.setContentsMargins(8, 7, 8, 8)
        layout.setSpacing(8)
        self.animation_selection_group = QGroupBox("动画选择")
        left = QVBoxLayout(self.animation_selection_group)
        left.setSpacing(6)
        self.animation_list = QListWidget()
        self.animation_list.addItems(f"[{i:02X}]{i:03d}：{name}" for i, name in enumerate(self.names))
        self.animation_list.currentRowChanged.connect(self._select_animation)
        left.addWidget(self.animation_list, 1)
        self.add_button = QPushButton("添加")
        self.add_button.setToolTip(
            "复制当前动画到下一个预留槽；内部循环指针会同步重定位。"
        )
        self.add_button.clicked.connect(self._add_animation)
        left.addWidget(self.add_button)
        left.addWidget(QLabel("动画名称（配置标签）"))
        self.animation_name = QLineEdit()
        self.animation_name.setMaxLength(80)
        self.animation_name.textEdited.connect(self._change_animation_name)
        left.addWidget(self.animation_name)
        self.preview_button = QPushButton("游戏内真实预览")
        self.preview_button.setToolTip(
            "把当前草稿写入隔离测试 ROM，由 Mesen 中的游戏引擎实际播放并逐帧抓取；"
            "不会覆盖当前 ROM。"
        )
        self.preview_button.clicked.connect(self._preview_animation_runtime)
        left.addWidget(self.preview_button)
        self.offline_preview_button = QPushButton("快速结构预览（非实机）")
        self.offline_preview_button.setToolTip(
            "仅用于快速检查组图、配色与等待结构；最终效果请以游戏内真实预览为准。"
        )
        self.offline_preview_button.clicked.connect(self._preview_animation_offline)
        left.addWidget(self.offline_preview_button)
        self.credits_button = QPushButton("字幕内容（制作信息与出演名单）")
        self.credits_button.setToolTip(
            "编辑这组开场动画绘制的 Bank $3D 字幕；与动画草稿一起确定或取消。"
        )
        self.credits_button.clicked.connect(self._edit_opening_credits)
        self.credits_button.setVisible(False)
        left.addWidget(self.credits_button)
        self.animation_selection_group.setMinimumWidth(225)
        self.animation_selection_group.setMaximumWidth(260)
        layout.addWidget(self.animation_selection_group, 2)
        self.animation_editor_group = QGroupBox("动画编辑")
        editor_layout = QVBoxLayout(self.animation_editor_group)
        editor_layout.setContentsMargins(8, 12, 8, 8)
        editor_layout.setSpacing(0)
        self.script_editor = AnimationScriptWidget(
            legacy_pointer_dialog=True,
            allow_structure_edit=True,
            show_raw_column=False,
            show_structure_buttons=False,
            chr_bank_count=max(0, self.project.chr_tile_count // 64 - 3),
        )
        # The map-animation page follows the reference editor's presentation:
        # a readable instruction list with a single code-edit entry.  Rich
        # command editors remain available by double-click and context menu.
        self.script_editor.parameters.hide()
        self.script_editor.status.hide()
        self.script_editor.pool_status.hide()
        self.script_editor.instruction_table.horizontalHeader().hide()
        self.script_editor.code_button.setMaximumWidth(120)
        self.script_editor.pointer_requested.connect(self._jump_to_animation_pointer)
        self.script_editor.guidance.setToolTip(self.script_editor.guidance.text())
        self.script_editor.guidance.hide()
        self.instruction_table = self.script_editor.instruction_table
        self.code_button = self.script_editor.code_button
        editor_layout.addWidget(self.script_editor)
        layout.addWidget(self.animation_editor_group, 5)
        return page

    def _preview_animation_offline(self) -> None:
        row = self.animation_list.currentRow()
        if row < 0 or not self._flush_script():
            return
        try:
            preview_data = self._preview_data()
            dialog = MapAnimationPreviewDialog(
                self.project, preview_data, row, self.names[row], self
            )
        except ValueError as error:
            self.read_only_status.setText(f"无法预览动画：{error}")
            return
        dialog.exec()
        dialog.deleteLater()

    def _preview_data(self) -> bytes:
        """Materialize every staged map-animation edit for either preview path."""

        if self._pending_credits is None:
            return bytes(self.draft)
        preview_project = deepcopy(self.project)
        preview_project.working[:] = self.draft
        preview_project._refresh_dynamic_codecs()
        preview_project.set_production_credits(*self._pending_credits)
        return bytes(preview_project.working)

    def _edit_opening_credits(self) -> None:
        row = self.animation_list.currentRow()
        if row not in (0x13, 0x14) or self.project is None:
            return
        if not self.project.supports_production_credits:
            self.read_only_status.setText("当前 ROM 没有已验证的开场字幕文字块。")
            return
        from .production_credits_editor import ProductionCreditsDialog

        try:
            dialog = ProductionCreditsDialog(
                parent=self,
                project=self.project,
                staged_texts=self._pending_credits,
                defer_apply=True,
            )
        except ValueError as error:
            self.read_only_status.setText(f"无法打开字幕内容：{error}")
            return
        if (
            dialog.exec() == QDialog.DialogCode.Accepted
            and dialog.edited_texts is not None
        ):
            self._pending_credits = dialog.edited_texts
            self.read_only_status.setText(
                "制作信息与出演名单已暂存到地图动画窗口；"
                "点本窗口“确定”统一写入，点“取消”统一放弃。"
            )
        dialog.deleteLater()

    def _preview_animation_runtime(self) -> None:
        row = self.animation_list.currentRow()
        if row < 0 or not self._flush_script():
            return
        emulator = ROOT / "tools" / "vendor" / "mesen-0.9.9" / "Mesen.exe"
        source_save = (
            ROOT / "references" / "emulator-state" / "fceux" / "sav"
            / "DC_kuorong.sav"
        )
        battle_script = (
            ROOT / "tests" / "emulator" / "helpers"
            / "dc_map_animation_runtime_preview.lua"
        )
        title_script = (
            ROOT / "tests" / "emulator" / "helpers"
            / "dc_title_animation_runtime_preview.lua"
        )
        try:
            if not emulator.is_file():
                raise FileNotFoundError(f"找不到随附模拟器：{emulator}")
            artifacts = prepare_map_animation_runtime_preview(
                self._preview_data(),
                row,
                source_save,
                ROOT / "output" / "verification" / "map-animation-runtime-preview",
                emulator.parent,
                battle_script,
                title_script,
            )
            progress = QProgressDialog(
                "正在由 Mesen 运行游戏并抓取真实动画画面……",
                "取消",
                0,
                0,
                self,
            )
            progress.setWindowTitle("生成游戏内真实预览")
            progress.setWindowModality(Qt.WindowModality.WindowModal)
            progress.setMinimumDuration(0)
            process = QProcess(progress)
            process.setWorkingDirectory(str(emulator.parent))
            process.finished.connect(lambda *_args: progress.accept())
            progress.canceled.connect(process.kill)
            process.start(
                str(emulator),
                [
                    "--testrunner",
                    str(artifacts.script_path),
                    str(artifacts.rom_path),
                    "--timeout=60",
                ],
            )
            if not process.waitForStarted(5000):
                raise RuntimeError("Mesen 真实预览进程启动失败。")
            progress.exec()
            if process.state() != QProcess.ProcessState.NotRunning:
                process.kill()
                process.waitForFinished(3000)
                raise RuntimeError("已取消游戏内真实预览。")
            if process.exitStatus() != QProcess.ExitStatus.NormalExit or process.exitCode() != 0:
                error = bytes(process.readAllStandardError()).decode("utf-8", errors="replace")
                raise RuntimeError(
                    "Mesen 未能完成真实动画抓取。" + (f"\n{error}" if error else "")
                )
            frames = runtime_preview_frames(artifacts.frame_directory)
            if not frames:
                raise RuntimeError("Mesen 已结束，但没有生成动画画面。")
            dialog = RuntimeMapAnimationPlaybackDialog(
                frames,
                row,
                self.names[row],
                artifacts.context,
                self,
            )
            dialog.exec()
            dialog.deleteLater()
            self.read_only_status.setText(
                f"已使用游戏引擎完成动画 ${row:02X} 的真实预览；"
                "当前 ROM 和窗口草稿均未被预览流程改写。"
            )
        except Exception as error:
            self.read_only_status.setText(f"游戏内真实预览失败：{error}")

    def _jump_to_animation_pointer(self, pointer: int) -> None:
        matches = [
            index
            for index, value in enumerate(self.codec.pointers["map"])
            if value == pointer
        ]
        if not matches:
            self.script_editor.status.setText(
                f"指针 ${pointer:04X} 不属于当前地图动画表；未修改 ROM。"
            )
            return
        target = matches[0]
        self.animation_list.setCurrentRow(target)
        if self.animation_list.currentRow() != target:
            return
        self.script_editor.code_edit.show()
        aliases = "、".join(f"${index:02X}" for index in matches)
        self.script_editor.status.setText(
            f"已定位指针 ${pointer:04X}（动画 {aliases}）；"
            "结构代码区已展开；可增删完整指令，地址与循环目标会安全重定位。"
        )
        self.script_editor.code_edit.setFocus()

    def _flush_script(self) -> bool:
        try:
            if self.script_editor.has_pending_changes():
                offset, before, after = self.script_editor.pending_patch()
                if self.draft[offset:offset + len(before)] != before:
                    raise ValueError("当前草稿已变化，请重新选择动画。")
                self.draft[offset:offset + len(after)] = after
            return True
        except ValueError as error:
            self.read_only_status.setText(f"动画草稿未保存：{error}")
            return False

    def _select_animation(self, row: int) -> None:
        if row < 0:
            return
        if self._selected >= 0 and not self._flush_script():
            blocked = self.animation_list.blockSignals(True)
            self.animation_list.setCurrentRow(self._selected)
            self.animation_list.blockSignals(blocked)
            return
        self._selected = row
        self.animation_name.setText(self.names[row])
        self.script_editor.set_record(self.draft, "map", row)
        self.credits_button.setVisible(row in (0x13, 0x14))
        self.credits_button.setEnabled(
            bool(
                self.project is not None
                and self.project.supports_production_credits
            )
        )

    def _change_animation_name(self, text: str) -> None:
        row = self.animation_list.currentRow()
        if row < 0:
            return
        self.names[row] = text
        if text == self.default_names["map"][row]:
            self.name_overrides.pop(("map", row), None)
        else:
            self.name_overrides[("map", row)] = text
        self.animation_list.item(row).setText(f"[{row:02X}]{row:03d}：{text}")
        if hasattr(self, "_call_combos"):
            for combo in self._call_combos.values():
                combo.setItemText(row, f"[{row:02X}]{row:03d}：{text}")

    def _add_animation(self) -> None:
        source_index = self.animation_list.currentRow()
        if source_index < 0 or not self._flush_script():
            return
        try:
            codec = AnimationCodec(self.draft)
            new_index, patches = codec.clone_map_animation_patches(source_index)
            for offset, before, after in patches:
                if bytes(self.draft[offset:offset + len(before)]) != before:
                    raise ValueError("动画草稿已变化，请重新打开窗口。")
                self.draft[offset:offset + len(after)] = after
            base_name = self.names[source_index]
            new_name = f"{base_name} 副本"
            if len(new_name) > 80:
                new_name = f"动画 {new_index:03d} 副本"
            self.names[new_index] = new_name
            self.name_overrides[("map", new_index)] = new_name
            self.animation_list.item(new_index).setText(
                f"[{new_index:02X}]{new_index:03d}：{new_name}"
            )
            if hasattr(self, "_call_combos"):
                for combo in self._call_combos.values():
                    combo.setItemText(
                        new_index,
                        f"[{new_index:02X}]{new_index:03d}：{new_name}",
                    )
            self.animation_list.setCurrentRow(new_index)
            self.read_only_status.setText(
                f"已把动画 ${source_index:02X} 复制到预留槽 ${new_index:02X}；"
                "点击确定后写入工程。"
            )
        except ValueError as error:
            self.read_only_status.setText(f"未添加动画：{error}")

    def _rules_tab(self) -> QWidget:
        page = QWidget()
        layout = QHBoxLayout(page)
        layout.setSpacing(10)
        self.rule_groups: dict[str, QGroupBox] = {}
        self.rule_lists: dict[str, QListWidget] = {}
        self.rule_codes: dict[str, QPlainTextEdit] = {}
        self.rule_statuses: dict[str, QLabel] = {}
        self.rule_names: dict[str, list[str]] = {}
        self.rule_name_edits: dict[str, QLineEdit] = {}
        self.rule_add_buttons: dict[str, QPushButton] = {}
        self.rule_apply_buttons: dict[str, QPushButton] = {}
        self._movement_roles = self.codec.movement_roles()
        for kind, title, filename, first in (
            ("background", "背景规律", "背景规律名称.ini", 0),
            ("movement", "运行规律", "地图动画运行规律名称.ini", 1),
            ("sprite", "组图规律", "地图动画图片名称.ini", 0),
        ):
            group = QGroupBox(title)
            self.rule_groups[kind] = group
            box = QVBoxLayout(group)
            listing = QListWidget()
            defaults = animation_names(filename, self.codec.count(kind), first)
            self.default_names[kind] = defaults
            names = [
                self.name_overrides.get((kind, index), default)
                for index, default in enumerate(defaults)
            ]
            self.rule_names[kind] = names
            listing.addItems(f"[{i:02X}]{i:03d}：{name}" for i, name in enumerate(names))
            self.rule_lists[kind] = listing
            listing.currentRowChanged.connect(lambda row, key=kind: self._select_rule(key, row))
            box.addWidget(listing, 3)
            if kind in ("movement", "sprite"):
                add_button = QPushButton("添加")
                self.rule_add_buttons[kind] = add_button
                if kind == "sprite":
                    add_button.setToolTip(
                        "复制当前完整组图到 $EB—$F6 可调用预留槽；使用尾部 88 字节安全池。"
                    )
                    add_button.clicked.connect(
                        lambda _checked=False: self._add_sprite_rule()
                    )
                else:
                    add_button.setToolTip(
                        "复制当前规律到 $7D—$9C，并同时改绑当前地图动画中唯一一处同角色引用。"
                    )
                    add_button.clicked.connect(
                        lambda _checked=False: self._add_movement_rule()
                    )
                box.addWidget(add_button)
            name_edit = QLineEdit()
            name_edit.setMaxLength(80)
            name_edit.textEdited.connect(
                lambda text, key=kind: self._change_rule_name(key, text)
            )
            self.rule_name_edits[kind] = name_edit
            box.addWidget(QLabel("规律名称"))
            box.addWidget(name_edit)
            status = QLabel()
            status.setWordWrap(True)
            self.rule_statuses[kind] = status
            code = QPlainTextEdit()
            code.setReadOnly(True)
            self.rule_codes[kind] = code
            box.addWidget(code, 2)
            if kind == "sprite":
                code.setReadOnly(False)
                apply = QPushButton("应用首图块")
                self.rule_apply_buttons[kind] = apply
                apply.setToolTip(
                    "仅首图块字节已有参考版保存/全新进程重开黄金；X/Y 与后续拼图指令保持只读。"
                )
                apply.clicked.connect(self._apply_sprite_code)
                box.addWidget(apply)
                preview_library = QComboBox()
                bank_count = self.project.chr_tile_count // 64
                for bank in range(max(0, bank_count - 3)):
                    preview_library.addItem(
                        f"[{bank:02X}]{bank:03d}：{0x80010 + bank * 0x400:05X}",
                        bank,
                    )
                preview_library.setCurrentIndex(
                    max(0, preview_library.findData(8))
                )
                preview_library.setToolTip(
                    "只选择物理拼图使用的 4 KiB CHR 预览窗口，不写入 ROM。"
                )
                self.sprite_preview_library = preview_library
                preview_row = QFormLayout()
                preview_row.addRow("预览图库", preview_library)
                box.addLayout(preview_row)
                self.animation_puzzle_button = QPushButton("动画拼图")
                self.animation_puzzle_button.clicked.connect(self._open_sprite_puzzle)
                box.addWidget(self.animation_puzzle_button)
                form = QFormLayout()
                self.sprite_y, self.sprite_x = QSpinBox(), QSpinBox()
                for spin in (self.sprite_y, self.sprite_x):
                    spin.setRange(-128, 127)
                    spin.setReadOnly(True)
                    spin.setButtonSymbols(QSpinBox.ButtonSymbols.NoButtons)
                    spin.setToolTip(
                        "参考版现场采集证明：界面值会变化，但确定/保存不写 ROM，故保持只读。"
                    )
                form.addRow("起始 X", self.sprite_x)
                form.addRow("起始 Y", self.sprite_y)
                self.sprite_readonly_details = QWidget()
                self.sprite_readonly_details.setLayout(form)
            elif kind == "movement":
                apply = QPushButton("应用等长代码")
                self.rule_apply_buttons[kind] = apply
                apply.clicked.connect(self._apply_movement_code)
                box.addWidget(apply)
                notice = QLabel("根据实际调用区分组图帧和坐标位移。可改帧、位移、音效和循环次数；跳转、长度与控制码保持原值。")
                notice.setWordWrap(True)
                box.addWidget(notice)
            else:
                apply = QPushButton("应用等长代码")
                self.rule_apply_buttons[kind] = apply
                apply.clicked.connect(self._apply_background_code)
                box.addWidget(apply)
                notice = QLabel(
                    "仅完整到达唯一结束码的背景记录可改已验证绘制参数；控制码、资源引用、变长/运行时参数、FE 布局头和 FF 结束码保持原值。"
                )
                notice.setWordWrap(True)
                box.addWidget(notice)
            diagnostics = QWidget()
            diagnostics_layout = QVBoxLayout(diagnostics)
            diagnostics_layout.setContentsMargins(0, 0, 0, 0)
            diagnostics_layout.addWidget(status)
            if kind == "sprite":
                diagnostics_layout.addWidget(self.sprite_readonly_details)
            box.addWidget(collapsible_details(diagnostics))
            group.setMinimumWidth(250)
            layout.addWidget(group, 1)
        for kind, listing in self.rule_lists.items():
            listing.setCurrentRow(1 if kind == "movement" else 0)
        return page

    def _change_rule_name(self, kind: str, text: str) -> None:
        row = self.rule_lists[kind].currentRow()
        if row < 0:
            return
        self.rule_names[kind][row] = text
        if text == self.default_names[kind][row]:
            self.name_overrides.pop((kind, row), None)
        else:
            self.name_overrides[(kind, row)] = text
        self.rule_lists[kind].item(row).setText(
            f"[{row:02X}]{row:03d}：{text}"
        )

    def _add_sprite_rule(self) -> None:
        source_index = self.rule_lists["sprite"].currentRow()
        if source_index < 0:
            return
        try:
            codec = AnimationCodec(self.draft)
            new_index, patches = codec.clone_sprite_rule_patches(source_index)
            for offset, before, after in patches:
                if bytes(self.draft[offset:offset + len(before)]) != before:
                    raise ValueError("组图草稿已变化，请重新打开窗口。")
                self.draft[offset:offset + len(after)] = after
            base_name = self.rule_names["sprite"][source_index]
            new_name = f"{base_name} 副本"
            if len(new_name) > 80:
                new_name = f"组图 {new_index:03d} 副本"
            self.rule_names["sprite"][new_index] = new_name
            self.name_overrides[("sprite", new_index)] = new_name
            self.rule_lists["sprite"].item(new_index).setText(
                f"[{new_index:02X}]{new_index:03d}：{new_name}"
            )
            self.rule_lists["sprite"].setCurrentRow(new_index)
            self.read_only_status.setText(
                f"已把组图 ${source_index:02X} 复制到预留槽 ${new_index:02X}；"
                "点击确定后写入工程。"
            )
        except ValueError as error:
            self.read_only_status.setText(f"未添加组图：{error}")

    def _add_movement_rule(self) -> None:
        source_index = self.rule_lists["movement"].currentRow()
        map_index = self.animation_list.currentRow()
        if source_index < 0 or map_index < 0 or not self._flush_script():
            return
        try:
            codec = AnimationCodec(self.draft)
            new_index, role, patches = codec.clone_movement_rule_patches(
                source_index,
                map_index,
            )
            for offset, before, after in patches:
                if bytes(self.draft[offset:offset + len(before)]) != before:
                    raise ValueError("运行规律草稿已变化，请重新打开窗口。")
                self.draft[offset:offset + len(after)] = after
            self._movement_roles = AnimationCodec(self.draft).movement_roles()
            base_name = self.rule_names["movement"][source_index]
            new_name = f"{base_name} 副本"
            if len(new_name) > 80:
                new_name = f"运行规律 {new_index:03d} 副本"
            self.rule_names["movement"][new_index] = new_name
            self.name_overrides[("movement", new_index)] = new_name
            self.rule_lists["movement"].item(new_index).setText(
                f"[{new_index:02X}]{new_index:03d}：{new_name}"
            )
            # Refresh the visible map record so returning to the first tab does
            # not retain the pre-bind operand in its local editor snapshot.
            self.script_editor.set_record(self.draft, "map", map_index)
            self.rule_lists["movement"].setCurrentRow(new_index)
            role_text = "组图帧序列" if role == "frames" else "坐标位移"
            self.read_only_status.setText(
                f"已把{role_text} ${source_index:02X} 复制到 ${new_index:02X}，"
                f"并改绑地图动画 ${map_index:02X} 的唯一引用；点击确定后写入工程。"
            )
        except ValueError as error:
            self.read_only_status.setText(f"未添加运行规律：{error}")

    def _select_rule(self, kind: str, row: int) -> None:
        if row < 0:
            return
        if (
            kind == "background"
            and self._background_index >= 0
            and not self._apply_background_code(self._background_index)
        ):
            listing = self.rule_lists[kind]
            blocked = listing.blockSignals(True)
            listing.setCurrentRow(self._background_index)
            listing.blockSignals(blocked)
            return
        if kind == "movement" and self._movement_index >= 0 and not self._apply_movement_code(self._movement_index):
            listing = self.rule_lists[kind]
            blocked = listing.blockSignals(True)
            listing.setCurrentRow(self._movement_index)
            listing.blockSignals(blocked)
            return
        if kind == "sprite" and self._sprite_index >= 0 and not self._apply_sprite_code(self._sprite_index):
            listing = self.rule_lists[kind]
            blocked = listing.blockSignals(True)
            listing.setCurrentRow(self._sprite_index)
            listing.blockSignals(blocked)
            return
        record = AnimationCodec(self.draft).record(kind, row)
        self.rule_name_edits[kind].setText(self.rule_names[kind][row])
        self.rule_codes[kind].setPlainText(record.raw.hex(" ").upper())
        self.rule_statuses[kind].setText(f"当前 ROM · ${record.offset:06X} · {len(record.raw)} 字节"
                                         + (f" · 与 {len(record.aliases)} 项共享" if record.aliases else ""))
        if kind == "background":
            self._background_index = row
            editable, explanation = AnimationCodec(self.draft).background_edit_status(row)
            self.rule_codes[kind].setReadOnly(not editable)
            self.rule_codes[kind].setVisible(editable)
            self.rule_apply_buttons[kind].setVisible(editable)
            self.rule_statuses[kind].setText(
                self.rule_statuses[kind].text()
                + f" · {explanation}"
            )
        if kind == "movement":
            self._movement_index = row
            roles = self._movement_roles.get(row, set())
            self.rule_codes[kind].setReadOnly(len(roles) != 1)
            self.rule_codes[kind].setVisible(len(roles) == 1)
            self.rule_apply_buttons[kind].setVisible(len(roles) == 1)
            self.rule_statuses[kind].setText(self.rule_statuses[kind].text() + " · " +
                                            ({"frames": "组图帧序列", "axis": "坐标位移"}.get(next(iter(roles)), "")
                                             if len(roles) == 1 else "运行方式未唯一确认，只读"))
        if kind == "sprite":
            self._sprite_index = row
            self.rule_codes[kind].setPlainText(record.raw[2:].hex(" ").upper())
            self.rule_statuses[kind].setText(
                self.rule_statuses[kind].text()
                + " · X/Y 参考版不持久化，只读；首图块已有动态黄金"
            )
            self._loading = True
            self.sprite_x.setValue(int.from_bytes(record.raw[:1], signed=True))
            self.sprite_y.setValue(int.from_bytes(record.raw[1:2], signed=True))
            self._loading = False

    def _open_sprite_puzzle(self) -> None:
        row = self.rule_lists["sprite"].currentRow()
        if row < 0:
            return
        codec = AnimationCodec(self.draft)
        record = codec.record("sprite", row)
        SpritePuzzlePreviewDialog(
            record,
            self.project,
            codec,
            self,
            initial_library=int(self.sprite_preview_library.currentData() or 0),
        ).exec()

    def _apply_movement_code(self, row: int | None = None) -> bool:
        try:
            codec = AnimationCodec(self.draft)
            if row is None or isinstance(row, bool):
                row = self.rule_lists["movement"].currentRow()
            record = codec.record("movement", row)
            changed = bytes.fromhex(self.rule_codes["movement"].toPlainText())
            if changed == record.raw:
                return True
            offset, _before, after = codec.rule_patch(record, changed)
            self.draft[offset:offset + len(after)] = after
            self.read_only_status.setText("运行规律已应用到窗口草稿，点击确定后写入工程。")
            return True
        except ValueError as error:
            self.read_only_status.setText(f"运行规律未应用：{error}")
            return False

    def _apply_background_code(self, row: int | None = None) -> bool:
        try:
            codec = AnimationCodec(self.draft)
            if row is None or isinstance(row, bool):
                row = self.rule_lists["background"].currentRow()
            record = codec.record("background", row)
            changed = bytes.fromhex(self.rule_codes["background"].toPlainText())
            if changed == record.raw:
                return True
            offset, _before, after = codec.rule_patch(record, changed)
            self.draft[offset:offset + len(after)] = after
            self.read_only_status.setText(
                "背景规律已验证绘制参数已应用到窗口草稿，点击确定后写入工程。"
            )
            return True
        except ValueError as error:
            self.read_only_status.setText(f"背景规律未应用：{error}")
            return False

    def _apply_sprite_code(self, row: int | None = None) -> bool:
        try:
            codec = AnimationCodec(self.draft)
            if row is None or isinstance(row, bool):
                row = self.rule_lists["sprite"].currentRow()
            record = codec.record("sprite", row)
            changed = record.raw[:2] + bytes.fromhex(
                self.rule_codes["sprite"].toPlainText()
            )
            if changed == record.raw:
                return True
            offset, _before, after = codec.rule_patch(record, changed)
            self.draft[offset:offset + len(after)] = after
            self.read_only_status.setText(
                "组图首图块已应用到窗口草稿，点击确定后写入工程。"
            )
            return True
        except ValueError as error:
            self.read_only_status.setText(f"组图规律未应用：{error}")
            return False
            return False

    def _calls_tab(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        hint = QLabel(
            "按游戏用途列出已确认可修改的精神与地图武器动画；"
            "选择新动画后会随窗口“确定”一起保存。"
        )
        hint.setWordWrap(True)
        layout.addWidget(hint)
        self.call_table = QTableWidget(0, 5)
        self.call_table.setHorizontalHeaderLabels(
            ("使用场景", "动画调用", "操作", "调用位置", "状态/原因")
        )
        self.call_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        self.call_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        self.call_table.horizontalHeader().setSectionResizeMode(4, QHeaderView.ResizeMode.Stretch)
        self.call_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.call_table.setAlternatingRowColors(True)
        self.call_combos: dict[int, QComboBox] = {}
        self.call_editable_rows: list[tuple[int, bool]] = []
        self.call_animation_model = QStandardItemModel(self)
        for i, name in enumerate(self.names):
            item = QStandardItem(f"[{i:02X}]{i:03d}：{name}")
            item.setData(i, Qt.ItemDataRole.UserRole)
            self.call_animation_model.appendRow(item)
        calls = self.codec.calls()
        self.call_table.setRowCount(len(calls))
        for row, (offset, index) in enumerate(calls):
            self.call_table.setItem(row, 0, QTableWidgetItem(self._call_usage_label(offset)))
            combo = QComboBox()
            combo.setModel(self.call_animation_model)
            combo.setCurrentIndex(index)
            editable, explanation = self.codec.call_status(offset)
            if not editable:
                combo.setEnabled(False)
                combo.setToolTip(explanation)
            else:
                combo.setToolTip(explanation)
            combo.currentIndexChanged.connect(lambda selected, address=offset: self._change_call(address, selected))
            self.call_table.setCellWidget(row, 1, combo)
            self.call_combos[offset] = combo
            status_item = QTableWidgetItem(explanation)
            status_item.setToolTip(explanation)
            self.call_table.setItem(row, 4, status_item)
            jump = QPushButton("查看动画")
            jump.clicked.connect(lambda checked=False, box=combo: self._show_call_animation(box.currentIndex()))
            self.call_table.setCellWidget(row, 2, jump)
            self.call_table.setItem(row, 3, QTableWidgetItem(f"${offset:06X}"))
            self.call_editable_rows.append((row, editable))
            self.call_table.setRowHidden(row, not editable)
        self.call_table.setColumnHidden(3, True)
        self.call_table.setColumnHidden(4, True)
        diagnostics = QWidget()
        diagnostics_layout = QVBoxLayout(diagnostics)
        diagnostics_layout.setContentsMargins(0, 0, 0, 0)
        self.show_readonly_calls = QCheckBox("显示不可编辑的调用、地址和原因")
        self.show_readonly_calls.toggled.connect(self._toggle_call_diagnostics)
        diagnostics_layout.addWidget(self.show_readonly_calls)
        layout.addWidget(collapsible_details(diagnostics))
        layout.addWidget(self.call_table, 1)
        return page

    @staticmethod
    def _call_usage_label(offset: int) -> str:
        if offset in SPIRIT_ANIMATION_CALLS:
            return f"精神：{SPIRIT_NAMES[SPIRIT_ANIMATION_CALLS.index(offset)]}"
        if offset in MAP_WEAPON_ANIMATION_CALLS:
            return f"地图武器：{MAP_WEAPON_ANIMATION_CALLS[offset]}"
        return "其他已确认动画调用"

    def _toggle_call_diagnostics(self, enabled: bool) -> None:
        self.call_table.setColumnHidden(3, not enabled)
        self.call_table.setColumnHidden(4, not enabled)
        for row, editable in self.call_editable_rows:
            self.call_table.setRowHidden(row, not editable and not enabled)

    def _change_call(self, offset: int, index: int) -> None:
        try:
            # The two address/ID-documented sites are verified against the
            # original ROM value.  After a first draft change, checking that
            # documentation against the draft would incorrectly lock the
            # selector and prevent a second edit or a return to the original.
            if not self.codec.call_is_editable(offset):
                raise ValueError("此处只识别到调用字节，事件上下文尚未验证，暂不改写。")
            codec = AnimationCodec(self.draft)
            if self.draft[offset:offset + 2] != b"\x38\x02":
                raise ValueError("动画调用指令已变化，不能继续编辑。")
            if not 0 <= index < codec.count("map"):
                raise ValueError("动画编号超出指针表。")
            if not codec.record("map", index).complete:
                raise ValueError("目标动画包含未验证指令，不能作为新的调用目标。")
            self.draft[offset + 2] = index
        except ValueError as error:
            self.read_only_status.setText(str(error))
            combo = self.call_combos[offset]
            blocked = combo.blockSignals(True)
            combo.setCurrentIndex(self.draft[offset + 2])
            combo.blockSignals(blocked)

    def _show_call_animation(self, index: int) -> None:
        self.animation_list.setCurrentRow(index)
        self.tabs.setCurrentIndex(0)

    def accept(self) -> None:
        if (self.project is None or not hasattr(self, "script_editor") or not self._flush_script()
                or not self._apply_movement_code() or not self._apply_background_code()
                or not self._apply_sprite_code()):
            return
        try:
            # Small changed runs retain optimistic conflict checks without
            # treating unrelated database edits as an animation conflict.
            patches = []
            cursor = 0
            while cursor < len(self.base):
                if self.base[cursor] == self.draft[cursor]:
                    cursor += 1
                    continue
                start = cursor
                while cursor < len(self.base) and self.base[cursor] != self.draft[cursor]:
                    cursor += 1
                patches.append((start, self.base[start:cursor], bytes(self.draft[start:cursor])))
            with self.project.transaction("地图动画、字幕、规律、调用与名称"):
                apply_animation_patches(
                    self.project,
                    tuple(patches),
                    "地图动画、规律与调用",
                )
                if self._pending_credits is not None:
                    self.project.set_production_credits(*self._pending_credits)
                self.project.replace_animation_label_overrides(self.name_overrides)
        except ValueError as error:
            self.read_only_status.setText(f"未写入：{error}")
            return
        super().accept()
