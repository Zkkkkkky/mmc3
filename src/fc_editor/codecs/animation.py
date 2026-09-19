"""Bounded decoding of the animation resources used by the current DC ROM.

Addresses and operand lengths are checked against the resource loader and the
animation interpreter, rather than the older CHM's original-ROM addresses.
Only existing operands may change; pointers and control flow stay intact.
"""
from __future__ import annotations

from dataclasses import dataclass
import struct


BytePatch = tuple[int, bytes, bytes]


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
class SpriteTimeline:
    frames: tuple[int, ...]
    loop_start: int | None
    terminated: bool
    complete: bool
    error: str = ""


def _signed_byte(value: int) -> int:
    return value - 0x100 if value & 0x80 else value


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
        if op < 0xE0:
            text = f"等待：{op:03d} 帧" if op else "等待：256 帧（00）"
            editable = [(0, 1, 0xDF)]
        elif op in (0xE0, 0xE1):
            size = 2
            if len(tail) >= size:
                text = f"切换 {op - 0xE0:02X} 区域图库：${tail[1]:02X}"
                editable = [(1, 0, 255)]
        elif op in (0xF0, 0xF2):
            size = 3 + tail[2] if len(tail) >= 3 else len(tail) + 1
            if len(tail) >= size and tail[2]:
                values = tail[3:size]
                if op == 0xF0:
                    text = f"调用颜色（{'物理' if tail[1] == 0x11 else '背景'}）：{values.hex(' ').upper()}"
                    editable = [(i, 0, 0x3F) for i in range(3, size) if tail[i] < 0x40]
                else:
                    text = f"切换图库：区域 ${tail[1]:02X}，图库 {values.hex(' ').upper()}"
                    editable = [(i, 0, 255) for i in range(3, size)]
        elif op == 0xF1:
            size = 2
            if len(tail) >= size:
                text = f"更新调色板/显示状态：${tail[1]:02X}"
        elif op == 0xF3:
            size = 3
            if len(tail) >= size:
                text = f"调用背景规律：资源 ${tail[1]:02X}，规律 ${tail[2]:02X}"
        elif op == 0xF4:
            size = 2
            if len(tail) >= size:
                text = f"调用音乐/音效：${tail[1]:02X}"
                editable = [(1, 0, 255)]
        elif op in (0xF5, 0xF7):
            size = 3
            if len(tail) >= size:
                text = f"{'物体坐标' if op == 0xF5 else '背景参数'}：{tail[1:size].hex(' ').upper()}"
                if op == 0xF5:
                    editable = [(2, 0, 255)]
        elif op in (0xF6, 0xFA, 0xFB, 0xFC):
            size = 2
            if len(tail) >= size:
                text = {0xF6: "屏幕属性", 0xFA: "删除物体", 0xFB: "隐藏物体", 0xFC: "显示物体"}[op] + f"：${tail[1]:02X}"
        elif op in (0xF8, 0xF9):
            if len(tail) >= 2:
                # C583 reads its value from the event argument queue without
                # consuming script bytes when coordinate flag bits are set.
                coordinates = 2 - bool(tail[1] & 0x80) - bool(tail[1] & 0x40)
                size = 7 + coordinates
                if len(tail) >= size:
                    base = 2 + coordinates
                    text = (f"创建物体：${tail[1] & 15:02X}，"
                            f"坐标 {tail[2:base].hex(' ').upper() or '事件参数'}；"
                            f"运行规律：{tail[base:base+2].hex(' ').upper()}，"
                            f"组图 ${tail[base+2]:02X} / X ${tail[base+3]:02X} / Y ${tail[base+4]:02X}")
                    editable = [(i, 0, 255) for i in range(2, base)]
        elif op == 0xFD:
            size = 3
            if len(tail) >= size:
                text = f"移动屏幕：X {int.from_bytes(tail[1:2], signed=True)}，Y {int.from_bytes(tail[2:3], signed=True)}"
                editable = [(1, 0, 255), (2, 0, 255)]
        elif op == 0xFE:
            size = 4
            if len(tail) >= size:
                text = f"循环 {tail[1]} 次：转到 CPU ${int.from_bytes(tail[2:4], 'little'):04X}（控制流保留）"
                editable = [(1, 1, 255)]
        elif op == 0xFF:
            rows.append(AnimationInstruction(start + cursor, b"\xff", "动画结束"))
            return tuple(rows), True
        if not text or cursor + size > len(raw):
            rows.append(AnimationInstruction(start + cursor, tail, "未验证指令/截断记录：原始字节保留，后续停止解码"))
            return tuple(rows), False
        rows.append(AnimationInstruction(start + cursor, tail[:size], text, tuple(editable)))
        cursor += size
    return tuple(rows), False


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
                or raw[0] not in (0xF8, 0xF9)
                or len(raw) < 7
                or raw[-4] != table.selector
            ):
                continue
            for local, role in zip(
                range(len(raw) - 3, len(raw)),
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
                if raw[0] not in (0xF8, 0xF9) or len(raw) < 7:
                    continue
                if raw[-4] != 0x68:
                    continue
                for ref, role in zip(raw[-3:], ("frames", "axis", "axis")):
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
        return tuple((i, self.data[i + 2]) for i in range(0x38010, 0x3C00E)
                     if self.data[i:i + 2] == b"\x38\x02" and self.data[i + 2] < self.count("map"))

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


def apply_animation_patches(project, patches: tuple[BytePatch, ...], description: str) -> None:
    AnimationCodec(project.working)
    with project.transaction(description):
        for offset, before, after in patches:
            if len(before) != len(after) or bytes(project.working[offset:offset + len(before)]) != before:
                raise ValueError("动画数据已变化，草稿未写入。请重新载入后重试。")
        for offset, _before, after in patches:
            project.working[offset:offset + len(after)] = after
