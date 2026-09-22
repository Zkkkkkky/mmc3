-- Open DATA LOAD and select the first verified save slot.
local frame = 0
local captures = { [900]=true, [980]=true, [1200]=true, [1800]=true,
                   [3000]=true, [5000]=true, [8000]=true }
local function held(first, last) return frame >= first and frame < last end

emu.addEventCallback(function()
    emu.setInput(0, {
        down = held(690, 700) or held(720, 730),
        a = held(760, 770) or held(950, 960),
    }, false)
end, emu.eventType.inputPolled)

emu.addEventCallback(function()
    frame = frame + 1
    if captures[frame] then
        local name = string.format("slot-%04d.png", frame)
        local image = assert(io.open(name, "wb"))
        image:write(emu.takeScreenshot())
        image:close()
    end
    if frame == 8000 then emu.stop(0) end
end, emu.eventType.endFrame)
