from __future__ import annotations

import hashlib
import os
from pathlib import Path
import zipfile

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtGui import QColor, QImage
from PySide6.QtWidgets import QApplication

from dc_modifier.database_graphics import (
    palette_color,
    read_unit_appearance,
    render_unit_battle_preview,
)
from dc_modifier.map_page import MAP_ICON_BANK_CANDIDATES, MAP_ICON_PALETTES_NES
from dc_modifier.unit_appearance_dialog import WORK_PALETTE
from fc_editor.legacy_bitmap import LEGACY_MATERIAL_PALETTE_RGB, encode_legacy_bmp24
from fc_rom_editor_core import RomProject


ROOT = Path(__file__).resolve().parents[2]
ROM = ROOT / "output/rom/DC_kuorong_464K.nes"
SAMPLES = ROOT / "output/verification/legacy-user-evidence-2026-09-14/legacy-unit-export-samples.zip"


def bmp_bytes(image: QImage) -> bytes:
    pixels = (
        (image.pixelColor(x, y).red(), image.pixelColor(x, y).green(), image.pixelColor(x, y).blue())
        for y in range(image.height())
        for x in range(image.width())
    )
    return encode_legacy_bmp24(image.width(), image.height(), pixels)


def mismatch(left: QImage, right: QImage) -> int:
    if (left.width(), left.height()) != (right.width(), right.height()):
        return -1
    return sum(
        left.pixelColor(x, y).rgb() != right.pixelColor(x, y).rgb()
        for y in range(left.height())
        for x in range(left.width())
    )


def icon_image(project, unit_id: int, bank: int, palette: tuple[QColor, ...]) -> QImage:
    first_tile = project.record_bytes(unit_id)[2]
    local = first_tile % 64
    image = QImage(16, 16, QImage.Format.Format_RGB32)
    image.fill(palette[0])
    for quadrant in range(4):
        pixels = project.chr_tile_pixels(bank * 64 + local + quadrant)
        x0 = quadrant % 2 * 8
        y0 = quadrant // 2 * 8
        for y in range(8):
            for x in range(8):
                image.setPixelColor(x0 + x, y0 + y, palette[pixels[y * 8 + x]])
    return image


def main() -> None:
    QApplication.instance() or QApplication([])
    project = RomProject.load(ROM)
    appearance = read_unit_appearance(project, 1)
    with zipfile.ZipFile(SAMPLES) as archive:
        entries = {
            Path(info.filename).name: archive.read(info)
            for info in archive.infolist()
            if "/001：" in info.filename
        }
    print(sorted(entries))
    expected = {name: QImage.fromData(raw, "BMP") for name, raw in entries.items()}
    modes = {
        "机体-material": render_unit_battle_preview(
            project, appearance, show_fragments=False, display_palette=WORK_PALETTE
        ),
        "碎片-material": render_unit_battle_preview(
            project, appearance, show_body=False, display_palette=WORK_PALETTE
        ),
        "效果-game": render_unit_battle_preview(project, appearance),
        "效果-material": render_unit_battle_preview(
            project, appearance, display_palette=WORK_PALETTE
        ),
    }
    for label, image in modes.items():
        suffix = {"机体-material": "[机体].bmp", "碎片-material": "[碎片].bmp"}.get(
            label, "[效果].bmp"
        )
        name = next(name for name in entries if name.endswith(suffix))
        raw = bmp_bytes(image)
        print(
            label,
            "mismatch",
            mismatch(image, expected[name]),
            "sha",
            hashlib.sha256(raw).hexdigest().upper(),
            hashlib.sha256(entries[name]).hexdigest().upper(),
        )

    material = tuple(QColor(*rgb) for rgb in LEGACY_MATERIAL_PALETTE_RGB)
    palettes = {"material": material}
    palettes.update(
        {side: tuple(palette_color(value) for value in values) for side, values in MAP_ICON_PALETTES_NES.items()}
    )
    for suffix in ("[图标1].bmp", "[图标2].bmp"):
        name = next(name for name in entries if name.endswith(suffix))
        ranked = []
        for bank in MAP_ICON_BANK_CANDIDATES:
            for label, colors in palettes.items():
                image = icon_image(project, 1, bank, colors)
                ranked.append((mismatch(image, expected[name]), bank, label, hashlib.sha256(bmp_bytes(image)).hexdigest().upper()))
        print(suffix, sorted(ranked)[:10], "expected", hashlib.sha256(entries[name]).hexdigest().upper())

    with zipfile.ZipFile(SAMPLES) as archive:
        samples: dict[tuple[int, str], bytes] = {}
        for info in archive.infolist():
            parts = info.filename.split("/")
            unit_id = int(parts[1][:3])
            kind = parts[2].rsplit("[", 1)[1].removesuffix("].bmp")
            samples[unit_id, kind] = archive.read(info)

    exact = {kind: 0 for kind in ("机体", "碎片", "效果", "图标1", "图标2")}
    failures: dict[str, list[tuple[int, int]]] = {kind: [] for kind in exact}
    icon_choices: dict[str, dict[tuple[int, str], int]] = {"图标1": {}, "图标2": {}}
    for unit_id in range(1, 256):
        appearance = read_unit_appearance(project, unit_id)
        rendered = {
            "机体": render_unit_battle_preview(
                project, appearance, show_fragments=False, display_palette=WORK_PALETTE
            ),
            "碎片": render_unit_battle_preview(
                project, appearance, show_body=False, display_palette=WORK_PALETTE
            ),
            "效果": render_unit_battle_preview(project, appearance),
        }
        for kind, image in rendered.items():
            expected_image = QImage.fromData(samples[unit_id, kind], "BMP")
            distance = mismatch(image, expected_image)
            if distance == 0:
                exact[kind] += 1
            else:
                failures[kind].append((unit_id, distance))
        for kind, palette_labels in (("图标1", ("我", "敌", "客")), ("图标2", ("material",))):
            expected_image = QImage.fromData(samples[unit_id, kind], "BMP")
            choices = []
            for bank in MAP_ICON_BANK_CANDIDATES:
                for label in palette_labels:
                    image = icon_image(project, unit_id, bank, palettes[label])
                    distance = mismatch(image, expected_image)
                    if distance == 0:
                        choices.append((bank, label))
            if choices:
                exact[kind] += 1
                choice = choices[0]
                icon_choices[kind][choice] = icon_choices[kind].get(choice, 0) + 1
            else:
                failures[kind].append((unit_id, min(
                    mismatch(icon_image(project, unit_id, bank, palettes[label]), expected_image)
                    for bank in MAP_ICON_BANK_CANDIDATES for label in palette_labels
                )))
    print("exact", exact)
    print("icon choices", icon_choices)
    print("failures", {kind: values[:30] for kind, values in failures.items()})
    print("nonblank icon routes")
    for unit_id in range(1, 256):
        expected_image = QImage.fromData(samples[unit_id, "图标2"], "BMP")
        black = QColor(0, 0, 0).rgb()
        if all(expected_image.pixelColor(x, y).rgb() == black for y in range(16) for x in range(16)):
            continue
        banks = [
            bank for bank in MAP_ICON_BANK_CANDIDATES
            if mismatch(icon_image(project, unit_id, bank, palettes["material"]), expected_image) == 0
        ]
        config = read_unit_appearance(project, unit_id).configuration[0]
        print(unit_id, hex(project.record_bytes(unit_id)[2]), hex(config), banks)
    for unit_id, kind in ((9, "碎片"), (9, "效果"), (241, "效果")):
        appearance = read_unit_appearance(project, unit_id)
        image = render_unit_battle_preview(
            project,
            appearance,
            show_body=kind != "碎片",
            show_fragments=True,
            display_palette=WORK_PALETTE if kind == "碎片" else None,
        )
        reference = QImage.fromData(samples[unit_id, kind], "BMP")
        differences = [
            (x, y, image.pixelColor(x, y).name(), reference.pixelColor(x, y).name())
            for y in range(128) for x in range(128)
            if image.pixelColor(x, y).rgb() != reference.pixelColor(x, y).rgb()
        ]
        print("pixel differences", unit_id, kind, differences[:80])


if __name__ == "__main__":
    main()
