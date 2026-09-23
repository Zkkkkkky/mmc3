local state = savestate.create([[C:\Users\hu\Desktop\fceux\fcs\测试.fc0]])
assert(pcall(savestate.load, state))
local prefix = os.getenv("DC_CAPTURE_PREFIX") or [[D:\GIT\mmc3\output\verification\full-turn]]
emu.speedmode("maximum")
local shot = 0
for frame = 0, 1400 do
  if frame == 1 or (frame >= 150 and frame % 30 == 0) then joypad.set(1, {A=true}) end
  if frame % 10 == 0 then
    gui.savescreenshotas(prefix .. string.format("-%03d-f%04d.png", shot, frame))
    shot = shot + 1
  end
  emu.frameadvance()
end
emu.exit()
