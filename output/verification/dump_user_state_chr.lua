local state = savestate.create([[C:\Users\hu\Desktop\fceux\fcs\测试.fc0]])
assert(pcall(savestate.load, state))
local f = assert(io.open([[D:\GIT\mmc3\output\verification\user-state-chr.log]], "w"))
local bases = {0x03BC,0x03C6,0x03D0,0x03DA,0x03E4,0x03EE}
for r=1,6 do
  f:write(string.format("R%d:", r-1))
  for i=0,9 do f:write(string.format(" %02X",memory.readbyte(bases[r]+i))) end
  f:write("\n")
end
f:write("M:")
for a=0x04D8,0x04DD do f:write(string.format(" %02X",memory.readbyte(a))) end
f:write(string.format("\nPPUCTRL=%02X state395=%02X\n", memory.readbyte(0x2000),memory.readbyte(0x0395)))
f:close()
emu.frameadvance(); emu.exit()
