local state = savestate.create([[C:\Users\hu\Desktop\fceux\fcs\测试.fc0]])
local ok, err = pcall(savestate.load, state)
local log = io.open([[D:\GIT\mmc3\output\verification\load-user-fc0.log]], "w")
log:write("load_ok=", tostring(ok), "\n")
if not ok then log:write("error=", tostring(err), "\n") end
log:close()
gui.savescreenshotas([[D:\GIT\mmc3\output\verification\user-fc0-preview.png]])
for i = 1, 2 do emu.frameadvance() end
emu.exit()
