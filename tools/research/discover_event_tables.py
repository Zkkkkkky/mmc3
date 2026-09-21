from __future__ import annotations

import struct
import sys
from dataclasses import dataclass
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))

from fc_editor.codecs.event import EventScriptCodec  # noqa: E402


@dataclass(frozen=True)
class Candidate:
    score: int
    bank: int
    table_offset: int
    pointers: tuple[int, ...]
    terminated_scripts: int
    command_scripts: int


def script_metrics(data: bytes) -> tuple[bool, bool]:
    instructions = EventScriptCodec.decode(data)
    terminated = bool(instructions) and instructions[-1].opcode == 0xFF
    has_command = any(instruction.opcode >= 0xF0 for instruction in instructions[:-1])
    valid = terminated and not any(instruction.truncated for instruction in instructions)
    return valid, has_command


def scan(rom: bytes) -> list[Candidate]:
    result: list[Candidate] = []
    for bank in range(0, 0x40, 2):
        window_start = 16 + bank * 0x2000
        window = rom[window_start : window_start + 0x4000]
        for relative in range(0, len(window) - 16, 2):
            pointers: list[int] = []
            cursor = relative
            while cursor + 1 < len(window) and len(pointers) < 256:
                pointer = struct.unpack_from("<H", window, cursor)[0]
                if not 0x8000 <= pointer < 0xC000:
                    break
                pointers.append(pointer)
                cursor += 2
            if len(pointers) < 8:
                continue
            unique = tuple(dict.fromkeys(pointers))
            terminated = 0
            commands = 0
            for pointer in unique[:32]:
                start = pointer - 0x8000
                block = window[start : min(start + 512, len(window))]
                valid, has_command = script_metrics(block)
                terminated += valid
                commands += valid and has_command
            if terminated < min(4, len(unique)) or not commands:
                continue
            monotonic = sum(left <= right for left, right in zip(pointers, pointers[1:]))
            score = terminated * 5 + commands * 12 + monotonic + len(unique)
            result.append(
                Candidate(
                    score,
                    bank,
                    window_start + relative,
                    tuple(pointers),
                    terminated,
                    commands,
                )
            )
    return sorted(result, key=lambda item: item.score, reverse=True)


def main() -> int:
    rom_path = ROOT / "references" / "rom" / "baselines" / "DC_kuorong.nes"
    rom = rom_path.read_bytes()
    for candidate in scan(rom)[:100]:
        pointers = " ".join(f"{pointer:04X}" for pointer in candidate.pointers[:16])
        print(
            f"score={candidate.score:4} bank=${candidate.bank:02X}/${candidate.bank + 1:02X} "
            f"table=0x{candidate.table_offset:06X} count={len(candidate.pointers):3} "
            f"valid={candidate.terminated_scripts:2} commands={candidate.command_scripts:2} "
            f"pointers={pointers}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
