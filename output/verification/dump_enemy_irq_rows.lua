local state=savestate.create([[C:\Users\hu\Desktop\fceux\fcs\测试.fc0]])
assert(pcall(savestate.load,state)); emu.speedmode("maximum")
for frame=0,330 do
  if frame==1 or (frame>=150 and frame%30==0) then joypad.set(1,{A=true}) end
  emu.frameadvance()
end
local f=assert(io.open([[D:\GIT\mmc3\output\verification\enemy-irq-rows.log]],"w"))
local bases={0x03BC,0x03C6,0x03D0,0x03DA,0x03E4,0x03EE}
for r=1,6 do
  f:write(string.format("R%d:",r-1))
  for i=0,9 do f:write(string.format(" %02X",memory.readbyte(bases[r]+i))) end
  f:write("\n")
end
f:write("M:"); for a=0x04D8,0x04DD do f:write(string.format(" %02X",memory.readbyte(a))) end
f:write("\n"); f:close(); emu.exit()
