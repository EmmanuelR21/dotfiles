------------------------
---- HOST DETECTION ----
------------------------

-- Figures out what kind of machine this is, so the shared configs can pick
-- per-device settings. Everything is detected from the hardware, so it works
-- on a fresh install without any setup.
--
-- Usage: local host = require("host")
--   host.profile      -> "desktop" or "laptop"
--   host.has_battery  -> true if a battery exists
--   host.has_nvidia   -> true if the NVIDIA driver is loaded

local function read(path)
    local f = io.open(path, "r")
    if not f then return nil end
    local line = f:read("*l")
    f:close()
    return line
end

-- Firmware chassis codes that mean "portable": Portable, Laptop, Notebook,
-- Sub Notebook, Convertible, Detachable
local laptop_chassis = { [8] = true, [9] = true, [10] = true, [14] = true, [31] = true, [32] = true }

local host = {}

host.has_battery = read("/sys/class/power_supply/BAT0/type") ~= nil
    or read("/sys/class/power_supply/BAT1/type") ~= nil

host.has_nvidia = read("/proc/driver/nvidia/version") ~= nil

local chassis = tonumber(read("/sys/class/dmi/id/chassis_type") or "")
host.profile = (laptop_chassis[chassis] or host.has_battery) and "laptop" or "desktop"

return host
