local log = assert(io.open([[D:\GIT\mmc3\output\verification\v29-weapon-clip.tsv]], "w"))
local state = savestate.create([[C:\Users\hu\Desktop\fceux\fcs\测试_真实OAM分屏修复V12.bak.fc0]])
local loaded, load_error = pcall(savestate.load, state)
log:write(string.format("load\t%s\t%s\n", tostring(loaded), tostring(load_error)))
if not loaded then
  log:close()
  emu.exit()
  return
end
local injected = false
local clip_hits = 0

memory.registerexec(0xF467, function()
  if not injected then
    -- Two synthetic weapon sprites below the $80 UI boundary.
    memory.writebyte(0x0240, 0x90)
    memory.writebyte(0x0244, 0xE0)
    injected = true
    log:write(string.format("inject\t%02X\t%02X\n", memory.readbyte(0x0240), memory.readbyte(0x0244)))
  end
end)

memory.registerexec(0xF54D, function()
  clip_hits = clip_hits + 1
  log:write(string.format("clip_return\t%02X\t%02X\n", memory.readbyte(0x0240), memory.readbyte(0x0244)))
end)

emu.speedmode("maximum")
for frame = 1, 120 do
  emu.frameadvance()
end

log:write(string.format("summary\tinjected=%s\tclip_hits=%d\n", tostring(injected), clip_hits))
log:close()
emu.exit()
