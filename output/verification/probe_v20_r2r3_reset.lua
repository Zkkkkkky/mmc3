local state=savestate.create([[C:\Users\hu\Desktop\fceux\fcs\测试_真实OAM分屏修复V12.bak.fc0]])
assert(pcall(savestate.load,state))
local log=assert(io.open([[D:\GIT\mmc3\output\verification\v20-r2r3-reset.tsv]],"w"))
emu.speedmode("maximum")
local current=0
local mapHits=0
local hookHits=0
memory.registerexec(0xF467,function()
  hookHits=hookHits+1
  if hookHits==1 then memory.writebyte(0x0240,0x90) end
end)
memory.registerexec(0xF498,function() mapHits=mapHits+1 end)
for frame=1,100 do
  current=frame
  emu.frameadvance()
  log:write(string.format("%d\t%02X\t%02X\t%02X\t%02X\t%d\t%d\n",frame,memory.readbyte(0x04D8),memory.readbyte(0x0240),memory.readbyte(0x03D1),memory.readbyte(0x03DB),hookHits,mapHits))
end
log:close();emu.exit()
