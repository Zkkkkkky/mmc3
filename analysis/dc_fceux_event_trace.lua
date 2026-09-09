-- Trace the fixed-bank visual-event VM while booting the unexpanded source ROM.
-- The expanded ROM keeps banks $00-$3F byte-identical, so discovered offsets
-- remain applicable. FCEUX is used only for this low-bank reverse-engineering run.

local output = assert(io.open("../analysis/dc_fceux_event_trace.log", "w"))
local frame = 0
local hits = 0
local seen = {}
local bank_select = 0
local prg_bank_8000 = -1
local prg_bank_a000 = -1

memory.registerwrite(0x8000, 1, function(_address, _size, value)
    bank_select = value
end)

memory.registerwrite(0x8001, 1, function(_address, _size, value)
    local register = bank_select % 8
    if register == 6 then prg_bank_8000 = value end
    if register == 7 then prg_bank_a000 = value end
end)

local function hex_bytes(address, count)
    local result = {}
    for index = 0, count - 1 do
        result[#result + 1] = string.format("%02X", memory.readbyte(address + index))
    end
    return table.concat(result, " ")
end

memory.registerexec(0xE844, function()
    local pointer = memory.readbyte(0x0090) + memory.readbyte(0x0091) * 0x100
    hits = hits + 1
    if not seen[pointer] then
        seen[pointer] = true
        output:write(string.format(
            "frame=%d map=%02X pointer=%04X bank8000=%02X bankA000=%02X bytes=%s\n",
            frame, memory.readbyte(0x00CD), pointer,
            prg_bank_8000, prg_bank_a000, hex_bytes(pointer, 48)))
        output:flush()
    end
end)

emu.speedmode("maximum")
emu.softreset()
for current = 1, 12000 do
    frame = current
    local input = {
        A = false, B = false, start = false, select = false,
        up = false, down = false, left = false, right = false,
    }
    if (current >= 720 and current < 724) or
       (current >= 844 and current < 848) or
       (current >= 920 and current % 40 < 4) then
        input.A = true
    end
    joypad.set(1, input)
    emu.frameadvance()
    if current == 1000 or current == 2000 or current == 11990 then
        gui.savescreenshotas(string.format("../analysis/dc_event_frame_%05d.png", current))
    end
end

local unique = 0
for _key, _value in pairs(seen) do unique = unique + 1 end
output:write(string.format("RESULT frames=%d hits=%d unique=%d\n", frame, hits, unique))
output:close()
emu.exit()
