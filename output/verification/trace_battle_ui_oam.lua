local log = assert(io.open([[D:\GIT\mmc3\output\verification\battle-ui-oam.log]], "w"))
emu.speedmode("maximum")
for frame = 1, 7350 do
  if frame == 100 or frame == 105 then joypad.set(1, {start=true}) end
  if frame >= 180 and frame <= 900 and frame % 8 == 0 then joypad.set(1, {A=true}) end
  if frame == 1100 or frame == 1110 or frame == 1120 then joypad.set(1, {down=true}) end
  if frame == 1130 then joypad.set(1, {left=true}) end
  if frame == 1150 then joypad.set(1, {A=true}) end
  if frame == 1450 or frame == 1455 then joypad.set(1, {A=true}) end
  if frame == 1600 or frame == 1610 or frame == 1620 then joypad.set(1, {right=true}) end
  if frame == 1650 then joypad.set(1, {A=true}) end
  if frame == 1750 or frame == 1755 or frame == 1850 or frame == 1855 then joypad.set(1, {A=true}) end
  if frame >= 2250 and frame <= 7350 and frame % 90 == 0 then joypad.set(1, {A=true}) end
  if frame >= 6800 and frame <= 7350 and frame % 5 == 0 then
    log:write(string.format("F%04d ctrl=%02X r0=%02X r1=%02X ui:", frame,
      memory.readbyte(0x0395), memory.readbyte(0x04D8), memory.readbyte(0x04D9)))
    for slot=0,15 do
      local a=0x0200+slot*4
      local y=memory.readbyte(a)
      if y < 0xF0 then
        log:write(string.format(" %02d[%02X,%02X,%02X,%02X]", slot, y,
          memory.readbyte(a+1), memory.readbyte(a+2), memory.readbyte(a+3)))
      end
    end
    log:write(" cross:")
    for slot=16,63 do
      local a=0x0200+slot*4
      local y=memory.readbyte(a)
      if y >= 0x70 and y < 0xF0 then
        log:write(string.format(" %02d[%02X,%02X,%02X,%02X]", slot, y,
          memory.readbyte(a+1), memory.readbyte(a+2), memory.readbyte(a+3)))
      end
    end
    log:write("\n")
    if frame == 6900 then
      log:write("IRQ_SELECT:")
      for i=0,15 do log:write(string.format(" %02X", memory.readbyte(0x03BC+i))) end
      log:write("\nIRQ_VALUE :")
      for i=0,15 do log:write(string.format(" %02X", memory.readbyte(0x03C6+i))) end
      log:write("\nCTRL_TABLE:")
      for i=0,15 do log:write(string.format(" %02X", memory.readbyte(0x038C+i))) end
      log:write("\nIRQ_R0:")
      for i=0,9 do log:write(string.format(" %02X", memory.readbyte(0x03BC+i))) end
      log:write("\nIRQ_R1:")
      for i=0,9 do log:write(string.format(" %02X", memory.readbyte(0x03C6+i))) end
      log:write("\nIRQ_R2:")
      for i=0,9 do log:write(string.format(" %02X", memory.readbyte(0x03D0+i))) end
      log:write("\nIRQ_R3:")
      for i=0,9 do log:write(string.format(" %02X", memory.readbyte(0x03DA+i))) end
      log:write("\nIRQ_R4:")
      for i=0,9 do log:write(string.format(" %02X", memory.readbyte(0x03E4+i))) end
      log:write("\nIRQ_R5:")
      for i=0,9 do log:write(string.format(" %02X", memory.readbyte(0x03EE+i))) end
      log:write("\nTOP:")
      for i=0,7 do log:write(string.format(" %02X", memory.readbyte(0x04D8+i))) end
      log:write("\n")
    end
  end
  emu.frameadvance()
end
log:close()
emu.exit()
