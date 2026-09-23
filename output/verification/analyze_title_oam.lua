local used={}
emu.speedmode("maximum")
for frame=1,240 do
  for slot=0,63 do
    local a=0x0200+slot*4
    if memory.readbyte(a)<0xF0 then used[memory.readbyte(a+1)]=true end
  end
  emu.frameadvance()
end
local values={}
for i=0,255 do if used[i] then values[#values+1]=string.format("%02X",i) end end
local log=assert(io.open([[D:\GIT\mmc3\output\verification\title-oam-usage.log]],"w"))
log:write(table.concat(values," ").."\n")
log:close()
emu.exit()
