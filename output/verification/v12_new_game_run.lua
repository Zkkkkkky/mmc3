local out = [[D:\GIT\mmc3\output\verification\v12-newgame-]]
emu.speedmode("maximum")
for frame=1,6000 do
  if frame==100 or frame==105 then joypad.set(1,{start=true}) end
  if frame>=180 and frame%8==0 then joypad.set(1,{A=true}) end
  if frame%200==0 then gui.savescreenshotas(out..frame..[[.png]]) end
  emu.frameadvance()
end
emu.pause()
