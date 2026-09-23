local log = assert(io.open([[D:\GIT\mmc3\output\verification\v37-oam.txt]], "w"))
emu.speedmode("maximum")
for frame = 1, 7140 do
  if frame == 100 or frame == 105 then joypad.set(1, {start=true}) end
  if frame >= 180 and frame <= 900 and frame % 8 == 0 then joypad.set(1, {A=true}) end
  if frame == 1100 or frame == 1110 or frame == 1120 then joypad.set(1, {down=true}) end
  if frame == 1130 then joypad.set(1, {left=true}) end
  if frame == 1150 then joypad.set(1, {A=true}) end
  if frame == 1450 or frame == 1455 then joypad.set(1, {A=true}) end
  if frame == 1600 or frame == 1610 or frame == 1620 then joypad.set(1, {right=true}) end
  if frame == 1650 then joypad.set(1, {A=true}) end
  if frame == 1750 or frame == 1755 or frame == 1850 or frame == 1855 then joypad.set(1, {A=true}) end
  if frame >= 2250 and frame <= 7140 and frame % 90 == 0 then joypad.set(1, {A=true}) end
  if frame == 7137 then
    log:write(string.format("ctrl=%02X r1=%02X\n", memory.readbyte(0x0395), memory.readbyte(0x03C7)))
    for i = 0, 63 do
      local o = 0x0200 + i * 4
      log:write(string.format("%02X %02X %02X %02X %02X\n", i, memory.readbyte(o), memory.readbyte(o+1), memory.readbyte(o+2), memory.readbyte(o+3)))
    end
    log:flush()
  end
  emu.frameadvance()
end
log:close(); emu.exit()
