from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QComboBox,
    QCheckBox,
    QFileDialog,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QSpinBox,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from fc_editor.unit_package import UnitPackage

from .pages import ProjectPage, page_title
from .chr_widget import ChrGraphicsWidget
from .unit_packages import affected_unit_ids, apply_unit_package, package_from_project


class UnitImportPage(ProjectPage):
    def __init__(self) -> None:
        super().__init__()
        self.loaded_package: UnitPackage | None = None

        layout = QVBoxLayout(self)
        title, subtitle = page_title(
            "机体导入与复制",
            "用 .dcunit 文件交换完整的机体数值记录和名称引用；写入前会显示共享记录影响范围。",
        )
        layout.addWidget(title)
        layout.addWidget(subtitle)

        self.tabs = QTabWidget()
        package_tab = QWidget()
        package_root = QVBoxLayout(package_tab)
        self.graphics = ChrGraphicsWidget()
        self.graphics.project_changed.connect(self.project_changed.emit)
        self.tabs.addTab(package_tab, "机体包")
        self.tabs.addTab(self.graphics, "CHR图像")
        layout.addWidget(self.tabs, 1)

        source_group = QGroupBox("1. 选择来源机体")
        source_layout = QHBoxLayout(source_group)
        self.source_unit = QComboBox()
        self.source_unit.setMaxVisibleItems(24)
        export_button = QPushButton("导出 .dcunit…")
        export_button.clicked.connect(self.export_package)
        use_button = QPushButton("作为待导入机体")
        use_button.clicked.connect(self.use_selected_unit)
        source_layout.addWidget(self.source_unit, 1)
        source_layout.addWidget(export_button)
        source_layout.addWidget(use_button)
        package_root.addWidget(source_group)

        chr_group = QGroupBox("可选：随包携带连续CHR图块")
        chr_layout = QHBoxLayout(chr_group)
        self.include_chr = QCheckBox("包含")
        self.chr_first_tile = QSpinBox()
        self.chr_first_tile.setDisplayIntegerBase(16)
        self.chr_first_tile.setPrefix("$")
        self.chr_tile_count = QSpinBox()
        self.chr_tile_count.setRange(1, 256)
        self.chr_tile_count.setValue(16)
        chr_layout.addWidget(self.include_chr)
        chr_layout.addWidget(QLabel("起点"))
        chr_layout.addWidget(self.chr_first_tile)
        chr_layout.addWidget(QLabel("数量"))
        chr_layout.addWidget(self.chr_tile_count)
        chr_layout.addStretch()
        package_root.addWidget(chr_group)

        package_group = QGroupBox("2. 载入机体包")
        package_layout = QVBoxLayout(package_group)
        package_actions = QHBoxLayout()
        open_button = QPushButton("打开 .dcunit…")
        open_button.clicked.connect(self.open_package)
        clear_button = QPushButton("清除")
        clear_button.clicked.connect(self.clear_package)
        package_actions.addWidget(open_button)
        package_actions.addWidget(clear_button)
        package_actions.addStretch()
        self.package_summary = QLabel("尚未载入机体包。也可点击“作为待导入机体”直接复制。")
        self.package_summary.setObjectName("emptyState")
        self.package_summary.setWordWrap(True)
        self.package_summary.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextSelectableByMouse
        )
        package_layout.addLayout(package_actions)
        package_layout.addWidget(self.package_summary)
        package_root.addWidget(package_group)

        target_group = QGroupBox("3. 预览影响并写入")
        target_layout = QVBoxLayout(target_group)
        target_row = QHBoxLayout()
        self.target_unit = QComboBox()
        self.target_unit.setMaxVisibleItems(24)
        self.target_unit.currentIndexChanged.connect(self._refresh_impact)
        apply_button = QPushButton("覆盖目标机体")
        apply_button.setObjectName("primaryButton")
        apply_button.clicked.connect(self.apply_loaded_package)
        target_row.addWidget(QLabel("目标 ID"))
        target_row.addWidget(self.target_unit, 1)
        target_row.addWidget(apply_button)
        self.impact = QLabel("尚未载入ROM。")
        self.impact.setObjectName("hintText")
        self.impact.setWordWrap(True)
        target_layout.addLayout(target_row)
        target_layout.addWidget(self.impact)
        package_root.addWidget(target_group)

        scope = QLabel(
            "当前可完整迁移：16字节机体记录、原生名称引用。"
            "地图图标、战斗图、调色板与动画已经预留包内资源槽，但必须等对应指针格式验证后才允许写入。"
        )
        scope.setObjectName("hintText")
        scope.setWordWrap(True)
        package_root.addWidget(scope)
        package_root.addStretch()

    def refresh(self) -> None:
        source_value = self.source_unit.currentData()
        target_value = self.target_unit.currentData()
        for combo in (self.source_unit, self.target_unit):
            combo.blockSignals(True)
            combo.clear()
            if self.project is not None:
                for unit_id in range(1, self.project.unit_count):
                    combo.addItem(
                        f"${unit_id:02X} · {self.project.unit_display_name(unit_id)}",
                        unit_id,
                    )
            combo.blockSignals(False)
        self._restore_combo(self.source_unit, source_value)
        self._restore_combo(self.target_unit, target_value)
        if self.project is not None:
            self.chr_first_tile.setRange(0, self.project.chr_tile_count - 1)
        self._refresh_impact()
        self.graphics.set_project(self.project)

    @staticmethod
    def _restore_combo(combo: QComboBox, value: object) -> None:
        index = combo.findData(value)
        combo.setCurrentIndex(index if index >= 0 else (0 if combo.count() else -1))

    def _selected_id(self, combo: QComboBox) -> int:
        value = combo.currentData()
        if value is None:
            raise ValueError("请先选择机体ID。")
        return int(value)

    def _refresh_impact(self) -> None:
        if self.project is None or self.target_unit.currentData() is None:
            self.impact.setText("尚未载入ROM。")
            return
        target_id = self._selected_id(self.target_unit)
        affected = affected_unit_ids(self.project, target_id)
        ids = "、".join(f"${unit_id:02X}" for unit_id in affected)
        if len(affected) > 1:
            self.impact.setText(
                f"警告：目标 ${target_id:02X} 的16字节记录由 {ids} 共用；"
                "覆盖数值会同时影响这些ID。名称引用只修改目标ID。"
            )
        else:
            self.impact.setText(
                f"目标 ${target_id:02X} 使用独立记录；名称与数值均只影响该ID。"
            )

    def use_selected_unit(self) -> None:
        if self.project is None:
            return
        try:
            self.set_loaded_package(
                self._package_from_selected_unit()
            )
        except Exception as error:
            self.show_error(error)

    def set_loaded_package(self, package: UnitPackage | None) -> None:
        self.loaded_package = package
        if package is None:
            self.package_summary.setText(
                "尚未载入机体包。也可点击“作为待导入机体”直接复制。"
            )
            return
        asset_text = (
            "无附加资源"
            if not package.assets
            else "、".join(self._asset_summary(asset) for asset in package.assets)
        )
        name_text = (
            "无"
            if package.name_source_id is None
            else f"${package.name_source_id:02X}"
        )
        self.package_summary.setText(
            f"{package.label}\n"
            f"来源配置：{package.source_profile}　来源机体：${package.source_unit_id:02X}\n"
            f"名称引用：{name_text}　16字节记录：{package.unit_record.hex(' ').upper()}\n"
            f"附加资源：{asset_text}"
        )

    @staticmethod
    def _asset_summary(asset) -> str:
        metadata = asset.metadata_map
        if asset.kind == "chr_tiles":
            first_tile = metadata.get("firstTile", "?")
            tile_count = metadata.get("tileCount", "?")
            start = f"${first_tile:04X}" if isinstance(first_tile, int) else str(first_tile)
            return f"CHR {start} 起共 {tile_count} 块（{len(asset.data)}字节）"
        return f"{asset.kind}:{asset.filename}"

    def _package_from_selected_unit(self) -> UnitPackage:
        assert self.project is not None
        ranges: tuple[tuple[int, int], ...] = ()
        if self.include_chr.isChecked():
            first_tile = self.chr_first_tile.value()
            tile_count = self.chr_tile_count.value()
            if first_tile + tile_count > self.project.chr_tile_count:
                raise ValueError("随包携带的CHR范围超出有效CHR-ROM。")
            ranges = ((first_tile, tile_count),)
        return package_from_project(
            self.project,
            self._selected_id(self.source_unit),
            chr_ranges=ranges,
        )

    def clear_package(self) -> None:
        self.set_loaded_package(None)

    def export_package(self) -> None:
        if self.project is None:
            return
        try:
            unit_id = self._selected_id(self.source_unit)
            package = self._package_from_selected_unit()
            default = self.project.path.with_name(f"unit_{unit_id:02X}.dcunit")
            filename, _ = QFileDialog.getSaveFileName(
                self,
                "导出机体包",
                str(default),
                "新DC机体包 (*.dcunit)",
            )
            if not filename:
                return
            destination = Path(filename)
            if destination.suffix.lower() != ".dcunit":
                destination = destination.with_suffix(".dcunit")
            package.save(destination)
            self.set_loaded_package(package)
            self.project_changed.emit(f"机体包已导出：{destination.name}")
        except Exception as error:
            self.show_error(error)

    def open_package(self) -> None:
        start = self.project.path.parent if self.project is not None else Path.cwd()
        filename, _ = QFileDialog.getOpenFileName(
            self,
            "打开机体包",
            str(start),
            "新DC机体包 (*.dcunit);;所有文件 (*)",
        )
        if not filename:
            return
        try:
            self.set_loaded_package(UnitPackage.load(filename))
        except Exception as error:
            self.show_error(error)

    def apply_loaded_package(self) -> None:
        if self.project is None:
            return
        if self.loaded_package is None:
            self.show_error(ValueError("请先载入或选择一个待导入机体。"))
            return
        try:
            target_id = self._selected_id(self.target_unit)
            affected = affected_unit_ids(self.project, target_id)
            ids = "、".join(f"${unit_id:02X}" for unit_id in affected)
            question = (
                f"将“{self.loaded_package.label}”覆盖到机体 ${target_id:02X}。\n\n"
                f"数值记录影响：{ids}\n名称引用影响：${target_id:02X}\n\n"
                f"附加资源：{len(self.loaded_package.assets)} 项\n\n"
                "所有内容会作为一个事务写入并可一次撤销。是否继续？"
            )
            answer = QMessageBox.question(self, "确认导入机体", question)
            if answer != QMessageBox.StandardButton.Yes:
                return
            apply_unit_package(self.project, self.loaded_package, target_id)
            self.project_changed.emit(
                f"已将机体包覆盖到 ${target_id:02X}（影响 {ids}）"
            )
        except Exception as error:
            self.show_error(error)
