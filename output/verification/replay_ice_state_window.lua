local state=savestate.create([[D:\GIT\mmc3\output\verification\v5.fc0]])
assert(pcall(savestate.load,state)); emu.speedmode("maximum")
local prefix=os.getenv("DC_CAPTURE_PREFIX") or [[D:\GIT\mmc3\output\verification\ice-window]]
for frame=1,620 do
  if frame<=5 then joypad.set(1,{A=true}) end
  if frame>=500 and frame<=610 and frame%2==0 then gui.savescreenshotas(prefix..string.format("-%03d.png",frame)) end
  emu.frameadvance()
end
emu.exit()
