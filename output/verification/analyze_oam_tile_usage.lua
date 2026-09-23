local top, lower = {}, {}
emu.speedmode("maximum")
for frame=1,7350 do
  if frame==100 or frame==105 then joypad.set(1,{start=true}) end
  if frame>=180 and frame<=900 and frame%8==0 then joypad.set(1,{A=true}) end
  if frame==1100 or frame==1110 or frame==1120 then joypad.set(1,{down=true}) end
  if frame==1130 then joypad.set(1,{left=true}) end
  if frame==1150 then joypad.set(1,{A=true}) end
  if frame==1450 or frame==1455 then joypad.set(1,{A=true}) end
  if frame==1600 or frame==1610 or frame==1620 then joypad.set(1,{right=true}) end
  if frame==1650 then joypad.set(1,{A=true}) end
  if frame==1750 or frame==1755 or frame==1850 or frame==1855 then joypad.set(1,{A=true}) end
  if frame>=2250 and frame<=7350 and frame%90==0 then joypad.set(1,{A=true}) end
  if frame>=6800 then
    for slot=0,63 do
      local a=0x0200+slot*4
      local y=memory.readbyte(a)
      local tile=memory.readbyte(a+1)
      if y<0x78 then top[tile]=true elseif y<0xF0 then lower[tile]=true end
    end
  end
  emu.frameadvance()
end
local function list(set)
  local result={}
  for i=0,255 do if set[i] then result[#result+1]=string.format("%02X",i) end end
  return table.concat(result," ")
end
local log=assert(io.open([[D:\GIT\mmc3\output\verification\oam-tile-usage.log]],"w"))
log:write("TOP\n"..list(top).."\nLOWER\n"..list(lower).."\n")
log:close()
emu.exit()
