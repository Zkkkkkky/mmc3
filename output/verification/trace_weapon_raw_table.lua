local state=savestate.create([[C:\Users\hu\Desktop\fceux\fcs\测试.fc0]])
assert(pcall(savestate.load,state)); emu.speedmode("maximum")
local frame=0; local seen={}; local f=assert(io.open([[D:\GIT\mmc3\output\verification\weapon-raw-table.log]],"w"))
local function cb()
  if frame<200 or frame>390 then return end
  local obj=memory.readbyte(0x1F)
  local final=memory.getregister("a"); local y=memory.getregister("y")
  local ptr=memory.readbyte(0x18)+memory.readbyte(0x19)*256; local addr=(ptr+y)%0x10000
  if ptr<0x8300 or ptr>=0x8500 or final<0x86 or final>0xA9 then return end
  local raw=memory.readbyte(addr)
  local base=raw
  if raw>=0xF0 then base=memory.readbyte(0x06B6+AND(raw,0x0F)) end
  local key=string.format("%04X/%02X/%02X",addr,raw,final)
  if not seen[key] then seen[key]=true; f:write(string.format("f=%03d obj=%02X addr=%04X raw=%02X base=%02X final=%02X code=%s\n",frame,obj,addr,raw,base,final,raw>=0xF0 and "lookup" or "direct")) end
end
memory.registerexec(0xD219,cb)
for i=0,410 do frame=i; if i==1 or (i>=150 and i%30==0) then joypad.set(1,{A=true}) end; emu.frameadvance() end
f:close(); emu.exit()
