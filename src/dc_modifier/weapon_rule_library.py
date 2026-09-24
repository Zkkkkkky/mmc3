from __future__ import annotations

from dataclasses import dataclass

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
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

    def pointer(self, table: WeaponRuleTable, rule_id: int) -> int:
        if not 1 <= rule_id <= table.count:
            raise IndexError(rule_id)
        return self._pointer(table, rule_id)

    def record(
        self,
        table: WeaponRuleTable,
        rule_id: int,
        *,
        include_hidden: bool = False,
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
        return start, raw if include_hidden else raw[table.hidden_prefix:], aliases


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
        self.searches: dict[str, QLineEdit] = {}
        self.complete_checks: dict[str, QCheckBox] = {}
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
            selection = QVBoxLayout()
            search_row = QHBoxLayout()
            search = QLineEdit()
            search.setPlaceholderText("按编号或名称查找，例如 20、光束")
            find_next = QPushButton("查找下一个")
            find_next.clicked.connect(
                lambda _checked=False, item=table: self._find_next(item)
            )
            search.returnPressed.connect(lambda item=table: self._find_next(item))
            search_row.addWidget(search, 1)
            search_row.addWidget(find_next)
            selection.addLayout(search_row)
            selection.addWidget(listing, 1)
            layout.addLayout(selection, 2)
            details = QVBoxLayout()
            status = QLabel()
            status.setWordWrap(True)
            status.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
            details.addWidget(status)
            details.addWidget(QLabel("规律名称（当前配置）"))
            name = QLineEdit()
            name.setMaxLength(80)
            details.addWidget(name)
            code_title = QHBoxLayout()
            code_title.addWidget(QLabel("代码（安全只读）"))
            complete = QCheckBox("显示完整记录（含前置字节）")
            complete.setToolTip(
                "参考窗口会隐藏部分固定前置字节；勾选后可查看磁盘中的完整记录，仍不会修改 ROM。"
            )
            complete.toggled.connect(
                lambda _checked=False, item=table: self._refresh_selected(item)
            )
            code_title.addStretch()
            code_title.addWidget(complete)
            details.addLayout(code_title)
            code = QPlainTextEdit()
            code.setReadOnly(True)
            details.addWidget(code, 1)
            code_actions = QHBoxLayout()
            copy_code = QPushButton("复制代码")
            copy_code.clicked.connect(
                lambda _checked=False, item=table: self._copy_current(item)
            )
            export_current = QPushButton("导出当前…")
            export_current.clicked.connect(
                lambda _checked=False, item=table: self._export_current(item)
            )
            export_all = QPushButton("导出本页全部…")
            export_all.clicked.connect(
                lambda _checked=False, item=table: self._export_all(item)
            )
            code_actions.addWidget(copy_code)
            code_actions.addWidget(export_current)
            code_actions.addWidget(export_all)
            code_actions.addStretch()
            details.addLayout(code_actions)
            boundary = QLabel(
                "名称保存到工程；查找、复制、完整查看与导出均已可用。"
                "规律代码写回仍需单字段保存黄金，当前不会猜写 ROM。"
            )
            boundary.setWordWrap(True)
            details.addWidget(boundary)
            layout.addLayout(details, 3)
            self.tabs.addTab(page, table.title)
            self.lists[table.key] = listing
            self.names[table.key] = name
            self.codes[table.key] = code
            self.statuses[table.key] = status
            self.searches[table.key] = search
            self.complete_checks[table.key] = complete
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
        include_hidden = self.complete_checks[table.key].isChecked()
        self.names[table.key].setText(
            self.lists[table.key].item(row).text().split("：", 1)[-1]
        )
        try:
            offset, raw, aliases = self.catalog.record(
                table, rule_id, include_hidden=include_hidden
            )
        except ValueError as error:
            pointer = self.catalog.pointer(table, rule_id)
            self.codes[table.key].clear()
            self.statuses[table.key].setText(
                f"规律 ${rule_id:02X} · 指针 ${pointer:04X} · "
                f"保留/控制项，不能按普通规律解析：{error}"
            )
            return
        self.codes[table.key].setPlainText(raw.hex(" ").upper())
        shared = "、".join(f"${value:02X}" for value in aliases[:16])
        self.statuses[table.key].setText(
            f"规律 ${rule_id:02X} · 文件地址 0x{offset:06X} · {len(raw)} 字节"
            + (
                f"（完整记录，含 {table.hidden_prefix} 个前置字节）"
                if include_hidden and table.hidden_prefix
                else ""
            )
            + (f" · 共享：{shared}" if shared else " · 独立记录")
        )

    def _refresh_selected(self, table: WeaponRuleTable) -> None:
        self._select(table, self.lists[table.key].currentRow())

    def _find_next(self, table: WeaponRuleTable) -> None:
        query = self.searches[table.key].text().strip().casefold()
        if not query:
            return
        listing = self.lists[table.key]
        start = listing.currentRow() + 1
        for step in range(listing.count()):
            row = (start + step) % listing.count()
            text = listing.item(row).text().casefold()
            rule_id = row + 1
            identifiers = {
                str(rule_id), f"{rule_id:02x}", f"${rule_id:02x}",
                f"[{rule_id:02x}]",
            }
            if query in text or query in identifiers:
                listing.setCurrentRow(row)
                listing.scrollToItem(listing.item(row))
                return
        QMessageBox.information(self, "没有找到", f"本页没有匹配“{query}”的规律。")

    def _current_text(self, table: WeaponRuleTable) -> str:
        row = self.lists[table.key].currentRow()
        if row < 0:
            return ""
        rule_id = row + 1
        name = self.lists[table.key].item(row).text().split("：", 1)[-1]
        try:
            offset, raw, aliases = self.catalog.record(
                table,
                rule_id,
                include_hidden=self.complete_checks[table.key].isChecked(),
            )
        except ValueError as error:
            pointer = self.catalog.pointer(table, rule_id)
            return (
                f"{table.title} ${rule_id:02X}\n"
                f"名称：{name}\n"
                f"指针：${pointer:04X}\n"
                f"状态：保留/控制项，不能按普通规律解析（{error}）\n"
            )
        alias_text = "、".join(f"${value:02X}" for value in aliases) or "无"
        return (
            f"{table.title} ${rule_id:02X}\n"
            f"名称：{name}\n"
            f"文件地址：0x{offset:06X}\n"
            f"共享规律：{alias_text}\n"
            f"代码：{raw.hex(' ').upper()}\n"
        )

    def _all_text(self, table: WeaponRuleTable) -> str:
        complete = self.complete_checks[table.key].isChecked()
        rows = [f"# {table.title}", f"# 记录数：{table.count}", ""]
        for rule_id in range(1, table.count + 1):
            name = self.lists[table.key].item(rule_id - 1).text().split("：", 1)[-1]
            try:
                offset, raw, aliases = self.catalog.record(
                    table, rule_id, include_hidden=complete
                )
            except ValueError as error:
                pointer = self.catalog.pointer(table, rule_id)
                rows.append(
                    f"${rule_id:02X}\t指针:${pointer:04X}\t{name}\t"
                    f"保留/控制项\t{error}"
                )
                continue
            shared = ",".join(f"${value:02X}" for value in aliases) or "-"
            rows.append(
                f"${rule_id:02X}\t0x{offset:06X}\t{name}\t共享:{shared}\t"
                f"{raw.hex(' ').upper()}"
            )
        return "\n".join(rows) + "\n"

    def _copy_current(self, table: WeaponRuleTable) -> None:
        text = self._current_text(table)
        if text:
            QApplication.clipboard().setText(text)
            self.statuses[table.key].setText(
                self.statuses[table.key].text() + " · 已复制"
            )

    def _save_text(self, title: str, suggested: str, text: str) -> None:
        path, _selected_filter = QFileDialog.getSaveFileName(
            self, title, suggested, "文本文件 (*.txt);;所有文件 (*)"
        )
        if not path:
            return
        try:
            from pathlib import Path

            Path(path).write_text(text, encoding="utf-8-sig")
        except OSError as error:
            QMessageBox.warning(self, "导出失败", str(error))

    def _export_current(self, table: WeaponRuleTable) -> None:
        row = self.lists[table.key].currentRow()
        if row < 0:
            return
        self._save_text(
            "导出当前规律",
            f"{table.title}-${row + 1:02X}.txt",
            self._current_text(table),
        )

    def _export_all(self, table: WeaponRuleTable) -> None:
        self._save_text(
            "导出本页全部规律",
            f"{table.title}-全部.txt",
            self._all_text(table),
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
