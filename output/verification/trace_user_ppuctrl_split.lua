local rom_state = savestate.create([[C:\Users\hu\Desktop\fceux\fcs\测试.fc0]])
assert(pcall(savestate.load, rom_state))
local path = os.getenv("DC_PPUCTRL_LOG") or [[D:\GIT\mmc3\output\verification\user-ppuctrl-split.log]]
local log = assert(io.open(path, "w"))
local frame = 0

local function scanline()
  local ok, value = pcall(function() return ppu.getscanline() end)
  if ok then return value end
  return -1
end

local function write_ppu(address, size, value)
  if frame >= 315 and frame <= 350 then
    log:write(string.format("f=%03d sl=%03d pc=%04X address=%04X value=%02X state394=%02X state395=%02X\n",
      frame, scanline(), memory.getregister("pc"), address, value,
      memory.readbyte(0x0394), memory.readbyte(0x0395)))
  end
end

memory.registerwrite(0x2000, 2, write_ppu)
memory.registerwrite(0x2003, 2, write_ppu)
memory.registerwrite(0x4014, 1, write_ppu)
emu.speedmode("maximum")
for i = 0, 430 do
  frame = i
  if i == 1 or (i >= 150 and i % 30 == 0) then joypad.set(1, {A = true}) end
  emu.frameadvance()
end
log:close()
emu.exit()
