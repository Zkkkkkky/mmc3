-- Render a selected map animation through the real game interpreter.
-- The generated ROM temporarily redirects the first spirit animation call.
local frame = 0
local function held(first, last) return frame >= first and frame < last end

emu.addEventCallback(function()
    emu.setInput(0, {
        down = held(690,700),
        right = held(1540,1550),
        a = held(740,750) or held(1400,1410) or held(1600,1610)
            or held(1800,1810),
    }, false)
end, emu.eventType.inputPolled)

emu.addEventCallback(function()
    frame = frame + 1
    if frame >= 1820 and frame <= 2600 and frame % 2 == 0 then
        local folder = emu.getScriptDataFolder()
        local name = string.format("%s/runtime-frame-%04d.png", folder, frame)
        local image = assert(io.open(name, "wb"))
        image:write(emu.takeScreenshot())
        image:close()
    end
    if frame == 2610 then emu.stop(0) end
end, emu.eventType.endFrame)
