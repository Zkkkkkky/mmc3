local state=savestate.create([[D:\GIT\mmc3\output\verification\v12-newgame-map.fc0]])
emu.speedmode("maximum")
for frame=1,1100 do
  if frame==100 or frame==105 then joypad.set(1,{start=true}) end
  if frame>=180 and frame<=900 and frame%8==0 then joypad.set(1,{A=true}) end
  if frame==1050 then
    savestate.save(state)
    gui.savescreenshotas([[D:\GIT\mmc3\output\verification\v12-map-state.png]])
  end
  emu.frameadvance()
end
emu.exit()
