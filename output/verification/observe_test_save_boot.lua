emu.speedmode("maximum")
for frame=1,360 do
    if frame==1 or frame==60 or frame==120 or frame==180 or frame==240 or frame==300 or frame==360 then
        gui.savescreenshotas([[D:\GIT\mmc3\output\verification\test-save-boot-]]..frame..[[.png]])
    end
    emu.frameadvance()
end
emu.pause()
