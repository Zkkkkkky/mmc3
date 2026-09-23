local state=savestate.create([[C:\Users\hu\Desktop\fceux\fcs\DC续威力加强版_全武器CHR分屏根治V10.fc0]])
assert(pcall(savestate.load,state))
emu.speedmode("maximum")
for frame=1,120 do
    if frame==1 or frame==30 or frame==120 then
        gui.savescreenshotas([[D:\GIT\mmc3\output\verification\test-v10-state-]]..frame..[[.png]])
    end
    emu.frameadvance()
end
emu.pause()
