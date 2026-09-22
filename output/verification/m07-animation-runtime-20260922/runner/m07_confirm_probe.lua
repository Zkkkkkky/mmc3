-- Confirm-button probe using the verified Mesen 0.9.9 input signature.
local frame = 0
local captures = { [675]=true, [740]=true, [800]=true, [940]=true,
                   [1080]=true, [1250]=true, [1500]=true, [1800]=true }

local function held(first, last)
    return frame >= first and frame < last
end

emu.addEventCallback(function()
    local input = {
        down = held(700, 710),
        b = held(760, 780),
        a = held(900, 920) or (frame >= 1200 and frame % 30 < 5),
        start = held(1040, 1060),
        up = false, left = false, right = false, select = false,
    }
    emu.setInput(0, input, false)
end, emu.eventType.inputPolled)

emu.addEventCallback(function()
    frame = frame + 1
    if captures[frame] then
        local name = string.format("confirm-%04d.png", frame)
        local image = assert(io.open(name, "wb"))
        image:write(emu.takeScreenshot())
        image:close()
        print(string.format("CAPTURE frame=%d file=%s pc=%04X", frame, name, emu.getState().cpu.pc))
    end
    if frame == 1800 then
        print(string.format("RESULT frames=%d pc=%04X", frame, emu.getState().cpu.pc))
        emu.stop(0)
    end
end, emu.eventType.endFrame)
