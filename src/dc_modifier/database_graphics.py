from __future__ import annotations

from dataclasses import dataclass

from PySide6.QtGui import QColor, QImage, QPainter, QPen

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


@dataclass(frozen=True)
class FragmentTile:
    tile_index: int
    x: int
    y: int
    flip_horizontal: bool = False
    flip_vertical: bool = False


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


def decode_unit_fragment_script(script: bytes) -> tuple[FragmentTile, ...]:
    """Decode the documented unit-fragment sprite composition language.

    The first three bytes are ``X, Y, tile``.  The stored Y value is the
    signed offset from the bottom of the 128-pixel battle viewport.  Every
    following command draws
    that tile, optionally flips it, then describes the next tile/position.
    Bit $40 is horizontal flip and bit $80 is vertical flip.  The command
    families are the ones documented by the original editor's
    ``机体碎片组合方式`` reference.
    """

    if len(script) < 4 or script[-1] != 0xFF:
        raise ValueError("机体碎片脚本不完整或缺少 FF 结束码。")
    # The stock empty record is a sentinel rather than a drawable sprite.
    if script == bytes.fromhex("00 F0 00 00 FF"):
        return ()
    # The two leading coordinates are easy to misread in the old reference:
    # they are X followed by Y, not Y followed by X.  X is already relative
    # to the unit-side viewport, while Y is stored as a signed displacement
    # from its bottom edge.  Keeping this conversion here makes every caller
    # (main database page and the appearance dialog) use the game geometry.
    x = _signed_byte(script[0])
    y = _signed_byte(script[1]) + 0x80
    tile = script[2]
    cursor = 3
    placements: list[FragmentTile] = []
    parameter_counts = {
        0x02: 0, 0x03: 0,
        0x06: 1, 0x07: 1,
        0x0A: 1, 0x0B: 1,
        0x0E: 2, 0x0F: 2,
        0x22: 1, 0x23: 1,
        0x26: 2, 0x27: 2,
        0x2A: 2, 0x2B: 2,
        0x2E: 3, 0x2F: 3,
    }
    while cursor < len(script):
        command = script[cursor]
        cursor += 1
        if command == 0xFF:
            if cursor != len(script):
                raise ValueError("机体碎片结束码后仍有未解析字节。")
            return tuple(placements)
        base = command & 0x3F
        count = parameter_counts.get(base)
        if count is None:
            raise ValueError(f"机体碎片包含未验证指令 ${command:02X}。")
        if cursor + count > len(script):
            raise ValueError(f"机体碎片指令 ${command:02X} 参数不完整。")
        parameters = script[cursor:cursor + count]
        cursor += count
        if not 0 <= tile < 0x80:
            raise ValueError(f"机体碎片引用图块 ${tile:02X}，超出 2 KiB 图库。")
        placements.append(FragmentTile(
            tile, x, y, bool(command & 0x40), bool(command & 0x80)
        ))
        # $02/$03 continue horizontally.  $06/$07 use an explicit horizontal
        # delta; $0A/$0B do the same after advancing one 8-pixel sprite row;
        # $0E/$0F provide both deltas.  This is the distinction described by
        # the legacy physical-sprite reference as "上一图块" versus
        # "上一图块的下一格位置".
        if base in (0x02, 0x03):
            x += 8
        elif base in (0x06, 0x07):
            x += _signed_byte(parameters[0])
        elif base in (0x0A, 0x0B):
            x += _signed_byte(parameters[0])
            y += 8
        elif base in (0x0E, 0x0F):
            x += _signed_byte(parameters[0])
            y += _signed_byte(parameters[1])
        elif base in (0x22, 0x23):
            tile = parameters[0] - 1
            x += 8
        elif base in (0x26, 0x27):
            tile = parameters[0] - 1
            x += _signed_byte(parameters[1])
        elif base in (0x2A, 0x2B):
            tile = parameters[0] - 1
            x += _signed_byte(parameters[1])
            y += 8
        else:  # $2E/$2F: next tile plus both position deltas.
            tile = parameters[0] - 1
            x += _signed_byte(parameters[1])
            y += _signed_byte(parameters[2])
        tile += 1
    raise ValueError("机体碎片脚本缺少 FF 结束码。")


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


def render_chr_banks(
    project,
    banks: tuple[int, ...],
    colors: tuple[int, ...],
    *,
    columns: int | None = None,
) -> QImage:
    """Render actual CHR banks in tile order, not a fabricated battle pose."""

    if not banks or len(colors) != 3:
        raise ValueError("图库预览需要有效页号和三色索引。")
    if any(bank < 0 or (bank + 1) * 64 > project.chr_tile_count for bank in banks):
        raise ValueError("外观引用的图库超出活动 CHR。")
    if columns is None:
        columns = len(banks)
    if not 1 <= columns <= len(banks):
        raise ValueError("图库预览列数无效。")
    rows = (len(banks) + columns - 1) // columns
    image = QImage(64 * columns, 64 * rows, QImage.Format.Format_RGB32)
    background = palette_color(0x0F)
    image.fill(background)
    palette = (background, *(palette_color(value) for value in colors))
    for bank_index, bank in enumerate(banks):
        bank_column = bank_index % columns
        bank_row = bank_index // columns
        for tile in range(64):
            pixels = project.chr_tile_pixels(bank * 64 + tile)
            x0 = bank_column * 64 + tile % 8 * 8
            y0 = bank_row * 64 + tile // 8 * 8
            for y in range(8):
                for x in range(8):
                    image.setPixelColor(x0 + x, y0 + y, palette[pixels[y * 8 + x]])
    return image


def render_tile_grid(image: QImage, spacing: int = 8) -> QImage:
    """Return a copy with a subtle tile grid for the composition inspector."""

    if spacing <= 0:
        raise ValueError("网格间距必须大于零。")
    result = image.copy()
    painter = QPainter(result)
    painter.setPen(QPen(QColor(190, 205, 215, 105), 1))
    for x in range(0, result.width(), spacing):
        painter.drawLine(x, 0, x, result.height() - 1)
    for y in range(0, result.height(), spacing):
        painter.drawLine(0, y, result.width() - 1, y)
    painter.end()
    return result


def render_unit_body_composition(
    project,
    script: bytes,
    banks: tuple[int, ...],
    colors: tuple[int, ...],
) -> QImage:
    """Render the verified background/body composition."""

    if not banks or len(colors) != 3:
        raise ValueError("机体拼装预览需要有效图库和三色索引。")
    if any(bank < 0 or (bank + 1) * 64 > project.chr_tile_count for bank in banks):
        raise ValueError("机体拼图引用的图库超出活动 CHR。")
    placements = decode_unit_body_script(script, len(banks) * 64)
    image = QImage(128, 128, QImage.Format.Format_RGB32)
    image.fill(palette_color(0x0F))
    if not placements:
        return image
    min_x = min(item.x for item in placements)
    max_x = max(item.x for item in placements)
    min_y = min(item.y for item in placements)
    max_y = max(item.y for item in placements)
    offset_x = (16 - (max_x - min_x + 1)) // 2 - min_x
    offset_y = (16 - (max_y - min_y + 1)) // 2 - min_y
    palette = (palette_color(0x0F), *(palette_color(value) for value in colors))
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


def render_unit_battle_preview(
    project,
    appearance: UnitAppearance,
    *,
    show_body: bool = True,
    show_fragments: bool = True,
) -> QImage:
    """Render the body background and fragment sprites as the game layers them.

    The 128x128 viewport is the unit-side crop used by the battle screen.  The
    body script uses its battle baseline at Y=120; fragment coordinates are
    converted by :func:`decode_unit_fragment_script` from the same runtime
    coordinate system.
    """

    body = decode_unit_body_script(
        appearance.body_script, len(appearance.secondary_banks) * 64
    )
    fragments = decode_unit_fragment_script(appearance.fragment_script)
    image = QImage(128, 128, QImage.Format.Format_RGB32)
    image.fill(palette_color(0x0F))
    body_palette = (
        palette_color(0x0F),
        *(palette_color(value) for value in appearance.first_palette),
    )
    # Bit $40 is the opposing-side layout.  Its scripts use negative X tile
    # coordinates and the game anchors that background at tile column 15.
    body_origin_x = 15 if appearance.configuration[0] & 0x40 else 0
    for placement in body if show_body else ():
        bank_index, local_tile = divmod(placement.tile_index, 64)
        pixels = project.chr_tile_pixels(
            appearance.secondary_banks[bank_index] * 64 + local_tile
        )
        x0 = (placement.x + body_origin_x) * 8
        y0 = (placement.y + 15) * 8
        for y in range(8):
            for x in range(8):
                color_index = pixels[y * 8 + x]
                if color_index and 0 <= x0 + x < 128 and 0 <= y0 + y < 128:
                    image.setPixelColor(x0 + x, y0 + y, body_palette[color_index])
    fragment_bank = appearance.primary_bank & 0xFE
    fragment_palette = (
        palette_color(0x0F),
        *(palette_color(value) for value in appearance.second_palette),
    )
    # Opposing-side sprite X values occupy the right-hand half of the battle
    # viewport.  The signed script coordinate deliberately wraps at 128.
    fragment_origin_x = 0x80 if appearance.configuration[0] & 0x40 else 0
    for placement in fragments if show_fragments else ():
        bank_index, local_tile = divmod(placement.tile_index, 64)
        pixels = project.chr_tile_pixels((fragment_bank + bank_index) * 64 + local_tile)
        for y in range(8):
            source_y = 7 - y if placement.flip_vertical else y
            for x in range(8):
                source_x = 7 - x if placement.flip_horizontal else x
                color_index = pixels[source_y * 8 + source_x]
                target_x = placement.x + fragment_origin_x + x
                target_y = placement.y + y
                if color_index and 0 <= target_x < 128 and 0 <= target_y < 128:
                    image.setPixelColor(target_x, target_y, fragment_palette[color_index])
    return image
