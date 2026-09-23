local out = [[D:\GIT\mmc3\output\verification\v12-direct-]]
emu.speedmode("normal")
for frame=1,420 do
  if frame==30 or frame==90 or frame==150 or frame==210 or frame==300 or frame==420 then
    gui.savescreenshotas(out..frame..[[.png]])
  end
  if frame==100 or frame==105 then joypad.set(1,{start=true}) end
  if frame==180 or frame==185 then joypad.set(1,{A=true}) end
  emu.frameadvance()
end
emu.pause()
