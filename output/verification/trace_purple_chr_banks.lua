local log=assert(io.open([[D:\GIT\mmc3\output\verification\purple-chr-banks.tsv]],"w"))
log:write("frame\tcount\ttiles\tctrl\tD8_DF\tR0\tR1\tR2\tR3\tR4\tR5\n")
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
  if frame>=7000 then
    local c=0;local tiles={}
    for o=0x0200,0x02FC,4 do
      local y=memory.readbyte(o)
      if y>=0x80 and y<0xB0 then c=c+1;tiles[#tiles+1]=string.format("%02X",memory.readbyte(o+1)) end
    end
    if c>0 then
      local d,r={},{}
      for i=0,7 do d[#d+1]=string.format("%02X",memory.readbyte(0x04D8+i)) end
      local bases={0x03BC,0x03C6,0x03D0,0x03DA,0x03E4,0x03EE}
      for _,a in ipairs(bases) do r[#r+1]=string.format("%02X/%02X",memory.readbyte(a),memory.readbyte(a+1)) end
      log:write(string.format("%d\t%d\t%s\t%02X\t%s\t%s\n",frame,c,table.concat(tiles,","),memory.readbyte(0x60),table.concat(d," "),table.concat(r,"\t")))
    end
  end
  emu.frameadvance()
end
log:close();emu.exit()
