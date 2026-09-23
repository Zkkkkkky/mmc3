local out = [[D:\GIT\mmc3\output\verification\v30d-purple-]]
local log = assert(io.open([[D:\GIT\mmc3\output\verification\v30d-purple.tsv]], "w"))
log:write("frame\tcrossing\tR0\tR2\tR3\n")
emu.speedmode("maximum")
for frame = 1, 7400 do
  if frame == 100 or frame == 105 then joypad.set(1, {start=true}) end
  if frame >= 180 and frame <= 900 and frame % 8 == 0 then joypad.set(1, {A=true}) end
  if frame == 1100 or frame == 1110 or frame == 1120 then joypad.set(1, {down=true}) end
  if frame == 1130 then joypad.set(1, {left=true}) end
  if frame == 1150 then joypad.set(1, {A=true}) end
  if frame == 1450 or frame == 1455 then joypad.set(1, {A=true}) end
  if frame == 1600 or frame == 1610 or frame == 1620 then joypad.set(1, {right=true}) end
  if frame == 1650 then joypad.set(1, {A=true}) end
  if frame == 1750 or frame == 1755 or frame == 1850 or frame == 1855 then joypad.set(1, {A=true}) end
  if frame >= 2250 and frame <= 7300 and frame % 90 == 0 then joypad.set(1, {A=true}) end

  if frame >= 6800 then
    local crossing = 0
    for o = 0x0240, 0x02FC, 4 do
      local y = memory.readbyte(o)
      if y >= 0x80 and y < 0xF0 then crossing = crossing + 1 end
    end
    if crossing > 0 then
      log:write(string.format("%d\t%d\t%02X\t%02X\t%02X\n", frame, crossing,
        memory.readbyte(0x04D8), memory.readbyte(0x03D1), memory.readbyte(0x03DB)))
    end
    if frame <= 7300 and frame % 3 == 0 then gui.savescreenshotas(out..frame..[[.png]]) end
    if frame == 7113 then
      for base = 0x0380, 0x03F0, 0x10 do
        local values = {}
        for i = 0, 15 do values[#values+1] = string.format("%02X", memory.readbyte(base+i)) end
        log:write(string.format("RAM%04X\t%s\n", base, table.concat(values, " ")))
      end
    end
  end
  emu.frameadvance()
end
log:close()
emu.exit()
