-- Resume the active battle, open the selected unit menu and choose Attack.
local frame = 0
local captures = { [780]=true, [1500]=true, [1700]=true, [1900]=true,
                   [2200]=true, [2600]=true, [3200]=true }
local function held(first, last) return frame >= first and frame < last end

emu.addEventCallback(function()
    emu.setInput(0, {
        down = held(690, 700) or held(1540, 1550) or held(1590, 1600),
        a = held(740, 750) or held(1400, 1410) or held(1650, 1660),
    }, false)
end, emu.eventType.inputPolled)

emu.addEventCallback(function()
    frame = frame + 1
    if captures[frame] then
        local name = string.format("attack-%04d.png", frame)
        local image = assert(io.open(name, "wb"))
        image:write(emu.takeScreenshot())
        image:close()
    end
    if frame == 3200 then emu.stop(0) end
end, emu.eventType.endFrame)
