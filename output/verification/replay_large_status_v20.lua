local state=savestate.create([[D:\GIT\mmc3\output\verification\large-ui.fc0]])
assert(pcall(savestate.load,state))
emu.speedmode("maximum")
for frame=1,260 do
  if frame==2 then joypad.set(1,{B=true}) end
  if frame==62 or frame==67 or frame==72 then joypad.set(1,{left=true}) end
  if frame==77 or frame==82 then joypad.set(1,{up=true}) end
  if frame==115 then joypad.set(1,{A=true}) end
  if frame==205 then joypad.set(1,{right=true}) end
  if frame==180 or frame==240 then gui.savescreenshotas([[D:\GIT\mmc3\output\verification\v20-large-form-]]..frame..[[.png]]) end
  emu.frameadvance()
end
emu.exit()
