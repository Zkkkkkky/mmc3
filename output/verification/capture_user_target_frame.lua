local state = savestate.create([[C:\Users\hu\Desktop\fceux\fcs\测试.fc0]])
assert(pcall(savestate.load, state))
local prefix = os.getenv("DC_TARGET_PREFIX") or [[D:\GIT\mmc3\output\verification\target-frame]]
local log = assert(io.open(prefix .. ".log", "w"))
local frame = 0
local oam_address = 0
local captured = {}
local banks = {}

emu.speedmode("maximum")

memory.registerwrite(0x2003, 1, function(address, size, value)
  oam_address = value
end)

memory.registerwrite(0x2004, 1, function(address, size, value)
  if frame >= 250 and frame <= 300 then
    if not captured[frame] then captured[frame] = {} end
    captured[frame][oam_address] = value
  end
  oam_address = (oam_address + 1) % 256
end)

for i = 0, 330 do
  frame = i
  if i == 1 or (i >= 150 and i % 30 == 0) then joypad.set(1, {A = true}) end
  if i >= 250 and i <= 300 then
    banks[i] = {
      memory.readbyte(0x04D8), memory.readbyte(0x04D9),
      memory.readbyte(0x03BC), memory.readbyte(0x03C6)
    }
    gui.savescreenshotas(prefix .. string.format("-%03d.png", i))
  end
  emu.frameadvance()
end

for f = 250, 300 do
  local data = captured[f]
  if data then
    local bank = banks[f] or {0xFF, 0xFF, 0xFF, 0xFF}
    log:write(string.format("frame=%03d R0=%02X R1=%02X UI_R0=%02X UI_R1=%02X\n",
      f, bank[1], bank[2], bank[3], bank[4]))
    for address = 0, 252, 4 do
      local y = data[address] or 0xFF
      local tile = data[address + 1] or 0xFF
      local attr = data[address + 2] or 0xFF
      local x = data[address + 3] or 0xFF
      if y >= 0x58 and y < 0xF0 then
        log:write(string.format("%02X: y=%02X tile=%02X attr=%02X x=%02X\n",
          address, y, tile, attr, x))
      end
    end
  end
end

log:close()
emu.exit()
