local out = [[D:\GIT\mmc3\output\verification\v12-continue-]]
emu.speedmode("maximum")
for frame=1,900 do
  if frame==90 then joypad.set(1,{down=true}) end
  if frame==100 or frame==105 then joypad.set(1,{start=true}) end
  if frame==150 or frame==240 or frame==360 or frame==540 or frame==720 or frame==900 then
    gui.savescreenshotas(out..frame..[[.png]])
  end
  emu.frameadvance()
end
emu.pause()
