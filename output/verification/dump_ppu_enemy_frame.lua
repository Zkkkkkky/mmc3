local state=savestate.create([[C:\Users\hu\Desktop\fceux\fcs\测试.fc0]])
assert(pcall(savestate.load,state)); emu.speedmode("maximum")
for frame=0,330 do
  if frame==1 or (frame>=150 and frame%30==0) then joypad.set(1,{A=true}) end
  emu.frameadvance()
end
local f=assert(io.open([[D:\GIT\mmc3\output\verification\ppu-enemy-frame.bin]],"wb"))
for a=0x1000,0x1FFF do f:write(string.char(ppu.readbyte(a))) end
f:close(); emu.exit()
