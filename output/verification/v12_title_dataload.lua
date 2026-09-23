local out=[[D:\GIT\mmc3\output\verification\v12-dataload-]]
emu.speedmode("maximum")
for frame=1,800 do
  if frame==100 or frame==120 then joypad.set(1,{select=true}) end
  if frame==110 or frame==130 then gui.savescreenshotas(out..frame..[[.png]]) end
  if frame==150 or frame==155 then joypad.set(1,{start=true}) end
  if frame==220 or frame==350 or frame==500 or frame==800 then gui.savescreenshotas(out..frame..[[.png]]) end
  emu.frameadvance()
end
emu.exit()
