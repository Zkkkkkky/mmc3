local log=assert(io.open([[D:\GIT\mmc3\output\verification\v41-boot.log]],"w"))
emu.speedmode("maximum")
for frame=1,120 do
  log:write(string.format("%d pc=%04X s=%02X be=%02X d8=%02X d0=%02X d1=%02X da=%02X db=%02X f0=%02X\n",frame,
    memory.getregister("pc"),memory.getregister("s"),memory.readbyte(0x03BE),memory.readbyte(0x04D8),
    memory.readbyte(0x03D0),memory.readbyte(0x03D1),memory.readbyte(0x04DA),memory.readbyte(0x04DB),memory.readbyte(0x03F0)))
  emu.frameadvance()
end
log:close()
emu.exit()
