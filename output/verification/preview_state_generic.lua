local path=assert(os.getenv("DC_STATE_PATH")); local prefix=assert(os.getenv("DC_CAPTURE_PREFIX"))
local state=savestate.create(path); assert(pcall(savestate.load,state)); emu.speedmode("maximum")
for frame=0,180 do
  if frame<=5 then joypad.set(1,{A=true}) end
  if frame==0 or frame==30 or frame==60 or frame==90 or frame==120 or frame==180 then gui.savescreenshotas(prefix.."-"..frame..".png") end
  emu.frameadvance()
end
emu.exit()
