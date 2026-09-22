-- M07 runtime acceptance helper.
-- Uses only normal controller input: no RAM writes and no CPU jumps.
local frame = 0
local captures = { [675]=true, [750]=true, [900]=true, [1200]=true,
                   [1800]=true, [2400]=true, [3600]=true, [5000]=true }

local function pulse(first, last)
    return frame >= first and frame < last
end

emu.addEventCallback(function()
    -- Move from START to CONTINUE, then confirm with the configured Start key.
    local press_down = pulse(720, 726)
    local press_start = pulse(760, 766) or pulse(1250, 1256)
    -- Confirm menus and advance dialogue using normal A-button pulses.
    local press_a = frame >= 800 and frame % 24 < 3
    emu.setInput({ down = press_down, start = press_start, a = press_a }, 0)
end, emu.eventType.inputPolled)

emu.addEventCallback(function()
    frame = frame + 1
    if captures[frame] then
        local name = string.format("m07-frame-%04d.png", frame)
        local image = assert(io.open(name, "wb"))
        image:write(emu.takeScreenshot())
        image:close()
        print(string.format("CAPTURE frame=%d file=%s pc=%04X", frame, name, emu.getState().cpu.pc))
    end
    if frame == 5000 then
        print(string.format("RESULT frames=%d pc=%04X", frame, emu.getState().cpu.pc))
        emu.stop(0)
    end
end, emu.eventType.endFrame)
