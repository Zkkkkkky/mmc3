local state_path = [[D:\GIT\mmc3\output\verification\v5.fc0]]
local log_path = [[D:\GIT\mmc3\output\verification\enemy_ice_blade_oam_writes.tsv]]
local log = assert(io.open(log_path, "w"))
local frame = 0

local function trace_oam_write(address, size, value)
    if address % 4 == 0 then
        log:write(string.format("%d\t%04X\t%04X\t%02X\n",
            frame, memory.getregister("pc"), address, value))
    end
end

local state = savestate.create(state_path)
assert(pcall(savestate.load, state))
log:write("frame\tpc\taddress\ty\n")
memory.registerwrite(0x0200, 0x0100, trace_oam_write)
emu.speedmode("maximum")

for i = 1, 900 do
    frame = i
    if i <= 5 then
        joypad.set(1, {A = true})
    end
    emu.frameadvance()
    if i % 30 == 0 then
        gui.savescreenshotas([[D:\GIT\mmc3\output\verification\ice-frame-]] .. i .. [[.png]])
    end
end

log:flush()
log:close()
emu.pause()
