#!/bin/bash

# Ensure graphical environment variables are passed if launched via systemd/hyprland
export XDG_RUNTIME_DIR="/run/user/$(id -u)"
export WAYLAND_DISPLAY="${WAYLAND_DISPLAY:-wayland-1}"

# Define options for Rofi
options="Enable (5000K)\nEnable (4000K)\nEnable (3000K)\nCustom Temperature\nDisable"

# Show rofi menu
chosen=$(echo -e "$options" | rofi -dmenu -p "Hyprsunset")

case "$chosen" in
    "Enable (5000K)")
        hyprsunset -t 5000
        ;;
    "Enable (4000K)")
        hyprsunset -t 4000
        ;;
    "Enable (3000K)")
        hyprsunset -t 3000
        ;;
    "Custom Temperature")
        # Prompt user for a custom temperature using rofi's dmenu input
        temp=$(rofi -dmenu -p "Enter Temperature (e.g., 4500):")
        if [[ "$temp" =~ ^[0-9]+$ ]]; then
            hyprsunset -t "$temp"
        fi
        ;;
    "Disable")
        pkill hyprsunset
        ;;
esac
