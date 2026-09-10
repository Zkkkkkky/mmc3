from __future__ import annotations

import hashlib

from ..constants import INES_HEADER_SIZE, PRG_BANK_SIZE
from ..profiles import CustomMusicSlotSpec
from ..rom_image import RomImage


class CustomMusicCodec:
    """Fixed-size FamiStudio music-data banks used by commands $9D-$9F."""

    def __init__(self, rom: RomImage) -> None:
        self.rom = rom
        self.slots = rom.profile.custom_music_slots
        if not self.slots:
            raise ValueError("当前ROM没有可替换的扩展音乐槽。")
        self.slot_by_command = {slot.command: slot for slot in self.slots}
        if len(self.slot_by_command) != len(self.slots):
            raise ValueError("扩展音乐槽命令重复。")
        for slot in self.slots:
            self.validate_bank(self.bank_bytes(slot.command), slot=slot)

    @staticmethod
    def bank_offset(slot: CustomMusicSlotSpec) -> int:
        return INES_HEADER_SIZE + slot.prg_bank * PRG_BANK_SIZE

    def bank_bytes(self, command: int, data: bytes | None = None) -> bytes:
        try:
            slot = self.slot_by_command[command]
        except KeyError as error:
            raise ValueError(f"命令 ${command:02X} 不是可替换扩展曲槽。") from error
        source = self.rom.data if data is None else data
        offset = self.bank_offset(slot)
        return bytes(source[offset : offset + PRG_BANK_SIZE])

    @staticmethod
    def validate_bank(
        payload: bytes,
        *,
        slot: CustomMusicSlotSpec | None = None,
    ) -> int:
        label = "音乐Bank" if slot is None else f"${slot.command:02X} {slot.label}"
        if len(payload) != PRG_BANK_SIZE:
            raise ValueError(f"{label} 必须正好为8192字节。")
        song_count = payload[0]
        if not 1 <= song_count <= 32:
            raise ValueError(f"{label} 的FamiStudio曲目数无效。")
        header_size = 5 + song_count * 14
        if header_size > len(payload):
            raise ValueError(f"{label} 的FamiStudio数据头不完整。")
        pointer_offsets = [1, 3]
        for song_index in range(song_count):
            base = 5 + song_index * 14
            pointer_offsets.extend(base + relative for relative in (0, 2, 4, 6, 8, 10))
        for offset in pointer_offsets:
            pointer = int.from_bytes(payload[offset : offset + 2], "little")
            if not 0x8000 <= pointer < 0xA000:
                raise ValueError(
                    f"{label} 的FamiStudio指针 ${pointer:04X} 超出 $8000—$9FFF。"
                )
        return song_count

    def sha256(self, command: int, data: bytes | None = None) -> str:
        return hashlib.sha256(self.bank_bytes(command, data)).hexdigest().upper()
