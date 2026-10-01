-- Read-only runtime trace for the A-G terrain-property records.
-- It advances from the title screen into the first battle and records the
-- exact instruction that consumes every attribute byte.  No ROM/RAM writes
-- are injected by this script.

local frame = 0
local reads = 0

emu.addMemoryCallback(function(address, value)
    local offset = emu.getPrgRomOffset(address)
    if offset ~= nil and offset >= 0x6050 and offset < 0x62A0 then
        local state = emu.getState()
        reads = reads + 1
        print(string.format(
            "ATTR_READ frame=%d cpu=%04X prg=%05X value=%02X " ..
            "pc=%04X pc_prg=%05X a=%02X x=%02X y=%02X",
            frame, address, offset, value, state.cpu.pc,
            emu.getPrgRomOffset(state.cpu.pc), state.cpu.a,
            state.cpu.x, state.cpu.y))
    end
end, emu.memCallbackType.cpuRead, 0x8000, 0xBFFF)

emu.addEventCallback(function()
    local press_down = frame >= 690 and frame < 696
    local press_a = frame >= 735 and frame < 741
    emu.setInput(0, {down = press_down, a = press_a}, false)
end, emu.eventType.inputPolled)

emu.addEventCallback(function()
    frame = frame + 1
    if frame == 900 then
        print(string.format("RESULT frames=%d attribute_reads=%d", frame, reads))
        emu.stop(reads > 0 and 0 or 2)
    end
end, emu.eventType.endFrame)
