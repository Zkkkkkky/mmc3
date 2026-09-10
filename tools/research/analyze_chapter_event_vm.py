from __future__ import annotations

import argparse
from collections import deque
from dataclasses import dataclass
from pathlib import Path

from py65.devices.mpu6502 import MPU
from py65.disassembler import Disassembler


ADVANCE_TARGETS = {0x82AF, 0x82B5, 0x82C5, 0x82FD}


@dataclass(frozen=True)
class State:
    pc: int
    y: int | None


def signed_byte(value: int) -> int:
    return value - 0x100 if value & 0x80 else value


def analyze_handler(
    memory: list[int],
    disassembler: Disassembler,
    start: int,
) -> tuple[int, ...]:
    queue = deque((State(start, None),))
    seen: set[State] = set()
    lengths: set[int] = set()

    while queue and len(seen) < 4096:
        state = queue.popleft()
        if state in seen:
            continue
        seen.add(state)
        pc = state.pc
        y = state.y
        if pc in ADVANCE_TARGETS:
            if y is not None:
                lengths.add(y + 1)
            continue
        if not 0x8000 <= pc < 0xA000:
            continue

        size, instruction = disassembler.instruction_at(pc)
        mnemonic = instruction[:3]
        operand = instruction[4:] if len(instruction) > 4 else ""
        next_pc = (pc + size) & 0xFFFF
        next_y = y
        if mnemonic == "LDY" and operand.startswith("#$"):
            next_y = int(operand[2:], 16)
        elif mnemonic == "INY":
            next_y = None if y is None else (y + 1) & 0xFF
        elif mnemonic == "DEY":
            next_y = None if y is None else (y - 1) & 0xFF
        elif mnemonic in {"TAY", "PLY"}:
            next_y = None

        opcode = memory[pc]
        if mnemonic == "JMP" and operand.startswith("$") and opcode == 0x4C:
            queue.append(State(int(operand[1:], 16), next_y))
            continue
        if mnemonic in {
            "BCC",
            "BCS",
            "BEQ",
            "BMI",
            "BNE",
            "BPL",
            "BVC",
            "BVS",
        }:
            target = (next_pc + signed_byte(memory[pc + 1])) & 0xFFFF
            queue.append(State(target, next_y))
            queue.append(State(next_pc, next_y))
            continue
        if mnemonic in {"RTS", "RTI", "BRK"}:
            continue
        queue.append(State(next_pc, next_y))
    return tuple(sorted(lengths))


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Infer DC chapter-event instruction lengths from the 6502 handlers."
    )
    parser.add_argument("rom", type=Path)
    args = parser.parse_args()

    data = args.rom.read_bytes()
    bank = data[16 + 0x1A * 0x2000 : 16 + 0x1B * 0x2000]
    memory = [0] * 0x10000
    memory[0x8000:0xA000] = bank
    mpu = MPU(memory=memory)
    disassembler = Disassembler(mpu)
    table = 0x81AF
    for opcode in range(0x7B):
        handler = memory[table + opcode * 2] | memory[table + opcode * 2 + 1] << 8
        lengths = analyze_handler(memory, disassembler, handler)
        rendered = ",".join(str(length) for length in lengths) or "?"
        print(f"{opcode:02X} -> ${handler:04X}: {rendered}")


if __name__ == "__main__":
    main()
