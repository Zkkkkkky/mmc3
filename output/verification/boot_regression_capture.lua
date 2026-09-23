local prefix=os.getenv("DC_CAPTURE_PREFIX") or [[D:\GIT\mmc3\output\verification\boot]]
emu.speedmode("maximum")
for frame=1,650 do
  if frame>=100 and frame<=140 then joypad.set(1,{start=true}) end
  if frame>=180 and frame<=500 and frame%8==0 then joypad.set(1,{A=true}) end
  if frame==100 or frame==300 or frame==600 or frame==650 then gui.savescreenshotas(prefix.."-"..frame..".png") end
  emu.frameadvance()
end
emu.exit()
