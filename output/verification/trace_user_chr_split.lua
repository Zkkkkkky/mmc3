local state = savestate.create([[C:\Users\hu\Desktop\fceux\fcs\测试.fc0]])
assert(pcall(savestate.load, state))
local output = os.getenv("DC_CHR_SPLIT_LOG") or [[D:\GIT\mmc3\output\verification\user-chr-split.log]]
local log = assert(io.open(output, "w"))
local frame = 0
local select_value = 0

local function scanline()
  local ok, value = pcall(function() return ppu.getscanline() end)
  if ok then return value end
  return -1
end

emu.speedmode("maximum")

memory.registerwrite(0x8000, 1, function(address, size, value)
  select_value = value
  if frame >= 330 and frame <= 344 then
    log:write(string.format("f=%03d sl=%03d pc=%04X select=%02X\n",
      frame, scanline(), memory.getregister("pc"), value))
  end
end)

memory.registerwrite(0x8001, 1, function(address, size, value)
  if frame >= 330 and frame <= 344 then
    log:write(string.format("f=%03d sl=%03d pc=%04X R%d=%02X select=%02X\n",
      frame, scanline(), memory.getregister("pc"), select_value % 8, value, select_value))
  end
end)

for i = 0, 430 do
  frame = i
  if i == 1 or (i >= 150 and i % 30 == 0) then joypad.set(1, {A = true}) end
  emu.frameadvance()
end

log:close()
emu.exit()
