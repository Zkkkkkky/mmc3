local state=savestate.create([[C:\Users\hu\Desktop\fceux\fcs\测试.fc0]])
assert(pcall(savestate.load,state))
local f=assert(io.open([[D:\GIT\mmc3\output\verification\ppu-pattern-pages.bin]],"wb"))
for a=0x0000,0x1FFF do f:write(string.char(ppu.readbyte(a))) end
f:close(); emu.frameadvance(); emu.exit()
