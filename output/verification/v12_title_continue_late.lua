local out=[[D:\GIT\mmc3\output\verification\v12-continuelate-]]
emu.speedmode("maximum")
for frame=1,1200 do
  if frame==160 then joypad.set(1,{down=true}) end
  if frame==175 then gui.savescreenshotas(out..frame..[[.png]]) end
  if frame==200 or frame==205 then joypad.set(1,{A=true}) end
  if frame==260 or frame==400 or frame==700 or frame==1200 then gui.savescreenshotas(out..frame..[[.png]]) end
  emu.frameadvance()
end
emu.exit()
