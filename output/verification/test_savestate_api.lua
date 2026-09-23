local log=assert(io.open([[D:\GIT\mmc3\output\verification\savestate-api.txt]],"w"))
local state=savestate.create(1)
emu.speedmode("maximum")
for i=1,120 do
  if i==100 then
    local ok,res=pcall(savestate.save,state)
    log:write("save=",tostring(ok)," result=",tostring(res),"\n")
  end
  emu.frameadvance()
end
log:close();emu.exit()
