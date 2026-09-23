local state=savestate.create([[C:\Users\hu\Desktop\fceux\fcs\测试.fc0]])
assert(pcall(savestate.load,state)); emu.speedmode("maximum")
local frame=0; local f=assert(io.open([[D:\GIT\mmc3\output\verification\object-pointer-raw.log]],"w"))
local function cb()
  if frame>=318 and frame<=325 then
    local x=memory.getregister("x")
    f:write(string.format("f=%d x=%02X mask=%02X p30=%02X p40=%02X\n",frame,x,memory.getregister("a"),memory.readbyte(0x0730+x),memory.readbyte(0x0740+x)))
  end
end
memory.registerexec(0xD1D7,cb)
for i=0,330 do frame=i; if i==1 or (i>=150 and i%30==0) then joypad.set(1,{A=true}) end; emu.frameadvance() end
f:close(); emu.exit()
