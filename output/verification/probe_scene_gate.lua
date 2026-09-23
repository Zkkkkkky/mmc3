local which=[[large]]
local path=[[D:\GIT\mmc3\output\verification\large-ui.fc0]]
if memory.readbyte(0)==0xFF then which=[[large]] end
local state=savestate.create(path)
assert(pcall(savestate.load,state))
local log=assert(io.open([[D:\GIT\mmc3\output\verification\scene-gate.tsv]],"w"))
emu.speedmode("maximum")
for frame=1,30 do
  local cross=0
  for o=0x0240,0x02FC,4 do local y=memory.readbyte(o); if y>=0x80 and y<0xF0 then cross=cross+1 end end
  log:write(string.format("%d\t%02X\t%02X\t%02X\t%02X\t%d\n",frame,memory.readbyte(0x04D8),memory.readbyte(0x04D9),memory.readbyte(0x60),memory.readbyte(0x15),cross))
  emu.frameadvance()
end
log:close();emu.exit()
