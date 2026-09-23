emu.speedmode("maximum")
for frame=1,400 do emu.frameadvance() end
local f=assert(io.open([[D:\GIT\mmc3\output\verification\title-sram.bin]],"wb"))
for address=0x6000,0x7FFF do f:write(string.char(memory.readbyte(address))) end
f:close()
emu.pause()
