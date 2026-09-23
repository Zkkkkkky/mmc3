local state=savestate.create([[C:\Users\hu\Desktop\fceux\fcs\测试.fc0]])
assert(pcall(savestate.load,state)); emu.speedmode("maximum")
local frame=0
local f=assert(io.open([[D:\GIT\mmc3\output\verification\enemy-tile-table.log]],"w"))
local seen={}
local function onread()
  if frame < 318 or frame > 325 then return end
  local a=memory.getregister("a")
  local y=memory.getregister("y")
  local ptr=memory.readbyte(0x18)+memory.readbyte(0x19)*256
  local addr=(ptr+y)%0x10000
  local key=string.format("%04X/%02X",addr,a)
  if true then
    f:write(string.format("f=%03d addr=%04X ptr=%04X yidx=%02X ypos=%02X tile=%02X bankSel=%02X bankData=%02X\n",
      frame,addr,ptr,y,memory.readbyte(0x12),a,memory.readbyte(0x7E),memory.readbyte(0x04DF)))
  end
end
memory.registerexec(0xD219,onread)
for i=0,370 do
  frame=i
  if i==1 or (i>=150 and i%30==0) then joypad.set(1,{A=true}) end
  emu.frameadvance()
end
f:close(); emu.exit()
