local state_path = [[C:\Users\hu\Desktop\fceux\fcs\测试.fc0]]
local prefix = os.getenv("DC_CAPTURE_PREFIX") or [[D:\GIT\mmc3\output\verification\user-purple-orig]]
local state = savestate.create(state_path)
assert(pcall(savestate.load, state))
emu.speedmode("maximum")

local log = assert(io.open(prefix .. ".log", "w"))
for frame = 0, 900 do
  if frame == 1 or (frame > 120 and frame % 45 == 0) then
    joypad.set(1, {A=true})
  end

  local matches = {}
  for addr = 0x0240, 0x02FC, 4 do
    local y = memory.readbyte(addr)
    local tile = memory.readbyte(addr + 1)
    if y >= 0x68 and y < 0xF0 and tile >= 0x06 and tile <= 0x29 then
      matches[#matches + 1] = string.format("%04X:y%02X/t%02X", addr, y, tile)
    end
  end
  if #matches > 0 then
    log:write(string.format(
      "f=%d banks=%02X,%02X,%02X,%02X,%02X,%02X oam=%s\n",
      frame,
      memory.readbyte(0x04D8), memory.readbyte(0x04D9),
      memory.readbyte(0x04DA), memory.readbyte(0x04DB),
      memory.readbyte(0x04DC), memory.readbyte(0x04DD),
      table.concat(matches, ";")))
    if frame % 2 == 0 then
      gui.savescreenshotas(prefix .. string.format("-%04d.png", frame))
    end
  end
  emu.frameadvance()
end
log:close()
emu.exit()
