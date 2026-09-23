local state = savestate.create([[C:\Users\hu\Desktop\fceux\fcs\测试.fc0]])
assert(pcall(savestate.load, state))
local prefix = os.getenv("DC_CAPTURE_PREFIX") or [[D:\GIT\mmc3\output\verification\state-window]]
emu.speedmode("maximum")
for frame = 0, 180 do
  if frame == 1 then joypad.set(1, {A=true}) end
  if frame >= 60 and frame <= 150 and frame % 2 == 0 then
    gui.savescreenshotas(prefix .. string.format("-%04d.png", frame))
  end
  emu.frameadvance()
end
emu.exit()
