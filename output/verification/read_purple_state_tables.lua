local log = assert(io.open([[D:\GIT\mmc3\output\verification\purple-state-tables.txt]], "w"))
local state = savestate.create([[D:\GIT\mmc3\output\verification\purple-pre-attack.fc0]])
local ok, err = pcall(savestate.load, state)
log:write("load=", tostring(ok), " ", tostring(err), "\n")
for i = 0, 9 do
  log:write(string.format("%d latch=%02X ctrl=%02X R0=%02X R1=%02X R2=%02X R3=%02X R4=%02X R5=%02X\n", i,
    memory.readbyte(0x038A+i), memory.readbyte(0x0394+i),
    memory.readbyte(0x03BC+i), memory.readbyte(0x03C6+i),
    memory.readbyte(0x03D0+i), memory.readbyte(0x03DA+i),
    memory.readbyte(0x03E4+i), memory.readbyte(0x03EE+i)))
end
log:close(); emu.exit()
