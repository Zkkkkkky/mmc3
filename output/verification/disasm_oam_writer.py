from pathlib import Path
from capstone import Cs, CS_ARCH_MOS65XX, CS_MODE_MOS65XX_6502

rom = Path(r"D:\GIT\mmc3\output\verification\test-ascii.nes").read_bytes()
start = 0x7D0C0
end = 0x7D290
base = 0xC000 + (start - 0x7C010)
md = Cs(CS_ARCH_MOS65XX, CS_MODE_MOS65XX_6502)
md.skipdata = True
for insn in md.disasm(rom[start:end], base):
    print(f"{insn.address:04X}  {insn.bytes.hex(' ').upper():<12} {insn.mnemonic.upper():<5} {insn.op_str}")
