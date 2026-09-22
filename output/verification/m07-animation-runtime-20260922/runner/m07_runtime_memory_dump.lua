-- Restore CONTINUE and dump internal CPU RAM plus battery RAM at the map.
local frame = 0

emu.addEventCallback(function()
    emu.setInput(0, {
        down = frame >= 690 and frame < 696,
        a = frame >= 735 and frame < 741,
    }, false)
end, emu.eventType.inputPolled)

emu.addEventCallback(function()
    frame = frame + 1
    if frame == 1000 then
        local output = assert(io.open("runtime-memory.bin", "wb"))
        for address = 0, 0x7FFF do
            output:write(string.char(emu.read(address, emu.memType.cpuDebug, false)))
        end
        output:close()
        local image = assert(io.open("runtime-memory.png", "wb"))
        image:write(emu.takeScreenshot())
        image:close()
        emu.stop(0)
    end
end, emu.eventType.endFrame)
