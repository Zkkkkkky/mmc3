from __future__ import annotations

from dataclasses import dataclass
import struct

from ..errors import RomFormatError
from ..rom_image import RomImage


BytePatch = tuple[int, bytes, bytes]
VALID_SEGMENTS = (0x00, 0x01, 0x04, 0x05, 0x07)


def _byte(value: int, label: str) -> int:
    if type(value) is not int or not 0 <= value <= 0xFF:
        raise ValueError(f"{label}必须是 00—FF。")
    return value


@dataclass(frozen=True)
class DialogueBinding:
    segment: int
    dialogue: int

    def encode(self) -> bytes:
        if self.segment not in VALID_SEGMENTS:
            raise ValueError("文字段必须是 00、01、04、05 或 07。")
        return bytes((self.segment, _byte(self.dialogue, "对话编号")))


@dataclass(frozen=True)
class DialogueRule:
    actor_or_unit: int
    weapon_or_unit: int
    segment: int
    dialogue: int

    def encode(self) -> bytes:
        if self.segment not in VALID_SEGMENTS:
            raise ValueError("文字段必须是 00、01、04、05 或 07。")
        return bytes((
            _byte(self.actor_or_unit, "人物/机体条件"),
            _byte(self.weapon_or_unit, "武器/机体条件"),
            self.segment,
            _byte(self.dialogue, "对话编号"),
        ))


@dataclass(frozen=True)
class CharacterDialogueRecord:
    direct: tuple[DialogueBinding, ...]
    rules: tuple[tuple[DialogueRule, ...], ...]

    def encode(self) -> bytes:
        if len(self.direct) != 8:
            raise ValueError("人物直接台词必须包含 8 个绑定。")
        if len(self.rules) != 3:
            raise ValueError("人物特殊台词必须包含 3 组规则。")
        payload = bytearray()
        for binding in self.direct:
            payload.extend(binding.encode())
        for rules in self.rules:
            for rule in rules:
                payload.extend(rule.encode())
            payload.append(0xFF)
        return bytes(payload)


@dataclass(frozen=True)
class TransformDialogueBinding:
    character_id: int
    unit_start: int
    unit_end: int
    dialogue: int

    def encode(self) -> bytes:
        character_id = _byte(self.character_id, "人物 ID")
        if character_id == 0xFF:
            raise ValueError("人物 ID FF 保留为变形台词表结束码。")
        start = _byte(self.unit_start, "起始机体")
        end = _byte(self.unit_end, "终止机体")
        if start > end:
            raise ValueError("变形台词的起始机体不能大于终止机体。")
        dialogue = _byte(self.dialogue, "变形台词编号")
        if dialogue >= 0x40:
            raise ValueError("变形台词编号必须在 00—3F 之间。")
        return bytes((character_id, start, end, dialogue))


class CharacterDialogueCodec:
    """Read and repack the verified native character-dialogue pool."""

    NATIVE_END_POINTER = 0xB510
    NATIVE_END_CODE = bytes.fromhex("a50785024cdab5a50785024c79b5")

    def __init__(self, rom: RomImage, data: bytes | bytearray | None = None) -> None:
        self.rom = rom
        source = rom.data if data is None else data
        profile = rom.profile
        if (
            profile.character_dialogue_pointer_table_offset is None
            or profile.character_dialogue_data_prg_bank is None
            or profile.character_dialogue_data_end_pointer is None
            or profile.character_dialogue_count <= 0
        ):
            raise RomFormatError("当前 ROM 没有已验证的人物台词绑定表。")
        table_size = profile.character_dialogue_count * 2
        start = profile.character_dialogue_pointer_table_offset
        raw = bytes(source[start:start + table_size])
        pointers = struct.unpack(f"<{profile.character_dialogue_count}H", raw)
        if any(not 0x8000 <= pointer < profile.character_dialogue_data_end_pointer for pointer in pointers):
            raise RomFormatError("人物台词指针超出已验证数据区。")
        self._pool_start = min(pointers)
        self._validate_all(source)
        self._validate_native_tail(source)
        self.transform_bindings(source)

    def _validate_native_tail(self, data: bytes | bytearray) -> None:
        profile = self.rom.profile
        if profile.character_dialogue_data_end_pointer != self.NATIVE_END_POINTER:
            raise RomFormatError("人物台词原生容量边界未通过验证。")
        code_offset = self.pointer_to_file_offset(self.NATIVE_END_POINTER - 1) + 1
        if bytes(data[code_offset : code_offset + len(self.NATIVE_END_CODE)]) != self.NATIVE_END_CODE:
            raise RomFormatError("人物台词数据区后的固定代码签名不匹配。")
        used_end = max(
            self._record_end_offset(
                self.pointer_to_file_offset(pointer), data
            )
            for pointer in set(self._pointers(data))
        )
        if any(data[used_end:code_offset]):
            raise RomFormatError("人物台词记录与固定代码之间含未识别数据。")

    def _check_id(self, character_id: int) -> None:
        if type(character_id) is not int or not 1 <= character_id <= self.rom.profile.character_dialogue_count:
            raise ValueError(
                f"人物 ID 必须在 01—{self.rom.profile.character_dialogue_count:02X} 之间。"
            )

    def pointer_offset(self, character_id: int) -> int:
        self._check_id(character_id)
        offset = self.rom.profile.character_dialogue_pointer_table_offset
        assert offset is not None
        return offset + (character_id - 1) * 2

    def pointer(self, character_id: int, data: bytes | bytearray | None = None) -> int:
        source = self.rom.data if data is None else data
        offset = self.pointer_offset(character_id)
        return int.from_bytes(source[offset : offset + 2], "little")

    def pointer_to_file_offset(self, pointer: int) -> int:
        profile = self.rom.profile
        assert profile.character_dialogue_data_prg_bank is not None
        assert profile.character_dialogue_data_end_pointer is not None
        if not 0x8000 <= pointer < profile.character_dialogue_data_end_pointer:
            raise ValueError(f"人物台词 CPU 指针 ${pointer:04X} 无效。")
        return (
            16
            + profile.character_dialogue_data_prg_bank * 0x2000
            + pointer
            - profile.character_dialogue_data_window_base
        )

    def _pointers(self, data: bytes | bytearray) -> tuple[int, ...]:
        return tuple(
            self.pointer(character_id, data)
            for character_id in range(1, self.rom.profile.character_dialogue_count + 1)
        )

    def _record_bytes(self, character_id: int, data: bytes | bytearray) -> bytes:
        pointer = self.pointer(character_id, data)
        start_offset = self.pointer_to_file_offset(pointer)
        end_offset = self._record_end_offset(start_offset, data)
        return bytes(data[start_offset:end_offset])

    def _record_end_offset(
        self, start_offset: int, data: bytes | bytearray
    ) -> int:
        """Return the explicit end of one dialogue record.

        A record contains eight fixed two-byte bindings followed by three
        independently FF-terminated four-byte rule lists.  The old modifier
        uses those terminators, not the next pointer, when it expands the
        packed resource into the native gap before the code at CPU $B510.
        """

        profile = self.rom.profile
        assert profile.character_dialogue_data_end_pointer is not None
        limit = self.pointer_to_file_offset(
            profile.character_dialogue_data_end_pointer - 1
        ) + 1
        cursor = start_offset + 16
        if cursor > limit:
            raise RomFormatError("人物台词固定绑定越过原生数据区。")
        for _group in range(3):
            while cursor < limit and data[cursor] != 0xFF:
                if cursor + 4 > limit:
                    raise RomFormatError("人物特殊台词规则越过原生数据区。")
                cursor += 4
            if cursor >= limit:
                raise RomFormatError("人物特殊台词规则缺少结束码。")
            cursor += 1
        return cursor

    def raw_record(
        self, character_id: int, data: bytes | bytearray | None = None
    ) -> bytes:
        source = self.rom.data if data is None else data
        return self._record_bytes(character_id, source)

    def read(
        self, character_id: int, data: bytes | bytearray | None = None
    ) -> CharacterDialogueRecord:
        source = self.rom.data if data is None else data
        raw = self._record_bytes(character_id, source)
        if len(raw) < 19:
            raise RomFormatError(f"人物 ${character_id:02X} 的台词记录过短。")
        direct = tuple(
            DialogueBinding(raw[index], raw[index + 1])
            for index in range(0, 16, 2)
        )
        cursor = 16
        groups: list[tuple[DialogueRule, ...]] = []
        for _group in range(3):
            rules: list[DialogueRule] = []
            while cursor < len(raw) and raw[cursor] != 0xFF:
                if cursor + 4 > len(raw):
                    raise RomFormatError(
                        f"人物 ${character_id:02X} 的特殊台词规则被截断。"
                    )
                rules.append(DialogueRule(*raw[cursor : cursor + 4]))
                cursor += 4
            if cursor >= len(raw):
                raise RomFormatError(
                    f"人物 ${character_id:02X} 的特殊台词规则缺少结束码。"
                )
            cursor += 1
            groups.append(tuple(rules))
        if cursor != len(raw):
            raise RomFormatError(
                f"人物 ${character_id:02X} 的台词记录边界与指针表不一致。"
            )
        record = CharacterDialogueRecord(direct, tuple(groups))
        if record.encode() != raw:
            raise RomFormatError(f"人物 ${character_id:02X} 的台词记录无法无损往返。")
        return record

    def shared_ids(
        self, character_id: int, data: bytes | bytearray | None = None
    ) -> tuple[int, ...]:
        source = self.rom.data if data is None else data
        pointer = self.pointer(character_id, source)
        return tuple(
            candidate
            for candidate in range(1, self.rom.profile.character_dialogue_count + 1)
            if self.pointer(candidate, source) == pointer
        )

    def patch(
        self,
        data: bytes | bytearray,
        character_id: int,
        record: CharacterDialogueRecord,
    ) -> BytePatch | None:
        aliases = self.shared_ids(character_id, data)
        if len(aliases) > 1:
            raise ValueError(
                "人物台词共用物理记录必须通过 repack_patches 按人物 ID 自动拆分。"
            )
        before = self._record_bytes(character_id, data)
        after = record.encode()
        if len(after) != len(before):
            raise ValueError(
                "人物台词规则当前只允许修改既有项，不能增删规则或改变记录长度。"
            )
        if before == after:
            return None
        offset = self.pointer_to_file_offset(self.pointer(character_id, data))
        return offset, before, after

    def repack_patches(
        self,
        data: bytes | bytearray,
        character_id: int,
        record: CharacterDialogueRecord,
    ) -> tuple[BytePatch, ...]:
        """Rebuild logical character records in the legacy modifier's style.

        Repeated pointers are storage deduplication only.  Editing one logical
        character automatically separates that ID while every other character
        keeps its previous decoded record.  Identical resulting records are
        deduplicated again in logical-ID order, matching the legacy cold-save
        evidence.  Growth may use the native gap up to the fixed code at $B510.
        """

        self._check_id(character_id)
        source = bytes(data)
        replacement = record.encode()
        pointers = self._pointers(source)
        pool_start = self._pool_start
        pool_end = self.rom.profile.character_dialogue_data_end_pointer
        assert pool_end is not None
        capacity = pool_end - pool_start

        logical_records = [
            replacement
            if candidate == character_id
            else self._record_bytes(candidate, source)
            for candidate in range(1, len(pointers) + 1)
        ]
        packed = bytearray()
        assigned: dict[bytes, int] = {}
        remapped: list[int] = []
        cursor = pool_start
        for raw in logical_records:
            pointer = assigned.get(raw)
            if pointer is None:
                pointer = cursor
                assigned[raw] = pointer
                packed.extend(raw)
                cursor += len(raw)
            remapped.append(pointer)
        packed_size = len(packed)
        if packed_size > capacity:
            raise ValueError(
                f"人物台词原生数据区容量不足：需要 {packed_size} 字节，"
                f"容量为 {capacity} 字节。请先删除不用的特殊规则。"
            )

        table_offset = self.rom.profile.character_dialogue_pointer_table_offset
        assert table_offset is not None
        table_size = len(pointers) * 2
        before_table = source[table_offset : table_offset + table_size]
        after_table = struct.pack(
            f"<{len(pointers)}H", *remapped
        )
        pool_offset = self.pointer_to_file_offset(pool_start)
        before_pool = source[pool_offset : pool_offset + capacity]
        after_pool = bytes(packed) + b"\x00" * (capacity - len(packed))
        patches = []
        if before_table != after_table:
            patches.append((table_offset, before_table, after_table))
        if before_pool != after_pool:
            patches.append((pool_offset, before_pool, after_pool))
        return tuple(patches)

    def _validate_all(self, data: bytes) -> None:
        seen: set[int] = set()
        for character_id in range(1, self.rom.profile.character_dialogue_count + 1):
            pointer = self.pointer(character_id, data)
            if pointer in seen:
                continue
            seen.add(pointer)
            self.read(character_id, data)

    def transform_bindings(
        self, data: bytes | bytearray | None = None
    ) -> tuple[TransformDialogueBinding, ...]:
        profile = self.rom.profile
        offset = profile.character_transform_table_offset
        capacity = profile.character_transform_capacity
        if offset is None or capacity <= 0:
            return ()
        source = self.rom.data if data is None else data
        raw = bytes(source[offset : offset + capacity * 4])
        if len(raw) != capacity * 4:
            raise RomFormatError("变形台词绑定表超出 ROM。")
        result = []
        terminated = False
        for index in range(capacity):
            row = raw[index * 4 : index * 4 + 4]
            if row[0] == 0xFF:
                terminated = True
                if row != b"\xFF" * 4:
                    raise RomFormatError("变形台词绑定表结束记录无效。")
                break
            binding = TransformDialogueBinding(*row)
            binding.encode()
            result.append(binding)
        if not terminated:
            raise RomFormatError("变形台词绑定表缺少结束记录。")
        return tuple(result)

    def character_transform_bindings(
        self, character_id: int, data: bytes | bytearray | None = None
    ) -> tuple[TransformDialogueBinding, ...]:
        self._check_id(character_id)
        return tuple(
            binding
            for binding in self.transform_bindings(data)
            if binding.character_id == character_id
        )

    def transform_patch(
        self,
        data: bytes | bytearray,
        character_id: int,
        replacements: tuple[TransformDialogueBinding, ...],
    ) -> BytePatch | None:
        self._check_id(character_id)
        if any(binding.character_id != character_id for binding in replacements):
            raise ValueError("变形台词替换记录的人物 ID 不一致。")
        current = list(self.transform_bindings(data))
        first = next(
            (index for index, binding in enumerate(current) if binding.character_id >= character_id),
            len(current),
        )
        retained = [binding for binding in current if binding.character_id != character_id]
        insert_at = min(first, len(retained))
        updated = retained[:insert_at] + list(replacements) + retained[insert_at:]
        capacity = self.rom.profile.character_transform_capacity
        if len(updated) >= capacity:
            raise ValueError(
                f"变形台词绑定表最多容纳 {capacity - 1} 项；当前需要 {len(updated)} 项。"
            )
        after = b"".join(binding.encode() for binding in updated)
        after += b"\xFF" * ((capacity - len(updated)) * 4)
        offset = self.rom.profile.character_transform_table_offset
        assert offset is not None
        before = bytes(data[offset : offset + capacity * 4])
        return None if before == after else (offset, before, after)
