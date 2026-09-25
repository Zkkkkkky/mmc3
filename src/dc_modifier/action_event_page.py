from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QApplication,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMenu,
    QPushButton,
    QSplitter,
    QVBoxLayout,
    QWidget,
)

from fc_editor.codecs.action_event import ActionEventInstruction
from fc_editor.codecs.action_event import ActionEventRecord
from fc_editor.codecs.chapter_event import ChapterEventCodec

from .pages import ProjectPage
from .beginner_ui import collapsible_details, task_hint
from .event_instruction_dialog import (
    EventCodeDialog,
    EventInstructionDialog,
    EventParameterDialog,
)
from .event_preview import reference_event_preview


def _load_action_names() -> tuple[str, ...]:
    path = (
        Path(__file__).resolve().parents[1]
        / "resources"
        / "default_config"
        / "行动名称.ini"
    )
    labels: list[str] = []
    if path.is_file():
        for encoding in ("utf-8-sig", "gb18030"):
            try:
                labels = [
                    line.strip()
                    for line in path.read_text(encoding=encoding).splitlines()
                ]
                break
            except UnicodeError:
                continue
    return tuple(
        labels[index] if index < len(labels) and labels[index] else "无"
        for index in range(0x100)
    )


ACTION_EVENT_NAMES = _load_action_names()


class ActionEventPage(ProjectPage):
    """Reference-shaped editor for the independent 256-entry action table."""

    transaction_sync_group = "action_event"
    _instruction_clipboard: bytes | None = None
    _record_clipboard: tuple[bytes, int] | None = None

    def __init__(self) -> None:
        super().__init__()
        self.current_action_id: int | None = None
        self.current_instruction_index: int | None = None
        self._source_raw = b""
        self._records: tuple[ActionEventRecord, ...] = ()
        self._changing_selection = False

        layout = QVBoxLayout(self)
        self.task_hint = task_hint(
            "操作：① 选择行动　② 右键事件指令　③ 选择插入、编辑、复制或删除"
        )
        layout.addWidget(self.task_hint)
        controls = QHBoxLayout()
        self.search = QLineEdit()
        self.search.setPlaceholderText("搜索行动名或ID…")
        self.search.setClearButtonEnabled(True)
        self.count_badge = QLabel("0 个行动")
        self.count_badge.setObjectName("countBadge")
        controls.addWidget(self.search, 1)
        controls.addWidget(self.count_badge)
        layout.addLayout(controls)

        splitter = QSplitter()
        actions = QGroupBox("行动事件")
        actions_layout = QVBoxLayout(actions)
        self.action_list = QListWidget()
        self.action_list.setAlternatingRowColors(True)
        self.action_list.setUniformItemSizes(True)
        self.action_list.setContextMenuPolicy(
            Qt.ContextMenuPolicy.CustomContextMenu
        )
        self.action_list.setToolTip(
            "右键菜单与参考版一致：复制、粘贴完整行动，或清空当前项下方的行动。"
        )
        actions_layout.addWidget(self.action_list)
        splitter.addWidget(actions)

        editor = QGroupBox("事件编辑")
        editor_layout = QVBoxLayout(editor)
        self.record_status = QLabel("请选择行动。")
        self.record_status.setWordWrap(True)
        self.record_status.setObjectName("hintText")
        self.instruction_list = QListWidget()
        self.instruction_list.setAlternatingRowColors(True)
        self.instruction_list.setUniformItemSizes(True)
        self.instruction_list.setContextMenuPolicy(
            Qt.ContextMenuPolicy.CustomContextMenu
        )
        self.instruction_list.setToolTip(
            "右键菜单与参考版一致：接上/接下、添加增援、编辑、代码编辑、"
            "剪切、复制、复制全部、粘贴、粘贴全部、删除和清空。"
        )
        self.raw = QLineEdit()
        self.raw.setPlaceholderText("一条完整指令，例如 60 05")
        self.pending_state = QLabel("请选择指令。")
        self.pending_state.setObjectName("pendingBanner")
        self.pending_state.setWordWrap(True)
        editor_layout.addWidget(self.instruction_list, 1)
        self.raw_label = QLabel("当前指令原码")
        editor_layout.addWidget(self.raw_label)
        editor_layout.addWidget(self.raw)
        editor_layout.addWidget(self.pending_state)

        edit_buttons = QHBoxLayout()
        self.visual_edit_button = QPushButton("可视化编辑…")
        self.apply_button = QPushButton("编辑")
        self.insert_before_button = QPushButton("插入（接上）")
        self.insert_after_button = QPushButton("插入（接下）")
        self.delete_button = QPushButton("删除")
        edit_buttons.addWidget(self.visual_edit_button)
        edit_buttons.addWidget(self.apply_button)
        edit_buttons.addWidget(self.insert_before_button)
        edit_buttons.addWidget(self.insert_after_button)
        edit_buttons.addWidget(self.delete_button)
        editor_layout.addLayout(edit_buttons)

        transfer_buttons = QHBoxLayout()
        self.copy_button = QPushButton("复制")
        self.paste_button = QPushButton("粘贴")
        self.reset_button = QPushButton("还原行动")
        transfer_buttons.addWidget(self.copy_button)
        transfer_buttons.addWidget(self.paste_button)
        transfer_buttons.addStretch()
        transfer_buttons.addWidget(self.reset_button)
        editor_layout.addLayout(transfer_buttons)

        # The reference window keeps the action page as a readable list.  It
        # only reveals parameters after the user explicitly chooses Edit or
        # Code Edit from the right-click menu.  Keep the programmatic controls
        # for compatibility/tests, but do not embed the current raw command or
        # duplicate action buttons in the page itself.
        self.raw_label.hide()
        self.raw.hide()
        self.pending_state.hide()
        for button in (
            self.visual_edit_button,
            self.apply_button,
            self.insert_before_button,
            self.insert_after_button,
            self.delete_button,
            self.copy_button,
            self.paste_button,
            self.reset_button,
        ):
            button.hide()
        splitter.addWidget(editor)
        splitter.setStretchFactor(0, 2)
        splitter.setStretchFactor(1, 5)
        layout.addWidget(splitter, 1)

        self.capacity_status = QLabel(
            "安全边界：变长操作会原子更新 256 项指针并重定位池内跳转。"
        )
        self.capacity_status.setWordWrap(True)
        self.capacity_status.setStyleSheet("color: #9a5b00;")
        diagnostics = QWidget()
        diagnostics_layout = QVBoxLayout(diagnostics)
        diagnostics_layout.setContentsMargins(0, 0, 0, 0)
        diagnostics_layout.addWidget(self.record_status)
        diagnostics_layout.addWidget(self.capacity_status)
        self.advanced_details = collapsible_details(diagnostics)
        layout.addWidget(self.advanced_details)

        self.search.textChanged.connect(self._filter_actions)
        self.action_list.currentItemChanged.connect(self._action_changed)
        self.instruction_list.currentItemChanged.connect(self._instruction_changed)
        self.action_list.customContextMenuRequested.connect(
            self._show_action_context_menu
        )
        self.instruction_list.customContextMenuRequested.connect(
            self._show_instruction_context_menu
        )
        self.raw.textChanged.connect(self._update_pending_state)
        self.visual_edit_button.clicked.connect(self._open_instruction_editor)
        self.apply_button.clicked.connect(self._apply_raw)
        self.insert_before_button.clicked.connect(
            lambda: self._insert_raw(after=False)
        )
        self.insert_after_button.clicked.connect(
            lambda: self._insert_raw(after=True)
        )
        self.delete_button.clicked.connect(self._delete_instruction)
        self.copy_button.clicked.connect(self.copy_instruction)
        self.paste_button.clicked.connect(self.paste_instruction)
        self.reset_button.clicked.connect(self._reset_action)
        self._set_editor_enabled(False)

    @staticmethod
    def _select_context_item(listing: QListWidget, position) -> bool:
        item = listing.itemAt(position)
        if item is None:
            return False
        listing.setCurrentItem(item)
        return True

    def _build_action_context_menu(self) -> QMenu:
        menu = QMenu(self.action_list)
        copy = menu.addAction("复制")
        copy.triggered.connect(self.copy_all_instructions)
        paste = menu.addAction("粘贴")
        paste.triggered.connect(self.paste_all_instructions)
        clear = menu.addAction("清空下方")
        clear.triggered.connect(self.clear_actions_below)
        enabled = self._record() is not None
        copy.setEnabled(enabled)
        paste.setEnabled(enabled and type(self)._record_clipboard is not None)
        clear.setEnabled(enabled)
        return menu

    def _show_action_context_menu(self, position) -> None:
        if not self._select_context_item(self.action_list, position):
            return
        self._build_action_context_menu().exec(
            self.action_list.viewport().mapToGlobal(position)
        )

    def _open_code_editor(self) -> None:
        instruction = self._selected_instruction()
        if instruction is None:
            return
        try:
            raw = self._candidate_raw() if self.has_pending_draft else instruction.raw
        except Exception as error:
            self.show_error(error)
            return
        dialog = EventCodeDialog(raw, None, self)
        if dialog.exec() != dialog.DialogCode.Accepted:
            return
        self.raw.setText(dialog.raw().hex(" ").upper())
        self._apply_raw()

    def _open_instruction_editor(self) -> None:
        instruction = self._selected_instruction()
        if instruction is None:
            return
        try:
            raw = self._candidate_raw() if self.has_pending_draft else instruction.raw
        except Exception as error:
            self.show_error(error)
            return
        dialog = EventParameterDialog(
            raw,
            self,
            title="行动事件指令编辑",
            context=(
                f"行动 ${self.current_action_id:02X} · 指令 {instruction.index + 1:03d} · "
                f"Bank $26:${instruction.address:04X}"
            ),
        )
        if dialog.exec() != dialog.DialogCode.Accepted:
            return
        self.raw.setText(dialog.raw().hex(" ").upper())
        self._apply_raw()

    def _build_instruction_context_menu(self) -> QMenu:
        menu = QMenu(self.instruction_list)
        insert_before = menu.addAction("插入（接上）")
        insert_before.triggered.connect(lambda: self._insert_raw(after=False))
        insert_after = menu.addAction("插入（接下）")
        insert_after.triggered.connect(lambda: self._insert_raw(after=True))
        menu.addSeparator()
        reinforcement = menu.addAction("添加增援")
        reinforcement.triggered.connect(self._add_reinforcement)
        menu.addSeparator()
        edit = menu.addAction("编辑")
        edit.triggered.connect(self._open_instruction_editor)
        code_edit = menu.addAction("代码编辑")
        code_edit.triggered.connect(self._open_code_editor)
        menu.addSeparator()
        cut = menu.addAction("剪切")
        cut.triggered.connect(self.cut_instruction)
        copy = menu.addAction("复制")
        copy.triggered.connect(self.copy_instruction)
        copy_all = menu.addAction("复制全部")
        copy_all.triggered.connect(self.copy_all_instructions)
        paste = menu.addAction("粘贴")
        paste.triggered.connect(self.paste_instruction)
        paste_all = menu.addAction("粘贴全部")
        paste_all.triggered.connect(self.paste_all_instructions)
        delete = menu.addAction("删除")
        delete.triggered.connect(self._delete_instruction)
        clear = menu.addAction("清空")
        clear.triggered.connect(self.clear_action)
        enabled = self._selected_instruction() is not None
        for action in (
            insert_before,
            insert_after,
            reinforcement,
            edit,
            code_edit,
            cut,
            copy,
            copy_all,
            paste,
            paste_all,
            delete,
            clear,
        ):
            action.setEnabled(enabled)
        paste.setEnabled(enabled and type(self)._instruction_clipboard is not None)
        paste_all.setEnabled(enabled and type(self)._record_clipboard is not None)
        return menu

    def _show_instruction_context_menu(self, position) -> None:
        if not self._select_context_item(self.instruction_list, position):
            return
        self._build_instruction_context_menu().exec(
            self.instruction_list.viewport().mapToGlobal(position)
        )

    @staticmethod
    def _parse_hex(text: str) -> bytes:
        compact = text.replace(",", " ").replace("0x", "").replace("$", "")
        tokens = compact.split()
        if not tokens:
            raise ValueError("请输入十六进制字节。")
        try:
            return bytes(int(token, 16) for token in tokens)
        except ValueError as error:
            raise ValueError("原始字节必须是 00—FF 的十六进制数。") from error

    @staticmethod
    def _validate_instruction(raw: bytes) -> None:
        if not raw:
            raise ValueError("事件指令不能为空。")
        length = ChapterEventCodec.instruction_length(raw[0], raw, 0)
        if length != len(raw):
            raise ValueError(
                f"操作码 ${raw[0]:02X} 需要 {length} 字节，"
                f"当前输入为 {len(raw)} 字节。"
            )

    def _record(self):
        if (
            self.project is None
            or self.current_action_id is None
            or not self.project.supports_action_events
        ):
            return None
        if self.current_action_id < len(self._records):
            return self._records[self.current_action_id]
        return self.project.get_action_event(self.current_action_id)

    def _selected_instruction(self) -> ActionEventInstruction | None:
        record = self._record()
        if record is None or self.current_instruction_index is None:
            return None
        if not 0 <= self.current_instruction_index < len(record.instructions):
            return None
        return record.instructions[self.current_instruction_index]

    def _set_editor_enabled(self, enabled: bool) -> None:
        for widget in (
            self.raw,
            self.visual_edit_button,
            self.apply_button,
            self.insert_before_button,
            self.insert_after_button,
            self.delete_button,
            self.copy_button,
            self.paste_button,
            self.reset_button,
        ):
            widget.setEnabled(enabled)

    def refresh(self) -> None:
        action_id = self.current_action_id
        instruction_index = self.current_instruction_index
        self.action_list.blockSignals(True)
        self.action_list.clear()
        if self.project is not None and self.project.supports_action_events:
            self._records = self.project.action_event_records()
            for item_id, record in enumerate(self._records):
                item = QListWidgetItem(
                    f"{item_id:03d} [${item_id:02X}] {ACTION_EVENT_NAMES[item_id]}"
                )
                item.setData(Qt.ItemDataRole.UserRole, item_id)
                item.setToolTip(
                    f"Bank $26:${record.pointer:04X} · {len(record.instructions)} 条指令 · "
                    f"{len(record.raw)} 字节\n{record.raw.hex(' ').upper()}"
                )
                self.action_list.addItem(item)
        self.action_list.blockSignals(False)
        self.count_badge.setText(f"{self.action_list.count()} 个行动")
        self._filter_actions(self.search.text())
        if self.action_list.count():
            row = action_id if action_id is not None else 0
            self.action_list.setCurrentRow(min(row, self.action_list.count() - 1))
            self.current_action_id = min(row, self.action_list.count() - 1)
            self._populate_instructions(instruction_index)
        else:
            self._records = ()
            self.current_action_id = None
            self.current_instruction_index = None
            self.instruction_list.clear()
            self.raw.clear()
            self.record_status.setText("当前 ROM 不支持独立行动事件表。")
            self._set_editor_enabled(False)

    def _filter_actions(self, text: str) -> None:
        query = text.strip().casefold()
        visible = 0
        for row in range(self.action_list.count()):
            item = self.action_list.item(row)
            hidden = bool(query) and query not in (
                item.text() + " " + item.toolTip()
            ).casefold()
            item.setHidden(hidden)
            visible += not hidden
        self.count_badge.setText(f"{visible} / {self.action_list.count()} 个行动")

    def _select_action(self, action_id: int | None) -> None:
        self.action_list.blockSignals(True)
        try:
            self.action_list.setCurrentRow(-1 if action_id is None else action_id)
        finally:
            self.action_list.blockSignals(False)

    def _select_instruction(self, index: int | None) -> None:
        self.instruction_list.blockSignals(True)
        try:
            self.instruction_list.setCurrentRow(-1 if index is None else index)
        finally:
            self.instruction_list.blockSignals(False)

    def _action_changed(
        self,
        current: QListWidgetItem | None,
        _previous: QListWidgetItem | None,
    ) -> None:
        if self._changing_selection or current is None:
            return
        requested = int(current.data(Qt.ItemDataRole.UserRole))
        previous = self.current_action_id
        if previous is not None and requested != previous and self.has_pending_draft:
            self._select_action(previous)
            if not self.commit_pending_changes():
                self.show_error(
                    ValueError(
                        self.pending_draft_error
                        or "当前指令无法应用，请修正后再切换行动。"
                    )
                )
                return
            self._select_action(requested)
        self.current_action_id = requested
        self._populate_instructions(0)

    def _populate_instructions(self, requested_index: int | None = None) -> None:
        record = self._record()
        self.instruction_list.blockSignals(True)
        self.instruction_list.clear()
        if record is not None:
            address_rows = {
                instruction.address: instruction.index
                for instruction in record.instructions
            }
            for instruction in record.instructions:
                item = QListWidgetItem(
                    reference_event_preview(
                        instruction,
                        index=instruction.index,
                        project=self.project,
                        address_rows=address_rows,
                    )
                )
                item.setData(Qt.ItemDataRole.UserRole, instruction.index)
                item.setToolTip(
                    f"Bank $26:${instruction.address:04X} / "
                    f"文件 0x{instruction.file_offset:X}"
                )
                self.instruction_list.addItem(item)
            usage = self.project.action_event_usage()
            aliases = "、".join(f"${item:02X}" for item in record.aliases)
            self.record_status.setText(
                f"行动 ${record.action_id:02X} · {ACTION_EVENT_NAMES[record.action_id]} · "
                f"Bank $26:${record.pointer:04X} · {len(record.instructions)} 条 / "
                f"{len(record.raw)} 字节 · 指针引用 {aliases}"
            )
            self.capacity_status.setText(
                f"行动池：{usage.used} / {usage.capacity} 字节，"
                f"可用 {usage.free} 字节；变长操作会原子重排指针并重定位"
                "$55/$57/$58 池内跳转。"
            )
        self.instruction_list.blockSignals(False)
        if self.instruction_list.count():
            index = 0 if requested_index is None else min(
                max(requested_index, 0), self.instruction_list.count() - 1
            )
            self.instruction_list.setCurrentRow(index)
            self.current_instruction_index = index
            self._show_instruction(self._selected_instruction())
        else:
            self.current_instruction_index = None
            self._show_instruction(None)

    def _instruction_changed(
        self,
        current: QListWidgetItem | None,
        _previous: QListWidgetItem | None,
    ) -> None:
        if self._changing_selection or current is None:
            return
        requested = int(current.data(Qt.ItemDataRole.UserRole))
        previous = self.current_instruction_index
        if previous is not None and requested != previous and self.has_pending_draft:
            self._select_instruction(previous)
            if not self.commit_pending_changes():
                self.show_error(
                    ValueError(
                        self.pending_draft_error
                        or "当前指令无法应用，请修正后再切换。"
                    )
                )
                return
            self._select_instruction(requested)
        self.current_instruction_index = requested
        self._show_instruction(self._selected_instruction())

    def _show_instruction(self, instruction: ActionEventInstruction | None) -> None:
        self.raw.blockSignals(True)
        if instruction is None:
            self._source_raw = b""
            self.raw.clear()
            self.pending_state.setText("请选择指令。")
            self._set_editor_enabled(False)
        else:
            self._source_raw = instruction.raw
            self.raw.setText(instruction.raw.hex(" ").upper())
            self._set_editor_enabled(True)
            self.pending_state.setText("✓ 与当前工程一致")
            self.pending_state.setStyleSheet("color: #2e7d4f;")
        self.raw.blockSignals(False)
        self._update_pending_state()

    def _candidate_raw(self) -> bytes:
        value = self._parse_hex(self.raw.text())
        self._validate_instruction(value)
        return value

    def _update_pending_state(self) -> None:
        instruction = self._selected_instruction()
        if instruction is None:
            self.apply_button.setEnabled(False)
            return
        try:
            raw = self._candidate_raw()
            changed = raw != self._source_raw
            self.pending_state.setText(
                "● 指令长度改变，应用时将重排行动池"
                if changed and len(raw) != len(self._source_raw)
                else "● 当前指令尚未应用"
                if changed
                else "✓ 与当前工程一致"
            )
            self.pending_state.setStyleSheet(
                "color: #b45309; font-weight: 650;"
                if changed
                else "color: #2e7d4f;"
            )
            self.apply_button.setEnabled(changed)
        except (ValueError, IndexError) as error:
            self.pending_state.setText(f"● {error}")
            self.pending_state.setStyleSheet("color: #b42318; font-weight: 650;")
            self.apply_button.setEnabled(False)

    @property
    def has_pending_draft(self) -> bool:
        return self.pending_state.text().startswith("●")

    @property
    def pending_draft_error(self) -> str | None:
        if not self.has_pending_draft:
            return None
        try:
            self._candidate_raw()
        except (ValueError, IndexError) as error:
            return str(error)
        return None

    def commit_pending_changes(self) -> bool:
        if not self.has_pending_draft:
            return True
        if self.pending_draft_error is not None:
            return False
        self._apply_raw()
        return not self.has_pending_draft

    def discard_pending_changes(self) -> None:
        self._show_instruction(self._selected_instruction())

    def _apply_raw(self) -> None:
        if (
            self.project is None
            or self.current_action_id is None
            or self.current_instruction_index is None
        ):
            return
        try:
            raw = self._candidate_raw()
            self.project.set_action_event_instruction(
                self.current_action_id,
                self.current_instruction_index,
                raw,
            )
        except Exception as error:
            self.show_error(error)
            return
        action_id = self.current_action_id
        index = self.current_instruction_index
        self.refresh()
        self.current_action_id = action_id
        self._select_action(action_id)
        self._populate_instructions(index)
        self.project_changed.emit(
            f"已更新行动 ${action_id:02X} 指令 {index + 1}"
        )

    def _insert_raw(self, *, after: bool) -> None:
        if (
            self.project is None
            or self.current_action_id is None
            or self.current_instruction_index is None
        ):
            return
        try:
            if self.has_pending_draft and self.pending_draft_error is not None:
                raise ValueError(self.pending_draft_error)
            preset = self._candidate_raw()
        except Exception as error:
            self.show_error(error)
            return
        dialog = EventInstructionDialog(
            preset,
            self,
            title="插入事件指令",
            allow_variable_length=True,
            context=(
                f"行动 ${self.current_action_id:02X} · "
                f"在第 {self.current_instruction_index + 1} 条"
                f"{'之后' if after else '之前'}插入"
            ),
        )
        if dialog.exec() != dialog.DialogCode.Accepted:
            return
        try:
            raw = dialog.raw()
            action_id = self.current_action_id
            index = self.current_instruction_index
            self.project.insert_action_event_instruction(
                action_id,
                index,
                raw,
                after=after,
            )
        except Exception as error:
            self.show_error(error)
            return
        target = index + (1 if after else 0)
        self.refresh()
        self.current_action_id = action_id
        self._select_action(action_id)
        self._populate_instructions(target)
        self.project_changed.emit(
            f"已在行动 ${action_id:02X} 插入一条指令"
        )

    def _delete_instruction(self) -> None:
        if (
            self.project is None
            or self.current_action_id is None
            or self.current_instruction_index is None
        ):
            return
        try:
            if self.has_pending_draft:
                raise ValueError("当前指令有未应用改动，请先编辑或还原。")
            action_id = self.current_action_id
            index = self.current_instruction_index
            self.project.delete_action_event_instruction(action_id, index)
        except Exception as error:
            self.show_error(error)
            return
        self.refresh()
        self.current_action_id = action_id
        self._select_action(action_id)
        self._populate_instructions(max(0, index - 1))
        self.project_changed.emit(
            f"已从行动 ${action_id:02X} 删除一条指令"
        )

    def copy_instruction(self) -> None:
        try:
            raw = self._candidate_raw()
        except Exception as error:
            self.show_error(error)
            return
        type(self)._instruction_clipboard = raw
        QApplication.clipboard().setText(raw.hex(" ").upper())

    def paste_instruction(self) -> None:
        try:
            raw = type(self)._instruction_clipboard
            if raw is None:
                raw = self._parse_hex(QApplication.clipboard().text())
            self._validate_instruction(raw)
        except Exception as error:
            self.show_error(error)
            return
        self.raw.setText(raw.hex(" ").upper())

    def cut_instruction(self) -> None:
        if self._selected_instruction() is None:
            return
        self.copy_instruction()
        self._delete_instruction()

    def copy_all_instructions(self) -> None:
        record = self._record()
        if record is None:
            return
        type(self)._record_clipboard = (record.raw, record.pointer)
        QApplication.clipboard().setText(record.raw.hex(" ").upper())
        self.pending_state.setText(
            f"已复制整个行动：{len(record.instructions)} 条，{len(record.raw)} 字节。"
        )
        self.pending_state.setStyleSheet("color: #18794e;")

    def paste_all_instructions(self) -> None:
        if self.project is None or self.current_action_id is None:
            return
        payload = type(self)._record_clipboard
        if payload is None:
            self.show_error(ValueError("请先复制一个完整行动。"))
            return
        raw, source_pointer = payload
        try:
            action_id = self.current_action_id
            self.project.replace_action_event(
                action_id,
                raw,
                source_pointer=source_pointer,
            )
        except Exception as error:
            self.show_error(error)
            return
        self.refresh()
        self._select_action(action_id)
        self._populate_instructions(0)
        self.project_changed.emit(f"已粘贴整个行动到 ${action_id:02X}")

    def clear_action(self) -> None:
        if self.project is None or self.current_action_id is None:
            return
        try:
            action_id = self.current_action_id
            self.project.replace_action_event(action_id, b"\xDF")
        except Exception as error:
            self.show_error(error)
            return
        self.refresh()
        self._select_action(action_id)
        self._populate_instructions(0)
        self.project_changed.emit(f"已清空行动 ${action_id:02X}")

    def clear_actions_below(self) -> None:
        if self.project is None or self.current_action_id is None:
            return
        action_id = self.current_action_id
        if action_id >= 0xFF:
            self.pending_state.setText("当前已经是最后一个行动，下方没有可清空的项目。")
            self.pending_state.setStyleSheet("color: #9a5b00;")
            return
        try:
            self.project.clear_action_events_below(action_id)
        except Exception as error:
            self.show_error(error)
            return
        self.refresh()
        self._select_action(action_id)
        self._populate_instructions(0)
        self.project_changed.emit(
            f"已清空行动 ${action_id + 1:02X}—$FF（保留当前行动 ${action_id:02X}）"
        )

    def _add_reinforcement(self) -> None:
        if (
            self.project is None
            or self.current_action_id is None
            or self.current_instruction_index is None
        ):
            return
        # 参考版“添加增援”进入七字节敌军增援编辑。只预置已验证的
        # 敌军增援操作码；坐标、人物、机体、等级和标志均由用户确认。
        dialog = EventParameterDialog(
            bytes.fromhex("4B 00 00 00 00 00 00"),
            self,
            title="添加增援",
            context=(
                f"行动 ${self.current_action_id:02X} · "
                "敌军增援（X、Y、人物、机体、等级、AI/标志）"
            ),
            project=self.project,
        )
        if dialog.exec() != dialog.DialogCode.Accepted:
            return
        try:
            action_id = self.current_action_id
            index = self.current_instruction_index
            self.project.insert_action_event_instruction(
                action_id,
                index,
                dialog.raw(),
                after=True,
            )
        except Exception as error:
            self.show_error(error)
            return
        self.refresh()
        self._select_action(action_id)
        self._populate_instructions(index + 1)
        self.project_changed.emit(f"已向行动 ${action_id:02X} 添加增援")

    def _reset_action(self) -> None:
        if self.project is None or self.current_action_id is None:
            return
        try:
            action_id = self.current_action_id
            self.project.reset_action_event(action_id)
        except Exception as error:
            self.show_error(error)
            return
        self.refresh()
        self.current_action_id = action_id
        self._select_action(action_id)
        self._populate_instructions(0)
        self.project_changed.emit(f"已还原行动 ${action_id:02X}")
