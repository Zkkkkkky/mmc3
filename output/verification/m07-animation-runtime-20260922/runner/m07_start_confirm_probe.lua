-- Probe title-screen confirmation while the cursor remains on START.
-- Mesen 0.9.9 uses emu.setInput(port, inputTable, allowUserInput).
local frame = 0
local events = {
    { name="a",       first=5200, last=5220 },
    { name="b",       first=5500, last=5520 },
    { name="start",   first=5800, last=5820 },
    { name="a_b",     first=6100, last=6120 },
    { name="a_start", first=6400, last=6420 },
    { name="b_start", first=6700, last=6720 },
}
local captures = { [5100]=true, [5250]=true, [5550]=true, [5850]=true,
                   [6150]=true, [6450]=true, [6750]=true, [7000]=true }

local function active(name)
    for _, event in ipairs(events) do
        if event.name == name and frame >= event.first and frame < event.last then
            return true
        end
    end
    return false
end

emu.addEventCallback(function()
    local ab = active("a_b")
    local ast = active("a_start")
    local bst = active("b_start")
    emu.setInput(0, {
        a = active("a") or ab or ast,
        b = active("b") or ab or bst,
        start = active("start") or ast or bst,
    }, false)
end, emu.eventType.inputPolled)

emu.addEventCallback(function()
    frame = frame + 1
    if captures[frame] then
        local name = string.format("start-%04d.png", frame)
        local image = assert(io.open(name, "wb"))
        image:write(emu.takeScreenshot())
        image:close()
        print(string.format("CAPTURE frame=%d file=%s pc=%04X", frame, name, emu.getState().cpu.pc))
    end
    if frame == 7000 then
        print(string.format("RESULT frames=%d pc=%04X", frame, emu.getState().cpu.pc))
        emu.stop(0)
    end
end, emu.eventType.endFrame)
