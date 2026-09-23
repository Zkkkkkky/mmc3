local log = assert(io.open([[D:\GIT\mmc3\output\verification\v30-map-restore.tsv]], "w"))
local state = savestate.create([[C:\Users\hu\Desktop\fceux\fcs\测试_真实OAM分屏修复V12.bak.fc0]])
local loaded, load_error = pcall(savestate.load, state)
log:write(string.format("load\t%s\t%s\n", tostring(loaded), tostring(load_error)))
if not loaded then log:close(); emu.exit(); return end

local injected = false
local phase = ""
local active_hits = 0
local restore_hits = 0

memory.registerexec(0xF467, function()
  if not injected then
    memory.writebyte(0x0240, 0x90)
    memory.writebyte(0x0244, 0xE0)
    injected = true
    log:write(string.format("inject\tR0=%02X\tR2=%02X\tR3=%02X\n",
      memory.readbyte(0x04D8), memory.readbyte(0x03D1), memory.readbyte(0x03DB)))
  end
end)

memory.registerexec(0xF522, function()
  active_hits = active_hits + 1
  phase = "active"
end)

memory.registerexec(0xF53B, function()
  restore_hits = restore_hits + 1
  phase = "restore"
end)

memory.registerexec(0xFF65, function()
  log:write(string.format("%s_return\tR0=%02X\tR2=%02X\tR3=%02X\n",
    phase, memory.readbyte(0x04D8), memory.readbyte(0x03D1), memory.readbyte(0x03DB)))
  if phase == "active" then
    for o = 0x0240, 0x02FC, 4 do memory.writebyte(o, 0xF0) end
  end
end)

emu.speedmode("maximum")
for frame = 1, 120 do emu.frameadvance() end
log:write(string.format("summary\tactive=%d\trestore=%d\n", active_hits, restore_hits))
log:close()
emu.exit()
