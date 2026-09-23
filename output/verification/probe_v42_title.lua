local hits=0
local restores=0
memory.registerexec(0xF53B,function() hits=hits+1 end)
memory.registerexec(0xF4B0,function() restores=restores+1 end)
local log=assert(io.open([[D:\GIT\mmc3\output\verification\v42-title-probe.log]],"w"))
emu.speedmode("maximum")
for frame=1,300 do
  if frame==150 or frame==155 then joypad.set(1,{start=true}) end
  if frame%25==0 then
    log:write(string.format("%d hit=%d restore=%d d0=%02X d1=%02X da=%02X db=%02X pc=%04X\n",
      frame,hits,restores,memory.readbyte(0x03D0),memory.readbyte(0x03D1),
      memory.readbyte(0x04DA),memory.readbyte(0x04DB),memory.getregister("pc")))
  end
  emu.frameadvance()
end
log:close()
emu.exit()
