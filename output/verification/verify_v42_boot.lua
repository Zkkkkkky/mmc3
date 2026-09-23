emu.speedmode("maximum")
for frame = 1, 1000 do
  if frame >= 100 and frame <= 140 then joypad.set(1, {start=true}) end
  if frame >= 180 and frame <= 500 and frame % 8 == 0 then joypad.set(1, {A=true}) end
  if frame == 100 or frame == 200 or frame == 400 or frame == 600 or frame == 800 or frame == 1000 then
    gui.savescreenshotas([[D:\GIT\mmc3\output\verification\v42-boot-]]..frame..[[.png]])
  end
  emu.frameadvance()
end
emu.exit()
