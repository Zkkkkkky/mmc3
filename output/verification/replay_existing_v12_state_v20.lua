local state=savestate.create([[C:\Users\hu\Desktop\fceux\fcs\测试_真实OAM分屏修复V12.bak.fc0]])
local ok=pcall(savestate.load,state)
local log=assert(io.open([[D:\GIT\mmc3\output\verification\existing-state-load.txt]],"w"))
log:write("load=",tostring(ok),"\n")
emu.speedmode("maximum")
for frame=1,3000 do
  if frame%30==0 then joypad.set(1,{A=true}) end
  if frame%2==0 then gui.savescreenshotas([[D:\GIT\mmc3\output\verification\v20-existing-]]..frame..[[.png]]) end
  emu.frameadvance()
end
log:close();emu.exit()
