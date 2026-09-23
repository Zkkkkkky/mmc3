local log = assert(io.open([[D:\GIT\mmc3\output\verification\v30-ctrl-2.txt]], "w"))
emu.speedmode("maximum")
for f = 1, 7120 do
  if f == 100 or f == 105 then joypad.set(1, {start=true}) end
  if f >= 180 and f <= 900 and f % 8 == 0 then joypad.set(1, {A=true}) end
  if f == 1100 or f == 1110 or f == 1120 then joypad.set(1, {down=true}) end
  if f == 1130 then joypad.set(1, {left=true}) end
  if f == 1150 then joypad.set(1, {A=true}) end
  if f == 1450 or f == 1455 then joypad.set(1, {A=true}) end
  if f == 1600 or f == 1610 or f == 1620 then joypad.set(1, {right=true}) end
  if f == 1650 then joypad.set(1, {A=true}) end
  if f == 1750 or f == 1755 or f == 1850 or f == 1855 then joypad.set(1, {A=true}) end
  if f >= 2250 and f <= 7120 and f % 90 == 0 then joypad.set(1, {A=true}) end
  if f == 7113 then
    for i = 0, 9 do
      log:write(string.format("%d %02X %02X %02X %02X %02X %02X %02X\n", i,
        memory.readbyte(0x038A+i), memory.readbyte(0x0394+i),
        memory.readbyte(0x03BC+i), memory.readbyte(0x03C6+i),
        memory.readbyte(0x03D0+i), memory.readbyte(0x03DA+i),
        memory.readbyte(0x039E+i)))
    end
    log:flush()
  end
  emu.frameadvance()
end
log:close()
emu.exit()
