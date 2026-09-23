local state=savestate.create([[C:\Users\hu\Desktop\fceux\fcs\测试.fc0]])
assert(pcall(savestate.load,state)); emu.speedmode("maximum")
local frame=0
local hit=0
local function capture()
  if frame < 323 or frame > 326 or hit >= 4 then return end
  local f=assert(io.open(string.format([[D:\GIT\mmc3\output\verification\irq-ppu-f%03d-h%d.bin]],frame,hit),"wb"))
  for a=0x1000,0x1FFF do f:write(string.char(ppu.readbyte(a))) end
  f:close()
  local l=assert(io.open([[D:\GIT\mmc3\output\verification\irq-ppu-calls.log]],"a"))
  l:write(string.format("f=%d hit=%d M=%02X,%02X R=%02X,%02X\n",frame,hit,
    memory.readbyte(0x04D8),memory.readbyte(0x04D9),memory.readbyte(0x03BC),memory.readbyte(0x03C6)))
  l:close(); hit=hit+1
end
memory.registerexec(0xF9AE,capture)
for i=0,330 do
  frame=i
  if i==1 or (i>=150 and i%30==0) then joypad.set(1,{A=true}) end
  emu.frameadvance()
end
emu.exit()
