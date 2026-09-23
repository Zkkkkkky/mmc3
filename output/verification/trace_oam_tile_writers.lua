local state=savestate.create([[C:\Users\hu\Desktop\fceux\fcs\测试.fc0]])
assert(pcall(savestate.load,state)); emu.speedmode("maximum")
local frame=0
local f=assert(io.open([[D:\GIT\mmc3\output\verification\oam-tile-writers.log]],"w"))
local function onwrite(addr,size,val)
  if frame < 290 or frame > 360 or addr < 0x0241 or (addr % 4) ~= 1 then return end
  if val >= 0x80 and val <= 0xAF then
    f:write(string.format("f=%03d pc=%04X a=%04X y=%02X t=%02X x=%02X attr=%02X\n",
      frame,memory.getregister("pc"),addr,memory.readbyte(addr-1),val,
      memory.readbyte(addr+2),memory.readbyte(addr+1)))
  end
end
memory.registerwrite(0x0200,0x100,onwrite)
for i=0,370 do
  frame=i
  if i==1 or (i>=150 and i%30==0) then joypad.set(1,{A=true}) end
  emu.frameadvance()
end
f:close(); emu.exit()
