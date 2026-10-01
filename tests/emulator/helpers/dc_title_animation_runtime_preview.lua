-- Render animation $00 in its real title-screen invocation context.
local frame = 0

emu.addEventCallback(function()
    frame = frame + 1
    if frame >= 300 and frame <= 850 and frame % 2 == 0 then
        local folder = emu.getScriptDataFolder()
        local name = string.format("%s/runtime-frame-%04d.png", folder, frame)
        local image = assert(io.open(name, "wb"))
        image:write(emu.takeScreenshot())
        image:close()
    end
    if frame == 860 then emu.stop(0) end
end, emu.eventType.endFrame)
