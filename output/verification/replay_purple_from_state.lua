local state=savestate.create([[D:\GIT\mmc3\output\verification\purple-pre.fc0]])
assert(pcall(savestate.load,state))
local out = [[D:\GIT\mmc3\output\verification\purple-replay-]]
emu.speedmode("maximum")
for frame=1,1200 do
  if frame % 30 == 0 then joypad.set(1,{A=true}) end
  if frame % 3 == 0 then gui.savescreenshotas(out..frame..[[.png]]) end
  emu.frameadvance()
end
emu.exit()
