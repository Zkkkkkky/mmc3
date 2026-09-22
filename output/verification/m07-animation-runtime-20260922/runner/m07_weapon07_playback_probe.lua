-- Resume a verified active battle and execute the first equipped weapon ($07).
local frame = 0
local captures = {}
for value = 1500, 6000, 100 do captures[value] = true end
local function held(first, last) return frame >= first and frame < last end

emu.addEventCallback(function()
    emu.setInput(0, {
        down = held(690, 700) or held(1540, 1550) or held(1590, 1600),
        a = held(740, 750) or held(1400, 1410) or held(1650, 1660)
            or held(1800, 1810) or held(2050, 2060) or held(2300, 2310)
            or held(2800, 2810) or held(3400, 3410) or held(4000, 4010),
    }, false)
end, emu.eventType.inputPolled)

emu.addEventCallback(function()
    frame = frame + 1
    if captures[frame] then
        local name = string.format("weapon07-%04d.png", frame)
        local image = assert(io.open(name, "wb"))
        image:write(emu.takeScreenshot())
        image:close()
    end
    if frame == 6000 then emu.stop(0) end
end, emu.eventType.endFrame)
