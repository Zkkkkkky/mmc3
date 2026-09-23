local state=savestate.create([[D:\GIT\mmc3\output\verification\v12-newgame-map.fc0]])
assert(pcall(savestate.load,state))
emu.speedmode("maximum")
for frame=1,180 do
  if frame==10 or frame==20 or frame==30 then joypad.set(1,{down=true}) end
  if frame==40 then joypad.set(1,{left=true}) end
  if frame==60 then joypad.set(1,{A=true}) end
  if frame==90 or frame==140 or frame==180 then
    gui.savescreenshotas([[D:\GIT\mmc3\output\verification\v12-select-]]..frame..[[.png]])
  end
  emu.frameadvance()
end
emu.exit()
