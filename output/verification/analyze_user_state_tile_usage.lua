local state = savestate.create([[C:\Users\hu\Desktop\fceux\fcs\测试.fc0]])
assert(pcall(savestate.load, state))
local out = os.getenv("DC_USAGE_LOG") or [[D:\GIT\mmc3\output\verification\user-state-tile-usage.log]]
local seen = {}
local byphase = {{},{},{}}
emu.speedmode("maximum")
for frame = 0, 430 do
  if frame == 1 or (frame >= 150 and frame % 30 == 0) then joypad.set(1,{A=true}) end
  local phase = frame < 170 and 1 or (frame < 400 and 2 or 3)
  for addr=0x0200,0x02FC,4 do
    local y=memory.readbyte(addr)
    if y < 0xF0 then
      local t=memory.readbyte(addr+1)
      seen[t]=true; byphase[phase][t]=true
    end
  end
  emu.frameadvance()
end
local f=assert(io.open(out,"w"))
local function line(label,s)
  f:write(label,":")
  for t=0,255 do if s[t] then f:write(string.format(" %02X",t)) end end
  f:write("\n")
end
line("all",seen); line("player",byphase[1]); line("enemy",byphase[2]); line("after",byphase[3])
f:write("unused-runs:")
local start=nil
for t=0,256 do
  if t<256 and not seen[t] then if not start then start=t end
  elseif start then f:write(string.format(" %02X-%02X(%d)",start,t-1,t-start)); start=nil end
end
f:write("\n"); f:close(); emu.exit()
