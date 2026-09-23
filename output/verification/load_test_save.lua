emu.speedmode("maximum")
for frame=1,900 do
    if frame>=400 and frame<=402 then joypad.set(1,{select=true}) end
    if frame>=430 and frame<=432 then joypad.set(1,{select=true}) end
    if frame>=460 and frame<=462 then joypad.set(1,{start=true}) end
    if frame>=520 and frame<=522 then joypad.set(1,{A=true}) end
    if frame>=560 and frame<=562 then joypad.set(1,{start=true}) end
    if frame==420 or frame==500 or frame==600 or frame==750 or frame==900 then
        gui.savescreenshotas([[D:\GIT\mmc3\output\verification\test-save-load-]]..frame..[[.png]])
    end
    emu.frameadvance()
end
emu.pause()
