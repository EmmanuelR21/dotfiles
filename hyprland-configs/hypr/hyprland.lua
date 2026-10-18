-- Refer to the wiki for more information.
-- https://wiki.hypr.land/Configuring/Start/
-- You can (and should!!) split this configuration into multiple files
-- Create your files separately and then require them like this:
-- require("myColors")
require("monitors")
require("autostart")
require("binds")

-------------------------------
---- ENVIRONMENT VARIABLES ----
-------------------------------

hl.env("HYPRCURSOR_SIZE", "24")

-- NVIDIA --
hl.env("LIBVA_DRIVER_NAME", "nvidia")
hl.env("__GLX_VENDOR_LIBRARY_NAME", "nvidia")
hl.env("XDG_SESSION_TYPE", "wayland")

-----------------------
---- LOOK AND FEEL ----
-----------------------

-- Refer to https://wiki.hypr.land/Configuring/Basics/Variables/
hl.config({
    general = {
        gaps_in          = 3,
        gaps_out         = 6,

        border_size      = 2,

        col              = {
            active_border   = { colors = { "rgba(999999ff)" }, angle = 45 },
            inactive_border = "rgba(595959AA)",
        },

        -- Set to true to enable resizing windows by clicking and dragging on borders and gaps
        resize_on_border = false,

        -- Please see https://wiki.hypr.land/Configuring/Advanced-and-Cool/Tearing/ before you turn this on
        allow_tearing    = false,

        layout           = "dwindle",
    },

    decoration = {
        rounding         = 0,
        rounding_power   = 0,

        -- Change transparency of focused and unfocused windows
        active_opacity   = 1.0,
        inactive_opacity = 1.0,

        shadow           = {
            enabled      = true,
            range        = 4,
            render_power = 3,
            color        = 0xee1a1a1a,
        },

        blur             = {
            enabled  = true,
            size     = 3,
            passes   = 1,
            vibrancy = 0.1696,
        },
    },

    animations = {
        enabled = true,
    },
})

-- Two curves, shared everywhere:
--   snap   : fast start, long soft settle (easeOutExpo-ish) -> feels heavy, not floaty
--   weight : same feel with a tiny overshoot, so moving windows "land"
hl.curve("snap", { type = "bezier", points = { { 0.22, 1 }, { 0.36, 1 } } })
hl.curve("weight", { type = "bezier", points = { { 0.25, 0.9 }, { 0.2, 1.02 } } })

-- speed is in deciseconds: 3.5 = 350ms. Things that appear take 3.5, things that leave take 2.5.
hl.animation({ leaf = "global", enabled = true, speed = 3.5, bezier = "snap" })
hl.animation({ leaf = "border", enabled = true, speed = 3.5, bezier = "snap" })

hl.animation({ leaf = "windows", enabled = true, speed = 3.5, bezier = "weight" })
hl.animation({ leaf = "windowsIn", enabled = true, speed = 3.5, bezier = "weight", style = "popin 92%" })
hl.animation({ leaf = "windowsOut", enabled = true, speed = 2.5, bezier = "snap", style = "popin 92%" })

hl.animation({ leaf = "fade", enabled = true, speed = 3.5, bezier = "snap" })
hl.animation({ leaf = "fadeOut", enabled = true, speed = 2.5, bezier = "snap" })

hl.animation({ leaf = "layers", enabled = true, speed = 3.5, bezier = "snap", style = "fade" })
hl.animation({ leaf = "layersOut", enabled = true, speed = 2.5, bezier = "snap", style = "fade" })

hl.animation({ leaf = "workspaces", enabled = true, speed = 3.5, bezier = "snap", style = "slide" })

hl.animation({ leaf = "zoomFactor", enabled = true, speed = 3.5, bezier = "snap" })

-- See https://wiki.hypr.land/Configuring/Layouts/Dwindle-Layout/ for more
hl.config({
    dwindle = {
        preserve_split = true, -- You probably want this
    },
})

-- See https://wiki.hypr.land/Configuring/Layouts/Master-Layout/ for more
hl.config({
    master = {
        new_status = "master",
    },
})

-- See https://wiki.hypr.land/Configuring/Layouts/Scrolling-Layout/ for more
hl.config({
    scrolling = {
        fullscreen_on_one_column = true,
    },
})

----------------
----  MISC  ----
----------------

hl.config({
    misc = {
        force_default_wallpaper  = 0,    -- Set to 0 or 1 to disable the anime mascot wallpapers
        disable_hyprland_logo    = true, -- true disables the random hyprland logo/anime girl background.
        disable_splash_rendering = true, -- true disables the splash screen.
    },
})


---------------
---- INPUT ----
---------------

hl.config({
    input = {
        kb_layout    = "us",
        kb_variant   = "",
        kb_model     = "",
        kb_options   = "",
        kb_rules     = "",

        follow_mouse = 0,

        sensitivity  = 0, -- -1.0 - 1.0, 0 means no modification.

        touchpad     = {
            natural_scroll = false,
        },
    },
})

hl.gesture({
    fingers = 3,
    direction = "horizontal",
    action = "workspace"
})

-- Example per-device config
-- See https://wiki.hypr.land/Configuring/Advanced-and-Cool/Devices/ for more
hl.device({
    name        = "epic-mouse-v1",
    sensitivity = -0.5,
})

--------------------------------
---- WINDOWS AND WORKSPACES ----
--------------------------------

-- See https://wiki.hypr.land/Configuring/Basics/Window-Rules/
-- and https://wiki.hypr.land/Configuring/Basics/Workspace-Rules/

-- Example window rules that are useful

local suppressMaximizeRule = hl.window_rule({
    -- Ignore maximize requests from all apps. You'll probably like this.
    name           = "suppress-maximize-events",
    match          = { class = ".*" },

    suppress_event = "maximize",
})
-- suppressMaximizeRule:set_enabled(false)

hl.window_rule({
    -- Fix some dragging issues with XWayland
    name     = "fix-xwayland-drags",
    match    = {
        class      = "^$",
        title      = "^$",
        xwayland   = true,
        float      = true,
        fullscreen = false,
        pin        = false,
    },

    no_focus = false,
})

-- Hyprland-run windowrule
hl.window_rule({
    name  = "move-hyprland-run",
    match = { class = "hyprland-run" },

    move  = "20 monitor_h-120",
    float = true,
})
