------------------
---- MONITORS ----
------------------

-- See https://wiki.hypr.land/Configuring/Basics/Monitors/
local host = require("host")

if host.profile == "laptop" then
    hl.monitor({
        output   = "eDP-1",
        mode     = "1920x1200@60.00400",
        position = "auto",
        scale    = "1.07",
    })
else
    hl.monitor({
        output   = "DP-1",
        mode     = "1920x1080@180.06Hz",
        position = "auto",
        scale    = "auto",
    })
end

-- Fallback for any monitor not listed above (fresh installs, external screens)
hl.monitor({
    output   = "",
    mode     = "preferred",
    position = "auto",
    scale    = "auto",
})
