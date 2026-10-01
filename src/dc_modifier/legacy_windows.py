from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from PySide6.QtCore import QSize, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QPainter, QPen, QPixmap, QShowEvent
from PySide6.QtWidgets import (
    QAbstractSpinBox,
    QAbstractItemView,
    QApplication,
    QBoxLayout,
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
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
    QMenu,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QSpinBox,
    QSplitter,
    QTabWidget,
    QTableWidget,
    QTableWidgetItem,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from fc_editor.dc_text import dc_map_label, default_dc_text_table
from fc_editor.codecs.chapter_title import ChapterTitleCodec
from fc_editor.codecs.legacy_scenario import LegacyScenarioCodec
from fc_editor.errors import RomFormatError
from fc_editor.models import UNIT_FIELD_BY_KEY
from fc_editor.resources import Allocation, BankAllocator
from fc_editor.unit_package import UnitPackage
from fc_rom_editor_core import RomProject

from .action_event_page import ActionEventPage
from .event_page import EventPage
from .event_instruction_dialog import (
    EventCodeDialog,
    EventInstructionDialog,
    EventParameterDialog,
)
from .database_graphics import (
    decode_unit_body_script,
    palette_color,
    read_unit_appearance,
    render_chr_banks,
    render_unit_battle_preview,
)
from .database_memory import DatabaseModuleMemoryPanel
from .database_records import (
    ReadableCharacterPage, ReadableWeaponPage, readable_references,
)
from .battle_calculator import (
    UNIT_SPECIAL_FLAGS,
    UNIT_SPECIAL_LOW_BITS,
    unit_special_names,
    unit_special_summary,
)
from .map_page import (
    CHAPTER_TITLE_PALETTE_NES,
    MAP_ICON_PALETTES_NES,
    MAP_ICON_BANK_CANDIDATES,
    SCENARIO_MAP_ICON_BANKS,
    CompactNesColorField,
    render_chapter_title,
    render_title_segment,
    render_unit_icon_bank,
)
from .unit_icon_dialog import UnitIconBindingDialog, UnitIconDialog
from .pages import (
    CharacterPage,
    ProjectPage,
    SearchableRecordPage,
    UnitPage,
    WeaponPage,
)
from .persuasion_page import PersuasionPage
from .story_page import StoryPage
from .unit_packages import apply_unit_package, package_from_project
from .unit_appearance_dialog import (
    UnitAppearanceDialog,
    appearance_patch,
    clear_unit_appearance_image,
)
from .legacy_text_pages import LegacyGrowthPage, LegacyShopPage, LegacyTextPage, LegacyScenarioEventsPage
from .legacy_unit_export import export_legacy_unit_bitmaps_for_id
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
        self._deferred_pages: set[ProjectPage] = set()
        self._loaded_pages: set[ProjectPage] = set()
        self._snapshot: _DialogSnapshot | None = None
        self._session_active = False
        self._dialog_title = title
        self.setWindowTitle(title)
        self.setModal(True)
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose, False)

    def register_page(
        self, page: ProjectPage, *, defer_refresh: bool = False
    ) -> ProjectPage:
        """Attach a functional page and proxy its public integration signals."""

        self.pages.append(page)
        conflict_setter = getattr(page, "set_transaction_conflict_checker", None)
        if callable(conflict_setter):
            conflict_setter(self._pending_page_conflict_error)
        page.project_changed.connect(
            lambda message, source=page: self._registered_page_changed(source, message)
        )
        page.navigation_requested.connect(self._forward_navigation)
        if defer_refresh:
            self._deferred_pages.add(page)
            page.set_project_deferred(self.project)
        else:
            page.set_project(self.project)
            self._loaded_pages.add(page)
        return page

    def _ensure_page_loaded(self, page: ProjectPage) -> None:
        if page in self._loaded_pages:
            return
        page.refresh()
        self._loaded_pages.add(page)

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
        self._loaded_pages.difference_update(self._deferred_pages)
        for page in self.pages:
            discard = getattr(page, "discard_pending_changes", None)
            if callable(discard):
                discard()
            if page in self._deferred_pages:
                page.set_project_deferred(project)
            else:
                page.set_project(project)
                self._loaded_pages.add(page)
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

    def exec(self) -> int:
        """Capture the outer transaction before a nested modal can mutate ROM."""

        if not self._session_active:
            self._begin_session()
        return super().exec()

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
            # The child puzzle can render cleared CHR tiles before the outer
            # database is cancelled.  Restoring bytes alone would leave those
            # cancelled pixels in the revision-keyed preview cache, so reopen
            # and repaint could still look cleared despite correct ROM bytes.
            self.project.invalidate_derived_caches()
            self.project._refresh_dynamic_codecs()
        self._snapshot = None
        self._session_active = False
        pending_pages = tuple(page for page in self.pages if page.has_pending_draft)
        for page in pending_pages:
            discard = getattr(page, "discard_pending_changes", None)
            if callable(discard):
                discard()
            else:
                page.refresh()
        # An untouched modal used to rebuild every table, text codec and CHR
        # preview while it was closing.  Besides being unnecessary, that made
        # Cancel slower than opening the database.  Pending pages restore their
        # own form above; a complete reload is only required after ROM bytes
        # were actually rolled back.
        if restored:
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

    def preferred_record_id(self) -> int | None:
        if self.project is None:
            return None
        return next(
            (
                unit_id
                for unit_id in self.record_ids()
                if any(self.project.record_bytes(unit_id)[3:])
                and any(read_unit_appearance(self.project, unit_id).secondary_banks)
            ),
            None,
        )

    def record_text(self, record_id: int) -> str:
        assert self.project is not None
        name = self.project.unit_display_name(record_id)
        if name == "空白/未分配机体槽":
            name = ""
        return f"[{record_id:02X}]{record_id:03d}: {name}".rstrip()

    def load_record(self, record_id: int | None) -> None:
        super().load_record(record_id)
        self.record_loaded.emit()


UNIT_SPECIAL_DIALOG_FLAGS = tuple(reversed(UNIT_SPECIAL_FLAGS))


class UnitSpecialEditorDialog(QDialog):
    """Visual editor for the verified bit layout of the unit-special byte."""

    def __init__(
        self,
        value: int,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        if not 0 <= value <= 0xFF:
            raise ValueError("机体特殊技能必须在 $00—$FF 之间。")
        self.setWindowTitle("机体特技")
        self.setObjectName("unitSpecialEditorDialog")
        self.setModal(True)
        self.setFixedSize(380, 250)

        root = QVBoxLayout(self)
        root.setContentsMargins(12, 12, 12, 12)
        root.setSpacing(8)

        editor_row = QHBoxLayout()
        editor_row.setSpacing(10)
        options_panel = QGroupBox("特技组合")
        options_panel.setObjectName("unitSpecialOptionsPanel")
        options_layout = QVBoxLayout(options_panel)
        options_layout.setContentsMargins(10, 12, 10, 8)
        options_layout.setSpacing(2)

        self.low_bits = QComboBox()
        self.low_bits.setObjectName("unitSpecialLowBits")
        for low_value, label in enumerate(UNIT_SPECIAL_LOW_BITS):
            self.low_bits.addItem(f"{low_value:02d}：{label}", low_value)
        self.low_bits.setCurrentIndex(value & 0x07)
        self.low_bits.setFixedHeight(28)
        self.flag_checks: dict[int, QCheckBox] = {}
        for mask, label in UNIT_SPECIAL_DIALOG_FLAGS:
            check = QCheckBox(label)
            check.setFixedHeight(23)
            check.setChecked(bool(value & mask))
            check.toggled.connect(self._refresh_summary)
            options_layout.addWidget(check)
            self.flag_checks[mask] = check

        low_bits_label = QLabel("基础防御特技（单选）")
        low_bits_label.setObjectName("unitSpecialLowBitsLabel")
        options_layout.addWidget(low_bits_label)
        options_layout.addWidget(self.low_bits)
        editor_row.addWidget(options_panel, 1)

        self.summary = QLabel()
        self.summary.setObjectName("unitSpecialSummary")
        self.summary.setFixedHeight(28)

        ok_button = QPushButton("确定")
        cancel_button = QPushButton("取消")
        ok_button.setObjectName("unitSpecialPrimaryButton")
        cancel_button.setObjectName("unitSpecialSecondaryButton")
        ok_button.setFixedSize(100, 30)
        cancel_button.setFixedSize(100, 30)
        ok_button.clicked.connect(self.accept)
        cancel_button.clicked.connect(self.reject)
        button_column = QVBoxLayout()
        button_column.setSpacing(6)
        button_column.addWidget(ok_button)
        button_column.addWidget(cancel_button)
        button_column.addStretch(1)
        editor_row.addLayout(button_column)
        root.addLayout(editor_row, 1)
        root.addWidget(self.summary)
        self.setStyleSheet(
            "QDialog#unitSpecialEditorDialog { background:#EEF3F5; }"
            "QGroupBox#unitSpecialOptionsPanel { background:#F7FBF9; "
            "border:1px solid #91B7AA; border-radius:5px; margin-top:8px; }"
            "QGroupBox#unitSpecialOptionsPanel::title { subcontrol-origin:margin; "
            "left:10px; padding:1px 7px; background:#D9ECE5; color:#285D4E; "
            "font-weight:600; }"
            "QLabel#unitSpecialLowBitsLabel { color:#52676F; margin-top:2px; }"
            "QComboBox#unitSpecialLowBits { background:#FFFFFF; "
            "border:1px solid #91AEB8; border-radius:4px; padding:2px 7px; }"
            "QLabel#unitSpecialSummary { background:#E0EEF1; color:#245C69; "
            "border:1px solid #A4C0C8; border-radius:4px; padding:3px 8px; }"
            "QPushButton#unitSpecialPrimaryButton { background:#3E8798; color:#FFFFFF; "
            "border:1px solid #2F7180; border-radius:4px; font-weight:600; }"
            "QPushButton#unitSpecialPrimaryButton:hover { background:#347B8C; }"
            "QPushButton#unitSpecialSecondaryButton { background:#F8FAFB; color:#344B54; "
            "border:1px solid #9CB4BD; border-radius:4px; }"
            "QPushButton#unitSpecialSecondaryButton:hover { background:#EAF1F3; }"
        )
        self.low_bits.currentIndexChanged.connect(self._refresh_summary)
        self._refresh_summary()

    def value(self) -> int:
        value = int(self.low_bits.currentData())
        for mask, check in self.flag_checks.items():
            if check.isChecked():
                value |= mask
        return value

    def _refresh_summary(self) -> None:
        value = self.value()
        names = unit_special_names(value)
        self.summary.setText(
            f"当前组合：{value} · " + ("、".join(names) if names else "无")
        )


class ChrBankComboBox(QComboBox):
    """Legacy-style editable CHR page selector with address context."""

    valueChanged = Signal(int)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._project: RomProject | None = None
        self._minimum = 0
        self._maximum = 0xFF
        self.setMaxVisibleItems(18)
        self.setSizeAdjustPolicy(
            QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon
        )
        self.setMinimumContentsLength(8)
        self.setMinimumWidth(95)
        self.setFixedHeight(32)
        self.currentIndexChanged.connect(self._emit_value)
        self._rebuild()

    def sizeHint(self) -> QSize:  # noqa: N802 - Qt API
        hint = super().sizeHint()
        hint.setWidth(max(hint.width(), 150))
        return hint

    def _label(self, bank: int) -> str:
        if self._project is None:
            return f"[{bank:02X}]{bank:03d}"
        offset = self._project.chr_codec.tile_offset(bank * 64)
        return f"[{bank:02X}]{bank:03d}: {offset:06X}"

    def _rebuild(self) -> None:
        previous = self.value()
        blocked = self.blockSignals(True)
        self.clear()
        for bank in range(self._minimum, self._maximum + 1):
            self.addItem(self._label(bank), bank)
        index = self.findData(min(max(previous, self._minimum), self._maximum))
        self.setCurrentIndex(max(0, index))
        self.blockSignals(blocked)

    def set_project(self, project: RomProject | None) -> None:
        if project is self._project:
            return
        self._project = project
        self._rebuild()

    def setRange(self, minimum: int, maximum: int) -> None:  # noqa: N802 - Qt API shape
        minimum, maximum = int(minimum), int(maximum)
        if (minimum, maximum) == (self._minimum, self._maximum):
            return
        self._minimum, self._maximum = minimum, maximum
        self._rebuild()

    def setValue(self, value: int) -> None:  # noqa: N802 - QSpinBox compatibility
        index = self.findData(int(value))
        if index >= 0:
            self.setCurrentIndex(index)

    def value(self) -> int:
        value = self.currentData()
        return int(value) if value is not None else self._minimum

    def _emit_value(self, _index: int) -> None:
        self.valueChanged.emit(self.value())


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
        self.name_text = self.controller.name_text
        self.weapon_slots = self.controller.weapon_slots
        self.apply_button = self.controller.apply_button
        self.apply_button.setText("暂存当前机体")
        self.apply_button.setFixedSize(104, 24)
        self.apply_button.setToolTip(
            "暂存到本窗口会话；按右下角“确定”保留，按“取消”全部回滚。"
        )
        # The reference editor has no extra page-level action strip.  Database
        # OK already commits the current valid form, while Cancel rolls the
        # whole dialog back, so keep this compatibility action non-visual.
        self.apply_button.hide()

        root = QHBoxLayout(self)
        root.setContentsMargins(5, 4, 5, 4)
        splitter = QSplitter()
        splitter.setChildrenCollapsible(False)
        root.addWidget(splitter)

        selection = QGroupBox("机体选择")
        selection.setObjectName("unitSelectionPanel")
        selection.setMinimumWidth(220)
        selection.setMaximumWidth(270)
        selection_layout = QVBoxLayout(selection)
        selection_layout.setContentsMargins(7, 10, 7, 7)
        selection_layout.addWidget(self.records, 1)
        self.record_count = QLabel("尚未载入机体。")
        self.record_count.setWordWrap(True)
        self.record_count.setObjectName("hintText")
        self.record_count.hide()
        selection_layout.addWidget(self.record_count)
        # The reference editor exposes record operations only from the unit
        # list's context menu.  Keep the selection rail visually quiet and do
        # not duplicate copy/paste/export/reset buttons beneath the list.
        try:
            self.records.customContextMenuRequested.disconnect(
                self.controller._show_record_context_menu
            )
        except (RuntimeError, TypeError):
            pass
        self.records.customContextMenuRequested.connect(
            self._show_unit_context_menu
        )
        self.records.setToolTip(
            "右键：复制机体、粘贴机体、导出机体、清除机体或清空全部。"
        )
        self.records.setStyleSheet(
            "QListWidget::item { padding: 1px 4px; }"
        )
        self.add_button = QPushButton("添加")
        self.add_button.setFixedHeight(24)
        self.add_button.setToolTip(
            "当前格式的机体 ID $01—$FF 共 255 个槽位均已开放；"
            "点击可查看容量说明；不会生成格式无法表示的第 256 个 ID。"
        )
        self.add_button.clicked.connect(self._show_add_capacity)
        selection_layout.addWidget(self.add_button)
        splitter.addWidget(selection)

        detail = QWidget()
        detail.setObjectName("unitDetailSurface")
        detail_layout = QVBoxLayout(detail)
        detail_layout.setContentsMargins(2, 0, 0, 0)
        detail_layout.setSpacing(4)
        self.record_heading = self.controller.record_heading
        self.pending_state = self.controller.pending_state
        # The reference page starts directly with "机体图片".  Keep these
        # controller labels as hidden diagnostic state instead of spending a
        # second title/status row above the real panel.
        self.record_heading.hide()
        self.pending_state.hide()
        self.graphics_group = self._build_graphics_group()
        detail_layout.addWidget(self.graphics_group)
        detail_layout.addLayout(self._build_data_row())

        staged_row = QGridLayout()
        staged_row.addWidget(self.apply_button, 0, 0)
        self.session_hint = QLabel("页内暂存后仍可用右下角“取消”完整撤销。")
        self.session_hint.setObjectName("hintText")
        self.session_hint.setWordWrap(True)
        self.session_hint.hide()
        staged_row.addWidget(self.session_hint, 0, 1)
        staged_row.setColumnStretch(1, 1)
        detail_layout.addLayout(staged_row)
        # Keep the action row attached to the editable panels.  Any remaining
        # room belongs below the completed form instead of becoming a hollow
        # band between the fields and their action.
        detail_layout.addStretch(1)
        self.detail_scroll = QScrollArea()
        self.detail_scroll.setWidgetResizable(True)
        self.detail_scroll.setWidget(detail)
        splitter.addWidget(self.detail_scroll)
        # Keep the record list close to the legacy editor's width so the
        # three-column detail area also fits at 125% Windows scaling.
        splitter.setSizes([245, 795])
        splitter.splitterMoved.connect(lambda *_args: self._arrange_data_groups())
        self._compact_data_layout: str | None = None
        self.setStyleSheet(
            "QGroupBox#unitSelectionPanel { background:#F5FAFB; "
            "border:1px solid #91AFBA; border-radius:5px; }"
            "QGroupBox#unitSelectionPanel::title { background:#D2E8ED; "
            "color:#1F5867; padding:2px 8px; font-weight:600; }"
            "QGroupBox#unitSelectionPanel QListWidget { background:#FFFFFF; "
            "border:1px solid #A4BCC5; border-radius:3px; }"
            "QGroupBox#unitSelectionPanel QListWidget::item:selected { "
            "background:#347F91; color:#FFFFFF; }"
            "QWidget#unitDetailSurface { background:#EEF3F5; }"
            "QGroupBox#unitGraphicsPanel { background:#FBFDFD; "
            "border:1px solid #86AAB7; border-radius:5px; }"
            "QGroupBox#unitBasicPanel { background:#F8FBFC; "
            "border:1px solid #91AFBA; border-radius:5px; }"
            "QGroupBox#unitAttributesPanel { background:#F5FAF8; "
            "border:1px solid #91B7AA; border-radius:5px; }"
            "QGroupBox#unitWeaponsPanel { background:#F8F9FC; "
            "border:1px solid #9EACC1; border-radius:5px; }"
            "QGroupBox#unitGraphicsPanel::title, QGroupBox#unitBasicPanel::title, "
            "QGroupBox#unitAttributesPanel::title, QGroupBox#unitWeaponsPanel::title {"
            " background:#D2E8ED; color:#205968; padding:2px 8px; font-weight:600; }"
            "QGroupBox#unitAttributesPanel::title { background:#D9ECE5; color:#285D4E; }"
            "QGroupBox#unitWeaponsPanel::title { background:#DEE5EF; color:#3E5572; }"
            "QGroupBox#unitAttributesPanel QLabel { color:#29464E; font-weight:400; }"
            "QGroupBox#unitAttributesPanel QSpinBox { background:#FFFFFF; color:#173640; "
            "border:1px solid #86A7B1; border-radius:4px; font-weight:500; }"
            "QGroupBox#unitAttributesPanel QSpinBox:hover { border-color:#5F8E9B; }"
            "QGroupBox#unitAttributesPanel QSpinBox:focus { border-color:#347F91; }"
            "QLabel#unitPanelNote { background:#EAF2F4; color:#60747D; "
            "border-radius:4px; padding:4px 7px; font-size:11px; }"
            "QPushButton#unitUploadButton, QPushButton#unitNavigateButton, "
            "QPushButton#unitClearButton { padding:2px 7px; border-radius:4px; }"
            "QPushButton#unitUploadButton { background:#D5EBEF; color:#174F5C; "
            "border:1px solid #729EAA; font-weight:600; }"
            "QPushButton#unitUploadButton:hover { background:#C5E2E8; border-color:#4F8795; }"
            "QPushButton#unitNavigateButton { background:#DEE7F2; color:#294F75; "
            "border:1px solid #829DBB; font-weight:600; }"
            "QPushButton#unitNavigateButton:hover { background:#CEDCEC; border-color:#607F9F; }"
            "QPushButton#unitClearButton { background:#F8E2DD; color:#7B3129; "
            "border:1px solid #C98A80; font-weight:600; }"
            "QPushButton#unitClearButton:hover { background:#F2D1CA; border-color:#B66E63; }"
            "QPushButton#unitUploadButton:disabled, QPushButton#unitNavigateButton:disabled, "
            "QPushButton#unitClearButton:disabled { background:#EEF1F2; color:#96A1A7; "
            "border:1px solid #D3DADD; font-weight:400; }"
            "QLabel#unitPoolStatus { background:#EEF7F4; color:#285E52; "
            "border:1px solid #BFD9D1; border-radius:4px; padding:3px 7px; }"
            "QWidget#unitImportPanel, QWidget#unitVisualSettingsPanel { "
            "background:#F6FAFB; border:1px solid #9CB7C1; border-radius:4px; }"
            "QWidget#unitImportColumns, QWidget#unitPalettePanel, "
            "QWidget#unitAppearancePanel { "
            "background:transparent; border:0; }"
            "QWidget#unitAppearanceDivider { background:#D2E0E5; }"
            "QLabel#unitPaletteHeading, QLabel#unitAppearanceHeading { "
            "color:#294F5B; font-weight:600; }"
            "QWidget#unitSpecialField { background:transparent; }"
            "QPushButton#unitSpecialValueButton { background:#F8FCFC; color:#173F49; "
            "border:1px solid #9FB7C0; border-right:0; "
            "border-top-left-radius:4px; border-bottom-left-radius:4px; "
            "font-weight:500; padding:0; }"
            "QPushButton#unitSpecialValueButton:hover { background:#E7F2F4; "
            "border-color:#5F8E9B; }"
            "QToolButton#unitSpecialExpandButton { background:#F2F7F8; color:#244E59; "
            "border:1px solid #86A7B1; border-top-right-radius:4px; "
            "border-bottom-right-radius:4px; padding:0; }"
            "QToolButton#unitSpecialExpandButton:hover { background:#DDECEF; "
            "border-color:#5F8E9B; }"
            "QWidget#unitImportSeparator { background:#93A8B0; }"
            "QWidget#unitIconStrip { background:#F8FBFC; "
            "border-top:1px solid #A7BBC3; }"
            "QLabel#unitWeaponHint { color:#4E626C; }"
        )

    def _create_unit_context_menu(self) -> tuple[QMenu, dict[str, Any]]:
        """Build the exact five-item menu observed in the reference editor."""

        menu = QMenu(self.records)
        actions = {
            "copy": menu.addAction("复制机体"),
            "paste": menu.addAction("粘贴机体"),
            "export": menu.addAction("导出机体"),
            "clear": menu.addAction("清除机体"),
            "clear_all": menu.addAction("清空全部"),
        }
        actions["paste"].setEnabled(
            self.controller._copied_record_id is not None
            and self.controller._copied_record_id != self.current_id
        )
        return menu, actions

    def _show_unit_context_menu(self, position) -> None:
        item = self.records.itemAt(position)
        if item is not None:
            self.records.setCurrentItem(item)
        if self.current_id is None:
            return
        menu, actions = self._create_unit_context_menu()
        selected = menu.exec(self.records.viewport().mapToGlobal(position))
        if selected is actions["copy"]:
            self.controller.copy_selected_record()
        elif selected is actions["paste"]:
            self.controller.paste_copied_record()
        elif selected is actions["export"]:
            self._export_current_legacy_bitmaps()
        elif selected is actions["clear"]:
            self._clear_current_unit()
        elif selected is actions["clear_all"]:
            self._clear_all_units()

    def _clear_current_unit(self) -> None:
        if self.project is None or self.current_id is None:
            return
        try:
            unit_id = self.current_id
            sync_shared = self.sync_shared_previews_check.isChecked()
            with self.project.transaction(f"机体 ${unit_id:02X} · 清除全部数据"):
                body_tiles = clear_unit_appearance_image(
                    self.project,
                    unit_id,
                    "body",
                    sync_shared_previews=sync_shared,
                )
                fragment_tiles = clear_unit_appearance_image(
                    self.project,
                    unit_id,
                    "fragment",
                    sync_shared_previews=sync_shared,
                )
                self.project.clear_unit_bundle(unit_id)
            self.controller.refresh()
            self.controller.select_record_id(unit_id)
            self.project_changed.emit(
                f"已清空机体 ${unit_id:02X} 的属性、名称、武器、主体和碎片；"
                f"清除主体图块 {body_tiles} 个、碎片图块 {fragment_tiles} 个"
            )
        except Exception as error:
            self.show_error(error)

    def _clear_all_units(self) -> None:
        if self.project is None:
            return
        selected_id = self.current_id
        try:
            self.project.clear_all_unit_bundles()
            self.controller.refresh()
            if selected_id is not None:
                self.controller.select_record_id(selected_id)
            self.project_changed.emit("已清空全部机体的属性、名称和武器")
        except Exception as error:
            self.show_error(error)

    def _show_add_capacity(self) -> None:
        QMessageBox.information(
            self,
            "机体容量已满",
            "当前 ROM 的机体编号是单字节，$01—$FF 共 255 个 ID 已全部存在，"
            "不能再创建第 256 个机体。\n\n"
            "如需替换未使用机体，请在左侧选择目标 ID，再使用“复制/粘贴”或“导入”；"
            "名称和属性均按目标机体 ID 独立保存，不会联动修改其他机体。",
        )

    def resizeEvent(self, event) -> None:  # noqa: N802 - Qt API
        super().resizeEvent(event)
        self._arrange_data_groups()
        QTimer.singleShot(0, self._sync_special_skill_geometry)

    def _sync_special_skill_geometry(self) -> None:
        """Match the composite special selector to the native spin-box row."""

        control = getattr(self, "special_skill_control", None)
        reference = self.fields.get("upgrade")
        if control is None or reference is None or reference.height() <= 0:
            return
        if control.height() != reference.height():
            control.setFixedHeight(reference.height())

    def _arrange_data_groups(self) -> None:
        if not hasattr(self, "detail_scroll"):
            return
        viewport_width = self.detail_scroll.viewport().width()
        mode = "compact" if viewport_width < 650 else (
            "medium" if viewport_width < 740 else "wide"
        )
        if mode == self._compact_data_layout:
            return
        self._compact_data_layout = mode
        self.graphics_content.setDirection(
            QBoxLayout.Direction.TopToBottom
            if mode in ("compact", "medium")
            else QBoxLayout.Direction.LeftToRight
        )
        for group in (self.basic_group, self.attributes_group, self.weapons_group):
            self.data_grid.removeWidget(group)
        for column in range(3):
            self.data_grid.setColumnStretch(column, 0)
        if mode == "compact":
            for index, group in enumerate((self.basic_group, self.attributes_group, self.weapons_group)):
                self.data_grid.addWidget(group, index, 0)
            self.data_grid.setColumnStretch(0, 1)
        elif mode == "medium":
            self.data_grid.addWidget(self.basic_group, 0, 0)
            self.data_grid.addWidget(self.attributes_group, 0, 1)
            self.data_grid.addWidget(self.weapons_group, 1, 0, 1, 2)
            self.data_grid.setColumnStretch(0, 2)
            self.data_grid.setColumnStretch(1, 3)
        else:
            self.data_grid.addWidget(self.basic_group, 0, 0)
            self.data_grid.addWidget(self.attributes_group, 0, 1)
            self.data_grid.addWidget(self.weapons_group, 0, 2)
            # Follow the reference window's lower-row proportions: the basic
            # and weapon panels are nearly equal, while the attribute panel is
            # only moderately wider (not the oversized centre card used by the
            # previous revision).
            self.data_grid.setColumnStretch(0, 28)
            self.data_grid.setColumnStretch(1, 42)
            self.data_grid.setColumnStretch(2, 30)

    @property
    def current_id(self) -> int | None:
        return self.controller.current_id

    def _disabled_button(self, text: str, tooltip: str) -> QPushButton:
        button = QPushButton(text)
        button.setEnabled(False)
        button.setToolTip(tooltip)
        return button

    def _build_graphics_group(self) -> QGroupBox:
        group = QGroupBox("机体图片")
        group.setObjectName("unitGraphicsPanel")
        root = QVBoxLayout(group)
        # Preserve the legacy 256 px preview while reclaiming the ten logical
        # pixels that otherwise forced a horizontal scrollbar with the real
        # Microsoft YaHei font at 100%/125% DPI.
        root.setContentsMargins(4, 7, 4, 6)
        root.setSpacing(3)
        self.graphics_status = QLabel("请选择机体。")
        self.graphics_status.setObjectName("unitPoolStatus")
        self.graphics_status.setWordWrap(True)
        # The module strip below already exposes the same capacity details.
        # Hiding this duplicate banner restores the legacy page's direct
        # image-first hierarchy without discarding its diagnostic state.
        self.graphics_status.hide()

        content = QHBoxLayout()
        content.setSpacing(3)
        self.graphics_content = content
        root.addLayout(content, 1)
        preview_column = QVBoxLayout()
        preview_column.setSpacing(2)
        self.body_preview = QLabel("请选择机体")
        self.body_preview.setObjectName("legacyUnitBodyPreview")
        self.body_preview.setAlignment(Qt.AlignmentFlag.AlignCenter)
        # Match the legacy editor's square 128x128 battle viewport at 2x.
        # The former 340x256 label added a wide black gutter that made the
        # unit look displaced even when its game coordinates were correct.
        self.body_preview.setFixedSize(256, 256)
        self.body_preview.setStyleSheet(
            "background: #000000; color: #d2d2d2; border: 1px solid #202020;"
        )
        self.body_preview.setToolTip(
            "按战斗画面顺序叠加主体背景层与碎片精灵层。"
        )
        preview_column.addWidget(
            self.body_preview, 0, Qt.AlignmentFlag.AlignVCenter
        )
        content.addLayout(preview_column)

        # Keep the two import columns beside the preview, matching the legacy
        # modifier's M05 unit-image panel.  The detailed composition dialog is
        # still used for the actual edit so imports retain validation, draft
        # previews and outer-dialog rollback.
        import_columns = QWidget()
        import_columns.setObjectName("unitImportColumns")
        import_columns.setFixedWidth(188)
        import_columns.setSizePolicy(
            QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Expanding
        )
        import_grid = QGridLayout(import_columns)
        import_grid.setContentsMargins(4, 2, 4, 2)
        import_grid.setHorizontalSpacing(8)
        import_grid.setVerticalSpacing(5)

        def import_column(column: int, kind: str) -> None:
            is_body = kind == "body"
            upload = QPushButton("上传机体" if is_body else "上传碎片")
            clear = QPushButton("清除机体" if is_body else "清除碎片")
            upload.setObjectName("unitUploadButton")
            clear.setObjectName("unitClearButton")
            offset_label = QLabel("导图偏移：")
            offset = QSpinBox()
            offset.setRange(0, 63 if is_body else 127)
            offset.setAlignment(Qt.AlignmentFlag.AlignCenter)
            offset.setButtonSymbols(QAbstractSpinBox.ButtonSymbols.NoButtons)
            offset.setFixedSize(82, 25)
            compress = QCheckBox("压缩/复用")
            compress.setChecked(True)
            layout = QPushButton("机体拼图" if is_body else "碎片拼图")
            layout.setObjectName("unitNavigateButton")
            show = QCheckBox("显示机体" if is_body else "显示碎片")
            show.setChecked(True)
            for button in (upload, clear, layout):
                button.setFixedSize(82, 25)
            upload.setToolTip(
                (
                    "上传不超过128×128的机体图片：未勾压缩时仅预览，勾选后"
                    "自动分块并生成拼图脚本；是否允许3像素微调由下方开关控制。"
                )
                if is_body
                else (
                    "按旧修改器规则上传原始128×128碎片图片：未勾压缩时仅预览，"
                    "勾选后才自动分块并生成拼图脚本。"
                )
            )
            clear.setToolTip(
                "只清除当前机体或碎片脚本实际引用的图块并置空脚本；"
                "同图库中未引用的素材保持不变。"
                "未扩容 ROM 也使用原生动态目录；数据库取消仍可完整撤销。"
            )
            offset.setToolTip(
                "导入的第一个图块写入当前图库的此编号。"
            )
            compress.setToolTip(
                "勾选时按原图坐标自动分块，优先复用当前图库中完全相同的图块，"
                "差异图块写入安全空位；未勾选时仅预览、不写图库或脚本。"
            )
            upload.clicked.connect(
                lambda _checked=False, target=kind: self._edit_appearance(
                    0 if target == "body" else 1, f"import_{target}"
                )
            )
            clear.clicked.connect(
                lambda _checked=False, target=kind: self._clear_appearance_from_main(target)
            )
            layout.clicked.connect(
                lambda _checked=False, target=kind: self._edit_appearance(
                    0 if target == "body" else 1
                )
            )
            show.toggled.connect(self._refresh_visuals)
            for row, widget in enumerate((
                upload, clear, offset_label, offset, compress, layout, show
            )):
                import_grid.addWidget(widget, row, column)
            if is_body:
                self.body_upload_button = upload
                self.body_clear_button = clear
                self.body_import_offset = offset
                self.body_compress_upload = compress
                self.body_layout_button = layout
                self.show_body_check = show
            else:
                self.fragment_upload_button = upload
                self.fragment_clear_button = clear
                self.fragment_import_offset = offset
                self.fragment_compress_upload = compress
                self.fragment_layout_button = layout
                self.show_fragment_check = show

        import_column(0, "body")
        import_column(2, "fragment")
        import_separator = QWidget(import_columns)
        import_separator.setObjectName("unitImportSeparator")
        import_separator.setFixedWidth(1)
        import_grid.addWidget(import_separator, 0, 1, 7, 1)
        auto_align_row = QWidget(import_columns)
        auto_align_layout = QHBoxLayout(auto_align_row)
        auto_align_layout.setContentsMargins(0, 0, 0, 0)
        auto_align_layout.setSpacing(3)
        self.body_auto_align_check = QCheckBox("导入自动微调")
        self.body_auto_align_check.setChecked(True)
        self.body_auto_align_check.setToolTip(
            "开启：按右侧像素上限搜索机体位置，只有唯一图块数严格减少时才移动；"
            "关闭：严格保持图片原位置。"
        )
        self.body_auto_align_pixels = QSpinBox()
        self.body_auto_align_pixels.setRange(1, 7)
        self.body_auto_align_pixels.setValue(3)
        self.body_auto_align_pixels.setFixedSize(40, 22)
        self.body_auto_align_pixels.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.body_auto_align_pixels.setToolTip(
            "自动微调的单轴最大像素数；8×8图块相位只需检查1—7像素。"
        )
        self.body_auto_align_pixels.setEnabled(True)
        self.body_auto_align_check.toggled.connect(
            self.body_auto_align_pixels.setEnabled
        )
        auto_align_layout.addWidget(self.body_auto_align_check)
        auto_align_layout.addWidget(self.body_auto_align_pixels)
        auto_align_layout.addWidget(QLabel("px"))
        import_grid.addWidget(
            auto_align_row,
            7,
            0,
            1,
            3,
            Qt.AlignmentFlag.AlignHCenter,
        )
        self.sync_shared_previews_check = QCheckBox("同步同组贴图")
        self.sync_shared_previews_check.setChecked(True)
        self.sync_shared_previews_check.setToolTip(
            "开启：主体或碎片拼图持续同步到原版同指针组；"
            "关闭：当前机体保持独立，但压缩导入仍会复用完全相同的8×8图块。"
        )
        import_grid.addWidget(
            self.sync_shared_previews_check,
            8,
            0,
            1,
            3,
            Qt.AlignmentFlag.AlignHCenter,
        )
        # Distribute spare height through the real control rows.  The former
        # hidden stretch row absorbed all extra room below them and left the
        # seven visible rows unnecessarily packed against the top.
        for visible_row in range(9):
            import_grid.setRowStretch(visible_row, 1)
        tool_panel = QWidget()
        tool_panel.setObjectName("unitImportPanel")
        tool_panel.setFixedWidth(190)
        tool_column = QVBoxLayout(tool_panel)
        tool_column.setContentsMargins(0, 0, 0, 0)
        tool_column.setSpacing(0)
        tool_column.addWidget(import_columns, 1, Qt.AlignmentFlag.AlignHCenter)
        content.addWidget(tool_panel)

        # Palette, type and CHR addresses form one coherent appearance editor
        # in the reference modifier.  Repeated full-height cards made this
        # narrow area look cramped and consumed useful width with duplicate
        # borders and margins, so keep one softly coloured outer container.
        visual_settings = QWidget()
        visual_settings.setObjectName("unitVisualSettingsPanel")
        visual_settings.setFixedWidth(292)
        visual_layout = QHBoxLayout(visual_settings)
        visual_layout.setContentsMargins(5, 4, 5, 4)
        visual_layout.setSpacing(6)
        content.addWidget(visual_settings)

        palette_panel = QWidget(visual_settings)
        palette_panel.setObjectName("unitPalettePanel")
        palette_panel.setFixedWidth(94)
        palette_column = QVBoxLayout(palette_panel)
        palette_column.setContentsMargins(2, 0, 2, 0)
        palette_column.setSpacing(2)
        visual_layout.addWidget(palette_panel)

        appearance_divider = QWidget(visual_settings)
        appearance_divider.setObjectName("unitAppearanceDivider")
        appearance_divider.setFixedWidth(1)
        visual_layout.addWidget(appearance_divider)

        appearance_panel = QWidget(visual_settings)
        appearance_panel.setObjectName("unitAppearancePanel")
        appearance_panel.setFixedWidth(175)
        controls = QVBoxLayout(appearance_panel)
        controls.setContentsMargins(0, 0, 0, 0)
        controls.setSpacing(2)
        visual_layout.addWidget(appearance_panel)

        # Retain the summary as non-visual state for diagnostics and tests.  The
        # old editor did not spend a full row repeating these record details.
        self.appearance_summary = QLabel("外观记录：—", group)
        self.appearance_summary.setWordWrap(True)
        self.appearance_summary.setAlignment(
            Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop
        )
        self.appearance_summary.setFixedHeight(26)
        self.appearance_summary.setStyleSheet(
            "background:#F5F8FA; border:1px solid #D9E2E8; padding:4px;"
        )
        self.appearance_summary.hide()

        appearance_fields = QWidget()
        appearance_fields.setSizePolicy(
            QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Expanding
        )
        appearance_grid = QGridLayout(appearance_fields)
        appearance_grid.setContentsMargins(0, 0, 0, 0)
        appearance_grid.setHorizontalSpacing(5)
        appearance_grid.setVerticalSpacing(2)
        self.appearance_type = QComboBox()
        for label, code in (
            ("我方小型机", 0x00),
            ("敌方小型机", 0x40),
            ("我方大型机", 0x80),
            ("敌方大型机", 0xC0),
        ):
            self.appearance_type.addItem(label, code)
        self.appearance_type.setToolTip(
            "控制战斗画面的敌我方向和主体图库数量；切换大型机时启用图片地址2。"
        )
        # The old editor kept these selectors close to their actual content
        # width.  Letting the grid stretch them wastes most of the right-hand
        # panel and, at 125% DPI, pushes the weapon controls off screen.
        self.appearance_type.setFixedWidth(175)
        self.appearance_type.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed
        )
        self.appearance_type.setFixedHeight(25)
        self.appearance_type.currentIndexChanged.connect(
            self._set_appearance_type
        )
        type_header = QWidget()
        type_header_layout = QHBoxLayout(type_header)
        type_header_layout.setContentsMargins(0, 0, 0, 0)
        type_header_layout.setSpacing(4)
        appearance_type_heading = QLabel("机体类型")
        appearance_type_heading.setObjectName("unitAppearanceHeading")
        type_header_layout.addWidget(appearance_type_heading)
        type_header_layout.addStretch(1)
        self.captain_check = QCheckBox("舰长")
        self.captain_check.setToolTip(
            "大型机专用标志；对应旧修改器“舰长”复选框和外观记录位 $20。"
        )
        self.captain_check.toggled.connect(self._set_appearance_captain)
        type_header_layout.addWidget(self.captain_check)
        appearance_grid.addWidget(type_header, 0, 0)
        appearance_grid.addWidget(self.appearance_type, 1, 0)

        self.appearance_bank_editors: list[ChrBankComboBox | None] = [None, None, None]
        # Match the reference editor's visual order exactly: body page 1,
        # optional body page 2, then the fragment page.  The backing list
        # remains indexed as fragment/body1/body2 for codec compatibility.
        for bank_index, caption, row in (
            (1, "机体图片地址1", 2),
            (2, "机体图片地址2", 4),
            (0, "机体碎片地址", 6),
        ):
            editor = ChrBankComboBox()
            editor.setToolTip(
                "格式为[十六进制图库号]十进制图库号: 文件偏移；"
                "选择后立即修改当前外观记录并按游戏规则刷新预览。"
            )
            editor.valueChanged.connect(
                lambda value, index=bank_index: self._set_appearance_bank(index, value)
            )
            # Keep the complete bank/page/file-offset triplet readable without
            # using the wide, two-column field strip from the newer layout.
            editor.setMinimumContentsLength(16)
            editor.setFixedWidth(175)
            editor.setSizePolicy(
                QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed
            )
            editor.setFixedHeight(25)
            self.appearance_bank_editors[bank_index] = editor
            column = 0
            label = QLabel(caption)
            label.setObjectName("unitAppearanceHeading")
            label.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
            appearance_grid.addWidget(label, row, column)
            appearance_grid.addWidget(editor, row + 1, column)
        for row in range(8):
            appearance_grid.setRowStretch(row, 1)
        appearance_fields.setFixedWidth(175)
        controls.addWidget(appearance_fields, 1)
        self.appearance_bank_editors = [
            editor for editor in self.appearance_bank_editors if editor is not None
        ]

        self.appearance_color_buttons: list[CompactNesColorField] = []
        palette_rows = []
        for group_index, caption in enumerate(("机体三色", "碎片三色")):
            palette_row = QWidget()
            palette_layout = QVBoxLayout(palette_row)
            palette_layout.setContentsMargins(0, 0, 0, 0)
            palette_layout.setSpacing(2)
            label = QLabel(caption)
            label.setObjectName("unitPaletteHeading")
            palette_layout.addWidget(label)
            palette_layout.addStretch(1)
            for local_index in range(3):
                color_index = group_index * 3 + local_index
                button = CompactNesColorField()
                button.swatch.setFixedSize(28, 24)
                button.code_button.setFixedSize(52, 24)
                button.setFixedSize(84, 24)
                button.value_changed.connect(
                    lambda value, index=color_index: self._set_appearance_color(index, value)
                )
                self.appearance_color_buttons.append(button)
                palette_layout.addWidget(button)
                if local_index < 2:
                    palette_layout.addStretch(1)
            palette_rows.append(palette_row)
            palette_column.addWidget(palette_row, 1)
        # Keep these public labels for status/error reporting used elsewhere.
        self.body_palette_caption = palette_rows[0].findChildren(QLabel)[0]
        self.fragment_palette_caption = palette_rows[1].findChildren(QLabel)[0]
        icon_box = QWidget()
        icon_box.setObjectName("unitIconStrip")
        self.icon_group = icon_box
        icon_box.setFixedSize(188, 42)
        icon_layout = QHBoxLayout(icon_box)
        icon_layout.setContentsMargins(2, 4, 2, 4)
        icon_layout.setSpacing(2)
        icon_layout.addWidget(QLabel("机体图标"))
        self.icon_bank = QComboBox(icon_box)
        self.icon_bank.setFixedWidth(72)
        for bank in MAP_ICON_BANK_CANDIDATES:
            self.icon_bank.addItem(f"图库 ${bank:02X}", bank)
        self.icon_bank.currentIndexChanged.connect(self._refresh_icon_bank)
        self.icon_bank.hide()
        self.icon_index = QComboBox(icon_box)
        self.icon_index.setFixedWidth(64)
        for index in range(16):
            self.icon_index.addItem(f"图标 {index:X}", index)
        self.icon_index.currentIndexChanged.connect(self._refresh_icon_bank)
        self.icon_index.hide()
        # The reference editor places the icon tools below the two import
        # columns, not below the type/address column.
        self.icon_preview = QLabel("—")
        self.icon_preview.setObjectName("legacyUnitIconPreview")
        self.icon_preview.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.icon_preview.setFixedSize(30, 30)
        self.icon_preview.setStyleSheet(
            "background: #000000; color: white; border: 1px solid #4d555c;"
        )
        icon_layout.addWidget(self.icon_preview)
        self.icon_address = QLineEdit(icon_box)
        self.icon_address.setReadOnly(True)
        self.icon_address.setMinimumWidth(0)
        self.icon_address.hide()
        self.edit_icon_button = QPushButton("上传图标")
        self.edit_icon_button.setObjectName("unitUploadButton")
        self.edit_icon_button.setFixedSize(46, 24)
        self.edit_icon_button.setText("上传")
        self.edit_icon_button.setToolTip(
            "打开真实CHR图标编辑器；可编辑像素，或导入、导出旧版24位BMP。"
        )
        self.edit_icon_button.clicked.connect(self._edit_unit_icon)
        self.bind_icon_button = QPushButton("更改图标")
        self.bind_icon_button.setObjectName("unitNavigateButton")
        self.bind_icon_button.setFixedSize(46, 24)
        self.bind_icon_button.setText("更改")
        self.bind_icon_button.setToolTip(
            "像旧修改器一样，按机体出现关卡查看动态图库路由并选择图标。"
        )
        self.bind_icon_button.clicked.connect(self._choose_unit_icon)
        icon_layout.addWidget(self.edit_icon_button)
        icon_layout.addWidget(self.bind_icon_button)
        tool_column.addWidget(icon_box, 0, Qt.AlignmentFlag.AlignHCenter)

        # Retain these non-visual compatibility objects for refresh and tests.
        # Their former collapsible panel duplicated the dedicated composition
        # dialog and consumed a large vertical block in the main unit page.
        self.raw_body_preview = QLabel("请选择机体", group)
        self.raw_body_preview.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.raw_body_preview.hide()
        self.fragment_preview = QLabel("请选择机体", group)
        self.fragment_preview.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.fragment_preview.hide()
        self.appearance_details = QPlainTextEdit(group)
        self.appearance_details.setReadOnly(True)
        self.appearance_details.hide()
        self.unsupported_graphics_buttons: list[QPushButton] = []
        # Use the page's existing lower slack to let the import rows breathe;
        # the outer database window remains the same size.
        group.setFixedHeight(300)
        return group

    def _set_appearance_color(self, color_index: int, value: int) -> None:
        """Apply a palette-cell choice inside the outer database transaction."""

        if self.project is None or self.current_id is None:
            return
        try:
            appearance = read_unit_appearance(self.project, self.current_id)
            count = 9 if appearance.configuration[0] & 0x80 else 8
            values = list(appearance.configuration[1:1 + count])
            if values[color_index] == value:
                return
            values[color_index] = value
            offset, before, after = appearance_patch(
                self.project, self.current_id, tuple(values)
            )
            with self.project.transaction(
                f"机体 ${self.current_id:02X} · 颜色{color_index + 1}"
            ):
                self.project.working[offset:offset + len(after)] = after
            self._refresh_visuals()
        except (ValueError, IndexError) as error:
            self.show_error(error)

    def _set_appearance_type(self, _index: int) -> None:
        if self.project is None or self.current_id is None:
            return
        try:
            appearance = read_unit_appearance(self.project, self.current_id)
            code = int(self.appearance_type.currentData())
            captain_flag = (
                appearance.configuration[0] & 0x20 if code & 0x80 else 0
            )
            desired_type = code | captain_flag
            if appearance.configuration[0] == desired_type:
                return
            configuration = bytearray(appearance.configuration)
            if code & 0x80 and not appearance.configuration[0] & 0x80:
                # A stock small record's normalised tenth byte belongs to the
                # next physical record.  Initialise the new second body page
                # from address1 instead of exposing that neighbour byte.
                configuration[9] = min(
                    configuration[8] + 1,
                    self.project.chr_tile_count // 64 - 1,
                )
            configuration[0] = desired_type
            rebuilt_body_script = None
            if not code & 0x80:
                try:
                    decode_unit_body_script(appearance.body_script, 64)
                except ValueError:
                    # A one-bank small unit cannot reference the large unit's
                    # $40-$7F body tiles.  Match the composition editor and
                    # immediately produce a valid legacy 8x8 one-bank script.
                    start_x = 0xF9 if code & 0x40 else 0x00
                    rebuilt_body_script = bytes.fromhex(
                        f"F3 F9 {start_x:02X} FD 20 08 F9 40 00 FF"
                    )
                    if self.project.expansion_plan is None:
                        raise ValueError(
                            "该大型机拼图使用了图片地址2；请先完成机体扩容，"
                            "再切换为小型机并自动重建单图库脚本。"
                        )
            with self.project.transaction(
                f"机体 ${self.current_id:02X} · 类型与拼图"
            ):
                self.project.set_unit_appearance_configuration(
                    self.current_id, bytes(configuration)
                )
                if rebuilt_body_script is not None:
                    self.project.set_unit_appearance_scripts(
                        self.current_id,
                        body_script=rebuilt_body_script,
                        fragment_script=appearance.fragment_script,
                    )
            self._refresh_visuals()
        except (ValueError, IndexError) as error:
            self.show_error(error)
            self._refresh_visuals()

    def _set_appearance_captain(self, checked: bool) -> None:
        if self.project is None or self.current_id is None:
            return
        try:
            appearance = read_unit_appearance(self.project, self.current_id)
            if not appearance.configuration[0] & 0x80:
                self._refresh_visuals()
                return
            configuration = bytearray(appearance.configuration)
            desired = (
                configuration[0] | 0x20
                if checked
                else configuration[0] & ~0x20
            )
            if configuration[0] == desired:
                return
            configuration[0] = desired
            self.project.set_unit_appearance_configuration(
                self.current_id, bytes(configuration)
            )
            self._refresh_visuals()
        except (ValueError, IndexError) as error:
            self.show_error(error)
            self._refresh_visuals()

    def _set_appearance_bank(self, bank_index: int, value: int) -> None:
        if self.project is None or self.current_id is None:
            return
        try:
            appearance = read_unit_appearance(self.project, self.current_id)
            configuration = bytearray(appearance.configuration)
            offset = 7 + bank_index
            if configuration[offset] == value:
                return
            configuration[offset] = value
            self.project.set_unit_appearance_configuration(
                self.current_id, bytes(configuration)
            )
            self._refresh_visuals()
        except (ValueError, IndexError) as error:
            self.show_error(error)
            self._refresh_visuals()

    def _build_data_row(self) -> QGridLayout:
        row = QGridLayout()
        self.data_grid = row
        row.setSpacing(8)

        basic = QGroupBox("基本设置")
        basic.setObjectName("unitBasicPanel")
        self.basic_group = basic
        basic_form = QFormLayout(basic)
        basic_form.setContentsMargins(11, 14, 11, 10)
        basic_form.setHorizontalSpacing(8)
        basic_form.setVerticalSpacing(20)
        basic_form.setFormAlignment(Qt.AlignmentFlag.AlignVCenter)
        self.name_text.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed
        )
        basic_form.addRow("机体名称", self.name_text)
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
        for value, label in (UNIT_FIELD_BY_KEY["transform"].choices or {}).items():
            self.transform.addItem(label, value)
        self.transform.currentIndexChanged.connect(self._transform_changed)
        self.fields["transform"].valueChanged.connect(self._refresh_transform)
        self.transform.setToolTip(
            "只修改机体类型字节的高六位；适应地形低两位保持不变。"
        )
        basic_form.addRow("变形", self.transform)
        self.basic_note = QLabel("适应地形与变形共同组成机体类型字段。")
        self.basic_note.setObjectName("unitPanelNote")
        self.basic_note.setWordWrap(True)
        basic_form.addRow(self.basic_note)
        self.basic_note.hide()
        technical = QWidget()
        technical_form = QFormLayout(technical)
        technical_form.setContentsMargins(0, 0, 0, 0)
        technical_form.addRow("名称引用", self.name_reference)
        self.record_meta = self.controller.record_meta
        self.record_meta.setWordWrap(True)
        technical_form.addRow("记录位置", self.record_meta)
        self.raw_unit_record = QLineEdit()
        self.raw_unit_record.setReadOnly(True)
        self.raw_unit_record.setToolTip("当前属性指针实际指向的完整16字节；零值也是ROM中的真实内容。")
        technical_form.addRow("完整16字节", self.raw_unit_record)
        self.raw_type_flags = QLineEdit()
        self.raw_type_flags.setReadOnly(True)
        technical_form.addRow("类型/标志原码", self.raw_type_flags)
        self.raw_graphics_index = QLineEdit()
        self.raw_graphics_index.setReadOnly(True)
        self.raw_graphics_index.setToolTip(
            "属性记录 +2 的地图小图标首图块；每个图标连续使用四个 8×8 图块。"
        )
        technical_form.addRow("地图小图标", self.raw_graphics_index)
        # Keep the record widgets alive for controller refresh/save compatibility,
        # but remove the technical disclosure from the everyday editing surface.
        technical.setParent(basic)
        technical.hide()
        row.addWidget(basic, 0, 0)

        attributes = QGroupBox("机体属性")
        attributes.setObjectName("unitAttributesPanel")
        self.attributes_group = attributes
        attribute_grid = QGridLayout(attributes)
        attribute_grid.setContentsMargins(7, 14, 7, 8)
        attribute_grid.setHorizontalSpacing(10)
        attribute_grid.setVerticalSpacing(2)
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
                if field_key is None:
                    label = QLabel(next(placeholders))
                    editor = QSpinBox()
                    editor.setEnabled(False)
                    editor.setToolTip("该字段在当前ROM中的语义尚未验证。")
                else:
                    label = QLabel(labels[field_key])
                    editor = self.fields[field_key]
                label.setAlignment(
                    Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter
                )
                # The reference editor uses three vertical field columns:
                # caption above, value below.  Keeping caption and editor on
                # the same line made Chinese labels collide at the real
                # 1050 px window width even though off-screen tests passed.
                row_base = grid_row * 2
                attribute_grid.addWidget(label, row_base, logical_column)
                if field_key == "special":
                    self.special_skill_control = QWidget()
                    self.special_skill_control.setObjectName("unitSpecialField")
                    self.special_skill_control.setFixedWidth(72)
                    self.special_skill_control.setSizePolicy(
                        QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Preferred
                    )
                    special_layout = QHBoxLayout(self.special_skill_control)
                    special_layout.setContentsMargins(0, 0, 0, 0)
                    special_layout.setSpacing(0)
                    self.special_skill_button = QPushButton()
                    self.special_skill_button.setObjectName("unitSpecialValueButton")
                    self.special_skill_button.setToolTip(
                        "点击按旧修改器的组合位定义编辑机体特殊技能。"
                    )
                    self.special_skill_button.setFixedWidth(50)
                    self.special_skill_button.clicked.connect(
                        self._edit_special_skill
                    )
                    self.special_skill_expand_button = QToolButton()
                    self.special_skill_expand_button.setObjectName(
                        "unitSpecialExpandButton"
                    )
                    self.special_skill_expand_button.setArrowType(
                        Qt.ArrowType.DownArrow
                    )
                    self.special_skill_expand_button.setFixedWidth(22)
                    self.special_skill_expand_button.setToolTip(
                        "展开机体特殊技能选择。"
                    )
                    self.special_skill_expand_button.clicked.connect(
                        self._edit_special_skill
                    )
                    special_layout.addWidget(self.special_skill_button)
                    special_layout.addWidget(self.special_skill_expand_button)
                    editor.hide()
                    editor.valueChanged.connect(self._refresh_special_skill_button)
                    self._refresh_special_skill_button(editor.value())
                    attribute_grid.addWidget(
                        self.special_skill_control, row_base + 1, logical_column
                    )
                else:
                    # Keep the three legacy-style attribute columns within the
                    # real 125% DPI viewport.  The former size hints forced the
                    # whole detail page wider than the window by about 45 px.
                    editor.setFixedWidth(72)
                    attribute_grid.addWidget(editor, row_base + 1, logical_column)
                attribute_grid.setColumnStretch(logical_column, 1)
        row.addWidget(attributes, 0, 1)

        weapons = QGroupBox("机体武器")
        weapons.setObjectName("unitWeaponsPanel")
        self.weapons_group = weapons
        weapons_layout = QVBoxLayout(weapons)
        weapons_layout.setContentsMargins(11, 14, 11, 10)
        weapons_layout.setSpacing(9)
        weapons_layout.addStretch(1)
        self.weapon_jump_buttons: list[QPushButton] = []
        for slot, editor in enumerate(self.weapon_slots):
            # Match the legacy editor: keep the label and jump action on the
            # first line, then give the weapon selector the complete second
            # line.  Long names remain visible without hiding the action.
            slot_row = QGridLayout()
            slot_row.setHorizontalSpacing(5)
            slot_row.setVerticalSpacing(2)
            slot_row.addWidget(QLabel(f"武器{slot + 1}"), 0, 0)
            editor.setSizeAdjustPolicy(
                QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon
            )
            editor.setMinimumContentsLength(16)
            editor.setMinimumWidth(0)
            editor.setSizePolicy(
                QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed
            )
            jump = QPushButton(f"转到武器{slot + 1}")
            jump.setObjectName("unitNavigateButton")
            jump.setFixedSize(80, 22)
            jump.clicked.connect(
                lambda _checked=False, weapon_slot=slot: self._request_weapon(weapon_slot)
            )
            editor.currentIndexChanged.connect(
                lambda _index, source=editor, button=jump: button.setEnabled(
                    source.isEnabled() and bool(source.currentData())
                )
            )
            jump.setEnabled(False)
            slot_row.addWidget(jump, 0, 1, Qt.AlignmentFlag.AlignRight)
            slot_row.addWidget(editor, 1, 0, 1, 2)
            slot_row.setColumnStretch(0, 1)
            weapons_layout.addLayout(slot_row)
            self.weapon_jump_buttons.append(jump)
        warning = QLabel(
            "跳转会自动暂存当前机体；本窗口“取消”仍可回滚全部修改。"
        )
        warning.setWordWrap(True)
        warning.setObjectName("unitWeaponHint")
        weapons_layout.addWidget(warning)
        weapons_layout.addStretch(1)
        row.addWidget(weapons, 1, 0, 1, 2)
        for group in (basic, attributes, weapons):
            # The global theme adds comfortable control padding, but its
            # aggregate size hints must not force a horizontal scrollbar.
            # Keep the legacy 2:3:2 panel proportions and allow long combo
            # text to elide inside its own field.
            group.setSizePolicy(
                QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred
            )
            group.setMinimumWidth(0)
            group.setMinimumHeight(250)
            group.setMaximumHeight(258)
        return row

    def _refresh_special_skill_button(self, value: int) -> None:
        text = "无" if value == 0 else str(value)
        self.special_skill_button.setText(text)
        self.special_skill_button.setToolTip(
            unit_special_summary(value) + "\n点击编辑组合能力。"
        )

    def _transform_changed(self, index: int) -> None:
        value = self.transform.itemData(index)
        if value is not None:
            self.fields["transform"].setValue(int(value))

    def _refresh_transform(self, value: int) -> None:
        index = self.transform.findData(value)
        if index < 0:
            self.transform.addItem(f"保留原码 ${value << 2:02X}", value)
            index = self.transform.count() - 1
        blocked = self.transform.blockSignals(True)
        self.transform.setCurrentIndex(index)
        self.transform.blockSignals(blocked)

    def _edit_special_skill(self) -> None:
        editor = self.fields["special"]
        dialog = UnitSpecialEditorDialog(editor.value(), self)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            editor.setValue(dialog.value())

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

    def _export_current_legacy_bitmaps(self) -> None:
        if self.project is None or self.current_id is None:
            return
        directory = QFileDialog.getExistingDirectory(
            self,
            "选择当前机体五张位图的导出位置",
            str(default_export_path("")),
        )
        if not directory:
            return
        try:
            if not self.commit_pending_changes():
                return
            written = export_legacy_unit_bitmaps_for_id(
                self.project,
                writable_output_path(Path(directory)),
                self.current_id,
            )
            output_directory = written[0].parent
            self.session_hint.setText(
                f"已导出当前机体五张 BMP：{output_directory}"
            )
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
            answer = QMessageBox.question(
                self, "确认导入范围",
                f"来源：{package.label}\n目标：{self.project.unit_display_name(self.current_id)}"
                f" [${self.current_id:02X}]\n"
                "16字节属性与名称引用均只修改当前目标；重复属性指针会自动拆分。"
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
        index = int(self.icon_index.currentData())
        side = "我"
        if self.current_id is not None:
            try:
                side = (
                    "敌"
                    if read_unit_appearance(
                        self.project, self.current_id
                    ).configuration[0] & 0x40
                    else "我"
                )
            except (ValueError, IndexError):
                pass
        palette_values = MAP_ICON_PALETTES_NES[side]
        image = render_unit_icon_bank(
            self.project, bank, palette_values
        ).copy(index * 16, 0, 16, 16)
        self.icon_preview.setPixmap(QPixmap.fromImage(image).scaled(
            32, 32, Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.FastTransformation,
        ))
        offset = self.project.chr_codec.offset + bank * 0x400 + index * 0x40
        icon_byte = (
            self.project.record_bytes(self.current_id)[2]
            if self.current_id is not None else 0
        )
        self.icon_address.setText(
            f"机体字段 ${icon_byte:02X} · 图库 ${bank:02X} · 文件 0x{offset:06X}"
        )

    @staticmethod
    def _icon_bank_slot(bank: int) -> int:
        slots = {
            slot
            for route in SCENARIO_MAP_ICON_BANKS
            for slot, current_bank in enumerate(route)
            if current_bank == bank
        }
        if len(slots) != 1:
            raise ValueError("所选图库不能唯一对应地图图标窗口。")
        return slots.pop()

    def _bind_unit_icon(self) -> None:
        if self.project is None or self.current_id is None:
            return
        try:
            bank = int(self.icon_bank.currentData())
            slot = self._icon_bank_slot(bank)
            index = int(self.icon_index.currentData())
            value = slot * 0x40 + index * 4
            self.project.set_value(self.current_id, "candidate_02", value)
            self._refresh_visuals()
        except (ValueError, IndexError) as error:
            self.show_error(error)

    def _choose_unit_icon(self) -> None:
        if self.project is None or self.current_id is None:
            return
        try:
            raw_value = self.project.record_bytes(self.current_id)[2]
            side = (
                "敌"
                if read_unit_appearance(
                    self.project, self.current_id
                ).configuration[0] & 0x40
                else "我"
            )
            dialog = UnitIconBindingDialog(
                self.project,
                raw_value,
                MAP_ICON_PALETTES_NES[side],
                self,
            )
            if dialog.exec() != QDialog.DialogCode.Accepted:
                return
            self.project.set_value(
                self.current_id, "candidate_02", dialog.raw_icon_value
            )
            self._refresh_visuals()
            self.icon_bank.blockSignals(True)
            self.icon_bank.setCurrentIndex(
                self.icon_bank.findData(dialog.selected_bank)
            )
            self.icon_bank.blockSignals(False)
            self.icon_index.blockSignals(True)
            self.icon_index.setCurrentIndex(
                self.icon_index.findData(dialog.selected_icon_index)
            )
            self.icon_index.blockSignals(False)
            self._refresh_icon_bank()
        except (ValueError, IndexError) as error:
            self.show_error(error)

    def _edit_unit_icon(self) -> None:
        if self.project is None or self.current_id is None:
            return
        try:
            bank = int(self.icon_bank.currentData())
            index = int(self.icon_index.currentData())
            side = (
                "敌"
                if read_unit_appearance(
                    self.project, self.current_id
                ).configuration[0] & 0x40
                else "我"
            )
            dialog = UnitIconDialog(
                self.project,
                bank,
                index,
                MAP_ICON_PALETTES_NES[side],
                self,
            )
            if dialog.exec() == QDialog.DialogCode.Accepted and dialog.changed:
                self._refresh_icon_bank()
        except (ValueError, IndexError) as error:
            self.show_error(error)

    def _edit_appearance(self, tab_index: int = 0, initial_action: str | None = None) -> None:
        if self.project is None or self.current_id is None:
            return
        try:
            dialog = UnitAppearanceDialog(self.project, self.current_id, self)
            dialog.preview_tabs.setCurrentIndex(tab_index)
            dialog.body_import_offset.setValue(self.body_import_offset.value())
            dialog.body_compress_upload.setChecked(self.body_compress_upload.isChecked())
            dialog.body_auto_align_check.setChecked(
                self.body_auto_align_check.isChecked()
            )
            dialog.body_auto_align_pixels.setValue(
                self.body_auto_align_pixels.value()
            )
            dialog.fragment_import_offset.setValue(self.fragment_import_offset.value())
            dialog.fragment_compress_upload.setChecked(
                self.fragment_compress_upload.isChecked()
            )
            dialog.sync_shared_previews_check.setChecked(
                self.sync_shared_previews_check.isChecked()
            )
            if initial_action is not None:
                kind = "body" if initial_action.endswith("body") else "fragment"
                if initial_action.startswith("import_"):
                    QTimer.singleShot(
                        0, lambda: dialog._import_library(kind, strict_legacy=True)
                    )
                elif initial_action.startswith("clear_"):
                    QTimer.singleShot(0, lambda: dialog._clear_image(kind))
            result = dialog.exec()
            self.sync_shared_previews_check.setChecked(
                dialog.sync_shared_previews_check.isChecked()
            )
            self.body_auto_align_check.setChecked(
                dialog.body_auto_align_check.isChecked()
            )
            self.body_auto_align_pixels.setValue(
                dialog.body_auto_align_pixels.value()
            )
            if result == QDialog.DialogCode.Accepted and dialog.changed:
                # Refresh graphics only: an uncommitted attribute form belongs
                # to the outer page and must not be discarded by this action.
                self._refresh_visuals()
        except (ValueError, IndexError) as error:
            self.show_error(error)

    def _clear_appearance_from_main(self, kind: str) -> None:
        """Clear one composed image directly without opening its puzzle page."""

        if self.project is None or self.current_id is None:
            return
        subject = "机体" if kind == "body" else "碎片"
        try:
            cleared = clear_unit_appearance_image(
                self.project,
                self.current_id,
                kind,
                sync_shared_previews=(
                    self.sync_shared_previews_check.isChecked()
                ),
            )
            self._refresh_visuals()
            self.project_changed.emit(
                f"已清除机体 ${self.current_id:02X} 的{subject}拼图及其实际引用的"
                f" {cleared} 个图块；同图库未引用图块保持不变"
            )
        except (ValueError, IndexError) as error:
            self.show_error(error)

    def _refresh_visuals(self) -> None:
        self._refresh_icon_bank()
        self.record_count.setText(
            f"{self.project.unit_count - 1} 个机体ID槽位；属性按逻辑ID独立修改。"
            if self.project is not None else "尚未载入机体。"
        )
        if self.project is None or self.current_id is None:
            self.body_preview.setText("请选择机体")
            self.raw_body_preview.setText("请选择机体")
            self.fragment_preview.setText("请选择机体")
            self.appearance_summary.setText("外观记录：—")
            self.body_palette_caption.setText("机体三色：—")
            self.fragment_palette_caption.setText("碎片三色：—")
            for button in self.appearance_color_buttons:
                button.setEnabled(False)
            self.appearance_type.setEnabled(False)
            self.captain_check.setEnabled(False)
            self.captain_check.hide()
            for editor in self.appearance_bank_editors:
                editor.setEnabled(False)
            self.appearance_details.clear()
            self.raw_unit_record.clear()
            self.raw_type_flags.clear()
            self.raw_graphics_index.clear()
            return
        unit_id = self.current_id
        raw = self.project.record_bytes(unit_id)
        self.raw_unit_record.setText(raw.hex(" ").upper())
        self.raw_type_flags.setText(
            f"${raw[0]:02X} · 地形低2位 {raw[0] & 3} · 其余标志 ${raw[0] & 0xFC:02X}"
        )
        self.raw_graphics_index.setText(f"${raw[2]:02X}")
        icon_slot, icon_tile = divmod(raw[2], 0x40)
        icon_index = icon_tile // 4
        if icon_slot < 3 and raw[2] % 4 == 0:
            preview_bank = SCENARIO_MAP_ICON_BANKS[0][icon_slot]
            self.icon_bank.blockSignals(True)
            self.icon_bank.setCurrentIndex(self.icon_bank.findData(preview_bank))
            self.icon_bank.blockSignals(False)
            self.icon_index.blockSignals(True)
            self.icon_index.setCurrentIndex(self.icon_index.findData(icon_index))
            self.icon_index.blockSignals(False)
            self._refresh_icon_bank()
        self._refresh_transform(self.fields["transform"].value())
        try:
            appearance = read_unit_appearance(self.project, unit_id)
            try:
                pool = self.project.unit_composition_pool_status()
                if pool.shared:
                    pool_text = (
                        f"共享脚本池 {pool.total_used}/{pool.total_capacity} B，"
                        f"剩余 {pool.total_available} B"
                    )
                else:
                    pool_text = (
                        f"主体池 {pool.body_used}/{pool.body_capacity} B；"
                        f"碎片池 {pool.fragment_used}/{pool.fragment_capacity} B；"
                        f"合计剩余 {pool.total_available} B"
                    )
                allocation_text = f"{pool_text}；保存时整体重排指针，可变长。"
            except ValueError:
                allocation_text = "当前拼图目录无法验证，已禁用变长写入。"
            self.graphics_status.setText(
                f"主体 {len(appearance.body_script)} B · "
                f"碎片 {len(appearance.fragment_script)} B；{allocation_text}"
            )
            fragment_bank = appearance.primary_bank & 0xFE
            type_code = appearance.configuration[0] & 0xC0
            unit_type = dict((
                (0x00, "我方小型机"),
                (0x40, "敌方小型机"),
                (0x80, "我方大型机"),
                (0xC0, "敌方大型机"),
            ))[type_code]
            self.appearance_summary.setText(
                f"外观记录：0x{appearance.file_offset:06X}　"
                "机体类型与三个图片地址均可直接选择编辑"
            )
            self.appearance_type.blockSignals(True)
            self.appearance_type.setCurrentIndex(
                self.appearance_type.findData(type_code)
            )
            self.appearance_type.setEnabled(True)
            self.appearance_type.blockSignals(False)
            is_large = bool(type_code & 0x80)
            self.captain_check.blockSignals(True)
            self.captain_check.setChecked(
                bool(appearance.configuration[0] & 0x20)
            )
            self.captain_check.setEnabled(is_large)
            self.captain_check.setVisible(is_large)
            self.captain_check.blockSignals(False)
            bank_limit = max(0, self.project.chr_tile_count // 64 - 1)
            for bank_index, editor in enumerate(self.appearance_bank_editors):
                editor.blockSignals(True)
                editor.set_project(self.project)
                editor.setRange(0, bank_limit)
                editor.setValue(appearance.configuration[7 + bank_index])
                editor.setEnabled(bank_index < 2 or bool(type_code & 0x80))
                editor.blockSignals(False)
            self.appearance_details.setPlainText(
                f"外观记录文件位置：0x{appearance.file_offset:06X}\n"
                f"归一化外观记录：{appearance.configuration.hex(' ').upper()}\n"
                f"主体拼图：{appearance.body_script.hex(' ').upper()}\n"
                f"碎片拼图：{appearance.fragment_script.hex(' ').upper()}"
            )
            for caption, label, colors in (
                ("机体三色", self.body_palette_caption, appearance.first_palette),
                ("碎片三色", self.fragment_palette_caption, appearance.second_palette),
            ):
                label.setText(caption)
            for button, value in zip(
                self.appearance_color_buttons,
                (*appearance.first_palette, *appearance.second_palette),
            ):
                button.blockSignals(True)
                button.set_value(value)
                button.setEnabled(True)
                button.blockSignals(False)
            body_picture = render_unit_battle_preview(
                self.project, appearance,
                show_body=self.show_body_check.isChecked(),
                show_fragments=self.show_fragment_check.isChecked(),
            )
            self.body_preview.setPixmap(QPixmap.fromImage(body_picture).scaled(
                self.body_preview.size(),
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.FastTransformation,
            ))
            self.body_preview.setToolTip(
                "战斗合成预览 · 主体图库 "
                + " / ".join(f"${bank:02X}" for bank in appearance.secondary_banks)
                + f" · 碎片图库 ${fragment_bank:02X}/${fragment_bank + 1:02X}"
            )
            for label, banks, palette in (
                (self.raw_body_preview, appearance.secondary_banks, appearance.first_palette),
                (self.fragment_preview, (fragment_bank, fragment_bank + 1),
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
            self.raw_body_preview.setText("此配置暂不支持图库预览")
            self.fragment_preview.setText("此配置暂不支持图库预览")
            self.appearance_details.clear()
            self.appearance_summary.setText("外观记录：未读取")
            self.body_palette_caption.setText("机体三色：未读取")
            self.fragment_palette_caption.setText("碎片三色：未读取")
            for button in self.appearance_color_buttons:
                button.setEnabled(False)
            self.appearance_type.setEnabled(False)
            self.captain_check.setEnabled(False)
            self.captain_check.hide()
            for editor in self.appearance_bank_editors:
                editor.setEnabled(False)

        for field_key, editor in self.fields.items():
            base_value = self.project.get_value(unit_id, field_key, original=True)
            scale = self.project.unit_field(field_key).display_scale
            editor.setToolTip(
                f"{editor.toolTip().split('；基准ROM：')[0]}；"
                f"基准ROM：{base_value * scale}"
            )

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

    VERIFIED_LEVEL_CAP_TOOLTIP = (
        "当前受支持 ROM 已是99级布局（运行时 CMP #$62、累计经验表99项、"
        "成长记录50字节）。3778字节的60→61样本来自产品不支持的audit.nes，"
        "不能套用；超过99级的表重排协议尚未验证。"
    )

    def __init__(self) -> None:
        super().__init__()
        self._loading = False
        root = QVBoxLayout(self)
        experience_group = QGroupBox("升级经验")
        self.experience_group = experience_group
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
        level_cap_row = QHBoxLayout()
        self.level_cap_value = QLabel("当前等级上限：—")
        self.level_cap_button = QPushButton("更改等级上限")
        self.level_cap_button.setToolTip("当前ROM的等级上限布局尚未验证。")
        self.level_cap_button.clicked.connect(self._show_level_cap_boundary)
        level_cap_row.addWidget(self.level_cap_value)
        level_cap_row.addStretch()
        level_cap_row.addWidget(self.level_cap_button)
        experience_layout.addLayout(level_cap_row)
        tables = QHBoxLayout()
        tables.addWidget(experience_group, 11)

        distance_group = QGroupBox("武器距离命中补正")
        self.distance_group = distance_group
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
        # Keep the verified 4×16 matrix as the backing editor for API/tests,
        # but present it like the legacy modifier: choose one method, then edit
        # a readable 16-row distance/percentage table.  The former 16-column
        # surface was unusable in the intended narrow right-hand panel.
        self.distance_table.hide()
        self.distance_method = QComboBox()
        for method in range(4):
            self.distance_method.addItem(f"方式 {method}", method)
        self.distance_method.currentIndexChanged.connect(self._refresh_distance_view)
        distance_layout.addWidget(self.distance_method)
        self.distance_view = QTableWidget(16, 2)
        self.distance_view.setHorizontalHeaderLabels(("距离", "命中百分比"))
        self.distance_view.verticalHeader().setVisible(False)
        self.distance_view.horizontalHeader().setSectionResizeMode(
            1, QHeaderView.ResizeMode.Stretch
        )
        self.distance_view.setColumnWidth(0, 52)
        self.distance_view.setAlternatingRowColors(True)
        self.distance_view.itemChanged.connect(self._distance_view_changed)
        distance_layout.addWidget(self.distance_view)
        tables.addWidget(distance_group, 10)
        root.addLayout(tables, 1)

        footer = QHBoxLayout()
        self.pending_state = QLabel("当前ROM没有已验证的全局表。")
        self.pending_state.setObjectName("pendingBanner")
        self.apply_button = QPushButton("应用当前表格修改")
        self.apply_button.clicked.connect(self.apply_changes)
        self.reset_button = QPushButton("还原两张表")
        self.reset_button.clicked.connect(self.reset_tables)
        footer.addStretch()
        footer.addWidget(self.apply_button)
        footer.addWidget(self.reset_button)
        root.addLayout(footer)
        root.addWidget(self.pending_state)
        self.pending_state.hide()

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
            self.distance_view.setEditTriggers(
                QAbstractItemView.EditTrigger.AllEditTriggers
                if supported
                else QAbstractItemView.EditTrigger.NoEditTriggers
            )
            self.apply_button.setEnabled(False)
            self.reset_button.setEnabled(supported)
            self.level_cap_value.setText("当前等级上限：—")
            self.level_cap_button.setEnabled(supported)
            self.level_cap_button.setToolTip("当前ROM的等级上限布局尚未验证。")
            if not supported:
                self.experience_table.clearContents()
                self.distance_table.clearContents()
                self.pending_state.setText("当前ROM没有已验证的全局表。")
                self.pending_state.show()
                return
            experience = self.project.get_experience_totals()
            corrections = self.project.get_distance_hit_corrections()
            try:
                level_cap = self.project.get_verified_level_cap()
            except ValueError as error:
                self.level_cap_value.setText("当前等级上限：未验证")
                self.level_cap_button.setToolTip(
                    f"{error} 等级上限写入已禁用。"
                )
            else:
                self.level_cap_value.setText(f"当前等级上限：{level_cap}")
                self.level_cap_button.setToolTip(self.VERIFIED_LEVEL_CAP_TOOLTIP)
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
            self._refresh_distance_view()
        finally:
            self._loading = False
        self._update_pending_state()

    def _refresh_distance_view(self, *_args) -> None:
        method = int(self.distance_method.currentData() or 0)
        previous = self.distance_view.blockSignals(True)
        try:
            for distance in range(16):
                label = QTableWidgetItem(str(distance + 1))
                label.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                label.setFlags(label.flags() & ~Qt.ItemFlag.ItemIsEditable)
                source = self.distance_table.item(method, distance)
                value = "" if source is None else source.text()
                self.distance_view.setItem(distance, 0, label)
                self.distance_view.setItem(distance, 1, self._editable_item(int(value or 0)))
        finally:
            self.distance_view.blockSignals(previous)

    def _distance_view_changed(self, item: QTableWidgetItem) -> None:
        if self._loading or item.column() != 1:
            return
        method = int(self.distance_method.currentData() or 0)
        target = self.distance_table.item(method, item.row())
        if target is not None and target.text() != item.text():
            target.setText(item.text())
        self._update_pending_state()

    def _show_level_cap_boundary(self) -> None:
        if not self._is_supported:
            return
        try:
            level_cap = self.project.get_verified_level_cap()
        except ValueError as error:
            QMessageBox.warning(self, "等级上限未验证", str(error))
            return
        QMessageBox.information(
            self,
            "等级上限容量",
            f"当前 ROM 已使用完整的 {level_cap} 级经验表和成长记录容量。\n\n"
            "超过 99 级需要同时扩展经验表、成长记录并修改运行时代码；"
            "旧版 60→61 样本与当前 ROM 布局不兼容，因此本次不会改写 ROM。",
        )

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
        for row in range(1, len(experience)):
            if experience[row] < experience[row - 1]:
                raise ValueError(
                    f"等级{row + 1}累计经验不能小于等级{row}累计经验。"
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
            self.pending_state.show()
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
            self.pending_state.show()
        elif pending:
            self.pending_state.setText("● 有尚未暂存的经验/命中补正改动")
            self.pending_state.show()
        else:
            self.pending_state.setText("✓ 两张表与当前工程一致")
            self.pending_state.hide()

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
        self._description_page: LegacyTextPage | None = None
        root = QVBoxLayout(self)
        self.item_table = QTableWidget(self.ITEM_COUNT, 3)
        self.item_table.setHorizontalHeaderLabels(("编号", "道具名称", "显示价格"))
        self.item_table.verticalHeader().setVisible(False)
        self.item_table.horizontalHeader().setSectionResizeMode(
            1, QHeaderView.ResizeMode.Stretch
        )
        self.item_table.setColumnWidth(0, 78)
        self.item_table.setColumnWidth(2, 150)
        self.item_table.setAlternatingRowColors(True)
        self.item_table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.item_table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.item_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.item_table.itemChanged.connect(self._table_item_changed)
        self.item_table.currentCellChanged.connect(self._selected_item_changed)
        root.addWidget(self.item_table, 1)

        editors = QHBoxLayout()
        name_column = QVBoxLayout()
        name_column.addWidget(QLabel("名称修改："))
        self.name_edit = QLineEdit()
        self.name_edit.setObjectName("legacyItemNameEdit")
        name_column.addWidget(self.name_edit)
        price_column = QVBoxLayout()
        price_column.addWidget(QLabel("价格修改："))
        self.price_edit = QLineEdit()
        self.price_edit.setObjectName("legacyItemPriceEdit")
        price_column.addWidget(self.price_edit)
        self.name_edit.textChanged.connect(self._selected_name_changed)
        self.price_edit.textChanged.connect(self._selected_price_changed)
        editors.addLayout(name_column, 2)
        editors.addLayout(price_column, 1)
        root.addLayout(editors)

        self.description_group = QGroupBox("道具说明：")
        self.description_layout = QVBoxLayout(self.description_group)
        root.addWidget(self.description_group)

        footer = QHBoxLayout()
        self.pending_state = QLabel("当前ROM没有已验证的道具表。")
        self.pending_state.setObjectName("pendingBanner")
        self.apply_button = QPushButton("应用当前道具修改")
        self.apply_button.clicked.connect(self.apply_changes)
        self.reset_button = QPushButton("还原名称与价格")
        self.reset_button.clicked.connect(self.reset_items)
        footer.addStretch()
        footer.addWidget(self.apply_button)
        footer.addWidget(self.reset_button)
        root.addLayout(footer)
        root.addWidget(self.pending_state)
        self.pending_state.hide()

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
                QAbstractItemView.EditTrigger.NoEditTriggers
            )
            self.name_edit.setEnabled(supported)
            self.price_edit.setEnabled(supported)
            self.apply_button.setEnabled(False)
            self.reset_button.setEnabled(supported)
            if not supported:
                self._loaded_name_records = ()
                self._loaded_name_texts = ()
                self.item_table.clearContents()
                self.pending_state.setText("当前ROM没有已验证的道具名称/价格表。")
                self.pending_state.show()
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
        current_row = self.item_table.currentRow()
        self.item_table.setCurrentCell(
            current_row if 0 <= current_row < self.ITEM_COUNT else 0,
            0,
        )
        self._selected_item_changed(self.item_table.currentRow(), 0, -1, -1)
        self._update_pending_state()

    def bind_description_page(self, page: LegacyTextPage) -> None:
        self._description_page = page
        page.set_embedded_single_record_mode()
        self.description_layout.addWidget(page)
        self._selected_item_changed(self.item_table.currentRow(), 0, -1, -1)

    def _selected_item_changed(
        self,
        current_row: int,
        _current_column: int,
        _previous_row: int,
        _previous_column: int,
    ) -> None:
        if current_row < 0:
            self.name_edit.clear()
            self.price_edit.clear()
            return
        self._loading = True
        try:
            name = self.item_table.item(current_row, 1)
            price = self.item_table.item(current_row, 2)
            self.name_edit.setText("" if name is None else name.text())
            self.price_edit.setText("" if price is None else price.text())
        finally:
            self._loading = False
        if (
            self._description_page is not None
            and self._description_page.record_list.count() > current_row
        ):
            self._description_page.record_list.setCurrentRow(current_row)

    def _table_item_changed(self, item: QTableWidgetItem) -> None:
        if not self._loading and item.row() == self.item_table.currentRow():
            self._loading = True
            try:
                if item.column() == 1:
                    self.name_edit.setText(item.text())
                elif item.column() == 2:
                    self.price_edit.setText(item.text())
            finally:
                self._loading = False
        self._update_pending_state()

    def _selected_name_changed(self, text: str) -> None:
        if self._loading:
            return
        item = self.item_table.item(self.item_table.currentRow(), 1)
        if item is not None and item.text() != text:
            item.setText(text)

    def _selected_price_changed(self, text: str) -> None:
        if self._loading:
            return
        item = self.item_table.item(self.item_table.currentRow(), 2)
        if item is not None and item.text() != text:
            item.setText(text)

    def _draft_values(self) -> tuple[tuple[bytes, ...], tuple[int, ...]]:
        prospective_text = "".join(
            self.item_table.item(row, 1).text()
            for row in range(self.ITEM_COUNT)
            if self.item_table.item(row, 1) is not None
        )
        text_table, _allocated = self.project.prospective_font_text_table(
            prospective_text, channel="item", validate_renderer=True
        )
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
                    raw_name = text_table.encode_preserving_tokens(
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
            self.pending_state.show()
            self.apply_button.setEnabled(False)
            return
        error = self.pending_draft_error
        pending = self.has_pending_draft
        self.apply_button.setEnabled(pending and error is None)
        if error is not None:
            self.pending_state.setText(f"● {error}")
            self.pending_state.show()
        elif pending:
            self.pending_state.setText("● 有尚未暂存的道具名称/价格改动")
            self.pending_state.show()
        else:
            self.pending_state.setText("✓ 道具名称与价格和当前工程一致")
            self.pending_state.hide()

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
            all_names = "".join(
                self.item_table.item(row, 1).text()
                for row in range(self.ITEM_COUNT)
                if self.item_table.item(row, 1) is not None
            )
            with self.project.transaction("道具名称与价格"):
                self.project.ensure_font_characters(all_names, channel="item")
                self._text_table = self.project.dc_text_table()
                names, prices = self._draft_values()
                current_names = self.project.get_item_name_records()
                current_prices = self.project.get_item_prices()
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
        *,
        lazy: bool = False,
    ) -> None:
        super().__init__(project, title="数据库", parent=parent)
        # Keep the legacy editor's compact footprint at 125% scaling instead
        # of opening a 1550 px-wide modern canvas that only spreads the same
        # controls farther apart.  The added module strip uses reclaimed space.
        # The reference window is about 700 logical pixels tall (875 physical
        # pixels at 125%).  The former 670 px height clipped the lower battle-
        # dialogue rows and made the character page needlessly scroll.
        self.resize(1050, 700)
        self.setMinimumSize(860, 600)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(5, 5, 5, 5)
        layout.setSpacing(4)
        self.tabs = QTabWidget()
        self.tabs.setObjectName("legacyDatabaseTabs")

        self._lazy_database = lazy
        self._database_pages_by_tab: dict[int, tuple[ProjectPage, ...]] = {}
        self._database_hosts_by_tab: dict[int, QWidget] = {}
        self._database_memory_panels: dict[int, DatabaseModuleMemoryPanel] = {}
        self._lazy_tab_placeholders: dict[int, QWidget] = {}
        self.unit_page = self.register_page(LegacyUnitDatabasePage())
        assert isinstance(self.unit_page, LegacyUnitDatabasePage)
        self.unit_page.weapon_requested.connect(self._select_weapon)
        self._database_pages_by_tab[0] = (self.unit_page,)
        self.tabs.addTab(
            self._wrap_database_page(0, self.unit_page, (self.unit_page,)),
            self.TAB_LABELS[0],
        )

        if lazy:
            # Data refresh was already deferred before, but constructing every
            # hidden page still created thousands of child controls and made
            # Qt polish the complete tree before the first frame.  Keep real
            # placeholders in the tab widget and build a tab only when it is
            # selected (or a compatibility caller accesses its public page
            # attribute).
            for index, label in enumerate(self.TAB_LABELS[1:], start=1):
                placeholder = QWidget()
                placeholder.setObjectName(f"databaseTabPlaceholder{index}")
                self._lazy_tab_placeholders[index] = placeholder
                self.tabs.addTab(placeholder, label)
        else:
            self._build_database_tab(1)
            self._build_database_tab(2)
            self._build_database_tab(3)
            self._build_database_tab(4)
            self._build_database_tab(5)
        layout.addWidget(self.tabs, 1)

        footer = QHBoxLayout()
        footer.setSpacing(4)
        self.database_search = QLineEdit()
        self.database_search.setPlaceholderText("查找名称或ID")
        self.database_search.setMinimumWidth(220)
        self.database_search.setMaximumWidth(360)
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
        self.tabs.currentChanged.connect(self._database_tab_changed)
        self.tabs.currentChanged.connect(
            lambda _index: self._sync_active_search(self.database_search.text())
        )
        self.tabs.currentChanged.connect(self._refresh_database_context)
        for control in (
            self.database_search,
            self.find_next_button,
            self.find_previous_button,
            self.ok_button,
            self.cancel_button,
        ):
            control.setFixedHeight(26)
        self.find_next_button.setFixedWidth(88)
        self.find_previous_button.setFixedWidth(88)
        self.ok_button.setFixedWidth(58)
        self.cancel_button.setFixedWidth(58)
        footer.addWidget(self.database_search)
        footer.addWidget(self.find_next_button)
        footer.addWidget(self.find_previous_button)
        footer.addStretch()
        footer.addWidget(self.ok_button)
        footer.addWidget(self.cancel_button)
        layout.addLayout(footer)

    def __getattr__(self, name: str):
        lazy_tabs = {
            "character_page": 1,
            "weapon_page": 2,
            "battle_dialogue_page": 3,
            "other_page_1": 4,
            "system_text_page": 4,
            "growth_page": 4,
            "other_page_2": 5,
            "item_description_page": 5,
            "shop_page": 5,
        }
        index = lazy_tabs.get(name)
        if index is not None and self.__dict__.get("_lazy_database", False):
            self._build_database_tab(index)
            return object.__getattribute__(self, name)
        raise AttributeError(name)

    def _build_database_tab(self, index: int) -> tuple[ProjectPage, ...]:
        existing = self._database_pages_by_tab.get(index)
        if existing is not None:
            return existing

        deferred = self._lazy_database
        if index == 1:
            self.character_page = self.register_page(
                ReadableCharacterPage(), defer_refresh=deferred
            )
            assert isinstance(self.character_page, CharacterPage)
            self._prepare_record_page(self.character_page, "暂存当前人物")
            self._install_reference_record_menu(
                self.character_page,
                copy_label="复制人物",
                paste_label="粘贴人物",
                export_label="导出人物",
            )
            pages = (self.character_page,)
            visible_page = self.character_page
        elif index == 2:
            self.weapon_page = self.register_page(
                ReadableWeaponPage(), defer_refresh=deferred
            )
            assert isinstance(self.weapon_page, WeaponPage)
            self.weapon_page.unit_requested.connect(self._select_unit)
            self._prepare_record_page(self.weapon_page, "暂存当前武器")
            self._install_reference_record_menu(
                self.weapon_page,
                copy_label="复制武器",
                paste_label="粘贴武器",
            )
            pages = (self.weapon_page,)
            visible_page = self.weapon_page
        elif index == 3:
            self.battle_dialogue_page = self.register_page(
                LegacyTextPage(), defer_refresh=deferred
            )
            pages = (self.battle_dialogue_page,)
            visible_page = self.battle_dialogue_page
        elif index == 4:
            self.other_page_1 = self.register_page(
                LegacyGlobalTablesPage(), defer_refresh=deferred
            )
            self.system_text_page = self.register_page(
                LegacyTextPage(("system",)), defer_refresh=deferred
            )
            self.growth_page = self.register_page(
                LegacyGrowthPage(), defer_refresh=deferred
            )
            self._compose_other1(
                self.other_page_1,
                self.system_text_page,
                self.growth_page,
            )
            pages = (self.other_page_1, self.system_text_page, self.growth_page)
            visible_page = self.other_page_1
        elif index == 5:
            self.other_page_2 = self.register_page(
                LegacyItemTablePage(), defer_refresh=deferred
            )
            self.item_description_page = self.register_page(
                LegacyTextPage(("item_description",)), defer_refresh=deferred
            )
            self.shop_page = self.register_page(
                LegacyShopPage(), defer_refresh=deferred
            )
            self.other_page_2.bind_description_page(self.item_description_page)
            self._compose_other2(self.other_page_2, self.shop_page)
            pages = (
                self.other_page_2,
                self.item_description_page,
                self.shop_page,
            )
            visible_page = self.other_page_2
        else:
            return ()

        self._database_pages_by_tab[index] = pages
        visible_host = self._wrap_database_page(index, visible_page, pages)
        placeholder = self._lazy_tab_placeholders.pop(index, None)
        if placeholder is not None:
            was_current = self.tabs.currentIndex() == index
            self.tabs.blockSignals(True)
            self.tabs.removeTab(index)
            self.tabs.insertTab(index, visible_host, self.TAB_LABELS[index])
            if was_current:
                self.tabs.setCurrentIndex(index)
            self.tabs.blockSignals(False)
            placeholder.deleteLater()
        elif self.tabs.indexOf(visible_host) < 0:
            self.tabs.addTab(visible_host, self.TAB_LABELS[index])
        return pages

    def _wrap_database_page(
        self,
        index: int,
        visible_page: QWidget,
        pages: tuple[ProjectPage, ...],
    ) -> QWidget:
        existing = self._database_hosts_by_tab.get(index)
        if existing is not None:
            return existing
        contents = QWidget()
        contents.setObjectName(f"databaseModuleContents{index}")
        original_layout = visible_page.layout()
        if original_layout is not None:
            contents.setLayout(original_layout)
        layout = QVBoxLayout(visible_page)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)
        layout.addWidget(contents, 1)
        panel = DatabaseModuleMemoryPanel(
            self.project, self.TAB_LABELS[index], visible_page
        )
        for page in pages:
            page.project_changed.connect(panel.refresh)
        layout.addWidget(panel)
        self._database_hosts_by_tab[index] = visible_page
        self._database_memory_panels[index] = panel
        return visible_page

    def _database_tab_changed(self, index: int) -> None:
        for page in self._build_database_tab(index):
            self._ensure_page_loaded(page)

    def _refresh_pages(self) -> None:
        """Refresh both editor pages and module capacity strips after rollback."""

        super()._refresh_pages()
        for panel in self._database_memory_panels.values():
            panel.refresh()

    def set_project(self, project: RomProject | None) -> None:
        super().set_project(project)
        if hasattr(self, "tabs"):
            if project is not None:
                for panel in self._database_memory_panels.values():
                    panel.project = project
                    panel.refresh()
            self._database_tab_changed(self.tabs.currentIndex())

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
        if isinstance(page, ReadableCharacterPage):
            capacity_message = (
                "按旧修改器规则新增一个人物 ID，并同步重排属性、双名称、头像、"
                "战斗音乐与台词；任一共享区容量不足时整笔取消。"
            )
            add_button.setToolTip(capacity_message)
        elif isinstance(page, ReadableWeaponPage):
            capacity_message = (
                "当前已列出完整的 8 位武器 ID $01—$FF；没有可新增的 ID，"
                "参考版在此容量下点击添加也不产生记录。"
            )
            add_button.setToolTip(capacity_message + " 点击查看容量说明。")
        else:
            capacity_message = "当前记录表没有可安全新增的槽位。"
            add_button.setToolTip(capacity_message)
        if isinstance(page, ReadableCharacterPage):
            add_button.clicked.connect(page.add_character_record)
        else:
            add_button.clicked.connect(
                lambda _checked=False, host=page, message=capacity_message: QMessageBox.information(
                    host,
                    "记录容量已满",
                    message + "\n\n本次操作不会修改 ROM。",
                )
            )
        page.add_record_button = add_button
        selection_layout.addWidget(add_button)

    @staticmethod
    def _build_reference_record_menu(
        page: SearchableRecordPage,
        *,
        copy_label: str,
        paste_label: str,
        export_label: str | None = None,
    ) -> tuple[QMenu, dict[str, Any]]:
        """Build the exact record-list menu discovered in the reference app."""

        menu = QMenu(page.records)
        actions = {
            "copy": menu.addAction(copy_label),
            "paste": menu.addAction(paste_label),
        }
        actions["paste"].setEnabled(
            page._copied_record_id is not None
            and page._copied_record_id != page.current_id
        )
        if export_label is not None:
            actions["export"] = menu.addAction(export_label)
        return menu, actions

    @classmethod
    def _install_reference_record_menu(
        cls,
        page: SearchableRecordPage,
        *,
        copy_label: str,
        paste_label: str,
        export_label: str | None = None,
    ) -> None:
        try:
            page.records.customContextMenuRequested.disconnect(
                page._show_record_context_menu
            )
        except (RuntimeError, TypeError):
            pass

        def show(position) -> None:
            item = page.records.itemAt(position)
            if item is not None:
                page.records.setCurrentItem(item)
            if page.current_id is None:
                return
            menu, actions = cls._build_reference_record_menu(
                page,
                copy_label=copy_label,
                paste_label=paste_label,
                export_label=export_label,
            )
            selected = menu.exec(page.records.viewport().mapToGlobal(position))
            if selected is actions["copy"]:
                page.copy_selected_record()
            elif selected is actions["paste"]:
                page.paste_copied_record()
            elif selected is actions.get("export"):
                page.export_selected_record()

        page.records.customContextMenuRequested.connect(show)
        labels = [copy_label, paste_label]
        if export_label:
            labels.append(export_label)
        page.records.setToolTip("右键：" + "、".join(labels) + "。")

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

    @staticmethod
    def _compose_other1(
        page: LegacyGlobalTablesPage,
        system_page: LegacyTextPage,
        growth_page: LegacyGrowthPage,
    ) -> None:
        """Match the reference four-column Other 1 page."""

        global_contents = QWidget()
        global_contents.setLayout(page.layout())

        system_contents = QWidget()
        system_contents.setLayout(system_page.layout())
        growth_contents = QWidget()
        growth_contents.setLayout(growth_page.layout())

        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.setObjectName("legacyOther1Panels")
        splitter.setChildrenCollapsible(False)
        splitter.addWidget(system_contents)
        splitter.addWidget(growth_contents)
        splitter.addWidget(global_contents)
        # The generic text editor is horizontal on standalone pages.  In the
        # legacy Other-1 column it is stacked: record list above, selected text
        # below.  This restores the old four-column proportions and releases
        # enough width for the distance table.
        system_page.splitter.setOrientation(Qt.Orientation.Vertical)
        system_page.splitter.setSizes((370, 170))
        system_page.search_edit.hide()
        system_page.system_note.hide()
        embedded_note = QLabel(system_page.system_note.text())
        embedded_note.setObjectName("legacySystemTextNote")
        embedded_note.setWordWrap(True)
        embedded_note.setStyleSheet("color:#b00020;")
        system_left_layout = system_page.splitter.widget(0).layout()
        if isinstance(system_left_layout, QVBoxLayout):
            system_left_layout.insertWidget(2, embedded_note)
        system_page.embedded_system_note = embedded_note
        splitter.setStretchFactor(0, 36)
        splitter.setStretchFactor(1, 20)
        splitter.setStretchFactor(2, 44)
        splitter.setSizes((370, 210, 450))

        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(splitter)
        page.other1_splitter = splitter
        page.system_contents = system_contents
        page.growth_contents = growth_contents
        page.global_contents = global_contents

    @staticmethod
    def _compose_other2(page: LegacyItemTablePage, shop_page: LegacyShopPage) -> None:
        """Restore the reference M10 two-column, three-panel presentation."""

        item_contents = QWidget()
        item_contents.setLayout(page.layout())

        item_group = QGroupBox("道具")
        item_layout = QVBoxLayout(item_group)
        item_layout.setContentsMargins(6, 6, 6, 6)
        item_layout.addWidget(item_contents)

        shop_group = QGroupBox("商店")
        shop_layout = QVBoxLayout(shop_group)
        shop_layout.setContentsMargins(6, 6, 6, 6)
        shop_layout.addWidget(shop_page)

        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.setObjectName("legacyOther2Panels")
        splitter.addWidget(item_group)
        splitter.addWidget(shop_group)
        splitter.setStretchFactor(0, 1)
        splitter.setStretchFactor(1, 1)
        splitter.setSizes((590, 610))

        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(splitter)
        page.other2_splitter = splitter
        page.item_group = item_group
        page.shop_group = shop_group

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

    def _select_character(self, character_id: int) -> None:
        self.database_search.clear()
        self.tabs.setCurrentIndex(1)
        for row in range(self.character_page.records.count()):
            item = self.character_page.records.item(row)
            if int(item.data(Qt.ItemDataRole.UserRole)) == character_id:
                self.character_page.records.setCurrentRow(row)
                selected = self.character_page.records.currentItem()
                if (
                    selected is not None
                    and int(selected.data(Qt.ItemDataRole.UserRole)) == character_id
                ):
                    self.character_page.records.scrollToItem(selected)
                break

    def _refresh_database_context(self, index: int) -> None:
        panel = self._database_memory_panels.get(index)
        if panel is not None:
            panel.refresh()
        if index == 2:
            self.weapon_page.refresh_usage()

    def _active_search_page(self) -> ProjectPage | None:
        index = self.tabs.currentIndex()
        current = self.tabs.currentWidget()
        pages = self._database_pages_by_tab.get(index)
        if pages:
            current = pages[0]
        # Do not materialize the hidden "其他修改1" tab merely because the
        # shared search box asks which visible page owns search.
        other_page_1 = self.__dict__.get("other_page_1")
        if other_page_1 is not None and current is other_page_1:
            return self.system_text_page
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


class ChapterTitleDialog(QDialog):
    """Safe shared-pool editor for one verified title tile script."""

    def __init__(
        self,
        project: RomProject,
        scenario_id: int,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.project = project
        self.scenario_id = scenario_id
        self.record = project.get_chapter_title(scenario_id)
        self._loading_segment = False
        self._segment_initialized = False
        self.setWindowTitle("标题拼图")
        self.resize(700, 470)
        self.setMinimumSize(660, 440)

        layout = QVBoxLayout(self)
        controls = QGridLayout()
        self.segment_selector = QComboBox()
        self.segment_x = QSpinBox()
        self.segment_y = QSpinBox()
        self.segment_width = QSpinBox()
        for spin in (self.segment_x, self.segment_y, self.segment_width):
            spin.setRange(0, 255)
            spin.setMinimumWidth(68)
        self.segment_width.setRange(1, 127)
        self.segment_tiles = QLineEdit()
        self.segment_tiles.setVisible(False)
        self.segment_apply = QPushButton("应用当前段")
        self.segment_apply.setVisible(False)
        self.show_tile_numbers = QCheckBox("显示图块编号")
        self.refresh_button = QPushButton("刷新")
        self.code_button = QPushButton("查看拼图代码")
        # The reference window labels the stored Y byte as title X and the
        # stored X byte as title Y; preserve that visible convention.
        controls.addWidget(QLabel("标题X坐标："), 0, 0)
        controls.addWidget(self.segment_y, 0, 1)
        controls.addWidget(QLabel("标题Y坐标："), 0, 2)
        controls.addWidget(self.segment_x, 0, 3)
        controls.addWidget(QLabel("标题宽度："), 0, 4)
        controls.addWidget(self.segment_width, 0, 5)
        controls.addWidget(self.refresh_button, 0, 6)
        controls.addWidget(self.code_button, 0, 7)
        layout.addLayout(controls)

        layout.addWidget(QLabel("图块："))
        self.title_preview = QLabel()
        self.title_preview.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.title_preview.setMinimumHeight(72)
        self.title_preview.setMaximumHeight(86)
        self.title_preview.setStyleSheet("background: black; border: 1px solid #202020;")
        layout.addWidget(self.title_preview)

        self.segment_table = QTableWidget(0, 5)
        self.segment_table.hide()
        self.code_edit = QPlainTextEdit(self.record.raw.hex(" ").upper())
        self.code_edit.setObjectName("chapterTitleCode")
        self.code_edit.hide()
        self.code_edit.textChanged.connect(self._refresh_preview)

        bank_layout = QGridLayout()
        self.bank_spins: list[ChrBankComboBox] = []
        self.bank_previews: list[QLabel] = []
        bank_limit = max(0, project.chr_tile_count // 64 - 1)
        for index, value in enumerate(self.record.chr_banks):
            selector = ChrBankComboBox()
            selector.set_project(project)
            selector.setRange(0, bank_limit)
            selector.setValue(value)
            selector.valueChanged.connect(self._refresh_preview)
            preview = QLabel()
            preview.setAlignment(Qt.AlignmentFlag.AlignCenter)
            preview.setMinimumSize(150, 150)
            preview.setSizePolicy(
                QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding
            )
            preview.setStyleSheet("background: black; border: 1px solid #404040;")
            bank_layout.addWidget(QLabel(f"图库地址{index + 1}："), 0, index)
            bank_layout.addWidget(selector, 1, index)
            bank_layout.addWidget(preview, 2, index)
            self.bank_spins.append(selector)
            self.bank_previews.append(preview)
        layout.addLayout(bank_layout, 1)

        footer = QHBoxLayout()
        self.selected_tile_label = QLabel("当前选中图块：00")
        self.selected_tile_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        footer.addWidget(self.show_tile_numbers)
        footer.addStretch(1)
        footer.addWidget(self.selected_tile_label)
        footer.addStretch(1)
        layout.addLayout(footer)

        self.segment_table.setHorizontalHeaderLabels(
            ("段", "X", "Y", "宽度", "图块数")
        )
        self.segment_table.horizontalHeader().setSectionResizeMode(
            QHeaderView.ResizeMode.Stretch
        )
        self.segment_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.status = QLabel()
        self.status.setObjectName("hintText")
        self.status.setWordWrap(True)
        self.status.hide()

        buttons = QHBoxLayout()
        self.ok_button = QPushButton("确定")
        self.cancel_button = QPushButton("取消")
        self.refresh_button.clicked.connect(self._apply_segment_fields)
        self.code_button.clicked.connect(self._open_code_editor)
        self.ok_button.clicked.connect(self.accept)
        self.cancel_button.clicked.connect(self.reject)
        buttons.addStretch(1)
        buttons.addWidget(self.ok_button)
        buttons.addWidget(self.cancel_button)
        layout.addLayout(buttons)
        self.segment_selector.currentIndexChanged.connect(self._load_segment)
        self.segment_apply.clicked.connect(self._apply_segment_fields)
        self.show_tile_numbers.toggled.connect(self._refresh_preview)
        self._refresh_preview()

    def _banks(self) -> tuple[int, int, int]:
        values = tuple(spin.value() for spin in self.bank_spins)
        return values  # type: ignore[return-value]

    def _raw(self) -> bytes:
        compact = "".join(self.code_edit.toPlainText().split())
        if not compact:
            raise ValueError("标题拼图代码不能为空。")
        try:
            return bytes.fromhex(compact)
        except ValueError as error:
            raise ValueError("标题拼图代码必须是成对的十六进制字节。") from error

    def _refresh_preview(self) -> None:
        try:
            raw = self._raw()
            codec = self.project.chapter_title_codec
            if codec is None:
                raise ValueError("当前 ROM 没有已验证的关卡标题表。")
            segments = ChapterTitleCodec.parse_segments(raw)
            codec.replacement_patches(
                self.project.working,
                self.scenario_id,
                self._banks(),
                raw,
            )
            for preview, bank in zip(
                self.bank_previews,
                self._banks(),
                strict=True,
            ):
                image = render_chr_banks(
                    self.project,
                    (bank,),
                    CHAPTER_TITLE_PALETTE_NES[1:],
                )
                pixmap = QPixmap.fromImage(image).scaled(
                    128,
                    128,
                    Qt.AspectRatioMode.KeepAspectRatio,
                    Qt.TransformationMode.FastTransformation,
                )
                if self.show_tile_numbers.isChecked():
                    painter = QPainter(pixmap)
                    painter.setPen(QPen(QColor("#ffd500")))
                    scale = max(1, pixmap.width() // 64)
                    for tile in range(64):
                        painter.drawText(
                            (tile % 8) * 8 * scale + 1,
                            (tile // 8) * 8 * scale + min(11, 8 * scale - 1),
                            f"{tile:02X}",
                        )
                    painter.end()
                preview.setPixmap(pixmap)
            self.title_preview.setPixmap(
                render_title_segment(
                    self.project,
                    self._banks(),
                    segments[-1],
                )
            )
            self.segment_table.setRowCount(len(segments))
            for row, segment in enumerate(segments):
                for column, value in enumerate(
                    (row + 1, segment.x, segment.y, segment.width, len(segment.tiles))
                ):
                    text = str(value) if column in (0, 3, 4) else f"${value:02X}"
                    self.segment_table.setItem(row, column, QTableWidgetItem(text))
            selected = self.segment_selector.currentIndex()
            if not self._segment_initialized:
                selected = len(segments) - 1
                self._segment_initialized = True
            self.segment_selector.blockSignals(True)
            self.segment_selector.clear()
            for index, segment in enumerate(segments):
                self.segment_selector.addItem(
                    f"段 {index + 1} · X=${segment.x:02X} Y=${segment.y:02X} "
                    f"宽 {segment.width}",
                    index,
                )
            self.segment_selector.setCurrentIndex(
                min(max(selected, 0), len(segments) - 1)
            )
            self.segment_selector.blockSignals(False)
            self._load_segment()
            self.status.setStyleSheet("color: #18794e;")
            self.status.setText(
                f"结构有效 · 当前记录 {len(raw)} 字节 · "
                f"{len(segments)} 段 · 保存时自动重排 32 项标题指针"
            )
            self.ok_button.setEnabled(True)
        except (RomFormatError, ValueError) as error:
            self.title_preview.clear()
            self.segment_table.setRowCount(0)
            self.status.setStyleSheet("color: #b42318;")
            self.status.setText(str(error))
            self.ok_button.setEnabled(False)

    def _open_code_editor(self) -> None:
        """Keep raw code available without occupying the reference layout."""

        dialog = QDialog(self)
        dialog.setWindowTitle("标题拼图代码")
        dialog.resize(620, 260)
        layout = QVBoxLayout(dialog)
        hint = QLabel(
            "高级功能：每段格式为 FE X Y 宽度 图块…，最后以 FF 结束。"
            "普通修改只需使用主窗口中的坐标、宽度和图库。"
        )
        hint.setWordWrap(True)
        layout.addWidget(hint)
        editor = QPlainTextEdit(self.code_edit.toPlainText())
        editor.setObjectName("chapterTitleCodePopup")
        layout.addWidget(editor, 1)
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok
            | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.button(QDialogButtonBox.StandardButton.Ok).setText("确定")
        buttons.button(QDialogButtonBox.StandardButton.Cancel).setText("取消")
        buttons.accepted.connect(dialog.accept)
        buttons.rejected.connect(dialog.reject)
        layout.addWidget(buttons)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            self.code_edit.setPlainText(editor.toPlainText())

    def _load_segment(self, *_args) -> None:
        try:
            segments = ChapterTitleCodec.parse_segments(self._raw())
            index = self.segment_selector.currentData()
            index = 0 if index is None else int(index)
            segment = segments[index]
        except (IndexError, RomFormatError, ValueError):
            return
        self._loading_segment = True
        try:
            self.segment_x.setValue(segment.x)
            self.segment_y.setValue(segment.y)
            self.segment_width.setValue(segment.width)
            self.segment_tiles.setText(segment.tiles.hex(" ").upper())
        finally:
            self._loading_segment = False

    def _apply_segment_fields(self) -> None:
        if self._loading_segment:
            return
        try:
            segments = list(ChapterTitleCodec.parse_segments(self._raw()))
            index = self.segment_selector.currentData()
            index = 0 if index is None else int(index)
            compact = " ".join(self.segment_tiles.text().split())
            tiles = bytes.fromhex(compact)
            width = self.segment_width.value()
            if len(tiles) != width * 2:
                raise ValueError(
                    f"宽度 {width} 需要 {width * 2} 个图块，当前为 {len(tiles)} 个。"
                )
            replacement = bytearray()
            for segment_index, segment in enumerate(segments):
                if segment_index == index:
                    x = self.segment_x.value()
                    y = self.segment_y.value()
                    segment_width = width
                    segment_tiles = tiles
                else:
                    x = segment.x
                    y = segment.y
                    segment_width = segment.width
                    segment_tiles = segment.tiles
                replacement.extend((0xFE, x, y, segment_width))
                replacement.extend(segment_tiles)
            replacement.append(0xFF)
            codec = self.project.chapter_title_codec
            if codec is None:
                raise ValueError("当前 ROM 没有已验证的关卡标题表。")
            codec.replacement_patches(
                self.project.working,
                self.scenario_id,
                self._banks(),
                bytes(replacement),
            )
        except (IndexError, RomFormatError, ValueError) as error:
            QMessageBox.warning(self, "无法应用标题段", str(error))
            return
        self.code_edit.setPlainText(bytes(replacement).hex(" ").upper())

    def accept(self) -> None:
        try:
            self.project.set_chapter_title(
                self.scenario_id,
                self._banks(),
                self._raw(),
            )
        except (RomFormatError, ValueError) as error:
            QMessageBox.warning(self, "无法保存标题拼图", str(error))
            return
        super().accept()


class ScenarioDialog(TransactionalProjectDialog):
    """Reference-shaped scenario window with right-click event editors."""

    TAB_LABELS = (
        "关卡设置",
        "行动事件",
        "劝降事件",
        "地图事件",
        "剧情对话",
        "胜利文字",
    )
    EVENT_TAB_LABELS = ("界面事件", "回合事件", "即时事件")
    SPACE_BUTTON_TEXT = (
        "检查剧情；界面事件和回合事件；即时事件；"
        "行动事件，劝降事件和地图事件剩余空间"
    )

    def __init__(
        self,
        project: RomProject | None,
        parent: QWidget | None = None,
        *,
        initial_scenario_id: int | None = None,
        lazy: bool = False,
    ) -> None:
        super().__init__(project, title="事件编辑", parent=parent)
        self._lazy_scenario = lazy
        inherited = getattr(getattr(parent, "map_page", None), "current_map_id", None)
        requested = initial_scenario_id if initial_scenario_id is not None else inherited
        self.initial_scenario_id = int(requested) if requested is not None else 0
        self.current_scenario_id: int | None = None
        self._victory_source_body = b""
        self._victory_source_text = ""
        self._victory_dirty = False
        self._overview_refresh_keys: dict[int, tuple[int, int | None]] = {}
        self.resize(1180, 780)
        self.setMinimumSize(900, 600)

        self.setup_event_pages = [
            self._register_hidden_page(LegacyScenarioEventsPage(phase))
            for phase in range(3)
        ]
        self.action_event_page = self.register_page(
            ActionEventPage(), defer_refresh=lazy
        )
        self.persuasion_page = self._register_hidden_page(
            PersuasionPage(), defer_refresh=lazy
        )
        self.map_event_page = self._register_hidden_page(
            _LegacyEventController(), defer_refresh=lazy
        )
        self.story_page = self._register_hidden_page(
            StoryPage(), defer_refresh=lazy
        )
        self.victory_page = self._register_hidden_page(
            StoryPage(), defer_refresh=lazy
        )

        assert isinstance(self.action_event_page, ActionEventPage)
        assert isinstance(self.persuasion_page, PersuasionPage)
        assert isinstance(self.map_event_page, EventPage)
        assert isinstance(self.story_page, StoryPage)
        assert isinstance(self.victory_page, StoryPage)

        self.chapter_context = self._build_chapter_context()
        setup = self._build_setup_page()
        action = self.action_event_page
        self.action_event_list = self.action_event_page.action_list
        self.action_event_list_code_button = self.action_event_page.apply_button
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
        self.space_button = QPushButton(self.SPACE_BUTTON_TEXT)
        self.space_button.setEnabled(project is not None)
        self.space_button.setToolTip(
            "显示八组剧情文本、三组章节事件池和 Bank $26 "
            "独立行动表的占用、容量和剩余字节。"
        )
        self.space_button.clicked.connect(self._show_space_report)
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

        self.tabs.currentChanged.connect(self._scenario_tab_changed)
        self.tabs.currentChanged.connect(self._move_chapter_context)
        self.chapter_list.currentItemChanged.connect(self._chapter_changed)
        self._configure_event_views()
        self._move_chapter_context(0)
        self._populate_chapters()

    @staticmethod
    def _script_pool_usage(
        codec: LegacyScenarioCodec,
        phases: tuple[int, ...],
    ) -> dict[int, int]:
        records = {
            (instruction.bank, instruction.file_offset): instruction
            for scenario_id in range(0x20)
            for phase in phases
            for instruction in codec.instructions(scenario_id, phase)
        }
        banks = sorted({bank for bank, _offset in records})
        return {
            bank: sum(
                len(instruction.raw)
                for (record_bank, _offset), instruction in records.items()
                if record_bank == bank
            )
            for bank in banks
        }

    def scenario_space_report_text(self) -> str:
        """Return the evidence-bounded capacity report shown by button 690."""

        if self.project is None:
            raise ValueError("请先载入兼容 ROM。")

        project = self.project
        story_codec = project.story_text_codec
        story_lines = []
        for group in project.story_text_groups:
            used = 0
            for _pointer, indices in story_codec.ids_by_pointer(
                group.selector
            ).items():
                record = story_codec.decode(
                    group.selector,
                    indices[0],
                    bytes(project.working),
                )
                used += len(record.raw)
            capacity = group.data_end - group.data_start
            location = (
                "扩展 Bank pair"
                if group.selector in story_codec.relocated_selectors
                else "原位数据池"
            )
            story_lines.append(
                f"剧情 ${group.selector:02X}（{location}）："
                f"{used} / {capacity} 字节，剩余 {capacity - used} 字节"
            )

        scenario_codec = LegacyScenarioCodec(bytes(project.working))
        setup_usage = self._script_pool_usage(scenario_codec, (0, 1))
        immediate_usage = self._script_pool_usage(scenario_codec, (2,))
        bank_capacity = 0x2000
        event_lines = []
        for bank, used in setup_usage.items():
            event_lines.append(
                f"界面事件和回合事件（Bank ${bank:02X}）："
                f"{used} / {bank_capacity} 字节，"
                f"剩余 {bank_capacity - used} 字节"
            )
        for bank, used in immediate_usage.items():
            event_lines.append(
                f"即时事件（Bank ${bank:02X}）：{used} / {bank_capacity} 字节，"
                f"剩余 {bank_capacity - used} 字节"
            )

        action_usage = project.action_event_usage()
        persuasion_slots = 0
        if project.persuasion_rule_codec is not None:
            persuasion_slots = project.persuasion_rule_codec.spec.editable_count
        event_lines.extend(
            (
                "独立行动事件（Bank $26）："
                f"{action_usage.used} / {action_usage.capacity} 字节，"
                f"剩余 {action_usage.free} 字节；256 项指针 / "
                f"{action_usage.physical_records} 个有效物理脚本",
                f"边界说明：劝降事件为 {persuasion_slots} 个已验证等长槽；"
                "地图事件为分 Bank 章节脚本的条件索引。",
            )
        )
        return "剧情文本\n" + "\n".join(story_lines) + "\n\n事件脚本\n" + "\n".join(event_lines)

    def _show_space_report(self) -> None:
        if not self._commit_pending_pages():
            return
        try:
            report = self.scenario_space_report_text()
        except (ValueError, RomFormatError) as error:
            QMessageBox.warning(self, "无法检查剩余空间", str(error))
            return
        QMessageBox.information(self, "提示", report)

    def _register_hidden_page(
        self, page: ProjectPage, *, defer_refresh: bool = False
    ) -> ProjectPage:
        registered = self.register_page(page, defer_refresh=defer_refresh)
        registered.setParent(self)
        registered.hide()
        registered.project_changed.connect(lambda _message: self._refresh_overviews())
        return registered

    def _scenario_tab_changed(self, tab_index: int) -> None:
        page_by_tab = {
            1: self.action_event_page,
            2: self.persuasion_page,
            3: self.map_event_page,
            4: self.story_page,
            5: self.victory_page,
        }
        page = page_by_tab.get(tab_index)
        if page is None:
            return
        was_loaded = page in self._loaded_pages
        self._ensure_page_loaded(page)
        # The initial chapter refresh records revision keys for all overview
        # tabs, including lazy pages whose hidden editor was not populated yet.
        # Do not let that cache key suppress the first real projection after a
        # lazy page is loaded.
        if not was_loaded:
            self._overview_refresh_keys.pop(tab_index, None)
        if page is self.map_event_page and self.current_scenario_id is not None:
            index = page.scenario_filter.findData(self.current_scenario_id)
            if index >= 0:
                page.scenario_filter.setCurrentIndex(index)
        revision = self.project.revision if self.project is not None else -1
        refresh_key = (revision, self.current_scenario_id)
        if self._overview_refresh_keys.get(tab_index) == refresh_key:
            return
        self._refresh_overviews()
        self._overview_refresh_keys[tab_index] = refresh_key

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
        self.chapter_title = QLineEdit()
        self.chapter_title.setReadOnly(True)
        settings_layout.addWidget(QLabel("初始胜利文字:"))
        self.initial_victory = QPlainTextEdit()
        self.initial_victory.setMaximumHeight(118)
        self.initial_victory.textChanged.connect(self._victory_text_changed)
        settings_layout.addWidget(self.initial_victory)
        self.initial_victory_status = QLabel("—")
        self.initial_victory_status.setObjectName("hintText")
        self.initial_victory_status.setWordWrap(True)
        settings_layout.addWidget(self.initial_victory_status)
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
            "编辑三个 CHR 图库和当前固定容量的 FE/FF 标题拼图脚本。"
        )
        self.title_code_button.clicked.connect(self._open_title_editor)
        title_layout.addWidget(self.title_preview, 1)
        title_layout.addWidget(self.title_code_button)
        page_layout.addWidget(title_art)

        event_group = QGroupBox("事件编辑")
        event_layout = QVBoxLayout(event_group)
        self.setup_event_tabs = QTabWidget()
        self.setup_event_tabs.setObjectName("legacyScenarioEventTabs")
        self.setup_event_lists: list[QListWidget] = []
        for label, controller in zip(self.EVENT_TAB_LABELS, self.setup_event_pages):
            panel, overview = self._setup_event_list_panel(controller)
            self.setup_event_lists.append(overview)
            self.setup_event_tabs.addTab(panel, label)
        event_layout.addWidget(self.setup_event_tabs)
        page_layout.addWidget(event_group, 1)
        return page

    def _setup_event_list_panel(
        self, controller: LegacyScenarioEventsPage
    ) -> tuple[QWidget, QListWidget]:
        """Expose the reference list; editing starts from its right-click menu."""

        host = QWidget()
        layout = QVBoxLayout(host)
        layout.setContentsMargins(3, 3, 3, 3)
        overview = QListWidget()
        overview.setAlternatingRowColors(True)
        overview.setUniformItemSizes(True)
        overview.setToolTip("鼠标右键事件指令，再选择“编辑”或“代码编辑”。")
        overview.currentRowChanged.connect(controller.record_list.setCurrentRow)
        self._attach_setup_event_context_menu(overview, controller)
        layout.addWidget(overview, 1)
        return host, overview

    @staticmethod
    def _disabled_structure_action(action, explanation: str) -> None:
        action.setEnabled(False)
        action.setToolTip(explanation)
        action.setStatusTip(explanation)

    def _build_setup_event_context_menu(
        self,
        listing: QListWidget,
        controller: LegacyScenarioEventsPage,
    ) -> QMenu:
        """Build the reference event menu with verified Bank-local relocation."""

        menu = QMenu(listing)
        insert_before = menu.addAction("插入(接上)")
        insert_after = menu.addAction("插入(接下)")
        insert_before.triggered.connect(
            lambda: self._insert_setup_event(controller, after=False)
        )
        insert_after.triggered.connect(
            lambda: self._insert_setup_event(controller, after=True)
        )
        menu.addSeparator()
        reinforcement = menu.addAction("添加增援")
        reinforcement.triggered.connect(
            lambda: self._insert_setup_reinforcement(controller)
        )
        menu.addSeparator()
        edit = menu.addAction("编辑")
        edit.triggered.connect(
            lambda: self._open_advanced_editor(controller, "事件指令")
        )
        code = menu.addAction("代码编辑")
        code.triggered.connect(lambda: self._open_setup_event_code_editor(controller))
        menu.addSeparator()
        cut = menu.addAction("剪切")
        cut.triggered.connect(lambda: self._cut_setup_event(controller))
        copy = menu.addAction("复制")
        copy.triggered.connect(lambda: self._copy_setup_event(controller, False))
        copy_all = menu.addAction("复制全部")
        copy_all.triggered.connect(lambda: self._copy_setup_event(controller, True))
        paste = menu.addAction("粘贴")
        paste.triggered.connect(lambda: self._paste_setup_event(controller, False))
        paste_all = menu.addAction("粘贴全部")
        paste_all.triggered.connect(lambda: self._paste_setup_event(controller, True))
        menu.addSeparator()
        delete = menu.addAction("删除")
        clear = menu.addAction("清空")
        delete.triggered.connect(lambda: self._delete_setup_event(controller))
        clear.triggered.connect(lambda: self._clear_setup_event(controller))
        has_selection = listing.currentItem() is not None
        for action in (
            insert_before, insert_after, reinforcement, edit, code, cut,
            copy, copy_all, paste, paste_all, delete, clear,
        ):
            action.setEnabled(has_selection)
        return menu

    def _attach_setup_event_context_menu(
        self, listing: QListWidget, controller: LegacyScenarioEventsPage
    ) -> None:
        listing.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)

        def show(position) -> None:
            item = listing.itemAt(position)
            if item is None:
                return
            listing.setCurrentItem(item)
            self._build_setup_event_context_menu(listing, controller).exec(
                listing.viewport().mapToGlobal(position)
            )

        listing.customContextMenuRequested.connect(show)

    def _open_setup_event_code_editor(
        self, controller: LegacyScenarioEventsPage
    ) -> None:
        row = controller.record_list.currentRow()
        if not 0 <= row < len(controller._instructions):
            return
        instruction = controller._instructions[row]
        dialog = EventCodeDialog(instruction.raw, None, self)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        controller.raw_edit.setText(dialog.raw().hex(" ").upper())
        controller.apply_changes()
        self._refresh_overviews()

    def _apply_setup_event_patches(
        self,
        controller: LegacyScenarioEventsPage,
        patches,
        description: str,
    ) -> bool:
        if controller.project is None:
            return False
        try:
            controller.project._apply_legacy_global_patches(patches, description)
        except Exception as error:
            QMessageBox.warning(self, "事件结构未修改", str(error))
            return False
        controller._drafts.clear()
        controller.refresh()
        self._refresh_overviews()
        controller.project_changed.emit(description)
        return True

    def _insert_setup_event(
        self,
        controller: LegacyScenarioEventsPage,
        *,
        after: bool,
        preset: bytes = b"\xDF",
        title: str = "插入事件指令",
    ) -> None:
        row = controller.record_list.currentRow()
        if not 0 <= row < len(controller._instructions) or controller.project is None:
            return
        instruction = controller._instructions[row]
        dialog = EventInstructionDialog(
            preset,
            self,
            title=title,
            allow_variable_length=True,
            context=(
                f"{LegacyScenarioCodec.PHASE_LABELS[controller.phase]} · "
                f"Bank ${instruction.bank:02X}:${instruction.address:04X} · "
                f"{'接下' if after else '接上'}"
            ),
        )
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        try:
            codec = LegacyScenarioCodec(controller.project.working)
            current = next(
                item
                for item in codec.instructions(controller.scenario_id, controller.phase)
                if item.address == instruction.address
            )
            patches = codec.insertion_patches(current, dialog.raw(), after=after)
        except Exception as error:
            QMessageBox.warning(self, "无法插入事件", str(error))
            return
        self._apply_setup_event_patches(controller, patches, "章节事件插入")

    def _insert_setup_reinforcement(
        self, controller: LegacyScenarioEventsPage
    ) -> None:
        self._insert_setup_event(
            controller,
            after=True,
            preset=bytes.fromhex("4B 00 00 00 00 00 00"),
            title="添加敌军增援",
        )

    def _delete_setup_event(
        self, controller: LegacyScenarioEventsPage
    ) -> None:
        row = controller.record_list.currentRow()
        if not 0 <= row < len(controller._instructions) or controller.project is None:
            return
        instruction = controller._instructions[row]
        try:
            codec = LegacyScenarioCodec(controller.project.working)
            current = next(
                item
                for item in codec.instructions(controller.scenario_id, controller.phase)
                if item.address == instruction.address
            )
            patches = codec.deletion_patches(current)
        except Exception as error:
            QMessageBox.warning(self, "无法删除事件", str(error))
            return
        self._apply_setup_event_patches(controller, patches, "章节事件删除")

    def _cut_setup_event(self, controller: LegacyScenarioEventsPage) -> None:
        self._copy_setup_event(controller, False)
        self._delete_setup_event(controller)

    def _clear_setup_event(self, controller: LegacyScenarioEventsPage) -> None:
        row = controller.record_list.currentRow()
        if not 0 <= row < len(controller._instructions) or controller.project is None:
            return
        instruction = controller._instructions[row]
        try:
            codec = LegacyScenarioCodec(controller.project.working)
            current = next(
                item
                for item in codec.instructions(controller.scenario_id, controller.phase)
                if item.address == instruction.address
            )
            patches = codec.replacement_patches(current, b"\xDF")
        except Exception as error:
            QMessageBox.warning(self, "无法清空事件", str(error))
            return
        self._apply_setup_event_patches(controller, patches, "章节事件清空")

    @staticmethod
    def _copy_setup_event(
        controller: LegacyScenarioEventsPage, copy_all: bool
    ) -> None:
        if copy_all:
            lines = [
                controller._drafts.get(item.file_offset, item.raw.hex(" ").upper())
                for item in controller._instructions
            ]
            QApplication.clipboard().setText("\n".join(lines))
            return
        row = controller.record_list.currentRow()
        if 0 <= row < len(controller._instructions):
            item = controller._instructions[row]
            QApplication.clipboard().setText(
                controller._drafts.get(item.file_offset, item.raw.hex(" ").upper())
            )

    def _paste_setup_event(
        self, controller: LegacyScenarioEventsPage, paste_all: bool
    ) -> None:
        text = QApplication.clipboard().text().strip()
        rows = [line.strip() for line in text.splitlines() if line.strip()]
        if not paste_all:
            rows = [text]
            targets = [controller.record_list.currentRow()]
        else:
            targets = list(range(len(controller._instructions)))
        if len(rows) != len(targets):
            QMessageBox.warning(
                self,
                "无法粘贴事件指令",
                f"需要 {len(targets)} 条等长指令，剪贴板中有 {len(rows)} 条。",
            )
            return
        replacements: list[tuple[Any, bytes]] = []
        try:
            for row, raw_text in zip(targets, rows):
                if not 0 <= row < len(controller._instructions):
                    raise ValueError("请先选择一条事件指令。")
                instruction = controller._instructions[row]
                raw = bytes.fromhex(raw_text)
                if paste_all:
                    controller.codec.replacement_patch(instruction, raw)
                else:
                    controller.codec._validate_sequence(raw)
                replacements.append((instruction, raw))
        except (AttributeError, ValueError, IndexError) as error:
            QMessageBox.warning(self, "无法粘贴事件指令", str(error))
            return
        for instruction, raw in replacements:
            if raw == instruction.raw:
                controller._drafts.pop(instruction.file_offset, None)
            else:
                controller._drafts[instruction.file_offset] = raw.hex(" ").upper()
        controller._select()

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
        overview.setToolTip("双击或右键所选事件打开参数编辑器。")
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
        self._attach_edit_context_menu(
            overview,
            "编辑所选事件参数…",
            lambda page=controller: self._open_advanced_editor(
                page, "事件参数编辑"
            ),
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
        self.persuasion_overview_list.setToolTip(
            "双击或右键所选规则打开劝降条件编辑器。"
        )
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
        self._attach_edit_context_menu(
            self.persuasion_overview_list,
            "编辑所选劝降条件…",
            lambda: self._open_advanced_editor(
                self.persuasion_page, "劝降事件编辑"
            ),
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
        overview.setToolTip("双击或右键所选文字打开编辑器。")
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
        self._attach_edit_context_menu(
            overview,
            f"编辑所选{title}…",
            lambda page=controller, caption=title: self._open_advanced_editor(
                page, caption
            ),
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

    @staticmethod
    def _build_edit_context_menu(
        listing: QListWidget,
        action_text: str,
        callback: Callable[[], None],
    ) -> QMenu:
        menu = QMenu(listing)
        action = menu.addAction(action_text)
        action.triggered.connect(callback)
        action.setEnabled(listing.currentItem() is not None)
        return menu

    def _attach_edit_context_menu(
        self,
        listing: QListWidget,
        action_text: str,
        callback: Callable[[], None],
    ) -> None:
        listing.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)

        def show(position) -> None:
            item = listing.itemAt(position)
            if item is None:
                return
            listing.setCurrentItem(item)
            self._build_edit_context_menu(
                listing, action_text, callback
            ).exec(listing.viewport().mapToGlobal(position))

        listing.customContextMenuRequested.connect(show)

    def _configure_event_views(self) -> None:
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
            if not self._commit_initial_victory():
                restore()
                return
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
        self._load_initial_victory(scenario_id)
        self.title_preview.clear()
        title_supported = (
            self.project is not None
            and self.project.supports_chapter_titles
            and self.project.chapter_title_codec is not None
            and scenario_id < self.project.chapter_title_codec.count
        )
        self.title_code_button.setEnabled(title_supported)
        if self.project is not None:
            self.title_preview.setPixmap(
                render_chapter_title(self.project, scenario_id)
            )
        else:
            self.title_preview.setText(label)

        for page in self.setup_event_pages:
            if not page.has_pending_draft:
                page.set_scenario(scenario_id)
        for page in (self.map_event_page,):
            if self._lazy_scenario and page not in self._loaded_pages:
                continue
            if page.has_pending_draft:
                continue
            index = page.scenario_filter.findData(scenario_id)
            if index >= 0:
                page.scenario_filter.setCurrentIndex(index)
        self._refresh_overviews()

    def _open_title_editor(self) -> None:
        if self.project is None or self.current_scenario_id is None:
            return
        if not self.project.supports_chapter_titles:
            QMessageBox.warning(
                self,
                "无法编辑标题拼图",
                "当前 ROM 没有已验证的关卡标题表。",
            )
            return
        dialog = ChapterTitleDialog(
            self.project,
            self.current_scenario_id,
            self,
        )
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        self.title_preview.setPixmap(
            render_chapter_title(self.project, self.current_scenario_id)
        )
        self.project_changed.emit(
            f"已更新关卡 {self.current_scenario_id + 1:03d} 标题拼图"
        )

    @staticmethod
    def _victory_editor_text(text: str) -> str:
        """Match the reference editor's visible line before each ``@`` break."""

        return text.replace("@", "\n@")

    @staticmethod
    def _victory_encoded_text(text: str) -> str:
        return text.replace("\r\n@", "@").replace("\n@", "@")

    def _load_initial_victory(self, scenario_id: int) -> None:
        supported = (
            self.project is not None
            and self.project.supports_chapter_victory
            and self.project.chapter_victory_codec is not None
            and scenario_id < self.project.chapter_victory_codec.count
        )
        previous = self.initial_victory.blockSignals(True)
        try:
            self.initial_victory_status.setStyleSheet("")
            if not supported:
                self._victory_source_body = b""
                self._victory_source_text = ""
                self._victory_dirty = False
                self.initial_victory.setPlainText(
                    "该备用关卡没有已验证的初始胜利文字记录。"
                )
                self.initial_victory.setReadOnly(True)
                self.initial_victory_status.setText("只读 · 不会写入 ROM")
                return
            assert self.project is not None
            record = self.project.get_chapter_victory(scenario_id)
            decoded = self.project.dc_text_table().decode(record.body)
            display = self._victory_editor_text(decoded)
            self._victory_source_body = record.body
            self._victory_source_text = display
            self._victory_dirty = False
            self.initial_victory.setReadOnly(False)
            self.initial_victory.setPlainText(display)
            self.initial_victory_status.setText(
                f"ROM $3D:${0x8000 + record.file_offset - 0x7A010:04X} · "
                f"正文 {record.body_capacity} 字节 · 13 关共享池内可变长"
            )
        finally:
            self.initial_victory.blockSignals(previous)

    def _pending_initial_victory_body(self) -> bytes:
        if self.project is None or self.current_scenario_id is None:
            return b""
        normalized = self._victory_encoded_text(
            self.initial_victory.toPlainText()
        )
        text_table, _allocated = self.project.prospective_font_text_table(
            normalized, channel="story", validate_renderer=True
        )
        source_text = text_table.decode(self._victory_source_body)
        if normalized == source_text:
            return self._victory_source_body
        return text_table.encode_preserving_tokens(
            self._victory_source_body,
            normalized,
        )

    def _victory_text_changed(self) -> None:
        if self.initial_victory.isReadOnly() or self.current_scenario_id is None:
            self._victory_dirty = False
            return
        self._victory_dirty = (
            self.initial_victory.toPlainText() != self._victory_source_text
        )
        if not self._victory_dirty:
            return
        try:
            body = self._pending_initial_victory_body()
            if self.project is None or self.project.chapter_victory_codec is None:
                raise ValueError("当前 ROM 没有已验证的初始胜利文字表。")
            self.project.chapter_victory_codec.replacement_patches(
                self.project.working,
                self.current_scenario_id,
                body,
            )
            self.initial_victory_status.setText(
                f"正文 {len(body)} 字节 · 共享池可重排 · 有尚未应用的改动"
            )
            self.initial_victory_status.setStyleSheet(
                "color: #b45309; font-weight: 650;"
            )
        except (RomFormatError, ValueError) as error:
            self.initial_victory_status.setText(str(error))
            self.initial_victory_status.setStyleSheet("color: #b42318;")

    def _commit_initial_victory(self) -> bool:
        if not self._victory_dirty:
            return True
        if self.project is None or self.current_scenario_id is None:
            return False
        try:
            normalized = self._victory_encoded_text(
                self.initial_victory.toPlainText()
            )
            with self.project.transaction(
                f"关卡 {self.current_scenario_id + 1:03d} · 初始胜利文字"
            ):
                self.project.ensure_font_characters(normalized, channel="story")
                body = self._pending_initial_victory_body()
                self.project.set_chapter_victory_body(
                    self.current_scenario_id, body
                )
        except (RomFormatError, ValueError) as error:
            QMessageBox.warning(self, "无法应用初始胜利文字", str(error))
            return False
        self._victory_source_body = body
        self._victory_source_text = self.initial_victory.toPlainText()
        self._victory_dirty = False
        self.initial_victory_status.setStyleSheet("")
        self.initial_victory_status.setText(
            f"正文 {len(body)} 字节 · 已应用到当前工程"
        )
        self.project_changed.emit(
            f"已更新关卡 {self.current_scenario_id + 1:03d} 初始胜利文字"
        )
        return True

    def accept(self) -> None:
        if not self._commit_initial_victory():
            return
        super().accept()

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
    def _refresh_setup_event_overview(
        page: LegacyScenarioEventsPage, overview: QListWidget
    ) -> None:
        selected_row = page.record_list.currentRow()
        overview.blockSignals(True)
        overview.clear()
        for row in range(page.record_list.count()):
            source = page.record_list.item(row)
            item = QListWidgetItem(source.text())
            if row < len(page._instructions):
                instruction = page._instructions[row]
                item.setToolTip(
                    f"Bank ${instruction.bank:02X} · ${instruction.address:04X} · "
                    f"{instruction.raw.hex(' ').upper()}\n"
                    "选择后在下方编辑；右键打开事件菜单。"
                )
            overview.addItem(item)
        if overview.count():
            overview.setCurrentRow(min(max(selected_row, 0), overview.count() - 1))
        overview.blockSignals(False)
        if overview.currentRow() >= 0:
            page.record_list.setCurrentRow(overview.currentRow())

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
        for page, overview in zip(self.setup_event_pages, self.setup_event_lists):
            self._refresh_setup_event_overview(page, overview)
        if not self._lazy_scenario or self.action_event_page in self._loaded_pages:
            self.action_event_page.refresh()
        if not self._lazy_scenario or self.map_event_page in self._loaded_pages:
            self._refresh_event_overview(self.map_event_page, self.map_event_list)
        if not self._lazy_scenario or self.persuasion_page in self._loaded_pages:
            self._refresh_persuasion_overview()
        if not self._lazy_scenario or self.story_page in self._loaded_pages:
            self._refresh_story_overview(self.story_page, self.story_overview_list)
        if not self._lazy_scenario or self.victory_page in self._loaded_pages:
            self._refresh_story_overview(
                self.victory_page, self.victory_overview_list
            )
        revision = self.project.revision if self.project is not None else -1
        key = (revision, self.current_scenario_id)
        for tab_index in range(len(self.TAB_LABELS)):
            self._overview_refresh_keys[tab_index] = key

    def _open_advanced_editor(self, page: ProjectPage, title: str) -> None:
        if isinstance(page, LegacyScenarioEventsPage):
            row = page.record_list.currentRow()
            if not 0 <= row < len(page._instructions):
                return
            instruction = page._instructions[row]
            dialog = EventParameterDialog(
                instruction.raw,
                self,
                title=title,
                context=(
                    f"{LegacyScenarioCodec.PHASE_LABELS[page.phase]} · "
                    f"关卡 {page.scenario_id + 1:03d} · "
                    f"Bank ${instruction.bank:02X}:${instruction.address:04X}"
                ),
            )
            if dialog.exec() != QDialog.DialogCode.Accepted:
                return
            page.raw_edit.setText(dialog.raw().hex(" ").upper())
            page.apply_changes()
            self._refresh_overviews()
            return
        if isinstance(page, EventPage):
            instruction = page._selected_instruction()
            if instruction is None:
                return
            dialog = EventParameterDialog(
                instruction.raw,
                self,
                title=title,
                context=(
                    f"地址 ${instruction.address:04X} · "
                    f"{page._context_text(instruction)}"
                ),
            )
            if dialog.exec() != QDialog.DialogCode.Accepted:
                return
            page.raw.setText(dialog.raw().hex(" ").upper())
            page._apply_raw()
            self._refresh_overviews()
            return
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

    def set_project(self, project: RomProject | None) -> None:
        self._overview_refresh_keys.clear()
        super().set_project(project)
        self.space_button.setEnabled(project is not None)
        self._configure_event_views()
        self._populate_chapters()
        self._refresh_overviews()
