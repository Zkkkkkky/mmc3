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


@dataclass(frozen=True)
class CompositionTile:
    tile_index: int
    x: int
    y: int


def _signed_byte(value: int) -> int:
    return value - 0x100 if value & 0x80 else value


def decode_unit_body_script(
    script: bytes,
    tile_capacity: int,
) -> tuple[CompositionTile, ...]:
    """Decode the verified body-composition commands into an 8x8 tile grid.

    ``F3 dy dx`` moves the cursor and starts a new row, ``FD 20 width``
    selects the row width, and ``F9 count first`` expands consecutive tiles.
    Literal bytes draw one tile.  The same row counter is shared by literals
    and expanded runs, which is required by the large-unit records.
    """

    if not script:
        raise ValueError("机体拼图脚本为空。")
    if not 1 <= tile_capacity <= 0x80:
        raise ValueError("机体拼图图库容量无效。")
    x = y = 0
    row_width = 0x20
    row_count = 0
    cursor = 0
    placements: list[CompositionTile] = []

    def place(tile_index: int) -> None:
        nonlocal x, y, row_count
        if not 0 <= tile_index < tile_capacity:
            raise ValueError(
                f"机体拼图引用图块 ${tile_index:02X}，超出当前图库容量。"
            )
        placements.append(CompositionTile(tile_index, x, y))
        x += 1
        row_count += 1
        if row_count == row_width:
            x -= row_width
            y += 1
            row_count = 0

    while cursor < len(script):
        opcode = script[cursor]
        cursor += 1
        if opcode == 0xFF:
            if cursor != len(script):
                raise ValueError("机体拼图结束码后仍有未解析字节。")
            if placements:
                width = max(item.x for item in placements) - min(item.x for item in placements) + 1
                height = max(item.y for item in placements) - min(item.y for item in placements) + 1
                if width > 16 or height > 16:
                    raise ValueError(
                        f"机体拼图范围为 {width}x{height} 图块，超出 128x128 画布。"
                    )
            return tuple(placements)
        if opcode == 0xF3:
            if cursor + 2 > len(script):
                raise ValueError("机体拼图的 F3 坐标参数不完整。")
            y += _signed_byte(script[cursor])
            x += _signed_byte(script[cursor + 1])
            cursor += 2
            row_count = 0
            continue
        if opcode == 0xFD:
            if cursor + 2 > len(script) or script[cursor] != 0x20:
                raise ValueError("机体拼图只支持已验证的 FD 20 宽度指令。")
            row_width = script[cursor + 1]
            cursor += 2
            row_count = 0
            if not 1 <= row_width <= 0x20:
                raise ValueError("机体拼图行宽必须在 1—32 图块之间。")
            continue
        if opcode == 0xF9:
            if cursor + 2 > len(script):
                raise ValueError("机体拼图的 F9 连续图块参数不完整。")
            count, first_tile = script[cursor:cursor + 2]
            cursor += 2
            for index in range(count):
                place(first_tile + index)
            continue
        if opcode >= 0xF0:
            raise ValueError(f"机体拼图包含未验证指令 ${opcode:02X}。")
        place(opcode)
    raise ValueError("机体拼图缺少 FF 结束码。")


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


def render_unit_body_composition(
    project,
    script: bytes,
    banks: tuple[int, ...],
    colors: tuple[int, ...],
) -> QImage:
    """Render the current unit's body script on the legacy 128x128 canvas."""

    if not banks or len(colors) != 3:
        raise ValueError("机体拼装预览需要有效图库和三色索引。")
    if any(bank < 0 or (bank + 1) * 64 > project.chr_tile_count for bank in banks):
        raise ValueError("机体拼图引用的图库超出活动 CHR。")
    placements = decode_unit_body_script(script, len(banks) * 64)
    image = QImage(128, 128, QImage.Format.Format_RGB32)
    image.fill(QColor("#000000"))
    if not placements:
        return image
    min_x = min(item.x for item in placements)
    max_x = max(item.x for item in placements)
    min_y = min(item.y for item in placements)
    max_y = max(item.y for item in placements)
    offset_x = (16 - (max_x - min_x + 1)) // 2 - min_x
    offset_y = (16 - (max_y - min_y + 1)) // 2 - min_y
    palette = (QColor("#000000"), *(palette_color(value) for value in colors))
    for placement in placements:
        bank_index, local_tile = divmod(placement.tile_index, 64)
        pixels = project.chr_tile_pixels(banks[bank_index] * 64 + local_tile)
        x0 = (placement.x + offset_x) * 8
        y0 = (placement.y + offset_y) * 8
        for y in range(8):
            for x in range(8):
                color_index = pixels[y * 8 + x]
                if color_index:
                    image.setPixelColor(x0 + x, y0 + y, palette[color_index])
    return image
