local log=assert(io.open([[D:\GIT\mmc3\output\verification\v20-early-hits.tsv]],"w"))
local frame=0
memory.registerexec(0xF498,function()
  log:write(string.format("%d\t%02X\t%02X\t%02X\n",frame,memory.readbyte(0x04D8),memory.readbyte(0x04D9),memory.readbyte(0x60)))
end)
emu.speedmode("maximum")
for i=1,6500 do
  frame=i
  if i==100 or i==105 then joypad.set(1,{start=true}) end
  if i>=180 and i<=900 and i%8==0 then joypad.set(1,{A=true}) end
  if i==1100 or i==1110 or i==1120 then joypad.set(1,{down=true}) end
  if i==1130 then joypad.set(1,{left=true}) end
  if i==1150 then joypad.set(1,{A=true}) end
  if i==1450 or i==1455 then joypad.set(1,{A=true}) end
  if i==1600 or i==1610 or i==1620 then joypad.set(1,{right=true}) end
  if i==1650 then joypad.set(1,{A=true}) end
  if i==1750 or i==1755 or i==1850 or i==1855 then joypad.set(1,{A=true}) end
  if i>=2250 and i%90==0 then joypad.set(1,{A=true}) end
  emu.frameadvance()
end
log:close();emu.exit()
