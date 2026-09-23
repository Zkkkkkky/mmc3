local input_state = savestate.create([[C:\Users\hu\Desktop\fceux\fcs\测试.fc0]])
assert(pcall(savestate.load, input_state))
local output_state = savestate.create(0)

emu.speedmode("maximum")

for frame = 0, 279 do
  if frame == 1 or (frame >= 150 and frame % 30 == 0) then
    joypad.set(1, {A = true})
  end
  emu.frameadvance()
end

savestate.save(output_state)
gui.savescreenshotas([[D:\GIT\mmc3\output\verification\V57_目标帧280_存档画面.png]])
emu.exit()
