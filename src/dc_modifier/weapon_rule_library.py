from __future__ import annotations

from dataclasses import dataclass

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QMessageBox,
    QPlainTextEdit,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from .animation_editor import animation_names


@dataclass(frozen=True)
class WeaponRuleTable:
    key: str
    title: str
    filename: str
    pointer_table: int
    count: int
    file_base: int
    cpu_base: int
    hidden_prefix: int
    first_pointer: int


WEAPON_RULE_TABLES = (
    WeaponRuleTable(
        "weapon_beam", "光束组图规律", "光束规律名称.ini",
        0x11117, 0xFF, 0x10010, 0x8000, 3, 0x9307,
    ),
    WeaponRuleTable(
        "weapon_movement_1", "物理运行规律1", "运行规律名称.ini",
        0x120B9, 0xFC, 0x12010, 0xA000, 0, 0xA2A3,
    ),
    WeaponRuleTable(
        "weapon_movement_2", "物理运行规律2", "运行规律名称2.ini",
        0x12A8A, 0xFA, 0x12010, 0xA000, 0, 0xAC70,
    ),
    WeaponRuleTable(
        "weapon_picture", "物理图片", "物理图片名称.ini",
        0x10030, 0xFF, 0x10010, 0x8000, 2, 0x8220,
    ),
)


class WeaponRuleCatalog:
    """Read the four reference weapon-rule pointer libraries safely."""

    def __init__(self, data: bytes | bytearray) -> None:
        self.data = bytes(data)
        for table in WEAPON_RULE_TABLES:
            if self._pointer(table, 1) != table.first_pointer:
                raise ValueError(f"{table.title}指针表与已验证格式不同；已停止解析。")

    def _pointer(self, table: WeaponRuleTable, rule_id: int) -> int:
        offset = table.pointer_table + rule_id * 2
        return int.from_bytes(self.data[offset:offset + 2], "little")

    def record(
        self,
        table: WeaponRuleTable,
        rule_id: int,
    ) -> tuple[int, bytes, tuple[int, ...]]:
        if not 1 <= rule_id <= table.count:
            raise IndexError(rule_id)
        pointer = self._pointer(table, rule_id)
        aliases = tuple(
            index
            for index in range(1, table.count + 1)
            if index != rule_id and self._pointer(table, index) == pointer
        )
        larger = {
            self._pointer(table, index)
            for index in range(1, table.count + 1)
            if self._pointer(table, index) > pointer
        }
        start = table.file_base + pointer - table.cpu_base
        if larger:
            end = table.file_base + min(larger) - table.cpu_base
        else:
            bank_end = table.file_base + 0x2000
            terminator = self.data.find(b"\xFF", start, bank_end)
            end = terminator + 1 if terminator >= start else bank_end
        if not 0 <= start < end <= len(self.data):
            raise ValueError(f"{table.title} ${rule_id:02X} 指针越界。")
        raw = self.data[start:end]
        return start, raw[table.hidden_prefix:], aliases


class WeaponRuleLibraryDialog(QDialog):
    """Reference-shaped, dedicated four-page weapon-rule browser."""

    def __init__(self, project, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.project = project
        self.catalog = WeaponRuleCatalog(project.working)
        self.overrides = dict(getattr(project, "animation_label_overrides", {}))
        self.defaults: dict[str, tuple[str, ...]] = {}
        self.setWindowTitle("规律")
        self.resize(940, 680)
        root = QVBoxLayout(self)
        notice = QLabel(
            "这里是武器专用的四套规律库，不与地图动画规律混用。"
            "当前已按参考版指针表读取名称、代码、地址和共享项；"
            "规律代码写回尚无逐字段黄金，因此保持只读。"
        )
        notice.setWordWrap(True)
        root.addWidget(notice)
        self.tabs = QTabWidget()
        self.lists: dict[str, QListWidget] = {}
        self.names: dict[str, QLineEdit] = {}
        self.codes: dict[str, QPlainTextEdit] = {}
        self.statuses: dict[str, QLabel] = {}
        root.addWidget(self.tabs, 1)
        overrides = getattr(project, "animation_label_overrides", {})
        for table in WEAPON_RULE_TABLES:
            page = QWidget()
            layout = QHBoxLayout(page)
            listing = QListWidget()
            defaults = animation_names(table.filename, table.count)
            self.defaults[table.key] = defaults
            listing.addItems(
                f"[{rule_id:02X}]{rule_id:03d}："
                f"{overrides.get((table.key, rule_id), defaults[rule_id - 1])}"
                for rule_id in range(1, table.count + 1)
            )
            listing.setMinimumWidth(330)
            layout.addWidget(listing, 2)
            details = QVBoxLayout()
            status = QLabel()
            status.setWordWrap(True)
            status.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
            details.addWidget(status)
            details.addWidget(QLabel("规律名称（当前配置）"))
            name = QLineEdit()
            name.setMaxLength(80)
            details.addWidget(name)
            details.addWidget(QLabel("代码（只读）"))
            code = QPlainTextEdit()
            code.setReadOnly(True)
            details.addWidget(code, 1)
            details.addWidget(QLabel("复制、完整与规律代码修改将在取得单字段保存黄金后开放。"))
            layout.addLayout(details, 3)
            self.tabs.addTab(page, table.title)
            self.lists[table.key] = listing
            self.names[table.key] = name
            self.codes[table.key] = code
            self.statuses[table.key] = status
            listing.currentRowChanged.connect(
                lambda row, item=table: self._select(item, row)
            )
            name.textEdited.connect(
                lambda text, item=table: self._rename(item, text)
            )
            listing.setCurrentRow(0)
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok
            | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.button(QDialogButtonBox.StandardButton.Ok).setText("确定")
        buttons.button(QDialogButtonBox.StandardButton.Cancel).setText("取消")
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        root.addWidget(buttons)

    def _select(self, table: WeaponRuleTable, row: int) -> None:
        if row < 0:
            return
        rule_id = row + 1
        offset, raw, aliases = self.catalog.record(table, rule_id)
        self.names[table.key].setText(
            self.lists[table.key].item(row).text().split("：", 1)[-1]
        )
        self.codes[table.key].setPlainText(raw.hex(" ").upper())
        shared = "、".join(f"${value:02X}" for value in aliases[:16])
        self.statuses[table.key].setText(
            f"规律 ${rule_id:02X} · 文件地址 0x{offset:06X} · {len(raw)} 字节"
            + (f" · 共享：{shared}" if shared else " · 独立记录")
        )

    def _rename(self, table: WeaponRuleTable, text: str) -> None:
        row = self.lists[table.key].currentRow()
        if row < 0:
            return
        rule_id = row + 1
        default = self.defaults[table.key][row]
        if text == default:
            self.overrides.pop((table.key, rule_id), None)
        else:
            self.overrides[(table.key, rule_id)] = text
        self.lists[table.key].item(row).setText(
            f"[{rule_id:02X}]{rule_id:03d}：{text}"
        )

    def accept(self) -> None:
        try:
            self.project.replace_animation_label_overrides(self.overrides)
        except ValueError as error:
            QMessageBox.warning(self, "无法保存规律名称", str(error))
            return
        super().accept()
