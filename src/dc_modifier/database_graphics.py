from __future__ import annotations

from dataclasses import dataclass

from PySide6.QtGui import QColor, QImage

from fc_editor.expansion import FLAG_UNITS
from fc_editor.expansion_unit import (
    CONFIGURATION_TABLE,
    SOURCE_CONFIGURATION_PAIR,
    extract_unit_expansion_records,
    validate_unit_expansion_payload,
)


# Display RGB values from the bundled FCEUX 2.6.6 FCEUX.pal.  ROM values are
# palette indices, not RGB colours; using one explicit display palette keeps
# the inspector deterministic and does not change any game palette bytes.
FCEUX_RGB = bytes.fromhex(
    "74747424188c0000a844009c8c0074a80010a400007c0800402c00004400005000003c14"
    "183c5c000000000000000000bcbcbc0070ec2038ec8000f0bc00bce40058d82800c84c0c"
    "88700000940000a800009038008088000000000000000000fcfcfc3cbcfc5c94fccc88fc"
    "f478fcfc74b4fc7460fc9838f0bc3c80d0104cdc4858f89800e8d8787878000000000000"
    "fcfcfca8e4fcc4d4fcd4c8fcfcc4fcfcc4d8fcbcb0fcd8a8fce4a0e0fca0a8f0bc"
    "b0fccc9cfcf0c4c4c4000000000000"
)


@dataclass(frozen=True)
class UnitAppearance:
    configuration: bytes
    file_offset: int
    body_script: bytes
    fragment_script: bytes

    @property
    def first_palette(self) -> tuple[int, ...]:
        return tuple(self.configuration[1:4])

    @property
    def second_palette(self) -> tuple[int, ...]:
        return tuple(self.configuration[4:7])

    @property
    def primary_bank(self) -> int:
        return self.configuration[7]

    @property
    def secondary_banks(self) -> tuple[int, ...]:
        # $8E86 stores byte +8 in $04D4. Byte +9 is only read when the
        # configuration sign bit is set ($8E8B-$8E92); small records are
        # physically nine bytes and their following byte must not be shown
        # as a second bank belonging to this unit.
        return tuple(self.configuration[8:10] if self.configuration[0] & 0x80
                     else self.configuration[8:9])


def read_unit_appearance(project, unit_id: int) -> UnitAppearance:
    """Read the stock or relocated resources, without guessing write layouts."""

    if project.profile.key not in ("dc-kuorong-mmc3-v1", "dc-kuorong-mmc3-v2"):
        raise ValueError("此 ROM 的战斗外观资源尚未验证，当前仅提供数值编辑。")
    if not 1 <= unit_id < project.unit_count:
        raise ValueError("请选择有效机体。")
    source = bytes(project.working)
    # Both sides load these exact palette and CHR fields. Keep this check
    # independent of table decoding so an altered runtime cannot silently
    # acquire the stock interpretation.
    if source[0x8E65:0x8EA5] != bytes.fromhex(
        "a000b1188507c8b1188d7604c8b1188d7704c8b1188d7804c8b1188d7904"
        "c8b1188d7a04c8b1188d7b04c8b1188dd004c8b1188dd40424071006c8b1188dd504"
    ):
        raise ValueError("战斗外观加载代码与已验证格式不同，已停止资源预览。")
    plan = project.expansion_plan
    pair = SOURCE_CONFIGURATION_PAIR
    if plan is not None and plan.flags & FLAG_UNITS:
        pairs = tuple(zip(plan.unit_banks[::2], plan.unit_banks[1::2]))
        records = validate_unit_expansion_payload(source, pairs)
        pair = plan.unit_banks[2]
    else:
        records = extract_unit_expansion_records(source)
    pair_offset = 16 + pair * 0x2000
    pointer_offset = pair_offset + CONFIGURATION_TABLE - 0x8000 + unit_id * 2
    pointer = int.from_bytes(source[pointer_offset:pointer_offset + 2], "little")
    return UnitAppearance(
        records.configurations[unit_id - 1],
        pair_offset + pointer - 0x8000,
        records.body_scripts[unit_id - 1],
        records.fragment_scripts[unit_id - 1],
    )


def palette_color(index: int) -> QColor:
    start = (index & 0x3F) * 3
    return QColor(*FCEUX_RGB[start:start + 3])


def render_chr_banks(project, banks: tuple[int, ...], colors: tuple[int, ...]) -> QImage:
    """Render actual CHR banks in tile order, not a fabricated battle pose."""

    if not banks or len(colors) != 3:
        raise ValueError("图库预览需要有效页号和三色索引。")
    if any(bank < 0 or (bank + 1) * 64 > project.chr_tile_count for bank in banks):
        raise ValueError("外观引用的图库超出活动 CHR。")
    image = QImage(64 * len(banks), 64, QImage.Format.Format_RGB32)
    palette = (QColor("#000000"), *(palette_color(value) for value in colors))
    for column, bank in enumerate(banks):
        for tile in range(64):
            pixels = project.chr_tile_pixels(bank * 64 + tile)
            x0, y0 = column * 64 + tile % 8 * 8, tile // 8 * 8
            for y in range(8):
                for x in range(8):
                    image.setPixelColor(x0 + x, y0 + y, palette[pixels[y * 8 + x]])
    return image
