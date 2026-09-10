-- Runtime validation for the 1 MiB Mapper 194 dual-audio ROM.
--
-- This deliberately checks Mesen's resolved PRG-ROM offsets at each entry
-- point.  A CPU-address-only test can falsely pass in an emulator that wraps
-- Mapper 194 banks above 512 KiB.

local output_path = emu.getScriptDataFolder() .. "/dc_mesen_dual_audio.log"
local output = assert(io.open(output_path, "w"))
local failures = {}
local checks = 0

local function read_byte(address)
    return emu.read(address, emu.memType.cpuDebug, false)
end

local function write_byte(address, value)
    emu.write(address, value, emu.memType.cpuDebug)
end

local function prg_offset(address)
    local value = emu.getPrgRomOffset(address)
    if value == nil then
        return -1
    end
    return value
end

local function check(name, condition, detail)
    checks = checks + 1
    local status = condition and "PASS" or "FAIL"
    output:write(string.format("%s %s %s\n", status, name, detail or ""))
    output:flush()
    if not condition then
        failures[#failures + 1] = name
    end
end

local counters = {
    fixed = 0,
    fixed_wrong = 0,
    stock = 0,
    stock_wrong = 0,
    bridge = 0,
    bridge_wrong = 0,
    init = 0,
    play = 0,
    update = 0,
    sfx = 0,
    engine_wrong = 0,
    song61 = 0,
    song62 = 0,
    song63 = 0,
    song_wrong = 0,
    apu = 0,
    bridge_magic = 0,
    suppressed_game_music = 0,
}

local test_hold_custom = false

local function register_exec(address, callback)
    emu.addMemoryCallback(
        callback,
        emu.memCallbackType.cpuExec,
        address,
        address)
end

register_exec(0xFDF0, function()
    local offset = prg_offset(0xFDF0)
    if offset == 0xFFDF0 then
        counters.fixed = counters.fixed + 1
    else
        counters.fixed_wrong = counters.fixed_wrong + 1
    end
end)

register_exec(0x8020, function()
    local offset = prg_offset(0x8020)
    if offset == 0x30020 then
        counters.stock = counters.stock + 1
    else
        counters.stock_wrong = counters.stock_wrong + 1
    end
end)

register_exec(0xB500, function()
    local offset = prg_offset(0xB500)
    if offset == 0xC9500 then
        counters.bridge = counters.bridge + 1
    else
        counters.bridge_wrong = counters.bridge_wrong + 1
    end
    if read_byte(0x0468) == 0x5A and
       read_byte(0x0469) == 0xA5 and
       read_byte(0x046A) == 0xC3 then
        counters.bridge_magic = counters.bridge_magic + 1
    end
    if test_hold_custom then
        local command = read_byte(0x004C)
        if command >= 0x80 and (command < 0x9D or command > 0x9F) then
            write_byte(0x004C, 0xFF)
            counters.suppressed_game_music =
                counters.suppressed_game_music + 1
        end
    end
end)

local function record_engine_entry(kind)
    local engine_offset = prg_offset(0xA000)
    if engine_offset ~= 0xC8000 then
        counters.engine_wrong = counters.engine_wrong + 1
        return
    end
    counters[kind] = counters[kind] + 1
end

local function record_song_mapping()
    local state = read_byte(0x046B)
    local offset = prg_offset(0x8000)
    local expected = -1
    if state == 0x9D then expected = 0xC2000 end
    if state == 0x9E then expected = 0xC4000 end
    if state == 0x9F then expected = 0xC6000 end
    if expected >= 0 and offset == expected then
        if state == 0x9D then counters.song61 = counters.song61 + 1 end
        if state == 0x9E then counters.song62 = counters.song62 + 1 end
        if state == 0x9F then counters.song63 = counters.song63 + 1 end
    elseif expected >= 0 then
        counters.song_wrong = counters.song_wrong + 1
    end
end

register_exec(0xA000, function()
    record_engine_entry("init")
    record_song_mapping()
end)

register_exec(0xA003, function()
    record_engine_entry("play")
end)

register_exec(0xA009, function()
    record_engine_entry("update")
    record_song_mapping()
end)

register_exec(0xA00F, function()
    record_engine_entry("sfx")
end)

emu.addMemoryCallback(
    function()
        local active = read_byte(0x046B)
        if active >= 0x9D and active <= 0x9F then
            counters.apu = counters.apu + 1
        end
    end,
    emu.memCallbackType.cpuWrite,
    0x4000,
    0x4013)

local frame = 0
local phase = "boot"
local deadline = 300
local stock_before = 0
local apu_before = 0
local play_before = 0
local update_before = 0
local sfx_before = 0
local next_sfx = 55

local function verify_custom_song(name, command, expected_counter)
    local counter_value = counters[expected_counter]
    check(
        name,
        read_byte(0x046B) == command and
        read_byte(0x0052) == (command % 0x20) and
        counters.play > play_before and
        counters.update > update_before and
        counter_value > 0 and
        counters.apu > apu_before,
        string.format(
            "active=%02X current=%02X play_delta=%d update_delta=%d " ..
            "bank_hits=%d apu_delta=%d",
            read_byte(0x046B), read_byte(0x0052),
            counters.play - play_before, counters.update - update_before,
            counter_value, counters.apu - apu_before))
end

local function finish()
    check(
        "true-1mib-fixed-bank",
        counters.fixed == 1 and counters.fixed_wrong == 0,
        string.format("hits=%d wrong=%d", counters.fixed, counters.fixed_wrong))
    check(
        "stock-audio-patched-in-place",
        counters.stock > 100 and counters.stock_wrong == 0,
        string.format("hits=%d wrong=%d", counters.stock, counters.stock_wrong))
    check(
        "true-1mib-engine-bank",
        counters.bridge > 100 and counters.bridge_wrong == 0 and
        counters.engine_wrong == 0,
        string.format(
            "bridge=%d bridge_wrong=%d engine_wrong=%d",
            counters.bridge, counters.bridge_wrong, counters.engine_wrong))
    check(
        "all-three-expanded-song-banks",
        counters.song61 > 0 and counters.song62 > 0 and counters.song63 > 0 and
        counters.song_wrong == 0,
        string.format(
            "bank61=%d bank62=%d bank63=%d wrong=%d",
            counters.song61, counters.song62, counters.song63,
            counters.song_wrong))
    check(
        "bridge-state-initialized",
        counters.bridge_magic > 1000,
        string.format("valid_frames=%d", counters.bridge_magic))
    check(
        "famistudio-apu-output",
        counters.apu > 1000,
        string.format("writes=%d", counters.apu))
    check(
        "engine-entry-counts",
        counters.init >= 3 and counters.play >= 3 and counters.update > 300,
        string.format(
            "init=%d play=%d update=%d sfx=%d",
            counters.init, counters.play, counters.update, counters.sfx))

    local state = emu.getState()
    output:write(string.format(
        "RESULT checks=%d failures=%d frames=%d pc=%04X " ..
        "stock=%d bridge=%d init=%d play=%d update=%d sfx=%d apu=%d\n",
        checks, #failures, frame, state.cpu.pc,
        counters.stock, counters.bridge, counters.init, counters.play,
        counters.update, counters.sfx, counters.apu))
    if #failures > 0 then
        output:write("FAILED_NAMES " .. table.concat(failures, ",") .. "\n")
    end
    output:close()
    emu.stop(#failures == 0 and 0 or 1)
end

emu.addEventCallback(function()
    frame = frame + 1
    if frame < deadline then return end

    if phase == "boot" then
        check(
            "booted-with-expanded-fixed-banks",
            counters.fixed == 1 and counters.stock > 100 and counters.bridge > 100,
            string.format(
                "fixed=%d stock=%d bridge=%d",
                counters.fixed, counters.stock, counters.bridge))
        stock_before = counters.stock
        write_byte(0x004C, 0x85)
        phase = "stock-song"
        deadline = frame + 8
    elseif phase == "stock-song" then
        check(
            "original-song-stays-stock",
            counters.stock > stock_before and counters.play == 0,
            string.format(
                "active=%02X stock_delta=%d current=%02X",
                read_byte(0x046B), counters.stock - stock_before,
                read_byte(0x0052)))
        apu_before = counters.apu
        play_before = counters.play
        update_before = counters.update
        test_hold_custom = true
        write_byte(0x004C, 0x9D)
        phase = "ash-start"
        deadline = frame + 8
    elseif phase == "ash-start" then
        verify_custom_song("ash-to-ash", 0x9D, "song61")
        phase = "ash-sustain"
        deadline = frame + 3600
    elseif phase == "ash-sustain" then
        check(
            "ash-keeps-updating",
            read_byte(0x046B) == 0x9D and counters.update - update_before > 3500,
            string.format(
                "active=%02X update_delta=%d",
                read_byte(0x046B), counters.update - update_before))
        apu_before = counters.apu
        play_before = counters.play
        update_before = counters.update
        write_byte(0x004C, 0x9E)
        phase = "dark-knight"
        deadline = frame + 8
    elseif phase == "dark-knight" then
        verify_custom_song("dark-knight", 0x9E, "song62")
        apu_before = counters.apu
        update_before = counters.update
        phase = "dark-knight-sustain"
        deadline = frame + 3600
    elseif phase == "dark-knight-sustain" then
        check(
            "dark-knight-keeps-updating",
            read_byte(0x046B) == 0x9E and
            counters.update - update_before > 3500 and
            counters.apu > apu_before,
            string.format(
                "active=%02X update_delta=%d apu_delta=%d",
                read_byte(0x046B), counters.update - update_before,
                counters.apu - apu_before))
        apu_before = counters.apu
        play_before = counters.play
        update_before = counters.update
        write_byte(0x004C, 0x9F)
        phase = "dark-prison"
        deadline = frame + 8
    elseif phase == "dark-prison" then
        verify_custom_song("dark-prison", 0x9F, "song63")
        apu_before = counters.apu
        update_before = counters.update
        phase = "dark-prison-sustain"
        deadline = frame + 3600
    elseif phase == "dark-prison-sustain" then
        check(
            "dark-prison-keeps-updating",
            read_byte(0x046B) == 0x9F and
            counters.update - update_before > 3500 and
            counters.apu > apu_before,
            string.format(
                "active=%02X update_delta=%d apu_delta=%d",
                read_byte(0x046B), counters.update - update_before,
                counters.apu - apu_before))
        sfx_before = counters.sfx
        phase = "sfx"
        deadline = frame + 1
    elseif phase == "sfx" then
        if next_sfx >= 0 then
            write_byte(0x004C, next_sfx)
            next_sfx = next_sfx - 1
            deadline = frame + 3
        else
            check(
                "all-56-famistudio-sfx",
                counters.sfx - sfx_before == 56,
                string.format("calls=%d", counters.sfx - sfx_before))
            stock_before = counters.stock
            test_hold_custom = false
            write_byte(0x004C, 0x89)
            phase = "return-stock"
            deadline = frame + 8
        end
    elseif phase == "return-stock" then
        check(
            "return-to-stock-engine",
            counters.stock > stock_before and
            not (read_byte(0x0468) == 0x5A and
                 read_byte(0x0469) == 0xA5 and
                 read_byte(0x046A) == 0xC3),
            string.format(
                "active=%02X stock_delta=%d current=%02X",
                read_byte(0x046B), counters.stock - stock_before,
                read_byte(0x0052)))
        finish()
    end
end, emu.eventType.endFrame)
