local state = savestate.create([[C:\Users\hu\Desktop\fceux\fcs\测试.fc0]])
assert(pcall(savestate.load, state))
local prefix = os.getenv("DC_CAPTURE_PREFIX") or [[D:\GIT\mmc3\output\verification\full-trace]]
local log = assert(io.open(prefix .. ".log", "w"))
emu.speedmode("maximum")
local bases = {0x03BC,0x03C6,0x03D0,0x03DA,0x03E4,0x03EE}
for frame = 0, 430 do
  if frame == 1 or (frame >= 150 and frame % 30 == 0) then joypad.set(1, {A=true}) end
  if frame >= 190 and frame <= 390 then
    local active = {}
    for addr = 0x0240, 0x02FC, 4 do
      local y = memory.readbyte(addr)
      if y >= 0x60 and y < 0xF0 then
        active[#active + 1] = string.format("%02X/%02X/%02X", y, memory.readbyte(addr+1), memory.readbyte(addr+2))
      end
    end
    log:write(string.format("f=%03d S=%02X M=%02X,%02X,%02X,%02X,%02X,%02X R=%02X,%02X,%02X,%02X,%02X,%02X O=%s\n",
      frame,
      memory.readbyte(0x007E),
      memory.readbyte(0x04D8),memory.readbyte(0x04D9),memory.readbyte(0x04DA),
      memory.readbyte(0x04DB),memory.readbyte(0x04DC),memory.readbyte(0x04DD),
      memory.readbyte(bases[1]),memory.readbyte(bases[2]),memory.readbyte(bases[3]),
      memory.readbyte(bases[4]),memory.readbyte(bases[5]),memory.readbyte(bases[6]),
      table.concat(active,";")))
    if frame >= 300 and frame <= 360 then gui.savescreenshotas(prefix .. string.format("-%03d.png",frame)) end
  end
  emu.frameadvance()
end
log:close(); emu.exit()
