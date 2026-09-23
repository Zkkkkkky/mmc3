local state=savestate.create([[D:\GIT\mmc3\output\verification\v5.fc0]])
assert(pcall(savestate.load,state))
local log=assert(io.open([[D:\GIT\mmc3\output\verification\ice-state.log]],"w"))
emu.speedmode("maximum")
for frame=1,600 do
  if frame<=5 then joypad.set(1,{A=true}) end
  if frame>=540 and frame<=590 then
    log:write(string.format("F%d TOP %02X %02X %02X %02X %02X %02X CROSS",frame,
      memory.readbyte(0x04D8),memory.readbyte(0x04D9),memory.readbyte(0x04DA),
      memory.readbyte(0x04DB),memory.readbyte(0x04DC),memory.readbyte(0x04DD)))
    for slot=16,63 do
      local a=0x0200+slot*4
      local y=memory.readbyte(a)
      if y>=0x70 and y<0xF0 then log:write(string.format(" %02X:%02X",y,memory.readbyte(a+1))) end
    end
    log:write("\n")
  end
  emu.frameadvance()
end
log:close()
emu.exit()
