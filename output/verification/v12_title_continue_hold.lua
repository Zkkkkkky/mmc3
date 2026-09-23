local out=[[D:\GIT\mmc3\output\verification\v12-continuehold-]]
emu.speedmode("maximum")
for frame=1,1600 do
  if frame>=150 and frame<=165 then joypad.set(1,{down=true}) end
  if frame==180 then gui.savescreenshotas(out..frame..[[.png]]) end
  if frame>=210 and frame<=225 then joypad.set(1,{A=true,start=true}) end
  if frame==280 or frame==450 or frame==800 or frame==1200 or frame==1600 then
    gui.savescreenshotas(out..frame..[[.png]])
  end
  emu.frameadvance()
end
emu.exit()
