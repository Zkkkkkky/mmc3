from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QPixmap, QShowEvent
from PySide6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QComboBox,
    QDialog,
    QFormLayout,
    QFrame,
    QGridLayout,
    QGroupBox,
    QHeaderView,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QSpinBox,
    QSplitter,
    QTabWidget,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from fc_editor.dc_text import dc_map_label, default_dc_text_table
from fc_editor.resources import Allocation, BankAllocator
from fc_rom_editor_core import RomProject

from .event_page import EventPage
from .map_page import render_map_title, render_unit_icon_bank
from .pages import CharacterPage, ProjectPage, UnitPage, WeaponPage
from .persuasion_page import PersuasionPage
from .story_page import StoryPage


@dataclass(frozen=True)
class _DialogSnapshot:
    working: bytes
    allocations: tuple[Allocation, ...]
    undo_stack: tuple[Any, ...]
    redo_stack: tuple[Any, ...]


class TransactionalProjectDialog(QDialog):
    """A legacy editor window with whole-window accept/cancel semantics.

    Existing editor pages apply changes directly to ``RomProject.working``.
    The original SRW2 editor, however, treats an entire child window as one
    editing session.  This wrapper takes a complete session snapshot when the
    dialog is shown and restores it when the user presses Cancel or closes the
    window.  It deliberately restores the allocator and history stacks too so
    a cancelled resource edit cannot later reappear through Undo/Redo.
    """

    project_changed = Signal(str)
    navigation_requested = Signal(str)

    def __init__(
        self,
        project: RomProject | None,
        parent: QWidget | None = None,
        *,
        title: str = "编辑",
    ) -> None:
        super().__init__(parent)
        self.project = project
        self.pages: list[ProjectPage] = []
        self._snapshot: _DialogSnapshot | None = None
        self._session_active = False
        self._dialog_title = title
        self.setWindowTitle(title)
        self.setModal(True)
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose, False)

    def register_page(self, page: ProjectPage) -> ProjectPage:
        """Attach a functional page and proxy its public integration signals."""

        self.pages.append(page)
        conflict_setter = getattr(page, "set_transaction_conflict_checker", None)
        if callable(conflict_setter):
            conflict_setter(self._pending_page_conflict_error)
        page.project_changed.connect(
            lambda message, source=page: self._registered_page_changed(source, message)
        )
        page.navigation_requested.connect(self._forward_navigation)
        page.set_project(self.project)
        return page

    def _registered_page_changed(self, page: ProjectPage, message: str) -> None:
        """Reload the source and clean peers while preserving owned drafts."""

        page.refresh()
        sync_group = getattr(page, "transaction_sync_group", None)
        if sync_group is not None:
            for sibling in self.pages:
                if (
                    sibling is not page
                    and getattr(sibling, "transaction_sync_group", None) == sync_group
                    and not sibling.has_pending_draft
                ):
                    sibling.refresh()
        self.project_changed.emit(message)

    def _pending_page_conflict_error(self, source: ProjectPage) -> str | None:
        """Reject two local drafts that target the same underlying resource."""

        source_key = getattr(source, "pending_draft_key", None)
        if source_key is None:
            return None
        for sibling in self.pages:
            if sibling is source:
                continue
            if getattr(sibling, "pending_draft_key", None) == source_key:
                if source_key[0] == "chapter_event":
                    return (
                        f"同一事件指令 ${source_key[1]:04X} 同时存在于多个"
                        "编辑页的未提交草稿中。请先保留其中一份并还原"
                        "另一份，再重试。"
                    )
                return (
                    "同一剧情文本同时存在于多个编辑页的未提交草稿中。"
                    "请先保留其中一份并还原另一份，再重试。"
                )
        return None

    def set_project(self, project: RomProject | None) -> None:
        self.project = project
        self._snapshot = None
        self._session_active = False
        for page in self.pages:
            page.set_project(project)
        if self.isVisible():
            self._begin_session()

    def _forward_navigation(self, page_key: str) -> None:
        self.navigation_requested.emit(page_key)

    def _begin_session(self) -> None:
        if self.project is None:
            self._snapshot = None
        else:
            self._snapshot = _DialogSnapshot(
                bytes(self.project.working),
                self.project.resource_allocator.allocations,
                tuple(self.project._undo_stack),
                tuple(self.project._redo_stack),
            )
        self._session_active = True

    def showEvent(self, event: QShowEvent) -> None:  # noqa: N802 - Qt API
        if not self._session_active:
            self._begin_session()
        super().showEvent(event)

    def _refresh_pages(self) -> None:
        pages = list(self.pages)
        for page in self.findChildren(ProjectPage):
            if page not in pages:
                pages.append(page)
        for page in pages:
            page.refresh()

    def _commit_pending_pages(self) -> bool:
        pending = tuple(page for page in self.pages if page.has_pending_draft)
        for page in pending:
            error = page.pending_draft_error
            if error is not None:
                QMessageBox.warning(
                    self,
                    "当前修改无法确认",
                    error,
                )
                return False
        for page in pending:
            if page.commit_pending_changes():
                continue
            QMessageBox.warning(
                self,
                "当前修改无法确认",
                page.pending_draft_error
                or "当前页仍有无法提交的输入，请修正后重试。",
            )
            return False
        return True

    def accept(self) -> None:
        if not self._commit_pending_pages():
            return
        self._snapshot = None
        self._session_active = False
        super().accept()

    def reject(self) -> None:
        restored = False
        if self.project is not None and self._session_active and self._snapshot is not None:
            snapshot = self._snapshot
            restored = (
                bytes(self.project.working) != snapshot.working
                or self.project.resource_allocator.allocations != snapshot.allocations
            )
            self.project.working[:] = snapshot.working
            self.project.resource_allocator = BankAllocator(
                self.project.profile,
                self.project.original,
                snapshot.allocations,
            )
            self.project._undo_stack[:] = snapshot.undo_stack
            self.project._redo_stack[:] = snapshot.redo_stack
            self.project._refresh_dynamic_codecs()
        self._snapshot = None
        self._session_active = False
        self._refresh_pages()
        if restored:
            title = self.windowTitle() or self._dialog_title
            self.project_changed.emit(f"已取消{title}修改并恢复打开前状态")
        super().reject()


class _LegacyEventController(EventPage):
    """Event editor that participates in window-wide resource conflicts."""

    def __init__(self) -> None:
        self._transaction_conflict_checker: (
            Callable[[ProjectPage], str | None] | None
        ) = None
        super().__init__()

    @property
    def transaction_sync_group(self) -> str:
        return "chapter_event"

    @property
    def pending_draft_key(self) -> tuple[str, int] | None:
        if not self.has_pending_draft or self.current_address is None:
            return None
        return self.transaction_sync_group, self.current_address

    def set_transaction_conflict_checker(
        self,
        checker: Callable[[ProjectPage], str | None] | None,
    ) -> None:
        self._transaction_conflict_checker = checker

    def _transaction_conflict_error(self) -> str | None:
        if not self.has_pending_draft or self._transaction_conflict_checker is None:
            return None
        return self._transaction_conflict_checker(self)

    @property
    def pending_draft_error(self) -> str | None:
        return super().pending_draft_error or self._transaction_conflict_error()

    def _apply_template(self) -> None:
        conflict = self._transaction_conflict_error()
        if conflict is not None:
            self.show_error(ValueError(conflict))
            return
        super()._apply_template()

    def _apply_raw(self) -> None:
        conflict = self._transaction_conflict_error()
        if conflict is not None:
            self.show_error(ValueError(conflict))
            return
        super()._apply_raw()


class _LegacyUnitController(UnitPage):
    """UnitPage logic with the record captions used by the reference editor."""

    record_loaded = Signal()

    def record_text(self, record_id: int) -> str:
        assert self.project is not None
        return (
            f"[{record_id:02X}]{record_id:03d}: "
            f"{self.project.unit_display_name(record_id)}"
        )

    def load_record(self, record_id: int | None) -> None:
        super().load_record(record_id)
        self.record_loaded.emit()


class LegacyUnitDatabasePage(ProjectPage):
    """Reference-shaped unit editor backed by the verified UnitPage logic."""

    weapon_requested = Signal(int)

    def __init__(self) -> None:
        super().__init__()
        self.controller = _LegacyUnitController()
        self.controller.setParent(self)
        self.controller.hide()
        self.controller.project_changed.connect(self.project_changed.emit)
        self.controller.navigation_requested.connect(self.navigation_requested.emit)
        self.controller.record_loaded.connect(self._refresh_visuals)

        # Public compatibility attributes used by database navigation/tests.
        self.records = self.controller.records
        self.search = self.controller.search
        self.search_panel = self.controller.search_panel
        self.fields = self.controller.fields
        self.name_reference = self.controller.name_reference
        self.weapon_slots = self.controller.weapon_slots
        self.apply_button = self.controller.apply_button
        self.apply_button.setText("暂存当前机体")
        self.apply_button.setToolTip(
            "暂存到本窗口会话；按右下角“确定”保留，按“取消”全部回滚。"
        )

        root = QHBoxLayout(self)
        root.setContentsMargins(6, 6, 6, 6)
        splitter = QSplitter()
        splitter.setChildrenCollapsible(False)
        root.addWidget(splitter)

        selection = QGroupBox("机体选择")
        selection.setMinimumWidth(340)
        selection.setMaximumWidth(390)
        selection_layout = QVBoxLayout(selection)
        selection_layout.setContentsMargins(7, 10, 7, 7)
        selection_layout.addWidget(self.records, 1)
        self.add_button = QPushButton("添加")
        self.add_button.setEnabled(False)
        self.add_button.setToolTip("新增机体所需的指针重定位规则尚未完成验证。")
        selection_layout.addWidget(self.add_button)
        splitter.addWidget(selection)

        detail = QWidget()
        detail_layout = QVBoxLayout(detail)
        detail_layout.setContentsMargins(2, 0, 0, 0)
        detail_layout.addWidget(self._build_graphics_group(), 3)
        detail_layout.addLayout(self._build_data_row(), 2)

        staged_row = QHBoxLayout()
        staged_row.addWidget(self.apply_button)
        duplicate = QPushButton("复制到其他ID…")
        duplicate.clicked.connect(self.controller.duplicate_record)
        reset = QPushButton("还原此机体")
        reset.clicked.connect(self.controller.reset_record)
        staged_row.addWidget(duplicate)
        staged_row.addWidget(reset)
        self.session_hint = QLabel("页内暂存后仍可用右下角“取消”完整撤销。")
        self.session_hint.setObjectName("hintText")
        staged_row.addWidget(self.session_hint)
        staged_row.addStretch()
        detail_layout.addLayout(staged_row)
        splitter.addWidget(detail)
        splitter.setSizes([365, 1080])

    @property
    def current_id(self) -> int | None:
        return self.controller.current_id

    def _disabled_button(self, text: str, tooltip: str) -> QPushButton:
        button = QPushButton(text)
        button.setEnabled(False)
        button.setToolTip(tooltip)
        return button

    def _disabled_check(self, text: str, tooltip: str) -> QCheckBox:
        checkbox = QCheckBox(text)
        checkbox.setEnabled(False)
        checkbox.setToolTip(tooltip)
        return checkbox

    def _build_graphics_group(self) -> QGroupBox:
        group = QGroupBox("机体图片")
        grid = QGridLayout(group)
        grid.setContentsMargins(8, 13, 8, 8)
        grid.setHorizontalSpacing(9)

        self.body_preview = QLabel("请选择机体")
        self.body_preview.setObjectName("legacyUnitBodyPreview")
        self.body_preview.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.body_preview.setMinimumSize(350, 245)
        self.body_preview.setStyleSheet(
            "background: #000000; color: #d2d2d2; border: 1px solid #202020;"
        )
        self.body_preview.setToolTip(
            "机体拼图脚本结构尚未完成验证，因此只保留旧版黑色预览区。"
        )
        grid.addWidget(self.body_preview, 0, 0, 2, 1)

        unverified = "机体拼图写入格式尚未完成逐字段差分验证；当前保持只读。"
        body_controls = QVBoxLayout()
        body_controls.addWidget(self._disabled_button("上传机体", unverified))
        body_controls.addWidget(self._disabled_button("清除机体", unverified))
        body_controls.addWidget(QLabel("导图偏移"))
        self.body_offset = QSpinBox()
        self.body_offset.setRange(-128, 127)
        self.body_offset.setValue(0)
        self.body_offset.setEnabled(False)
        self.body_offset.setToolTip(unverified)
        body_controls.addWidget(self.body_offset)
        body_controls.addWidget(self._disabled_check("调换图库", unverified))
        body_controls.addWidget(self._disabled_check("压缩上传", unverified))
        body_controls.addWidget(self._disabled_button("机体拼图", unverified))
        self.show_body = self._disabled_check("显示机体", unverified)
        self.show_body.setChecked(True)
        body_controls.addWidget(self.show_body)
        body_controls.addStretch()
        grid.addLayout(body_controls, 0, 1, 2, 1)

        fragment_controls = QVBoxLayout()
        fragment_controls.addWidget(self._disabled_button("上传碎片", unverified))
        fragment_controls.addWidget(self._disabled_button("清除碎片", unverified))
        fragment_controls.addWidget(QLabel("导图偏移"))
        self.fragment_offset = QSpinBox()
        self.fragment_offset.setRange(-128, 127)
        self.fragment_offset.setValue(0)
        self.fragment_offset.setEnabled(False)
        self.fragment_offset.setToolTip(unverified)
        fragment_controls.addWidget(self.fragment_offset)
        fragment_controls.addWidget(self._disabled_check("压缩上传", unverified))
        fragment_controls.addWidget(self._disabled_button("碎片拼图", unverified))
        self.show_fragment = self._disabled_check("显示碎片", unverified)
        self.show_fragment.setChecked(True)
        fragment_controls.addWidget(self.show_fragment)
        fragment_controls.addStretch()
        grid.addLayout(fragment_controls, 0, 2, 2, 1)

        icon_panel = QVBoxLayout()
        icon_panel.addWidget(QLabel("机体图标"))
        self.icon_preview = QLabel("—")
        self.icon_preview.setObjectName("legacyUnitIconPreview")
        self.icon_preview.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.icon_preview.setFixedSize(72, 72)
        self.icon_preview.setStyleSheet(
            "background: #000000; color: white; border: 1px solid #4d555c;"
        )
        icon_panel.addWidget(self.icon_preview, alignment=Qt.AlignmentFlag.AlignHCenter)
        icon_panel.addWidget(
            self._disabled_button(
                "上传图标", "图标替换入口尚未验证；预览直接读取活动CHR。"
            )
        )
        icon_panel.addWidget(
            self._disabled_button(
                "更改图标", "机体ID与图标索引关系尚未完成验证，不能安全写入。"
            )
        )
        icon_panel.addStretch()
        grid.addLayout(icon_panel, 0, 3, 2, 1)

        colors = QVBoxLayout()
        colors.addWidget(QLabel("机体三色"))
        self.body_color_values = self._add_color_rows(
            colors, ("#f46b5d", "#b60000", "#eeeeee")
        )
        colors.addSpacing(8)
        colors.addWidget(QLabel("碎片三色"))
        self.fragment_color_values = self._add_color_rows(
            colors, ("#49d94b", "#777777", "#b8b8b8")
        )
        colors.addStretch()
        grid.addLayout(colors, 0, 4, 2, 1)

        metadata = QFormLayout()
        self.unit_type = QComboBox()
        self.unit_type.addItem("结构待验证")
        self.unit_type.setEnabled(False)
        self.unit_type.setToolTip("机体类型字段尚未完成差分验证。")
        metadata.addRow("机体类型", self.unit_type)
        self.image_addresses: list[QComboBox] = []
        for label in ("机体图片地址1", "机体图片地址2", "机体碎片地址"):
            address = QComboBox()
            address.addItem("地址关系待验证")
            address.setEnabled(False)
            address.setToolTip("仅在确认指针关系后开放写入。")
            metadata.addRow(label, address)
            self.image_addresses.append(address)
        self.icon_address = QLineEdit()
        self.icon_address.setReadOnly(True)
        self.icon_address.setToolTip("活动CHR中的真实候选图标位置；不会写回ROM。")
        metadata.addRow("图标预览地址", self.icon_address)
        grid.addLayout(metadata, 0, 5, 2, 1)
        grid.setColumnStretch(0, 5)
        grid.setColumnStretch(5, 2)
        return group

    @staticmethod
    def _add_color_rows(layout: QVBoxLayout, colors: tuple[str, ...]) -> list[QLineEdit]:
        values: list[QLineEdit] = []
        for color in colors:
            row = QHBoxLayout()
            swatch = QFrame()
            swatch.setFixedSize(34, 28)
            swatch.setStyleSheet(f"background: {color}; border: 1px solid #777777;")
            value = QLineEdit("—")
            value.setFixedWidth(55)
            value.setReadOnly(True)
            value.setToolTip("配色索引尚未验证；色块仅复刻旧版区域外观。")
            row.addWidget(swatch)
            row.addWidget(value)
            layout.addLayout(row)
            values.append(value)
        return values

    def _build_data_row(self) -> QHBoxLayout:
        row = QHBoxLayout()
        row.setSpacing(9)

        basic = QGroupBox("基本设置")
        basic_form = QFormLayout(basic)
        basic_form.addRow("机体名称", self.name_reference)
        self.terrain = QComboBox()
        self.terrain.addItem("字段关系待验证")
        self.terrain.setEnabled(False)
        self.terrain.setToolTip("适应地形字段尚未完成差分验证。")
        basic_form.addRow("适应地形", self.terrain)
        self.transform = QComboBox()
        self.transform.addItem("字段关系待验证")
        self.transform.setEnabled(False)
        self.transform.setToolTip("变形关系尚未完成差分验证。")
        basic_form.addRow("变形", self.transform)
        self.record_meta = self.controller.record_meta
        self.record_meta.setWordWrap(True)
        basic_form.addRow("记录位置", self.record_meta)
        row.addWidget(basic, 3)

        attributes = QGroupBox("机体属性")
        attribute_grid = QGridLayout(attributes)
        logical_rows: tuple[tuple[str | None, str | None, str | None], ...] = (
            ("movement", "upgrade", "strength_growth"),
            ("strength", None, "defense_growth"),
            ("defense", None, "speed_growth"),
            ("speed", "hp", "hp_growth"),
        )
        labels = {
            "movement": "机动",
            "upgrade": "升级还需",
            "strength_growth": "强度成长",
            "strength": "强度",
            "defense_growth": "防御成长",
            "defense": "防御",
            "speed_growth": "速度成长",
            "speed": "速度",
            "hp": "HP",
            "hp_growth": "HP成长",
        }
        placeholders = iter(("基础金钱（待验证）", "特殊技能（待验证）"))
        for grid_row, columns in enumerate(logical_rows):
            for logical_column, field_key in enumerate(columns):
                column = logical_column * 2
                if field_key is None:
                    label = QLabel(next(placeholders))
                    editor = QSpinBox()
                    editor.setEnabled(False)
                    editor.setToolTip("该字段在当前ROM中的语义尚未验证。")
                else:
                    label = QLabel(labels[field_key])
                    editor = self.fields[field_key]
                attribute_grid.addWidget(label, grid_row, column)
                attribute_grid.addWidget(editor, grid_row, column + 1)
        row.addWidget(attributes, 5)

        weapons = QGroupBox("机体武器")
        weapons_layout = QVBoxLayout(weapons)
        self.weapon_jump_buttons: list[QPushButton] = []
        for slot, editor in enumerate(self.weapon_slots):
            slot_row = QHBoxLayout()
            slot_row.addWidget(QLabel(f"武器{slot + 1}"))
            slot_row.addWidget(editor, 1)
            jump = QPushButton(f"转到武器{slot + 1}")
            jump.clicked.connect(
                lambda _checked=False, weapon_slot=slot: self._request_weapon(weapon_slot)
            )
            slot_row.addWidget(jump)
            weapons_layout.addLayout(slot_row)
            self.weapon_jump_buttons.append(jump)
        warning = QLabel(
            "提示：如同时编辑机体和关联武器，请先暂存当前机体，再跳转到武器页。"
        )
        warning.setWordWrap(True)
        warning.setStyleSheet("color: #e02020;")
        weapons_layout.addWidget(warning)
        weapons_layout.addStretch()
        row.addWidget(weapons, 3)
        return row

    def _request_weapon(self, slot: int) -> None:
        editor = self.weapon_slots[slot]
        if editor.isEnabled() and editor.currentData() is not None:
            self.weapon_requested.emit(int(editor.currentData()))

    def _refresh_visuals(self) -> None:
        if self.project is None or self.current_id is None:
            self.body_preview.setText("请选择机体")
            self.icon_preview.setPixmap(QPixmap())
            self.icon_preview.setText("—")
            self.icon_address.clear()
            return
        unit_id = self.current_id
        self.body_preview.setPixmap(QPixmap())
        self.body_preview.setText("")

        # The three icon banks are verified active CHR data. The exact unit-ID
        # binding is still treated as a candidate, so this remains read-only.
        icon_group = ((unit_id - 1) // 32) % 3
        bank = 0x34 + icon_group
        icon = (unit_id - 1) % 32
        if bank * 64 + icon * 2 + 1 < self.project.chr_tile_count:
            sheet = render_unit_icon_bank(self.project, bank)
            column = icon % 16
            icon_row = icon // 16
            cropped = sheet.copy(column * 16, icon_row * 16, 16, 16)
            self.icon_preview.setText("")
            self.icon_preview.setPixmap(
                QPixmap.fromImage(cropped).scaled(
                    64,
                    64,
                    Qt.AspectRatioMode.KeepAspectRatio,
                    Qt.TransformationMode.FastTransformation,
                )
            )
            offset = self.project.chr_codec.offset + bank * 0x400 + icon * 0x20
            self.icon_address.setText(f"[{bank:02X}]{bank:03d}: {offset:06X}")
        else:
            self.icon_preview.setPixmap(QPixmap())
            self.icon_preview.setText("超出CHR")
            self.icon_address.setText("地址超出活动CHR")

        for field_key, editor in self.fields.items():
            base_value = self.project.get_value(unit_id, field_key, original=True)
            editor.setToolTip(f"{editor.toolTip().split('；基准ROM：')[0]}；基准ROM：{base_value}")

    def set_project(self, project: RomProject | None) -> None:
        self.project = project
        self.controller.set_project(project)
        self._refresh_visuals()

    def refresh(self) -> None:
        self.controller.refresh()
        self._refresh_visuals()

    def apply_record(self) -> None:
        self.controller.apply_record()

    def commit_pending(self) -> bool:
        if self.project is None or self.current_id is None:
            return False
        if self.name_reference.currentData() is None:
            return False
        if any(
            editor.isEnabled() and editor.currentData() is None
            for editor in self.weapon_slots
        ):
            return False
        if not self.apply_button.isEnabled():
            return True
        self.controller.apply_record()
        return not self.apply_button.isEnabled()

    def _select_relative(self, direction: int) -> None:
        self.controller._select_relative(direction)


class RawInspectionPage(ProjectPage):
    """Reference-shaped, read-only fallback for an unverified legacy page."""

    def __init__(self, title: str, records: tuple[str, ...], explanation: str) -> None:
        super().__init__()
        self._title = title
        self._explanation = explanation

        layout = QHBoxLayout(self)
        splitter = QSplitter()
        selection = QGroupBox(f"{title}选择")
        selection_layout = QVBoxLayout(selection)
        self.records = QListWidget()
        self.records.setAlternatingRowColors(True)
        for index, label in enumerate(records, 1):
            item = QListWidgetItem(f"[{index:02X}]{index:03d}: {label}")
            item.setData(Qt.ItemDataRole.UserRole, index - 1)
            self.records.addItem(item)
        self.add_button = QPushButton("添加")
        self.add_button.setEnabled(False)
        self.add_button.setToolTip("记录结构尚未验证，不能安全添加。")
        selection_layout.addWidget(self.records, 1)
        selection_layout.addWidget(self.add_button)
        splitter.addWidget(selection)

        detail = QWidget()
        detail_layout = QVBoxLayout(detail)
        warning = QLabel(explanation)
        warning.setObjectName("hintText")
        warning.setWordWrap(True)
        detail_layout.addWidget(warning)

        inspector = QGroupBox("只读原始数据查看")
        form = QFormLayout(inspector)
        self.offset = QLineEdit("0x10")
        self.offset.setPlaceholderText("文件偏移，例如 0x14010")
        self.length = QSpinBox()
        self.length.setRange(1, 0x1000)
        self.length.setValue(0x40)
        self.read_button = QPushButton("读取")
        self.read_button.clicked.connect(self.inspect_bytes)
        self.raw = QPlainTextEdit()
        self.raw.setReadOnly(True)
        self.raw.setPlaceholderText("输入文件偏移后可查看ROM字节；本页不会写入。")
        form.addRow("文件偏移", self.offset)
        form.addRow("读取长度", self.length)
        form.addRow("", self.read_button)
        form.addRow("原始字节", self.raw)
        detail_layout.addWidget(inspector, 1)
        splitter.addWidget(detail)
        splitter.setSizes([320, 900])
        layout.addWidget(splitter)

    @staticmethod
    def _parse_offset(text: str) -> int:
        value = text.strip()
        if value.startswith("$"):
            return int(value[1:], 16)
        return int(value, 0)

    def inspect_bytes(self) -> None:
        if self.project is None:
            self.raw.clear()
            return
        try:
            offset = self._parse_offset(self.offset.text())
            length = self.length.value()
            if offset < 0 or offset + length > len(self.project.working):
                raise ValueError(
                    f"读取范围超出ROM：0x{offset:X} + {length} 字节，"
                    f"ROM长度为 0x{len(self.project.working):X}。"
                )
            payload = bytes(self.project.working[offset : offset + length])
            rows = []
            for row_offset in range(0, len(payload), 16):
                chunk = payload[row_offset : row_offset + 16]
                rows.append(
                    f"{offset + row_offset:06X}: " + chunk.hex(" ").upper()
                )
            self.raw.setPlainText("\n".join(rows))
        except Exception as error:
            QMessageBox.critical(self, "读取失败", str(error))

    def refresh(self) -> None:
        self.read_button.setEnabled(self.project is not None)
        if self.project is None:
            self.raw.clear()


class LegacyGlobalTablesPage(ProjectPage):
    """Verified cumulative-EXP and distance-hit tables from database page five."""

    def __init__(self) -> None:
        super().__init__()
        self._loading = False
        root = QVBoxLayout(self)
        notice = QLabel(
            "已接通参考页中的升级累计经验表和武器距离命中补正表。"
            "系统文字与成长方式仍需独立差分，暂不在此猜写。"
        )
        notice.setWordWrap(True)
        notice.setObjectName("hintText")
        root.addWidget(notice)

        tables = QHBoxLayout()
        experience_group = QGroupBox("升级累计经验 · 等级1—99")
        experience_layout = QVBoxLayout(experience_group)
        self.experience_table = QTableWidget(99, 2)
        self.experience_table.setHorizontalHeaderLabels(("等级", "累计经验"))
        self.experience_table.verticalHeader().setVisible(False)
        self.experience_table.horizontalHeader().setSectionResizeMode(
            1, QHeaderView.ResizeMode.Stretch
        )
        self.experience_table.setAlternatingRowColors(True)
        self.experience_table.itemChanged.connect(self._update_pending_state)
        experience_layout.addWidget(self.experience_table)
        tables.addWidget(experience_group, 2)

        distance_group = QGroupBox("武器距离命中补正 · 距离1—16")
        distance_layout = QVBoxLayout(distance_group)
        self.distance_table = QTableWidget(4, 16)
        self.distance_table.setHorizontalHeaderLabels(
            tuple(str(distance) for distance in range(1, 17))
        )
        self.distance_table.setVerticalHeaderLabels(
            tuple(f"方式 {method}" for method in range(4))
        )
        self.distance_table.horizontalHeader().setSectionResizeMode(
            QHeaderView.ResizeMode.ResizeToContents
        )
        self.distance_table.setAlternatingRowColors(True)
        self.distance_table.itemChanged.connect(self._update_pending_state)
        distance_layout.addWidget(self.distance_table)
        tables.addWidget(distance_group, 5)
        root.addLayout(tables, 1)

        footer = QHBoxLayout()
        self.pending_state = QLabel("当前ROM没有已验证的全局表。")
        self.pending_state.setObjectName("pendingBanner")
        self.apply_button = QPushButton("暂存经验与命中补正")
        self.apply_button.clicked.connect(self.apply_changes)
        self.reset_button = QPushButton("还原两张表")
        self.reset_button.clicked.connect(self.reset_tables)
        footer.addWidget(self.pending_state, 1)
        footer.addWidget(self.apply_button)
        footer.addWidget(self.reset_button)
        root.addLayout(footer)

    @property
    def _is_supported(self) -> bool:
        return bool(
            self.project is not None
            and getattr(self.project, "supports_legacy_global_data", False)
        )

    @staticmethod
    def _editable_item(value: int) -> QTableWidgetItem:
        item = QTableWidgetItem(str(value))
        item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
        return item

    def refresh(self) -> None:
        self._loading = True
        try:
            supported = self._is_supported
            self.experience_table.setEditTriggers(
                QAbstractItemView.EditTrigger.AllEditTriggers
                if supported
                else QAbstractItemView.EditTrigger.NoEditTriggers
            )
            self.distance_table.setEditTriggers(
                QAbstractItemView.EditTrigger.AllEditTriggers
                if supported
                else QAbstractItemView.EditTrigger.NoEditTriggers
            )
            self.apply_button.setEnabled(False)
            self.reset_button.setEnabled(supported)
            if not supported:
                self.experience_table.clearContents()
                self.distance_table.clearContents()
                self.pending_state.setText("当前ROM没有已验证的全局表。")
                return
            experience = self.project.get_experience_totals()
            corrections = self.project.get_distance_hit_corrections()
            for row, value in enumerate(experience):
                level = QTableWidgetItem(str(row + 1))
                level.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                level.setFlags(level.flags() & ~Qt.ItemFlag.ItemIsEditable)
                self.experience_table.setItem(row, 0, level)
                self.experience_table.setItem(row, 1, self._editable_item(value))
            for row, values in enumerate(corrections):
                for column, value in enumerate(values):
                    self.distance_table.setItem(
                        row, column, self._editable_item(value)
                    )
        finally:
            self._loading = False
        self._update_pending_state()

    @staticmethod
    def _parse_cell(
        table: QTableWidget,
        row: int,
        column: int,
        *,
        maximum: int,
        label: str,
    ) -> int:
        item = table.item(row, column)
        text = "" if item is None else item.text().strip()
        try:
            value = int(text, 10)
        except ValueError as error:
            raise ValueError(f"{label}必须是十进制整数。") from error
        if not 0 <= value <= maximum:
            raise ValueError(f"{label}必须在0—{maximum}之间。")
        return value

    def _draft_values(
        self,
    ) -> tuple[tuple[int, ...], tuple[tuple[int, ...], ...]]:
        experience = tuple(
            self._parse_cell(
                self.experience_table,
                row,
                1,
                maximum=0xFFFF,
                label=f"等级{row + 1}累计经验",
            )
            for row in range(99)
        )
        corrections = tuple(
            tuple(
                self._parse_cell(
                    self.distance_table,
                    row,
                    column,
                    maximum=0xFF,
                    label=f"补正方式{row}距离{column + 1}",
                )
                for column in range(16)
            )
            for row in range(4)
        )
        return experience, corrections

    @property
    def has_pending_draft(self) -> bool:
        if not self._is_supported:
            return False
        try:
            experience, corrections = self._draft_values()
        except ValueError:
            return True
        return (
            experience != self.project.get_experience_totals()
            or corrections != self.project.get_distance_hit_corrections()
        )

    @property
    def pending_draft_error(self) -> str | None:
        if not self._is_supported:
            return None
        try:
            self._draft_values()
        except ValueError as error:
            return str(error)
        return None

    def _update_pending_state(self) -> None:
        if self._loading:
            return
        if not self._is_supported:
            self.pending_state.setText("当前ROM没有已验证的全局表。")
            self.apply_button.setEnabled(False)
            return
        error = self.pending_draft_error
        pending = self.has_pending_draft
        self.apply_button.setEnabled(pending and error is None)
        if error is not None:
            self.pending_state.setText(f"● {error}")
        elif pending:
            self.pending_state.setText("● 有尚未暂存的经验/命中补正改动")
        else:
            self.pending_state.setText("✓ 两张表与当前工程一致")

    def commit_pending_changes(self) -> bool:
        if not self.has_pending_draft:
            return True
        if self.pending_draft_error is not None:
            return False
        return self.apply_changes()

    def apply_changes(self) -> bool:
        if not self._is_supported:
            return False
        try:
            experience, corrections = self._draft_values()
            with self.project.transaction("升级经验与距离命中补正"):
                self.project.set_experience_totals(experience)
                self.project.set_distance_hit_corrections(corrections)
            self.project_changed.emit("已更新升级经验与距离命中补正")
            return not self.has_pending_draft
        except Exception as error:
            self.show_error(error)
            return False

    def reset_tables(self) -> None:
        if not self._is_supported:
            return
        try:
            with self.project.transaction("还原升级经验与距离命中补正"):
                self.project.reset_experience_totals()
                self.project.reset_distance_hit_corrections()
            self.project_changed.emit("已还原升级经验与距离命中补正")
        except Exception as error:
            self.show_error(error)


class LegacyItemTablePage(ProjectPage):
    """Verified name/price subset of the reference editor's item page."""

    ITEM_COUNT = 24
    NAME_POOL_CAPACITY = 0xB8
    MAX_DISPLAY_PRICE = 99_990

    def __init__(self) -> None:
        super().__init__()
        self._loading = False
        self._text_table = default_dc_text_table()
        self._loaded_name_records: tuple[bytes, ...] = ()
        self._loaded_name_texts: tuple[str, ...] = ()
        root = QVBoxLayout(self)
        notice = QLabel(
            "已接通24项道具名称和价格。价格按参考窗口显示为ROM原值×10；"
            "说明、F0—FE商店、店员和七段对话尚未完成独立差分，继续只读保护。"
        )
        notice.setWordWrap(True)
        notice.setObjectName("hintText")
        root.addWidget(notice)

        self.item_table = QTableWidget(self.ITEM_COUNT, 3)
        self.item_table.setHorizontalHeaderLabels(("编号", "道具名称", "显示价格"))
        self.item_table.verticalHeader().setVisible(False)
        self.item_table.horizontalHeader().setSectionResizeMode(
            1, QHeaderView.ResizeMode.Stretch
        )
        self.item_table.setColumnWidth(0, 78)
        self.item_table.setColumnWidth(2, 150)
        self.item_table.setAlternatingRowColors(True)
        self.item_table.itemChanged.connect(self._update_pending_state)
        root.addWidget(self.item_table, 1)

        protected = QGroupBox("尚未验证的参考字段")
        protected_layout = QFormLayout(protected)
        for label in ("道具说明", "商店 F0—FE", "店员及七段对话"):
            value = QLineEdit("只读：尚无独立可写记录证据")
            value.setReadOnly(True)
            value.setToolTip("需先用参考程序对隔离副本做单变量保存差分。")
            protected_layout.addRow(label, value)
        root.addWidget(protected)

        footer = QHBoxLayout()
        self.pending_state = QLabel("当前ROM没有已验证的道具表。")
        self.pending_state.setObjectName("pendingBanner")
        self.apply_button = QPushButton("暂存道具名称与价格")
        self.apply_button.clicked.connect(self.apply_changes)
        self.reset_button = QPushButton("还原名称与价格")
        self.reset_button.clicked.connect(self.reset_items)
        footer.addWidget(self.pending_state, 1)
        footer.addWidget(self.apply_button)
        footer.addWidget(self.reset_button)
        root.addLayout(footer)

    @property
    def _is_supported(self) -> bool:
        return bool(
            self.project is not None
            and getattr(self.project, "supports_legacy_global_data", False)
            and hasattr(self.project, "get_item_name_records")
        )

    @staticmethod
    def _fixed_item(text: str) -> QTableWidgetItem:
        item = QTableWidgetItem(text)
        item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
        item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEditable)
        return item

    def refresh(self) -> None:
        self._loading = True
        try:
            supported = self._is_supported
            self.item_table.setEditTriggers(
                QAbstractItemView.EditTrigger.AllEditTriggers
                if supported
                else QAbstractItemView.EditTrigger.NoEditTriggers
            )
            self.apply_button.setEnabled(False)
            self.reset_button.setEnabled(supported)
            if not supported:
                self._loaded_name_records = ()
                self._loaded_name_texts = ()
                self.item_table.clearContents()
                self.pending_state.setText("当前ROM没有已验证的道具名称/价格表。")
                return
            names = self.project.get_item_name_records()
            prices = self.project.get_item_prices()
            name_texts = tuple(self._text_table.decode(raw_name) for raw_name in names)
            self._loaded_name_records = names
            self._loaded_name_texts = name_texts
            for row, (name_text, raw_price) in enumerate(zip(name_texts, prices)):
                self.item_table.setItem(row, 0, self._fixed_item(f"{row + 1:02d}"))
                self.item_table.setItem(row, 1, QTableWidgetItem(name_text))
                price = QTableWidgetItem(str(raw_price * 10))
                price.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
                self.item_table.setItem(row, 2, price)
        finally:
            self._loading = False
        self._update_pending_state()

    def _draft_values(self) -> tuple[tuple[bytes, ...], tuple[int, ...]]:
        names: list[bytes] = []
        prices: list[int] = []
        for row in range(self.ITEM_COUNT):
            name_item = self.item_table.item(row, 1)
            name = "" if name_item is None else name_item.text()
            if not name:
                raise ValueError(f"道具 {row + 1:02d} 的名称不能为空。")
            if (
                row < len(self._loaded_name_texts)
                and row < len(self._loaded_name_records)
                and name == self._loaded_name_texts[row]
            ):
                # Several visually identical glyphs have both compact and
                # two-byte encodings.  Reuse the exact source bytes until the
                # user actually changes this row, otherwise merely opening
                # the page would silently canonicalize ROM data.
                raw_name = self._loaded_name_records[row]
            else:
                try:
                    raw_name = self._text_table.encode_preserving_tokens(
                        self._loaded_name_records[row],
                        name,
                    )
                except ValueError as error:
                    raise ValueError(f"道具 {row + 1:02d} 名称：{error}") from error
            if b"\xFF" in raw_name:
                raise ValueError(f"道具 {row + 1:02d} 名称不能包含结束符。")
            names.append(raw_name)

            price_item = self.item_table.item(row, 2)
            price_text = "" if price_item is None else price_item.text().strip()
            try:
                display_price = int(price_text, 10)
            except ValueError as error:
                raise ValueError(f"道具 {row + 1:02d} 价格必须是十进制整数。") from error
            if not 0 <= display_price <= self.MAX_DISPLAY_PRICE:
                raise ValueError(
                    f"道具 {row + 1:02d} 显示价格必须在0—{self.MAX_DISPLAY_PRICE}之间。"
                )
            if display_price % 10:
                raise ValueError(f"道具 {row + 1:02d} 显示价格必须是10的倍数。")
            prices.append(display_price // 10)

        used = sum(len(name) + 1 for name in names)
        if used > self.NAME_POOL_CAPACITY:
            raise ValueError(
                f"24项道具名称编码后共需{used}字节，超过名称池{self.NAME_POOL_CAPACITY}字节。"
            )
        return tuple(names), tuple(prices)

    @property
    def has_pending_draft(self) -> bool:
        if not self._is_supported:
            return False
        try:
            names, prices = self._draft_values()
        except ValueError:
            return True
        return (
            names != self.project.get_item_name_records()
            or prices != self.project.get_item_prices()
        )

    @property
    def pending_draft_error(self) -> str | None:
        if not self._is_supported:
            return None
        try:
            self._draft_values()
        except ValueError as error:
            return str(error)
        return None

    def _update_pending_state(self) -> None:
        if self._loading:
            return
        if not self._is_supported:
            self.pending_state.setText("当前ROM没有已验证的道具名称/价格表。")
            self.apply_button.setEnabled(False)
            return
        error = self.pending_draft_error
        pending = self.has_pending_draft
        self.apply_button.setEnabled(pending and error is None)
        if error is not None:
            self.pending_state.setText(f"● {error}")
        elif pending:
            self.pending_state.setText("● 有尚未暂存的道具名称/价格改动")
        else:
            self.pending_state.setText("✓ 道具名称与价格和当前工程一致")

    def commit_pending_changes(self) -> bool:
        if not self.has_pending_draft:
            return True
        if self.pending_draft_error is not None:
            return False
        return self.apply_changes()

    def apply_changes(self) -> bool:
        if not self._is_supported:
            return False
        try:
            names, prices = self._draft_values()
            current_names = self.project.get_item_name_records()
            current_prices = self.project.get_item_prices()
            with self.project.transaction("道具名称与价格"):
                if names != current_names:
                    self.project.set_item_name_records(names)
                if prices != current_prices:
                    self.project.set_item_prices(prices)
            self.project_changed.emit("已更新道具名称与价格")
            return not self.has_pending_draft
        except Exception as error:
            self.show_error(error)
            return False

    def reset_items(self) -> None:
        if not self._is_supported:
            return
        try:
            with self.project.transaction("还原道具名称与价格"):
                self.project.reset_item_name_records()
                self.project.reset_item_prices()
            self.project_changed.emit("已还原道具名称与价格")
        except Exception as error:
            self.show_error(error)


class DatabaseDialog(TransactionalProjectDialog):
    """The six-tab database window used by the reference SRW2 workflow."""

    TAB_LABELS = (
        "机体修改",
        "人物修改",
        "武器修改",
        "战斗对话",
        "其他修改1",
        "其他修改2",
    )

    def __init__(
        self,
        project: RomProject | None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(project, title="数据库", parent=parent)
        self.resize(1500, 970)
        self.setMinimumSize(1050, 700)

        layout = QVBoxLayout(self)
        self.tabs = QTabWidget()
        self.tabs.setObjectName("legacyDatabaseTabs")

        self.unit_page = self.register_page(LegacyUnitDatabasePage())
        self.character_page = self.register_page(CharacterPage())
        self.weapon_page = self.register_page(WeaponPage())
        assert isinstance(self.unit_page, LegacyUnitDatabasePage)
        assert isinstance(self.character_page, CharacterPage)
        assert isinstance(self.weapon_page, WeaponPage)
        self.unit_page.weapon_requested.connect(self._select_weapon)

        self.battle_dialogue_page = self.register_page(
            RawInspectionPage(
                "战斗对话",
                ("进攻战斗对话", "防御战斗对话"),
                "已确认旧版在此编辑进攻/防御战斗对话，但当前ROM的逐字段结构尚未验证。"
                "为避免破坏脚本，本页只允许查看原始字节。",
            )
        )
        self.other_page_1 = self.register_page(LegacyGlobalTablesPage())
        self.other_page_2 = self.register_page(LegacyItemTablePage())

        for label, page in zip(self.TAB_LABELS, self.pages):
            self.tabs.addTab(page, label)
        layout.addWidget(self.tabs, 1)

        footer = QHBoxLayout()
        self.database_search = QLineEdit()
        self.database_search.setPlaceholderText("查找名称或ID")
        self.find_next_button = QPushButton("查找下一个")
        self.find_previous_button = QPushButton("查找上一个")
        self.ok_button = QPushButton("确定")
        self.cancel_button = QPushButton("取消")
        self.ok_button.setDefault(True)
        self.ok_button.clicked.connect(self.accept)
        self.cancel_button.clicked.connect(self.reject)
        self.database_search.textChanged.connect(self._sync_active_search)
        self.find_next_button.clicked.connect(lambda: self._select_relative(1))
        self.find_previous_button.clicked.connect(lambda: self._select_relative(-1))
        self.tabs.currentChanged.connect(
            lambda _index: self._sync_active_search(self.database_search.text())
        )
        footer.addWidget(self.database_search, 1)
        footer.addWidget(self.find_next_button)
        footer.addWidget(self.find_previous_button)
        footer.addStretch()
        footer.addWidget(self.ok_button)
        footer.addWidget(self.cancel_button)
        layout.addLayout(footer)

        self._prepare_record_page(self.character_page, "暂存当前人物")
        self._prepare_record_page(self.weapon_page, "暂存当前武器")

    @staticmethod
    def _prepare_record_page(page: ProjectPage, apply_caption: str) -> None:
        """Adapt reusable record pages to the reference list/search shell."""

        search_panel = getattr(page, "search_panel", None)
        if isinstance(search_panel, QWidget):
            search_panel.hide()
        apply_button = getattr(page, "apply_button", None)
        if isinstance(apply_button, QPushButton):
            apply_button.setText(apply_caption)
            apply_button.setToolTip(
                "先暂存到本窗口会话；按窗口底部“确定”保留，按“取消”全部回滚。"
            )
        pending_state = getattr(page, "pending_state", None)
        if isinstance(pending_state, QWidget):
            pending_state.hide()
        splitter = page.findChild(QSplitter)
        if splitter is None or splitter.count() < 1:
            return
        selection_layout = splitter.widget(0).layout()
        if not isinstance(selection_layout, QVBoxLayout):
            return
        add_button = QPushButton("添加")
        add_button.setEnabled(False)
        add_button.setToolTip("新增记录的指针重定位规则尚未验证。")
        selection_layout.addWidget(add_button)

    def _select_weapon(self, weapon_id: int) -> None:
        self.tabs.setCurrentIndex(2)
        for row in range(self.weapon_page.records.count()):
            item = self.weapon_page.records.item(row)
            if int(item.data(Qt.ItemDataRole.UserRole)) == weapon_id:
                self.weapon_page.records.setCurrentRow(row)
                self.weapon_page.records.scrollToItem(item)
                break

    def _active_search_page(self) -> ProjectPage | None:
        current = self.tabs.currentWidget()
        return current if isinstance(current, ProjectPage) else None

    def _sync_active_search(self, text: str) -> None:
        page = self._active_search_page()
        search = getattr(page, "search", None)
        if isinstance(search, QLineEdit) and search.text() != text:
            search.setText(text)

    def _select_relative(self, direction: int) -> None:
        page = self._active_search_page()
        callback = getattr(page, "_select_relative", None)
        if callable(callback):
            callback(direction)

    def _forward_navigation(self, page_key: str) -> None:
        index_by_key = {"units": 0, "characters": 1, "weapons": 2}
        if page_key in index_by_key:
            self.tabs.setCurrentIndex(index_by_key[page_key])
        super()._forward_navigation(page_key)

    def _commit_current_form(self) -> bool:
        page = self.tabs.currentWidget()
        commit_pending = getattr(page, "commit_pending", None)
        if callable(commit_pending):
            return bool(commit_pending())
        if isinstance(page, (CharacterPage, WeaponPage)):
            if page.project is None or page.current_id is None:
                return False
            if page.name_reference.isEnabled() and page.name_reference.currentData() is None:
                return False
            if isinstance(page, CharacterPage) and any(
                editor.isEnabled() and editor.currentData() is None
                for editor in (page.ally_music, page.enemy_music)
            ):
                return False
            if not page.apply_button.isEnabled():
                return True
            page.apply_record()
            return not page.apply_button.isEnabled()
        return True

    def accept(self) -> None:
        if not self._commit_current_form():
            QMessageBox.warning(
                self,
                "无法确认数据库修改",
                "当前表单包含无法提交的内容，请修正后重试；窗口尚未关闭。",
            )
            return
        super().accept()


class ScenarioDialog(TransactionalProjectDialog):
    """Reference-shaped scenario window backed by hidden verified editors."""

    TAB_LABELS = (
        "关卡设置",
        "行动事件",
        "劝降事件",
        "地图事件",
        "剧情对话",
        "胜利文字",
    )
    EVENT_TAB_LABELS = ("界面事件", "回合事件", "即时事件")

    def __init__(
        self,
        project: RomProject | None,
        parent: QWidget | None = None,
        *,
        initial_scenario_id: int | None = None,
    ) -> None:
        super().__init__(project, title="事件编辑", parent=parent)
        inherited = getattr(getattr(parent, "map_page", None), "current_map_id", None)
        requested = initial_scenario_id if initial_scenario_id is not None else inherited
        self.initial_scenario_id = int(requested) if requested is not None else 0
        self.current_scenario_id: int | None = None
        self.setFixedSize(1490, 966)

        self.setup_event_pages = [
            self._register_hidden_event_page(phase) for phase in range(3)
        ]
        self.action_event_page = self._register_hidden_page(_LegacyEventController())
        self.persuasion_page = self._register_hidden_page(PersuasionPage())
        self.map_event_page = self._register_hidden_page(_LegacyEventController())
        self.story_page = self._register_hidden_page(StoryPage())
        self.victory_page = self._register_hidden_page(StoryPage())

        assert isinstance(self.action_event_page, EventPage)
        assert isinstance(self.persuasion_page, PersuasionPage)
        assert isinstance(self.map_event_page, EventPage)
        assert isinstance(self.story_page, StoryPage)
        assert isinstance(self.victory_page, StoryPage)

        self.chapter_context = self._build_chapter_context()
        setup = self._build_setup_page()
        action = self._build_event_overview(
            "行动事件", self.action_event_page, "action_event_list"
        )
        persuasion = self._build_persuasion_overview()
        map_events = self._build_event_overview(
            "地图事件", self.map_event_page, "map_event_list"
        )
        story = self._build_story_overview(
            "剧情对话",
            self.story_page,
            "story_overview_list",
            "当前ROM尚无剧情文本到关卡的已验证索引；列表按原始文本组显示。",
        )
        victory = self._build_story_overview(
            "胜利文字",
            self.victory_page,
            "victory_overview_list",
            "胜利文字的独立关卡索引尚未验证；不会按当前关卡猜测绑定。",
        )

        layout = QVBoxLayout(self)
        self.tabs = QTabWidget()
        self.tabs.setObjectName("legacyScenarioTabs")
        self._splitters: list[QSplitter] = []
        for label, page in zip(
            self.TAB_LABELS, (setup, action, persuasion, map_events, story, victory)
        ):
            splitter = QSplitter()
            splitter.setChildrenCollapsible(False)
            splitter.addWidget(page)
            self._splitters.append(splitter)
            self.tabs.addTab(splitter, label)
        layout.addWidget(self.tabs, 1)

        footer = QHBoxLayout()
        self.space_button = QPushButton("检查剧情剩余空间")
        self.space_button.clicked.connect(self._show_story_capacity)
        self.ok_button = QPushButton("确定")
        self.cancel_button = QPushButton("取消")
        self.ok_button.setDefault(True)
        self.ok_button.clicked.connect(self.accept)
        self.cancel_button.clicked.connect(self.reject)
        footer.addWidget(self.space_button)
        footer.addStretch()
        footer.addWidget(self.ok_button)
        footer.addWidget(self.cancel_button)
        layout.addLayout(footer)

        self.tabs.currentChanged.connect(self._move_chapter_context)
        self.chapter_list.currentItemChanged.connect(self._chapter_changed)
        self._configure_event_views()
        self._move_chapter_context(0)
        self._populate_chapters()

    def _register_hidden_page(self, page: ProjectPage) -> ProjectPage:
        registered = self.register_page(page)
        registered.setParent(self)
        registered.hide()
        registered.project_changed.connect(lambda _message: self._refresh_overviews())
        return registered

    def _register_hidden_event_page(self, phase: int) -> EventPage:
        page = self._register_hidden_page(_LegacyEventController())
        assert isinstance(page, EventPage)
        page.setProperty("legacyPhase", phase)
        return page

    def _build_chapter_context(self) -> QWidget:
        context = QWidget()
        context.setObjectName("sharedChapterContext")
        context.setMinimumWidth(390)
        context.setMaximumWidth(430)
        context_layout = QVBoxLayout(context)
        context_layout.setContentsMargins(5, 5, 5, 5)

        settings = QGroupBox("基本设置")
        settings_layout = QVBoxLayout(settings)
        settings_layout.addWidget(QLabel("标题:"))
        self.chapter_title = QLineEdit()
        self.chapter_title.setReadOnly(True)
        settings_layout.addWidget(self.chapter_title)
        settings_layout.addWidget(QLabel("初始胜利文字:"))
        self.initial_victory = QPlainTextEdit()
        self.initial_victory.setReadOnly(True)
        self.initial_victory.setMaximumHeight(118)
        settings_layout.addWidget(self.initial_victory)
        context_layout.addWidget(settings)

        selector = QGroupBox("关卡选择")
        selector_layout = QVBoxLayout(selector)
        self.chapter_list = QListWidget()
        self.chapter_list.setAlternatingRowColors(True)
        self.chapter_list.setUniformItemSizes(True)
        selector_layout.addWidget(self.chapter_list)
        context_layout.addWidget(selector, 1)
        return context

    def _build_setup_page(self) -> QWidget:
        page = QWidget()
        page_layout = QVBoxLayout(page)
        page_layout.setContentsMargins(5, 5, 5, 5)

        title_art = QGroupBox("标题拼图设置")
        title_layout = QHBoxLayout(title_art)
        self.title_preview = QLabel("请选择关卡")
        self.title_preview.setObjectName("legacyScenarioTitlePreview")
        self.title_preview.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.title_preview.setMinimumHeight(84)
        self.title_preview.setStyleSheet("background: black; border: 1px solid #202020;")
        self.title_code_button = QPushButton("代码编辑")
        self.title_code_button.setEnabled(False)
        self.title_code_button.setToolTip(
            "标题拼图脚本地址和写入规则尚未完成差分验证。"
        )
        title_layout.addWidget(self.title_preview, 1)
        title_layout.addWidget(self.title_code_button)
        page_layout.addWidget(title_art)

        event_group = QGroupBox("事件编辑")
        event_layout = QVBoxLayout(event_group)
        self.setup_event_tabs = QTabWidget()
        self.setup_event_tabs.setObjectName("legacyScenarioEventTabs")
        self.setup_event_lists: list[QListWidget] = []
        self.setup_code_buttons: list[QPushButton] = []
        for label, controller in zip(self.EVENT_TAB_LABELS, self.setup_event_pages):
            host, overview, button = self._event_list_panel(controller)
            self.setup_event_lists.append(overview)
            self.setup_code_buttons.append(button)
            self.setup_event_tabs.addTab(host, label)
        event_layout.addWidget(self.setup_event_tabs)
        page_layout.addWidget(event_group, 1)
        return page

    def _event_list_panel(
        self, controller: EventPage
    ) -> tuple[QWidget, QListWidget, QPushButton]:
        host = QWidget()
        layout = QVBoxLayout(host)
        layout.setContentsMargins(3, 3, 3, 3)
        overview = QListWidget()
        overview.setAlternatingRowColors(True)
        overview.setUniformItemSizes(True)
        overview.currentItemChanged.connect(
            lambda current, _previous, page=controller: self._select_event_item(
                page, current
            )
        )
        button = QPushButton("代码编辑")
        button.clicked.connect(
            lambda _checked=False, page=controller: self._open_advanced_editor(
                page, "事件代码编辑"
            )
        )
        overview.itemDoubleClicked.connect(
            lambda _item, page=controller: self._open_advanced_editor(
                page, "事件代码编辑"
            )
        )
        layout.addWidget(overview, 1)
        layout.addWidget(button, 0, Qt.AlignmentFlag.AlignLeft)
        return host, overview, button

    def _build_event_overview(
        self, title: str, controller: EventPage, attribute_name: str
    ) -> QWidget:
        host = QWidget()
        layout = QVBoxLayout(host)
        group = QGroupBox(title)
        group_layout = QVBoxLayout(group)
        panel, overview, button = self._event_list_panel(controller)
        group_layout.addWidget(panel)
        layout.addWidget(group)
        setattr(self, attribute_name, overview)
        setattr(self, f"{attribute_name}_code_button", button)
        return host

    def _build_persuasion_overview(self) -> QWidget:
        host = QWidget()
        layout = QVBoxLayout(host)
        group = QGroupBox("劝降事件")
        group_layout = QVBoxLayout(group)
        self.persuasion_overview_list = QListWidget()
        self.persuasion_overview_list.setAlternatingRowColors(True)
        self.persuasion_overview_list.currentItemChanged.connect(
            self._select_persuasion_item
        )
        self.persuasion_code_button = QPushButton("代码编辑")
        self.persuasion_code_button.clicked.connect(
            lambda: self._open_advanced_editor(self.persuasion_page, "劝降事件编辑")
        )
        self.persuasion_overview_list.itemDoubleClicked.connect(
            lambda _item: self._open_advanced_editor(
                self.persuasion_page, "劝降事件编辑"
            )
        )
        group_layout.addWidget(self.persuasion_overview_list, 1)
        group_layout.addWidget(
            self.persuasion_code_button, 0, Qt.AlignmentFlag.AlignLeft
        )
        layout.addWidget(group)
        return host

    def _build_story_overview(
        self,
        title: str,
        controller: StoryPage,
        attribute_name: str,
        note_text: str,
    ) -> QWidget:
        host = QWidget()
        layout = QVBoxLayout(host)
        group = QGroupBox(title)
        group_layout = QVBoxLayout(group)
        overview = QListWidget()
        overview.setAlternatingRowColors(True)
        overview.currentItemChanged.connect(
            lambda current, _previous, page=controller: self._select_story_item(
                page, current
            )
        )
        button = QPushButton("代码编辑")
        button.clicked.connect(
            lambda _checked=False, page=controller, caption=title: self._open_advanced_editor(
                page, caption
            )
        )
        overview.itemDoubleClicked.connect(
            lambda _item, page=controller, caption=title: self._open_advanced_editor(
                page, caption
            )
        )
        note = QLabel(note_text)
        note.setObjectName("hintText")
        note.setMaximumHeight(24)
        note.setToolTip(note_text)
        group_layout.addWidget(overview, 1)
        group_layout.addWidget(button, 0, Qt.AlignmentFlag.AlignLeft)
        group_layout.addWidget(note)
        layout.addWidget(group)
        setattr(self, attribute_name, overview)
        setattr(self, f"{attribute_name}_code_button", button)
        return host

    def _configure_event_views(self) -> None:
        for phase, page in enumerate(self.setup_event_pages):
            index = page.phase_filter.findData(phase)
            if index >= 0:
                page.phase_filter.setCurrentIndex(index)
        action_index = self.action_event_page.kind_filter.findText("行动控制")
        if action_index >= 0:
            self.action_event_page.kind_filter.setCurrentIndex(action_index)
        map_index = self.map_event_page.kind_filter.findText("触发条件与行动判定")
        if map_index >= 0:
            self.map_event_page.kind_filter.setCurrentIndex(map_index)

    def _move_chapter_context(self, tab_index: int) -> None:
        if not 0 <= tab_index < len(self._splitters):
            return
        splitter = self._splitters[tab_index]
        splitter.insertWidget(0, self.chapter_context)
        splitter.setSizes([410, 1050])

    @staticmethod
    def _select_list_data(overview: QListWidget, value: Any) -> bool:
        """Select one semantic list value without re-entering navigation slots."""

        previous = overview.blockSignals(True)
        try:
            if value is None:
                overview.setCurrentRow(-1)
                return True
            for row in range(overview.count()):
                item = overview.item(row)
                if item.data(Qt.ItemDataRole.UserRole) == value:
                    overview.setCurrentRow(row)
                    return True
            return False
        finally:
            overview.blockSignals(previous)

    def _guard_hidden_navigation(
        self,
        pages: tuple[ProjectPage, ...],
        restore_selection: Callable[[], None],
        destination: str,
    ) -> bool:
        """Commit hidden drafts before changing an outer legacy selection.

        The outer lists are only projections of the real hidden editors.  Qt
        changes their selection before delivering ``currentItemChanged``, so
        restore the projection first.  This keeps both layers aligned while a
        draft is validated and while page commit signals refresh the lists.
        """

        pending = tuple(page for page in pages if page.has_pending_draft)
        if not pending:
            return True

        restore_selection()
        for page in pending:
            error = page.pending_draft_error
            if error is not None:
                QMessageBox.warning(
                    self,
                    f"无法切换{destination}",
                    error,
                )
                return False

        for page in pending:
            if page.commit_pending_changes():
                continue
            restore_selection()
            QMessageBox.warning(
                self,
                f"无法切换{destination}",
                page.pending_draft_error
                or "当前隐藏编辑页仍有无法提交的输入，请修正后重试。",
            )
            return False
        return True

    def _populate_chapters(self) -> None:
        requested = self.current_scenario_id
        if requested is None:
            requested = self.initial_scenario_id
        self.chapter_list.blockSignals(True)
        self.chapter_list.clear()
        if self.project is not None:
            count = min(0x20, self.project.profile.map_count)
            for scenario_id in range(count):
                item = QListWidgetItem(
                    f"{scenario_id + 1:03d}: {dc_map_label(scenario_id)}"
                )
                item.setData(Qt.ItemDataRole.UserRole, scenario_id)
                self.chapter_list.addItem(item)
        self.chapter_list.blockSignals(False)
        if self.chapter_list.count():
            selected = 0
            for row in range(self.chapter_list.count()):
                if self.chapter_list.item(row).data(Qt.ItemDataRole.UserRole) == requested:
                    selected = row
                    break
            self.chapter_list.setCurrentRow(selected)
            self._chapter_changed(self.chapter_list.currentItem(), None)
        else:
            self.current_scenario_id = None
            self.chapter_title.clear()
            self.initial_victory.clear()
            self.title_preview.clear()
            self.title_preview.setText("请选择关卡")

    def _chapter_changed(
        self,
        current: QListWidgetItem | None,
        _previous: QListWidgetItem | None,
    ) -> None:
        if current is None:
            return
        scenario_id = int(current.data(Qt.ItemDataRole.UserRole))
        previous_scenario_id = self.current_scenario_id
        if (
            previous_scenario_id is not None
            and scenario_id != previous_scenario_id
        ):
            restore = lambda: self._select_list_data(
                self.chapter_list, previous_scenario_id
            )
            synchronized_pages = (
                *self.setup_event_pages,
                self.action_event_page,
                self.map_event_page,
                self.persuasion_page,
            )
            if not self._guard_hidden_navigation(
                synchronized_pages,
                restore,
                "关卡",
            ):
                return
            # A successful commit refreshes the overview lists and can also
            # restore the old visible chapter.  Re-apply the requested row
            # without recursively entering this slot.
            self._select_list_data(self.chapter_list, scenario_id)
        self.current_scenario_id = scenario_id
        label = dc_map_label(scenario_id)
        self.chapter_title.setText(label)
        self.initial_victory.setPlainText(
            "胜利文字关卡索引尚未验证；请在“胜利文字”页按原始文本组定位。"
        )
        self.title_preview.clear()
        if self.project is not None:
            self.title_preview.setPixmap(render_map_title(self.project, label, scale=4))
        else:
            self.title_preview.setText(label)

        for page in (
            *self.setup_event_pages,
            self.action_event_page,
            self.map_event_page,
        ):
            if page.has_pending_draft:
                continue
            index = page.scenario_filter.findData(scenario_id)
            if index >= 0:
                page.scenario_filter.setCurrentIndex(index)
        self._focus_persuasion(scenario_id)
        self._refresh_overviews()

    @staticmethod
    def _event_semantic_text(page: EventPage, instruction: Any, index: int) -> str:
        parameters = page._parameter_text(instruction)
        suffix = f"：{parameters}" if parameters != "—" else ""
        terminal = " · 结束" if instruction.is_terminal else ""
        return f"{index:03d}: {instruction.action_label}{suffix}{terminal}"

    def _refresh_event_overview(
        self, page: EventPage, overview: QListWidget
    ) -> None:
        previous = page.current_address
        instructions = tuple(page._visible_instructions())
        overview.blockSignals(True)
        overview.clear()
        selected_row = 0
        for index, instruction in enumerate(instructions):
            item = QListWidgetItem(self._event_semantic_text(page, instruction, index))
            item.setData(Qt.ItemDataRole.UserRole, instruction.address)
            item.setToolTip(
                f"地址 ${instruction.address:04X} · {instruction.raw.hex(' ').upper()}"
            )
            overview.addItem(item)
            if instruction.address == previous:
                selected_row = index
        if overview.count():
            overview.setCurrentRow(selected_row)
        overview.blockSignals(False)
        if overview.currentItem() is not None:
            self._select_event_item(page, overview.currentItem())

    @staticmethod
    def _select_event_item(page: EventPage, item: QListWidgetItem | None) -> None:
        if item is not None:
            page._select_address(int(item.data(Qt.ItemDataRole.UserRole)))

    def _refresh_persuasion_overview(self) -> None:
        overview = self.persuasion_overview_list
        current_slot = self.persuasion_page.current_slot
        overview.blockSignals(True)
        overview.clear()
        selected_row = 0
        if self.project is not None and self.project.supports_persuasion_rules:
            count = self.project.persuasion_rule_codec.spec.editable_count
            for slot in range(count):
                rule = self.project.get_persuasion_rule(slot)
                item = QListWidgetItem(
                    f"{slot:03d}: {dc_map_label(rule.scenario_id)} · "
                    f"{self.project.character_display_name(rule.persuader_id)} → "
                    f"{self.project.character_display_name(rule.target_id)} · "
                    f"成功脚本 ${rule.script_address:04X}"
                )
                item.setData(Qt.ItemDataRole.UserRole, slot)
                overview.addItem(item)
                if slot == current_slot:
                    selected_row = slot
        if overview.count():
            overview.setCurrentRow(min(selected_row, overview.count() - 1))
        overview.blockSignals(False)

    def _select_persuasion_item(
        self,
        current: QListWidgetItem | None,
        _previous: QListWidgetItem | None,
    ) -> None:
        if current is None:
            return
        slot = int(current.data(Qt.ItemDataRole.UserRole))
        previous_slot = self.persuasion_page.current_slot
        if previous_slot is not None and slot != previous_slot:
            restore = lambda: self._select_list_data(
                self.persuasion_overview_list, previous_slot
            )
            if not self._guard_hidden_navigation(
                (self.persuasion_page,),
                restore,
                "劝降事件",
            ):
                return
            self._select_list_data(self.persuasion_overview_list, slot)
        for row in range(self.persuasion_page.table.rowCount()):
            item = self.persuasion_page.table.item(row, 0)
            if item is not None and item.data(Qt.ItemDataRole.UserRole) == slot:
                self.persuasion_page.table.selectRow(row)
                return

    def _focus_persuasion(self, scenario_id: int) -> None:
        if (
            self.project is None
            or not self.project.supports_persuasion_rules
            or self.persuasion_page.has_pending_draft
        ):
            return
        count = self.project.persuasion_rule_codec.spec.editable_count
        for slot in range(count):
            if self.project.get_persuasion_rule(slot).scenario_id != scenario_id:
                continue
            for row in range(self.persuasion_page.table.rowCount()):
                item = self.persuasion_page.table.item(row, 0)
                if item is not None and item.data(Qt.ItemDataRole.UserRole) == slot:
                    self.persuasion_page.table.selectRow(row)
                    self.persuasion_overview_list.setCurrentRow(row)
                    return

    @staticmethod
    def _refresh_story_overview(page: StoryPage, overview: QListWidget) -> None:
        current_index = page.current_index
        overview.blockSignals(True)
        overview.clear()
        selected = 0
        group = page.selector.currentText()
        for row in range(page.indices.count()):
            source = page.indices.item(row)
            item = QListWidgetItem(f"{row:03d}: {source.text()}")
            item.setData(Qt.ItemDataRole.UserRole, source.data(Qt.ItemDataRole.UserRole))
            item.setToolTip(group)
            overview.addItem(item)
            if source.data(Qt.ItemDataRole.UserRole) == current_index:
                selected = row
        if overview.count():
            overview.setCurrentRow(selected)
        overview.blockSignals(False)

    def _select_story_item(
        self, page: StoryPage, item: QListWidgetItem | None
    ) -> None:
        if item is None:
            return
        target = item.data(Qt.ItemDataRole.UserRole)
        overview = (
            self.story_overview_list
            if page is self.story_page
            else self.victory_overview_list
        )
        previous_index = page.current_index
        if previous_index is not None and target != previous_index:
            restore = lambda: self._select_list_data(overview, previous_index)
            if not self._guard_hidden_navigation(
                (page,),
                restore,
                "剧情对话" if page is self.story_page else "胜利文字",
            ):
                return
            self._select_list_data(overview, target)
        for row in range(page.indices.count()):
            if page.indices.item(row).data(Qt.ItemDataRole.UserRole) == target:
                page.indices.setCurrentRow(row)
                return

    def _refresh_overviews(self) -> None:
        if not hasattr(self, "setup_event_lists"):
            return
        for page, overview in zip(self.setup_event_pages, self.setup_event_lists):
            self._refresh_event_overview(page, overview)
        self._refresh_event_overview(self.action_event_page, self.action_event_list)
        self._refresh_event_overview(self.map_event_page, self.map_event_list)
        self._refresh_persuasion_overview()
        self._refresh_story_overview(self.story_page, self.story_overview_list)
        self._refresh_story_overview(self.victory_page, self.victory_overview_list)

    def _open_advanced_editor(self, page: ProjectPage, title: str) -> None:
        popup = QDialog(self)
        popup.setWindowTitle(title)
        popup.setModal(True)
        popup.resize(1220, 820)
        layout = QVBoxLayout(popup)
        page.setParent(popup)
        layout.addWidget(page, 1)
        page.show()
        done = QPushButton("返回事件窗口")
        done.clicked.connect(popup.accept)
        layout.addWidget(done, 0, Qt.AlignmentFlag.AlignRight)
        try:
            popup.exec()
        finally:
            layout.removeWidget(page)
            page.hide()
            page.setParent(self)
            self._refresh_overviews()

    def _show_story_capacity(self) -> None:
        if self.project is None:
            return
        plan = self.project.expansion_plan
        if plan is None:
            detail = "尚未建立扩展容量规划。"
        else:
            capacity = len(plan.story_banks) * 0x2000
            used = len(plan.expanded_story_selectors) * 0x4000
            detail = (
                f"剧情专用配额：{capacity // 1024} KiB\n"
                f"已绑定文本组：{len(plan.expanded_story_selectors)} 组（{used // 1024} KiB）\n"
                f"尚可绑定：{max(0, capacity - used) // 1024} KiB"
            )
        QMessageBox.information(
            self,
            "剧情剩余空间",
            detail + "\n具体占用和冲突请以完整检查结果为准。",
        )

    def set_project(self, project: RomProject | None) -> None:
        super().set_project(project)
        self._configure_event_views()
        self._populate_chapters()
        self._refresh_overviews()
