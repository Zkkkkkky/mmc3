from __future__ import annotations

from collections.abc import Callable
import hashlib
from pathlib import Path
import re

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QComboBox,
    QFileDialog,
    QFormLayout,
    QFrame,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QInputDialog,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMenu,
    QMessageBox,
    QPlainTextEdit,
    QProgressBar,
    QPushButton,
    QScrollArea,
    QSpinBox,
    QSplitter,
    QTableWidget,
    QTableWidgetItem,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from fc_editor.models import UNIT_FIELDS, WEAPON_FIELDS
from fc_editor.dc_text import concise_dc_text
from fc_editor.expansion import AUTO_ALLOCATION_PREFIX, REOPEN_GUARD_PREFIX
from fc_editor.resources import ResourceGraph
from fc_rom_editor_core import RomProject, compact_ids

from .music_import import assemble_famistudio_music_source, load_music_bank
from .workspace import default_export_path, writable_output_path


def page_title(title: str, subtitle: str) -> tuple[QLabel, QLabel]:
    """Keep semantic page labels without taking space in the legacy layout."""
    heading = QLabel(title)
    heading.setObjectName("pageTitle")
    description = QLabel(subtitle)
    description.setObjectName("pageSubtitle")
    description.setWordWrap(True)
    heading.hide()
    description.hide()
    return heading, description


def readonly_item(text: str) -> QTableWidgetItem:
    item = QTableWidgetItem(text)
    item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEditable)
    return item


def parse_id_expression(text: str, maximum: int) -> list[int]:
    """Parse IDs such as ``$00-$05, 16, 0x20`` into a sorted unique list."""

    def parse_one(token: str) -> int:
        token = token.strip()
        if not token:
            raise ValueError("ID不能为空。")
        if token.startswith("$"):
            return int(token[1:], 16)
        if token.lower().startswith("0x"):
            return int(token[2:], 16)
        return int(token, 10)

    result: set[int] = set()
    for part in re.split(r"[,，、\s]+", text.strip()):
        if not part:
            continue
        match = re.fullmatch(r"(.+?)[-—~～](.+)", part)
        if match:
            start = parse_one(match.group(1))
            end = parse_one(match.group(2))
            if end < start:
                raise ValueError(f"ID范围倒置：{part}")
            result.update(range(start, end + 1))
        else:
            result.add(parse_one(part))
    if not result:
        raise ValueError("请输入至少一个ID。")
    invalid = sorted(value for value in result if not 0 <= value <= maximum)
    if invalid:
        raise ValueError(
            f"ID超出范围 $00—${maximum:02X}："
            + "、".join(f"${value:02X}" for value in invalid)
        )
    return sorted(result)


class ProjectPage(QWidget):
    project_changed = Signal(str)
    navigation_requested = Signal(str)

    def __init__(self) -> None:
        super().__init__()
        self.project: RomProject | None = None

    def set_project(self, project: RomProject | None) -> None:
        self.project = project
        self.refresh()

    def refresh(self) -> None:
        pass

    @property
    def has_pending_draft(self) -> bool:
        """Whether this page owns a valid form that has not been applied yet."""

        button = getattr(self, "apply_button", None)
        return isinstance(button, QPushButton) and button.isEnabled()

    @property
    def pending_draft_error(self) -> str | None:
        """Return why a pending form cannot be committed, if applicable."""

        return None

    def commit_pending_changes(self) -> bool:
        """Apply the page's primary pending form before a window-level OK."""

        if not self.has_pending_draft:
            return True
        button = getattr(self, "apply_button", None)
        if not isinstance(button, QPushButton):
            return False
        before = bytes(self.project.working) if self.project is not None else None
        button.click()
        if (
            self.project is not None
            and before is not None
            and bytes(self.project.working) != before
            and self.has_pending_draft
        ):
            self.refresh()
        return not self.has_pending_draft

    def show_error(self, error: Exception) -> None:
        QMessageBox.critical(self, "操作失败", str(error))


class OverviewPage(ProjectPage):
    def __init__(self) -> None:
        super().__init__()
        layout = QVBoxLayout(self)
        title, subtitle = page_title(
            "工程概览",
            "先确认基准ROM身份，再从上方工作区进入要修改的资源。所有输出都使用“另存为”。",
        )
        layout.addWidget(title)
        layout.addWidget(subtitle)
        cards = QGridLayout()
        self.profile_value = self._card(cards, 0, 0, "ROM配置", "尚未载入")
        self.mapper_value = self._card(cards, 0, 1, "Mapper / 容量", "—")
        self.hash_value = self._card(cards, 1, 0, "基准哈希", "—")
        self.space_value = self._card(cards, 1, 1, "扩展资源区", "—")
        layout.addLayout(cards)

        guide = QGroupBox("推荐工作流")
        guide_layout = QVBoxLayout(guide)
        guide_layout.addWidget(
            QLabel(
                "1. 打开 DC_kuorong_464K.nes　→　2. 自动规划扩展容量　→　"
                "3. 修改并随时验证　→　4. 保存工程并构建ROM/IPS"
            )
        )
        safety = QLabel(
            "安全规则：不会覆盖当前载入的基准ROM；音频引擎、固定银行和CHR区域由构建检查保护。"
        )
        safety.setWordWrap(True)
        safety.setObjectName("hintText")
        guide_layout.addWidget(safety)
        layout.addWidget(guide)
        quick_group = QGroupBox("常用入口")
        quick_layout = QGridLayout(quick_group)
        quick_entries = (
            ("扩展容量规划", "resources"),
            ("地图与部署", "maps"),
            ("机体属性", "units"),
            ("人物数据", "characters"),
            ("武器属性", "weapons"),
            ("剧情文字", "story"),
            ("增援/加入事件", "events"),
            ("劝降条件", "persuasion"),
            ("战斗音乐", "music"),
        )
        for index, (label, key) in enumerate(quick_entries):
            button = QPushButton(label)
            button.clicked.connect(
                lambda _checked=False, page_key=key: self.navigation_requested.emit(page_key)
            )
            quick_layout.addWidget(button, index // 3, index % 3)
        layout.addWidget(quick_group)
        layout.addStretch()

    @staticmethod
    def _card(layout: QGridLayout, row: int, column: int, label: str, value: str) -> QLabel:
        frame = QFrame()
        frame.setObjectName("metricCard")
        card_layout = QVBoxLayout(frame)
        caption = QLabel(label)
        caption.setObjectName("metricLabel")
        value_label = QLabel(value)
        value_label.setObjectName("metricValue")
        value_label.setWordWrap(True)
        value_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        card_layout.addWidget(caption)
        card_layout.addWidget(value_label)
        layout.addWidget(frame, row, column)
        return value_label

    def refresh(self) -> None:
        if self.project is None:
            self.profile_value.setText("尚未载入")
            self.mapper_value.setText("—")
            self.hash_value.setText("—")
            self.space_value.setText("—")
            return
        self.profile_value.setText(self.project.profile.label)
        self.mapper_value.setText(
            f"Mapper {self.project.rom_image.mapper} · {len(self.project.original) / 1024:.1f} KiB"
        )
        self.hash_value.setText(self.project.source_sha256)
        regions = "、".join(region.display for region in self.project.profile.free_prg_regions)
        self.space_value.setText(
            f"{self.project.expansion_available // 1024} / "
            f"{self.project.expansion_capacity // 1024} KiB 可用（{regions}）"
        )


class SearchableRecordPage(ProjectPage):
    def __init__(self) -> None:
        super().__init__()
        self.current_id: int | None = None
        self._copied_record_id: int | None = None
        self.search = QLineEdit()
        self.search.setClearButtonEnabled(True)
        self.search.setPlaceholderText("输入名称、十进制或十六进制ID…")
        self.search.textChanged.connect(self._filter_records)
        self.search_panel = QWidget()
        search_layout = QHBoxLayout(self.search_panel)
        search_layout.setContentsMargins(0, 0, 0, 0)
        search_layout.setSpacing(6)
        self.previous_record_button = QToolButton()
        self.previous_record_button.setText("◀")
        self.previous_record_button.setToolTip("上一条可见记录")
        self.previous_record_button.clicked.connect(lambda: self._select_relative(-1))
        self.next_record_button = QToolButton()
        self.next_record_button.setText("▶")
        self.next_record_button.setToolTip("下一条可见记录（Alt+↓）")
        self.next_record_button.clicked.connect(lambda: self._select_relative(1))
        self.result_count = QLabel("0 条")
        self.result_count.setObjectName("countBadge")
        search_layout.addWidget(self.search, 1)
        search_layout.addWidget(self.previous_record_button)
        search_layout.addWidget(self.next_record_button)
        search_layout.addWidget(self.result_count)
        self.records = QListWidget()
        self.records.setAlternatingRowColors(True)
        self.records.setUniformItemSizes(True)
        self.records.currentItemChanged.connect(self._selection_changed)
        self.records.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.records.customContextMenuRequested.connect(self._show_record_context_menu)
        self.records.setToolTip(
            "右键可复制、粘贴、复制到其他ID或还原当前记录。"
        )

    def set_project(self, project: RomProject | None) -> None:
        if project is not self.project:
            self._copied_record_id = None
        super().set_project(project)

    def _show_record_context_menu(self, position) -> None:
        item = self.records.itemAt(position)
        if item is not None:
            self.records.setCurrentItem(item)
        if self.current_id is None:
            return
        menu = QMenu(self.records)
        copy_action = menu.addAction("复制当前记录")
        paste_action = menu.addAction("粘贴到当前ID")
        paste_action.setEnabled(
            self._copied_record_id is not None
            and self._copied_record_id != self.current_id
        )
        menu.addSeparator()
        duplicate_action = menu.addAction("复制到其他ID…")
        reset_action = menu.addAction("还原当前记录")
        export_action = None
        if self.supports_record_export():
            menu.addSeparator()
            export_action = menu.addAction(self.record_export_label())
        selected = menu.exec(self.records.viewport().mapToGlobal(position))
        if selected is copy_action:
            self.copy_selected_record()
        elif selected is paste_action:
            self.paste_copied_record()
        elif selected is duplicate_action:
            self.duplicate_record()
        elif selected is reset_action:
            self.reset_record()
        elif export_action is not None and selected is export_action:
            self.export_selected_record()

    def copy_selected_record(self) -> None:
        if self.project is None or self.current_id is None:
            return
        if not self.commit_pending_changes():
            return
        self._copied_record_id = self.current_id
        self.records.setToolTip(
            f"已复制 ${self.current_id:02X}；在目标记录上右键选择“粘贴到当前ID”。"
        )

    def paste_copied_record(self) -> None:
        if (
            self.project is None
            or self.current_id is None
            or self._copied_record_id is None
            or self._copied_record_id == self.current_id
        ):
            return
        if not self.commit_pending_changes():
            return
        source_id = self._copied_record_id
        target_id = self.current_id
        if self.copy_record_to(source_id, target_id):
            self.populate_records()
            self.select_record_id(target_id)

    def select_record_id(self, record_id: int) -> bool:
        for row in range(self.records.count()):
            item = self.records.item(row)
            if int(item.data(Qt.ItemDataRole.UserRole)) == record_id:
                self.records.setCurrentRow(row)
                self.records.scrollToItem(item)
                return True
        return False

    def copy_record_to(self, source_id: int, target_id: int) -> bool:
        """Copy one verified record to another ID; subclasses own semantics."""

        return False

    def confirm_shared_name_edit(self, kind: str, record_ids: tuple[int, ...]) -> bool:
        if len(record_ids) <= 1:
            return True
        answer = QMessageBox.question(
            self,
            f"共用{kind}名称确认",
            f"当前名称记录由 {compact_ids(record_ids)} 共用。\n"
            f"直接改名会同时改变这些{kind}的显示名称，是否继续？",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel,
            QMessageBox.StandardButton.Cancel,
        )
        return answer == QMessageBox.StandardButton.Yes

    def supports_record_export(self) -> bool:
        return False

    def record_export_label(self) -> str:
        return "导出当前记录…"

    def export_selected_record(self) -> None:
        pass

    def duplicate_record(self) -> None:
        pass

    def reset_record(self) -> None:
        pass

    def record_text(self, record_id: int) -> str:
        return f"${record_id:02X}"

    def record_ids(self) -> range:
        return range(0)

    def preferred_record_id(self) -> int | None:
        """Choose a useful initial row while preserving an existing selection."""

        return None

    def populate_records(self) -> None:
        previous = self.current_id
        blocked = self.records.blockSignals(True)
        updates = self.records.updatesEnabled()
        self.records.setUpdatesEnabled(False)
        try:
            record_ids = list(self.record_ids()) if self.project is not None else []
            existing_ids = [
                self.records.item(row).data(Qt.ItemDataRole.UserRole)
                for row in range(self.records.count())
            ]
            if existing_ids == record_ids:
                # Applying a draft can refresh from inside currentItemChanged.
                # Keep the items alive until that Qt signal has returned.
                for row, record_id in enumerate(record_ids):
                    self.records.item(row).setText(self.record_text(record_id))
            else:
                self.records.clear()
                for record_id in record_ids:
                    item = QListWidgetItem(self.record_text(record_id))
                    item.setData(Qt.ItemDataRole.UserRole, record_id)
                    self.records.addItem(item)
            self._filter_records(self.search.text())
            if self.records.count():
                row = 0
                target_id = previous if previous is not None else self.preferred_record_id()
                if target_id is not None:
                    for index in range(self.records.count()):
                        if self.records.item(index).data(Qt.ItemDataRole.UserRole) == target_id:
                            row = index
                            break
                self.records.setCurrentRow(row)
        finally:
            self.records.blockSignals(blocked)
            self.records.setUpdatesEnabled(updates)
        if self.records.count():
            # Selection changes during repopulation are not user navigation.
            # Load once, after the final list is stable.
            self._selection_changed(self.records.currentItem(), None)
        else:
            self.current_id = None
            self.load_record(None)

    def _filter_records(self, text: str) -> None:
        query = text.strip().lower()
        visible_count = 0
        for index in range(self.records.count()):
            item = self.records.item(index)
            record_id = int(item.data(Qt.ItemDataRole.UserRole))
            decimal = str(record_id)
            hexadecimal = f"{record_id:02x}"
            visible = not query or query in item.text().lower() or query in (decimal, hexadecimal)
            item.setHidden(not visible)
            visible_count += int(visible)
        self.result_count.setText(f"{visible_count} 条")
        enabled = visible_count > 1
        self.previous_record_button.setEnabled(enabled)
        self.next_record_button.setEnabled(enabled)

    def _select_relative(self, direction: int) -> None:
        if not self.records.count():
            return
        start = self.records.currentRow()
        if start < 0:
            start = 0 if direction > 0 else self.records.count() - 1
        for step in range(1, self.records.count() + 1):
            row = (start + direction * step) % self.records.count()
            if not self.records.item(row).isHidden():
                self.records.setCurrentRow(row)
                self.records.scrollToItem(self.records.item(row))
                return

    def _selection_changed(
        self,
        current: QListWidgetItem | None,
        previous: QListWidgetItem | None,
    ) -> None:
        next_id = (
            int(current.data(Qt.ItemDataRole.UserRole)) if current is not None else None
        )
        if (
            previous is not None
            and self.current_id is not None
            and next_id is not None
            and next_id != self.current_id
            and self.has_pending_draft
        ):
            # The legacy editor keeps edits while moving between records. Apply
            # them to the dialog's transactional ROM buffer before switching;
            # Cancel on the outer dialog still rolls the whole session back.
            target_id = next_id
            old_id = self.current_id
            self.records.blockSignals(True)
            for row in range(self.records.count()):
                if int(self.records.item(row).data(Qt.ItemDataRole.UserRole)) == old_id:
                    self.records.setCurrentRow(row)
                    break
            self.records.blockSignals(False)
            if not self.commit_pending_changes():
                self.show_error(
                    ValueError(
                        self.pending_draft_error
                        or "当前记录仍有无法应用的改动，请修正后再切换。"
                    )
                )
                return
            for row in range(self.records.count()):
                if int(self.records.item(row).data(Qt.ItemDataRole.UserRole)) == target_id:
                    self.records.setCurrentRow(row)
                    return
            return
        self.current_id = next_id
        self.load_record(self.current_id)

    def load_record(self, record_id: int | None) -> None:
        pass


class UnitPage(SearchableRecordPage):
    def __init__(self) -> None:
        super().__init__()
        outer = QVBoxLayout(self)
        title, subtitle = page_title(
            "机体编辑",
            "编辑已确认的能力字段；共享记录会同时影响所有引用该记录的机体ID。",
        )
        outer.addWidget(title)
        outer.addWidget(subtitle)

        splitter = QSplitter()
        left = QWidget()
        left_layout = QVBoxLayout(left)
        left_layout.setContentsMargins(0, 0, 0, 0)
        left_layout.addWidget(self.records)
        left_layout.addWidget(self.search_panel)
        splitter.addWidget(left)

        detail = QWidget()
        detail_layout = QVBoxLayout(detail)
        self.record_heading = QLabel("请选择机体")
        self.record_heading.setObjectName("sectionTitle")
        self.record_meta = QLabel("—")
        self.record_meta.setObjectName("hintText")
        self.record_meta.setWordWrap(True)
        detail_layout.addWidget(self.record_heading)
        detail_layout.addWidget(self.record_meta)
        self.pending_state = QLabel("请选择机体")
        self.pending_state.setObjectName("pendingBanner")
        detail_layout.addWidget(self.pending_state)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        form_host = QWidget()
        form_root = QVBoxLayout(form_host)
        identity = QGroupBox("身份与装备")
        identity_form = QFormLayout(identity)
        self.name_reference = QComboBox()
        self.name_reference.setMaxVisibleItems(20)
        self.name_reference.currentIndexChanged.connect(self._update_pending_state)
        identity_form.addRow("名称引用", self.name_reference)
        self.name_text = QLineEdit()
        self.name_text.setPlaceholderText("在当前名称原槽容量内直接修改")
        self.name_text.textChanged.connect(self._update_pending_state)
        identity_form.addRow("直接修改名称", self.name_text)
        self.weapon_slots = (QComboBox(), QComboBox())
        for slot, editor in enumerate(self.weapon_slots, 1):
            editor.setMaxVisibleItems(24)
            editor.currentIndexChanged.connect(self._update_pending_state)
            identity_form.addRow(f"武器槽 {slot}", editor)
        form_root.addWidget(identity)

        capability = QGroupBox("能力参数")
        field_grid = QGridLayout(capability)
        field_grid.addWidget(QLabel("字段"), 0, 0)
        field_grid.addWidget(QLabel("当前编辑值"), 0, 1)
        field_grid.addWidget(QLabel("基准ROM"), 0, 2)
        self.fields: dict[str, QSpinBox] = {}
        self.original_values: dict[str, QLabel] = {}
        for row, field in enumerate(UNIT_FIELDS, 1):
            editor = QSpinBox()
            editor.setRange(field.minimum, field.maximum)
            editor.setToolTip(field.description)
            editor.valueChanged.connect(self._update_pending_state)
            self.fields[field.key] = editor
            original = QLabel("—")
            original.setObjectName("originalValue")
            original.setToolTip("载入基准 ROM 时的值")
            self.original_values[field.key] = original
            field_grid.addWidget(QLabel(field.label), row, 0)
            field_grid.addWidget(editor, row, 1)
            field_grid.addWidget(original, row, 2)
        field_grid.setColumnStretch(1, 1)
        form_root.addWidget(capability)
        form_root.addStretch()
        scroll.setWidget(form_host)
        detail_layout.addWidget(scroll, 1)

        buttons = QHBoxLayout()
        self.apply_button = QPushButton("应用当前表单")
        self.apply_button.setObjectName("primaryButton")
        self.apply_button.clicked.connect(self.apply_record)
        duplicate_button = QPushButton("复制到其他ID…")
        duplicate_button.setToolTip("复制数值、名称引用和两格武器配置")
        duplicate_button.clicked.connect(self.duplicate_record)
        reset_button = QPushButton("还原此机体")
        reset_button.clicked.connect(self.reset_record)
        buttons.addWidget(self.apply_button)
        buttons.addWidget(duplicate_button)
        buttons.addWidget(reset_button)
        buttons.addStretch()
        detail_layout.addLayout(buttons)

        advanced = QGroupBox("高级：16字节原始记录")
        advanced_layout = QHBoxLayout(advanced)
        self.raw_record = QLineEdit()
        self.raw_record.setPlaceholderText("00 00 …（共16字节）")
        raw_button = QPushButton("写入原始记录")
        raw_button.clicked.connect(self.apply_raw_record)
        advanced_layout.addWidget(self.raw_record, 1)
        advanced_layout.addWidget(raw_button)
        detail_layout.addWidget(advanced)

        splitter.addWidget(detail)
        splitter.setStretchFactor(0, 0)
        splitter.setStretchFactor(1, 1)
        splitter.setSizes([310, 760])
        outer.addWidget(splitter, 1)

    def record_ids(self) -> range:
        assert self.project is not None
        return range(1, self.project.unit_count)

    def supports_record_export(self) -> bool:
        return True

    def record_export_label(self) -> str:
        return "导出当前 .dcunit…"

    def export_selected_record(self) -> None:
        if self.project is None or self.current_id is None:
            return
        filename, _ = QFileDialog.getSaveFileName(
            self,
            "导出当前机体数据包",
            str(default_export_path(f"unit_{self.current_id:02X}.dcunit")),
            "新DC机体数据包 (*.dcunit)",
        )
        if not filename:
            return
        try:
            if not self.commit_pending_changes():
                return
            from .unit_packages import package_from_project

            destination = Path(filename).with_suffix(".dcunit")
            package_from_project(self.project, self.current_id).save(
                writable_output_path(destination)
            )
            self.records.setToolTip(f"已导出机体 ${self.current_id:02X}。")
        except Exception as error:
            self.show_error(error)

    def record_text(self, record_id: int) -> str:
        assert self.project is not None
        return f"${record_id:02X}  {self.project.unit_display_name(record_id)}"

    def refresh(self) -> None:
        self.name_reference.blockSignals(True)
        self.name_reference.clear()
        if self.project is not None:
            for source_id, pointer, label, source_ids in self.project.unit_name_reference_options():
                shared = compact_ids(source_ids)
                self.name_reference.addItem(
                    f"{label} · 来源 ${source_id:02X} · 指针 ${pointer:04X} · 共享ID {shared}",
                    source_id,
                )
        self.name_reference.blockSignals(False)
        for editor in self.weapon_slots:
            editor.blockSignals(True)
            editor.clear()
            if self.project is not None and self.project.supports_unit_weapons:
                editor.addItem("$00 · 无武器", 0)
                for weapon_id in range(1, self.project.weapon_count):
                    editor.addItem(
                        f"${weapon_id:02X} · {self.project.weapon_display_name(weapon_id)}",
                        weapon_id,
                    )
                editor.setEnabled(True)
            else:
                editor.addItem("当前ROM无已验证关系表", 0)
                editor.setEnabled(False)
            editor.blockSignals(False)
        self.populate_records()

    def load_record(self, record_id: int | None) -> None:
        if self.project is None or record_id is None:
            self.record_heading.setText("请选择机体")
            self.record_meta.setText("—")
            self.raw_record.clear()
            self.pending_state.setText("请选择机体")
            return
        record = self.project.unit_codec.decode_record(record_id, bytes(self.project.working))
        self.record_heading.setText(f"机体 ${record_id:02X} · {self.project.unit_display_name(record_id)}")
        shared = compact_ids(record.ids)
        name_pointer = self.project.get_unit_name_pointer(record_id)
        name_ids = self.project.unit_name_source_ids(record_id)
        self.record_meta.setText(
            f"记录指针 ${record.pointer:04X} · 文件偏移 0x{self.project.record_file_offset(record_id):06X}"
            f" · 属性共享ID：{shared} · 名称指针 ${name_pointer:04X}"
            f" · 名称共享ID：{compact_ids(name_ids)}"
        )
        for field in UNIT_FIELDS:
            spec = self.project.unit_field(field.key)
            editor = self.fields[field.key]
            editor.setRange(spec.minimum, spec.maximum)
            editor.setValue(record.get(field.key))
            base_value = self.project.get_value(record_id, field.key, original=True)
            self.original_values[field.key].setText(str(base_value))
            self.original_values[field.key].setStyleSheet(
                "color: #b05a00; font-weight: 650;"
                if record.get(field.key) != base_value
                else "color: #6c8292;"
            )
        source_ids = self.project.unit_name_source_ids(record_id)
        if source_ids:
            index = self.name_reference.findData(source_ids[0])
            self.name_reference.setCurrentIndex(index)
        self.name_text.setText(self.project.unit_display_name(record_id))
        if self.project.supports_unit_weapons:
            for editor, weapon_id in zip(
                self.weapon_slots, self.project.get_unit_weapons(record_id)
            ):
                editor.setCurrentIndex(editor.findData(weapon_id))
        self.raw_record.setText(record.raw.hex(" ").upper())
        self._update_pending_state()

    def _update_pending_state(self) -> None:
        if self.project is None or self.current_id is None:
            self.pending_state.setText("请选择机体")
            return
        pending = any(
            self.fields[field.key].value()
            != self.project.get_value(self.current_id, field.key)
            for field in UNIT_FIELDS
        )
        source_ids = self.project.unit_name_source_ids(self.current_id)
        if source_ids and self.name_reference.currentData() is not None:
            pending = pending or int(self.name_reference.currentData()) != source_ids[0]
        pending = pending or self.name_text.text().strip() != self.project.unit_display_name(
            self.current_id
        )
        if self.project.supports_unit_weapons:
            pending = pending or tuple(
                int(editor.currentData()) for editor in self.weapon_slots
            ) != self.project.get_unit_weapons(self.current_id)
        self.apply_button.setEnabled(pending)
        self.pending_state.setText(
            "● 有尚未应用的表单改动" if pending else "✓ 表单与当前工程一致"
        )
        self.pending_state.setStyleSheet(
            "color: #b45309; font-weight: 650;" if pending else "color: #2e7d4f;"
        )

    def duplicate_record(self) -> None:
        if self.project is None or self.current_id is None:
            return
        options = [
            f"${unit_id:02X} · {self.project.unit_display_name(unit_id)}"
            for unit_id in range(1, self.project.unit_count)
            if unit_id != self.current_id
        ]
        selected, accepted = QInputDialog.getItem(
            self,
            "复制机体",
            f"将 ${self.current_id:02X} 的数值、名称和武器复制到：",
            options,
            0,
            False,
        )
        if not accepted:
            return
        target_id = int(selected[1:3], 16)
        self.copy_record_to(self.current_id, target_id)

    def copy_record_to(self, source_id: int, target_id: int) -> bool:
        if self.project is None or source_id == target_id:
            return False
        try:
            affected = self.project.unit_codec.decode_record(
                target_id, bytes(self.project.working)
            ).ids
            if len(affected) > 1:
                answer = QMessageBox.question(
                    self,
                    "共享机体记录确认",
                    f"目标 ${target_id:02X} 的16字节属性记录由 "
                    f"{compact_ids(affected)} 共用。\n"
                    "复制后这些ID的属性都会改变；名称和武器仅修改目标ID。是否继续？",
                    QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel,
                    QMessageBox.StandardButton.Cancel,
                )
                if answer != QMessageBox.StandardButton.Yes:
                    return False
            name_ids = self.project.unit_name_source_ids(source_id)
            with self.project.transaction(
                f"复制机体 ${source_id:02X} 到 ${target_id:02X}"
            ):
                self.project.set_record_hex(
                    target_id, self.project.record_bytes(source_id).hex(" ")
                )
                if name_ids:
                    self.project.set_unit_name_reference(target_id, name_ids[0])
                if self.project.supports_unit_weapons:
                    for slot, weapon_id in enumerate(
                        self.project.get_unit_weapons(source_id)
                    ):
                        self.project.set_unit_weapon(target_id, slot, weapon_id)
            self.project_changed.emit(
                f"已复制机体 ${source_id:02X} 到 ${target_id:02X}"
            )
            return True
        except Exception as error:
            self.show_error(error)
            return False

    def apply_record(self) -> None:
        if self.project is None or self.current_id is None:
            return
        try:
            current_name = self.project.unit_display_name(self.current_id)
            edited_name = self.name_text.text().strip()
            name_changed = edited_name != current_name
            if name_changed and not self.confirm_shared_name_edit(
                "机体", self.project.unit_name_source_ids(self.current_id)
            ):
                return
            with self.project.transaction(f"机体 ${self.current_id:02X} · 批量属性"):
                for field in UNIT_FIELDS:
                    self.project.set_value(
                        self.current_id,
                        field.key,
                        self.fields[field.key].value(),
                    )
                source_id = int(self.name_reference.currentData())
                self.project.set_unit_name_reference(self.current_id, source_id)
                if name_changed:
                    self.project.set_unit_name_text(self.current_id, edited_name)
                if self.project.supports_unit_weapons:
                    for slot, editor in enumerate(self.weapon_slots):
                        self.project.set_unit_weapon(
                            self.current_id, slot, int(editor.currentData())
                        )
            self.project_changed.emit(f"已更新机体 ${self.current_id:02X}")
        except Exception as error:
            self.show_error(error)

    def apply_raw_record(self) -> None:
        if self.project is None or self.current_id is None:
            return
        answer = QMessageBox.question(
            self,
            "确认高级修改",
            "原始记录包含尚未确认的标志位。确定写入这16字节吗？",
        )
        if answer != QMessageBox.StandardButton.Yes:
            return
        try:
            self.project.set_record_hex(self.current_id, self.raw_record.text())
            self.project_changed.emit(f"已写入机体 ${self.current_id:02X} 原始记录")
        except Exception as error:
            self.show_error(error)

    def reset_record(self) -> None:
        if self.project is None or self.current_id is None:
            return
        try:
            with self.project.transaction(f"机体 ${self.current_id:02X} · 完整还原"):
                self.project.reset_record(self.current_id)
                self.project.reset_unit_name(self.current_id)
                if self.project.supports_unit_weapons:
                    self.project.reset_unit_weapons(self.current_id)
            self.project_changed.emit(f"已还原机体 ${self.current_id:02X}")
        except Exception as error:
            self.show_error(error)


class CharacterPage(SearchableRecordPage):
    """Edit verified character-name references and per-character battle themes."""

    def __init__(self) -> None:
        super().__init__()
        outer = QVBoxLayout(self)
        title, subtitle = page_title(
            "人物编辑",
            "编辑ROM中的真实战斗名称引用，以及人物作为我方/敌方时使用的战斗音乐。",
        )
        outer.addWidget(title)
        outer.addWidget(subtitle)

        splitter = QSplitter()
        left = QWidget()
        left_layout = QVBoxLayout(left)
        left_layout.setContentsMargins(0, 0, 0, 0)
        left_layout.addWidget(self.records)
        left_layout.addWidget(self.search_panel)
        splitter.addWidget(left)

        detail = QWidget()
        detail_layout = QVBoxLayout(detail)
        self.record_heading = QLabel("请选择人物")
        self.record_heading.setObjectName("sectionTitle")
        self.record_meta = QLabel("—")
        self.record_meta.setObjectName("hintText")
        self.record_meta.setWordWrap(True)
        detail_layout.addWidget(self.record_heading)
        detail_layout.addWidget(self.record_meta)
        self.pending_state = QLabel("请选择人物")
        self.pending_state.setObjectName("editState")
        detail_layout.addWidget(self.pending_state)

        identity = QGroupBox("名称")
        identity_form = QFormLayout(identity)
        self.name_reference = QComboBox()
        self.name_reference.setMaxVisibleItems(24)
        self.name_reference.currentIndexChanged.connect(self._update_pending_state)
        identity_form.addRow("名称引用", self.name_reference)
        self.name_text = QLineEdit()
        self.name_text.setPlaceholderText("在当前名称原槽容量内直接修改")
        self.name_text.textChanged.connect(self._update_pending_state)
        identity_form.addRow("直接修改名称", self.name_text)
        self.name_tokens = QLineEdit()
        self.name_tokens.setReadOnly(True)
        identity_form.addRow("名称Token", self.name_tokens)
        self.original_name = QLabel("基准ROM：—")
        self.original_name.setObjectName("hintText")
        identity_form.addRow("原始名称", self.original_name)
        detail_layout.addWidget(identity)

        music = QGroupBox("人物战斗音乐")
        music_form = QFormLayout(music)
        self.ally_music = QComboBox()
        self.enemy_music = QComboBox()
        self.ally_music.currentIndexChanged.connect(self._update_pending_state)
        self.enemy_music.currentIndexChanged.connect(self._update_pending_state)
        music_form.addRow("我方主动攻击曲", self.ally_music)
        music_form.addRow("敌方/被攻击曲", self.enemy_music)
        self.original_music = QLabel("基准ROM：—")
        self.original_music.setObjectName("hintText")
        self.original_music.setWordWrap(True)
        music_form.addRow("原始绑定", self.original_music)
        detail_layout.addWidget(music)

        scope = QLabel(
            "当前人物属性表、头像索引、精神与战斗台词关系尚未完成地址验证，"
            "本页不会猜测写入这些区域。"
        )
        scope.setObjectName("hintText")
        scope.setWordWrap(True)
        detail_layout.addWidget(scope)

        buttons = QHBoxLayout()
        self.apply_button = QPushButton("应用人物修改")
        self.apply_button.setObjectName("primaryButton")
        self.apply_button.clicked.connect(self.apply_record)
        self.apply_button.setEnabled(False)
        duplicate_button = QPushButton("复制到其他ID…")
        duplicate_button.clicked.connect(self.duplicate_record)
        reset_button = QPushButton("还原此人物")
        reset_button.clicked.connect(self.reset_record)
        buttons.addWidget(self.apply_button)
        buttons.addWidget(duplicate_button)
        buttons.addWidget(reset_button)
        buttons.addStretch()
        detail_layout.addLayout(buttons)
        detail_layout.addStretch()
        splitter.addWidget(detail)
        splitter.setSizes([360, 760])
        outer.addWidget(splitter, 1)

    def record_ids(self) -> range:
        assert self.project is not None
        return range(1, self.project.profile.character_name_count)

    def record_text(self, record_id: int) -> str:
        assert self.project is not None
        text = f"${record_id:02X}  {self.project.character_display_name(record_id)}"
        if (
            self.project.supports_battle_music
            and record_id < self.project.profile.battle_music.selector_count
        ):
            binding = self.project.get_battle_music_binding(record_id)
            text += f"  ·  BGM ${binding.attacker_command:02X}/${binding.defender_command:02X}"
        return text

    def refresh(self) -> None:
        self.name_reference.blockSignals(True)
        self.name_reference.clear()
        self.ally_music.blockSignals(True)
        self.enemy_music.blockSignals(True)
        self.ally_music.clear()
        self.enemy_music.clear()
        if self.project is not None:
            for source_id, pointer, label, source_ids in (
                self.project.character_name_reference_options()
            ):
                self.name_reference.addItem(
                    f"{label} · 来源 ${source_id:02X} · 指针 ${pointer:04X} · "
                    f"共享ID {compact_ids(source_ids)}",
                    source_id,
                )
            if self.project.battle_music_codec is not None:
                for track in self.project.battle_music_codec.tracks:
                    self.ally_music.addItem(track.display, track.command)
                    self.enemy_music.addItem(track.display, track.command)
        self.name_reference.blockSignals(False)
        self.ally_music.blockSignals(False)
        self.enemy_music.blockSignals(False)
        self.populate_records()

    def load_record(self, record_id: int | None) -> None:
        if self.project is None or record_id is None:
            self.record_heading.setText("请选择人物")
            self.record_meta.setText("—")
            self.name_text.clear()
            self.name_tokens.clear()
            self.original_name.setText("基准ROM：—")
            self.original_music.setText("基准ROM：—")
            self.apply_button.setEnabled(False)
            return
        name = self.project.character_display_name(record_id)
        pointer = self.project.get_character_name_pointer(record_id)
        source_ids = self.project.character_name_source_ids(record_id)
        self.record_heading.setText(f"人物 ${record_id:02X} · {name}")
        self.record_meta.setText(
            f"名称指针 ${pointer:04X} · 名称共享ID：{compact_ids(source_ids)} · "
            "人物ID同时作为战斗音乐选择器"
        )
        self.name_tokens.setText(
            self.project.character_name_record_bytes(record_id).hex(" ").upper()
        )
        self.name_text.setText(
            concise_dc_text(self.project.character_name_record_bytes(record_id))
        )
        if source_ids:
            self.name_reference.setCurrentIndex(
                self.name_reference.findData(source_ids[0])
            )
        original_sources = self.project.character_name_source_ids(
            record_id, original=True
        )
        original_name = (
            self.project.character_display_name(original_sources[0])
            if original_sources
            else "空白/未分配"
        )
        self.original_name.setText(
            f"基准ROM：{original_name} · 指针 "
            f"${self.project.get_character_name_pointer(record_id, original=True):04X}"
        )
        music_supported = (
            self.project.supports_battle_music
            and record_id < self.project.profile.battle_music.selector_count
        )
        self.ally_music.setEnabled(music_supported)
        self.enemy_music.setEnabled(music_supported)
        if music_supported:
            binding = self.project.get_battle_music_binding(record_id)
            original = self.project.get_battle_music_binding(record_id, original=True)
            self.ally_music.setCurrentIndex(
                self.ally_music.findData(binding.attacker_command)
            )
            self.enemy_music.setCurrentIndex(
                self.enemy_music.findData(binding.defender_command)
            )
            codec = self.project.battle_music_codec
            self.original_music.setText(
                "基准ROM：我方 "
                f"{codec.format_command(original.attacker_command)}；敌方 "
                f"{codec.format_command(original.defender_command)}"
            )
        else:
            self.original_music.setText("此人物ID没有已验证的音乐选择器。")
        self._update_pending_state()

    def _pending_values(self) -> tuple[bool, bool, bool]:
        if self.project is None or self.current_id is None:
            return False, False, False
        source_ids = self.project.character_name_source_ids(self.current_id)
        reference_pending = bool(
            source_ids
            and self.name_reference.currentData() is not None
            and int(self.name_reference.currentData()) != source_ids[0]
        )
        text_pending = self.name_text.text().strip() != concise_dc_text(
            self.project.character_name_record_bytes(self.current_id)
        )
        music_pending = False
        if self.ally_music.isEnabled() and self.ally_music.currentData() is not None:
            binding = self.project.get_battle_music_binding(self.current_id)
            music_pending = (
                int(self.ally_music.currentData()) != binding.attacker_command
                or int(self.enemy_music.currentData()) != binding.defender_command
            )
        return reference_pending, text_pending, music_pending

    def _update_pending_state(self) -> None:
        reference_pending, text_pending, music_pending = self._pending_values()
        pending = reference_pending or text_pending or music_pending
        self.apply_button.setEnabled(pending)
        if self.project is None or self.current_id is None:
            self.pending_state.setText("请选择人物")
        elif pending:
            parts = []
            if reference_pending:
                parts.append("名称引用")
            if text_pending:
                parts.append("名称文字")
            if music_pending:
                parts.append("音乐")
            self.pending_state.setText("● 尚未应用：" + "、".join(parts))
        else:
            self.pending_state.setText("✓ 表单与当前工程一致")
        self.pending_state.setProperty("pending", pending)
        self.pending_state.style().unpolish(self.pending_state)
        self.pending_state.style().polish(self.pending_state)

    def apply_record(self) -> None:
        if self.project is None or self.current_id is None:
            return
        try:
            reference_pending, text_pending, _music_pending = self._pending_values()
            if reference_pending and text_pending:
                raise ValueError("名称引用和名称文字不能同时修改；请先应用其中一项。")
            if text_pending and not self.confirm_shared_name_edit(
                "人物", self.project.character_name_source_ids(self.current_id)
            ):
                return
            with self.project.transaction(f"人物 ${self.current_id:02X} · 名称与音乐"):
                self.project.set_character_name_reference(
                    self.current_id, int(self.name_reference.currentData())
                )
                if text_pending:
                    self.project.set_character_name_text(
                        self.current_id, self.name_text.text()
                    )
                if self.ally_music.isEnabled():
                    self.project.set_battle_music_binding(
                        self.current_id,
                        int(self.ally_music.currentData()),
                        int(self.enemy_music.currentData()),
                    )
            self.project_changed.emit(f"已更新人物 ${self.current_id:02X}")
        except Exception as error:
            self.show_error(error)

    def duplicate_record(self) -> None:
        if self.project is None or self.current_id is None:
            return
        options = [
            f"${character_id:02X} · {self.project.character_display_name(character_id)}"
            for character_id in self.record_ids()
            if character_id != self.current_id
        ]
        selected, accepted = QInputDialog.getItem(
            self,
            "复制人物",
            f"把 ${self.current_id:02X} 的名称和战斗音乐复制到：",
            options,
            0,
            False,
        )
        if not accepted:
            return
        target_id = int(selected[1:3], 16)
        self.copy_record_to(self.current_id, target_id)

    def copy_record_to(self, source_id: int, target_id: int) -> bool:
        if self.project is None or source_id == target_id:
            return False
        try:
            source_ids = self.project.character_name_source_ids(source_id)
            with self.project.transaction(
                f"复制人物 ${source_id:02X} 到 ${target_id:02X}"
            ):
                if source_ids:
                    self.project.set_character_name_reference(target_id, source_ids[0])
                if (
                    self.project.supports_battle_music
                    and target_id < self.project.profile.battle_music.selector_count
                ):
                    binding = self.project.get_battle_music_binding(source_id)
                    self.project.set_battle_music_binding(
                        target_id,
                        binding.attacker_command,
                        binding.defender_command,
                    )
            self.project_changed.emit(
                f"已复制人物 ${source_id:02X} 到 ${target_id:02X}"
            )
            return True
        except Exception as error:
            self.show_error(error)
            return False

    def reset_record(self) -> None:
        if self.project is None or self.current_id is None:
            return
        try:
            with self.project.transaction(f"人物 ${self.current_id:02X} · 完整还原"):
                self.project.reset_character_name(self.current_id)
                if (
                    self.project.supports_battle_music
                    and self.current_id < self.project.profile.battle_music.selector_count
                ):
                    self.project.reset_battle_music_binding(self.current_id)
            self.project_changed.emit(f"已还原人物 ${self.current_id:02X}")
        except Exception as error:
            self.show_error(error)


class WeaponPage(SearchableRecordPage):
    def __init__(self) -> None:
        super().__init__()
        outer = QVBoxLayout(self)
        title, subtitle = page_title(
            "武器编辑",
            "显示并切换ROM中的真实武器名称，编辑射程、命中及三种地形攻击力。未确认位保持原值。",
        )
        outer.addWidget(title)
        outer.addWidget(subtitle)
        splitter = QSplitter()
        left = QWidget()
        left_layout = QVBoxLayout(left)
        left_layout.setContentsMargins(0, 0, 0, 0)
        left_layout.addWidget(self.records)
        left_layout.addWidget(self.search_panel)
        splitter.addWidget(left)

        detail = QWidget()
        detail_layout = QVBoxLayout(detail)
        self.record_heading = QLabel("请选择武器")
        self.record_heading.setObjectName("sectionTitle")
        self.record_meta = QLabel("—")
        self.record_meta.setObjectName("hintText")
        detail_layout.addWidget(self.record_heading)
        detail_layout.addWidget(self.record_meta)
        self.pending_state = QLabel("请选择武器")
        self.pending_state.setObjectName("pendingBanner")
        detail_layout.addWidget(self.pending_state)
        identity = QGroupBox("名称与记录")
        form = QFormLayout(identity)
        self.name_reference = QComboBox()
        self.name_reference.setMaxVisibleItems(24)
        self.name_reference.currentIndexChanged.connect(self._update_pending_state)
        form.addRow("名称引用", self.name_reference)
        self.name_text = QLineEdit()
        self.name_text.setPlaceholderText("在当前名称原槽容量内直接修改")
        self.name_text.textChanged.connect(self._update_pending_state)
        form.addRow("直接修改名称", self.name_text)
        self.name_tokens = QLineEdit()
        self.name_tokens.setReadOnly(True)
        form.addRow("名称Token", self.name_tokens)
        self.raw_record = QLineEdit()
        self.raw_record.setReadOnly(True)
        form.addRow("原始6字节", self.raw_record)
        detail_layout.addWidget(identity)
        attributes = QGroupBox("战斗参数")
        field_grid = QGridLayout(attributes)
        field_grid.addWidget(QLabel("字段"), 0, 0)
        field_grid.addWidget(QLabel("当前编辑值"), 0, 1)
        field_grid.addWidget(QLabel("基准ROM"), 0, 2)
        self.fields: dict[str, QSpinBox] = {}
        self.original_values: dict[str, QLabel] = {}
        for row, field in enumerate(WEAPON_FIELDS, 1):
            editor = QSpinBox()
            editor.setRange(field.minimum, field.maximum)
            editor.setToolTip(field.description)
            editor.valueChanged.connect(self._update_pending_state)
            self.fields[field.key] = editor
            original = QLabel("—")
            original.setObjectName("originalValue")
            self.original_values[field.key] = original
            field_grid.addWidget(QLabel(field.label), row, 0)
            field_grid.addWidget(editor, row, 1)
            field_grid.addWidget(original, row, 2)
        field_grid.setColumnStretch(1, 1)
        detail_layout.addWidget(attributes)
        buttons = QHBoxLayout()
        self.apply_button = QPushButton("应用当前表单")
        self.apply_button.setObjectName("primaryButton")
        self.apply_button.clicked.connect(self.apply_record)
        duplicate_button = QPushButton("复制到其他ID…")
        duplicate_button.clicked.connect(self.duplicate_record)
        reset_button = QPushButton("还原此武器")
        reset_button.clicked.connect(self.reset_record)
        buttons.addWidget(self.apply_button)
        buttons.addWidget(duplicate_button)
        buttons.addWidget(reset_button)
        buttons.addStretch()
        detail_layout.addLayout(buttons)
        detail_layout.addStretch()
        splitter.addWidget(detail)
        splitter.setSizes([310, 760])
        outer.addWidget(splitter, 1)

    def record_ids(self) -> range:
        assert self.project is not None
        return range(1, self.project.weapon_count)

    def record_text(self, record_id: int) -> str:
        assert self.project is not None
        return f"${record_id:02X}  {self.project.weapon_display_name(record_id)}"

    def refresh(self) -> None:
        self.name_reference.blockSignals(True)
        self.name_reference.clear()
        if self.project is not None:
            for source_id, pointer, label, source_ids in self.project.weapon_name_reference_options():
                self.name_reference.addItem(
                    f"{label} · 来源 ${source_id:02X} · 指针 ${pointer:04X} · 共享ID {compact_ids(source_ids)}",
                    source_id,
                )
        self.name_reference.setEnabled(bool(self.name_reference.count()))
        self.name_reference.blockSignals(False)
        self.populate_records()

    def load_record(self, record_id: int | None) -> None:
        if self.project is None or record_id is None:
            self.record_heading.setText("请选择武器")
            self.record_meta.setText("—")
            self.name_text.clear()
            self.raw_record.clear()
            self.name_tokens.clear()
            self.pending_state.setText("请选择武器")
            return
        record = self.project.weapon_codec.decode_record(record_id, bytes(self.project.working))
        name = self.project.weapon_display_name(record_id)
        self.record_heading.setText(f"武器 ${record_id:02X} · {name}")
        metadata = (
            f"属性指针 ${record.pointer:04X} · 文件偏移 "
            f"0x{self.project.weapon_record_file_offset(record_id):06X}"
        )
        if self.project.supports_weapon_names:
            name_pointer = self.project.get_weapon_name_pointer(record_id)
            source_ids = self.project.weapon_name_source_ids(record_id)
            metadata += (
                f" · 名称指针 ${name_pointer:04X} · 名称共享ID："
                f"{compact_ids(source_ids)}"
            )
            if source_ids:
                self.name_reference.setCurrentIndex(
                    self.name_reference.findData(source_ids[0])
                )
            self.name_tokens.setText(
                self.project.weapon_name_record_bytes(record_id).hex(" ").upper()
            )
            self.name_text.setText(
                concise_dc_text(self.project.weapon_name_record_bytes(record_id))
            )
        else:
            metadata += " · 此ROM配置未验证名称表"
            self.name_tokens.clear()
        self.record_meta.setText(metadata)
        for field in WEAPON_FIELDS:
            self.fields[field.key].setValue(record.get(field.key))
            base_value = self.project.get_weapon_value(
                record_id, field.key, original=True
            )
            self.original_values[field.key].setText(str(base_value))
            self.original_values[field.key].setStyleSheet(
                "color: #b05a00; font-weight: 650;"
                if record.get(field.key) != base_value
                else "color: #6c8292;"
            )
        self.raw_record.setText(record.raw.hex(" ").upper())
        self._update_pending_state()

    def _update_pending_state(self) -> None:
        if self.project is None or self.current_id is None:
            self.pending_state.setText("请选择武器")
            return
        pending = any(
            self.fields[field.key].value()
            != self.project.get_weapon_value(self.current_id, field.key)
            for field in WEAPON_FIELDS
        )
        if self.project.supports_weapon_names:
            source_ids = self.project.weapon_name_source_ids(self.current_id)
            if source_ids and self.name_reference.currentData() is not None:
                pending = pending or int(self.name_reference.currentData()) != source_ids[0]
            pending = pending or self.name_text.text().strip() != concise_dc_text(
                self.project.weapon_name_record_bytes(self.current_id)
            )
        self.apply_button.setEnabled(pending)
        self.pending_state.setText(
            "● 有尚未应用的表单改动" if pending else "✓ 表单与当前工程一致"
        )
        self.pending_state.setStyleSheet(
            "color: #b45309; font-weight: 650;" if pending else "color: #2e7d4f;"
        )

    def duplicate_record(self) -> None:
        if self.project is None or self.current_id is None:
            return
        options = [
            f"${weapon_id:02X} · {self.project.weapon_display_name(weapon_id)}"
            for weapon_id in range(1, self.project.weapon_count)
            if weapon_id != self.current_id
        ]
        selected, accepted = QInputDialog.getItem(
            self,
            "复制武器",
            f"将 ${self.current_id:02X} 的属性和名称复制到：",
            options,
            0,
            False,
        )
        if not accepted:
            return
        target_id = int(selected[1:3], 16)
        self.copy_record_to(self.current_id, target_id)

    def copy_record_to(self, source_id: int, target_id: int) -> bool:
        if self.project is None or source_id == target_id:
            return False
        try:
            target_pointer = self.project.weapon_codec.pointers[target_id]
            affected = tuple(
                weapon_id
                for weapon_id in range(1, self.project.weapon_count)
                if self.project.weapon_codec.pointers[weapon_id] == target_pointer
            )
            if len(affected) > 1:
                answer = QMessageBox.question(
                    self,
                    "共享武器记录确认",
                    f"目标 ${target_id:02X} 的6字节属性记录由 "
                    f"{compact_ids(affected)} 共用。\n"
                    "复制后这些ID的属性都会改变；名称仅修改目标ID。是否继续？",
                    QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel,
                    QMessageBox.StandardButton.Cancel,
                )
                if answer != QMessageBox.StandardButton.Yes:
                    return False
            name_ids = self.project.weapon_name_source_ids(source_id)
            with self.project.transaction(
                f"复制武器 ${source_id:02X} 到 ${target_id:02X}"
            ):
                for field in WEAPON_FIELDS:
                    self.project.set_weapon_value(
                        target_id,
                        field.key,
                        self.project.get_weapon_value(source_id, field.key),
                    )
                if name_ids:
                    self.project.set_weapon_name_reference(target_id, name_ids[0])
            self.project_changed.emit(
                f"已复制武器 ${source_id:02X} 到 ${target_id:02X}"
            )
            return True
        except Exception as error:
            self.show_error(error)
            return False

    def apply_record(self) -> None:
        if self.project is None or self.current_id is None:
            return
        try:
            name_sources = (
                self.project.weapon_name_source_ids(self.current_id)
                if self.project.supports_weapon_names
                else ()
            )
            reference_pending = bool(
                name_sources
                and self.name_reference.currentData() is not None
                and int(self.name_reference.currentData()) != name_sources[0]
            )
            text_pending = bool(
                self.project.supports_weapon_names
                and self.name_text.text().strip()
                != concise_dc_text(self.project.weapon_name_record_bytes(self.current_id))
            )
            if reference_pending and text_pending:
                raise ValueError("名称引用和名称文字不能同时修改；请先应用其中一项。")
            if text_pending and not self.confirm_shared_name_edit("武器", name_sources):
                return
            with self.project.transaction(f"武器 ${self.current_id:02X} · 属性与名称"):
                for field in WEAPON_FIELDS:
                    self.project.set_weapon_value(
                        self.current_id,
                        field.key,
                        self.fields[field.key].value(),
                    )
                if self.project.supports_weapon_names:
                    self.project.set_weapon_name_reference(
                        self.current_id, int(self.name_reference.currentData())
                    )
                    if text_pending:
                        self.project.set_weapon_name_text(
                            self.current_id, self.name_text.text()
                        )
            self.project_changed.emit(f"已更新武器 ${self.current_id:02X}")
        except Exception as error:
            self.show_error(error)

    def reset_record(self) -> None:
        if self.project is None or self.current_id is None:
            return
        try:
            with self.project.transaction(f"武器 ${self.current_id:02X} · 完整还原"):
                self.project.reset_weapon_record(self.current_id)
                if self.project.supports_weapon_names:
                    self.project.reset_weapon_name(self.current_id)
            self.project_changed.emit(f"已还原武器 ${self.current_id:02X}")
        except Exception as error:
            self.show_error(error)


class MusicPage(SearchableRecordPage):
    def __init__(self) -> None:
        super().__init__()
        outer = QVBoxLayout(self)
        title, subtitle = page_title(
            "战斗背景音乐",
            "分别设置主动攻击和被攻击时的曲目。当前支持原版20首及三首FamiStudio新曲。",
        )
        outer.addWidget(title)
        outer.addWidget(subtitle)
        splitter = QSplitter()
        left = QWidget()
        left_layout = QVBoxLayout(left)
        left_layout.setContentsMargins(0, 0, 0, 0)
        left_layout.addWidget(self.records)
        left_layout.addWidget(self.search_panel)
        splitter.addWidget(left)
        detail = QWidget()
        detail_layout = QVBoxLayout(detail)
        self.record_heading = QLabel("请选择音乐选择器")
        self.record_heading.setObjectName("sectionTitle")
        detail_layout.addWidget(self.record_heading)
        self.binding_help = QLabel(
            "分配战斗曲：选择已有曲目给人物使用，不会导入或替换音乐文件。\n"
            "要换成自己的曲子，请展开下方“替换扩展曲数据”。"
        )
        self.binding_help.setWordWrap(True)
        detail_layout.addWidget(self.binding_help)
        form = QFormLayout()
        self.attacker = QComboBox()
        self.defender = QComboBox()
        self.attacker.currentIndexChanged.connect(self._update_pending_state)
        self.defender.currentIndexChanged.connect(self._update_pending_state)
        form.addRow("主动攻击曲", self.attacker)
        form.addRow("被攻击曲", self.defender)
        detail_layout.addLayout(form)
        self.original_binding = QLabel("基准ROM：—")
        self.original_binding.setObjectName("hintText")
        detail_layout.addWidget(self.original_binding)
        self.pending_state = QLabel("选择记录后可编辑。")
        self.pending_state.setObjectName("editState")
        detail_layout.addWidget(self.pending_state)
        hint = QLabel("提示：$9D Ash to Ash、$9E Dark Knight、$9F Dark Prison。")
        hint.setObjectName("hintText")
        detail_layout.addWidget(hint)
        buttons = QHBoxLayout()
        self.apply_button = QPushButton("应用当前绑定")
        self.apply_button.setObjectName("primaryButton")
        self.apply_button.clicked.connect(self.apply_record)
        self.apply_button.setEnabled(False)
        reset_button = QPushButton("还原此绑定")
        reset_button.clicked.connect(self.reset_record)
        batch_button = QPushButton("应用到多个选择器…")
        batch_button.clicked.connect(self.apply_to_many)
        buttons.addWidget(self.apply_button)
        buttons.addWidget(reset_button)
        buttons.addWidget(batch_button)
        buttons.addStretch()
        detail_layout.addLayout(buttons)

        import_group = QGroupBox("替换曲槽内容（会影响所有使用该曲槽的人物）")
        import_layout = QVBoxLayout(import_group)
        slot_form = QFormLayout()
        self.music_slot = QComboBox()
        self.music_slot.currentIndexChanged.connect(self._refresh_music_slot)
        slot_form.addRow("目标曲槽", self.music_slot)
        import_layout.addLayout(slot_form)
        self.music_slot_status = QLabel("当前ROM不支持扩展曲导入。")
        self.music_slot_status.setObjectName("hintText")
        self.music_slot_status.setWordWrap(True)
        import_layout.addWidget(self.music_slot_status)
        import_buttons = QHBoxLayout()
        self.import_bin_button = QPushButton("导入 8 KiB Bank…")
        self.import_bin_button.clicked.connect(self.import_music_bank)
        self.import_asm_button = QPushButton("导入 FamiStudio ASM…")
        self.import_asm_button.clicked.connect(self.import_music_asm)
        self.export_bin_button = QPushButton("导出当前 Bank…")
        self.export_bin_button.clicked.connect(self.export_music_bank)
        self.reset_slot_button = QPushButton("还原曲槽")
        self.reset_slot_button.clicked.connect(self.reset_music_slot)
        import_buttons.addWidget(self.import_bin_button)
        import_buttons.addWidget(self.import_asm_button)
        import_buttons.addWidget(self.export_bin_button)
        import_buttons.addWidget(self.reset_slot_button)
        import_layout.addLayout(import_buttons)
        safety = QLabel(
            "ASM 导入仅接受自包含的 FamiStudio 数据导出；修改器会严格验证大小和指针。"
            "每个曲槽固定占用一个 Bank，音频引擎不会被覆盖。"
        )
        safety.setObjectName("hintText")
        safety.setWordWrap(True)
        import_layout.addWidget(safety)
        self.music_import_toggle = QToolButton()
        self.music_import_toggle.setText("替换扩展曲数据 / 导入自己的曲子")
        self.music_import_toggle.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        self.music_import_toggle.setCheckable(True)
        self.music_import_toggle.setArrowType(Qt.ArrowType.RightArrow)
        self.music_import_toggle.toggled.connect(import_group.setVisible)
        self.music_import_toggle.toggled.connect(lambda expanded: self.music_import_toggle.setArrowType(
            Qt.ArrowType.DownArrow if expanded else Qt.ArrowType.RightArrow
        ))
        detail_layout.addWidget(self.music_import_toggle)
        detail_layout.addWidget(import_group)
        import_group.hide()
        detail_layout.addStretch()
        splitter.addWidget(detail)
        splitter.setSizes([420, 650])
        outer.addWidget(splitter, 1)

    def record_ids(self) -> range:
        assert self.project is not None
        spec = self.project.profile.battle_music
        return range(spec.selector_count if spec is not None else 0)

    def record_text(self, record_id: int) -> str:
        assert self.project is not None
        binding = self.project.get_battle_music_binding(record_id)
        return (
            f"${record_id:02X}  {self.project.battle_music_selector_label(record_id)}  · "
            f"${binding.attacker_command:02X} / ${binding.defender_command:02X}"
        )

    def refresh(self) -> None:
        selected_slot = self.music_slot.currentData()
        self.attacker.clear()
        self.defender.clear()
        self.music_slot.blockSignals(True)
        self.music_slot.clear()
        if self.project is not None and self.project.battle_music_codec is not None:
            for track in self.project.battle_music_codec.tracks:
                self.attacker.addItem(track.display, track.command)
                self.defender.addItem(track.display, track.command)
        if self.project is not None and self.project.custom_music_codec is not None:
            for slot in self.project.custom_music_codec.slots:
                self.music_slot.addItem(
                    f"${slot.command:02X} · {slot.label} · PRG Bank ${slot.prg_bank:02X}",
                    slot.command,
                )
        restored = self.music_slot.findData(selected_slot)
        self.music_slot.setCurrentIndex(max(0, restored))
        self.music_slot.blockSignals(False)
        enabled = self.music_slot.count() > 0
        for widget in (
            self.music_slot,
            self.import_bin_button,
            self.import_asm_button,
            self.export_bin_button,
            self.reset_slot_button,
        ):
            widget.setEnabled(enabled)
        self._refresh_music_slot()
        self.populate_records()

    def _current_music_command(self) -> int | None:
        value = self.music_slot.currentData()
        return None if value is None else int(value)

    def _refresh_music_slot(self) -> None:
        command = self._current_music_command()
        if self.project is None or command is None or self.project.custom_music_codec is None:
            self.music_slot_status.setText("当前ROM不支持扩展曲导入。")
            return
        payload = self.project.custom_music_bank(command)
        count = self.project.custom_music_codec.validate_bank(payload)
        digest = self.project.custom_music_codec.sha256(command, self.project.working)
        state = "已修改" if payload != self.project.custom_music_bank(command, original=True) else "原始"
        self.music_slot_status.setText(
            f"状态：{state} · {count} 首数据 · 8192 字节 · SHA-256 {digest[:16]}…"
        )

    def _confirm_replace(self, source_name: str) -> bool:
        command = self._current_music_command()
        if command is None:
            return False
        answer = QMessageBox.question(
            self,
            "替换扩展曲槽",
            f"将用“{source_name}”完整替换曲槽 ${command:02X} 的 8192 字节数据。\n"
            "此操作可通过撤销恢复，是否继续？",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel,
            QMessageBox.StandardButton.Cancel,
        )
        return answer == QMessageBox.StandardButton.Yes

    def _apply_music_payload(self, payload: bytes, source_name: str) -> None:
        if self.project is None:
            return
        command = self._current_music_command()
        if command is None or not self._confirm_replace(source_name):
            return
        self.project.set_custom_music_bank(command, payload)
        self.project_changed.emit(f"已替换扩展曲槽 ${command:02X} · {source_name}")

    def import_music_bank(self) -> None:
        if self.project is None:
            return
        filename, _ = QFileDialog.getOpenFileName(
            self,
            "导入 FamiStudio 音乐 Bank",
            str(self.project.path.parent),
            "8 KiB Bank (*.bin);;所有文件 (*)",
        )
        if not filename:
            return
        try:
            self._apply_music_payload(load_music_bank(filename), Path(filename).name)
        except Exception as error:
            self.show_error(error)

    def import_music_asm(self) -> None:
        if self.project is None:
            return
        filename, _ = QFileDialog.getOpenFileName(
            self,
            "导入 FamiStudio ASM6 数据导出",
            str(self.project.path.parent),
            "ASM6 源文件 (*.asm);;所有文件 (*)",
        )
        if not filename:
            return
        try:
            self._apply_music_payload(
                assemble_famistudio_music_source(filename), Path(filename).name
            )
        except Exception as error:
            self.show_error(error)

    def export_music_bank(self) -> None:
        if self.project is None:
            return
        command = self._current_music_command()
        if command is None:
            return
        filename, _ = QFileDialog.getSaveFileName(
            self,
            "导出当前音乐 Bank",
            str(default_export_path(f"music_{command:02X}.bin")),
            "8 KiB Bank (*.bin)",
        )
        if not filename:
            return
        try:
            destination = Path(filename)
            if destination.suffix.lower() != ".bin":
                destination = destination.with_suffix(".bin")
            destination = writable_output_path(destination)
            destination.write_bytes(self.project.custom_music_bank(command))
        except Exception as error:
            self.show_error(error)

    def reset_music_slot(self) -> None:
        if self.project is None:
            return
        command = self._current_music_command()
        if command is None:
            return
        try:
            self.project.reset_custom_music_bank(command)
            self.project_changed.emit(f"已还原扩展曲槽 ${command:02X}")
        except Exception as error:
            self.show_error(error)

    def load_record(self, record_id: int | None) -> None:
        if self.project is None or record_id is None:
            self.record_heading.setText("请选择音乐选择器")
            self.original_binding.setText("基准ROM：—")
            self.pending_state.setText("选择记录后可编辑。")
            self.apply_button.setEnabled(False)
            return
        binding = self.project.get_battle_music_binding(record_id)
        original = self.project.get_battle_music_binding(record_id, original=True)
        self.record_heading.setText(
            f"选择器 ${record_id:02X} · "
            f"{self.project.battle_music_selector_label(record_id)}"
        )
        self.attacker.blockSignals(True)
        self.defender.blockSignals(True)
        self.attacker.setCurrentIndex(self.attacker.findData(binding.attacker_command))
        self.defender.setCurrentIndex(self.defender.findData(binding.defender_command))
        self.attacker.blockSignals(False)
        self.defender.blockSignals(False)
        self.original_binding.setText(
            "基准ROM：主动 "
            f"{self.project.battle_music_codec.format_command(original.attacker_command)} "
            "· 被攻击 "
            f"{self.project.battle_music_codec.format_command(original.defender_command)}"
        )
        self._update_pending_state()

    def _update_pending_state(self) -> None:
        if self.project is None or self.current_id is None:
            return
        binding = self.project.get_battle_music_binding(self.current_id)
        changed = (
            self.attacker.currentData() is not None
            and self.defender.currentData() is not None
            and (
                int(self.attacker.currentData()) != binding.attacker_command
                or int(self.defender.currentData()) != binding.defender_command
            )
        )
        self.apply_button.setEnabled(changed)
        self.pending_state.setText("● 有尚未应用的绑定" if changed else "✓ 当前表单已应用")
        self.pending_state.setProperty("pending", changed)
        self.pending_state.style().unpolish(self.pending_state)
        self.pending_state.style().polish(self.pending_state)

    def apply_to_many(self) -> None:
        if self.project is None or self.current_id is None:
            return
        text_value, accepted = QInputDialog.getText(
            self,
            "批量应用音乐绑定",
            "输入目标选择器ID（示例：$00-$05,$10）：",
        )
        if not accepted:
            return
        try:
            maximum = self.project.profile.battle_music.selector_count - 1
            ids = parse_id_expression(text_value, maximum)
            attacker = int(self.attacker.currentData())
            defender = int(self.defender.currentData())
            preview = "、".join(f"${value:02X}" for value in ids[:16])
            if len(ids) > 16:
                preview += f" 等 {len(ids)} 项"
            answer = QMessageBox.question(
                self,
                "确认批量绑定",
                f"将当前主动/被攻击曲应用到：{preview}\n"
                "所有写入可通过一次撤销恢复，是否继续？",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel,
                QMessageBox.StandardButton.Cancel,
            )
            if answer != QMessageBox.StandardButton.Yes:
                return
            with self.project.transaction(f"批量更新 {len(ids)} 个音乐选择器"):
                for selector in ids:
                    self.project.set_battle_music_binding(selector, attacker, defender)
            self.project_changed.emit(f"已批量更新 {len(ids)} 个音乐选择器")
        except Exception as error:
            self.show_error(error)

    def apply_record(self) -> None:
        if self.project is None or self.current_id is None:
            return
        try:
            self.project.set_battle_music_binding(
                self.current_id,
                int(self.attacker.currentData()),
                int(self.defender.currentData()),
            )
            self.project_changed.emit(f"已更新音乐选择器 ${self.current_id:02X}")
        except Exception as error:
            self.show_error(error)

    def reset_record(self) -> None:
        if self.project is None or self.current_id is None:
            return
        try:
            self.project.reset_battle_music_binding(self.current_id)
            self.project_changed.emit(f"已还原音乐选择器 ${self.current_id:02X}")
        except Exception as error:
            self.show_error(error)


class ResourcePage(ProjectPage):
    def __init__(self) -> None:
        super().__init__()
        self._quota_initialized = False
        layout = QVBoxLayout(self)
        title, subtitle = page_title(
            "容量分配与自动接通",
            "先按用途分配容量，修改器会自动搬移数据、写入 Bank 目录并接通运行时读取。",
        )
        layout.addWidget(title)
        layout.addWidget(subtitle)
        self.capacity_label = QLabel("尚未载入ROM")
        self.capacity_label.setObjectName("sectionTitle")
        self.capacity = QProgressBar()
        self.capacity.setRange(0, 100)
        self.capacity.setValue(0)
        self.capacity.setFormat("0 / 0 KiB")
        layout.addWidget(self.capacity_label)
        layout.addWidget(self.capacity)

        planner_group = QGroupBox("自动容量规划")
        planner_layout = QVBoxLayout(planner_group)
        planner_help = QLabel(
            "直接选择地图、机体、剧情各占多少，再点一次按钮完成分区和运行时绑定。"
            "地图包含地形、部署、地图事件与商店；机体包含属性、名称和战斗图配置；"
            "剧情配额用于可变长对话文本，章节事件和劝降仍使用原有安全编辑区。"
        )
        planner_help.setObjectName("hintText")
        planner_help.setWordWrap(True)
        planner_layout.addWidget(planner_help)

        quota_grid = QGridLayout()
        self.map_quota = QSpinBox()
        self.map_quota.setRange(16, 400)
        self.map_quota.setSingleStep(8)
        self.map_quota.setSuffix(" KiB")
        self.map_quota.setToolTip("8 KiB 为一个 PRG Bank；地形、部署和地图事件共用此配额。")
        self.unit_quota = QSpinBox()
        self.unit_quota.setRange(48, 80)
        self.unit_quota.setSingleStep(16)
        self.unit_quota.setSuffix(" KiB")
        self.unit_quota.setToolTip(
            "48 KiB 已支持常规界面中的机体编辑；64 KiB 增加独立主体/碎片池；"
            "80 KiB 再增加独立名称池。额外池主要供高级资源或后续导入功能。"
        )
        self.story_quota = QSpinBox()
        self.story_quota.setRange(16, 112)
        self.story_quota.setSingleStep(16)
        self.story_quota.setSuffix(" KiB")
        self.story_quota.setToolTip("每 16 KiB 可自动绑定一个被修改的剧情文本组。")
        for editor in (self.map_quota, self.unit_quota, self.story_quota):
            editor.valueChanged.connect(self._update_plan_preview)
        quota_grid.addWidget(QLabel("地图"), 0, 0)
        quota_grid.addWidget(self.map_quota, 0, 1)
        quota_grid.addWidget(QLabel("机体"), 0, 2)
        quota_grid.addWidget(self.unit_quota, 0, 3)
        quota_grid.addWidget(QLabel("剧情"), 0, 4)
        quota_grid.addWidget(self.story_quota, 0, 5)
        quota_grid.setColumnStretch(6, 1)
        planner_layout.addLayout(quota_grid)

        planner_actions = QHBoxLayout()
        self.plan_status = QLabel("尚未载入ROM")
        self.plan_status.setWordWrap(True)
        self.plan_status.setObjectName("hintText")
        self.recommended_button = QPushButton("使用推荐分配")
        self.recommended_button.clicked.connect(self._use_recommended_plan)
        self.apply_plan_button = QPushButton("自动分区并接通")
        self.apply_plan_button.setObjectName("primaryButton")
        self.apply_plan_button.clicked.connect(self._apply_auto_plan)
        planner_actions.addWidget(self.plan_status, 1)
        planner_actions.addWidget(self.recommended_button)
        planner_actions.addWidget(self.apply_plan_button)
        planner_layout.addLayout(planner_actions)
        layout.addWidget(planner_group)

        managed_group = QGroupBox("高级：规划后剩余空间（不自动接通）")
        managed_layout = QVBoxLayout(managed_group)
        managed_help = QLabel(
            "只在仍有未分配空间时使用。这里导入的是高级二进制资源，"
            "不会自动建立游戏内引用；一般编辑无需操作此区域。"
            "如果使用过此功能，请始终保留 .dcmod 并用工程续改。"
        )
        managed_help.setObjectName("hintText")
        managed_help.setWordWrap(True)
        managed_layout.addWidget(managed_help)
        managed_buttons = QHBoxLayout()
        self.import_button = QPushButton("导入二进制资源…")
        self.import_button.clicked.connect(self.import_resource)
        self.export_button = QPushButton("导出所选资源…")
        self.export_button.clicked.connect(self.export_resource)
        self.remove_button = QPushButton("删除所选资源")
        self.remove_button.clicked.connect(self.remove_resource)
        managed_buttons.addWidget(self.import_button)
        managed_buttons.addWidget(self.export_button)
        managed_buttons.addWidget(self.remove_button)
        managed_buttons.addStretch()
        managed_layout.addLayout(managed_buttons)
        self.allocation_table = QTableWidget(0, 6)
        self.allocation_table.setHorizontalHeaderLabels(
            ("资源ID", "名称", "PRG Bank", "文件范围", "大小", "SHA-256")
        )
        self.allocation_table.horizontalHeader().setSectionResizeMode(
            1, QHeaderView.ResizeMode.Stretch
        )
        for column in (0, 2, 3, 4, 5):
            self.allocation_table.horizontalHeader().setSectionResizeMode(
                column, QHeaderView.ResizeMode.ResizeToContents
            )
        self.allocation_table.setAlternatingRowColors(True)
        self.allocation_table.itemSelectionChanged.connect(self._update_button_state)
        managed_layout.addWidget(self.allocation_table)
        layout.addWidget(managed_group)

        layout.addWidget(QLabel("ROM布局与保护范围"))
        self.table = QTableWidget(0, 6)
        self.table.setHorizontalHeaderLabels(
            ("资源", "类型", "文件起点", "文件终点", "大小", "写入策略")
        )
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeMode.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(4, QHeaderView.ResizeMode.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(5, QHeaderView.ResizeMode.ResizeToContents)
        self.table.setAlternatingRowColors(True)
        layout.addWidget(self.table, 1)

    def set_project(self, project: RomProject | None) -> None:
        if project is not self.project:
            self._quota_initialized = False
        super().set_project(project)

    def refresh(self) -> None:
        self.table.setRowCount(0)
        self.allocation_table.setRowCount(0)
        if self.project is None:
            self.capacity_label.setText("尚未载入ROM")
            self.capacity.setFormat("0 / 0 KiB")
            self.capacity.setValue(0)
            self.plan_status.setText("尚未载入ROM")
            for editor in (self.map_quota, self.unit_quota, self.story_quota):
                editor.setEnabled(False)
            self.recommended_button.setEnabled(False)
            self.apply_plan_button.setEnabled(False)
            self._update_button_state()
            return
        supports_planner = self.project.profile.key == "dc-kuorong-mmc3-v2"
        plan = self.project.expansion_plan if supports_planner else None
        if plan is not None:
            values = (
                plan.map_bank_count * 8,
                plan.unit_bank_count * 8,
                plan.story_bank_count * 8,
            )
            for editor, value in zip(
                (self.map_quota, self.unit_quota, self.story_quota), values
            ):
                editor.blockSignals(True)
                editor.setValue(value)
                editor.blockSignals(False)
                editor.setEnabled(False)
            self.recommended_button.setEnabled(False)
            self.apply_plan_button.setEnabled(False)
            story_slots = plan.story_bank_count // 2
            guarded = sum(
                allocation.size
                for allocation in self.project.expansion_allocations
                if allocation.resource_id.startswith(REOPEN_GUARD_PREFIX)
            )
            guard_note = (
                f"输出ROM直接重开时已安全锁定未登记区 "
                f"{guarded // 1024} KiB，高级资源请用 .dcmod 续改。"
                if guarded
                else ""
            )
            self.plan_status.setText(
                f"已接通：地图 {values[0]} KiB，机体 {values[1]} KiB，"
                f"剧情 {values[2]} KiB（{story_slots} 个文本组槽位）；"
                f"未分配 {plan.unassigned_kib} KiB。{guard_note}"
            )
        elif supports_planner:
            for editor in (self.map_quota, self.unit_quota, self.story_quota):
                editor.setEnabled(True)
            self.recommended_button.setEnabled(True)
            if not self._quota_initialized:
                self._use_recommended_plan()
                self._quota_initialized = True
            self._update_plan_preview()
        else:
            for editor in (self.map_quota, self.unit_quota, self.story_quota):
                editor.setEnabled(False)
            self.recommended_button.setEnabled(False)
            self.apply_plan_button.setEnabled(False)
            self.plan_status.setText("当前ROM不是 464 KiB 可分配版本，不能使用自动容量规划。")
        graph = ResourceGraph.from_profile(self.project.profile, self.project.original)
        nodes = sorted(graph.nodes, key=lambda item: (item.offset, item.resource_id))
        self.table.setRowCount(len(nodes))
        kind_names = {
            "table": "指针表",
            "data": "数据",
            "code": "程序",
            "audio": "音频/保留",
            "graphics": "图像",
            "free": "可分配",
            "metadata": "元数据",
        }
        for row, node in enumerate(nodes):
            values = (
                node.label,
                kind_names[node.kind],
                f"0x{node.offset:06X}",
                f"0x{node.end - 1:06X}",
                f"{node.size:,} B",
                "修改器管理" if node.writable else "受保护",
            )
            for column, value in enumerate(values):
                self.table.setItem(row, column, readonly_item(value))
        capacity = self.project.expansion_capacity
        used = self.project.expansion_used
        available = self.project.expansion_available
        regions = "、".join(region.display for region in self.project.profile.free_prg_regions)
        self.capacity_label.setText(
            f"扩展资源区 {regions}：总计 {capacity // 1024} KiB，"
            f"剩余 {available:,} B"
        )
        self.capacity.setValue(round(used * 100 / capacity) if capacity else 0)
        self.capacity.setFormat(f"已分配 {used:,} B / {capacity:,} B")
        allocations = self.project.expansion_allocations
        self.allocation_table.setRowCount(len(allocations))
        for row, allocation in enumerate(allocations):
            first_bank = (allocation.offset - 16) // 0x2000
            last_bank = (allocation.end - 1 - 16) // 0x2000
            bank_text = (
                f"${first_bank:02X}"
                if first_bank == last_bank
                else f"${first_bank:02X}—${last_bank:02X}"
            )
            payload = self.project.expansion_resource_data(allocation.resource_id)
            values = (
                allocation.resource_id,
                allocation.label,
                bank_text,
                f"0x{allocation.offset:06X}—0x{allocation.end - 1:06X}",
                f"{allocation.size:,} B",
                hashlib.sha256(payload).hexdigest().upper()[:16] + "…",
            )
            for column, value in enumerate(values):
                item = readonly_item(value)
                if column == 0:
                    item.setData(Qt.ItemDataRole.UserRole, allocation.resource_id)
                self.allocation_table.setItem(row, column, item)
        self._update_button_state()

    def _use_recommended_plan(self) -> None:
        """Use every safe Bank while preserving all seven story-text slots."""

        for editor in (self.map_quota, self.unit_quota, self.story_quota):
            editor.blockSignals(True)
        self.map_quota.setValue(304)
        self.unit_quota.setValue(48)
        self.story_quota.setValue(112)
        for editor in (self.map_quota, self.unit_quota, self.story_quota):
            editor.blockSignals(False)
        self._update_plan_preview()

    def _update_plan_preview(self) -> None:
        if self.project is None or self.project.profile.key != "dc-kuorong-mmc3-v2":
            return
        if self.project.expansion_plan is not None:
            return
        map_kib = self.map_quota.value()
        unit_kib = self.unit_quota.value()
        story_kib = self.story_quota.value()
        invalid = []
        if map_kib % 8:
            invalid.append("地图必须按 8 KiB")
        if unit_kib not in (48, 64, 80):
            invalid.append("机体只能选择 48、64 或 80 KiB")
        if story_kib % 16:
            invalid.append("剧情必须按 16 KiB")
        if invalid:
            self.plan_status.setText("；".join(invalid) + " 的整数倍分配。")
            self.plan_status.setStyleSheet("color: #b42318; font-weight: 650;")
            self.apply_plan_button.setEnabled(False)
            return
        total = map_kib + unit_kib + story_kib
        capacity = self.project.expansion_capacity // 1024
        remaining = capacity - total
        if remaining < 0:
            self.plan_status.setText(
                f"已选择 {total} / {capacity} KiB，超出 {-remaining} KiB；请调小任一配额。"
            )
            self.plan_status.setStyleSheet("color: #b42318; font-weight: 650;")
            self.apply_plan_button.setEnabled(False)
        else:
            slots = story_kib // 16
            unit_note = {
                48: "常规编辑池（推荐）",
                64: "常规池+独立主体/碎片池",
                80: "常规池+独立主体/碎片/名称池",
            }[unit_kib]
            self.plan_status.setText(
                f"已选择 {total} / {capacity} KiB，剩余 {remaining} KiB；"
                f"剧情可容纳 {slots} 个修改文本组；机体为{unit_note}。"
            )
            self.plan_status.setStyleSheet("color: #2e7d4f;")
            self.apply_plan_button.setEnabled(True)

    def _apply_auto_plan(self) -> None:
        if self.project is None:
            return
        try:
            self.project.configure_expansion(
                self.map_quota.value(),
                self.unit_quota.value(),
                self.story_quota.value(),
            )
            self.project_changed.emit("已自动分区并接通地图、机体和剧情扩展容量")
        except Exception as error:
            self.show_error(error)

    def _selected_resource_id(self) -> str | None:
        row = self.allocation_table.currentRow()
        if row < 0:
            return None
        item = self.allocation_table.item(row, 0)
        return None if item is None else str(item.data(Qt.ItemDataRole.UserRole))

    def _update_button_state(self) -> None:
        loaded = self.project is not None
        selected_id = self._selected_resource_id() if loaded else None
        selected = selected_id is not None
        internal = bool(
            selected_id and selected_id.startswith(AUTO_ALLOCATION_PREFIX)
        )
        can_import = False
        if loaded:
            assert self.project is not None
            has_capacity = self.project.expansion_available > 0
            if self.project.profile.key == "dc-kuorong-mmc3-v2":
                has_reopen_guard = any(
                    allocation.resource_id.startswith(REOPEN_GUARD_PREFIX)
                    for allocation in self.project.expansion_allocations
                )
                can_import = (
                    self.project.expansion_plan is not None
                    and has_capacity
                    and not has_reopen_guard
                )
            else:
                # Legacy profiles have no automatic partition table; retain
                # their existing allocator-only workflow.
                can_import = has_capacity
        self.import_button.setEnabled(can_import)
        self.export_button.setEnabled(selected)
        self.remove_button.setEnabled(selected and not internal)

    def import_resource(self) -> None:
        if self.project is None:
            return
        filename, _ = QFileDialog.getOpenFileName(
            self,
            "导入扩展二进制资源",
            str(self.project.path.parent),
            "二进制文件 (*.bin);;所有文件 (*)",
        )
        if not filename:
            return
        try:
            path = Path(filename)
            payload = path.read_bytes()
            suggested = re.sub(r"[^a-z0-9._-]+", "-", path.stem.lower()).strip("-.")
            if not suggested or not suggested[0].isalnum():
                suggested = "resource"
            resource_id, accepted = QInputDialog.getText(
                self, "资源ID", "唯一资源ID：", text=suggested[:64]
            )
            if not accepted:
                return
            label, accepted = QInputDialog.getText(
                self, "资源名称", "显示名称：", text=path.stem
            )
            if not accepted:
                return
            allocation = self.project.import_expansion_resource(
                resource_id,
                label,
                payload,
                alignment=0x10,
            )
            self.project_changed.emit(
                f"已导入扩展资源 {allocation.resource_id} · {allocation.size} 字节"
            )
        except Exception as error:
            self.show_error(error)

    def export_resource(self) -> None:
        if self.project is None:
            return
        resource_id = self._selected_resource_id()
        if resource_id is None:
            return
        filename, _ = QFileDialog.getSaveFileName(
            self,
            "导出扩展资源",
            str(default_export_path(f"{resource_id}.bin")),
            "二进制文件 (*.bin);;所有文件 (*)",
        )
        if not filename:
            return
        try:
            destination = Path(filename)
            if destination.suffix.lower() != ".bin":
                destination = destination.with_suffix(".bin")
            destination = writable_output_path(destination)
            destination.write_bytes(self.project.expansion_resource_data(resource_id))
        except Exception as error:
            self.show_error(error)

    def remove_resource(self) -> None:
        if self.project is None:
            return
        resource_id = self._selected_resource_id()
        if resource_id is None:
            return
        allocation = self.project.resource_allocator.allocation(resource_id)
        answer = QMessageBox.question(
            self,
            "删除扩展资源",
            f"确定删除“{allocation.label}”并释放 {allocation.size:,} 字节吗？\n"
            "此操作可以撤销。",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel,
            QMessageBox.StandardButton.Cancel,
        )
        if answer != QMessageBox.StandardButton.Yes:
            return
        try:
            self.project.remove_expansion_resource(resource_id)
            self.project_changed.emit(f"已删除扩展资源 {resource_id}")
        except Exception as error:
            self.show_error(error)


class ChangesPage(ProjectPage):
    def __init__(self) -> None:
        super().__init__()
        layout = QVBoxLayout(self)
        title, subtitle = page_title(
            "变更与验证",
            "在构建前检查每个修改范围、资源引用和受保护区域。错误必须全部处理。",
        )
        layout.addWidget(title)
        layout.addWidget(subtitle)
        toolbar = QHBoxLayout()
        refresh_button = QPushButton("刷新")
        refresh_button.clicked.connect(self.refresh)
        validate_button = QPushButton("运行完整检查")
        validate_button.setObjectName("primaryButton")
        validate_button.clicked.connect(self.run_validation)
        self.summary = QLabel("尚未载入ROM")
        self.summary.setObjectName("sectionTitle")
        toolbar.addWidget(refresh_button)
        toolbar.addWidget(validate_button)
        toolbar.addStretch()
        toolbar.addWidget(self.summary)
        layout.addLayout(toolbar)
        splitter = QSplitter(Qt.Orientation.Vertical)
        self.changes = QTableWidget(0, 4)
        self.changes.setHorizontalHeaderLabels(("文件范围", "长度", "说明", "字节变化"))
        self.changes.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
        self.changes.setAlternatingRowColors(True)
        splitter.addWidget(self.changes)
        self.validation = QTableWidget(0, 3)
        self.validation.setHorizontalHeaderLabels(("级别", "模块", "结果"))
        self.validation.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
        self.validation.setAlternatingRowColors(True)
        splitter.addWidget(self.validation)
        splitter.setSizes([330, 260])
        layout.addWidget(splitter, 1)

    def refresh(self) -> None:
        self.changes.setRowCount(0)
        if self.project is None:
            self.summary.setText("尚未载入ROM")
            self.validation.setRowCount(0)
            return
        ranges = self.project.change_ranges()
        self.changes.setRowCount(len(ranges))
        for row, (start, end) in enumerate(ranges):
            old = self.project.original[start:end]
            new = bytes(self.project.working[start:end])
            description = self.project.change_description(start)
            preview = f"{old[:8].hex(' ').upper()} → {new[:8].hex(' ').upper()}"
            if end - start > 8:
                preview += " …"
            values = (f"0x{start:06X}—0x{end - 1:06X}", str(end - start), description, preview)
            for column, value in enumerate(values):
                self.changes.setItem(row, column, readonly_item(value))
        self.summary.setText(f"{len(self.project.change_rows())} 个字节已修改")

    def run_validation(self) -> None:
        if self.project is None:
            return
        try:
            issues = self.project.validate()
        except Exception as error:
            self.show_error(error)
            return
        self.validation.setRowCount(len(issues))
        names = {"error": "错误", "warning": "警告", "info": "通过/信息"}
        for row, issue in enumerate(issues):
            values = (names[issue.severity], issue.module, issue.message)
            for column, value in enumerate(values):
                item = readonly_item(value)
                if issue.severity == "error":
                    item.setForeground(Qt.GlobalColor.red)
                elif issue.severity == "warning":
                    item.setForeground(Qt.GlobalColor.darkYellow)
                self.validation.setItem(row, column, item)
        errors = sum(issue.severity == "error" for issue in issues)
        self.project_changed.emit("验证通过" if errors == 0 else f"验证发现 {errors} 个错误")


class PlaceholderPage(ProjectPage):
    def __init__(self, title_text: str, description: str, items: tuple[str, ...]) -> None:
        super().__init__()
        layout = QVBoxLayout(self)
        title, subtitle = page_title(title_text, description)
        layout.addWidget(title)
        layout.addWidget(subtitle)
        card = QGroupBox("本模块的完整范围")
        card_layout = QVBoxLayout(card)
        for item in items:
            label = QLabel(f"• {item}")
            label.setWordWrap(True)
            card_layout.addWidget(label)
        layout.addWidget(card)
        state = QLabel("底层格式正在按可逆、可校验原则接入；当前页面不会写入未确认数据。")
        state.setObjectName("emptyState")
        state.setAlignment(Qt.AlignmentFlag.AlignCenter)
        state.setWordWrap(True)
        layout.addWidget(state, 1)


PageFactory = Callable[[], ProjectPage]
