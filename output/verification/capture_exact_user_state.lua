local state = savestate.create([[C:\Users\hu\Desktop\fceux\fcs\测试.fc0]])
assert(pcall(savestate.load, state))
local prefix = os.getenv("DC_EXACT_PREFIX") or [[D:\GIT\mmc3\output\verification\exact-state]]
local log = assert(io.open(prefix .. ".log", "w"))
local frame = 0
local oam_address = 0
local captured = {}

emu.speedmode("maximum")

local function dump_shadow(label)
  log:write(string.format("%s R0=%02X R1=%02X UI_R0=%02X UI_R1=%02X\n",
    label, memory.readbyte(0x04D8), memory.readbyte(0x04D9),
    memory.readbyte(0x03BC), memory.readbyte(0x03C6)))
  for address = 0, 252, 4 do
    local y = memory.readbyte(0x0200 + address)
    local tile = memory.readbyte(0x0201 + address)
    local attr = memory.readbyte(0x0202 + address)
    local x = memory.readbyte(0x0203 + address)
    if y >= 0x58 and y < 0xF0 then
      log:write(string.format("S%02X: y=%02X tile=%02X attr=%02X x=%02X\n",
        address, y, tile, attr, x))
    end
  end
end

memory.registerwrite(0x2003, 1, function(address, size, value)
  oam_address = value
end)

memory.registerwrite(0x2004, 1, function(address, size, value)
  if not captured[frame] then captured[frame] = {} end
  captured[frame][oam_address] = value
  oam_address = (oam_address + 1) % 256
end)

dump_shadow("loaded")

for i = 0, 5 do
  frame = i
  gui.savescreenshotas(prefix .. string.format("-%02d.png", i))
  emu.frameadvance()
  dump_shadow(string.format("after=%02d", i))
end

for f = 0, 5 do
  local data = captured[f]
  if data then
    log:write(string.format("ppu-frame=%02d\n", f))
    for address = 0, 252, 4 do
      local y = data[address] or 0xFF
      local tile = data[address + 1] or 0xFF
      local attr = data[address + 2] or 0xFF
      local x = data[address + 3] or 0xFF
      if y >= 0x58 and y < 0xF0 then
        log:write(string.format("P%02X: y=%02X tile=%02X attr=%02X x=%02X\n",
          address, y, tile, attr, x))
      end
    end
  end
end

log:close()
emu.exit()
