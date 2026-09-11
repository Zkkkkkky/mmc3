-- Deterministic normal-input replay derived from dc_event_discovery.lua.
-- Does not patch RAM or jump the CPU. Run in an isolated Mesen folder.
-- Relative filenames avoid Lua 5.3 narrow-path I/O failures on Windows.
local frame = 0
local glyph_reads = 0
local first_read = -1
local last_read = -1
local glyph_value = -1
local target_prg_offset = 0x76C24 -- DAC2, file offset 0x76C34 minus iNES header.

for _, address in ipairs({0x8C24, 0xAC24, 0xCC24, 0xEC24}) do
    emu.addMemoryCallback(function(read_address, value)
        if emu.getPrgRomOffset(read_address) == target_prg_offset then
            glyph_reads = glyph_reads + 1
            if first_read < 0 then first_read = frame end
            last_read = frame
            glyph_value = value
        end
    end, emu.memCallbackType.cpuRead, address, address)
end

emu.addEventCallback(function()
    local press_start = (frame >= 700 and frame < 706) or (frame >= 1250 and frame < 1256)
    local press_a = frame >= 730 and frame % 24 < 2
    emu.setInput({start = press_start, a = press_a}, 0)
end, emu.eventType.inputPolled)

emu.addEventCallback(function()
    frame = frame + 1
    if frame == 675 or frame == 1000 or frame == 2000 or frame == 3000 or frame == 5000 then
        local path = string.format("font-frame-%04d.png", frame)
        local image = assert(io.open(path, "wb"))
        image:write(emu.takeScreenshot())
        image:close()
        print(string.format("CAPTURE frame=%d file=%s pc=%04X glyph_reads=%d",
              frame, path, emu.getState().cpu.pc, glyph_reads))
    end
    if frame == 5000 then
        print(string.format("RESULT frames=%d glyph_reads=%d first_read=%d last_read=%d glyph_value=%02X",
              frame, glyph_reads, first_read, last_read, glyph_value))
        emu.stop(0)
    end
end, emu.eventType.endFrame)
