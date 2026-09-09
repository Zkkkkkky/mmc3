from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

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
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPlainTextEdit,
    QProgressBar,
    QPushButton,
    QScrollArea,
    QSpinBox,
    QSplitter,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from fc_editor.models import UNIT_FIELDS, WEAPON_FIELDS
from fc_editor.resources import ResourceGraph
from fc_rom_editor_core import RomProject, compact_ids

from .music_import import assemble_famistudio_music_source, load_music_bank


def page_title(title: str, subtitle: str) -> tuple[QLabel, QLabel]:
    heading = QLabel(title)
    heading.setObjectName("pageTitle")
    description = QLabel(subtitle)
    description.setObjectName("pageSubtitle")
    description.setWordWrap(True)
    return heading, description


def readonly_item(text: str) -> QTableWidgetItem:
    item = QTableWidgetItem(text)
    item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEditable)
    return item


class ProjectPage(QWidget):
    project_changed = Signal(str)

    def __init__(self) -> None:
        super().__init__()
        self.project: RomProject | None = None

    def set_project(self, project: RomProject | None) -> None:
        self.project = project
        self.refresh()

    def refresh(self) -> None:
        pass

    def show_error(self, error: Exception) -> None:
        QMessageBox.critical(self, "操作失败", str(error))


class OverviewPage(ProjectPage):
    def __init__(self) -> None:
        super().__init__()
        layout = QVBoxLayout(self)
        title, subtitle = page_title(
            "工程概览",
            "先确认基准ROM身份，再从左侧选择要修改的资源。所有输出都使用“另存为”。",
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
                "1. 打开 DC_kuorong.nes　→　2. 修改并随时验证　→　"
                "3. 保存 .dcmod 工程　→　4. 构建新ROM与IPS"
            )
        )
        safety = QLabel(
            "安全规则：不会覆盖当前载入的基准ROM；音频引擎、固定银行和CHR区域由构建检查保护。"
        )
        safety.setWordWrap(True)
        safety.setObjectName("hintText")
        guide_layout.addWidget(safety)
        layout.addWidget(guide)
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
        self.space_value.setText(f"{self.project.expansion_capacity // 1024} KiB（Bank $65—$7D）")


class SearchableRecordPage(ProjectPage):
    def __init__(self) -> None:
        super().__init__()
        self.current_id: int | None = None
        self.search = QLineEdit()
        self.search.setClearButtonEnabled(True)
        self.search.setPlaceholderText("输入名称、十进制或十六进制ID…")
        self.search.textChanged.connect(self._filter_records)
        self.records = QListWidget()
        self.records.setAlternatingRowColors(True)
        self.records.currentItemChanged.connect(self._selection_changed)

    def record_text(self, record_id: int) -> str:
        return f"${record_id:02X}"

    def record_ids(self) -> range:
        return range(0)

    def populate_records(self) -> None:
        previous = self.current_id
        self.records.blockSignals(True)
        self.records.clear()
        if self.project is not None:
            for record_id in self.record_ids():
                item = QListWidgetItem(self.record_text(record_id))
                item.setData(Qt.ItemDataRole.UserRole, record_id)
                self.records.addItem(item)
        self.records.blockSignals(False)
        self._filter_records(self.search.text())
        if self.records.count():
            row = 0
            if previous is not None:
                for index in range(self.records.count()):
                    if self.records.item(index).data(Qt.ItemDataRole.UserRole) == previous:
                        row = index
                        break
            self.records.setCurrentRow(row)
            self._selection_changed(self.records.currentItem(), None)
        else:
            self.current_id = None
            self.load_record(None)

    def _filter_records(self, text: str) -> None:
        query = text.strip().lower()
        for index in range(self.records.count()):
            item = self.records.item(index)
            record_id = int(item.data(Qt.ItemDataRole.UserRole))
            decimal = str(record_id)
            hexadecimal = f"{record_id:02x}"
            visible = not query or query in item.text().lower() or query in (decimal, hexadecimal)
            item.setHidden(not visible)

    def _selection_changed(
        self,
        current: QListWidgetItem | None,
        _previous: QListWidgetItem | None,
    ) -> None:
        self.current_id = (
            int(current.data(Qt.ItemDataRole.UserRole)) if current is not None else None
        )
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
        left_layout.addWidget(self.search)
        left_layout.addWidget(self.records)
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

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        form_host = QWidget()
        form = QFormLayout(form_host)
        self.fields: dict[str, QSpinBox] = {}
        for field in UNIT_FIELDS:
            editor = QSpinBox()
            editor.setRange(field.minimum, field.maximum)
            editor.setToolTip(field.description)
            self.fields[field.key] = editor
            form.addRow(field.label, editor)
        self.name_reference = QComboBox()
        self.name_reference.setMaxVisibleItems(20)
        form.addRow("名称引用", self.name_reference)
        self.weapon_slots = (QComboBox(), QComboBox())
        for slot, editor in enumerate(self.weapon_slots, 1):
            editor.setMaxVisibleItems(24)
            form.addRow(f"武器槽 {slot}", editor)
        scroll.setWidget(form_host)
        detail_layout.addWidget(scroll, 1)

        buttons = QHBoxLayout()
        apply_button = QPushButton("应用修改")
        apply_button.setObjectName("primaryButton")
        apply_button.clicked.connect(self.apply_record)
        reset_button = QPushButton("还原此机体")
        reset_button.clicked.connect(self.reset_record)
        buttons.addWidget(apply_button)
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
        source_ids = self.project.unit_name_source_ids(record_id)
        if source_ids:
            index = self.name_reference.findData(source_ids[0])
            self.name_reference.setCurrentIndex(index)
        if self.project.supports_unit_weapons:
            for editor, weapon_id in zip(
                self.weapon_slots, self.project.get_unit_weapons(record_id)
            ):
                editor.setCurrentIndex(editor.findData(weapon_id))
        self.raw_record.setText(record.raw.hex(" ").upper())

    def apply_record(self) -> None:
        if self.project is None or self.current_id is None:
            return
        try:
            with self.project.transaction(f"机体 ${self.current_id:02X} · 批量属性"):
                for field in UNIT_FIELDS:
                    self.project.set_value(
                        self.current_id,
                        field.key,
                        self.fields[field.key].value(),
                    )
                source_id = int(self.name_reference.currentData())
                self.project.set_unit_name_reference(self.current_id, source_id)
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
        left_layout.addWidget(self.search)
        left_layout.addWidget(self.records)
        splitter.addWidget(left)

        detail = QWidget()
        detail_layout = QVBoxLayout(detail)
        self.record_heading = QLabel("请选择武器")
        self.record_heading.setObjectName("sectionTitle")
        self.record_meta = QLabel("—")
        self.record_meta.setObjectName("hintText")
        detail_layout.addWidget(self.record_heading)
        detail_layout.addWidget(self.record_meta)
        form = QFormLayout()
        self.name_reference = QComboBox()
        self.name_reference.setMaxVisibleItems(24)
        form.addRow("名称引用", self.name_reference)
        self.name_tokens = QLineEdit()
        self.name_tokens.setReadOnly(True)
        form.addRow("名称Token", self.name_tokens)
        self.fields: dict[str, QSpinBox] = {}
        for field in WEAPON_FIELDS:
            editor = QSpinBox()
            editor.setRange(field.minimum, field.maximum)
            editor.setToolTip(field.description)
            self.fields[field.key] = editor
            form.addRow(field.label, editor)
        detail_layout.addLayout(form)
        self.raw_record = QLineEdit()
        self.raw_record.setReadOnly(True)
        form.addRow("原始6字节", self.raw_record)
        buttons = QHBoxLayout()
        apply_button = QPushButton("应用修改")
        apply_button.setObjectName("primaryButton")
        apply_button.clicked.connect(self.apply_record)
        reset_button = QPushButton("还原此武器")
        reset_button.clicked.connect(self.reset_record)
        buttons.addWidget(apply_button)
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
            self.raw_record.clear()
            self.name_tokens.clear()
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
        else:
            metadata += " · 此ROM配置未验证名称表"
            self.name_tokens.clear()
        self.record_meta.setText(metadata)
        for field in WEAPON_FIELDS:
            self.fields[field.key].setValue(record.get(field.key))
        self.raw_record.setText(record.raw.hex(" ").upper())

    def apply_record(self) -> None:
        if self.project is None or self.current_id is None:
            return
        try:
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
        left_layout.addWidget(self.search)
        left_layout.addWidget(self.records)
        splitter.addWidget(left)
        detail = QWidget()
        detail_layout = QVBoxLayout(detail)
        self.record_heading = QLabel("请选择音乐选择器")
        self.record_heading.setObjectName("sectionTitle")
        detail_layout.addWidget(self.record_heading)
        form = QFormLayout()
        self.attacker = QComboBox()
        self.defender = QComboBox()
        form.addRow("主动攻击曲", self.attacker)
        form.addRow("被攻击曲", self.defender)
        detail_layout.addLayout(form)
        hint = QLabel("提示：$9D Ash to Ash、$9E Dark Knight、$9F Dark Prison。")
        hint.setObjectName("hintText")
        detail_layout.addWidget(hint)
        buttons = QHBoxLayout()
        apply_button = QPushButton("应用绑定")
        apply_button.setObjectName("primaryButton")
        apply_button.clicked.connect(self.apply_record)
        reset_button = QPushButton("还原此绑定")
        reset_button.clicked.connect(self.reset_record)
        buttons.addWidget(apply_button)
        buttons.addWidget(reset_button)
        buttons.addStretch()
        detail_layout.addLayout(buttons)

        import_group = QGroupBox("三首扩展曲的数据导入")
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
        detail_layout.addWidget(import_group)
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
            str(self.project.path.with_name(f"music_{command:02X}.bin")),
            "8 KiB Bank (*.bin)",
        )
        if not filename:
            return
        try:
            destination = Path(filename)
            if destination.suffix.lower() != ".bin":
                destination = destination.with_suffix(".bin")
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
            return
        binding = self.project.get_battle_music_binding(record_id)
        self.record_heading.setText(
            f"选择器 ${record_id:02X} · "
            f"{self.project.battle_music_selector_label(record_id)}"
        )
        self.attacker.setCurrentIndex(self.attacker.findData(binding.attacker_command))
        self.defender.setCurrentIndex(self.defender.findData(binding.defender_command))

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
        layout = QVBoxLayout(self)
        title, subtitle = page_title(
            "ROM资源占用",
            "查看关键表、受保护银行、扩展资源区和活动CHR。导入资源时将使用同一分配表。",
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

    def refresh(self) -> None:
        self.table.setRowCount(0)
        if self.project is None:
            self.capacity_label.setText("尚未载入ROM")
            self.capacity.setFormat("0 / 0 KiB")
            return
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
        capacity = self.project.expansion_capacity // 1024
        self.capacity_label.setText(f"扩展资源区：可用 {capacity} KiB")
        self.capacity.setValue(0)
        self.capacity.setFormat(f"已分配 0 KiB / {capacity} KiB")


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
