-- Confirm when the unmodified game itself stops invoking its stock audio hook.

local frames = 0
local calls = 0
local last_call_frame = -1

emu.addMemoryCallback(function()
    if emu.getPrgRomOffset(0x8020) == 0x30020 then
        calls = calls + 1
        last_call_frame = frames
    end
end, emu.memCallbackType.cpuExec, 0x8020, 0x8020)

emu.addEventCallback(function()
    frames = frames + 1
    if frames == 2000 then
        local path = emu.getScriptDataFolder() .. "/stock_lifetime.txt"
        local output = assert(io.open(path, "w"))
        output:write(string.format(
            "frames=%d calls=%d last_call_frame=%d pc=%04X\n",
            frames, calls, last_call_frame, emu.getState().cpu.pc))
        output:close()
        emu.stop(0)
    end
end, emu.eventType.endFrame)
