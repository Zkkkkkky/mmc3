-- Execute the second weapon and move the target cursor one tile upward.
local frame = 0
local captures = {}
for value = 1700, 6500, 100 do captures[value] = true end
local function held(first, last) return frame >= first and frame < last end

emu.addEventCallback(function()
    emu.setInput(0, {
        down = held(690, 700) or held(1540, 1550) or held(1590, 1600)
            or held(1720, 1730),
        up = held(1950, 1960),
        a = held(740, 750) or held(1400, 1410) or held(1650, 1660)
            or held(1800, 1810) or held(2050, 2060) or held(2400, 2410)
            or held(3000, 3010) or held(3800, 3810) or held(4600, 4610),
    }, false)
end, emu.eventType.inputPolled)

emu.addEventCallback(function()
    frame = frame + 1
    if captures[frame] then
        local name = string.format("target0b-%04d.png", frame)
        local image = assert(io.open(name, "wb"))
        image:write(emu.takeScreenshot())
        image:close()
    end
    if frame == 6500 then emu.stop(0) end
end, emu.eventType.endFrame)
