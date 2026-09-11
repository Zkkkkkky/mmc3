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


TABLES = (
    AnimationTable("map", 0x28, 2, 0x9FFC, 153, 0xC000, 0x62, b"\xf2\x28"),
    AnimationTable("ally", 0x22, 0, 0x8020, 256, 0xC000, 0x60, b"\xf0\x22"),
    AnimationTable("enemy", 0x20, 0, 0x8020, 256, 0xC000, 0x61, b"\xf0\x20"),
    AnimationTable("background", 0x0A, 2, 0xA0C1, 106, 0xBE00, 0x23, b"\x52\x00"),
    AnimationTable("movement", 0x18, 5, 0xB390, 157, 0xBB1D, 0x68, b"\xc5\x07"),
    AnimationTable("sprite", 0x18, 3, 0x9A80, 249, 0xB390, 0x40, b"\xc3\x00"),
)
TABLE_BY_KIND = {table.kind: table for table in TABLES}


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
        )
        for address, expected in signatures:
            offset = self.fixed + address - 0xE000
            value = bytes.fromhex(expected)
            if self.data[offset:offset + len(value)] != value:
                raise ValueError(f"动画解释器 ${address:04X} 与已验证格式不同。")
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

    def rule_patch(self, record: AnimationRecord, replacement: bytes) -> BytePatch:
        if self.record(record.kind, record.index) != record:
            raise ValueError("规律原值已变化，请重新载入。")
        if len(replacement) != len(record.raw):
            raise ValueError(f"规律必须保持 {len(record.raw)} 字节。")
        # Sprite first two bytes are the verified signed Y/X anchor. The
        # command stream (including FF values used as coordinates) is retained.
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
            if replacement[2:] != record.raw[2:]:
                raise ValueError("组图规律当前可编辑前两个坐标字节，拼图指令保持原值。")
        else:
            raise ValueError("此类规律暂提供真实代码查看；尚未开放代码改写。")
        return record.offset, record.raw, bytes(replacement)

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

    def call_is_editable(self, offset: int) -> bool:
        # The CHM's spirit/map-weapon examples and the current event scripts
        # agree on this complete setup + invocation sequence. Other byte
        # matches remain inspectable without being treated as verified sites.
        return (0x38010 <= offset < 0x3C00E
                and self.data[offset - 3:offset] in (b"\x2d\x1d\x03", b"\x2d\x1d\x0b")
                and (offset, self.data[offset + 2]) in self.calls())


def apply_animation_patches(project, patches: tuple[BytePatch, ...], description: str) -> None:
    AnimationCodec(project.working)
    with project.transaction(description):
        for offset, before, after in patches:
            if len(before) != len(after) or bytes(project.working[offset:offset + len(before)]) != before:
                raise ValueError("动画数据已变化，草稿未写入。请重新载入后重试。")
        for offset, _before, after in patches:
            project.working[offset:offset + len(after)] = after
