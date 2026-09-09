from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path

from .constants import (
    CPU_BANK_BASE,
    INES_HEADER_SIZE,
    PRG_BANK_SIZE,
)
from .errors import RomFormatError
from .profiles import RomProfile, detect_profile


def mapper_number(header: bytes) -> int:
    if len(header) < INES_HEADER_SIZE:
        raise RomFormatError("ROM 头长度不足。")
    return (header[6] >> 4) | (header[7] & 0xF0)


@dataclass(frozen=True)
class BankAddress:
    """An address paired with its mapped 8 KiB PRG bank."""

    prg_bank: int
    cpu_address: int
    window_base: int = CPU_BANK_BASE
    bank_size: int = PRG_BANK_SIZE

    def __post_init__(self) -> None:
        if self.prg_bank < 0:
            raise ValueError("PRG Bank 不能为负数。")
        if self.bank_size <= 0:
            raise ValueError("Bank 大小必须大于零。")
        if not self.window_base <= self.cpu_address < self.window_base + self.bank_size:
            raise ValueError(
                f"CPU 地址 ${self.cpu_address:04X} 不在 "
                f"${self.window_base:04X}—${self.window_base + self.bank_size - 1:04X}。"
            )

    @property
    def bank_offset(self) -> int:
        return self.cpu_address - self.window_base

    def to_file_offset(self, header_size: int = INES_HEADER_SIZE) -> int:
        return header_size + self.prg_bank * self.bank_size + self.bank_offset


class RomImage:
    """Validated immutable ROM bytes with explicit bank/address helpers."""

    def __init__(self, data: bytes, path: Path | None = None) -> None:
        self.data = bytes(data)
        self.path = path
        self.profile = self.validate_layout()

    @classmethod
    def load(cls, path: str | Path) -> "RomImage":
        resolved = Path(path).expanduser().resolve()
        return cls(resolved.read_bytes(), resolved)

    @property
    def size(self) -> int:
        return len(self.data)

    @property
    def mapper(self) -> int:
        return mapper_number(self.data[:INES_HEADER_SIZE])

    @property
    def sha256(self) -> str:
        return hashlib.sha256(self.data).hexdigest().upper()

    @property
    def is_reference_base(self) -> bool:
        return self.sha256 == self.profile.reference_sha256

    def validate_layout(self) -> RomProfile:
        if self.data[:4] != b"NES\x1A":
            raise RomFormatError("文件不是有效的 iNES ROM。")
        if len(self.data) < INES_HEADER_SIZE:
            raise RomFormatError("ROM 头长度不足。")
        trainer_size = 512 if self.data[6] & 0x04 else 0
        declared_size = (
            INES_HEADER_SIZE
            + trainer_size
            + self.data[4] * 0x4000
            + self.data[5] * 0x2000
        )
        if len(self.data) != declared_size:
            raise RomFormatError(
                f"ROM 大小与 iNES 头不符：头部声明 {declared_size} 字节，"
                f"实际 {len(self.data)} 字节。"
            )
        try:
            profile = detect_profile(self.data)
        except ValueError as error:
            raise RomFormatError(str(error)) from error
        actual_mapper = mapper_number(self.data[:INES_HEADER_SIZE])
        if actual_mapper != profile.mapper:
            raise RomFormatError(
                f"Mapper 不匹配：需要 {profile.mapper}，实际 {actual_mapper}。"
            )
        return profile

    def require_reference_base(self) -> None:
        if not self.is_reference_base:
            raise RomFormatError(
                f"ROM 的 SHA-256 不是“{self.profile.label}”的已验证基准版；"
                "项目操作不能安全重放。"
            )

    def read(self, offset: int, size: int) -> bytes:
        if offset < 0 or size < 0 or offset + size > len(self.data):
            raise RomFormatError(
                f"读取范围 0x{offset:X}—0x{offset + size:X} 超出 ROM。"
            )
        return self.data[offset : offset + size]

    def read_bank(self, address: BankAddress, size: int) -> bytes:
        if address.bank_offset + size > address.bank_size:
            raise RomFormatError("读取跨越了 PRG Bank 边界。")
        return self.read(address.to_file_offset(), size)
