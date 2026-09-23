local log=assert(io.open([[D:\GIT\mmc3\output\verification\v16-boot.tsv]],"w"))
local hits=0
memory.registerexec(0xF467,function() hits=hits+1 end)
emu.speedmode("maximum")
for frame=1,1000 do
  if frame>=100 and frame<=140 then joypad.set(1,{start=true}) end
  if frame>=180 and frame<=500 and frame%8==0 then joypad.set(1,{A=true}) end
  if frame%10==0 then
    log:write(string.format("%d\t%04X\t%d\t%02X\t%02X\t%02X\t%02X\n",frame,memory.getregister("pc"),hits,memory.readbyte(0x03C5),memory.readbyte(0x03D1),memory.readbyte(0x03DB),memory.readbyte(0x04D8)))
    hits=0
  end
  if frame==10 or frame==100 or frame==200 or frame==400 or frame==600 or frame==800 or frame==1000 then gui.savescreenshotas([[D:\GIT\mmc3\output\verification\v16-boot-]]..frame..[[.png]]) end
  emu.frameadvance()
end
log:close();emu.exit()
