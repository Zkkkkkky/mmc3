local state = savestate.create([[C:\Users\hu\Desktop\fceux\fcs\测试.fc0]])
assert(pcall(savestate.load, state))
local log = assert(io.open([[D:\GIT\mmc3\output\verification\enemy-weapon-marker-writes.log]], "w"))
local frame = 0

emu.speedmode("maximum")

memory.registerwrite(0x0740, 0x10, function(address, size, value)
  if value == 0xC2 or (frame >= 180 and frame <= 390) then
    local pointer = memory.readbyte(0x0090) + memory.readbyte(0x0091) * 256
    local bytes = {}
    for i = 0, 9 do bytes[#bytes + 1] = string.format("%02X", memory.readbyte(pointer + i)) end
    log:write(string.format(
      "f=%03d address=%04X value=%02X pc=%04X a=%02X x=%02X y=%02X ptr=%02X%02X data=%s\n",
      frame, address, value, memory.getregister("pc"), memory.getregister("a"),
      memory.getregister("x"), memory.getregister("y"),
      memory.readbyte(0x0091), memory.readbyte(0x0090), table.concat(bytes, " ")))
  end
end)

for i = 0, 430 do
  frame = i
  if i == 1 or (i >= 150 and i % 30 == 0) then joypad.set(1, {A = true}) end
  emu.frameadvance()
end

log:close()
emu.exit()
