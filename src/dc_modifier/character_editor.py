from __future__ import annotations

from PySide6.QtCore import Signal
from PySide6.QtGui import QImage, QPixmap
from PySide6.QtWidgets import (
    QCheckBox, QFileDialog, QFormLayout, QGridLayout, QGroupBox, QHBoxLayout,
    QLabel, QMessageBox, QPushButton, QSpinBox, QTabWidget, QVBoxLayout, QWidget,
)

from fc_editor.codecs.character_attributes import (
    CharacterAttributes, CharacterAttributesCodec, PortraitRecord, SPIRIT_NAMES,
    apply_verified_patches,
)
from .database_graphics import palette_color


class CharacterDetailsWidget(QWidget):
    changed = Signal()

    def __init__(self) -> None:
        super().__init__()
        self.project = None
        self.character_id = None
        self.codec = None
        self._loading = False
        self._baseline = None
        self._image_drafts: dict[str, tuple[int, bytes]] = {}
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        self.status = QLabel()
        self.status.setWordWrap(True)
        outer.addWidget(self.status)
        tabs = QTabWidget()
        outer.addWidget(tabs)
        attributes_page = QWidget()
        attributes_row = QHBoxLayout(attributes_page)
        attributes_row.setContentsMargins(4, 4, 4, 4)
        tabs.addTab(attributes_page, "人物属性与精神")

        attributes = QGroupBox("人物属性")
        grid = QGridLayout(attributes)
        self.fields = {}
        specs = (("spirit", "精神值", 255), ("growth", "精神成长", 250),
                 ("strength", "强度补正", 255), ("movement", "机动补正", 127),
                 ("defense", "防御补正", 255), ("hp", "HP补正", 255),
                 ("speed", "速度补正", 255))
        for index, (key, label, maximum) in enumerate(specs):
            spin = QSpinBox()
            spin.setRange(0, maximum)
            spin.setMaximumWidth(70)
            spin.setObjectName(f"character_{key}")
            spin.valueChanged.connect(self._changed)
            self.fields[key] = spin
            grid.addWidget(QLabel(label), index // 2, index % 2 * 2)
            grid.addWidget(spin, index // 2, index % 2 * 2 + 1)
        self.fields["growth"].setToolTip("0—200：每级固定增长；201—250：使用第 0—49 号成长曲线。")
        self.survive = QCheckBox("击落不消失")
        self.survive.toggled.connect(self._changed)
        grid.addWidget(self.survive, 3, 2, 1, 2)
        self.shared_attributes = QCheckBox("同时修改共用属性记录")
        self.shared_attributes.toggled.connect(self._changed)
        grid.addWidget(self.shared_attributes, 4, 0, 1, 4)
        self.attribute_sharing = QLabel()
        self.attribute_sharing.setWordWrap(True)
        grid.addWidget(self.attribute_sharing, 5, 0, 1, 4)
        attributes_row.addWidget(attributes, 1)

        spirits = QGroupBox("精神列表与消耗")
        grid = QGridLayout(spirits)
        self.spirits = []
        self.costs = []
        for index, name in enumerate(SPIRIT_NAMES):
            check = QCheckBox(name)
            check.setObjectName(f"character_spirit_{index}")
            cost = QSpinBox()
            cost.setRange(0, 255)
            cost.setMaximumWidth(62)
            cost.setObjectName(f"spirit_cost_{index}")
            check.toggled.connect(self._changed)
            cost.valueChanged.connect(self._changed)
            row, col = index % 8, index // 8 * 2
            grid.addWidget(check, row, col)
            grid.addWidget(cost, row, col + 1)
            self.spirits.append(check)
            self.costs.append(cost)
        hint = QLabel("消耗值全人物共用；游戏精神菜单最多显示 6 项，按列表顺序取前 6 项。")
        hint.setWordWrap(True)
        grid.addWidget(hint, 8, 0, 1, 6)
        attributes_row.addWidget(spirits, 2)

        portrait = QGroupBox("头像设置")
        form = QFormLayout(portrait)
        portrait_controls = QWidget()
        portrait_grid = QGridLayout(portrait_controls)
        portrait_grid.setContentsMargins(0, 0, 0, 0)
        self.portrait_fields = {}
        for index, (key, label, minimum, maximum) in enumerate((
            ("front_bank", "正面图库", 0, 255), ("front_slot", "正面位置", 1, 4),
            ("back_bank", "背景图库寄存器", 0, 255), ("back_slot", "背景位置（2KB内）", 1, 8),
            ("color0", "头像颜色1", 0, 63), ("color1", "头像颜色2", 0, 63),
            ("color2", "头像颜色3", 0, 63),
        )):
            spin = QSpinBox()
            spin.setRange(minimum, maximum)
            spin.setMaximumWidth(100)
            spin.setObjectName(f"portrait_{key}")
            spin.valueChanged.connect(self._changed)
            self.portrait_fields[key] = spin
            portrait_grid.addWidget(QLabel(label), index // 2, index % 2 * 2)
            portrait_grid.addWidget(spin, index // 2, index % 2 * 2 + 1)
        form.addRow(portrait_controls)
        self.shared_portrait = QCheckBox("同时修改共用头像记录")
        self.shared_portrait.toggled.connect(self._changed)
        form.addRow(self.shared_portrait)
        self.portrait_sharing = QLabel()
        self.portrait_sharing.setWordWrap(True)
        form.addRow(self.portrait_sharing)
        preview = QWidget()
        row = QHBoxLayout(preview)
        row.setContentsMargins(0, 0, 0, 0)
        self.front_preview = QLabel()
        self.back_preview = QLabel()
        self.composite_preview = QLabel()
        row.addWidget(QLabel("正面"))
        row.addWidget(self.front_preview)
        row.addWidget(QLabel("背景"))
        row.addWidget(self.back_preview)
        row.addWidget(QLabel("合成"))
        row.addWidget(self.composite_preview)
        row.addStretch()
        form.addRow(preview)
        uploads = QWidget()
        row = QHBoxLayout(uploads)
        row.setContentsMargins(0, 0, 0, 0)
        for kind, text in (("front", "上传正面…"), ("back", "上传背景…")):
            button = QPushButton(text)
            button.clicked.connect(lambda _checked=False, kind=kind: self._upload_image(kind))
            row.addWidget(button)
        row.addStretch()
        form.addRow(uploads)
        hint = QLabel("头像由真实 CHR 图块预览。背景使用 2KB 图库窗口，寄存器低位由硬件忽略；位置 5—8 使用后半个 1KB。")
        hint.setWordWrap(True)
        form.addRow(hint)
        tabs.addTab(portrait, "头像设置与上传")

    def _state(self):
        return (tuple(spin.value() for spin in self.fields.values()), self.survive.isChecked(),
                tuple(check.isChecked() for check in self.spirits), tuple(cost.value() for cost in self.costs),
                tuple(spin.value() for spin in self.portrait_fields.values()))

    def _changed(self, *_args) -> None:
        if self._loading:
            return
        self._render_previews()
        self.changed.emit()

    def has_pending_changes(self) -> bool:
        return self.codec is not None and self._baseline is not None and (self._state() != self._baseline or bool(self._image_drafts))

    def set_record(self, project, character_id: int | None) -> None:
        self.project, self.character_id = project, character_id
        self.codec = None
        self._baseline = None
        self._image_drafts.clear()
        if project is None or character_id is None:
            self.setEnabled(False)
            return
        self._loading = True
        try:
            codec = CharacterAttributesCodec(project)
            record = codec.read(character_id)
            portrait = codec.read_portrait(character_id)
            values = dict(zip(("movement", "strength", "defense", "speed", "hp"), record.corrections))
            values.update(spirit=record.spirit, growth=record.growth)
            values["movement"] &= 127
            for key, spin in self.fields.items():
                spin.setValue(values[key])
            self.survive.setChecked(bool(record.corrections[0] & 128))
            for index, check in enumerate(self.spirits):
                check.setChecked(bool(record.spirit_mask & (1 << (23 - index))))
            for cost, value in zip(self.costs, codec.costs()):
                cost.setValue(value)
            for key, spin in self.portrait_fields.items():
                value = portrait.colors[int(key[-1])] if key.startswith("color") else getattr(portrait, key)
                spin.setValue(value + (1 if key.endswith("slot") else 0))
            self.shared_attributes.setChecked(False)
            self.shared_portrait.setChecked(False)
            for label, is_portrait in ((self.attribute_sharing, False), (self.portrait_sharing, True)):
                ids = codec.shared_ids(character_id, portrait=is_portrait)
                names = "、".join(f"{item:03d}" for item in ids[:16])
                label.setText(f"共用此记录：{names}{'…' if len(ids) > 16 else ''}（{len(ids)} 个）。独立修改需要原数据池有空间。")
                label.setToolTip("、".join(f"{item:03d} {project.character_display_name(item)}" for item in ids if item < project.profile.character_name_count))
            self.codec = codec
            self._baseline = self._state()
            self.status.setText("修改将随数据库窗口“确定”保存；“取消”会还原本次窗口内的改动。")
            self.setEnabled(True)
            self._render_previews()
        except (ValueError, IndexError) as error:
            self.status.setText(str(error))
            self.setEnabled(False)
        finally:
            self._loading = False

    def attribute_record(self) -> CharacterAttributes:
        original = self.codec.read(self.character_id)
        values = self.fields
        movement = values["movement"].value() | (128 if self.survive.isChecked() else 0)
        return CharacterAttributes(values["spirit"].value(), values["growth"].value(),
                                   sum(1 << (23 - index) for index, check in enumerate(self.spirits) if check.isChecked()),
                                   (movement, values["strength"].value(), values["defense"].value(),
                                    values["speed"].value(), values["hp"].value()), original.reserved_flags)

    def portrait_record(self) -> PortraitRecord:
        values = {key: spin.value() for key, spin in self.portrait_fields.items()}
        return PortraitRecord(tuple(values[f"color{index}"] for index in range(3)),
                              values["front_bank"], values["back_bank"], values["front_slot"] - 1, values["back_slot"] - 1)

    def pending_patches(self):
        if self.codec is None or self.character_id is None:
            return ()
        patches = (self.codec.patches(self.character_id, self.attribute_record(), shared=self.shared_attributes.isChecked())
                   + self.codec.portrait_patches(self.character_id, self.portrait_record(), shared=self.shared_portrait.isChecked())
                   + (self.codec.cost_patch(tuple(cost.value() for cost in self.costs)),))
        portrait = self.portrait_record()
        targets = {"front": portrait.front_bank * 64 + portrait.front_slot * 16,
                   "back": (portrait.back_bank & 0xFE) * 64 + portrait.back_slot * 16}
        for kind, (first_tile, payload) in self._image_drafts.items():
            if targets[kind] != first_tile:
                raise ValueError("上传后更改了头像图库位置，请在新位置重新上传图片。")
            offset = self.project.chr_codec.tile_offset(first_tile)
            patches += ((offset, bytes(self.project.working[offset:offset + len(payload)]), payload),)
        replacements = {}
        for offset, _before, after in patches:
            for index, value in enumerate(after):
                if offset + index in replacements and replacements[offset + index] != value:
                    raise ValueError("正面和背景上传指向重叠的 CHR 图块，且内容不同；请为它们选择不同图库位置。")
                replacements[offset + index] = value
        return patches

    def apply_pending(self) -> None:
        if self.has_pending_changes():
            apply_verified_patches(self.project, self.pending_patches(), "人物属性、精神与头像")

    def reset_to_original(self) -> None:
        if self.codec is None or self.character_id is None:
            return
        patches = (self.codec.patches(self.character_id, self.codec.read(self.character_id, original=True),
                                      shared=self.shared_attributes.isChecked())
                   + self.codec.portrait_patches(self.character_id, self.codec.read_portrait(self.character_id, original=True),
                                                shared=self.shared_portrait.isChecked()))
        apply_verified_patches(self.project, patches, "还原人物属性与头像")

    def _render_previews(self) -> None:
        if self.project is None or self.codec is None:
            return
        record = self.portrait_record()
        front = self._render_preview(self.front_preview, record.front_bank * 64 + record.front_slot * 16, record.colors, transparent=True)
        back = self._render_preview(self.back_preview, (record.back_bank & 0xFE) * 64 + record.back_slot * 16, (0, 0x10, 0x20))
        if front is not None and back is not None:
            for y in range(32):
                for x in range(32):
                    if front.pixelColor(x, y).alpha():
                        back.setPixelColor(x, y, front.pixelColor(x, y))
            self.composite_preview.setPixmap(QPixmap.fromImage(back.scaled(96, 96)))

    def _render_preview(self, label: QLabel, first_tile: int, palette: tuple[int, ...], *, transparent: bool = False) -> QImage | None:
        if first_tile + 16 > self.project.chr_tile_count:
            label.clear()
            label.setText("图库越界")
            return None
        image = QImage(32, 32, QImage.Format.Format_ARGB32)
        colors = (palette_color(0x0F), *(palette_color(value) for value in palette))
        if transparent:
            colors[0].setAlpha(0)
        for tile in range(16):
            pixels = self.project.chr_tile_pixels(first_tile + tile)
            for draft_start, payload in self._image_drafts.values():
                if draft_start <= first_tile + tile < draft_start + 16:
                    raw = payload[(first_tile + tile - draft_start) * 16:(first_tile + tile - draft_start + 1) * 16]
                    pixels = tuple(((raw[y] >> (7-x)) & 1) | (((raw[y+8] >> (7-x)) & 1) << 1) for y in range(8) for x in range(8))
            for y in range(8):
                for x in range(8):
                    image.setPixelColor(tile % 4 * 8 + x, tile // 4 * 8 + y, colors[pixels[y * 8 + x]])
        label.setPixmap(QPixmap.fromImage(image.scaled(96, 96)))
        return image

    def import_portrait_image(self, kind: str, image: QImage) -> None:
        if self.codec is None or kind not in ("front", "back"):
            raise ValueError("请先选择人物及正面或背景头像。")
        if image.isNull() or image.width() != 32 or image.height() != 32:
            raise ValueError("头像图片必须为 32×32 像素。")
        record = self.portrait_record()
        first_tile = record.front_bank * 64 + record.front_slot * 16 if kind == "front" else (record.back_bank & 0xFE) * 64 + record.back_slot * 16
        self.project.chr_codec.range_bytes(first_tile, 16, bytes(self.project.working))
        colors = (palette_color(0x0F), *(palette_color(value) for value in (record.colors if kind == "front" else (0, 0x10, 0x20))))
        payload = bytearray()
        for tile in range(16):
            pixels = []
            for y in range(8):
                for x in range(8):
                    color = image.pixelColor(tile % 4 * 8 + x, tile // 4 * 8 + y)
                    if color.alpha() < 128:
                        pixels.append(0)
                    else:
                        pixels.append(min(range(4), key=lambda index: sum((a-b)**2 for a, b in zip(color.getRgb()[:3], colors[index].getRgb()[:3]))))
            payload.extend(self.project.chr_codec.encode_tile(pixels))
        self._image_drafts[kind] = first_tile, bytes(payload)
        self.status.setText("头像图片已暂存，按当前四色量化；上传会影响所有使用这些 CHR 图块的人物。确定后写入，取消可放弃。")
        self._changed()

    def _upload_image(self, kind: str) -> None:
        path, _filter = QFileDialog.getOpenFileName(self, "上传32×32头像", "", "图片 (*.png *.bmp)")
        if not path:
            return
        try:
            self.import_portrait_image(kind, QImage(path))
        except ValueError as error:
            QMessageBox.critical(self, "头像上传失败", str(error))
