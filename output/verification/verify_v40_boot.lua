emu.speedmode("maximum")
for frame = 1, 650 do
  if frame >= 100 and frame <= 140 then joypad.set(1, {start=true}) end
  if frame >= 180 and frame <= 500 and frame % 8 == 0 then joypad.set(1, {A=true}) end
  if frame == 600 then gui.savescreenshotas([[D:\GIT\mmc3\output\verification\v40-boot-600.png]]) end
  emu.frameadvance()
end
emu.exit()
