from __future__ import annotations

from dataclasses import dataclass

from .errors import ChangeConflictError


@dataclass(frozen=True)
class PatchOperation:
    offset: int
    before: bytes
    after: bytes
    source: str
    description: str

    def __post_init__(self) -> None:
        if self.offset < 0:
            raise ValueError("补丁偏移不能为负数。")
        if len(self.before) != len(self.after):
            raise ValueError("补丁的新旧数据必须等长。")
        if not self.before:
            raise ValueError("补丁不能为空。")

    @property
    def end(self) -> int:
        return self.offset + len(self.before)

    def overlaps(self, other: "PatchOperation") -> bool:
        return self.offset < other.end and other.offset < self.end


class ChangeSet:
    """Ordered reversible byte operations over an immutable base image."""

    def __init__(self, base: bytes) -> None:
        self.base = bytes(base)
        self._operations: list[PatchOperation] = []
        self._cursor = 0

    @property
    def active_operations(self) -> tuple[PatchOperation, ...]:
        return tuple(self._operations[: self._cursor])

    @property
    def can_undo(self) -> bool:
        return self._cursor > 0

    @property
    def can_redo(self) -> bool:
        return self._cursor < len(self._operations)

    @property
    def is_dirty(self) -> bool:
        return self.materialize() != self.base

    def materialize(self) -> bytes:
        result = bytearray(self.base)
        for operation in self.active_operations:
            result[operation.offset : operation.end] = operation.after
        return bytes(result)

    def apply_patch(
        self,
        offset: int,
        after: bytes,
        *,
        source: str,
        description: str,
        expected: bytes | None = None,
        allow_cross_source_overlap: bool = False,
    ) -> PatchOperation | None:
        if offset < 0 or offset + len(after) > len(self.base):
            raise ValueError("补丁范围超出 ROM。")
        current = self.materialize()[offset : offset + len(after)]
        if expected is not None and current != expected:
            raise ChangeConflictError(
                f"{description} 的原值不匹配：需要 {expected.hex(' ')}, "
                f"实际 {current.hex(' ')}。"
            )
        if current == after:
            return None
        candidate = PatchOperation(offset, current, bytes(after), source, description)
        if not allow_cross_source_overlap:
            for existing in self.active_operations:
                if existing.source != source and candidate.overlaps(existing):
                    raise ChangeConflictError(
                        f"“{description}”与“{existing.description}”写入范围重叠。"
                    )
        del self._operations[self._cursor :]
        self._operations.append(candidate)
        self._cursor += 1
        return candidate

    def undo(self) -> PatchOperation | None:
        if not self.can_undo:
            return None
        self._cursor -= 1
        return self._operations[self._cursor]

    def redo(self) -> PatchOperation | None:
        if not self.can_redo:
            return None
        operation = self._operations[self._cursor]
        current = self.materialize()[operation.offset : operation.end]
        if current != operation.before:
            raise ChangeConflictError(f"无法重做“{operation.description}”：当前字节已变化。")
        self._cursor += 1
        return operation

    def clear(self) -> None:
        self._operations.clear()
        self._cursor = 0

    def byte_diffs(self) -> list[tuple[int, int, int]]:
        current = self.materialize()
        return [
            (offset, old, new)
            for offset, (old, new) in enumerate(zip(self.base, current))
            if old != new
        ]
