-- Capture a deterministic title-screen frame for source/expanded comparison.

local frames = 0

emu.addEventCallback(function()
    frames = frames + 1
    if frames == 675 then
        local folder = emu.getScriptDataFolder()
        local image = assert(io.open(folder .. "/frame675.png", "wb"))
        image:write(emu.takeScreenshot())
        image:close()

        local state = emu.getState()
        local report = assert(io.open(folder .. "/frame675.txt", "w"))
        report:write(string.format(
            "frame=%d pc=%04X prg=%X\n",
            frames, state.cpu.pc, emu.getPrgRomOffset(state.cpu.pc)))
        report:close()
        emu.stop(0)
    end
end, emu.eventType.endFrame)
