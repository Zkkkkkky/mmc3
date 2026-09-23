local state=savestate.create([[C:\Users\hu\Desktop\fceux\fcs\测试.fc0]])
assert(pcall(savestate.load,state)); emu.speedmode("maximum")
for i=0,320 do if i==1 or (i>=150 and i%30==0) then joypad.set(1,{A=true}) end; emu.frameadvance() end
local f=assert(io.open([[D:\GIT\mmc3\output\verification\weapon-prg-8000.bin]],"wb"))
for a=0x8000,0x9FFF do f:write(string.char(memory.readbyte(a))) end
f:close(); emu.exit()
