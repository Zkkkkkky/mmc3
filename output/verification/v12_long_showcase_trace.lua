local out=[[D:\GIT\mmc3\output\verification\v12-showcase-]]
local log=assert(io.open([[D:\GIT\mmc3\output\verification\v12-showcase-trace.tsv]],"w"))
log:write("frame\tcrossing\ttop_r1\tsplit_r1\n")
emu.speedmode("maximum")
for frame=1,24000 do
  if frame==100 or frame==105 then joypad.set(1,{start=true}) end
  if frame>=180 and frame<=900 and frame%8==0 then joypad.set(1,{A=true}) end
  if frame==1100 or frame==1110 or frame==1120 then joypad.set(1,{down=true}) end
  if frame==1130 then joypad.set(1,{left=true}) end
  if frame==1150 then joypad.set(1,{A=true}) end
  if frame==1450 or frame==1455 then joypad.set(1,{A=true}) end
  if frame==1600 or frame==1610 or frame==1620 then joypad.set(1,{right=true}) end
  if frame==1650 then joypad.set(1,{A=true}) end
  if frame==1750 or frame==1755 or frame==1850 or frame==1855 then joypad.set(1,{A=true}) end
  if frame>=2250 and frame<=23500 and frame%90==0 then joypad.set(1,{A=true}) end
  if frame>=9000 then
    local crossing=0
    for o=0x0240,0x02FC,4 do
      local y=memory.readbyte(o)
      if y>=0x80 and y<0xF0 then crossing=crossing+1 end
    end
    local split=0xFF
    for x=0,9 do
      if memory.readbyte(0x03BC+x)==0xF0 then split=memory.readbyte(0x03C6+x) end
    end
    log:write(string.format("%d\t%d\t%02X\t%02X\n",frame,crossing,memory.readbyte(0x04D9),split))
    if split~=0xFF and frame%2==0 then gui.savescreenshotas(out..frame..[[.png]]) end
    if frame%500==0 then gui.savescreenshotas(out..frame..[[.png]]) end
  end
  emu.frameadvance()
end
log:close()
emu.exit()
