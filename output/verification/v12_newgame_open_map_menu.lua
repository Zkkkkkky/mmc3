local out=[[D:\GIT\mmc3\output\verification\v12-mapmenu-]]
emu.speedmode("maximum")
for frame=1,2000 do
  if frame==100 or frame==105 then joypad.set(1,{start=true}) end
  if frame>=180 and frame<=900 and frame%8==0 then joypad.set(1,{A=true}) end
  if frame==1100 or frame==1110 or frame==1120 then joypad.set(1,{down=true}) end
  if frame==1130 then joypad.set(1,{left=true}) end
  if frame==1150 then joypad.set(1,{A=true}) end
  if frame==1450 or frame==1455 then joypad.set(1,{A=true}) end
  if frame==1650 then joypad.set(1,{A=true}) end
  if frame==1700 or frame==1800 or frame==2000 then gui.savescreenshotas(out..frame..[[.png]]) end
  emu.frameadvance()
end
emu.exit()
