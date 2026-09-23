local log=assert(io.open([[D:\GIT\mmc3\output\verification\purple-oam-slots.tsv]],"w"))
log:write("frame\tindex\ty\ttile\tattr\tx\n")
emu.speedmode("maximum")
for frame=1,7300 do
  if frame==100 or frame==105 then joypad.set(1,{start=true}) end
  if frame>=180 and frame<=900 and frame%8==0 then joypad.set(1,{A=true}) end
  if frame==1100 or frame==1110 or frame==1120 then joypad.set(1,{down=true}) end
  if frame==1130 then joypad.set(1,{left=true}) end
  if frame==1150 then joypad.set(1,{A=true}) end
  if frame==1450 or frame==1455 then joypad.set(1,{A=true}) end
  if frame==1600 or frame==1610 or frame==1620 then joypad.set(1,{right=true}) end
  if frame==1650 then joypad.set(1,{A=true}) end
  if frame==1750 or frame==1755 or frame==1850 or frame==1855 then joypad.set(1,{A=true}) end
  if frame>=2250 and frame<=7250 and frame%90==0 then joypad.set(1,{A=true}) end
  if frame>=7000 and frame<=7250 then
    for i=0,63 do
      local o=0x0200+i*4
      local y=memory.readbyte(o)
      if y>=0x70 and y<0xF0 then
        log:write(string.format("%d\t%02X\t%02X\t%02X\t%02X\t%02X\n",frame,i,y,memory.readbyte(o+1),memory.readbyte(o+2),memory.readbyte(o+3)))
      end
    end
  end
  emu.frameadvance()
end
log:close();emu.exit()
