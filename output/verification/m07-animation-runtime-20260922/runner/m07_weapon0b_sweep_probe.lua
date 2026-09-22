-- Enter target mode, then sweep candidate tiles until an enemy is accepted.
local frame = 0
local actions = {
    {690,"down"},{720,"down"},{740,"a"},{1400,"a"},
    {1540,"down"},{1590,"down"},{1650,"a"},{1720,"down"},{1800,"a"},
}
local cursor = 1950
local function add(button)
    table.insert(actions, {cursor, button})
    cursor = cursor + 24
end

-- Search upward, then sweep a broad rectangle around the attacker.
for _ = 1, 6 do add("up"); add("a") end
for _ = 1, 8 do add("left"); add("a") end
for row = 1, 12 do
    if row % 2 == 1 then
        for _ = 1, 16 do add("right"); add("a") end
    else
        for _ = 1, 16 do add("left"); add("a") end
    end
    add("down"); add("a")
end

local function active(button)
    for _, action in ipairs(actions) do
        if action[2] == button and frame >= action[1] and frame < action[1] + 6 then
            return true
        end
    end
    return false
end

emu.addEventCallback(function()
    emu.setInput(0, {
        a=active("a"), up=active("up"), down=active("down"),
        left=active("left"), right=active("right"),
    }, false)
end, emu.eventType.inputPolled)

emu.addEventCallback(function()
    frame = frame + 1
    if frame >= 1800 and frame % 100 == 0 then
        local name = string.format("sweep0b-%05d.png", frame)
        local image = assert(io.open(name, "wb"))
        image:write(emu.takeScreenshot())
        image:close()
    end
    if frame == 13000 then emu.stop(0) end
end, emu.eventType.endFrame)
