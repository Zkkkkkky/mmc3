-- Probe whether this Mesen build treats the first controller as index 0 or 1.
-- Normal controller input only; no RAM writes and no CPU jumps.
local frame = 0
local captures = { [675]=true, [760]=true, [860]=true, [960]=true,
                   [1060]=true, [1160]=true, [1400]=true, [2000]=true }

local function held(first, last)
    return frame >= first and frame < last
end

emu.addEventCallback(function()
    local input = {
        start = held(700, 720) or held(1100, 1120),
        a = held(800, 820) or (frame >= 1200 and frame % 30 < 5),
        down = held(900, 920),
        select = held(1000, 1020),
    }
    emu.setInput(input, 0)
    emu.setInput(input, 1)
end, emu.eventType.inputPolled)

emu.addEventCallback(function()
    frame = frame + 1
    if captures[frame] then
        local name = string.format("port-probe-%04d.png", frame)
        local image = assert(io.open(name, "wb"))
        image:write(emu.takeScreenshot())
        image:close()
        print(string.format("CAPTURE frame=%d file=%s pc=%04X", frame, name, emu.getState().cpu.pc))
    end
    if frame == 2000 then
        print(string.format("RESULT frames=%d pc=%04X", frame, emu.getState().cpu.pc))
        emu.stop(0)
    end
end, emu.eventType.endFrame)
