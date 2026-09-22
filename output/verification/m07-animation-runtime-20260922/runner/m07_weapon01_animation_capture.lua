-- Drive the verified active-battle fixture and capture the selected weapon's
-- battle playback densely enough to retain transient animation frames.
local frame = 0
local function held(first, last) return frame >= first and frame < last end
local function advance_dialogue()
    if frame < 2200 or frame > 8000 then return false end
    return ((frame - 2200) % 120) < 8
end

emu.addEventCallback(function()
    emu.setInput(0, {
        down = held(690,700) or held(1540,1550) or held(1590,1600),
        up = held(1950,1956),
        a = held(740,750) or held(1400,1410) or held(1650,1660)
            or held(1800,1810) or held(2050,2060) or advance_dialogue(),
    }, false)
end, emu.eventType.inputPolled)

emu.addEventCallback(function()
    frame = frame + 1
    if frame >= 2000 and frame <= 2700 then
        local name = string.format("animation-%05d.png", frame)
        local image = assert(io.open(name, "wb"))
        image:write(emu.takeScreenshot())
        image:close()
    end
    if frame == 8200 then emu.stop(0) end
end, emu.eventType.endFrame)
