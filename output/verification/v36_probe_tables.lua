local out = [[D:\GIT\mmc3\output\verification\v36probe-]]
local log = assert(io.open([[D:\GIT\mmc3\output\verification\v36probe.txt]], "w"))
emu.speedmode("maximum")
for frame = 1, 7100 do
  if frame == 100 or frame == 105 then joypad.set(1, {start=true}) end
  if frame >= 180 and frame <= 900 and frame % 8 == 0 then joypad.set(1, {A=true}) end
  if frame == 1100 or frame == 1110 or frame == 1120 then joypad.set(1, {down=true}) end
  if frame == 1130 then joypad.set(1, {left=true}) end
  if frame == 1150 then joypad.set(1, {A=true}) end
  if frame == 1450 or frame == 1455 then joypad.set(1, {A=true}) end
  if frame == 1600 or frame == 1610 or frame == 1620 then joypad.set(1, {right=true}) end
  if frame == 1650 then joypad.set(1, {A=true}) end
  if frame == 1750 or frame == 1755 or frame == 1850 or frame == 1855 then joypad.set(1, {A=true}) end
  if frame >= 2250 and frame <= 7100 and frame % 90 == 0 then joypad.set(1, {A=true}) end
  if frame == 7047 or frame == 7089 then
    log:write(string.format("frame=%d ctrl=%02X p0=%02X p1=%02X R0=%02X/%02X R1=%02X/%02X R2=%02X/%02X R3=%02X/%02X\n",
      frame, memory.readbyte(0x60), memory.readbyte(0x0394), memory.readbyte(0x0395),
      memory.readbyte(0x03BC), memory.readbyte(0x03BD),
      memory.readbyte(0x03C6), memory.readbyte(0x03C7),
      memory.readbyte(0x03D0), memory.readbyte(0x03D1),
      memory.readbyte(0x03DA), memory.readbyte(0x03DB)))
    for i = 0, 15 do
      local o = 0x0200 + i * 4
      log:write(string.format("%02X:%02X,%02X,%02X,%02X ", i,
        memory.readbyte(o), memory.readbyte(o+1), memory.readbyte(o+2), memory.readbyte(o+3)))
    end
    log:write("\n")
    log:flush()
    gui.savescreenshotas(out..frame..[[.png]])
  end
  emu.frameadvance()
end
log:close(); emu.exit()
