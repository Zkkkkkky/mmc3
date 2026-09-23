local frame=0
emu.addEventCallback(function()
    frame=frame+1
    if frame==120 then
        local used={}
        local base=0x2000
        for i=0,0x3BF do
            used[emu.read(base+i,emu.memType.ppuDebug,false)]=true
        end
        local values={}
        for i=0,255 do if used[i] then values[#values+1]=string.format("%02X",i) end end
        print("TITLE_TILES "..table.concat(values," "))
        emu.stop(0)
    end
end,emu.eventType.endFrame)
