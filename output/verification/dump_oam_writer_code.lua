local state=savestate.create([[C:\Users\hu\Desktop\fceux\fcs\测试.fc0]])
assert(pcall(savestate.load,state)); emu.speedmode("maximum")
for i=0,330 do
  if i==1 or (i>=150 and i%30==0) then joypad.set(1,{A=true}) end
  emu.frameadvance()
end
local f=assert(io.open([[D:\GIT\mmc3\output\verification\oam-writer-cpu.bin]],"wb"))
for a=0xD180,0xD300 do f:write(string.char(memory.readbyte(a))) end
f:close(); emu.exit()
