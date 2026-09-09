from __future__ import annotations

import argparse
from pathlib import Path

from py65.devices.mpu6502 import MPU
from py65.disassembler import Disassembler


ROOT = Path(__file__).resolve().parents[1]


def main() -> int:
    parser = argparse.ArgumentParser(description="Disassemble one mapped 8 KiB DC PRG bank.")
    parser.add_argument("bank", type=lambda value: int(value, 0))
    parser.add_argument("start", type=lambda value: int(value, 0))
    parser.add_argument("end", type=lambda value: int(value, 0))
    parser.add_argument(
        "--window-base",
        type=lambda value: int(value, 0),
        choices=(0x8000, 0xA000, 0xC000, 0xE000),
        help="CPU window used for this 8 KiB bank (auto-detected when omitted)",
    )
    arguments = parser.parse_args()
    if arguments.window_base is not None:
        window_base = arguments.window_base
    elif arguments.start >= 0xE000:
        window_base = 0xE000
    elif arguments.start >= 0xC000:
        window_base = 0xC000
    elif arguments.start >= 0xA000:
        window_base = 0xA000
    else:
        window_base = 0x8000
    rom = (ROOT / "FC模拟器" / "DC_kuorong.nes").read_bytes()
    bank = rom[
        16 + arguments.bank * 0x2000 : 16 + (arguments.bank + 1) * 0x2000
    ]
    machine = MPU()
    machine.memory[window_base : window_base + len(bank)] = bank
    disassembler = Disassembler(machine)
    pc = arguments.start
    while pc < arguments.end:
        length, text = disassembler.instruction_at(pc)
        encoded = " ".join(f"{machine.memory[pc + index]:02X}" for index in range(length))
        print(f"{pc:04X}  {encoded:<10} {text}")
        pc += length
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
