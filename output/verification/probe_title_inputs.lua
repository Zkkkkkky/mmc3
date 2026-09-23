emu.speedmode("maximum")
for frame=1,400 do emu.frameadvance() end
local state=savestate.create([[D:\GIT\mmc3\output\verification\test-title.fc0]])
savestate.save(state)
local actions={"up","down","left","right","A","B","select","start"}
for _,action in ipairs(actions) do
    savestate.load(state)
    for frame=1,60 do
        if frame>=2 and frame<=4 then local input={};input[action]=true;joypad.set(1,input) end
        emu.frameadvance()
    end
    gui.savescreenshotas([[D:\GIT\mmc3\output\verification\title-input-]]..action..[[.png]])
end
emu.pause()
