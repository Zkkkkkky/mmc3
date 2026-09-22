-- Test every NES button after the title text has completed.
local frame = 0
local events = {
    { name="a",      first=5200, last=5220 },
    { name="b",      first=5500, last=5520 },
    { name="start",  first=5800, last=5820 },
    { name="select", first=6100, last=6120 },
    { name="right",  first=6400, last=6420 },
    { name="left",   first=6700, last=6720 },
    { name="up",     first=7000, last=7020 },
    { name="down",   first=7300, last=7320 },
}
local captures = { [675]=true, [5100]=true, [5250]=true, [5550]=true,
                   [5850]=true, [6150]=true, [6450]=true, [6750]=true,
                   [7050]=true, [7350]=true, [7600]=true }

local function active(name)
    for _, event in ipairs(events) do
        if event.name == name and frame >= event.first and frame < event.last then
            return true
        end
    end
    return false
end

emu.addEventCallback(function()
    local input = {
        -- Pick CONTINUE early, then leave input released until frame 5200.
        down = (frame >= 700 and frame < 710) or active("down"),
        a = active("a"), b = active("b"), start = active("start"),
        select = active("select"), right = active("right"),
        left = active("left"), up = active("up"),
    }
    emu.setInput(0, input, false)
end, emu.eventType.inputPolled)

emu.addEventCallback(function()
    frame = frame + 1
    if captures[frame] then
        local name = string.format("late-%04d.png", frame)
        local image = assert(io.open(name, "wb"))
        image:write(emu.takeScreenshot())
        image:close()
        print(string.format("CAPTURE frame=%d file=%s pc=%04X", frame, name, emu.getState().cpu.pc))
    end
    if frame == 7600 then
        print(string.format("RESULT frames=%d pc=%04X", frame, emu.getState().cpu.pc))
        emu.stop(0)
    end
end, emu.eventType.endFrame)
