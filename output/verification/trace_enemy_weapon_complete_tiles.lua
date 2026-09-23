local state = savestate.create([[C:\Users\hu\Desktop\fceux\fcs\测试.fc0]])
assert(pcall(savestate.load, state))
local output = os.getenv("DC_WEAPON_TILE_LOG") or [[D:\GIT\mmc3\output\verification\enemy-weapon-complete-tiles.log]]
local log = assert(io.open(output, "w"))
local frame = 0
local seen = {}

emu.speedmode("maximum")

local function trace_oam_write(address, size, value)
  if frame < 190 or frame > 390 then return end
  if address < 0x0201 or address > 0x02FD or (address % 4) ~= 1 then return end
  local object = memory.readbyte(0x001F)
  local p40 = memory.readbyte(0x0740 + object)
  if p40 ~= 0xC2 then return end
  local key = string.format("%02X", value)
  if not seen[key] then
    seen[key] = true
    log:write(string.format(
      "first=%03d tile=%02X obj=%02X p30=%02X mask=%02X ptr=%02X%02X y=%02X oam=%04X pc=%04X\n",
      frame, value, object, memory.readbyte(0x0730 + object),
      memory.readbyte(0x001E), memory.readbyte(0x0019), memory.readbyte(0x0018),
      memory.readbyte(address - 1), address, memory.getregister("pc")))
  end
end

memory.registerwrite(0x0200, 0x0100, trace_oam_write)

for i = 0, 430 do
  frame = i
  if i == 1 or (i >= 150 and i % 30 == 0) then
    joypad.set(1, {A = true})
  end
  emu.frameadvance()
end

local ordered = {}
for tile in pairs(seen) do ordered[#ordered + 1] = tile end
table.sort(ordered)
log:write("tiles=" .. table.concat(ordered, ",") .. "\n")
log:close()
emu.exit()
