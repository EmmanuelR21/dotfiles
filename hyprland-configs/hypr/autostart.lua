-------------------
---- AUTOSTART ----
-------------------

-- See https://wiki.hypr.land/Configuring/Basics/Autostart/

-- Autostart necessary processes (like notifications daemons, status bars, etc.)
-- Or execute your favorite apps at launch like this:

local host = require("host")

hl.on("hyprland.start", function ()
     hl.exec_cmd("systemctl --user start hyprpolkitagent")
     hl.exec_cmd("dunst")
     hl.exec_cmd("waybar & hyprpaper")
     hl.exec_cmd("hypridle")
     hl.exec_cmd("hyprlauncher -d")

     -- Low / critical battery warnings and charger plugged / unplugged (laptops only)
     if host.has_battery then
          hl.exec_cmd("~/.config/hypr/scripts/battery-notify.sh")
     end
 end)
