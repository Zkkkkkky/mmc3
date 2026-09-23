local f=assert(io.open([[D:\GIT\mmc3\output\verification\test.sav]],"rb"))
local data=f:read("*all")
f:close()
assert(#data==0x2000)
for index=1,#data do memory.writebyte(0x5FFF+index,string.byte(data,index)) end
emu.speedmode("maximum")
for frame=1,1000 do
    if frame>=400 and frame<=402 then joypad.set(1,{select=true}) end
    if frame>=430 and frame<=432 then joypad.set(1,{start=true}) end
    if frame>=500 and frame<=502 then joypad.set(1,{A=true}) end
    if frame==390 or frame==420 or frame==460 or frame==600 or frame==800 or frame==1000 then
        gui.savescreenshotas([[D:\GIT\mmc3\output\verification\injected-save-]]..frame..[[.png]])
    end
    emu.frameadvance()
end
emu.pause()
