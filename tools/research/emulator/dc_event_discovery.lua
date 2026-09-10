-- Runtime discovery aid for the fixed-bank visual event VM at CPU $E844.
-- It advances past the title with conservative A/Start pulses, records every
-- unique script pointer and mapped PRG offset, then exits under --testrunner.

local output_path = emu.getScriptDataFolder() .. "/dc_event_discovery.log"
local output = assert(io.open(output_path, "w"))
local frame = 0
local hits = 0
local seen = {}

local function read_byte(address)
    return emu.read(address, emu.memType.cpuDebug, false)
end

emu.addMemoryCallback(function()
    local pointer = read_byte(0x00AA) + read_byte(0x00AD) * 0x100
    local mapped = emu.getPrgRomOffset(pointer)
    local key = string.format("%04X:%X", pointer, mapped or -1)
    hits = hits + 1
    if not seen[key] then
        seen[key] = true
        local bytes = {}
        for index = 0, 31 do
            bytes[#bytes + 1] = string.format(
                "%02X", emu.read(pointer + index, emu.memType.cpuDebug, false))
        end
        output:write(string.format(
            "frame=%d pointer=%04X prg=%X bytes=%s\n",
            frame, pointer, mapped or -1, table.concat(bytes, " ")))
        output:flush()
    end
end, emu.memCallbackType.cpuExec, 0xE844, 0xE844)

emu.addEventCallback(function()
    local press_start = frame >= 700 and frame < 706
    local press_a = frame >= 730 and frame % 24 < 2
    emu.setInput({ start = press_start, a = press_a }, 0)
end, emu.eventType.inputPolled)

emu.addEventCallback(function()
    frame = frame + 1
    if frame == 3000 then
        local state = emu.getState()
        local unique = 0
        for _key, _value in pairs(seen) do unique = unique + 1 end
        output:write(string.format(
            "RESULT frames=%d hits=%d unique=%d pc=%04X prg=%X\n",
            frame, hits, unique, state.cpu.pc,
            emu.getPrgRomOffset(state.cpu.pc) or -1))
        output:close()
        emu.stop(0)
    end
end, emu.eventType.endFrame)
