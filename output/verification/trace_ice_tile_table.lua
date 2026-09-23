local state=savestate.create([[D:\GIT\mmc3\output\verification\v5.fc0]])
assert(pcall(savestate.load,state)); emu.speedmode("maximum")
local frame=0; local f=assert(io.open([[D:\GIT\mmc3\output\verification\ice-tile-table.log]],"w")); local seen={}
local function cb(addr,size,final)
  if frame<450 or frame>580 then return end
  if addr<0x0201 or (addr%4)~=1 or final<0x61 or final>0x6A then return end
  local ptr=memory.readbyte(0x18)+memory.readbyte(0x19)*256
  local obj=memory.readbyte(0x1F); local key=string.format("%04X/%02X/%02X",ptr,final,obj)
  if not seen[key] then seen[key]=true; f:write(string.format("f=%03d pc=%04X obj=%02X p40=%02X p30=%02X mask=%02X ptr=%04X final=%02X ypos=%02X oam=%04X\n",frame,memory.getregister("pc"),obj,memory.readbyte(0x0740+obj),memory.readbyte(0x0730+obj),memory.readbyte(0x1E),ptr,final,memory.readbyte(0x12),addr)) end
end
memory.registerwrite(0x0200,0x100,cb)
for i=1,600 do frame=i; if i<=5 then joypad.set(1,{A=true}) end; emu.frameadvance() end
f:close(); emu.exit()
