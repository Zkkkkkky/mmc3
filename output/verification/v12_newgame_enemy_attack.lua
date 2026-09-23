local out=[[D:\GIT\mmc3\output\verification\v12-attack-]]
emu.speedmode("maximum")
for frame=1,3200 do
  if frame==100 or frame==105 then joypad.set(1,{start=true}) end
  if frame>=180 and frame<=900 and frame%8==0 then joypad.set(1,{A=true}) end
  if frame==1100 or frame==1110 or frame==1120 then joypad.set(1,{down=true}) end
  if frame==1130 then joypad.set(1,{left=true}) end
  if frame==1150 then joypad.set(1,{A=true}) end
  if frame==1450 or frame==1455 then joypad.set(1,{A=true}) end
  if frame>=1350 and frame%10==0 then
    gui.savescreenshotas(out..frame..[[.png]])
  end
  emu.frameadvance()
end
emu.exit()
