from __future__ import annotations

from dataclasses import dataclass

from ..errors import RomFormatError
from ..profiles import BattleMusicSpec, BattleMusicTrackSpec
from ..rom_image import RomImage


@dataclass(frozen=True)
class BattleMusicBinding:
    selector: int
    label: str
    attacker_command: int
    defender_command: int
    attacker_offset: int
    defender_offset: int


class BattleMusicCodec:
    """Decode and safely patch the attacker/defender battle-theme tables."""

    def __init__(self, rom: RomImage) -> None:
        spec = rom.profile.battle_music
        if spec is None:
            raise RomFormatError(f"“{rom.profile.label}”没有已验证的战斗音乐表。")
        self.rom = rom
        self.spec: BattleMusicSpec = spec
        self.track_by_command = {track.command: track for track in spec.tracks}

    @property
    def tracks(self) -> tuple[BattleMusicTrackSpec, ...]:
        return self.spec.tracks

    def _check_selector(self, selector: int) -> None:
        if not 0 <= selector < self.spec.selector_count:
            raise IndexError(
                f"战斗音乐选择器必须在 00—{self.spec.selector_count - 1:02X} 之间。"
            )

    def _check_command(self, command: int) -> None:
        if command not in self.track_by_command:
            raise ValueError(f"不支持的战斗音乐命令 ${command:02X}。")

    def offsets(self, selector: int) -> tuple[int, int]:
        self._check_selector(selector)
        return (
            self.spec.attacker_table_offset + selector,
            self.spec.defender_table_offset + selector,
        )

    def decode(
        self,
        selector: int,
        data: bytes | bytearray | None = None,
    ) -> BattleMusicBinding:
        self._check_selector(selector)
        source = self.rom.data if data is None else data
        attacker_offset, defender_offset = self.offsets(selector)
        if defender_offset >= len(source):
            raise RomFormatError("战斗音乐选择表超出 ROM 范围。")
        return BattleMusicBinding(
            selector=selector,
            label=self.spec.selector_label(selector),
            attacker_command=source[attacker_offset],
            defender_command=source[defender_offset],
            attacker_offset=attacker_offset,
            defender_offset=defender_offset,
        )

    def replacement_patches(
        self,
        data: bytes | bytearray,
        selector: int,
        attacker_command: int,
        defender_command: int,
    ) -> tuple[tuple[int, bytes, bytes], tuple[int, bytes, bytes]]:
        self._check_command(attacker_command)
        self._check_command(defender_command)
        current = self.decode(selector, data)
        return (
            (
                current.attacker_offset,
                bytes((current.attacker_command,)),
                bytes((attacker_command,)),
            ),
            (
                current.defender_offset,
                bytes((current.defender_command,)),
                bytes((defender_command,)),
            ),
        )

    def format_command(self, command: int) -> str:
        track = self.track_by_command.get(command)
        if track is None:
            return f"${command:02X} · 未收录命令"
        return track.display

