local out=[[D:\GIT\mmc3\output\verification\v12-directselect-]]
emu.speedmode("maximum")
for frame=1,1400 do
  if frame==100 or frame==105 then joypad.set(1,{start=true}) end
  if frame>=180 and frame<=900 and frame%8==0 then joypad.set(1,{A=true}) end
  if frame==1100 or frame==1110 or frame==1120 then joypad.set(1,{down=true}) end
  if frame==1130 then joypad.set(1,{left=true}) end
  if frame==1150 then joypad.set(1,{A=true}) end
  if frame==1050 or frame==1140 or frame==1180 or frame==1250 or frame==1400 then
    gui.savescreenshotas(out..frame..[[.png]])
  end
  emu.frameadvance()
end
emu.exit()
