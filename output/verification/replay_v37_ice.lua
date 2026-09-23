local state = savestate.create([[D:\GIT\mmc3\output\verification\v5.fc0]])
assert(pcall(savestate.load, state))
emu.speedmode("maximum")
for frame = 1, 600 do
  if frame <= 5 then joypad.set(1, {A=true}) end
  if frame == 570 then gui.savescreenshotas([[D:\GIT\mmc3\output\verification\v37-ice-570.png]]) end
  emu.frameadvance()
end
emu.exit()
