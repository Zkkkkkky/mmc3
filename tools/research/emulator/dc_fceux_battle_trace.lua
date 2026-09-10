-- Trace banked service calls and SRAM writes during the first scenario.

local output = assert(io.open("../../../output/verification/fceux/dc_fceux_battle_trace.log", "w"))
local frame = 0
local bank_select = 0
local prg_bank_8000 = -1
local prg_bank_a000 = -1
local seen_dispatch = {}
local seen_write = {}
local write_lines = 0

memory.registerwrite(0x8000, 1, function(_address, _size, value)
    bank_select = value
end)

memory.registerwrite(0x8001, 1, function(_address, _size, value)
    local register = bank_select % 8
    if register == 6 then prg_bank_8000 = value end
    if register == 7 then prg_bank_a000 = value end
end)

memory.registerexec(0xFE55, function()
    if frame < 650 then return end
    local bank = memory.readbyte(0x00BD)
    local target = memory.readbyte(0x00BE) + memory.readbyte(0x00BF) * 0x100
    local key = string.format("%02X:%04X", bank, target)
    if not seen_dispatch[key] then
        seen_dispatch[key] = true
        output:write(string.format(
            "DISPATCH frame=%d map=%02X key=%s A=%02X X=%02X Y=%02X\n",
            frame, memory.readbyte(0x00CD), key,
            memory.getregister("a"), memory.getregister("x"), memory.getregister("y")))
        output:flush()
    end
end)

memory.registerwrite(0x6000, 0x2000, function(address, _size, value)
    if frame < 650 or write_lines >= 4000 then return end
    local pc = memory.getregister("pc")
    local page = math.floor(address / 0x10)
    local key = string.format("%04X:%03X", pc, page)
    if not seen_write[key] then
        seen_write[key] = true
        write_lines = write_lines + 1
        output:write(string.format(
            "WRITE frame=%d map=%02X pc=%04X addr=%04X value=%02X " ..
            "bank8000=%02X bankA000=%02X\n",
            frame, memory.readbyte(0x00CD), pc, address, value,
            prg_bank_8000, prg_bank_a000))
    end
end)

emu.speedmode("maximum")
emu.softreset()
for current = 1, 2400 do
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
end

output:write(string.format("RESULT frames=%d writeLines=%d\n", frame, write_lines))
output:close()
emu.exit()
