local state=savestate.create([[D:\GIT\mmc3\output\verification\large-ui.fc0]])
assert(pcall(savestate.load,state)); emu.speedmode("maximum")
local prefix=os.getenv("DC_CAPTURE_PREFIX") or [[D:\GIT\mmc3\output\verification\large-ui]]
for frame=1,60 do
  if frame==1 or frame==30 or frame==60 then gui.savescreenshotas(prefix.."-"..frame..".png") end
  emu.frameadvance()
end
emu.exit()
