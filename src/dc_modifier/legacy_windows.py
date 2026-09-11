from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QPixmap, QShowEvent
from PySide6.QtWidgets import (
    QAbstractItemView,
    QComboBox,
    QDialog,
    QFileDialog,
    QFormLayout,
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
    QScrollArea,
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
from fc_editor.unit_package import UnitPackage
from fc_rom_editor_core import RomProject

from .event_page import EventPage
from .database_graphics import palette_color, read_unit_appearance, render_chr_banks
from .database_records import (
    ReadableCharacterPage, ReadableWeaponPage, collapsible_details, readable_references,
)
from .map_page import render_map_title, render_unit_icon_bank
from .pages import CharacterPage, ProjectPage, UnitPage, WeaponPage
from .persuasion_page import PersuasionPage
from .story_page import StoryPage
from .unit_packages import affected_unit_ids, apply_unit_package, package_from_project
from .unit_appearance_dialog import UnitAppearanceDialog
from .legacy_text_pages import LegacyGrowthPage, LegacyShopPage, LegacyTextPage, LegacyScenarioEventsPage
from .workspace import default_export_path, writable_output_path


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
        source_keys = set(getattr(source, "pending_draft_keys", ()))
        if source_key is not None:
            source_keys.add(source_key)
        if not source_keys:
            return None
        for sibling in self.pages:
            if sibling is source:
                continue
            sibling_keys = set(getattr(sibling, "pending_draft_keys", ()))
            sibling_key = getattr(sibling, "pending_draft_key", None)
            if sibling_key is not None:
                sibling_keys.add(sibling_key)
            common = source_keys & sibling_keys
            if common:
                conflict_key = next(iter(common))
                if conflict_key[0] == "chapter_event":
                    return (
                        f"同一事件指令 ${conflict_key[1]:04X} 同时存在于多个"
                        "编辑页的未提交草稿中。请先保留其中一份并还原"
                        "另一份，再重试。"
                    )
                return (
                    "同一ROM记录同时存在于多个编辑页的未提交草稿中。"
                    "请先保留其中一份并还原另一份，再重试。"
                )
        return None

    def set_project(self, project: RomProject | None) -> None:
        self.project = project
        self._snapshot = None
        self._session_active = False
        for page in self.pages:
            discard = getattr(page, "discard_pending_changes", None)
            if callable(discard):
                discard()
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
        for page in self.pages:
            discard = getattr(page, "discard_pending_changes", None)
            if callable(discard):
                discard()
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

    @property
    def pending_draft_keys(self) -> frozenset[tuple[str, int]]:
        instruction = self._selected_instruction()
        if not self.has_pending_draft or instruction is None:
            return frozenset()
        # The chapter setup pages also expose Bank $1B scripts, but identify
        # their drafts by file offset because other phases use different banks.
        return frozenset({("rom_offset", instruction.file_offset)})

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
        selection.setMinimumWidth(180)
        selection.setMaximumWidth(350)
        selection_layout = QVBoxLayout(selection)
        selection_layout.setContentsMargins(7, 10, 7, 7)
        selection_layout.addWidget(self.records, 1)
        self.record_count = QLabel("尚未载入机体。")
        self.record_count.setWordWrap(True)
        self.record_count.setObjectName("hintText")
        selection_layout.addWidget(self.record_count)
        self.add_button = QPushButton("添加")
        self.add_button.setEnabled(False)
        self.add_button.setToolTip("新增机体所需的指针重定位规则尚未完成验证。")
        selection_layout.addWidget(self.add_button)
        splitter.addWidget(selection)

        detail = QWidget()
        detail_layout = QVBoxLayout(detail)
        detail_layout.setContentsMargins(2, 0, 0, 0)
        self.record_heading = self.controller.record_heading
        detail_layout.addWidget(self.record_heading)
        self.pending_state = self.controller.pending_state
        detail_layout.addWidget(self.pending_state)
        detail_layout.addLayout(self._build_data_row())
        detail_layout.addWidget(self._build_graphics_group())

        staged_row = QGridLayout()
        staged_row.addWidget(self.apply_button, 0, 0)
        duplicate = QPushButton("复制到其他ID…")
        duplicate.clicked.connect(self.controller.duplicate_record)
        reset = QPushButton("还原此机体")
        reset.clicked.connect(self.controller.reset_record)
        staged_row.addWidget(duplicate, 0, 1)
        staged_row.addWidget(reset, 0, 2)
        self.export_package_button = QPushButton("导出当前 .dcunit…")
        self.export_package_button.clicked.connect(self._export_current_package)
        self.import_package_button = QPushButton("导入到当前机体…")
        self.import_package_button.clicked.connect(self._import_current_package)
        staged_row.addWidget(self.export_package_button, 1, 0)
        staged_row.addWidget(self.import_package_button, 1, 1)
        self.session_hint = QLabel("页内暂存后仍可用右下角“取消”完整撤销。")
        self.session_hint.setObjectName("hintText")
        self.session_hint.setWordWrap(True)
        staged_row.addWidget(self.session_hint, 2, 0, 1, 3)
        detail_layout.addLayout(staged_row)
        self.detail_scroll = QScrollArea()
        self.detail_scroll.setWidgetResizable(True)
        self.detail_scroll.setWidget(detail)
        splitter.addWidget(self.detail_scroll)
        splitter.setSizes([280, 1080])
        splitter.splitterMoved.connect(lambda *_args: self._arrange_data_groups())
        self._compact_data_layout: bool | None = None

    def resizeEvent(self, event) -> None:  # noqa: N802 - Qt API
        super().resizeEvent(event)
        self._arrange_data_groups()

    def _arrange_data_groups(self) -> None:
        if not hasattr(self, "detail_scroll"):
            return
        compact = self.detail_scroll.viewport().width() < 820
        if compact == self._compact_data_layout:
            return
        self._compact_data_layout = compact
        for group in (self.basic_group, self.attributes_group, self.weapons_group):
            self.data_grid.removeWidget(group)
        if compact:
            for index, group in enumerate((self.basic_group, self.attributes_group, self.weapons_group)):
                self.data_grid.addWidget(group, index, 0)
        else:
            self.data_grid.addWidget(self.basic_group, 0, 0)
            self.data_grid.addWidget(self.attributes_group, 0, 1)
            self.data_grid.addWidget(self.weapons_group, 1, 0, 1, 2)

    @property
    def current_id(self) -> int | None:
        return self.controller.current_id

    def _disabled_button(self, text: str, tooltip: str) -> QPushButton:
        button = QPushButton(text)
        button.setEnabled(False)
        button.setToolTip(tooltip)
        return button

    def _build_graphics_group(self) -> QGroupBox:
        group = QGroupBox("机体图片与碎片图库")
        grid = QGridLayout(group)
        self.graphics_status = QLabel("请选择机体。")
        self.graphics_status.setWordWrap(True)
        grid.addWidget(self.graphics_status, 0, 0, 1, 3)
        self.body_preview = QLabel("请选择机体")
        self.body_preview.setObjectName("legacyUnitBodyPreview")
        self.body_preview.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.body_preview.setMinimumSize(180, 160)
        self.body_preview.setStyleSheet(
            "background: #000000; color: #d2d2d2; border: 1px solid #202020;"
        )
        self.body_preview.setToolTip(
            "按战斗外观记录的背景图库号读取真实 CHR，以图块顺序显示；不是拼合后的战斗姿势。"
        )
        self.fragment_preview = QLabel("请选择机体")
        self.fragment_preview.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.fragment_preview.setMinimumSize(260, 160)
        self.fragment_preview.setStyleSheet(self.body_preview.styleSheet())
        grid.addWidget(QLabel("机体图库 · 原始图块"), 1, 0)
        grid.addWidget(QLabel("碎片图库 · 2 KiB 原始图块"), 1, 1)
        grid.addWidget(self.body_preview, 2, 0)
        grid.addWidget(self.fragment_preview, 2, 1)
        self.body_palette_caption = QLabel("记录配色1：—")
        self.fragment_palette_caption = QLabel("记录配色2：—")
        grid.addWidget(self.body_palette_caption, 3, 0)
        grid.addWidget(self.fragment_palette_caption, 3, 1)

        details = QWidget()
        details_layout = QVBoxLayout(details)
        self.appearance_details = QPlainTextEdit()
        self.appearance_details.setReadOnly(True)
        self.appearance_details.setMaximumHeight(130)
        details_layout.addWidget(self.appearance_details)
        details_layout.addWidget(QLabel("地图图标图库浏览（尚未建立机体 ID 绑定）"))
        self.icon_bank = QComboBox()
        for bank in range(0x34, 0x37):
            self.icon_bank.addItem(f"图库 ${bank:02X} · 16 个 2×2 图块候选图标", bank)
        self.icon_bank.currentIndexChanged.connect(self._refresh_icon_bank)
        details_layout.addWidget(self.icon_bank)
        self.icon_preview = QLabel("—")
        self.icon_preview.setObjectName("legacyUnitIconPreview")
        self.icon_preview.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.icon_preview.setStyleSheet(
            "background: #000000; color: white; border: 1px solid #4d555c;"
        )
        details_layout.addWidget(self.icon_preview)
        self.icon_address = QLineEdit()
        self.icon_address.setReadOnly(True)
        details_layout.addWidget(self.icon_address)
        unsupported = QLabel(
            "未接通：合成效果图、拼图编辑、图片上传/清除、图标绑定。"
            "此处展示实际资源和脚本，不表示已兼容旧版五张 BMP 导出。"
        )
        unsupported.setWordWrap(True)
        details_layout.addWidget(unsupported)
        actions = QHBoxLayout()
        for caption in ("上传机体", "清除机体", "上传碎片", "清除碎片"):
            actions.addWidget(self._disabled_button(caption, "完整图像写入关系尚未验证。"))
        details_layout.addLayout(actions)
        grid.addWidget(collapsible_details("图像技术详情与尚未接通的功能", details), 4, 0, 1, 2)
        self.edit_appearance_button = QPushButton("修改配色与图库…")
        self.edit_appearance_button.clicked.connect(self._edit_appearance)
        grid.addWidget(self.edit_appearance_button, 5, 0, 1, 2)
        grid.setColumnStretch(0, 1)
        grid.setColumnStretch(1, 1)
        return group

    def _build_data_row(self) -> QGridLayout:
        row = QGridLayout()
        self.data_grid = row
        row.setSpacing(9)

        basic = QGroupBox("基本设置")
        self.basic_group = basic
        basic_form = QFormLayout(basic)
        basic_form.addRow("机体名称", self.name_reference)
        self.terrain = QComboBox()
        for value, label in enumerate(("空", "陆", "海", "保留原码 3")):
            self.terrain.addItem(label, value)
        self.terrain.currentIndexChanged.connect(
            lambda index: self.fields["terrain"].setValue(index) if index >= 0 else None
        )
        self.fields["terrain"].valueChanged.connect(self.terrain.setCurrentIndex)
        self.terrain.setToolTip("仅修改机体类型的低两位，变形和其他标志保持原值。")
        basic_form.addRow("适应地形", self.terrain)
        self.transform = QComboBox()
        self.transform.addItem("字段关系待验证")
        self.transform.setEnabled(False)
        self.transform.setToolTip("变形关系尚未完成差分验证。")
        basic_form.addRow("变形", self.transform)
        self.record_meta = self.controller.record_meta
        self.record_meta.setWordWrap(True)
        basic_form.addRow("记录位置", self.record_meta)
        row.addWidget(basic, 0, 0)

        attributes = QGroupBox("机体属性")
        self.attributes_group = attributes
        attribute_grid = QGridLayout(attributes)
        logical_rows: tuple[tuple[str | None, str | None, str | None], ...] = (
            ("movement", "experience", "strength_growth"),
            ("strength", "upgrade", "defense_growth"),
            ("defense", "special", "speed_growth"),
            ("speed", "hp", "hp_growth"),
        )
        labels = {
            "movement": "机动",
            "upgrade": "基础金钱",
            "experience": "基础经验",
            "special": "特殊技能",
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
        row.addWidget(attributes, 0, 1)

        weapons = QGroupBox("机体武器")
        self.weapons_group = weapons
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
            editor.currentIndexChanged.connect(
                lambda _index, source=editor, button=jump: button.setEnabled(
                    source.isEnabled() and bool(source.currentData())
                )
            )
            jump.setEnabled(False)
            slot_row.addWidget(jump)
            weapons_layout.addLayout(slot_row)
            self.weapon_jump_buttons.append(jump)
        warning = QLabel(
            "跳转会自动暂存当前机体；本窗口“取消”仍可回滚全部修改。"
        )
        warning.setWordWrap(True)
        warning.setObjectName("hintText")
        weapons_layout.addWidget(warning)
        weapons_layout.addStretch()
        row.addWidget(weapons, 1, 0, 1, 2)
        return row

    def _request_weapon(self, slot: int) -> None:
        editor = self.weapon_slots[slot]
        weapon_id = editor.currentData()
        if editor.isEnabled() and weapon_id and self.commit_pending_changes():
            self.weapon_requested.emit(int(weapon_id))

    def _export_current_package(self) -> None:
        if self.project is None or self.current_id is None:
            return
        filename, _ = QFileDialog.getSaveFileName(
            self, "导出当前机体的数据包（非旧版 BMP）",
            str(default_export_path(f"unit_{self.current_id:02X}.dcunit")),
            "新DC机体数据包 (*.dcunit)",
        )
        if not filename:
            return
        try:
            if not self.commit_pending_changes():
                return
            destination = Path(filename).with_suffix(".dcunit")
            package_from_project(self.project, self.current_id).save(
                writable_output_path(destination)
            )
            self.session_hint.setText("已导出当前16字节属性和名称引用；图像、武器配置不在此包内。")
        except Exception as error:
            self.show_error(error)

    def _import_current_package(self) -> None:
        if self.project is None or self.current_id is None:
            return
        filename, _ = QFileDialog.getOpenFileName(
            self, "导入数据包到当前机体", "", "新DC机体数据包 (*.dcunit)"
        )
        if not filename:
            return
        try:
            package = UnitPackage.load(filename)
            if package.source_profile != self.project.profile.key:
                raise ValueError("机体包与当前 ROM 的配置不兼容。")
            affected = affected_unit_ids(self.project, self.current_id)
            answer = QMessageBox.question(
                self, "确认导入范围",
                f"来源：{package.label}\n目标：{self.project.unit_display_name(self.current_id)}"
                f" [${self.current_id:02X}]\n"
                f"共享属性记录将影响 {len(affected)} 个机体："
                + "、".join(f"${value:02X}" for value in affected)
                + f"\n附带资源：{len(package.assets)} 项。"
                "\n将覆盖16字节属性与名称引用，附带CHR按包内原地址写入。"
                "不包含机体装备武器或旧版组合图资源；窗口“取消”可整体撤销。",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel,
                QMessageBox.StandardButton.Cancel,
            )
            if answer != QMessageBox.StandardButton.Yes:
                return
            if not self.commit_pending_changes():
                return
            apply_unit_package(self.project, package, self.current_id)
            self.project_changed.emit(f"已导入机体数据包到 ${self.current_id:02X}")
        except Exception as error:
            self.show_error(error)

    def _refresh_icon_bank(self) -> None:
        if self.project is None:
            self.icon_preview.clear()
            self.icon_address.clear()
            return
        bank = int(self.icon_bank.currentData())
        if (bank + 1) * 64 > self.project.chr_tile_count:
            self.icon_preview.setText("图库超出活动CHR")
            return
        image = render_unit_icon_bank(self.project, bank)
        self.icon_preview.setPixmap(QPixmap.fromImage(image).scaled(
            512, 32, Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.FastTransformation,
        ))
        offset = self.project.chr_codec.offset + bank * 0x400
        self.icon_address.setText(f"图库 ${bank:02X} · 文件 0x{offset:06X} · 尚未绑定机体ID")

    def _edit_appearance(self) -> None:
        if self.project is None or self.current_id is None:
            return
        try:
            dialog = UnitAppearanceDialog(self.project, self.current_id, self)
            if dialog.exec() == QDialog.DialogCode.Accepted and dialog.changed:
                # Refresh graphics only: an uncommitted attribute form belongs
                # to the outer page and must not be discarded by this action.
                self._refresh_visuals()
        except (ValueError, IndexError) as error:
            self.show_error(error)

    def _refresh_visuals(self) -> None:
        self._refresh_icon_bank()
        self.record_count.setText(
            f"{self.project.unit_count - 1} 个机体ID槽位；同名项可能共享属性。"
            if self.project is not None else "尚未载入机体。"
        )
        if self.project is None or self.current_id is None:
            self.body_preview.setText("请选择机体")
            self.fragment_preview.setText("请选择机体")
            return
        unit_id = self.current_id
        try:
            appearance = read_unit_appearance(self.project, unit_id)
            self.graphics_status.setText(
                f"已读取当前机体外观：主体脚本 {len(appearance.body_script)} 字节，"
                f"碎片脚本 {len(appearance.fragment_script)} 字节。"
                "已按机体/碎片各自配色显示，可修改配色与图库；"
                "主体合成预览已接通，碎片拼图和图片上传尚未接通。"
            )
            self.appearance_details.setPlainText(
                f"外观记录文件位置：0x{appearance.file_offset:06X}\n"
                f"归一化外观记录：{appearance.configuration.hex(' ').upper()}\n"
                f"主体拼图：{appearance.body_script.hex(' ').upper()}\n"
                f"碎片拼图：{appearance.fragment_script.hex(' ').upper()}"
            )
            for caption, label, colors in (
                ("记录配色1", self.body_palette_caption, appearance.first_palette),
                ("记录配色2", self.fragment_palette_caption, appearance.second_palette),
            ):
                label.setText(caption + "： " + "  ".join(
                    f'<span style="color:{palette_color(value).name()}; background:#222">'
                    f'■</span> ${value:02X}' for value in colors
                ))
            for label, banks, palette in (
                (self.body_preview,
                 appearance.secondary_banks, appearance.first_palette),
                (self.fragment_preview,
                 (appearance.primary_bank & 0xFE, (appearance.primary_bank & 0xFE) + 1),
                 appearance.second_palette),
            ):
                picture = render_chr_banks(self.project, banks, palette)
                label.setPixmap(QPixmap.fromImage(picture).scaled(
                    picture.width() * 2, picture.height() * 2,
                    Qt.AspectRatioMode.KeepAspectRatio,
                    Qt.TransformationMode.FastTransformation,
                ))
                label.setToolTip("真实图库：" + "、".join(f"${bank:02X}" for bank in banks))
        except (ValueError, IndexError) as error:
            self.graphics_status.setText(str(error))
            self.body_preview.setText("此配置暂不支持图库预览")
            self.fragment_preview.setText("此配置暂不支持图库预览")
            self.appearance_details.clear()
            self.body_palette_caption.setText("记录配色1：未读取")
            self.fragment_palette_caption.setText("记录配色2：未读取")

        for field_key, editor in self.fields.items():
            base_value = self.project.get_value(unit_id, field_key, original=True)
            editor.setToolTip(f"{editor.toolTip().split('；基准ROM：')[0]}；基准ROM：{base_value}")

    def set_project(self, project: RomProject | None) -> None:
        self.project = project
        self.controller.set_project(project)
        readable_references(self.name_reference)
        self._refresh_visuals()

    def refresh(self) -> None:
        self.controller.refresh()
        readable_references(self.name_reference)
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
            "“系统文字”页签可编辑实际系统文本。升级阈值可改，总经验和升级还需随之计算。"
        )
        notice.setWordWrap(True)
        notice.setObjectName("hintText")
        root.addWidget(notice)

        tables = QHBoxLayout()
        experience_group = QGroupBox("升级累计经验 · 等级1—99")
        experience_layout = QVBoxLayout(experience_group)
        self.experience_table = QTableWidget(99, 4)
        self.experience_table.setHorizontalHeaderLabels(("等级", "升级阈值", "总经验", "升级还需"))
        self.experience_table.setColumnWidth(0, 45)
        self.experience_table.verticalHeader().setVisible(False)
        self.experience_table.horizontalHeader().setSectionResizeMode(
            1, QHeaderView.ResizeMode.Stretch
        )
        self.experience_table.setAlternatingRowColors(True)
        self.experience_table.itemChanged.connect(self._update_pending_state)
        experience_layout.addWidget(self.experience_table)
        tables.addWidget(experience_group, 3)

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
                for column in (2, 3):
                    item = QTableWidgetItem()
                    item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEditable)
                    self.experience_table.setItem(row, column, item)
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
        if error is None:
            thresholds, _corrections = self._draft_values()
            previous = self.experience_table.blockSignals(True)
            try:
                for row, threshold in enumerate(thresholds):
                    total = thresholds[row - 1] if row else 0
                    self.experience_table.item(row, 2).setText(str(total))
                    self.experience_table.item(row, 3).setText(str(threshold - total))
            finally:
                self.experience_table.blockSignals(previous)
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
            "道具说明可在“道具说明”页签编辑。商店与店员对话按对应页面的已验证范围操作。"
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
        self.resize(1220, 840)
        self.setMinimumSize(900, 600)

        layout = QVBoxLayout(self)
        self.tabs = QTabWidget()
        self.tabs.setObjectName("legacyDatabaseTabs")

        self.unit_page = self.register_page(LegacyUnitDatabasePage())
        self.character_page = self.register_page(ReadableCharacterPage())
        self.weapon_page = self.register_page(ReadableWeaponPage())
        assert isinstance(self.unit_page, LegacyUnitDatabasePage)
        assert isinstance(self.character_page, CharacterPage)
        assert isinstance(self.weapon_page, WeaponPage)
        self.unit_page.weapon_requested.connect(self._select_weapon)
        self.weapon_page.unit_requested.connect(self._select_unit)

        self.battle_dialogue_page = self.register_page(LegacyTextPage())
        self.other_page_1 = self.register_page(LegacyGlobalTablesPage())
        self.other_page_2 = self.register_page(LegacyItemTablePage())

        for label, page in zip(self.TAB_LABELS, self.pages):
            self.tabs.addTab(page, label)
        self.system_text_page = self.register_page(LegacyTextPage(("system",)))
        self.item_description_page = self.register_page(LegacyTextPage(("item_description",)))
        self.growth_page = self.register_page(LegacyGrowthPage())
        self.shop_page = self.register_page(LegacyShopPage())
        self._add_detail_tabs(self.other_page_1, "经验与命中补正", self.system_text_page, "系统文字")
        self.other_page_1.detail_tabs.addTab(self.growth_page, "成长方式")
        self._add_detail_tabs(self.other_page_2, "道具名称与价格", self.item_description_page, "道具说明")
        self.other_page_2.detail_tabs.addTab(self.shop_page, "商店与对话")
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
        self.tabs.currentChanged.connect(self._refresh_database_context)
        for page in (self.other_page_1, self.other_page_2):
            page.detail_tabs.currentChanged.connect(
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
            pending_state.show()
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

    @staticmethod
    def _add_detail_tabs(page, original_label: str, extra, extra_label: str) -> None:
        original = QWidget()
        original.setLayout(page.layout())
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)
        tabs = QTabWidget()
        tabs.addTab(original, original_label)
        tabs.addTab(extra, extra_label)
        page.detail_tabs = tabs
        layout.addWidget(tabs)

    def _select_weapon(self, weapon_id: int) -> None:
        self.database_search.clear()
        self.tabs.setCurrentIndex(2)
        for row in range(self.weapon_page.records.count()):
            if int(self.weapon_page.records.item(row).data(Qt.ItemDataRole.UserRole)) == weapon_id:
                self.weapon_page.records.setCurrentRow(row)
                # Selection can commit the old record and rebuild the list.
                # Never retain a QListWidgetItem across that synchronous call.
                selected = self.weapon_page.records.currentItem()
                if selected is not None and int(selected.data(Qt.ItemDataRole.UserRole)) == weapon_id:
                    self.weapon_page.records.scrollToItem(selected)
                break

    def _select_unit(self, unit_id: int) -> None:
        self.database_search.clear()
        self.tabs.setCurrentIndex(0)
        for row in range(self.unit_page.records.count()):
            if int(self.unit_page.records.item(row).data(Qt.ItemDataRole.UserRole)) == unit_id:
                self.unit_page.records.setCurrentRow(row)
                selected = self.unit_page.records.currentItem()
                if selected is not None and int(selected.data(Qt.ItemDataRole.UserRole)) == unit_id:
                    self.unit_page.records.scrollToItem(selected)
                break

    def _refresh_database_context(self, index: int) -> None:
        if index == 2:
            self.weapon_page.refresh_usage()

    def _active_search_page(self) -> ProjectPage | None:
        current = self.tabs.currentWidget()
        tabs = getattr(current, "detail_tabs", None)
        if tabs is not None and isinstance(tabs.currentWidget(), ProjectPage):
            current = tabs.currentWidget()
        return current if isinstance(current, ProjectPage) else None

    def _sync_active_search(self, text: str) -> None:
        page = self._active_search_page()
        search = getattr(page, "search", getattr(page, "search_edit", None))
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
        self.resize(1180, 780)
        self.setMinimumSize(900, 600)

        self.setup_event_pages = [self.register_page(LegacyScenarioEventsPage(phase)) for phase in range(3)]
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
            "行动事件 · 全局指令索引", self.action_event_page, "action_event_list"
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
        context.setMinimumWidth(240)
        context.setMaximumWidth(380)
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
            self.setup_event_lists.append(controller.record_list)
            self.setup_code_buttons.append(controller.apply_button)
            self.setup_event_tabs.addTab(controller, label)
        event_layout.addWidget(self.setup_event_tabs)
        page_layout.addWidget(event_group, 1)
        return page

    def _event_list_panel(
        self, controller: EventPage
    ) -> tuple[QWidget, QListWidget, QPushButton]:
        host = QWidget()
        layout = QVBoxLayout(host)
        layout.setContentsMargins(3, 3, 3, 3)
        search = QLineEdit()
        search.setPlaceholderText("搜索事件动作、人物、章节或原码…")
        search.setClearButtonEnabled(True)
        overview = QListWidget()
        overview.setAlternatingRowColors(True)
        overview.setUniformItemSizes(True)
        overview.setProperty("eventSearch", search)
        search.textChanged.connect(
            lambda text, listing=overview: self._filter_story_overview(listing, text)
        )
        overview.currentItemChanged.connect(
            lambda current, _previous, page=controller: self._select_event_item(
                page, current
            )
        )
        button = QPushButton("编辑事件参数…")
        button.clicked.connect(
            lambda _checked=False, page=controller: self._open_advanced_editor(
                page, "事件参数编辑"
            )
        )
        overview.itemDoubleClicked.connect(
            lambda _item, page=controller: self._open_advanced_editor(
                page, "事件参数编辑"
            )
        )
        layout.addWidget(search)
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
        if controller is self.action_event_page:
            scope_note = QLabel(
                "全局汇总：显示各章节脚本中的行动控制指令，不随左侧关卡切换。"
                "记录的实际章节归属可在编辑器中查看；这不是独立行动脚本表。"
            )
            scope_note.setWordWrap(True)
            scope_note.setObjectName("hintText")
            group_layout.addWidget(scope_note)
        layout.addWidget(group)
        setattr(self, attribute_name, overview)
        setattr(self, f"{attribute_name}_code_button", button)
        return host

    def _build_persuasion_overview(self) -> QWidget:
        host = QWidget()
        layout = QVBoxLayout(host)
        group = QGroupBox("劝降事件 · 全局规则表")
        group_layout = QVBoxLayout(group)
        self.persuasion_overview_list = QListWidget()
        self.persuasion_overview_list.setAlternatingRowColors(True)
        self.persuasion_overview_list.currentItemChanged.connect(
            self._select_persuasion_item
        )
        self.persuasion_code_button = QPushButton("编辑劝降条件…")
        self.persuasion_code_button.clicked.connect(
            lambda: self._open_advanced_editor(self.persuasion_page, "劝降事件编辑")
        )
        self.persuasion_overview_list.itemDoubleClicked.connect(
            lambda _item: self._open_advanced_editor(
                self.persuasion_page, "劝降事件编辑"
            )
        )
        group_layout.addWidget(self.persuasion_overview_list, 1)
        scope_note = QLabel("这里列出全部已验证规则；所在关卡是每条规则自身的条件，不受关卡侧栏筛选。")
        scope_note.setWordWrap(True)
        scope_note.setObjectName("hintText")
        group_layout.addWidget(scope_note)
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
        controls = QHBoxLayout()
        selector = QComboBox()
        selector.setMinimumContentsLength(20)
        search = QLineEdit()
        search.setPlaceholderText("搜索正文、编号…")
        search.setClearButtonEnabled(True)
        controls.addWidget(QLabel("文本组"))
        controls.addWidget(selector, 1)
        controls.addWidget(search, 2)
        group_layout.addLayout(controls)
        overview = QListWidget()
        overview.setAlternatingRowColors(True)
        overview.setUniformItemSizes(True)
        overview.setProperty("textGroupSelector", selector)
        overview.setProperty("textSearch", search)
        selector.currentIndexChanged.connect(
            lambda _index, page=controller, source=selector, listing=overview:
            self._story_group_changed(page, source, listing)
        )
        search.textChanged.connect(
            lambda text, listing=overview: self._filter_story_overview(listing, text)
        )
        overview.currentItemChanged.connect(
            lambda current, _previous, page=controller: self._select_story_item(
                page, current
            )
        )
        button = QPushButton("编辑文字…（也可双击）")
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
        note.setWordWrap(True)
        note.setToolTip(note_text)
        group_layout.addWidget(overview, 1)
        group_layout.addWidget(button, 0, Qt.AlignmentFlag.AlignLeft)
        group_layout.addWidget(note)
        layout.addWidget(group)
        setattr(self, attribute_name, overview)
        setattr(self, f"{attribute_name}_code_button", button)
        setattr(self, f"{attribute_name}_group_selector", selector)
        setattr(self, f"{attribute_name}_search", search)
        return host

    def _configure_event_views(self) -> None:
        action_index = self.action_event_page.kind_filter.findText("行动控制")
        if action_index >= 0:
            self.action_event_page.kind_filter.setCurrentIndex(action_index)
        map_index = self.map_event_page.kind_filter.findText("触发条件与行动判定")
        if map_index >= 0:
            self.map_event_page.kind_filter.setCurrentIndex(map_index)

    def _move_chapter_context(self, tab_index: int) -> None:
        if not 0 <= tab_index < len(self._splitters):
            return
        # Only these views have a verified relationship to the selected map.
        # The other tabs are global tables or text groups, not chapter filters.
        if tab_index not in (0, 3):
            self.chapter_context.hide()
            return
        splitter = self._splitters[tab_index]
        splitter.insertWidget(0, self.chapter_context)
        self.chapter_context.show()
        splitter.setSizes([280, 880])

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
                self.map_event_page,
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

        for page in self.setup_event_pages:
            if not page.has_pending_draft:
                page.set_scenario(scenario_id)
        for page in (self.map_event_page,):
            if page.has_pending_draft:
                continue
            index = page.scenario_filter.findData(scenario_id)
            if index >= 0:
                page.scenario_filter.setCurrentIndex(index)
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
                f"地址 ${instruction.address:04X} · {instruction.raw.hex(' ').upper()}\n"
                + page._context_text(instruction)
            )
            overview.addItem(item)
            if instruction.address == previous:
                selected_row = index
        if overview.count():
            overview.setCurrentRow(selected_row)
        overview.blockSignals(False)
        search = overview.property("eventSearch")
        self._filter_story_overview(overview, search.text())
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
        selector = overview.property("textGroupSelector")
        selector.blockSignals(True)
        selector.clear()
        for index in range(page.selector.count()):
            selector.addItem(page.selector.itemText(index), page.selector.itemData(index))
        selector.setCurrentIndex(selector.findData(page.current_selector))
        selector.blockSignals(False)
        for row in range(page.indices.count()):
            source = page.indices.item(row)
            item = QListWidgetItem(source.text())
            item.setData(Qt.ItemDataRole.UserRole, source.data(Qt.ItemDataRole.UserRole))
            item.setToolTip(f"{group}\n{source.toolTip()}")
            overview.addItem(item)
            if source.data(Qt.ItemDataRole.UserRole) == current_index:
                selected = row
        if overview.count():
            overview.setCurrentRow(selected)
        overview.blockSignals(False)
        search = overview.property("textSearch")
        ScenarioDialog._filter_story_overview(overview, search.text())

    @staticmethod
    def _filter_story_overview(overview: QListWidget, text: str) -> None:
        query = text.strip().casefold()
        for row in range(overview.count()):
            item = overview.item(row)
            item.setHidden(
                bool(query)
                and query not in item.text().casefold()
                and query not in item.toolTip().casefold()
            )

    def _story_group_changed(
        self, page: StoryPage, selector: QComboBox, overview: QListWidget
    ) -> None:
        target = selector.currentData()
        index = page.selector.findData(target)
        if index < 0:
            return
        # StoryPage validates/commits its draft before changing groups; if it
        # rejects an invalid edit the outer projection must follow it back.
        page.selector.setCurrentIndex(index)
        self._refresh_story_overview(page, overview)

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
        self._refresh_event_overview(self.action_event_page, self.action_event_list)
        self._refresh_event_overview(self.map_event_page, self.map_event_list)
        self._refresh_persuasion_overview()
        self._refresh_story_overview(self.story_page, self.story_overview_list)
        self._refresh_story_overview(self.victory_page, self.victory_overview_list)

    def _open_advanced_editor(self, page: ProjectPage, title: str) -> None:
        popup = QDialog(self)
        popup.setWindowTitle(title)
        popup.setModal(True)
        popup.resize(min(1100, self.width()), min(760, self.height()))
        popup.setMinimumSize(840, 560)
        layout = QVBoxLayout(popup)
        page.setParent(popup)
        layout.addWidget(page, 1)
        page.show()
        if isinstance(page, StoryPage):
            page.focus_text_editor()
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
