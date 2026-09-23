local state=savestate.create([[D:\GIT\mmc3\output\verification\purple-pre-attack.fc0]])
assert(pcall(savestate.load,state))
local log=assert(io.open([[D:\GIT\mmc3\output\verification\v20-replay.tsv]],"w"))
emu.speedmode("maximum")
for frame=1,500 do
  if frame%90==0 then joypad.set(1,{A=true}) end
  local crossing=0
  for o=0x0240,0x02FC,4 do
    local y=memory.readbyte(o)
    if y>=0x80 and y<0xF0 then crossing=crossing+1 end
  end
  log:write(string.format("%d\t%d\t%02X\t%02X\t%02X\n",frame,crossing,memory.readbyte(0x04D8),memory.readbyte(0x03D1),memory.readbyte(0x03DB)))
  if frame%2==0 then gui.savescreenshotas([[D:\GIT\mmc3\output\verification\v20-replay-]]..frame..[[.png]]) end
  emu.frameadvance()
end
log:close();emu.exit()
