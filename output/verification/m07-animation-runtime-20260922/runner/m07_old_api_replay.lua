-- Mesen 0.9.9 uses emu.setInput(port, input, allowUserInput).
-- Normal controller input only; no RAM writes and no CPU jumps.
local frame = 0
local captures = { [675]=true, [760]=true, [860]=true, [1000]=true,
                   [1250]=true, [1600]=true, [2200]=true, [3000]=true,
                   [4200]=true, [6000]=true }

local function held(first, last)
    return frame >= first and frame < last
end

emu.addEventCallback(function()
    local input = {
        down = held(700, 706),
        start = held(740, 746) or held(1200, 1206),
        a = frame >= 780 and frame % 24 < 3,
        b = false,
        up = false,
        left = false,
        right = false,
        select = false,
    }
    emu.setInput(0, input, false)
end, emu.eventType.inputPolled)

emu.addEventCallback(function()
    frame = frame + 1
    if captures[frame] then
        local name = string.format("old-api-%04d.png", frame)
        local image = assert(io.open(name, "wb"))
        image:write(emu.takeScreenshot())
        image:close()
        print(string.format("CAPTURE frame=%d file=%s pc=%04X", frame, name, emu.getState().cpu.pc))
    end
    if frame == 6000 then
        print(string.format("RESULT frames=%d pc=%04X", frame, emu.getState().cpu.pc))
        emu.stop(0)
    end
end, emu.eventType.endFrame)
