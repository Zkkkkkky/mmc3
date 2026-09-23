local state=savestate.create([[C:\Users\hu\Desktop\fceux\fcs\测试.fc0]])
assert(pcall(savestate.load,state))
local f=assert(io.open([[D:\GIT\mmc3\output\verification\ppu-pattern-probe.log]],"w"))
local ok,val=pcall(ppu.readbyte,0x1860)
f:write("ok=",tostring(ok)," val=",tostring(val),"\n")
if ok then
  for t=0x80,0xA9 do
    f:write(string.format("%02X:",t))
    for i=0,15 do f:write(string.format("%02X",ppu.readbyte(0x1000+t*16+i))) end
    f:write("\n")
  end
end
f:close(); emu.frameadvance(); emu.exit()
