local out=[[D:\GIT\mmc3\output\verification\v38-purple-]]
emu.speedmode("maximum")
for f=1,7230 do
 if f==100 or f==105 then joypad.set(1,{start=true}) end
 if f>=180 and f<=900 and f%8==0 then joypad.set(1,{A=true}) end
 if f==1100 or f==1110 or f==1120 then joypad.set(1,{down=true}) end
 if f==1130 then joypad.set(1,{left=true}) end
 if f==1150 then joypad.set(1,{A=true}) end
 if f==1450 or f==1455 then joypad.set(1,{A=true}) end
 if f==1600 or f==1610 or f==1620 then joypad.set(1,{right=true}) end
 if f==1650 then joypad.set(1,{A=true}) end
 if f==1750 or f==1755 or f==1850 or f==1855 then joypad.set(1,{A=true}) end
 if f>=2250 and f<=7230 and f%90==0 then joypad.set(1,{A=true}) end
 if f>=7040 and f<=7220 and f%3==0 then gui.savescreenshotas(out..f..[[.png]]) end
 emu.frameadvance()
end
emu.exit()
