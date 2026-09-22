-- Trace the ROM unit->weapon table while opening the active unit's attack menu.
local frame = 0
local trace = assert(io.open("weapon-table-trace.log", "wb"))
local function held(first, last) return frame >= first and frame < last end

emu.addMemoryCallback(function(address, value)
    local offset = emu.getPrgRomOffset(address)
    if offset ~= nil and offset >= 0xB2D8 and offset < 0xB4D8 then
        local state = emu.getState()
        trace:write(string.format(
            "frame=%d cpu=%04X prg=%X value=%02X pc=%04X pc_prg=%X a=%02X x=%02X y=%02X sp=%02X\n",
            frame, address, offset, value, state.cpu.pc,
            emu.getPrgRomOffset(state.cpu.pc), state.cpu.a, state.cpu.x,
            state.cpu.y, state.cpu.sp))
        trace:flush()
    end
end, emu.memCallbackType.cpuRead, 0x8000, 0xFFFF)

emu.addEventCallback(function()
    emu.setInput(0, {
        down = held(690,700) or held(1540,1550) or held(1590,1600),
        a = held(740,750) or held(1400,1410) or held(1650,1660),
    }, false)
end, emu.eventType.inputPolled)

emu.addEventCallback(function()
    frame = frame + 1
    if frame == 2000 then
        trace:close()
        emu.stop(0)
    end
end, emu.eventType.endFrame)
