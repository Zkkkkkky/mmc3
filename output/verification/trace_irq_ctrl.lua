local log=assert(io.open([[D:\GIT\mmc3\output\verification\irq-ctrl.tsv]],"w"))
local frame=0
log:write("frame\ty\tctrl\tr0\tr1\tr2\tr3\n")
memory.registerexec(0xF9AE,function()
  if frame>=7040 and frame<=7220 then
    local y=memory.getregister("y")
    log:write(string.format("%d\t%02X\t%02X\t%02X\t%02X\t%02X\t%02X\n",frame,y,
      memory.readbyte(0x0394+y),memory.readbyte(0x03BC+y),memory.readbyte(0x03C6+y),
      memory.readbyte(0x03D0+y),memory.readbyte(0x03DA+y)))
  end
end)
emu.speedmode("maximum")
for f=1,7230 do
 frame=f
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
 emu.frameadvance()
end
log:close();emu.exit()
