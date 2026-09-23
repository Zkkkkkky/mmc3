local state=savestate.create([[C:\Users\hu\Desktop\fceux\fcs\测试.fc0]])
assert(pcall(savestate.load,state)); emu.speedmode("maximum")
for frame=0,320 do
  if frame==1 or (frame>=150 and frame%30==0) then joypad.set(1,{A=true}) end
  emu.frameadvance()
end
local out=os.getenv("DC_OAM_OUT") or [[D:\GIT\mmc3\output\verification\oam320.bin]]
local f=assert(io.open(out,"wb")); for a=0x0200,0x02FF do f:write(string.char(memory.readbyte(a))) end; f:close()
emu.exit()
