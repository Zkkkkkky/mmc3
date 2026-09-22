-- Enter DATA LOAD using a verified three-slot battery save.
local frame = 0
local captures = { [675]=true, [760]=true, [900]=true, [1200]=true,
                   [1800]=true, [2400]=true, [3600]=true, [5000]=true }

local function held(first, last)
    return frame >= first and frame < last
end

emu.addEventCallback(function()
    emu.setInput(0, {
        down = held(690, 700) or held(720, 730),
        a = held(760, 770),
    }, false)
end, emu.eventType.inputPolled)

emu.addEventCallback(function()
    frame = frame + 1
    if captures[frame] then
        local name = string.format("data-load-%04d.png", frame)
        local image = assert(io.open(name, "wb"))
        image:write(emu.takeScreenshot())
        image:close()
    end
    if frame == 5000 then emu.stop(0) end
end, emu.eventType.endFrame)
