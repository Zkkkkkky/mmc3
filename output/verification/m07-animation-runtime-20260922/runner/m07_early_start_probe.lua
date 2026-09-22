-- Confirm START immediately after the title menu becomes available.
local frame = 0
local captures = { [675]=true, [720]=true, [900]=true, [1200]=true,
                   [1800]=true, [2400]=true, [3600]=true, [5000]=true }

emu.addEventCallback(function()
    emu.setInput(0, { a = frame >= 700 and frame < 710 }, false)
end, emu.eventType.inputPolled)

emu.addEventCallback(function()
    frame = frame + 1
    if captures[frame] then
        local name = string.format("early-%04d.png", frame)
        local image = assert(io.open(name, "wb"))
        image:write(emu.takeScreenshot())
        image:close()
    end
    if frame == 5000 then
        emu.stop(0)
    end
end, emu.eventType.endFrame)
