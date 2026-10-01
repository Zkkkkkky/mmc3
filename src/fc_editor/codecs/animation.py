"""Bounded decoding of the animation resources used by the current DC ROM.

Addresses and operand lengths are checked against the resource loader and the
animation interpreter, rather than the older CHM's original-ROM addresses.
Only existing operands may change; pointers and control flow stay intact.
"""
from __future__ import annotations

from dataclasses import dataclass
from difflib import SequenceMatcher
import struct


BytePatch = tuple[int, bytes, bytes]


READ_ONLY_CALL_AUDIT: dict[int, tuple[str, str]] = {
    0x3804A: (
        "资料编号冲突",
        "资料记为 $3804A→$0C，当前 ROM 同址为 $00；不能按冲突编号改写。",
    ),
    0x384B0: (
        "只有编号含义",
        "只确认动画 $10 的含义，尚无该调用地址或完整前置序列证据。",
    ),
    0x3853D: (
        "只有编号含义",
        "只确认动画 $10 的含义，尚无该调用地址或完整前置序列证据。",
    ),
    0x38982: (
        "资料地址不一致",
        "资料写作 $38983→$02，当前 ROM 调用起点为 $38982；不把疑似偏一字节当作地址证据。",
    ),
    0x38E68: (
        "只有编号含义",
        "只确认动画 $14 的含义；资料未列出该地址，前置序列也未在已验证流程中复现。",
    ),
    0x38EF3: (
        "只有编号含义",
        "只确认动画 $12 的含义；邻近事件指令不足以证明这一字节可以安全改写。",
    ),
    0x3B9DC: (
        "嵌入数据未验证",
        "命中位于 6502 子程序后的嵌入数据段，没有调用地址与脚本入口的双重证据。",
    ),
    0x3B9E0: (
        "嵌入数据未验证",
        "命中紧邻另一处未验证数据，没有已验证调用链头，不能只凭 38 02 字节外观改写。",
    ),
}


@dataclass(frozen=True)
class AnimationInstruction:
    offset: int
    raw: bytes
    text: str
    editable: tuple[tuple[int, int, int], ...] = ()


@dataclass(frozen=True)
class AnimationRecord:
    kind: str
    index: int
    offset: int
    raw: bytes
    aliases: tuple[int, ...]
    instructions: tuple[AnimationInstruction, ...]
    complete: bool


@dataclass(frozen=True)
class AnimationTable:
    kind: str
    pair: int
    directory: int
    table: int
    count: int
    end: int
    selector: int
    descriptor: bytes

    def offset(self, pointer: int) -> int:
        return 16 + self.pair * 0x2000 + pointer - 0x8000


@dataclass(frozen=True)
class AnimationPoolUsage:
    capacity: int
    used: int
    free: int
    unique_records: int


@dataclass(frozen=True)
class SpriteTilePlacement:
    """One OAM tile emitted by the verified physical-puzzle interpreter."""

    command_offset: int
    x: int
    y: int
    tile_index: int | None
    tile_token: int
    attributes: int

    @property
    def horizontal_flip(self) -> bool:
        return bool(self.attributes & 0x40)

    @property
    def vertical_flip(self) -> bool:
        return bool(self.attributes & 0x80)

    @property
    def palette(self) -> int:
        return self.attributes & 0x03


@dataclass(frozen=True)
class SpriteComposition:
    anchor_x: int
    anchor_y: int
    placements: tuple[SpriteTilePlacement, ...]
    complete: bool
    consumed: int
    error: str = ""


@dataclass(frozen=True)
class BeamComposition:
    """Decoded weapon-beam grid stream.

    Beam puzzle records are not physical/OAM compositions.  Their ``FE Y X``
    header selects a grid origin, literal bytes draw tiles, ``F3 DY DX`` moves
    the cursor, ``FD 20 width`` sets a row width, ``F8 count tile`` repeats a
    tile, and ``F9 count first`` draws consecutive tiles.  These command
    families are independently documented and covered by reference-editor
    save goldens; they must never be rewritten through the unrelated physical
    puzzle encoder.
    """

    anchor_x: int
    anchor_y: int
    placements: tuple[SpriteTilePlacement, ...]
    complete: bool
    editable: bool
    consumed: int
    error: str = ""
    unsupported_commands: tuple[int, ...] = ()


@dataclass(frozen=True)
class SpriteTimeline:
    frames: tuple[int, ...]
    loop_start: int | None
    terminated: bool
    complete: bool
    error: str = ""


def _signed_byte(value: int) -> int:
    return value - 0x100 if value & 0x80 else value


def decode_legacy_beam_composition(
    raw: bytes,
    start: int = 0,
) -> BeamComposition:
    """Decode the verified legacy beam-puzzle command language.

    The full record is required, including ``FE Y X``.  Literal tile bytes,
    relative cursor command ``F3 DY DX``, row-width command ``FD 20 width``,
    repeat command ``F8 count tile`` and consecutive command
    ``F9 count first`` are established by the legacy documentation and
    controlled reference-editor saves.
    """

    if len(raw) < 4 or raw[0] != 0xFE:
        return BeamComposition(
            0, 0, (), False, False, min(len(raw), 1),
            "光束拼图缺少 FE/Y/X 前置字节。",
        )
    anchor_y = raw[1]
    anchor_x = raw[2]
    x = anchor_x
    y = anchor_y
    cursor = 3
    placements: list[SpriteTilePlacement] = []
    row_width: int | None = None
    row_origin_x = x
    row_progress = 0

    def emit(tile: int, command_offset: int) -> None:
        nonlocal x, y, row_progress
        placements.append(
            SpriteTilePlacement(
                command_offset=start + command_offset,
                x=x,
                y=y,
                tile_index=tile,
                tile_token=tile,
                attributes=0,
            )
        )
        x += 1
        if row_width is not None:
            row_progress += 1
            if row_progress >= row_width:
                x = row_origin_x
                y += 1
                row_progress = 0
    while cursor < len(raw):
        command_offset = cursor
        command = raw[cursor]
        cursor += 1
        if command == 0xFF:
            return BeamComposition(
                anchor_x,
                anchor_y,
                tuple(placements),
                True,
                True,
                cursor,
                "",
                (),
            )
        if command <= 0xEF:
            emit(command, command_offset)
            continue
        if command == 0xF3:
            if cursor + 2 > len(raw):
                return BeamComposition(
                    anchor_x, anchor_y, tuple(placements), False, False,
                    cursor, "光束拼图的 F3 位移参数被截断。", (),
                )
            dy = _signed_byte(raw[cursor])
            dx = _signed_byte(raw[cursor + 1])
            cursor += 2
            y += dy
            x += dx
            row_origin_x = x
            row_progress = 0
            continue
        if command == 0xFE:
            if cursor + 2 > len(raw):
                return BeamComposition(
                    anchor_x, anchor_y, tuple(placements), False, False,
                    cursor, "光束拼图的 FE 坐标参数被截断。", (),
                )
            y = raw[cursor]
            x = raw[cursor + 1]
            cursor += 2
            row_origin_x = x
            row_progress = 0
            continue
        if command == 0xFD:
            if cursor + 2 > len(raw):
                return BeamComposition(
                    anchor_x, anchor_y, tuple(placements), False, False,
                    cursor, f"光束拼图的 ${command:02X} 参数被截断。",
                    (),
                )
            subtype = raw[cursor]
            width = raw[cursor + 1]
            cursor += 2
            if subtype != 0x20 or width == 0:
                return BeamComposition(
                    anchor_x, anchor_y, tuple(placements), False, False,
                    cursor,
                    f"光束拼图含未验证的 FD ${subtype:02X} ${width:02X}。",
                    (),
                )
            row_width = width
            row_origin_x = x
            row_progress = 0
            continue
        if command in (0xF8, 0xF9):
            if cursor + 2 > len(raw):
                return BeamComposition(
                    anchor_x, anchor_y, tuple(placements), False, False,
                    cursor, f"光束拼图的 ${command:02X} 参数被截断。",
                    (),
                )
            count = raw[cursor]
            tile = raw[cursor + 1]
            cursor += 2
            for index in range(count):
                emit(
                    tile if command == 0xF8 else (tile + index) & 0xFF,
                    command_offset,
                )
            continue
        return BeamComposition(
            anchor_x, anchor_y, tuple(placements), False, False, cursor,
            f"光束拼图含未识别指令 ${command:02X}。", (),
        )
    return BeamComposition(
        anchor_x, anchor_y, tuple(placements), False, False, cursor,
        "光束拼图缺少 $FF 结束码。", (),
    )


def _beam_run_length(
    items: tuple[SpriteTilePlacement, ...],
    start: int,
    width: int | None,
) -> int:
    """Return the number of placements following one row-major cursor."""

    x = items[start].x
    y = items[start].y
    origin_x = x
    progress = 0
    count = 0
    for item in items[start:]:
        if (item.x, item.y) != (x, y):
            break
        count += 1
        x += 1
        if width is not None:
            progress += 1
            if progress == width:
                x = origin_x
                y += 1
                progress = 0
    return count


def _beam_best_width(
    items: tuple[SpriteTilePlacement, ...], start: int
) -> tuple[int | None, int]:
    """Find a proven row width, preferring the longest then smallest form."""

    linear = _beam_run_length(items, start, None)
    best_width: int | None = None
    best_length = linear
    for width in range(1, 0x21):
        length = _beam_run_length(items, start, width)
        # A width is only observable after at least one wrap.  Without this
        # guard an arbitrary width could silently change later coordinates.
        if length <= width:
            continue
        if length > best_length or (
            length == best_length
            and best_width is not None
            and width < best_width
        ):
            best_width = width
            best_length = length
    return best_width, best_length


def _append_beam_tiles(result: bytearray, tokens: list[int]) -> bool:
    """Append literals/F8/F9 using the shortest verified local runs."""

    used_compression = False
    index = 0
    while index < len(tokens):
        repeat = 1
        while (
            index + repeat < len(tokens)
            and tokens[index + repeat] == tokens[index]
            and repeat < 0xFF
        ):
            repeat += 1
        sequential = 1
        while (
            index + sequential < len(tokens)
            and tokens[index + sequential]
            == (tokens[index] + sequential) & 0xFF
            and sequential < 0xFF
            and tokens[index + sequential] <= 0xEF
        ):
            sequential += 1
        if repeat >= 3:
            result.extend((0xF8, repeat, tokens[index]))
            index += repeat
            used_compression = True
        elif sequential >= 3:
            result.extend((0xF9, sequential, tokens[index]))
            index += sequential
            used_compression = True
        else:
            result.append(tokens[index])
            index += 1
    return used_compression


def encode_legacy_beam_composition(
    placements: tuple[SpriteTilePlacement, ...] | list[SpriteTilePlacement],
    *,
    anchor_x: int | None = None,
    anchor_y: int | None = None,
) -> bytes:
    """Encode placements with the verified legacy beam command language.

    Dense row-major regions use ``FD/F8/F9`` so editing a compressed record
    does not expand it into hundreds of literal bytes.  Sparse records retain
    the reference editor's literal/F3 form and neutral trailing move.
    """

    items = tuple(placements)
    if items:
        anchor_x = items[0].x if anchor_x is None else anchor_x
        anchor_y = items[0].y if anchor_y is None else anchor_y
    else:
        anchor_x = 0 if anchor_x is None else anchor_x
        anchor_y = 0 if anchor_y is None else anchor_y
    if not 0 <= anchor_x <= 0xFF or not 0 <= anchor_y <= 0xFF:
        raise ValueError("光束拼图初始坐标必须在 $00—$FF 之间。")
    result = bytearray((0xFE, anchor_y, anchor_x))
    current_x = anchor_x
    current_y = anchor_y
    used_compact = False
    active_width: int | None = None
    index = 0
    while index < len(items):
        item = items[index]
        if not 0 <= item.tile_token <= 0xEF:
            raise ValueError("光束拼图的直接图块编号必须在 $00—$EF 之间。")
        if (item.x, item.y) != (current_x, current_y):
            dx = item.x - current_x
            dy = item.y - current_y
            if not -128 <= dx <= 127 or not -128 <= dy <= 127:
                raise ValueError("相邻光束图块坐标差必须在 -128—127 之间。")
            result.extend((0xF3, dy & 0xFF, dx & 0xFF))
            current_x, current_y = item.x, item.y

        width, length = _beam_best_width(items, index)
        if width is not None:
            result.extend((0xFD, 0x20, width))
            used_compact = True
            active_width = width
        else:
            # No wrap was observed, so consume only the proven horizontal
            # stretch.  A later discontinuity is represented by F3.  FD has
            # no disable opcode, so after an earlier width command reset to a
            # 32-cell row and cap this segment before it could wrap.
            length = max(1, _beam_run_length(items, index, None))
            if active_width is not None:
                active_width = 0x20
                result.extend((0xFD, 0x20, active_width))
                used_compact = True
                length = min(length, active_width)
        tokens = [entry.tile_token for entry in items[index:index + length]]
        if any(not 0 <= token <= 0xEF for token in tokens):
            raise ValueError("光束拼图的直接图块编号必须在 $00—$EF 之间。")
        used_compact = _append_beam_tiles(result, tokens) or used_compact

        if width is None:
            current_x = items[index + length - 1].x + 1
            current_y = items[index + length - 1].y
        else:
            progress = length % width
            rows = length // width
            current_x = item.x + progress
            current_y = item.y + rows
        index += length
    if not used_compact:
        result.extend((0xF3, 0x00, 0x00))
    result.append(0xFF)
    return bytes(result)


def decode_sprite_composition(
    raw: bytes,
    start: int = 0,
) -> SpriteComposition:
    """Decode the exact tile walk used by the current ROM at $D194-$D2EF.

    The first two bytes are signed X/Y anchors and the third byte selects the
    first tile.  Each following byte both describes the current OAM tile and
    controls how the next tile, X and Y values are obtained.  Runtime tile
    tokens $F0-$FF depend on RAM lookup tables; they remain explicit unresolved
    placements instead of being replaced with guessed graphics.
    """

    if len(raw) < 3:
        return SpriteComposition(
            0,
            0,
            (),
            False,
            len(raw),
            "组图规律少于 X、Y 和首图块三个字节。",
        )
    anchor_x = _signed_byte(raw[0])
    anchor_y = _signed_byte(raw[1])
    x = anchor_x
    y = anchor_y
    tile_token = raw[2]
    tile_index: int | None = tile_token if tile_token < 0xF0 else None
    cursor = 3
    placements: list[SpriteTilePlacement] = []

    def truncated(label: str) -> SpriteComposition:
        return SpriteComposition(
            anchor_x,
            anchor_y,
            tuple(placements),
            False,
            cursor,
            f"{label}在 +${cursor:04X} 截断。",
        )

    while cursor < len(raw):
        command_offset = cursor
        command = raw[cursor]
        cursor += 1
        if command == 0xFF:
            return SpriteComposition(
                anchor_x,
                anchor_y,
                tuple(placements),
                True,
                cursor,
            )
        placements.append(
            SpriteTilePlacement(
                command_offset=start + command_offset,
                x=x,
                y=y,
                tile_index=tile_index,
                tile_token=tile_token,
                attributes=command & 0xC3,
            )
        )

        if command & 0x20:
            if cursor >= len(raw):
                return truncated("显式图块参数")
            tile_token = raw[cursor]
            cursor += 1
            tile_index = tile_token if tile_token < 0xF8 else None
        elif not command & 0x10:
            if tile_index is not None:
                tile_index = (tile_index + 1) & 0xFF
            tile_token = (tile_token + 1) & 0xFF

        if command & 0x08:
            if cursor >= len(raw):
                return truncated("X 位移参数")
            x += _signed_byte(raw[cursor])
            cursor += 1
            if command & 0x04:
                if cursor >= len(raw):
                    return truncated("Y 位移参数")
                y += _signed_byte(raw[cursor])
                cursor += 1
            else:
                y += 8
        elif command & 0x04:
            if cursor >= len(raw):
                return truncated("X 位移参数")
            x += _signed_byte(raw[cursor])
            cursor += 1
        else:
            x += 8

    return SpriteComposition(
        anchor_x,
        anchor_y,
        tuple(placements),
        False,
        cursor,
        "组图规律缺少 $FF 结束码。",
    )


def encode_sprite_composition(
    placements: tuple[SpriteTilePlacement, ...] | list[SpriteTilePlacement],
    *,
    anchor_x: int | None = None,
    anchor_y: int | None = None,
) -> bytes:
    """Encode an editable sprite placement list as a canonical safe stream.

    The legacy interpreter allows many equivalent compact encodings.  Editing
    needs one deterministic form, so every transition explicitly stores the
    following tile and signed X/Y delta.  This preserves placement order,
    coordinates, flip bits and palette bits without depending on implicit
    increment state.
    """

    items = tuple(placements)
    if items:
        if anchor_x is None:
            anchor_x = items[0].x
        if anchor_y is None:
            anchor_y = items[0].y
    else:
        anchor_x = 0 if anchor_x is None else anchor_x
        anchor_y = 0 if anchor_y is None else anchor_y
    if not -128 <= anchor_x <= 127 or not -128 <= anchor_y <= 127:
        raise ValueError("拼图锚点必须在 -128—127 之间。")
    if not items:
        return bytes((anchor_x & 0xFF, anchor_y & 0xFF, 0x00, 0xFF))
    if (items[0].x, items[0].y) != (anchor_x, anchor_y):
        raise ValueError("首个图块坐标必须与拼图锚点一致。")

    result = bytearray((anchor_x & 0xFF, anchor_y & 0xFF, items[0].tile_token))
    for index, item in enumerate(items):
        if not 0 <= item.tile_token <= 0xFF:
            raise ValueError("图块编号必须在 $00—$FF 之间。")
        attributes = item.attributes & 0xC3
        if index + 1 == len(items):
            result.append(attributes | 0x10)
            continue
        following = items[index + 1]
        dx = following.x - item.x
        dy = following.y - item.y
        if not -128 <= dx <= 127 or not -128 <= dy <= 127:
            raise ValueError("相邻图块坐标差必须在 -128—127 之间。")
        result.extend(
            (
                attributes | 0x2C,
                following.tile_token,
                dx & 0xFF,
                dy & 0xFF,
            )
        )
    result.append(0xFF)
    return bytes(result)


def encode_legacy_sprite_composition(
    placements: tuple[SpriteTilePlacement, ...] | list[SpriteTilePlacement],
    *,
    anchor_x: int | None = None,
    anchor_y: int | None = None,
) -> bytes:
    """Encode the compact stream emitted by the reference puzzle editor.

    Unlike :func:`encode_sprite_composition`, the reference editor keeps the
    shortest available transition: implicit tile increment, tile hold or an
    explicit tile byte, combined with the shortest matching X/Y movement.
    This is byte-for-byte stable for untouched legacy records and for the
    reference editor's whole-image flip output.
    """

    items = tuple(placements)
    if items:
        if anchor_x is None:
            anchor_x = items[0].x
        if anchor_y is None:
            anchor_y = items[0].y
    else:
        anchor_x = 0 if anchor_x is None else anchor_x
        anchor_y = 0 if anchor_y is None else anchor_y
    if not -128 <= anchor_x <= 127 or not -128 <= anchor_y <= 127:
        raise ValueError("拼图锚点必须在 -128—127 之间。")
    if not items:
        return bytes((anchor_x & 0xFF, anchor_y & 0xFF, 0x00, 0xFF))
    if (items[0].x, items[0].y) != (anchor_x, anchor_y):
        raise ValueError("首个图块坐标必须与拼图锚点一致。")

    result = bytearray((anchor_x & 0xFF, anchor_y & 0xFF, items[0].tile_token))
    for index, item in enumerate(items):
        if not 0 <= item.tile_token <= 0xFF:
            raise ValueError("图块编号必须在 $00—$FF 之间。")
        command = item.attributes & 0xC3
        parameters: list[int] = []
        if index + 1 < len(items):
            following = items[index + 1]
            if following.tile_token == ((item.tile_token + 1) & 0xFF):
                pass
            elif following.tile_token == item.tile_token:
                command |= 0x10
            else:
                command |= 0x20
                parameters.append(following.tile_token)

            dx = following.x - item.x
            dy = following.y - item.y
            if not -128 <= dx <= 127 or not -128 <= dy <= 127:
                raise ValueError("相邻图块坐标差必须在 -128—127 之间。")
            if dx == 8 and dy == 0:
                pass
            elif dy == 0:
                command |= 0x04
                parameters.append(dx & 0xFF)
            elif dy == 8:
                command |= 0x08
                parameters.append(dx & 0xFF)
            else:
                command |= 0x0C
                parameters.extend((dx & 0xFF, dy & 0xFF))
        result.append(command)
        result.extend(parameters)
    result.append(0xFF)
    return bytes(result)


def decode_sprite_timeline(
    raw: bytes,
    sprite_count: int,
    *,
    max_frames: int = 360,
) -> SpriteTimeline:
    """Run one verified frame-sequence movement rule without mutating ROM.

    This mirrors the $E8CC-$EA34 interpreter.  Axis rules and runtime-dependent
    pointer/table switches fail closed; finite and repeating frame streams are
    returned with a deterministic loop boundary for preview playback.
    """

    if max_frames <= 0:
        raise ValueError("预览帧上限必须大于零。")
    pc = 0
    repeat_counter = 0
    delay = 0
    current: int | None = None
    selector = 0x40
    frames: list[int] = []
    seen: dict[tuple[int, int, int, int | None, int], int] = {}
    instruction_budget = max(1024, max_frames * 32)

    def fail(message: str) -> SpriteTimeline:
        return SpriteTimeline(tuple(frames), None, False, False, message)

    for _ in range(max_frames):
        state = (pc, repeat_counter, delay, current, selector)
        if state in seen and frames:
            return SpriteTimeline(
                tuple(frames), seen[state], False, True, ""
            )
        seen[state] = len(frames)
        if delay:
            delay -= 1
            if current is None:
                return fail("等待指令出现在首个组图帧之前。")
            frames.append(current)
            continue

        while instruction_budget:
            instruction_budget -= 1
            if not 0 <= pc < len(raw):
                return fail(f"运行规律跳转到记录外 +${pc & 0xFF:02X}。")
            opcode = raw[pc]
            if opcode < 0xF7:
                if selector != 0x40:
                    return fail(
                        f"规律切换到资源选择器 ${selector:02X}，不属于当前组图表。"
                    )
                if opcode >= sprite_count:
                    return fail(f"组图编号 ${opcode:02X} 超出当前指针表。")
                current = opcode
                frames.append(current)
                pc += 1
                break
            if opcode == 0xF7:
                if pc + 1 >= len(raw):
                    return fail("资源选择器指令截断。")
                selector = raw[pc + 1]
                pc += 2
                continue
            if opcode == 0xF8:
                pc = 0
                continue
            if opcode == 0xF9:
                if pc + 1 >= len(raw):
                    return fail("绝对跳转指令截断。")
                pc = raw[pc + 1]
                continue
            if opcode == 0xFA:
                return fail("规律使用运行时指针页切换，离线预览不猜测目标记录。")
            if opcode == 0xFB:
                if pc + 2 >= len(raw):
                    return fail("循环指令截断。")
                count = raw[pc + 1]
                if not repeat_counter:
                    if count >= 0xFC:
                        return fail("循环次数来自运行时参数，离线预览不猜测。")
                    repeat_counter = count
                repeat_counter = (repeat_counter - 1) & 0xFF
                if not repeat_counter:
                    pc += 3
                else:
                    pc = (pc + 3 + _signed_byte(raw[pc + 2])) & 0xFF
                continue
            if opcode == 0xFC:
                if pc + 2 >= len(raw):
                    return fail("音效指令截断。")
                pc += 3
                continue
            if opcode == 0xFD:
                if pc + 1 >= len(raw):
                    return fail("音效指令截断。")
                pc += 2
                continue
            if opcode == 0xFE:
                if pc + 1 >= len(raw):
                    return fail("等待指令截断。")
                wait = raw[pc + 1]
                pc += 2
                if wait:
                    if current is None:
                        return fail("等待指令出现在首个组图帧之前。")
                    frames.append(current)
                    delay = wait - 1
                    break
                continue
            if opcode == 0xFF:
                return SpriteTimeline(tuple(frames), None, True, True, "")
        else:
            return fail("运行规律控制流超过安全步数。")

    return fail(f"运行规律在 {max_frames} 帧内未终止或形成稳定循环。")


TABLES = (
    AnimationTable("map", 0x28, 2, 0x9FFC, 153, 0xC000, 0x62, b"\xf2\x28"),
    AnimationTable("ally", 0x22, 0, 0x8020, 256, 0xC000, 0x60, b"\xf0\x22"),
    AnimationTable("enemy", 0x20, 0, 0x8020, 256, 0xC000, 0x61, b"\xf0\x20"),
    AnimationTable("background", 0x0A, 2, 0xA0C1, 106, 0xBE00, 0x23, b"\x52\x00"),
    AnimationTable("movement", 0x18, 5, 0xB390, 157, 0xBB1D, 0x68, b"\xc5\x07"),
    AnimationTable("sprite", 0x18, 3, 0x9A80, 249, 0xB390, 0x40, b"\xc3\x00"),
)
TABLE_BY_KIND = {table.kind: table for table in TABLES}

SPRITE_RESERVED_FIRST = 0xEB
SPRITE_RESERVED_USABLE_LAST = 0xF6
SPRITE_RESERVED_LAST = 0xF8
SPRITE_RESERVED_POINTER = 0xB338
SPRITE_RESERVED_END = 0xB390
SPRITE_FREE_RECORD = bytes.fromhex("00 F0 00 00 FF")
SPRITE_RESERVED_BASELINE_RECORDS = (
    bytes.fromhex("00 F0 00 F0 00 00 FF"),
    bytes.fromhex("08 08 00 F0 00 00 FF"),
    bytes.fromhex("08 08 00 F0 00 00 FF"),
    bytes.fromhex("05 05 00 F0 00 00 FF"),
    bytes.fromhex("FF FF 00 F0 00 00 FF"),
    bytes.fromhex("00 00 00 F0 00 00 FF"),
    bytes.fromhex("00 05 00 F0 00 00 FF"),
    bytes.fromhex("FA 00 00 F0 00 00 FF"),
    bytes.fromhex("FC 00 00 F0 00 00 FF"),
    SPRITE_FREE_RECORD,
    SPRITE_FREE_RECORD,
    SPRITE_FREE_RECORD,
    SPRITE_FREE_RECORD,
    SPRITE_FREE_RECORD,
)
MOVEMENT_RESERVED_FIRST = 0x7D
MOVEMENT_RESERVED_LAST = 0x9C
MOVEMENT_RESERVED_POINTER = 0xBAFD
MOVEMENT_RESERVED_END = 0xBB1D


def decode_script(raw: bytes, start: int) -> tuple[tuple[AnimationInstruction, ...], bool]:
    rows: list[AnimationInstruction] = []
    cursor = 0
    while cursor < len(raw):
        op = raw[cursor]
        size = 1
        editable: list[tuple[int, int, int]] = []
        text = ""
        tail = raw[cursor:]
        if op in (0x40, 0x42, 0xC0, 0xC2):
            size = 5
            if len(tail) >= size:
                text = (
                    f"调取物体运行规律({op:02X} {tail[1]:02X}：地图动画专用)："
                    f"取图规律号:[{tail[2]:02X}]{tail[2]:03d} "
                    f"X轴运行规律号[{tail[3]:02X}]{tail[3]:03d} "
                    f"Y轴运行规律号[{tail[4]:02X}]{tail[4]:03d}"
                )
                editable = [(i, 0, 255) for i in range(1, size)]
        elif op < 0xE0:
            text = f"等待：{op:03d}帧" if op else "等待：256帧"
            editable = [(0, 1, 0xDF)]
        elif op in (0xE0, 0xE1):
            size = 2
            if len(tail) >= size:
                text = f"切换{op - 0xE0:02X}区域的图库号：图库编号:{tail[1]:02X}"
                editable = [(1, 0, 255)]
        elif op in (0xF0, 0xF2):
            size = 3 + tail[2] if len(tail) >= 3 else len(tail) + 1
            if len(tail) >= size and tail[2]:
                values = tail[3:size]
                if op == 0xF0:
                    color_kind = "物理" if tail[1] == 0x11 else "光束"
                    text = (
                        f"调用颜色（{color_kind}）：颜色三字节:"
                        + " ".join(f"{value:02X}" for value in values)
                    )
                    editable = [(i, 0, 0x3F) for i in range(3, size) if tail[i] < 0x40]
                else:
                    text = (
                        f"切换光束图库：区域 {tail[1]:02X}，"
                        + "图库 " + " ".join(f"{value:02X}" for value in values)
                    )
                    editable = [(i, 0, 255) for i in range(3, size)]
        elif op == 0xF1:
            size = 2
            if len(tail) >= size:
                text = f"刷新调色板/显示状态：{tail[1]:02X}"
        elif op == 0xF3:
            size = 3
            if len(tail) >= size:
                text = f"调用背景规律：背景 {tail[1]:02X}，规律 {tail[2]:02X}"
        elif op == 0xF4:
            size = 2
            if len(tail) >= size:
                text = f"调用音乐：音乐代码:{tail[1]:02X}"
                editable = [(1, 0, 255)]
        elif op in (0xF5, 0xF7):
            size = 3
            if len(tail) >= size:
                text = (
                    f"物体坐标：编号 {tail[1]:02X}，位置 {tail[2]:02X}"
                    if op == 0xF5
                    else (
                        f"设置背景位置：状态代码:{tail[1]:02X} "
                        f"X轴偏移:{_signed_byte(tail[2]):+d}"
                    )
                )
                if op == 0xF5:
                    editable = [(2, 0, 255)]
                else:
                    # F7 is a fixed three-byte command in the verified map
                    # interpreter.  Byte 1 selects the background state and
                    # stays locked; byte 2 is the signed horizontal offset.
                    editable = [(2, 0, 255)]
        elif op in (0xF6, 0xFA, 0xFB, 0xFC):
            size = 2
            if len(tail) >= size:
                text = {0xF6: "设置屏幕属性", 0xFA: "删除物体", 0xFB: "隐藏物体", 0xFC: "显示物体"}[op] + f"：编号 {tail[1]:02X}"
        elif op in (0xF8, 0xF9):
            if len(tail) >= 2:
                # C583 reads its value from the event argument queue without
                # consuming script bytes when coordinate flag bits are set on
                # F8.  The reference weapon editor proves that F9 always
                # stores both entered coordinates, for every object value.
                coordinates = (
                    2
                    if op == 0xF9
                    else 2 - bool(tail[1] & 0x80) - bool(tail[1] & 0x40)
                )
                size = 2 + coordinates
                if len(tail) >= size:
                    coordinates_text = (
                        "坐标由事件传入"
                        if coordinates == 0
                        else (
                            f"物体X坐标:{tail[2]:03d} "
                            + (f"物体Y坐标:{tail[3]:03d}" if coordinates > 1 else "物体Y坐标:由事件传入")
                        )
                    )
                    text = (
                        f"创建物体： 物体编号:{tail[1]:02X} "
                        f"{coordinates_text}"
                    )
                    editable = [(i, 0, 255) for i in range(2, 2 + coordinates)]
        elif op == 0xFD:
            size = 3
            if len(tail) >= size:
                text = f"移动屏幕：X {int.from_bytes(tail[1:2], signed=True)}，Y {int.from_bytes(tail[2:3], signed=True)}"
                editable = [(1, 0, 255), (2, 0, 255)]
        elif op == 0xFE:
            size = 4
            if len(tail) >= size:
                text = f"循环 {tail[1]} 次：返回前面的循环起点"
                editable = [(1, 1, 255)]
        elif op == 0xFF:
            rows.append(AnimationInstruction(start + cursor, b"\xff", "动画结束"))
            return tuple(rows), True
        if not text or cursor + size > len(raw):
            rows.append(AnimationInstruction(start + cursor, tail, "这条动画指令尚未完整识别，后续内容保持不变"))
            return tuple(rows), False
        rows.append(AnimationInstruction(start + cursor, tail[:size], text, tuple(editable)))
        cursor += size
    return tuple(rows), False


def legacy_script_lines(instruction: AnimationInstruction) -> tuple[str, ...]:
    """Return the exact reference-style visible lines for one decoded command.

    The legacy editor suppresses F1 refresh commands and expands F8/F9 into a
    creation line plus a movement-rule line.  This is presentation only; the
    decoder and writer retain the real instruction boundary.
    """

    raw = instruction.raw
    if not raw:
        return (instruction.text,)
    if raw[0] == 0xF1:
        return ()
    return (instruction.text,)


def decode_background_rule(
    raw: bytes,
    start: int = 0,
) -> tuple[tuple[AnimationInstruction, ...], bool]:
    """Decode the statically bounded subset of the background-drawing VM.

    The byte fetch at $D3E8 dispatches $F0-$FF through the table at $D3F7;
    values below $EE are literal drawing data.  $EE has one fixed operand;
    $F5 and the non-rebasing branch of $FB have lengths proven by their flag
    bytes.  $EF and the pointer-rebasing $FA/$FB paths still depend on runtime
    state, so decoding stops rather than guessing past them.  Only literal
    drawing bytes and the two fixed operands of $F8/$F9 are exposed as
    parameters.  Every opcode, resource selector, pointer and variable-width
    flag stays immutable.
    """

    rows: list[AnimationInstruction] = []
    cursor = 0
    while cursor < len(raw):
        op = raw[cursor]
        tail = raw[cursor:]
        size = 1
        text = ""
        editable: tuple[tuple[int, int, int], ...] = ()

        if op < 0xEE:
            text = f"绘制数据：${op:02X}"
            editable = ((0, 0x00, 0xED),)
        elif op == 0xEE:
            size = 2
            text = "设置运行时绘制索引"
        elif op == 0xEF:
            text = "动态地址分派：后续边界不作静态推测"
        elif op == 0xF0:
            size = 2
            text = "设置行列等待参数"
        elif op == 0xF1:
            text = "提交当前绘制行"
        elif op == 0xF2:
            size = 2
            text = "设置绘制偏移"
        elif op == 0xF3:
            size = 3
            text = "设置绘制起点"
        elif op == 0xF4:
            if len(tail) < 4:
                size = len(tail) + 1
            else:
                size = 4 + bool(tail[3] & 0x40)
            text = "设置矩形绘制参数"
        elif op == 0xF5:
            if len(tail) < 2 or tail[1] == 0xFF:
                text = "运行时长度的填充指令：后续边界不作静态推测"
            else:
                size = 3 if tail[1] & 0x10 else 4
                text = "设置填充绘制参数"
        elif op == 0xF6:
            size = 2
            text = "开始重复块"
        elif op == 0xF7:
            text = "结束重复块"
        elif op in (0xF8, 0xF9):
            size = 3
            text = "设置逐步绘制参数"
            editable = ((1, 0x00, 0xFF), (2, 0x00, 0xFF))
        elif op == 0xFA:
            text = "切换到内嵌数据指针：后续边界不作静态推测"
        elif op == 0xFB:
            if len(tail) < 3 or tail[2] & 0x80:
                text = "内嵌指针逐步绘制：后续边界不作静态推测"
            else:
                size = 5
                text = "设置连续逐步绘制参数"
        elif op == 0xFC:
            size = 3
            text = "调用背景资源"
        elif op == 0xFD:
            if len(tail) < 2:
                size = len(tail) + 1
            else:
                flags = tail[1]
                size = 2 + bool(flags & 0x20) + bool(flags & 0x10)
            text = "设置背景状态"
        elif op == 0xFE:
            if len(tail) < 2 or tail[1] == 0xFF:
                text = "运行时布局头：后续边界不作静态推测"
            else:
                size = 3 + bool(tail[1] & 0x20)
                text = "设置背景布局"
        else:
            rows.append(
                AnimationInstruction(start + cursor, b"\xFF", "背景规律结束")
            )
            return tuple(rows), True

        if (
            op in (0xEF, 0xFA)
            or (op == 0xF5 and (len(tail) < 2 or tail[1] == 0xFF))
            or (op == 0xFB and (len(tail) < 3 or tail[2] & 0x80))
            or (op == 0xFE and (len(tail) < 2 or tail[1] == 0xFF))
            or cursor + size > len(raw)
        ):
            rows.append(AnimationInstruction(start + cursor, tail, text))
            return tuple(rows), False
        rows.append(
            AnimationInstruction(
                start + cursor,
                tail[:size],
                text,
                editable,
            )
        )
        cursor += size
    return tuple(rows), False


class AnimationCodec:
    """Read current pointers, guard the interpreter, and produce bounded edits."""

    def __init__(self, data: bytes | bytearray) -> None:
        self.data = bytes(data)
        self._calls_cache: tuple[tuple[int, int], ...] | None = None
        if self.data[:4] != b"NES\x1a" or len(self.data) < 0x80010:
            raise ValueError("当前 ROM 不具备已验证的 DC 动画资源。")
        self.fixed = 16 + (self.data[4] * 2 - 1) * 0x2000
        signatures = (
            (0xE84A, "90 25 29 0F 20 C8 C4"),
            (0xEC21, "C8 B1 90 85 4C C8 4C 87 E8"),
            (0xFEDB, "B1 90 C9 E0 D0 0A C8 B1 90 8D D8 04"),
            (0xFD4F, "A5 18 0A AA B0 06 BD E2 F3 4C 4D FE"),
            (0xF7C8, "AC 7F 7F F0 03 4C 8D F7 C9 EE D0 03 4C 2F FF C9 EF"),
        )
        for address, expected in signatures:
            offset = self.fixed + address - 0xE000
            value = bytes.fromhex(expected)
            if self.data[offset:offset + len(value)] != value:
                raise ValueError(f"动画解释器 ${address:04X} 与已验证格式不同。")
        background_fixed = self.fixed - 0x2000
        background_signatures = (
            (
                0xD39E,
                "AD 01 06 29 08 D0 F8 A6 72 E4 73 B0 F2 A5 A8 20 8B FD",
            ),
            (
                0xD3F7,
                "FD D4 33 D5 36 D5 42 D5 8E D5 13 D6 8E D6 D0 D6 "
                "F9 D6 22 D7 4D D7 7B D7 BC D7 67 D8 BA D8 D9 D8",
            ),
            (0xD6F9, "A4 05 B1 8C D0 03 20 83 C5 8D 02 06 E6 05"),
            (0xD613, "20 FC DC A4 05 B1 8C C9 FF D0 0E 20 83 C5"),
            (0xD77B, "A4 05 B1 8C D0 03 20 83 C5 8D 02 06 E6 05"),
            (0xD7BC, "A4 05 B1 8C C9 FF D0 03 20 83 C5 85 18 E6 05"),
            (0xD8BA, "20 FC DC 20 CD DE E6 05 A5 0F 29 20 F0 09"),
            (0xDECD, "A4 05 B1 8C C9 FF D0 0D 20 83 C5 85 00 85 0F"),
        )
        for address, expected in background_signatures:
            offset = background_fixed + address - 0xC000
            value = bytes.fromhex(expected)
            if self.data[offset:offset + len(value)] != value:
                raise ValueError(
                    f"背景规律解释器 ${address:04X} 与已验证格式不同。"
                )
        self.pointers: dict[str, tuple[int, ...]] = {}
        for table in TABLES:
            descriptor_offset = self.fixed + 0x13E2 + table.selector * 2
            if self.data[descriptor_offset:descriptor_offset + 2] != table.descriptor:
                raise ValueError(f"{table.kind} 动画资源描述符已变化。")
            directory = 16 + table.pair * 0x2000 + table.directory * 2
            if struct.unpack_from("<H", self.data, directory)[0] != table.table:
                raise ValueError(f"{table.kind} 动画目录指针已变化。")
            pointers = struct.unpack_from(f"<{table.count}H", self.data, table.offset(table.table))
            lower = table.table + table.count * 2
            if any(p and not lower <= p < table.end for p in pointers):
                raise ValueError(f"{table.kind} 动画表含越界指针。")
            self.pointers[table.kind] = pointers

    def count(self, kind: str) -> int:
        return len(self.pointers[kind])

    def record(self, kind: str, index: int) -> AnimationRecord:
        table = TABLE_BY_KIND[kind]
        pointers = self.pointers[kind]
        pointer = pointers[index]
        if not pointer:
            return AnimationRecord(kind, index, 0, b"", (), (), False)
        end = min((p for p in pointers if p > pointer), default=table.end)
        offset = table.offset(pointer)
        raw = self.data[offset:table.offset(end)]
        aliases = tuple(i for i, p in enumerate(pointers) if p == pointer and i != index)
        if kind in ("map", "ally", "enemy"):
            rows, complete = decode_script(raw, offset)
            if complete:
                raw = raw[:sum(len(row.raw) for row in rows)]
        else:
            rows, complete = (), False
        return AnimationRecord(kind, index, offset, raw, aliases, rows, complete)

    def script_patch(self, record: AnimationRecord, replacement: bytes) -> BytePatch:
        current = self.record(record.kind, record.index)
        if current != record:
            raise ValueError("动画原值已变化，请重新载入。")
        if len(replacement) != len(record.raw):
            raise ValueError(f"仅支持等长编辑：当前记录必须保持 {len(record.raw)} 字节。")
        allowed: dict[int, tuple[int, int]] = {}
        for row in record.instructions:
            for local, low, high in row.editable:
                allowed[row.offset - record.offset + local] = (low, high)
        for index, (before, after) in enumerate(zip(record.raw, replacement)):
            if before == after:
                continue
            if index not in allowed:
                raise ValueError(f"+${index:04X} 是指令、引用或尚未验证的参数，不能改写。")
            low, high = allowed[index]
            if not low <= after <= high:
                raise ValueError(f"+${index:04X} 的参数须在 ${low:02X}–${high:02X}。")
        decoded, complete = decode_script(replacement, record.offset)
        if complete != record.complete or tuple(len(x.raw) for x in decoded) != tuple(len(x.raw) for x in record.instructions):
            raise ValueError("编辑改变了动画指令边界。")
        return record.offset, record.raw, bytes(replacement)

    def script_capacity(self, record: AnimationRecord) -> int:
        """Return the pointer-bounded byte allocation owned by one script."""

        if record.kind not in ("map", "ally", "enemy"):
            raise ValueError("当前资源不是动画脚本。")
        current = self.record(record.kind, record.index)
        if current != record:
            raise ValueError("动画原值已变化，请重新载入。")
        table = TABLE_BY_KIND[record.kind]
        pointer = self.pointers[record.kind][record.index]
        if not pointer:
            return 0
        end = min(
            (candidate for candidate in self.pointers[record.kind] if candidate > pointer),
            default=table.end,
        )
        return end - pointer

    def script_pool_usage(self, kind: str) -> AnimationPoolUsage:
        """Return actual instruction usage for one verified script pool.

        Pointer gaps are not treated as occupied.  Structural writes repack
        complete records, so every such gap is reusable capacity.
        """

        if kind not in ("map", "ally", "enemy"):
            raise ValueError("当前资源不是动画脚本。")
        table = TABLE_BY_KIND[kind]
        pointers = self.pointers[kind]
        unique = sorted(set(pointer for pointer in pointers if pointer))
        records = [self.record(kind, pointers.index(pointer)) for pointer in unique]
        if any(not record.complete for record in records):
            raise ValueError("动画池含未验证或截断记录，不能计算可重排空间。")
        capacity = table.end - (table.table + table.count * 2)
        used = sum(len(record.raw) for record in records)
        return AnimationPoolUsage(capacity, used, capacity - used, len(records))

    def script_sequence_patch(
        self,
        record: AnimationRecord,
        replacement: bytes,
    ) -> BytePatch:
        """Repack a complete script pool and relocate every proven ``FE`` target.

        Map/ally/enemy scripts share a pointer-bounded pool.  Repacking all
        unique records makes holes left by shorter records reusable instead of
        imposing the old record's length on later edits.  Pointer aliases are
        preserved exactly.  Any absolute loop target that no longer resolves
        to a proven instruction boundary aborts the whole operation.
        """

        current = self.record(record.kind, record.index)
        if current != record:
            raise ValueError("动画原值已变化，请重新载入。")
        if not current.complete:
            raise ValueError("当前动画含未验证或截断指令，不能进行结构编辑。")
        decoded, complete = decode_script(replacement, record.offset)
        consumed = sum(len(instruction.raw) for instruction in decoded)
        if not complete or consumed != len(replacement):
            raise ValueError("动画必须由完整指令组成，并以 FF 动画结束结束。")
        table = TABLE_BY_KIND[record.kind]
        pointers = self.pointers[record.kind]
        selected_pointer = pointers[record.index]
        unique_pointers = sorted(set(pointer for pointer in pointers if pointer))
        records = {
            pointer: self.record(record.kind, pointers.index(pointer))
            for pointer in unique_pointers
        }
        if any(not item.complete for item in records.values()):
            raise ValueError("动画池含未验证或截断记录，不能安全重排。")
        pool_start = table.table + table.count * 2
        required = sum(
            len(replacement) if pointer == selected_pointer else len(item.raw)
            for pointer, item in records.items()
        )
        capacity = table.end - pool_start
        if required > capacity:
            raise ValueError(
                f"动画区总容量 {capacity} 字节，当前修改需要 {required} 字节，"
                f"还差 {required - capacity} 字节。"
            )

        new_pointers: dict[int, int] = {}
        cursor = pool_start
        for pointer in unique_pointers:
            new_pointers[pointer] = cursor
            cursor += len(replacement) if pointer == selected_pointer else len(records[pointer].raw)

        # Map every old, proven instruction boundary to its new location.
        # The edited record uses whole-command matching so deleting a loop
        # destination fails closed rather than silently retargeting it.
        boundary_map: dict[int, int] = {}
        for pointer, item in records.items():
            destination = new_pointers[pointer]
            if pointer != selected_pointer:
                for row in item.instructions:
                    boundary_map[pointer + row.offset - item.offset] = (
                        destination + row.offset - item.offset
                    )
                boundary_map[pointer + len(item.raw)] = destination + len(item.raw)
                continue
            boundary_map[pointer] = destination
            matcher = SequenceMatcher(
                a=[row.raw for row in item.instructions],
                b=[row.raw for row in decoded],
                autojunk=False,
            )
            for old_at, new_at, size in matcher.get_matching_blocks():
                for step in range(size):
                    old_row = item.instructions[old_at + step]
                    new_row = decoded[new_at + step]
                    boundary_map[pointer + old_row.offset - item.offset] = (
                        destination + new_row.offset - record.offset
                    )
            boundary_map[pointer + len(item.raw)] = destination + len(replacement)

        def relocate_target(target: int) -> int:
            if pool_start <= target < table.end:
                try:
                    return boundary_map[target]
                except KeyError as error:
                    raise ValueError(
                        f"动画循环目标 CPU ${target:04X} 对应的指令已删除或无法唯一识别。"
                    ) from error
            return target

        pointer_table_offset = table.offset(table.table)
        span_end = table.offset(table.end)
        before = bytes(self.data[pointer_table_offset:span_end])
        after = bytearray(len(before))
        rebased = tuple(new_pointers.get(pointer, 0) for pointer in pointers)
        struct.pack_into(f"<{len(rebased)}H", after, 0, *rebased)
        for pointer in unique_pointers:
            source_record = records[pointer]
            raw = bytearray(
                replacement if pointer == selected_pointer else source_record.raw
            )
            rows = decoded if pointer == selected_pointer else source_record.instructions
            source_start = record.offset if pointer == selected_pointer else source_record.offset
            for instruction in rows:
                if instruction.raw[:1] != b"\xFE" or len(instruction.raw) != 4:
                    continue
                local = instruction.offset - source_start
                target = int.from_bytes(instruction.raw[2:4], "little")
                raw[local + 2:local + 4] = relocate_target(target).to_bytes(2, "little")
            destination = table.offset(new_pointers[pointer]) - pointer_table_offset
            after[destination:destination + len(raw)] = raw
        return pointer_table_offset, before, bytes(after)

    def script_insert_end_patch(
        self,
        record: AnimationRecord,
        instruction_index: int,
    ) -> BytePatch:
        """Reproduce the reference editor's immediate ``FF`` insertion.

        The old editor does not replace every alias of a shared script.  It
        inserts a private physical copy at the selected pointer, places the
        new terminator before the selected command, and moves the original
        pool (including the shared source record) after that copy.  The
        selected directory entry keeps its address; every other entry at or
        after that address moves by the private allocation size.  This is a
        distinct storage operation from the normal compacting editor.
        """

        current = self.record(record.kind, record.index)
        if current != record:
            raise ValueError("动画原值已变化，请重新载入。")
        if record.kind not in ("ally", "enemy"):
            raise ValueError("旧版 FF 独立化写法只在双方武器动画中完成验证。")
        if not current.complete or not current.raw:
            raise ValueError("当前动画含未验证或截断指令，不能插入结束指令。")
        if not 0 <= instruction_index < len(current.instructions):
            raise ValueError("请选择有效的动画指令位置。")

        selected_row = current.instructions[instruction_index]
        if selected_row.raw == b"\xFF":
            raise ValueError("所选位置已经是动画结束。")
        insert_at = selected_row.offset - current.offset
        private = current.raw[:insert_at] + b"\xFF" + current.raw[insert_at:]
        shared = bool(current.aliases)
        # A shared source must remain available for its aliases, so the old
        # editor inserts a complete private allocation before it.  A unique
        # source only needs the new one-byte terminator inserted in place.
        delta = len(private) if shared else 1

        table = TABLE_BY_KIND[record.kind]
        pointers = self.pointers[record.kind]
        selected_pointer = pointers[record.index]
        unique_pointers = sorted(set(pointer for pointer in pointers if pointer))
        records = {
            pointer: self.record(record.kind, pointers.index(pointer))
            for pointer in unique_pointers
        }
        if any(not item.complete for item in records.values()):
            raise ValueError("动画池含未验证或截断记录，不能安全搬移。")

        used_end = max(item.offset + len(item.raw) for item in records.values())
        pool_end = table.offset(table.end)
        if used_end + delta > pool_end:
            free = pool_end - used_end
            raise ValueError(
                f"动画区尾部只剩 {free} 字节，旧版独立化写入需要 {delta} 字节，"
                f"还差 {delta - free} 字节。"
            )

        pointer_table_offset = table.offset(table.table)
        span_end = used_end + delta
        before = bytes(self.data[pointer_table_offset:span_end])
        after = bytearray(before)

        rebased = tuple(
            pointer
            if not pointer or pointer < selected_pointer or index == record.index
            else pointer + delta
            for index, pointer in enumerate(pointers)
        )
        struct.pack_into(f"<{len(rebased)}H", after, 0, *rebased)

        selected_local = current.offset - pointer_table_offset
        if shared:
            source_pool = self.data[current.offset:used_end]
            after[selected_local:selected_local + delta] = private
            after[
                selected_local + delta:selected_local + delta + len(source_pool)
            ] = source_pool
        else:
            insertion_local = selected_local + insert_at
            source_pool = self.data[current.offset + insert_at:used_end]
            after[insertion_local] = 0xFF
            after[
                insertion_local + 1:insertion_local + 1 + len(source_pool)
            ] = source_pool

        def relocate_target(target: int) -> int:
            relocation_start = (
                selected_pointer if shared else selected_pointer + insert_at
            )
            if target >= relocation_start and target < table.end:
                return target + delta
            return target

        # Relocate every active loop in the original pool.  Records before
        # the insertion keep their physical position but may target a moved
        # record; records at/after it move with the original pool.
        for pointer, item in records.items():
            destination = item.offset + (
                delta
                if (pointer >= selected_pointer if shared else pointer > selected_pointer)
                else 0
            )
            for instruction in item.instructions:
                if instruction.raw[:1] != b"\xFE" or len(instruction.raw) != 4:
                    continue
                local = instruction.offset - item.offset
                target = int.from_bytes(instruction.raw[2:4], "little")
                target = relocate_target(target)
                instruction_shift = (
                    delta
                    if not shared
                    and pointer == selected_pointer
                    and local >= insert_at
                    else 0
                )
                destination_local = (
                    destination - pointer_table_offset + local + instruction_shift
                )
                after[destination_local + 2:destination_local + 4] = target.to_bytes(
                    2, "little"
                )

        # Only the prefix before the inserted FF remains executable in the
        # private copy.  Its absolute loop targets must follow the moved pool;
        # the unreachable suffix is intentionally retained byte-for-byte,
        # matching the reference editor's physical output.
        for instruction in (
            current.instructions[:instruction_index] if shared else ()
        ):
            if instruction.raw[:1] != b"\xFE" or len(instruction.raw) != 4:
                continue
            local = instruction.offset - current.offset
            target = int.from_bytes(instruction.raw[2:4], "little")
            target = relocate_target(target)
            destination_local = selected_local + local
            after[destination_local + 2:destination_local + 4] = target.to_bytes(
                2, "little"
            )

        return pointer_table_offset, before, bytes(after)

    def legacy_weapon_sequence_patch(
        self,
        record: AnimationRecord,
        replacement: bytes,
    ) -> BytePatch:
        """Rebuild a weapon script pool exactly like the reference editor.

        The reference database does not preserve pointer identity when a
        weapon animation is structurally edited.  On confirmation it walks
        weapon records in numeric order, writes the first occurrence of each
        complete byte sequence, and makes later byte-identical records reuse
        that address.  Consequently editing one member of a shared pointer is
        copy-on-write, while ``paste all`` and ``clear`` can merge records
        whose resulting scripts are identical.  This differs deliberately
        from :meth:`script_sequence_patch`, whose modern map-animation policy
        preserves existing aliases.
        """

        current = self.record(record.kind, record.index)
        if current != record:
            raise ValueError("动画原值已变化，请重新载入。")
        if record.kind not in ("ally", "enemy"):
            raise ValueError("旧版武器动画重排只适用于我方或敌方武器动画。")
        if not current.complete:
            raise ValueError("当前动画含未验证或截断指令，不能进行结构编辑。")
        decoded, complete = decode_script(replacement, record.offset)
        if not complete or sum(len(row.raw) for row in decoded) != len(replacement):
            raise ValueError("动画必须由完整指令组成，并以 FF 动画结束结束。")

        table = TABLE_BY_KIND[record.kind]
        pointers = self.pointers[record.kind]
        records_by_pointer = {
            pointer: self.record(record.kind, pointers.index(pointer))
            for pointer in set(pointers) if pointer
        }
        if any(not item.complete for item in records_by_pointer.values()):
            raise ValueError("动画池含未验证或截断记录，不能安全重排。")

        # First pass: reproduce the old editor's index-order allocation and
        # whole-script content deduplication.
        pool_start = table.table + table.count * 2
        cursor = pool_start
        content_pointer: dict[bytes, int] = {}
        rebased: list[int] = []
        allocations: list[tuple[int, bytes, AnimationRecord, bool]] = []
        for index, pointer in enumerate(pointers):
            if not pointer:
                rebased.append(0)
                continue
            source = records_by_pointer[pointer]
            raw = bytes(replacement if index == record.index else source.raw)
            destination = content_pointer.get(raw)
            if destination is None:
                destination = cursor
                content_pointer[raw] = destination
                cursor += len(raw)
                allocations.append((destination, raw, source, index == record.index))
            rebased.append(destination)

        if cursor > table.end:
            capacity = table.end - pool_start
            required = cursor - pool_start
            raise ValueError(
                f"动画区总容量 {capacity} 字节，当前修改需要 {required} 字节，"
                f"还差 {required - capacity} 字节。"
            )

        # Old absolute FE targets identify instruction boundaries in the old
        # pool.  Prefer an unchanged alias when the edited record was shared;
        # otherwise map the selected record through matching commands.
        global_boundaries: dict[int, int] = {}
        for old_pointer, source in records_by_pointer.items():
            unchanged_index = next(
                (
                    index for index, pointer in enumerate(pointers)
                    if pointer == old_pointer and index != record.index
                ),
                None,
            )
            if unchanged_index is not None:
                destination = rebased[unchanged_index]
                for row in source.instructions:
                    global_boundaries[old_pointer + row.offset - source.offset] = (
                        destination + row.offset - source.offset
                    )
                global_boundaries[old_pointer + len(source.raw)] = (
                    destination + len(source.raw)
                )
            elif old_pointer != pointers[record.index]:
                index = pointers.index(old_pointer)
                destination = rebased[index]
                for row in source.instructions:
                    global_boundaries[old_pointer + row.offset - source.offset] = (
                        destination + row.offset - source.offset
                    )
                global_boundaries[old_pointer + len(source.raw)] = (
                    destination + len(source.raw)
                )

        selected_destination = rebased[record.index]
        selected_boundaries: dict[int, int] = dict(global_boundaries)
        selected_boundaries[pointers[record.index]] = selected_destination
        matcher = SequenceMatcher(
            a=[row.raw for row in current.instructions],
            b=[row.raw for row in decoded],
            autojunk=False,
        )
        for old_at, new_at, size in matcher.get_matching_blocks():
            for step in range(size):
                old_row = current.instructions[old_at + step]
                new_row = decoded[new_at + step]
                selected_boundaries[
                    pointers[record.index] + old_row.offset - current.offset
                ] = selected_destination + new_row.offset - record.offset
        selected_boundaries[pointers[record.index] + len(current.raw)] = (
            selected_destination + len(replacement)
        )

        old_used_end = max(
            item.offset + len(item.raw) for item in records_by_pointer.values()
        )
        pointer_table_offset = table.offset(table.table)
        span_end = max(old_used_end, table.offset(cursor))
        before = bytes(self.data[pointer_table_offset:span_end])
        after = bytearray(before)
        struct.pack_into(f"<{len(rebased)}H", after, 0, *rebased)
        # When content deduplication shortens the pool, the reference editor
        # clears the released tail rather than leaving the former script
        # bytes behind.  This is observable in its whole-ROM save output.
        new_used_end = table.offset(cursor)
        if new_used_end < old_used_end:
            tail_start = new_used_end - pointer_table_offset
            tail_end = old_used_end - pointer_table_offset
            after[tail_start:tail_end] = b"\x00" * (tail_end - tail_start)

        for destination, source_raw, source, is_selected in allocations:
            raw = bytearray(source_raw)
            rows = decoded if is_selected else source.instructions
            source_start = record.offset if is_selected else source.offset
            boundaries = selected_boundaries if is_selected else global_boundaries
            for instruction in rows:
                if instruction.raw[:1] != b"\xFE" or len(instruction.raw) != 4:
                    continue
                local = instruction.offset - source_start
                target = int.from_bytes(instruction.raw[2:4], "little")
                if pool_start <= target < table.end:
                    try:
                        target = boundaries[target]
                    except KeyError as error:
                        raise ValueError(
                            f"动画循环目标 CPU ${target:04X} 对应的指令已删除或无法唯一识别。"
                        ) from error
                raw[local + 2:local + 4] = target.to_bytes(2, "little")
            local = table.offset(destination) - pointer_table_offset
            after[local:local + len(raw)] = raw

        return pointer_table_offset, before, bytes(after)

    def clone_map_animation_patches(
        self,
        source_index: int,
    ) -> tuple[int, tuple[BytePatch, BytePatch]]:
        """Materialize the next reserved map slot as a relocated script copy."""

        table = TABLE_BY_KIND["map"]
        pointers = self.pointers["map"]
        if not 0 <= source_index < len(pointers):
            raise ValueError("请选择有效的地图动画。")
        source = self.record("map", source_index)
        if not source.complete or not source.raw:
            raise ValueError("当前动画没有完整结束码，不能复制。")

        referenced = {animation_id for _offset, animation_id in self.calls()}
        reserved = [
            index
            for index in range(0x3F, len(pointers))
            if index not in referenced
            and self.record("map", index).raw == b"\xFF"
            and self.record("map", index).aliases
        ]
        if not reserved:
            raise ValueError("地图动画预留槽已用完。")
        new_index = reserved[0]

        occupied: list[tuple[int, int]] = []
        seen: set[int] = set()
        for index, pointer in enumerate(pointers):
            if not pointer or pointer in seen:
                continue
            seen.add(pointer)
            record = self.record("map", index)
            if record.raw:
                occupied.append((record.offset, record.offset + len(record.raw)))
        occupied.sort()
        pool_start = table.offset(table.table + table.count * 2)
        pool_end = table.offset(table.end)
        cursor = pool_start
        destination_offset: int | None = None
        for start, end in occupied + [(pool_end, pool_end)]:
            if start - cursor >= len(source.raw):
                candidate = self.data[cursor:cursor + len(source.raw)]
                if candidate == bytes(len(source.raw)):
                    destination_offset = cursor
                    break
            cursor = max(cursor, end)
        if destination_offset is None:
            raise ValueError(
                f"地图动画池没有 {len(source.raw)} 字节的连续已验证空区。"
            )

        pair_offset = 16 + table.pair * 0x2000
        destination_pointer = destination_offset - pair_offset + 0x8000
        source_pointer = pointers[source_index]
        relocated = bytearray(source.raw)
        for instruction in source.instructions:
            if instruction.raw[:1] != b"\xFE" or len(instruction.raw) != 4:
                continue
            target = int.from_bytes(instruction.raw[2:4], "little")
            if not source_pointer <= target < source_pointer + len(source.raw):
                raise ValueError(
                    f"动画 ${source_index:02X} 含指向记录外 ${target:04X} 的循环，不能安全复制。"
                )
            relocated_target = destination_pointer + target - source_pointer
            local = instruction.offset - source.offset
            relocated[local + 2:local + 4] = relocated_target.to_bytes(2, "little")
        decoded, complete = decode_script(bytes(relocated), destination_offset)
        if not complete or sum(len(row.raw) for row in decoded) != len(relocated):
            raise ValueError("复制后的动画未通过指令边界校验。")

        pointer_offset = table.offset(table.table) + new_index * 2
        return new_index, (
            (
                pointer_offset,
                self.data[pointer_offset:pointer_offset + 2],
                destination_pointer.to_bytes(2, "little"),
            ),
            (
                destination_offset,
                self.data[destination_offset:destination_offset + len(relocated)],
                bytes(relocated),
            ),
        )

    def clone_sprite_rule_patches(
        self,
        source_index: int,
    ) -> tuple[int, tuple[BytePatch, BytePatch]]:
        """Copy one complete composition into the verified reserved tail.

        Slots $EB-$F6 remain valid frame operands.  $F7/$F8 are movement
        interpreter control opcodes, so they are retained only as aliases of
        the five-byte terminal dummy.  Allocations grow backwards from that
        dummy; this keeps every allocated record bounded by the next pointer
        without moving any live composition.
        """

        table = TABLE_BY_KIND["sprite"]
        pointers = self.pointers["sprite"]
        if not 0 <= source_index < len(pointers):
            raise ValueError("请选择有效的组图规律。")
        source = self.record("sprite", source_index)
        composition = decode_sprite_composition(source.raw, source.offset)
        if not composition.complete or composition.consumed != len(source.raw):
            raise ValueError("当前组图没有完整且唯一的结束边界，不能复制。")

        reserved_indices = tuple(
            range(SPRITE_RESERVED_FIRST, SPRITE_RESERVED_LAST + 1)
        )
        usable_indices = tuple(
            range(SPRITE_RESERVED_FIRST, SPRITE_RESERVED_USABLE_LAST + 1)
        )
        pointer_offset = table.offset(table.table) + SPRITE_RESERVED_FIRST * 2
        pool_offset = table.offset(SPRITE_RESERVED_POINTER)
        pool_end_offset = table.offset(SPRITE_RESERVED_END)
        dummy_pointer = SPRITE_RESERVED_END - len(SPRITE_FREE_RECORD)
        current_pointers = tuple(pointers[index] for index in reserved_indices)
        current_pool = self.data[pool_offset:pool_end_offset]

        expected_pointers: list[int] = []
        cursor = SPRITE_RESERVED_POINTER
        for raw in SPRITE_RESERVED_BASELINE_RECORDS:
            expected_pointers.append(cursor)
            cursor += len(raw)
        if cursor != SPRITE_RESERVED_END:
            raise AssertionError("组图预留尾区基线定义不完整。")
        pristine = (
            current_pointers == tuple(expected_pointers)
            and current_pool == b"".join(SPRITE_RESERVED_BASELINE_RECORDS)
        )

        frame_references: set[int] = set()
        roles = self.movement_roles()
        for index, role in roles.items():
            if role != {"frames"}:
                continue
            record = self.record("movement", index)
            timeline = decode_sprite_timeline(record.raw, self.count("sprite"))
            frame_references.update(timeline.frames)
            # Runtime-dependent streams fail closed.  Treat every reserved
            # byte in a frame record as a reference even when it is an operand;
            # a false positive only keeps a slot unavailable.
            frame_references.update(
                value
                for value in record.raw
                if SPRITE_RESERVED_FIRST
                <= value
                <= SPRITE_RESERVED_USABLE_LAST
            )

        if pristine:
            allocated: dict[int, int] = {}
        else:
            if any(
                not SPRITE_RESERVED_POINTER <= pointer <= dummy_pointer
                for pointer in current_pointers
            ):
                raise ValueError("组图预留尾区指针已变化，不能继续分配。")
            if any(
                pointers[index] != dummy_pointer
                for index in range(
                    SPRITE_RESERVED_USABLE_LAST + 1,
                    SPRITE_RESERVED_LAST + 1,
                )
            ):
                raise ValueError("组图控制码保留槽没有指向安全空记录。")
            allocated = {
                index: pointers[index]
                for index in usable_indices
                if pointers[index] != dummy_pointer
            }
            if len(set(allocated.values())) != len(allocated):
                raise ValueError("已分配组图预留槽含共享指针，不能继续搬移。")
            lowest_pointer = min(allocated.values(), default=dummy_pointer)
            prefix = self.data[
                pool_offset : table.offset(lowest_pointer)
            ]
            if prefix != bytes((0xFF,)) * len(prefix):
                raise ValueError("组图预留尾区的剩余空间不再是全 FF。")
            for index in allocated:
                record = self.record("sprite", index)
                decoded = decode_sprite_composition(record.raw, record.offset)
                if not decoded.complete or decoded.consumed != len(record.raw):
                    raise ValueError(
                        f"已分配组图 ${index:02X} 的记录边界不完整。"
                    )

        free_indices = [
            index
            for index in usable_indices
            if index not in allocated and index not in frame_references
        ]
        if not free_indices:
            raise ValueError("组图规律可调用的预留槽已用完。")
        if source_index in free_indices:
            raise ValueError("当前项是尚未分配的组图预留槽，不能作为复制来源。")
        new_index = free_indices[0]
        lowest_pointer = min(allocated.values(), default=dummy_pointer)
        destination_pointer = lowest_pointer - len(source.raw)
        if destination_pointer < SPRITE_RESERVED_POINTER:
            remaining = lowest_pointer - SPRITE_RESERVED_POINTER
            raise ValueError(
                f"组图预留尾区只剩 {remaining} 字节，不能复制 {len(source.raw)} 字节。"
            )

        new_pointers = [dummy_pointer] * len(reserved_indices) if pristine else list(current_pointers)
        new_pointers[new_index - SPRITE_RESERVED_FIRST] = destination_pointer
        new_pool = bytearray(
            bytes((0xFF,)) * (SPRITE_RESERVED_END - SPRITE_RESERVED_POINTER)
            if pristine
            else current_pool
        )
        local = destination_pointer - SPRITE_RESERVED_POINTER
        new_pool[local:local + len(source.raw)] = source.raw
        dummy_local = dummy_pointer - SPRITE_RESERVED_POINTER
        new_pool[dummy_local:dummy_local + len(SPRITE_FREE_RECORD)] = SPRITE_FREE_RECORD

        pointer_before = self.data[
            pointer_offset : pointer_offset + len(reserved_indices) * 2
        ]
        pointer_after = struct.pack(f"<{len(new_pointers)}H", *new_pointers)
        patches = (
            (pointer_offset, pointer_before, pointer_after),
            (pool_offset, current_pool, bytes(new_pool)),
        )
        checked = bytearray(self.data)
        for offset, before, after in patches:
            if bytes(checked[offset:offset + len(before)]) != before:
                raise AssertionError("组图复制补丁的旧值不匹配。")
            checked[offset:offset + len(after)] = after
        cloned = AnimationCodec(checked).record("sprite", new_index)
        if cloned.raw != source.raw:
            raise AssertionError("组图复制后的指针边界与源记录不一致。")
        return new_index, patches

    def clone_movement_rule_patches(
        self,
        source_index: int,
        map_index: int,
    ) -> tuple[int, str, tuple[BytePatch, BytePatch, BytePatch]]:
        """Copy and bind one uniquely typed movement rule.

        The current ROM reserves $7D-$9C as 32 consecutive one-byte ``FF``
        records.  A copy is only materialized when the selected map animation
        contains exactly one reference to the source in a role that already
        classifies it as either a frame stream or an axis stream.  Rebinding
        that operand in the same patch set makes the role recoverable after a
        project reopen without inventing separate metadata.
        """

        table = TABLE_BY_KIND["movement"]
        pointers = self.pointers["movement"]
        if not 0 <= source_index < len(pointers):
            raise ValueError("请选择有效的运行规律。")
        if not 0 <= map_index < self.count("map"):
            raise ValueError("请选择有效的地图动画。")
        roles = self.movement_roles()
        source_roles = roles.get(source_index, set())
        if len(source_roles) != 1:
            raise ValueError("当前运行规律没有唯一的帧/坐标角色，不能复制。")
        source_role = next(iter(source_roles))
        source = self.record("movement", source_index)
        if not source.raw:
            raise ValueError("当前运行规律没有可复制的记录。")

        map_record = self.record("map", map_index)
        if not map_record.complete:
            raise ValueError("当前地图动画没有完整结束边界。")
        bindings: list[tuple[int, str]] = []
        for instruction in map_record.instructions:
            raw = instruction.raw
            if (
                not raw
                or raw[0] not in (0x40, 0x42, 0xC0, 0xC2)
                or len(raw) != 5
                or raw[1] != table.selector
            ):
                continue
            for local, role in zip(
                range(2, 5),
                ("frames", "axis", "axis"),
            ):
                if raw[local] == source_index:
                    bindings.append((instruction.offset + local, role))
        if len(bindings) != 1:
            raise ValueError(
                "当前地图动画必须恰好一次引用所选运行规律，才能无歧义复制并绑定。"
            )
        binding_offset, binding_role = bindings[0]
        if binding_role != source_role:
            raise ValueError("当前地图动画引用角色与运行规律既有角色不一致。")

        reserved_indices = tuple(
            range(MOVEMENT_RESERVED_FIRST, MOVEMENT_RESERVED_LAST + 1)
        )
        pointer_offset = table.offset(table.table) + MOVEMENT_RESERVED_FIRST * 2
        pool_offset = table.offset(MOVEMENT_RESERVED_POINTER)
        pool_end_offset = table.offset(MOVEMENT_RESERVED_END)
        dummy_pointer = MOVEMENT_RESERVED_END - 1
        current_pointers = tuple(pointers[index] for index in reserved_indices)
        current_pool = self.data[pool_offset:pool_end_offset]
        expected_pointers = tuple(
            range(MOVEMENT_RESERVED_POINTER, MOVEMENT_RESERVED_END)
        )
        pristine = (
            current_pointers == expected_pointers
            and current_pool == bytes((0xFF,)) * len(current_pool)
        )

        if pristine:
            allocated: dict[int, int] = {}
        else:
            if any(
                not MOVEMENT_RESERVED_POINTER <= pointer <= dummy_pointer
                for pointer in current_pointers
            ):
                raise ValueError("运行规律预留尾区指针已变化，不能继续分配。")
            allocated = {
                index: pointers[index]
                for index in reserved_indices
                if pointers[index] != dummy_pointer
            }
            if len(set(allocated.values())) != len(allocated):
                raise ValueError("已分配运行规律含共享指针，不能继续搬移。")
            lowest_pointer = min(allocated.values(), default=dummy_pointer)
            prefix = self.data[
                pool_offset : table.offset(lowest_pointer)
            ]
            if prefix != bytes((0xFF,)) * len(prefix):
                raise ValueError("运行规律预留尾区的剩余空间不再是全 FF。")
            for index in allocated:
                if len(roles.get(index, set())) != 1:
                    raise ValueError(
                        f"已分配运行规律 ${index:02X} 没有唯一调用角色。"
                    )
                if not self.record("movement", index).raw:
                    raise ValueError(
                        f"已分配运行规律 ${index:02X} 没有完整记录。"
                    )

        free_indices = [
            index
            for index in reserved_indices
            if index not in allocated and index not in roles
        ]
        if not free_indices:
            raise ValueError("运行规律预留槽已用完。")
        if source_index in free_indices:
            raise ValueError("当前项是尚未分配的运行规律预留槽，不能作为复制来源。")
        new_index = free_indices[0]
        lowest_pointer = min(allocated.values(), default=dummy_pointer)
        destination_pointer = lowest_pointer - len(source.raw)
        if destination_pointer < MOVEMENT_RESERVED_POINTER:
            remaining = lowest_pointer - MOVEMENT_RESERVED_POINTER
            raise ValueError(
                f"运行规律预留尾区只剩 {remaining} 字节，不能复制 {len(source.raw)} 字节。"
            )

        new_pointers = [dummy_pointer] * len(reserved_indices) if pristine else list(current_pointers)
        new_pointers[new_index - MOVEMENT_RESERVED_FIRST] = destination_pointer
        new_pool = bytearray(
            bytes((0xFF,)) * (MOVEMENT_RESERVED_END - MOVEMENT_RESERVED_POINTER)
            if pristine
            else current_pool
        )
        local = destination_pointer - MOVEMENT_RESERVED_POINTER
        new_pool[local:local + len(source.raw)] = source.raw
        new_pool[-1] = 0xFF

        pointer_before = self.data[
            pointer_offset : pointer_offset + len(reserved_indices) * 2
        ]
        pointer_after = struct.pack(f"<{len(new_pointers)}H", *new_pointers)
        patches = (
            (pointer_offset, pointer_before, pointer_after),
            (pool_offset, current_pool, bytes(new_pool)),
            (
                binding_offset,
                self.data[binding_offset:binding_offset + 1],
                bytes((new_index,)),
            ),
        )
        checked = bytearray(self.data)
        for offset, before, after in patches:
            if bytes(checked[offset:offset + len(before)]) != before:
                raise AssertionError("运行规律复制补丁的旧值不匹配。")
            checked[offset:offset + len(after)] = after
        cloned_codec = AnimationCodec(checked)
        cloned = cloned_codec.record("movement", new_index)
        if cloned.raw != source.raw:
            raise AssertionError("运行规律复制后的指针边界与源记录不一致。")
        if cloned_codec.movement_roles().get(new_index) != {source_role}:
            raise AssertionError("运行规律复制后的调用角色未能从地图动画恢复。")
        return new_index, source_role, patches

    def rule_patch(self, record: AnimationRecord, replacement: bytes) -> BytePatch:
        if self.record(record.kind, record.index) != record:
            raise ValueError("规律原值已变化，请重新载入。")
        if len(replacement) != len(record.raw):
            raise ValueError(f"规律必须保持 {len(record.raw)} 字节。")
        # The reference editor exposes signed X/Y spin boxes, but a live
        # save/reopen capture proved that changing them does not persist.  Its
        # code field does persist the stream that follows those two bytes.  We
        # therefore keep both anchors fixed and only allow the golden-verified
        # first physical tile byte to change.
        if record.kind == "movement":
            roles = self.movement_roles().get(record.index, set())
            if len(roles) != 1:
                raise ValueError("此规律未确定单一运行方式，暂不改写。")
            mode = next(iter(roles))
            masks = self._movement_editable(record.raw, mode)
            for index, (old, new) in enumerate(zip(record.raw, replacement)):
                if old == new:
                    continue
                if index not in masks or new not in masks[index]:
                    raise ValueError(f"+${index:04X} 不是可编辑的帧、位移、音效或循环次数；控制流保持原值。")
        elif record.kind == "sprite" and len(record.raw) >= 3:
            if replacement[:2] != record.raw[:2]:
                raise ValueError("参考版保存不持久化组图 X/Y；两个锚点字节保持只读。")
            changed = [
                index
                for index, (old, new) in enumerate(zip(record.raw, replacement))
                if old != new
            ]
            if any(index != 2 for index in changed):
                raise ValueError("组图规律仅首图块字节已有参考版保存/重开黄金；其余拼图指令保持原值。")
            if replacement[2] >= 0xF0:
                raise ValueError("首图块必须是 $00—$EF 的物理图块；运行时令牌保持原值。")
            decoded = decode_sprite_composition(replacement, record.offset)
            if not decoded.complete or decoded.consumed != len(replacement):
                raise ValueError("组图规律修改后未在原记录边界到达 $FF。")
        elif record.kind == "background":
            if record.index not in self.background_editable_indices():
                raise ValueError("此背景规律没有完整且唯一的静态参数边界，暂不改写。")
            decoded, complete = decode_background_rule(record.raw, record.offset)
            if not complete or sum(len(row.raw) for row in decoded) != len(record.raw):
                raise ValueError("此背景规律没有完整且唯一的静态指令边界。")
            allowed: dict[int, tuple[int, int]] = {}
            for row in decoded:
                for local, low, high in row.editable:
                    allowed[row.offset - record.offset + local] = (low, high)
            for index, (old, new) in enumerate(zip(record.raw, replacement)):
                if old == new:
                    continue
                if index not in allowed:
                    raise ValueError(
                        f"+${index:04X} 是背景控制码、资源引用或未验证参数，必须保持原值。"
                    )
                low, high = allowed[index]
                if not low <= new <= high:
                    raise ValueError(
                        f"+${index:04X} 的绘制参数须在 ${low:02X}–${high:02X}。"
                    )
            replacement_rows, replacement_complete = decode_background_rule(
                replacement,
                record.offset,
            )
            if (
                not replacement_complete
                or sum(len(row.raw) for row in replacement_rows) != len(replacement)
                or tuple(len(row.raw) for row in replacement_rows)
                != tuple(len(row.raw) for row in decoded)
            ):
                raise ValueError("编辑改变了背景规律的指令边界。")
        else:
            raise ValueError("此类规律暂提供真实代码查看；尚未开放代码改写。")
        return record.offset, record.raw, bytes(replacement)

    def background_editable_indices(self) -> tuple[int, ...]:
        """Return rules with a complete unique boundary and safe parameters."""

        result: list[int] = []
        for index in range(self.count("background")):
            record = self.record("background", index)
            decoded, complete = decode_background_rule(record.raw, record.offset)
            if (
                complete
                and sum(len(row.raw) for row in decoded) == len(record.raw)
                and any(row.editable for row in decoded)
            ):
                result.append(index)
        return tuple(result)

    def background_edit_status(self, index: int) -> tuple[bool, str]:
        """Explain the exact safe-write state of one background-rule slot."""

        record = self.record("background", index)
        decoded, complete = decode_background_rule(record.raw, record.offset)
        consumed = sum(len(row.raw) for row in decoded)
        editable_count = sum(len(row.editable) for row in decoded)
        if complete and consumed == len(record.raw) and editable_count:
            return True, f"边界完整；{editable_count} 个已验证绘制参数可改"
        if complete and consumed == len(record.raw):
            return False, "边界完整，但只有控制/资源指令，没有可安全修改的绘制参数"
        if complete:
            return False, f"在结束码后还有 {len(record.raw) - consumed} 字节，无法证明属于本记录"
        if decoded:
            last = decoded[-1]
            relative = last.offset - record.offset
            if "后续边界" not in last.text and "未验证" not in last.text:
                return False, (
                    f"到达指针边界但没有背景结束码；最后一项 +${relative:04X} 为{last.text}"
                )
            return False, f"+${relative:04X}：{last.text}"
        return False, "空记录或没有可验证的指令边界"

    def background_static_reference_indices(self) -> tuple[int, ...]:
        """Return rules referenced by complete current map-animation scripts."""

        result: set[int] = set()
        for index in range(self.count("map")):
            for instruction in self.record("map", index).instructions:
                raw = instruction.raw
                if (
                    len(raw) == 3
                    and raw[0] == 0xF3
                    and raw[1] == TABLE_BY_KIND["background"].selector
                    and raw[2] < self.count("background")
                ):
                    result.add(raw[2])
        return tuple(sorted(result))

    def movement_roles(self) -> dict[int, set[str]]:
        result: dict[int, set[str]] = {}
        for index in range(self.count("map")):
            for instruction in self.record("map", index).instructions:
                raw = instruction.raw
                if raw[0] not in (0x40, 0x42, 0xC0, 0xC2) or len(raw) != 5:
                    continue
                if raw[1] != 0x68:
                    continue
                for ref, role in zip(raw[2:5], ("frames", "axis", "axis")):
                    if ref < self.count("movement"):
                        result.setdefault(ref, set()).add(role)
        # A pointer alias shares both bytes and interpretation.
        pointers = self.pointers["movement"]
        for index in tuple(result):
            for alias, pointer in enumerate(pointers):
                if pointer == pointers[index]:
                    result.setdefault(alias, set()).update(result[index])
        return result

    def _movement_editable(self, raw: bytes, mode: str) -> dict[int, range | set[int]]:
        allowed: dict[int, range | set[int]] = {}
        cursor = 0
        sizes = ({0xF7: 2, 0xF8: 1, 0xF9: 2, 0xFA: 2, 0xFB: 3,
                  0xFC: 3, 0xFD: 2, 0xFE: 2, 0xFF: 1} if mode == "frames"
                 else {0x80: 1, 0x81: 2, 0x82: 2, 0x83: 3, 0x84: 3, 0x85: 2, 0x86: 1})
        while cursor < len(raw):
            op = raw[cursor]
            size = sizes.get(op, 1)
            if cursor + size > len(raw):
                break
            if op not in sizes:
                allowed[cursor] = (range(min(0xF7, self.count("sprite"))) if mode == "frames"
                                   else set(range(256)) - set(range(0x80, 0x87)))
            elif op == (0xFB if mode == "frames" else 0x83) and raw[cursor + 1] < 0xFC:
                allowed[cursor + 1] = range(1, 0xFC)
            elif op == (0xFD if mode == "frames" else 0x85):
                allowed[cursor + 1] = range(256)
            elif mode == "frames" and op == 0xFE:
                allowed[cursor + 1] = range(1, 256)
            cursor += size
            if op in ((0xF8, 0xF9, 0xFA, 0xFF) if mode == "frames" else (0x80, 0x81, 0x82, 0x86)):
                break
        return allowed

    def calls(self) -> tuple[tuple[int, int], ...]:
        # Script bank $1C/$1D, excluding its unrelated pointer/data tail.
        # Sites are discovered from current data and displayed by address;
        # no unverified spirit name is assigned to a byte-search result.
        if self._calls_cache is None:
            map_count = self.count("map")
            self._calls_cache = tuple(
                (offset, self.data[offset + 2])
                for offset in range(0x38010, 0x3C00E)
                if self.data[offset : offset + 2] == b"\x38\x02"
                and self.data[offset + 2] < map_count
            )
        return self._calls_cache

    def call_patch(self, offset: int, animation_id: int) -> BytePatch:
        if not 0x38010 <= offset < 0x3C00E or (offset, self.data[offset + 2]) not in self.calls():
            raise ValueError("该位置不属于当前 ROM 中识别到的动画调用。")
        if not self.call_is_editable(offset):
            raise ValueError("此处只识别到调用字节，事件上下文尚未验证，暂不改写。")
        if not 0 <= animation_id < self.count("map"):
            raise ValueError("动画编号超出指针表。")
        # The map entry must itself decode safely before it can be called.
        if not self.record("map", animation_id).complete:
            raise ValueError("目标动画包含未验证指令，不能作为新的调用目标。")
        return offset + 2, self.data[offset + 2:offset + 3], bytes((animation_id,))

    def call_evidence(self, offset: int) -> str | None:
        """Return the verified context class for an animation call operand."""
        if not 0x38010 <= offset < 0x3C00E or (offset, self.data[offset + 2]) not in self.calls():
            return None
        # The reference editor's exhaustive save chain changed only the byte
        # after the same 38 02 opcode at these file offsets and confirmed it
        # from a fresh process.  The current ROM still has the identical
        # opcode boundary, so only its animation-id operand is writable.  The
        # value at $380DF differs between the reference input and this ROM;
        # address + opcode + isolated saved operand, rather than the old value,
        # is the compatibility proof.
        reference_save_sites = {0x380DF, 0x38EEA}
        if offset in reference_save_sites:
            return "参考逐字段保存同址黄金"
        prefix = self.data[offset - 3:offset]
        if prefix in (b"\x2d\x1d\x03", b"\x2d\x1d\x0b"):
            return "直接设置/调用序列"
        # The battle-flow listing documents ``21 1D 03 38 02 id`` as the
        # unit-explosion animation path.  Eight current-ROM sites match it.
        if prefix == b"\x21\x1d\x03":
            return "战斗流程调用序列"
        # Anger/rage-style spirit scripts pass one byte between the setup and
        # ``1D 0B``.  Both current sites are reproduced verbatim in the CHM.
        longer = self.data[offset - 6:offset]
        if longer[:3] == b"\x2d\x1d\x0c" and longer[4:] == b"\x1d\x0b":
            return "带参数精神调用序列"
        # A verified setup can invoke several animations consecutively.  Walk
        # only over complete three-byte 38 02 operands; do not cross any other
        # command while looking for the head of the chain.
        cursor = offset
        while self.data[cursor - 3:cursor - 1] == b"\x38\x02":
            cursor -= 3
        if cursor != offset and self.data[cursor - 3:cursor] == b"\x2d\x1d\x03":
            return "连续动画调用序列"
        # The two miracle routines use the same documented flash pair.
        miracle_pair = bytes.fromhex("38 02 07 2B 94 58 2B F8 38 02 0A")
        if (self.data[offset:offset + len(miracle_pair)] == miracle_pair
                or self.data[offset - 8:offset + 3] == miracle_pair):
            return "奇迹闪烁调用序列"
        # The CHM map-animation index (page_325.html) names these exact file
        # offsets and IDs.  Only entries whose current byte still matches that
        # listing are writable; $3804A is deliberately excluded because the
        # current ROM has $00 where the reference lists $0C.
        documented_sites = {0x38113: 0x0D, 0x384F2: 0x0B}
        if documented_sites.get(offset) == self.data[offset + 2]:
            return "资料集地址/编号清单"
        return None

    def call_is_editable(self, offset: int) -> bool:
        # The CHM listings and current ROM must agree on a complete context.
        # The remaining raw byte matches stay inspectable but read-only.
        return self.call_evidence(offset) is not None

    def call_status(self, offset: int) -> tuple[bool, str]:
        """Return a beginner-facing status instead of a generic disabled state."""

        evidence = self.call_evidence(offset)
        if evidence is not None:
            return True, f"可改：{evidence}；只写动画编号字节"
        title, reason = READ_ONLY_CALL_AUDIT.get(
            offset,
            ("上下文未验证", "只识别到 38 02 字节外观，尚未证明它是可写动画调用。"),
        )
        return False, f"只读：{title}。{reason}"


def apply_animation_patches(project, patches: tuple[BytePatch, ...], description: str) -> None:
    AnimationCodec(project.working)
    with project.transaction(description):
        for offset, before, after in patches:
            if len(before) != len(after) or bytes(project.working[offset:offset + len(before)]) != before:
                raise ValueError("动画数据已变化，草稿未写入。请重新载入后重试。")
        for offset, _before, after in patches:
            project.working[offset:offset + len(after)] = after
