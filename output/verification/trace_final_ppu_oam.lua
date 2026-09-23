local state = savestate.create([[C:\Users\hu\Desktop\fceux\fcs\测试.fc0]])
assert(pcall(savestate.load, state))
local output = os.getenv("DC_FINAL_OAM_LOG") or [[D:\GIT\mmc3\output\verification\final-ppu-oam.log]]
local log = assert(io.open(output, "w"))
local frame = 0
local oam_address = 0
local captured = {}

emu.speedmode("maximum")

memory.registerwrite(0x2003, 1, function(address, size, value)
  oam_address = value
end)

memory.registerwrite(0x2004, 1, function(address, size, value)
  if frame >= 330 and frame <= 350 then
    if not captured[frame] then captured[frame] = {} end
    captured[frame][oam_address] = value
  end
  oam_address = (oam_address + 1) % 256
end)

for i = 0, 430 do
  frame = i
  if i == 1 or (i >= 150 and i % 30 == 0) then joypad.set(1, {A = true}) end
  emu.frameadvance()
end

for f = 330, 350 do
  local data = captured[f]
  if data then
    log:write(string.format("frame=%03d\n", f))
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
