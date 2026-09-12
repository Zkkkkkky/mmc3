-- Runtime-only terrain palette probe.  It does not patch RAM, ROM, or PC.

local frame = 0
local record_reads = 0
local palette_writes = 0
local snapshots = {}

local function hex_bytes(values)
    local parts = {}
    for _, value in ipairs(values) do
        parts[#parts + 1] = string.format("%02X", value)
    end
    return table.concat(parts, " ")
end

local function read_cpu_range(first, count)
    local values = {}
    for offset = 0, count - 1 do
        values[#values + 1] = emu.read(first + offset, emu.memType.cpuDebug, false)
    end
    return values
end

local function read_ppu_palette()
    local values = {}
    for offset = 0, 0x1F do
        values[#values + 1] = emu.read(0x3F00 + offset, emu.memType.ppuDebug, false)
    end
    return values
end

local function snapshot(label)
    local state = emu.getState()
    local ram = read_cpu_range(0x0490, 0x20)
    local ppu = read_ppu_palette()
    local line = string.format(
        "SNAP frame=%d label=%s pc=%04X prg=%X ram=%s ppu=%s reads=%d writes=%d",
        frame, label, state.cpu.pc, emu.getPrgRomOffset(state.cpu.pc),
        hex_bytes(ram), hex_bytes(ppu), record_reads, palette_writes)
    print(line)
    snapshots[#snapshots + 1] = line
    local image = assert(io.open(string.format("palette-frame-%04d.png", frame), "wb"))
    image:write(emu.takeScreenshot())
    image:close()
end

emu.addMemoryCallback(function(read_address, value)
    local offset = emu.getPrgRomOffset(read_address)
    if offset ~= nil and offset >= 0x6050 and offset < 0x62A0 then
        record_reads = record_reads + 1
        if record_reads <= 24 then
            print(string.format(
                "RECORD_READ frame=%d cpu=%04X prg=%X value=%02X",
                frame, read_address, offset, value))
        end
    end
end, emu.memCallbackType.cpuRead, 0x8000, 0xBFFF)

emu.addMemoryCallback(function(address, value)
    palette_writes = palette_writes + 1
    if palette_writes <= 64 then
        print(string.format(
            "PALETTE_WRITE frame=%d address=%04X value=%02X",
            frame, address, value))
    end
end, emu.memCallbackType.cpuWrite, 0x0490, 0x04AF)

emu.addEventCallback(function()
    -- Choose CONTINUE once the title menu is stable, then confirm repeatedly.
    local down = frame >= 690 and frame < 696
    local press_a = (frame >= 715 and frame < 721) or
                    (frame >= 850 and frame % 40 < 2) or
                    (frame >= 1300 and frame % 30 < 2)
    local press_start = frame >= 1100 and frame < 1106
    emu.setInput({down = down, a = press_a, start = press_start}, 0)
end, emu.eventType.inputPolled)

emu.addEventCallback(function()
    frame = frame + 1
    if frame == 675 or frame == 750 or frame == 1000 or frame == 1500 or
       frame == 2200 or frame == 3200 or frame == 5000 then
        snapshot("checkpoint")
    end
    if frame == 5000 then
        print(string.format(
            "RESULT frames=%d record_reads=%d palette_writes=%d snapshots=%d",
            frame, record_reads, palette_writes, #snapshots))
        emu.stop(record_reads > 0 and 0 or 2)
    end
end, emu.eventType.endFrame)
