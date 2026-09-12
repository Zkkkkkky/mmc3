from __future__ import annotations

from dataclasses import dataclass

from PySide6.QtCore import QAbstractTableModel, QModelIndex, QSortFilterProxyModel, Qt, Signal
from PySide6.QtGui import QValidator
from PySide6.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QSpinBox,
    QTableView,
    QTableWidget,
    QTableWidgetItem,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from fc_editor.codecs.animation import AnimationCodec, TABLES
from fc_editor.codecs.character_attributes import (
    CharacterAttributesCodec,
    SPIRIT_NAMES,
    weapon_extra_values,
)
from fc_editor.codecs.legacy_scenario import LegacyScenarioCodec
from fc_editor.codecs.legacy_text import LegacyTextCodec
from .database_graphics import read_unit_appearance


@dataclass(frozen=True)
class DataSheet:
    headers: tuple[str, ...]
    rows: tuple[tuple[str, ...], ...]
    offsets: tuple[int | None, ...]

    def __post_init__(self) -> None:
        if len(self.rows) != len(self.offsets):
            raise ValueError("数据行和地址索引数量不一致。")
        if any(len(row) != len(self.headers) for row in self.rows):
            raise ValueError("结构化数据列数不一致。")


def _hex(raw: bytes) -> str:
    return raw.hex(" ").upper()


def _address(offset: int | None) -> str:
    return "—" if offset is None else f"0x{offset:06X}"


def build_unit_sheet(project) -> DataSheet:
    headers = (
        "ID", "名称", "名称指针", "属性地址", "完整16字节", "类型原码", "特技", "地图小图标首图块",
        "移动", "速度", "强度", "防御", "基础金钱", "HP", "基础经验",
        "成长 速/强/防/HP", "武器1/2", "外观地址", "完整外观10字节",
    )
    rows = []
    offsets = []
    for unit_id in range(1, project.unit_count):
        raw = project.record_bytes(unit_id)
        offset = project.record_file_offset(unit_id)
        try:
            appearance = read_unit_appearance(project, unit_id)
            appearance_offset = _address(appearance.file_offset)
            appearance_raw = _hex(appearance.configuration)
        except (ValueError, IndexError) as error:
            appearance_offset = "—"
            appearance_raw = f"读取失败：{error}"
        weapons = project.get_unit_weapons(unit_id) if project.supports_unit_weapons else ()
        rows.append((
            f"${unit_id:02X}",
            project.unit_display_name(unit_id),
            f"${project.get_unit_name_pointer(unit_id):04X}",
            _address(offset),
            _hex(raw),
            f"${raw[0]:02X}",
            f"${project.get_value(unit_id, 'special'):02X}",
            f"${raw[2]:02X}",
            str(project.get_value(unit_id, "movement")),
            str(project.get_value(unit_id, "speed")),
            str(project.get_value(unit_id, "strength")),
            str(project.get_value(unit_id, "defense")),
            str(project.get_value(unit_id, "upgrade")),
            str(project.get_value(unit_id, "hp")),
            str(project.get_value(unit_id, "experience")),
            "/".join(str(project.get_value(unit_id, key)) for key in (
                "speed_growth", "strength_growth", "defense_growth", "hp_growth"
            )),
            "/".join(f"${value:02X}" for value in weapons) if weapons else "—",
            appearance_offset,
            appearance_raw,
        ))
        offsets.append(offset)
    return DataSheet(headers, tuple(rows), tuple(offsets))


def build_character_sheet(project) -> DataSheet:
    headers = (
        "ID", "名称", "名称指针", "名称Token", "属性地址", "属性原始字节",
        "精神值", "精神成长", "五项修正 机/强/防/速/HP", "精神列表",
        "头像地址", "头像7字节", "我方/敌方BGM",
    )
    rows = []
    offsets = []
    codec = CharacterAttributesCodec(project)
    for character_id in range(1, project.profile.character_name_count):
        attributes = codec.read(character_id)
        portrait = codec.read_portrait(character_id)
        attr_offset = codec.record_offset(character_id)
        portrait_offset = codec.record_offset(character_id, portrait=True)
        spirit_names = tuple(
            name for index, name in enumerate(SPIRIT_NAMES)
            if attributes.spirit_mask & (1 << (23 - index))
        )
        if project.supports_battle_music and character_id < project.profile.battle_music.selector_count:
            binding = project.get_battle_music_binding(character_id)
            music = f"${binding.attacker_command:02X}/${binding.defender_command:02X}"
        else:
            music = "—"
        rows.append((
            f"${character_id:02X}",
            project.character_display_name(character_id),
            f"${project.get_character_name_pointer(character_id):04X}",
            _hex(project.character_name_record_bytes(character_id)),
            _address(attr_offset),
            _hex(codec.record_bytes(character_id)),
            str(attributes.spirit),
            str(attributes.growth),
            "/".join(str(value) for value in attributes.corrections),
            "、".join(spirit_names) if spirit_names else "无",
            _address(portrait_offset),
            _hex(codec.record_bytes(character_id, portrait=True)),
            music,
        ))
        offsets.append(attr_offset)
    return DataSheet(headers, tuple(rows), tuple(offsets))


def build_weapon_sheet(project) -> DataSheet:
    headers = (
        "ID", "名称", "属性地址", "完整6字节", "名称指针", "名称Token",
        "射程", "命中", "距离表", "特技", "空/陆/海攻击",
        "我方动画 地址/长度", "敌方动画 地址/长度",
    )
    rows = []
    offsets = []
    animation = AnimationCodec(project.working)
    for weapon_id in range(1, project.weapon_count):
        raw = project.weapon_record_bytes(weapon_id)
        offset = project.weapon_codec.record_offset(weapon_id)
        skill, distance = weapon_extra_values(project, weapon_id)
        name_pointer = (
            f"${project.weapon_name_codec.pointer(weapon_id, project.working):04X}"
            if project.weapon_name_codec is not None else "—"
        )
        name_raw = (
            _hex(project.weapon_name_record_bytes(weapon_id))
            if project.weapon_name_codec is not None else "—"
        )
        animation_labels = []
        for kind in ("ally", "enemy"):
            record = animation.record(kind, weapon_id)
            animation_labels.append(
                "空记录" if not record.raw else f"{_address(record.offset)}/{len(record.raw)}"
            )
        rows.append((
            f"${weapon_id:02X}",
            project.weapon_display_name(weapon_id),
            _address(offset),
            _hex(raw),
            name_pointer,
            name_raw,
            str(project.get_weapon_value(weapon_id, "max_range")),
            str(project.get_weapon_value(weapon_id, "hit")),
            str(distance),
            f"{skill:02d}",
            "/".join(str(project.get_weapon_value(weapon_id, key)) for key in (
                "power_air", "power_land", "power_sea"
            )),
            animation_labels[0],
            animation_labels[1],
        ))
        offsets.append(offset)
    return DataSheet(headers, tuple(rows), tuple(offsets))


def build_map_sheet(project) -> DataSheet:
    headers = (
        "地图ID", "地图地址", "尺寸", "地形 原长/容量", "压缩地形原始字节",
        "部署地址", "敌/客/我", "部署 原长/容量", "部署原始字节", "地图触发器",
    )
    rows = []
    offsets = []
    for map_id in range(project.map_count):
        record = project.get_map(map_id)
        offset = project.map_codec.record_offset(map_id)
        if map_id < project.scenario_count:
            layout = project.get_scenario_layout(map_id)
            layout_offset = project.scenario_layout_codec.record_offset(map_id)
            layout_counts = f"{len(layout.enemies)}/{len(layout.guests)}/{len(layout.player_placements)}"
            layout_size = f"{len(layout.raw)}/{layout.capacity}"
            layout_raw = _hex(layout.raw)
            if project.supports_map_triggers:
                triggers = project.get_map_triggers(map_id)
                pointer = project.map_trigger_codec.pointer(map_id, project.working)
                trigger_text = (
                    f"{len(triggers)} 条 · 指针 ${pointer:04X} · "
                    f"{_hex(project.map_trigger_codec.encode_entries(triggers))}"
                )
            else:
                trigger_text = "—"
        else:
            layout_offset = None
            layout_counts = layout_size = layout_raw = trigger_text = "—"
        rows.append((
            f"${map_id:02X}",
            _address(offset),
            f"{record.width}×{record.height}",
            f"{len(record.raw)}/{record.capacity}",
            _hex(record.raw),
            _address(layout_offset),
            layout_counts,
            layout_size,
            layout_raw,
            trigger_text,
        ))
        offsets.append(offset)
    return DataSheet(headers, tuple(rows), tuple(offsets))


def build_text_sheet(project) -> DataSheet:
    headers = ("分组", "编号", "分支", "地址", "指针", "字节数", "原始Token", "解码正文", "共享项")
    rows = []
    offsets = []
    codec = LegacyTextCodec(project.working)
    for group in codec.groups:
        for index in range(group.count):
            for variant in range(codec.variant_count(group.key, index)):
                record = codec.record(group.key, index, variant)
                rows.append((
                    group.label,
                    f"{index:03d}",
                    str(variant),
                    _address(record.file_offset),
                    f"${record.pointer:04X}",
                    str(len(record.raw)),
                    _hex(record.raw),
                    record.text,
                    "、".join(f"{row}:{sub}" for row, sub in record.shared_by),
                ))
                offsets.append(record.file_offset)
    return DataSheet(headers, tuple(rows), tuple(offsets))


def build_animation_sheet(project) -> DataSheet:
    headers = ("类别", "编号", "地址", "长度", "完整解码", "共享编号", "原始字节", "指令摘要")
    rows = []
    offsets = []
    codec = AnimationCodec(project.working)
    for table in TABLES:
        for index in range(codec.count(table.kind)):
            record = codec.record(table.kind, index)
            rows.append((
                table.kind,
                f"${index:02X}",
                _address(record.offset if record.raw else None),
                str(len(record.raw)),
                "是" if record.complete else "否",
                "、".join(f"${value:02X}" for value in record.aliases) or "—",
                _hex(record.raw),
                "；".join(instruction.text for instruction in record.instructions),
            ))
            offsets.append(record.offset if record.raw else None)
    return DataSheet(headers, tuple(rows), tuple(offsets))


def build_event_sheet(project) -> DataSheet:
    headers = (
        "来源", "Bank/地址", "文件偏移", "关卡/阶段", "操作", "参数",
        "原始字节", "结束本组",
    )
    rows = []
    offsets = []
    for instruction in project.chapter_event_instructions():
        contexts = "、".join(
            f"{context.scenario_id + 1:02d}/{context.phase + 1}" for context in instruction.contexts
        )
        rows.append((
            "行动事件表",
            f"${project.chapter_event_codec.spec.data_prg_bank:02X}/${instruction.address:04X}",
            _address(instruction.file_offset),
            contexts,
            instruction.action_label,
            " ".join(f"${value:02X}" for value in instruction.parameters),
            _hex(instruction.raw),
            "是" if instruction.is_terminal else "否",
        ))
        offsets.append(instruction.file_offset)
    legacy = LegacyScenarioCodec(project.working)
    for scenario_id in range(32):
        for phase in range(3):
            for instruction in legacy.instructions(scenario_id, phase):
                rows.append((
                    "分Bank关卡脚本",
                    f"${instruction.bank:02X}/${instruction.address:04X}",
                    _address(instruction.file_offset),
                    f"{scenario_id + 1:02d}/{phase + 1} {legacy.PHASE_LABELS[phase]}",
                    instruction.label,
                    " ".join(f"${value:02X}" for value in instruction.raw[1:]),
                    _hex(instruction.raw),
                    "是" if instruction.raw[0] & 0x80 else "否",
                ))
                offsets.append(instruction.file_offset)
    return DataSheet(headers, tuple(rows), tuple(offsets))


class DataSheetModel(QAbstractTableModel):
    def __init__(self, sheet: DataSheet, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.sheet = sheet

    def rowCount(self, parent: QModelIndex = QModelIndex()) -> int:  # noqa: N802
        return 0 if parent.isValid() else len(self.sheet.rows)

    def columnCount(self, parent: QModelIndex = QModelIndex()) -> int:  # noqa: N802
        return 0 if parent.isValid() else len(self.sheet.headers)

    def data(self, index: QModelIndex, role: int = Qt.ItemDataRole.DisplayRole):
        if not index.isValid():
            return None
        if role in (Qt.ItemDataRole.DisplayRole, Qt.ItemDataRole.ToolTipRole):
            return self.sheet.rows[index.row()][index.column()]
        if role == Qt.ItemDataRole.UserRole:
            return self.sheet.offsets[index.row()]
        return None

    def headerData(self, section: int, orientation: Qt.Orientation, role: int = Qt.ItemDataRole.DisplayRole):  # noqa: N802
        if role != Qt.ItemDataRole.DisplayRole:
            return None
        if orientation == Qt.Orientation.Horizontal:
            return self.sheet.headers[section]
        return str(section + 1)


class DataSheetPage(QWidget):
    offset_requested = Signal(int)

    def __init__(self, sheet: DataSheet, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        layout = QVBoxLayout(self)
        toolbar = QHBoxLayout()
        search = QLineEdit()
        search.setClearButtonEnabled(True)
        search.setPlaceholderText("筛选当前表的名称、编号、地址、正文或原始字节…")
        status = QLabel(f"已读取 {len(sheet.rows)} 条记录；双击任意行可跳到完整 HEX。")
        toolbar.addWidget(search, 1)
        toolbar.addWidget(status)
        layout.addLayout(toolbar)
        self.table = QTableView()
        self.model = DataSheetModel(sheet, self)
        self.proxy = QSortFilterProxyModel(self)
        self.proxy.setSourceModel(self.model)
        self.proxy.setFilterCaseSensitivity(Qt.CaseSensitivity.CaseInsensitive)
        self.proxy.setFilterKeyColumn(-1)
        self.table.setModel(self.proxy)
        self.table.setSortingEnabled(True)
        self.table.sortByColumn(0, Qt.SortOrder.AscendingOrder)
        self.table.setAlternatingRowColors(True)
        self.table.setSelectionBehavior(QTableView.SelectionBehavior.SelectRows)
        self.table.setEditTriggers(QTableView.EditTrigger.NoEditTriggers)
        self.table.horizontalHeader().setStretchLastSection(True)
        self.table.doubleClicked.connect(self._open_offset)
        search.textChanged.connect(self.proxy.setFilterFixedString)
        layout.addWidget(self.table, 1)

    def _open_offset(self, index: QModelIndex) -> None:
        source = self.proxy.mapToSource(index)
        offset = self.model.sheet.offsets[source.row()]
        if offset is not None:
            self.offset_requested.emit(offset)


class HexOffsetSpinBox(QSpinBox):
    def textFromValue(self, value: int) -> str:  # noqa: N802
        return f"0x{value:06X}"

    def valueFromText(self, text: str) -> int:  # noqa: N802
        value = text.strip().lower()
        return int(value, 16) if value.startswith("0x") else int(value)

    def validate(self, text: str, position: int):  # noqa: N802
        value = text.strip().lower()
        if value in ("", "0x"):
            return QValidator.State.Intermediate, text, position
        try:
            parsed = int(value, 16) if value.startswith("0x") else int(value)
        except ValueError:
            return QValidator.State.Invalid, text, position
        state = (
            QValidator.State.Acceptable
            if self.minimum() <= parsed <= self.maximum()
            else QValidator.State.Invalid
        )
        return state, text, position


class RomHexPage(QWidget):
    PAGE_SIZE = 0x100

    def __init__(self, project, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.project = project
        self.data = bytes(project.working)
        self._loading = False
        layout = QVBoxLayout(self)
        toolbar = QHBoxLayout()
        toolbar.addWidget(QLabel("文件偏移："))
        self.offset = HexOffsetSpinBox()
        self.offset.setRange(0, max(0, len(self.data) - 1))
        self.offset.setSingleStep(self.PAGE_SIZE)
        self.offset.valueChanged.connect(self._load_page)
        toolbar.addWidget(self.offset)
        toolbar.addWidget(QLabel("每页固定显示 0x100 字节；可输入十进制或 0x 十六进制地址。"))
        toolbar.addStretch()
        layout.addLayout(toolbar)
        self.table = QTableWidget(16, 16)
        self.table.setHorizontalHeaderLabels(tuple(f"{value:X}" for value in range(16)))
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.table.setSelectionMode(QTableWidget.SelectionMode.SingleSelection)
        self.table.currentCellChanged.connect(self._selected)
        self.table.horizontalHeader().setDefaultSectionSize(48)
        self.table.verticalHeader().setDefaultSectionSize(28)
        layout.addWidget(self.table, 1)
        self.detail = QLabel()
        self.detail.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        layout.addWidget(self.detail)
        self._load_page()

    def go_to(self, offset: int) -> None:
        offset = max(0, min(offset, len(self.data) - 1))
        page = offset & ~(self.PAGE_SIZE - 1)
        self.offset.setValue(page)
        relative = offset - page
        self.table.setCurrentCell(relative // 16, relative % 16)

    def _load_page(self, *_args) -> None:
        if self._loading:
            return
        self._loading = True
        page = self.offset.value() & ~(self.PAGE_SIZE - 1)
        if page != self.offset.value():
            self.offset.setValue(page)
        for row in range(16):
            self.table.setVerticalHeaderItem(row, QTableWidgetItem(f"{page + row * 16:06X}"))
            for column in range(16):
                offset = page + row * 16 + column
                item = self.table.item(row, column) or QTableWidgetItem()
                item.setText(f"{self.data[offset]:02X}" if offset < len(self.data) else "")
                item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                item.setToolTip(self._describe(offset) if offset < len(self.data) else "ROM 末尾之外")
                self.table.setItem(row, column, item)
        self._loading = False
        self.table.setCurrentCell(0, 0)
        self._selected(0, 0)

    def _selected(self, row: int, column: int, *_args) -> None:
        offset = (self.offset.value() & ~(self.PAGE_SIZE - 1)) + row * 16 + column
        if 0 <= offset < len(self.data):
            self.detail.setText(self._describe(offset))

    def _describe(self, offset: int) -> str:
        value = self.data[offset]
        if offset < 16:
            region = f"iNES 文件头 +0x{offset:X}"
        else:
            prg_size = self.data[4] * 0x4000
            chr_start = 16 + prg_size
            if offset < chr_start:
                relative = offset - 16
                region = f"PRG 8 KiB Bank ${relative // 0x2000:02X} + ${relative % 0x2000:04X}"
            else:
                relative = offset - chr_start
                region = (
                    f"CHR 1 KiB Bank ${relative // 0x400:02X} + ${relative % 0x400:03X}"
                    f" · 图块 ${relative // 16:04X}"
                )
        return f"文件偏移 0x{offset:06X} · 值 ${value:02X}（{value}） · {region}"


class RomDataBrowserDialog(QDialog):
    """Read every ROM byte and index all structures already verified by the editor."""

    def __init__(self, project, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.project = project
        self.setWindowTitle("完整 ROM 数据读取")
        self.resize(1280, 820)
        self.setMinimumSize(900, 600)
        layout = QVBoxLayout(self)
        self.summary = QLabel(
            f"已读取当前工程内存镜像 {len(project.working):,} 字节。"
            "结构化页列出修改器已验证的全部记录；完整 HEX 页可查看其余任何字节。"
        )
        self.summary.setWordWrap(True)
        layout.addWidget(self.summary)
        self.tabs = QTabWidget()
        layout.addWidget(self.tabs, 1)
        sheets = (
            ("机体", build_unit_sheet(project)),
            ("人物", build_character_sheet(project)),
            ("武器", build_weapon_sheet(project)),
            ("地图与部署", build_map_sheet(project)),
            ("文字", build_text_sheet(project)),
            ("动画", build_animation_sheet(project)),
            ("关卡事件", build_event_sheet(project)),
        )
        self.sheet_pages: list[DataSheetPage] = []
        for label, sheet in sheets:
            page = DataSheetPage(sheet)
            page.offset_requested.connect(self.show_offset)
            self.sheet_pages.append(page)
            self.tabs.addTab(page, f"{label}（{len(sheet.rows)}）")
        self.hex_page = RomHexPage(project)
        self.tabs.addTab(self.hex_page, "完整 HEX")
        close_button = QPushButton("关闭")
        close_button.clicked.connect(self.accept)
        layout.addWidget(close_button, 0, Qt.AlignmentFlag.AlignRight)

    def show_offset(self, offset: int) -> None:
        self.tabs.setCurrentWidget(self.hex_page)
        self.hex_page.go_to(offset)
